"""GSTR-1 / GSTR-3B filing API: taxpayer OTP session + Save→File chain."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth import get_current_active_user, require_admin_user, require_manager_user, require_writer_user
from app.models.roles import is_admin_or_partner, is_manager_or_above, is_writer_or_above
from app.config import get_settings
from app.database import get_supabase
from app.filing import filing_store
from app.filing.gstr1_orchestrator import (
    map_sales_register_to_gstr1,
    serialize_gstr1_readiness,
)
from app.filing.gstr3b_filing_mapper import (
    apply_system_late_fee_to_save_body,
    normalize_gstr3b_save_body,
)
from app.filing.gstr3b_offset import (
    Gstr3bOffsetBuildError,
    build_gstr3b_offset_body,
    extract_offset_pair,
    offset_bodies_equal,
)
from app.filing.gstr3b_suggestions import (
    load_itc_oth_suggestion,
    load_osup_det_suggestion,
    load_rcm_suggestion,
    load_table4_suggestion,
)
from app.services.cumulative_fy_reconciliation import (
    assemble_cumulative_fy_reconciliation,
)
from app.services.filing_override_service import (
    FilingPolicy,
    FilingPolicyMode,
    FilingPolicyUpdate,
    consume_override_on_file,
    consume_override_on_file_sync,
    create_partner_override,
    get_firm_filing_policy,
    update_firm_filing_policy,
    verify_filing_governance_gate,
)
from app.services.pre_filing_validator import (
    compute_figures_digest,
    validate_gstr1_pre_filing,
    validate_gstr3b_pre_filing,
)
from app.filing.sandbox_filing_client import (
    FilingApiError,
    FilingAuthError,
    FilingClientError,
    FilingGstnError,
    build_save_body,
    get_filing_client,
    period_to_fp,
)
from app.integrations.gstn_error_mapper import gstn_http_exception, map_gstn_error

# File / EVC require a GSTN-confirmed Save (inner status_cd P) or later.
_EVC_OR_FILE_STATUSES = frozenset({"saved", "proceeded", "evc_pending"})
_PROCEED_STATUSES = frozenset({"saved"})
# GSTR-3B: Offset after confirmed Save; EVC/File after Offset complete.
_GSTR3B_OFFSET_STATUSES = frozenset({"saved"})
_GSTR3B_EVC_OR_FILE_STATUSES = frozenset({"offset_complete", "evc_pending"})
_GSTR3B_OFFSET_STATUS_ACTIONS = frozenset({"RETOFFSET", "OFFSET", "OFFLIAB"})
from app.services.firm_access import list_accessible_client_gstin_ids
from app.utils.audit import resolve_firm_id
from app.utils.crypto import decrypt_secret, encrypt_secret

router = APIRouter(redirect_slashes=False)
_log = logging.getLogger(__name__)


def require_gstr3b_filing_enabled() -> None:
    """Block GSTR-3B filing when the production feature flag is off."""
    if not get_settings().gstr3b_filing_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GSTR3B_FILING_DISABLED",
                "message": (
                    "GSTR-3B filing is not yet available. "
                    "Save → Offset → File has not been live-proven end-to-end."
                ),
            },
        )


# GSTR-3B filing router.
# Preparation, Table 4 reconciliation suggestions, and offline JSON exports are always enabled.
# Mutating ledger operations (Offset Liability and File) are strictly protected by require_gstr3b_filing_enabled.
gstr3b_router = APIRouter(
    redirect_slashes=False,
)


@router.get("/features")
def filing_features():
    """Public feature flags for filing UI entry points (no auth)."""
    return {
        "gstr1_filing_enabled": True,
        "gstr3b_preparation_enabled": True,
        "gstr3b_filing_enabled": get_settings().gstr3b_filing_enabled,
    }


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class _StripModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GenerateOtpBody(_StripModel):
    gstin: str
    username: str
    client_gstin_id: Optional[str] = None

    @field_validator("gstin", "username")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class VerifyOtpBody(GenerateOtpBody):
    otp: str

    @field_validator("otp")
    @classmethod
    def _otp(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class SessionIdBody(_StripModel):
    session_id: str

    @field_validator("session_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class SaveGstr1Body(_StripModel):
    client_gstin_id: str
    period: str
    session_id: Optional[str] = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    gt: float = 0.0
    cur_gt: float = 0.0
    patches: Optional[list[dict[str, Any]]] = None

    @field_validator("client_gstin_id", "period")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class ReadinessBody(_StripModel):
    """Sales Register → orchestrator readiness (no GSTN call)."""

    client_gstin_id: str
    period: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    patches: Optional[list[dict[str, Any]]] = None

    @field_validator("client_gstin_id", "period")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class ExportGstr3bJsonBody(_StripModel):
    client_gstin_id: str
    figures: Optional[dict[str, Any]] = None

    @field_validator("client_gstin_id")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class ExportGstr1JsonBody(_StripModel):
    client_gstin_id: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    gt: float = 0.0
    cur_gt: float = 0.0
    patches: Optional[list[dict[str, Any]]] = None

    @field_validator("client_gstin_id")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class StatusQuery(_StripModel):
    reference_id: str
    session_id: Optional[str] = None
    run_id: Optional[str] = None


class ProceedBody(_StripModel):
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    is_nil: str = "N"


class EvcOtpBody(_StripModel):
    pan: str
    session_id: Optional[str] = None
    run_id: Optional[str] = None

    @field_validator("pan")
    @classmethod
    def _pan(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 10:
            raise ValueError("pan must be 10 characters")
        return v


class FileGstr1Body(_StripModel):
    pan: str
    signing_method: str = "evc"
    otp: Optional[str] = None
    signature: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    # Optional override; otherwise built from GET summary on the run.
    file_body: Optional[dict[str, Any]] = None

    @field_validator("pan")
    @classmethod
    def _pan(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 10:
            raise ValueError("pan must be 10 characters")
        return v

    @field_validator("signing_method")
    @classmethod
    def _method(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("evc", "dsc"):
            raise ValueError("signing_method must be 'evc' or 'dsc'")
        return v

    @field_validator("otp", "signature")
    @classmethod
    def _strip_opt(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s if s else None

    @model_validator(mode="after")
    def _validate_signing_credentials(self) -> "FileGstr1Body":
        if self.signing_method == "evc" and not self.otp:
            raise ValueError("otp is required when signing_method is 'evc'")
        if self.signing_method == "dsc" and not self.signature:
            raise ValueError("signature is required when signing_method is 'dsc'")
        return self


class SaveGstr3bBody(_StripModel):
    """CA-confirmed GSTR-3B Save body (product does not invent Rule 42/43 figures)."""

    client_gstin_id: str
    period: str
    session_id: Optional[str] = None
    save_body: dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None

    @field_validator("client_gstin_id", "period")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class OffsetGstr3bBody(_StripModel):
    """Exact ``{pdcash, pditc}`` the CA confirmed — not an empty go-trigger."""

    client_gstin_id: str
    session_id: Optional[str] = None
    run_id: str
    pdcash: list[dict[str, Any]] = Field(default_factory=list)
    pditc: dict[str, Any] = Field(default_factory=dict)

    @field_validator("client_gstin_id", "run_id")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class EvcOtpGstr3bBody(EvcOtpBody):
    """Same shape as GSTR-1 EVC; client passes ``gstr=gstr-3b``."""


class FileGstr3bBody(_StripModel):
    pan: str
    signing_method: str = "evc"
    otp: Optional[str] = None
    signature: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    # Must include post-Offset ``tx_pmt``; when omitted, re-fetched from Get Details.
    file_body: Optional[dict[str, Any]] = None

    @field_validator("pan")
    @classmethod
    def _pan(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 10:
            raise ValueError("pan must be 10 characters")
        return v

    @field_validator("signing_method")
    @classmethod
    def _method(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("evc", "dsc"):
            raise ValueError("signing_method must be 'evc' or 'dsc'")
        return v

    @field_validator("otp", "signature")
    @classmethod
    def _strip_opt(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s if s else None

    @model_validator(mode="after")
    def _validate_signing_credentials(self) -> "FileGstr3bBody":
        if self.signing_method == "evc" and not self.otp:
            raise ValueError("otp is required when signing_method is 'evc'")
        if self.signing_method == "dsc" and not self.signature:
            raise ValueError("signature is required when signing_method is 'dsc'")
        return self

class PreFilingValidationGstr3bBody(_StripModel):
    client_gstin_id: str
    save_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("client_gstin_id")
    @classmethod
    def _cid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class PreFilingValidationGstr1Body(_StripModel):
    client_gstin_id: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    patches: Optional[list[dict[str, Any]]] = None

    @field_validator("client_gstin_id")
    @classmethod
    def _cid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class CreateOverrideBody(_StripModel):
    client_gstin_id: str
    period: str
    return_type: str = "gstr-3b"
    figures_digest: str
    validation_digest: Optional[str] = None
    justification: str
    violations_acknowledged: list[str] = Field(default_factory=list)

    @field_validator("client_gstin_id", "period", "figures_digest", "justification")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class CreateBatchBody(_StripModel):
    period: str
    client_gstin_ids: list[str] = Field(default_factory=list)
    return_type: str = "gstr-1"

    @field_validator("period")
    @classmethod
    def _period(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _firm_id(sb, user: dict) -> str:
    firm = resolve_firm_id(sb, user)
    if not firm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="could not resolve firm_id for user",
        )
    return firm


def _assert_client_access(sb, user: dict, client_gstin_id: str) -> dict[str, Any]:
    allowed = list_accessible_client_gstin_ids(sb, user)
    if client_gstin_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )
    res = (
        sb.table("client_gstins")
        .select("id, gstin")
        .eq("id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client_gstins row not found",
        )
    return res.data[0]


def _load_session_for_firm(sb, firm_id: str, session_id: str) -> dict[str, Any]:
    row = filing_store.get_session_by_id(sb, session_id)
    if not row or str(row.get("firm_id")) != firm_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="filing session not found",
        )
    if row.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"filing session is {row.get('status')}",
        )
    return row


def _resolve_token(
    sb,
    firm_id: str,
    *,
    session_id: str | None,
    gstin: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if session_id:
        row = _load_session_for_firm(sb, firm_id, session_id)
        return str(row["session_token"]), row
    if gstin:
        row = filing_store.get_active_session(sb, firm_id=firm_id, gstin=gstin)
        if row:
            return str(row["session_token"]), row
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="no active filing session; complete OTP verify first",
    )


def _map_client_error(exc: FilingClientError) -> HTTPException:
    err_cd = getattr(exc, "error_cd", None)
    clean_msg = map_gstn_error(exc, error_code=err_cd)
    if isinstance(exc, FilingAuthError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=clean_msg)
    if isinstance(exc, FilingGstnError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": clean_msg, "error_cd": exc.error_cd},
        )
    if isinstance(exc, FilingApiError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=clean_msg,
        )
    return gstn_http_exception(exc, error_code=err_cd)


def _raise_gstr3b_locked(exc: filing_store.Gstr3bPeriodLockedError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=filing_store.gstr3b_period_locked_detail(exc),
    ) from exc


def _gstr3b_offset_stale_detail(
    *,
    period: str,
    posted: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    return {
        "code": "GSTR3B_OFFSET_STALE",
        "message": (
            "Confirmed offset no longer matches current Get Details + ledger "
            "balance. Refresh the confirmation screen."
        ),
        "period": period,
        "posted": extract_offset_pair(posted),
        "current": extract_offset_pair(current),
    }


def _load_run_for_firm(sb, firm_id: str, run_id: str) -> dict[str, Any]:
    run = filing_store.get_run(sb, run_id)
    if not run or str(run.get("firm_id")) != firm_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="filing run not found",
        )
    return run


def _require_run_status(
    sb,
    firm_id: str,
    run_id: str | None,
    *,
    allowed: frozenset[str],
    action: str,
) -> dict[str, Any] | None:
    """Gate Proceed / EVC / File on a GSTN-confirmed Save lifecycle.

    When ``run_id`` is omitted the gate is skipped (API clients that track
    status out-of-band). The frontend always passes ``run_id``.
    """
    if not run_id:
        return None
    run = _load_run_for_firm(sb, firm_id, run_id)
    st = str(run.get("status") or "")
    if st not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"{action} requires run status in {sorted(allowed)}; "
                    f"current={st!r}"
                ),
                "run_id": run_id,
                "run_status": st,
            },
        )
    return run


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------


@router.post("/session/otp/generate")
def generate_otp(
    body: GenerateOtpBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to generate filing session OTP",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    if body.client_gstin_id:
        _assert_client_access(sb, current_user, body.client_gstin_id)
    else:
        cg_res = (
            sb.table("client_gstins")
            .select("id")
            .eq("firm_owner_id", firm_id)
            .eq("gstin", body.gstin.strip().upper())
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not cg_res.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Client GSTIN not found or not accessible",
            )
        _assert_client_access(sb, current_user, str(cg_res.data[0]["id"]))
    try:
        with get_filing_client() as client:
            envelope = client.generate_otp(username=body.username, gstin=body.gstin)
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    return {
        "message": "OTP sent",
        "transaction_id": envelope.get("transaction_id"),
        "status_cd": (envelope.get("data") or {}).get("status_cd"),
    }


@router.post("/session/otp/verify")
def verify_otp(
    body: VerifyOtpBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to verify filing session OTP",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = None
    if body.client_gstin_id:
        client_row = _assert_client_access(sb, current_user, body.client_gstin_id)
    else:
        cg_res = (
            sb.table("client_gstins")
            .select("id, gstin")
            .eq("firm_owner_id", firm_id)
            .eq("gstin", body.gstin.strip().upper())
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not cg_res.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Client GSTIN not found or not accessible",
            )
        client_row = _assert_client_access(sb, current_user, str(cg_res.data[0]["id"]))
        body.client_gstin_id = str(client_row["id"])
    try:
        with get_filing_client() as client:
            session = client.verify_otp(
                username=body.username,
                gstin=body.gstin,
                otp=body.otp,
            )
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc

    row = filing_store.create_session(
        sb,
        firm_id=firm_id,
        gstin=body.gstin,
        username=body.username,
        session=session,
        client_gstin_id=body.client_gstin_id,
    )
    # Keep legacy client_gstins token in sync when a client row is known.
    if client_row is not None:
        try:
            sb.table("client_gstins").update(
                {
                    "gstn_access_token": encrypt_secret(session.access_token),
                    "gstn_token_expiry": session.token_expires_at.isoformat(),
                }
            ).eq("id", client_row["id"]).execute()
        except Exception:
            _log.exception("failed to mirror token onto client_gstins")

    return {
        "session_id": row["id"],
        "gstin": row["gstin"],
        "token_expires_at": row["token_expires_at"],
        "session_expires_at": row.get("session_expires_at"),
        "status": row["status"],
    }


@router.post("/session/refresh")
def refresh_session(
    body: SessionIdBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to refresh filing session",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    row = _load_session_for_firm(sb, firm_id, body.session_id)
    try:
        with get_filing_client() as client:
            session = client.refresh_session(str(row["session_token"]))
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    updated = filing_store.update_session_token(sb, body.session_id, session)
    return {
        "session_id": body.session_id,
        "token_expires_at": updated.get("token_expires_at"),
        "status": "active",
    }


@router.post("/session/logout")
def logout_session(
    body: SessionIdBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Logout is best-effort; local row is always marked logged_out."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to log out filing session",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    row = filing_store.get_session_by_id(sb, body.session_id)
    if not row or str(row.get("firm_id")) != firm_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="filing session not found",
        )
    sandbox_ok = False
    sandbox_error = None
    if row.get("session_token") and row.get("status") == "active":
        try:
            with get_filing_client() as client:
                result = client.logout(str(row["session_token"]))
            sandbox_ok = result.ok
            if not result.ok:
                sandbox_error = {
                    "error_cd": result.error_cd,
                    "message": map_gstn_error(result.error_message, error_code=result.error_cd),
                }
        except Exception as exc:
            _log.warning("logout unexpected error (non-fatal): %s", exc)
            sandbox_error = {"message": map_gstn_error(exc)}

    filing_store.mark_session_logged_out(sb, body.session_id)
    return {
        "session_id": body.session_id,
        "status": "logged_out",
        "sandbox_logout_ok": sandbox_ok,
        "sandbox_error": sandbox_error,
    }


# ---------------------------------------------------------------------------
# GSTR-1 filing chain
# ---------------------------------------------------------------------------


def _assert_period_yyyy_mm(period: str) -> str:
    p = (period or "").strip()
    if len(p) != 7 or p[4] != "-" or not (p[:4].isdigit() and p[5:].isdigit()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"period must be YYYY-MM; got {period!r}",
        )
    return p


def _parse_sr_upload(file_content: bytes, filename: str) -> list[dict[str, Any]]:
    from app.parsers.sales_register_parser import ParseError, parse_sales_register

    try:
        sr_result = parse_sales_register(file_content, filename or "upload.xlsx")
    except ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "sales_register_parse_failed", "message": str(exc)},
        ) from exc
    if not sr_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "sales_register_parse_failed",
                "errors": sr_result.get("errors", []),
            },
        )
    records = sr_result.get("records") or []
    if not isinstance(records, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="sales register produced no records list",
        )
    return [r for r in records if isinstance(r, dict)]


def _parse_patches(raw: Any) -> list[dict[str, Any]]:
    """Safe parser for patch JSON string, dict, or list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, dict)]
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [p for p in parsed if isinstance(p, dict)]
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            return []
    return []


def _apply_record_patches(
    records: list[dict[str, Any]],
    patches: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """In-memory patch application on Sales Register records before GSTR-1 mapping.

    Allows immediate in-browser quick-fixes for typos, missing POS, or
    unclassified invoice types without forcing full Excel re-upload.
    """
    if not patches or not records:
        return records

    by_row: dict[int, dict[str, Any]] = {}
    by_inv: dict[str, dict[str, Any]] = {}
    for p in patches:
        rn = p.get("row_number")
        if rn is not None:
            try:
                by_row[int(rn)] = p
            except (ValueError, TypeError):
                pass
        inv = str(p.get("invoice_number") or p.get("inum") or "").strip().lower()
        if inv:
            by_inv[inv] = p

    patched: list[dict[str, Any]] = []
    for rec in records:
        r = dict(rec)
        patch = None
        rn = r.get("row_number")
        if rn is not None:
            try:
                if int(rn) in by_row:
                    patch = by_row[int(rn)]
            except (ValueError, TypeError):
                pass
        if not patch:
            raw_inv = str(
                r.get("invoice_number_raw") or r.get("invoice_number") or ""
            ).strip().lower()
            if raw_inv and raw_inv in by_inv:
                patch = by_inv[raw_inv]

        if patch:
            if "gstin" in patch and patch["gstin"]:
                clean_gstin = str(patch["gstin"]).strip().upper()
                r["gstin"] = clean_gstin
                r["gstin_valid"] = True
                r["gstin_format_ok"] = True
            if "place_of_supply" in patch and patch["place_of_supply"]:
                r["place_of_supply"] = str(patch["place_of_supply"]).strip()
            if "invoice_type" in patch and patch["invoice_type"]:
                itype = str(patch["invoice_type"]).strip().upper()
                r["invoice_type"] = itype
                r["invoice_type_raw"] = itype
            if "note_type" in patch and patch["note_type"]:
                ntype = str(patch["note_type"]).strip().upper()
                r["note_type"] = ntype
                r["note_type_raw"] = ntype
            if "export_type" in patch and patch["export_type"]:
                etype = str(patch["export_type"]).strip().upper()
                r["export_type"] = etype
                r["export_type_raw"] = etype
            if "tax_rate" in patch and patch["tax_rate"] is not None:
                try:
                    r["tax_rate"] = float(patch["tax_rate"])
                except (ValueError, TypeError):
                    pass
        patched.append(r)
    return patched


def _readiness_payload_for_client(
    *,
    sb,
    current_user: dict,
    client_gstin_id: str,
    period: str,
    records: list[dict[str, Any]],
    patches: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], Any, str]:
    client_row = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = str(client_row["gstin"]).strip().upper()
    effective_records = _apply_record_patches(records, patches)
    mapped = map_sales_register_to_gstr1(
        effective_records,
        filer_state=gstin[:2],
        filing_period=period,
    )
    payload = serialize_gstr1_readiness(mapped)
    payload["gstin"] = gstin
    payload["client_gstin_id"] = client_gstin_id
    payload["record_count"] = len(records)
    payload["patches_applied"] = len(patches) if patches else 0
    return payload, mapped, gstin


def _execute_save(
    *,
    sb,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    session_id: str | None,
    records: list[dict[str, Any]],
    gt: float,
    cur_gt: float,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if user is not None:
        role = str(user.get("role") or "").strip().lower()
        if not is_writer_or_above(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Write access required to save return",
            )
    token, session_row = _resolve_token(
        sb, firm_id, session_id=session_id, gstin=gstin,
    )
    mapped = map_sales_register_to_gstr1(
        records,
        filer_state=gstin[:2],
        filing_period=period,
    )
    save_body = build_save_body(
        mapped.save_payload,
        gstin=gstin,
        period=period,
        gt=gt,
        cur_gt=cur_gt,
    )

    # Phase 2 Pre-filing validation & governance gate
    readiness_data = serialize_gstr1_readiness(mapped)
    val_result = validate_gstr1_pre_filing(
        sb,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=period,
        mapped_readiness=readiness_data,
        save_payload=save_body,
    )
    effective_user = user or {"id": firm_id, "role": "admin"}
    verify_filing_governance_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=period,
        return_type="gstr-1",
        validation_result=val_result,
        user=effective_user,
    )

    run = filing_store.create_run(
        sb,
        firm_id=firm_id,
        gstin=gstin,
        period=period,
        filing_session_id=str(session_row["id"]),
        client_gstin_id=client_gstin_id,
        save_payload=save_body,
        status="draft",
    )
    try:
        with get_filing_client() as client:
            result = client.save_gstr1(
                token, period=period, save_body=save_body,
            )
    except FilingClientError as exc:
        err_cd = getattr(exc, "error_cd", None)
        filing_store.mark_run_failed(
            sb,
            run["id"],
            error_code=err_cd,
            error_message=map_gstn_error(exc, error_code=err_cd),
            raw_response=getattr(exc, "envelope", None),
        )
        raise _map_client_error(exc) from exc

    filing_store.update_run(
        sb,
        run["id"],
        status="save_pending",
        reference_id=result.reference_id,
        raw_response=result.envelope,
        clear_error=True,
    )
    readiness = serialize_gstr1_readiness(mapped)
    return {
        "run_id": run["id"],
        "reference_id": result.reference_id,
        # Outer Sandbox acceptance only — poll /status until inner status_cd P.
        "status": "save_pending",
        "filing_readiness": readiness["filing_readiness"],
        "pending_review_count": readiness["pending_review_count"],
        "external_input_tables": readiness["external_input_tables"],
        "save_payload_keys": readiness["save_section_keys"],
    }


@router.post("/gstr-1/{period}/readiness")
def gstr1_readiness(
    period: str,
    body: ReadinessBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Orchestrator readiness for the CA pre-Save review UI (no GSTN call).

    POST (not GET): Sales Register ``records`` must travel in the body — same
    payload shape as Save. Prefer ``/readiness-upload`` for .xlsx/.csv uploads.
    """
    period = _assert_period_yyyy_mm(period)
    if body.period != period:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period path and body must match",
        )
    sb = get_supabase()
    _firm_id(sb, current_user)
    payload, _, _ = _readiness_payload_for_client(
        sb=sb,
        current_user=current_user,
        client_gstin_id=body.client_gstin_id,
        period=period,
        records=body.records,
        patches=body.patches,
    )
    return payload


@router.post("/gstr-1/{period}/readiness-upload")
async def gstr1_readiness_upload(
    period: str,
    client_gstin_id: str = Form(...),
    sales_register_file: UploadFile = File(...),
    patches: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_active_user),
):
    """Parse an uploaded Sales Register and return filing readiness (no GSTN)."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    content = await sales_register_file.read()
    records = _parse_sr_upload(
        content, sales_register_file.filename or "upload.xlsx",
    )
    parsed_patches = _parse_patches(patches)
    payload, _, _ = _readiness_payload_for_client(
        sb=sb,
        current_user=current_user,
        client_gstin_id=client_gstin_id.strip(),
        period=period,
        records=records,
        patches=parsed_patches,
    )
    payload["source_filename"] = sales_register_file.filename
    return payload


@router.post("/gstr-1/{period}/pre-filing-validation")
def gstr1_pre_filing_validation(
    period: str,
    body: PreFilingValidationGstr1Body,
    current_user: dict = Depends(get_current_active_user),
):
    """Server-side pre-filing validation for GSTR-1 (readiness, mandatory sections, HSN/Doc gaps)."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()

    payload, mapped, _ = _readiness_payload_for_client(
        sb=sb,
        current_user=current_user,
        client_gstin_id=body.client_gstin_id.strip(),
        period=period,
        records=body.records,
        patches=body.patches,
    )
    save_body = build_save_body(
        mapped.save_payload,
        gstin=gstin,
        period=period,
        gt=0.0,
        cur_gt=0.0,
    )
    result = validate_gstr1_pre_filing(
        sb,
        client_gstin_id=body.client_gstin_id.strip(),
        gstin=gstin,
        period=period,
        mapped_readiness=payload,
        save_payload=save_body,
    )
    policy = get_firm_filing_policy(sb, firm_id)
    res_dict = result.to_dict()
    res_dict["policy_mode"] = policy.mode.value
    return res_dict


@router.post("/gstr-1/{period}/save")
def save_gstr1(
    period: str,
    body: SaveGstr1Body,
    current_user: dict = Depends(get_current_active_user),
):
    period = _assert_period_yyyy_mm(period)
    if body.period != period:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period path and body must match",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id)
    gstin = str(client_row["gstin"]).strip().upper()
    effective_records = _apply_record_patches(body.records, body.patches)
    return _execute_save(
        sb=sb,
        firm_id=firm_id,
        client_gstin_id=body.client_gstin_id,
        gstin=gstin,
        period=period,
        session_id=body.session_id,
        records=effective_records,
        gt=body.gt,
        cur_gt=body.cur_gt,
        user=current_user,
    )


@router.post("/gstr-1/{period}/save-upload")
async def save_gstr1_upload(
    period: str,
    client_gstin_id: str = Form(...),
    sales_register_file: UploadFile = File(...),
    patches: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    gt: float = Form(0.0),
    cur_gt: float = Form(0.0),
    current_user: dict = Depends(get_current_active_user),
):
    """Parse uploaded SR, map via orchestrator, Save to GSTN → ``save_pending``."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    content = await sales_register_file.read()
    records = _parse_sr_upload(
        content, sales_register_file.filename or "upload.xlsx",
    )
    effective_records = _apply_record_patches(records, _parse_patches(patches))
    return _execute_save(
        sb=sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id.strip(),
        gstin=gstin,
        period=period,
        session_id=(session_id.strip() if session_id else None),
        records=effective_records,
        gt=gt,
        cur_gt=cur_gt,
        user=current_user,
    )


@router.post("/gstr-1/{period}/export-json")
def gstr1_export_json(
    period: str,
    body: ExportGstr1JsonBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate official GSTN GSTR-1 offline JSON file from records."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    state_code = gstin[:2]
    fp = period_to_fp(period)

    if not body.records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No records provided to export",
        )

    effective_records = _apply_record_patches(body.records, body.patches)
    map_res = map_sales_register_to_gstr1(
        effective_records, filer_state=state_code, filing_period=period,
    )
    save_body = build_save_body(
        map_res.save_payload, gstin=gstin, period=period, gt=body.gt, cur_gt=body.cur_gt,
    )
    filename = f"gstr1_{gstin}_{fp}.json"
    return {
        "filename": filename,
        "gstin": gstin,
        "fp": fp,
        "record_count": len(effective_records),
        "summary": {
            "b2b": len(map_res.save_payload.get("b2b", [])),
            "b2cl": len(map_res.save_payload.get("b2cl", [])),
            "b2cs": len(map_res.save_payload.get("b2cs", [])),
            "cdnr": len(map_res.save_payload.get("cdnr", [])),
            "cdnur": len(map_res.save_payload.get("cdnur", [])),
            "exp": len(map_res.save_payload.get("exp", [])),
            "hsn": len(map_res.save_payload.get("hsn", {}).get("data", [])),
            "nil": len(map_res.save_payload.get("nil", {}).get("inv", [])),
        },
        "payload": save_body,
    }


@router.post("/gstr-1/{period}/export-json-upload")
async def gstr1_export_json_upload(
    period: str,
    client_gstin_id: str = Form(...),
    sales_register_file: UploadFile = File(...),
    patches: Optional[str] = Form(None),
    gt: float = Form(0.0),
    cur_gt: float = Form(0.0),
    current_user: dict = Depends(get_current_active_user),
):
    """Parse uploaded Sales Register and generate official GSTN GSTR-1 offline JSON file."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    state_code = gstin[:2]
    fp = period_to_fp(period)

    content = await sales_register_file.read()
    records = _parse_sr_upload(content, sales_register_file.filename or "upload.xlsx")
    if not records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid sales register rows found in uploaded file",
        )

    effective_records = _apply_record_patches(records, _parse_patches(patches))
    map_res = map_sales_register_to_gstr1(
        effective_records, filer_state=state_code, filing_period=period,
    )
    save_body = build_save_body(
        map_res.save_payload, gstin=gstin, period=period, gt=gt, cur_gt=cur_gt,
    )
    filename = f"gstr1_{gstin}_{fp}.json"
    return {
        "filename": filename,
        "gstin": gstin,
        "fp": fp,
        "record_count": len(effective_records),
        "source_filename": sales_register_file.filename,
        "summary": {
            "b2b": len(map_res.save_payload.get("b2b", [])),
            "b2cl": len(map_res.save_payload.get("b2cl", [])),
            "b2cs": len(map_res.save_payload.get("b2cs", [])),
            "cdnr": len(map_res.save_payload.get("cdnr", [])),
            "cdnur": len(map_res.save_payload.get("cdnur", [])),
            "exp": len(map_res.save_payload.get("exp", [])),
            "hsn": len(map_res.save_payload.get("hsn", {}).get("data", [])),
            "nil": len(map_res.save_payload.get("nil", {}).get("inv", [])),
        },
        "payload": save_body,
    }


@router.get("/gstr-1/{period}/status")
def return_status(
    period: str,
    reference_id: str,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    token, _ = _resolve_token(sb, firm_id, session_id=session_id)
    try:
        with get_filing_client() as client:
            result = client.get_return_status(
                token, period=period, reference_id=reference_id,
            )
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc

    info = result.return_status
    run_status = None
    if run_id and info is not None:
        # Only advance Save lifecycle from this poll when the action is SAVE
        # (or unset — Save is the common case). Proceed polls share this route.
        action = (info.action or "SAVE").upper()
        if action == "SAVE":
            updated = filing_store.apply_save_status_to_run(
                sb,
                run_id,
                return_status=info,
                envelope=result.envelope,
            )
            run_status = updated.get("status")
        else:
            filing_store.update_run(
                sb, run_id, raw_response=result.envelope,
            )

    return {
        "period": period,
        "reference_id": reference_id,
        "data": result.data,
        # Prefer nested GSTN status_cd; outer Sandbox "1" is not success.
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
        "gstn_success": bool(info and info.is_success),
        "gstn_failed": bool(info and info.is_failed),
        "run_status": run_status,
        "error_cd": info.error_cd if info else None,
        "error_message": (
            map_gstn_error(info.error_message, error_code=info.error_cd)
            if (info and info.error_message)
            else None
        ),
    }


@router.post("/gstr-1/{period}/proceed")
def proceed_to_file(
    period: str,
    body: ProceedBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to proceed with return filing",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _require_run_status(
        sb, firm_id, body.run_id, allowed=_PROCEED_STATUSES, action="Proceed",
    )
    token, _ = _resolve_token(sb, firm_id, session_id=body.session_id)
    try:
        with get_filing_client() as client:
            result = client.proceed_to_file(
                token, period=period, is_nil=body.is_nil,
            )
    except FilingClientError as exc:
        if body.run_id:
            err_cd = getattr(exc, "error_cd", None)
            filing_store.mark_run_failed(
                sb,
                body.run_id,
                error_code=err_cd,
                error_message=map_gstn_error(exc, error_code=err_cd),
                raw_response=getattr(exc, "envelope", None),
            )
        raise _map_client_error(exc) from exc
    if body.run_id:
        filing_store.update_run(
            sb,
            body.run_id,
            status="proceeded",
            reference_id=result.reference_id,
            raw_response=result.envelope,
            clear_error=True,
        )
    # Client already raised on nested ER/PE via _raise_if_inner_gstn_failure.
    info = result.return_status
    return {
        "period": period,
        "reference_id": result.reference_id,
        "status": "proceeded",
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
        "error_cd": info.error_cd if info else None,
        "error_message": (
            map_gstn_error(info.error_message, error_code=info.error_cd)
            if (info and info.error_message)
            else None
        ),
    }


@router.get("/gstr-1/{period}/summary")
def get_summary(
    period: str,
    session_id: Optional[str] = None,
    summary_type: str = "long",
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    token, _ = _resolve_token(sb, firm_id, session_id=session_id)
    try:
        with get_filing_client() as client:
            result = client.get_gstr1_summary(
                token, period=period, summary_type=summary_type,
            )
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    # Nested ER/PE already raised in the client.
    info = result.return_status
    return {
        "period": period,
        "summary": result.data,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
    }


@router.post("/gstr-1/{period}/evc-otp")
def generate_evc_otp(
    period: str,
    body: EvcOtpBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to generate EVC OTP",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    run = _require_run_status(
        sb,
        firm_id,
        body.run_id,
        allowed=_EVC_OR_FILE_STATUSES,
        action="EVC OTP",
    )
    if run and run.get("client_gstin_id"):
        _assert_client_access(sb, current_user, str(run["client_gstin_id"]))
    token, _ = _resolve_token(sb, firm_id, session_id=body.session_id)
    try:
        with get_filing_client() as client:
            result = client.generate_evc_otp(token, pan=body.pan)
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    if body.run_id:
        filing_store.update_run(
            sb, body.run_id, status="evc_pending", clear_error=True,
        )
    info = result.return_status
    data = result.data if isinstance(result.data, dict) else {}
    return {
        "period": period,
        "message": "EVC OTP sent to authorized signatory",
        "status_cd": data.get("status_cd"),
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
    }


@router.post("/gstr-1/{period}/file")
def file_gstr1(
    period: str,
    body: FileGstr1Body,
    current_user: dict = Depends(require_admin_user),
):
    """File GSTR-1. EVC OTP is accepted in JSON body only (never as query)."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _require_run_status(
        sb,
        firm_id,
        body.run_id,
        allowed=_EVC_OR_FILE_STATUSES,
        action="File",
    )
    token, _ = _resolve_token(sb, firm_id, session_id=body.session_id)

    governance_override: Optional[Any] = None
    # Enforce Pre-Filing Governance Gate before final Filing
    if body.run_id:
        run_data = _load_run_for_firm(sb, firm_id, body.run_id)
        client_gid = str(run_data.get("client_gstin_id") or "")
        run_gstin = str(run_data.get("gstin") or "").strip().upper()
        pol = get_firm_filing_policy(sb, firm_id)
        if pol.mode != FilingPolicyMode.ADVISORY and isinstance(run_data.get("save_payload"), dict):
            val_res = validate_gstr1_pre_filing(
                sb,
                client_gstin_id=client_gid,
                gstin=run_gstin,
                period=period,
                save_body=run_data["save_payload"],
            )
            governance_override = verify_filing_governance_gate(
                sb,
                firm_id=firm_id,
                client_gstin_id=client_gid,
                gstin=run_gstin,
                period=period,
                return_type="gstr-1",
                validation_result=val_res,
                user=current_user,
            )

    file_body = body.file_body
    if file_body is None:
        # Pull summary for sec_sum / chksum required by File.
        try:
            with get_filing_client() as client:
                summary = client.get_gstr1_summary(token, period=period)
        except FilingClientError as exc:
            raise _map_client_error(exc) from exc
        sdata = summary.data
        file_body = {
            "gstin": sdata.get("gstin"),
            "ret_period": sdata.get("ret_period") or period_to_fp(period),
            "newSumFlag": sdata.get("newSumFlag", True),
            "sec_sum": sdata.get("sec_sum") or [],
            "chksum": sdata.get("chksum"),
        }

    try:
        with get_filing_client() as client:
            result = client.file_gstr1(
                token,
                period=period,
                pan=body.pan,
                otp=body.otp,
                signature=body.signature,
                signing_method=body.signing_method,
                file_body=file_body,
            )
    except FilingClientError as exc:
        if body.run_id:
            err_cd = getattr(exc, "error_cd", None)
            filing_store.mark_run_failed(
                sb,
                body.run_id,
                error_code=err_cd,
                error_message=map_gstn_error(exc, error_code=err_cd),
                raw_response=getattr(exc, "envelope", None),
            )
        raise _map_client_error(exc) from exc

    if body.run_id:
        try:
            filing_store.update_run(
                sb,
                body.run_id,
                status="filed",
                ack_number=result.ack_number,
                raw_response=result.envelope,
                clear_error=True,
            )
        except Exception as db_err:
            _log.error("Failed to update run status to filed in database after GSTN submission: %s", db_err, exc_info=True)
        try:
            run_data = _load_run_for_firm(sb, firm_id, body.run_id)
            client_gid = str(run_data.get("client_gstin_id") or "")
            consume_override_on_file_sync(
                sb,
                firm_id=firm_id,
                client_gstin_id=client_gid,
                period=period,
                return_type="gstr-1",
                run_id=body.run_id,
                user=current_user,
                override_id=governance_override.id if governance_override else None,
            )
        except Exception:
            _log.warning("Failed to consume override on GSTR-1 file", exc_info=True)
    info = result.return_status
    return {
        "period": period,
        "status": "filed",
        "ack_number": result.ack_number,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
    }


# ---------------------------------------------------------------------------
# GSTR-3B filing chain (no Proceed — Offset replaces it)
# ---------------------------------------------------------------------------


def _fetch_gstr3b_details_and_ledger(client, token: str, *, period: str):
    details = client.get_gstr3b_details(token, period=period)
    ledger = client.get_ledger_balance(token, period=period)
    return details, ledger


def _compute_current_offset_body(client, token: str, *, period: str) -> dict[str, Any]:
    details, ledger = _fetch_gstr3b_details_and_ledger(client, token, period=period)
    try:
        return build_gstr3b_offset_body(details.data, ledger.data)
    except Gstr3bOffsetBuildError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "GSTR3B_OFFSET_BUILD_FAILED", "message": str(exc)},
        ) from exc


@gstr3b_router.get("/gstr-3b/{period}/details")
def get_gstr3b_details(
    period: str,
    client_gstin_id: str,
    session_id: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    token, _ = _resolve_token(sb, firm_id, session_id=session_id, gstin=gstin)
    try:
        with get_filing_client() as client:
            result = client.get_gstr3b_details(token, period=period)
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    info = result.return_status
    return {
        "period": period,
        "gstin": gstin,
        "details": result.data,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
    }


@gstr3b_router.get("/gstr-3b/{period}/raw-details")
def get_gstr3b_raw_details(
    period: str,
    client_gstin_id: str,
    session_id: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    token, _ = _resolve_token(sb, firm_id, session_id=session_id, gstin=gstin)
    try:
        with get_filing_client() as client:
            result = client.get_gstr3b_details(token, period=period)
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    return result.envelope



@gstr3b_router.get("/gstr-3b/{period}/ledger-balance")
def get_gstr3b_ledger_balance(
    period: str,
    client_gstin_id: str,
    session_id: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    token, _ = _resolve_token(sb, firm_id, session_id=session_id, gstin=gstin)
    try:
        with get_filing_client() as client:
            result = client.get_ledger_balance(token, period=period)
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    info = result.return_status
    return {
        "period": period,
        "gstin": gstin,
        "ledger": result.data,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
    }


@gstr3b_router.get("/gstr-3b/{period}/suggestions/osup-det")
def gstr3b_suggest_osup_det(
    period: str,
    client_gstin_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Optional GSTR-1 Table 3.1(a) draft for ``osup_det`` — never auto-applied."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id.strip())
    return load_osup_det_suggestion(
        sb, client_gstin_id=client_gstin_id.strip(), period=period,
    )


@gstr3b_router.get("/gstr-3b/{period}/suggestions/itc-oth")
def gstr3b_suggest_itc_oth(
    period: str,
    client_gstin_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Optional GSTR-2B available-ITC draft for ``itc_avl`` OTH — never auto-applied."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id.strip())
    return load_itc_oth_suggestion(
        sb, client_gstin_id=client_gstin_id.strip(), period=period,
    )


@gstr3b_router.get("/gstr-3b/{period}/suggestions/table4")
def gstr3b_suggest_table4(
    period: str,
    client_gstin_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Auto-compile GSTR-3B Table 4 from the latest purchase reconcile run."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id.strip())
    return load_table4_suggestion(
        sb, client_gstin_id=client_gstin_id.strip(), period=period,
    )


@gstr3b_router.get("/gstr-3b/{period}/suggestions/rcm")
def gstr3b_suggest_rcm(
    period: str,
    client_gstin_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Auto-detect reverse charge inward supplies from Purchase Register for Table 3.1(d)."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id.strip())
    return load_rcm_suggestion(
        sb, client_gstin_id=client_gstin_id.strip(), period=period,
    )


@gstr3b_router.post("/gstr-3b/{period}/pre-filing-validation")
def gstr3b_pre_filing_validation(
    period: str,
    body: PreFilingValidationGstr3bBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Server-side pre-filing validation for GSTR-3B (Rules 88C/88D, reconciliation status, RCM)."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()

    policy = get_firm_filing_policy(sb, firm_id)
    result = validate_gstr3b_pre_filing(
        sb,
        client_gstin_id=body.client_gstin_id.strip(),
        gstin=gstin,
        period=period,
        save_body=body.save_body,
        require_final_reconciliation=policy.require_final_reconciliation,
        rule_88c_pct_threshold=policy.rule_88c_pct_threshold,
        rule_88c_amount_threshold=policy.rule_88c_amount_threshold,
        rule_88d_pct_threshold=policy.rule_88d_pct_threshold,
        rule_88d_amount_threshold=policy.rule_88d_amount_threshold,
    )
    res_dict = result.to_dict()
    res_dict["policy_mode"] = policy.mode.value
    return res_dict


@gstr3b_router.post("/gstr-3b/{period}/export-json")
def gstr3b_export_json(
    period: str,
    body: ExportGstr3bJsonBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate official GSTN GSTR-3B offline JSON file for direct portal upload."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    ret_period = period_to_fp(period)

    save_body = dict(body.figures) if isinstance(body.figures, dict) else {}
    save_body["gstin"] = gstin
    save_body["ret_period"] = ret_period

    normalized = normalize_gstr3b_save_body(save_body)
    filename = f"gstr3b_{gstin}_{ret_period}.json"
    sup = normalized.get("sup_details", {})
    osup_det = sup.get("osup_det", {}) if isinstance(sup, dict) else {}
    total_tax = round(
        float(osup_det.get("iamt") or 0.0)
        + float(osup_det.get("camt") or 0.0)
        + float(osup_det.get("samt") or 0.0)
        + float(osup_det.get("csamt") or 0.0),
        2,
    )
    return {
        "filename": filename,
        "gstin": gstin,
        "ret_period": ret_period,
        "payload": normalized,
        "summary": {
            "total_tax_liability": total_tax,
        },
    }


@gstr3b_router.get("/gstr-3b/{period}/offset-preview")
def gstr3b_offset_preview(
    period: str,
    client_gstin_id: str,
    session_id: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    """Authoritative ``{pdcash, pditc}`` for the confirmation UI.

    Uses the same :func:`build_gstr3b_offset_body` helper as the Offset
    stale-check — what the CA sees is what Offset will accept.
    """
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    token, _ = _resolve_token(sb, firm_id, session_id=session_id, gstin=gstin)
    try:
        with get_filing_client() as client:
            details, ledger = _fetch_gstr3b_details_and_ledger(
                client, token, period=period,
            )
            try:
                offset_body = build_gstr3b_offset_body(details.data, ledger.data)
            except Gstr3bOffsetBuildError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "GSTR3B_OFFSET_BUILD_FAILED",
                        "message": str(exc),
                    },
                ) from exc
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    return {
        "period": period,
        "gstin": gstin,
        "pdcash": offset_body["pdcash"],
        "pditc": offset_body["pditc"],
        "details": details.data,
        "ledger": ledger.data,
    }


@gstr3b_router.post("/gstr-3b/{period}/save")
def save_gstr3b(
    period: str,
    body: SaveGstr3bBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to save GSTR-3B return",
        )
    period = _assert_period_yyyy_mm(period)
    if body.period != period:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period path and body must match",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id)
    gstin = str(client_row["gstin"]).strip().upper()

    try:
        filing_store.assert_gstr3b_save_allowed(sb, gstin=gstin, period=period)
    except filing_store.Gstr3bPeriodLockedError as exc:
        _raise_gstr3b_locked(exc)

    token, session_row = _resolve_token(
        sb, firm_id, session_id=body.session_id, gstin=gstin,
    )
    save_body = dict(body.save_body)
    save_body.setdefault("gstin", gstin)
    save_body.setdefault("ret_period", period_to_fp(period))

    # Phase 2: Pre-filing statutory validation & governance gate
    policy = get_firm_filing_policy(sb, firm_id)
    val_result = validate_gstr3b_pre_filing(
        sb,
        client_gstin_id=body.client_gstin_id,
        gstin=gstin,
        period=period,
        save_body=save_body,
        require_final_reconciliation=policy.require_final_reconciliation,
        rule_88c_pct_threshold=policy.rule_88c_pct_threshold,
        rule_88c_amount_threshold=policy.rule_88c_amount_threshold,
        rule_88d_pct_threshold=policy.rule_88d_pct_threshold,
        rule_88d_amount_threshold=policy.rule_88d_amount_threshold,
    )
    verify_filing_governance_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=body.client_gstin_id,
        gstin=gstin,
        period=period,
        return_type="gstr-3b",
        validation_result=val_result,
        user=current_user,
    )

    run = None
    if body.run_id:
        run = _load_run_for_firm(sb, firm_id, body.run_id)
        filing_store.update_run(
            sb, body.run_id, save_payload=save_body, clear_error=True,
        )
        run_id = body.run_id
    else:
        run = filing_store.create_run(
            sb,
            firm_id=firm_id,
            gstin=gstin,
            period=period,
            return_type=filing_store.RETURN_TYPE_GSTR3B,
            filing_session_id=str(session_row["id"]),
            client_gstin_id=body.client_gstin_id,
            save_payload=save_body,
            status="draft",
        )
        run_id = run["id"]

    try:
        with get_filing_client() as client:
            try:
                details_res = client.get_gstr3b_details(token, period=period)
                details_data = details_res.data
                _log.info(
                    "[SAVE_GSTR3B_DEBUG] raw get_gstr3b_details envelope: %s",
                    json.dumps(details_res.envelope, default=str),
                )
            except Exception as exc:
                _log.warning("[SAVE_GSTR3B_DEBUG] Could not fetch GSTR-3B details before save: %s", exc, exc_info=True)
                details_data = None

            save_body = apply_system_late_fee_to_save_body(save_body, details_data)
            _log.info(
                "[SAVE_GSTR3B_DEBUG] raw save_body sent to Sandbox: %s",
                json.dumps(save_body, default=str),
            )
            filing_store.update_run(
                sb, run_id, save_payload=save_body, clear_error=True,
            )

            result = client.save_gstr3b(
                token, period=period, save_body=save_body, sb=sb,
            )
    except filing_store.Gstr3bPeriodLockedError as exc:
        _raise_gstr3b_locked(exc)
    except FilingClientError as exc:
        err_cd = getattr(exc, "error_cd", None)
        filing_store.mark_run_failed(
            sb,
            run_id,
            error_code=err_cd,
            error_message=map_gstn_error(exc, error_code=err_cd),
            raw_response=getattr(exc, "envelope", None),
        )
        raise _map_client_error(exc) from exc

    filing_store.update_run(
        sb,
        run_id,
        status="save_pending",
        reference_id=result.reference_id,
        raw_response=result.envelope,
        clear_error=True,
    )
    info = result.return_status
    return {
        "run_id": run_id,
        "reference_id": result.reference_id,
        "status": "save_pending",
        "period": period,
        "outer_status_cd": info.outer_status_cd if info else None,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "message": "Save accepted for processing; poll status until inner P",
    }


@gstr3b_router.get("/gstr-3b/{period}/status")
def gstr3b_return_status(
    period: str,
    reference_id: str,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    """Return Status poll — advances Save **or** Offset from inner action."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    token, _ = _resolve_token(sb, firm_id, session_id=session_id)
    try:
        with get_filing_client() as client:
            result = client.get_return_status(
                token, period=period, reference_id=reference_id,
            )
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc

    info = result.return_status
    run_status = None
    if run_id and info is not None:
        action = (info.action or "SAVE").upper()
        if action in _GSTR3B_OFFSET_STATUS_ACTIONS:
            updated = filing_store.apply_offset_status_to_run(
                sb,
                run_id,
                return_status=info,
                envelope=result.envelope,
            )
            run_status = updated.get("status")
            # After Offset P, snapshot tx_pmt for File / CA proof.
            if run_status == "offset_complete":
                try:
                    with get_filing_client() as client:
                        details = client.get_gstr3b_details(token, period=period)
                    tx_pmt = None
                    if isinstance(details.data, dict):
                        tx_pmt = details.data.get("tx_pmt") or details.data
                    if tx_pmt is not None:
                        filing_store.update_run(
                            sb, run_id, tx_pmt_snapshot=tx_pmt,
                        )
                except FilingClientError:
                    _log.warning(
                        "post-offset Get Details failed for run_id=%s; "
                        "tx_pmt_snapshot not stored",
                        run_id,
                    )
        elif action == "SAVE":
            updated = filing_store.apply_save_status_to_run(
                sb,
                run_id,
                return_status=info,
                envelope=result.envelope,
            )
            run_status = updated.get("status")
        else:
            filing_store.update_run(
                sb, run_id, raw_response=result.envelope,
            )

    return {
        "period": period,
        "reference_id": reference_id,
        "data": result.data,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
        "gstn_success": bool(info and info.is_success),
        "gstn_failed": bool(info and info.is_failed),
        "run_status": run_status,
        "action": info.action if info else None,
        "error_cd": info.error_cd if info else None,
        "error_message": (
            map_gstn_error(info.error_message, error_code=info.error_cd)
            if (info and info.error_message)
            else None
        ),
    }


@gstr3b_router.post(
    "/gstr-3b/{period}/offset",
    dependencies=[Depends(require_gstr3b_filing_enabled)],
)
def offset_gstr3b(
    period: str,
    body: OffsetGstr3bBody,
    current_user: dict = Depends(require_admin_user),
):
    """Offset Liability — CA must POST the exact confirmed ``{pdcash, pditc}``.

    Recomputes from live Get Details + ledger via the shared builder; rejects
    with ``GSTR3B_OFFSET_STALE`` when the confirmation is out of date.
    """
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id)
    gstin = str(client_row["gstin"]).strip().upper()

    _require_run_status(
        sb,
        firm_id,
        body.run_id,
        allowed=_GSTR3B_OFFSET_STATUSES,
        action="Offset",
    )

    try:
        filing_store.assert_gstr3b_offset_allowed(sb, gstin=gstin, period=period)
    except filing_store.Gstr3bPeriodLockedError as exc:
        _raise_gstr3b_locked(exc)

    # Enforce Pre-Filing Governance Gate on Offset (server-side protection against direct API calls)
    run_obj = filing_store.get_run(sb, body.run_id)
    if run_obj and isinstance(run_obj.get("save_payload"), dict):
        pol = get_firm_filing_policy(sb, firm_id)
        if pol.mode != FilingPolicyMode.ADVISORY:
            val_res = validate_gstr3b_pre_filing(
                sb,
                client_gstin_id=body.client_gstin_id,
                gstin=gstin,
                period=period,
                save_body=run_obj["save_payload"],
                require_final_reconciliation=pol.require_final_reconciliation,
                rule_88c_pct_threshold=pol.rule_88c_pct_threshold,
                rule_88c_amount_threshold=pol.rule_88c_amount_threshold,
                rule_88d_pct_threshold=pol.rule_88d_pct_threshold,
                rule_88d_amount_threshold=pol.rule_88d_amount_threshold,
            )
            verify_filing_governance_gate(
                sb,
                firm_id=firm_id,
                client_gstin_id=body.client_gstin_id,
                gstin=gstin,
                period=period,
                return_type="gstr-3b",
                validation_result=val_res,
                user=current_user,
            )

    posted = extract_offset_pair({"pdcash": body.pdcash, "pditc": body.pditc})
    token, _ = _resolve_token(
        sb, firm_id, session_id=body.session_id, gstin=gstin,
    )

    try:
        with get_filing_client() as client:
            current = _compute_current_offset_body(client, token, period=period)
            if not offset_bodies_equal(posted, current):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_gstr3b_offset_stale_detail(
                        period=period, posted=posted, current=current,
                    ),
                )
            result = client.offset_gstr3b_liability(
                token,
                period=period,
                gstin=gstin,
                offset_body=posted,
                sb=sb,
            )
    except filing_store.Gstr3bPeriodLockedError as exc:
        _raise_gstr3b_locked(exc)
    except FilingClientError as exc:
        err_cd = getattr(exc, "error_cd", None)
        filing_store.mark_run_failed(
            sb,
            body.run_id,
            error_code=err_cd,
            error_message=map_gstn_error(exc, error_code=err_cd),
            raw_response=getattr(exc, "envelope", None),
        )
        raise _map_client_error(exc) from exc

    filing_store.update_run(
        sb,
        body.run_id,
        status="offset_pending",
        reference_id=result.reference_id,
        raw_response=result.envelope,
        offset_payload=posted,
        clear_error=True,
    )
    info = result.return_status
    return {
        "period": period,
        "run_id": body.run_id,
        "reference_id": result.reference_id,
        "status": "offset_pending",
        "offset_payload": posted,
        "outer_status_cd": info.outer_status_cd if info else None,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "gstn_success": False,
        "message": "Offset accepted for processing; poll status until inner P",
    }


@gstr3b_router.post("/gstr-3b/{period}/evc-otp")
def generate_evc_otp_gstr3b(
    period: str,
    body: EvcOtpGstr3bBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to generate EVC OTP",
        )
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    run = _require_run_status(
        sb,
        firm_id,
        body.run_id,
        allowed=_GSTR3B_EVC_OR_FILE_STATUSES,
        action="EVC OTP",
    )
    if run and run.get("client_gstin_id"):
        _assert_client_access(sb, current_user, str(run["client_gstin_id"]))
    token, _ = _resolve_token(sb, firm_id, session_id=body.session_id)
    try:
        with get_filing_client() as client:
            result = client.generate_evc_otp_gstr3b(token, pan=body.pan)
    except FilingClientError as exc:
        raise _map_client_error(exc) from exc
    if body.run_id:
        filing_store.update_run(
            sb, body.run_id, status="evc_pending", clear_error=True,
        )
    info = result.return_status
    data = result.data if isinstance(result.data, dict) else {}
    return {
        "period": period,
        "message": "EVC OTP sent to authorized signatory",
        "status_cd": data.get("status_cd"),
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
    }


@gstr3b_router.post(
    "/gstr-3b/{period}/file",
    dependencies=[Depends(require_gstr3b_filing_enabled)],
)
def file_gstr3b(
    period: str,
    body: FileGstr3bBody,
    current_user: dict = Depends(require_admin_user),
):
    """File GSTR-3B. EVC OTP in JSON body only (never as query to our API)."""
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _require_run_status(
        sb,
        firm_id,
        body.run_id,
        allowed=_GSTR3B_EVC_OR_FILE_STATUSES,
        action="File",
    )
    token, _ = _resolve_token(sb, firm_id, session_id=body.session_id)

    governance_override: Optional[Any] = None
    # Enforce Pre-Filing Governance Gate before final Filing
    if body.run_id:
        run_data = _load_run_for_firm(sb, firm_id, body.run_id)
        client_gid = str(run_data.get("client_gstin_id") or "")
        run_gstin = str(run_data.get("gstin") or "").strip().upper()
        pol = get_firm_filing_policy(sb, firm_id)
        if pol.mode != FilingPolicyMode.ADVISORY and isinstance(run_data.get("save_payload"), dict):
            val_res = validate_gstr3b_pre_filing(
                sb,
                client_gstin_id=client_gid,
                gstin=run_gstin,
                period=period,
                save_body=run_data["save_payload"],
                require_final_reconciliation=pol.require_final_reconciliation,
                rule_88c_pct_threshold=pol.rule_88c_pct_threshold,
                rule_88c_amount_threshold=pol.rule_88c_amount_threshold,
                rule_88d_pct_threshold=pol.rule_88d_pct_threshold,
                rule_88d_amount_threshold=pol.rule_88d_amount_threshold,
            )
            governance_override = verify_filing_governance_gate(
                sb,
                firm_id=firm_id,
                client_gstin_id=client_gid,
                gstin=run_gstin,
                period=period,
                return_type="gstr-3b",
                validation_result=val_res,
                user=current_user,
            )

    file_body = body.file_body
    if file_body is None:
        try:
            with get_filing_client() as client:
                details = client.get_gstr3b_details(token, period=period)
        except FilingClientError as exc:
            raise _map_client_error(exc) from exc
        file_body = dict(details.data) if isinstance(details.data, dict) else {}

    try:
        with get_filing_client() as client:
            result = client.file_gstr3b(
                token,
                period=period,
                pan=body.pan,
                otp=body.otp,
                signature=body.signature,
                signing_method=body.signing_method,
                file_body=file_body,
            )
    except FilingClientError as exc:
        if body.run_id:
            err_cd = getattr(exc, "error_cd", None)
            filing_store.mark_run_failed(
                sb,
                body.run_id,
                error_code=err_cd,
                error_message=map_gstn_error(exc, error_code=err_cd),
                raw_response=getattr(exc, "envelope", None),
            )
        raise _map_client_error(exc) from exc

    if body.run_id:
        try:
            filing_store.update_run(
                sb,
                body.run_id,
                status="filed",
                ack_number=result.ack_number,
                raw_response=result.envelope,
                clear_error=True,
            )
        except Exception as db_err:
            _log.error("Failed to update run status to filed in database after GSTN submission: %s", db_err, exc_info=True)
        try:
            run_data = _load_run_for_firm(sb, firm_id, body.run_id)
            client_gid = str(run_data.get("client_gstin_id") or "")
            consume_override_on_file_sync(
                sb,
                firm_id=firm_id,
                client_gstin_id=client_gid,
                period=period,
                return_type="gstr-3b",
                run_id=body.run_id,
                user=current_user,
                override_id=governance_override.id if governance_override else None,
            )
        except Exception:
            _log.warning("Failed to consume override on GSTR-3B file", exc_info=True)
    info = result.return_status
    return {
        "period": period,
        "status": "filed",
        "ack_number": result.ack_number,
        "gstn_status_cd": info.gstn_status_cd if info else None,
        "outer_status_cd": info.outer_status_cd if info else None,
    }


# ---------------------------------------------------------------------------
# Bulk Filing Batches
# ---------------------------------------------------------------------------


@router.post("/batches")
def create_filing_batch(
    body: CreateBatchBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Create and trigger a bulk return filing batch (GSTR-1 only)."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or Partner access required for bulk filing operations",
        )
    if body.return_type != "gstr-1":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bulk filing is currently supported for GSTR-1 only",
        )
    period = _assert_period_yyyy_mm(body.period)
    if not body.client_gstin_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one client_gstin_id must be selected for bulk filing",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    for cid in body.client_gstin_ids:
        if cid not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied for client_gstin_id {cid}",
            )
    batch = filing_store.create_batch(
        sb,
        firm_id=firm_id,
        created_by=str(current_user.get("id")),
        period=period,
        client_gstin_ids=body.client_gstin_ids,
        return_type=body.return_type,
    )
    try:
        from app.worker.filing_batch_task import process_filing_batch

        process_filing_batch.delay(batch["id"])
    except Exception as exc:
        _log.exception("Failed to dispatch process_filing_batch for batch %s: %s", batch["id"], exc)

    return batch


@router.get("/batches")
def list_filing_batches(
    current_user: dict = Depends(get_current_active_user),
):
    """List bulk filing batches for the firm."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    batches = filing_store.list_batches(sb, firm_id=firm_id)
    return {"batches": batches}


@router.get("/batches/{batch_id}")
def get_filing_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Get details of a bulk filing batch including all item statuses."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    batch = filing_store.get_batch(sb, batch_id)
    if not batch or str(batch.get("firm_id")) != firm_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Filing batch not found",
        )
    return batch


@router.post("/batches/{batch_id}/retry")
def retry_filing_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retry failed items in a bulk filing batch."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or Partner access required to retry filing batches",
        )
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    batch = filing_store.get_batch(sb, batch_id)
    if not batch or str(batch.get("firm_id")) != firm_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Filing batch not found",
        )
    for item in batch.get("items", []):
        if item.get("status") in ("failed", "pending"):
            filing_store.update_batch_item(
                sb, item["id"], status="pending", error_code=None, error_detail=None
            )

    filing_store.recalculate_batch_status(sb, batch_id)

    try:
        from app.worker.filing_batch_task import process_filing_batch

        process_filing_batch.delay(batch_id)
    except Exception as exc:
        _log.exception("Failed to dispatch retry for batch %s: %s", batch_id, exc)

    return filing_store.get_batch(sb, batch_id)


@router.get("/history/{client_gstin_id}")
def filing_history(
    client_gstin_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve filing history and ARNs for a client across all return types."""
    sb = get_supabase()
    _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()
    runs = (
        sb.table("filing_runs")
        .select(
            "id, return_type, period, status, reference_id, arn, filing_method, "
            "created_at, updated_at, offset_completed_at, filed_at"
        )
        .eq("gstin", gstin)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return {
        "gstin": gstin,
        "client_gstin_id": client_gstin_id.strip(),
        "filings": runs.data or [],
    }


# ---------------------------------------------------------------------------
# Pre-Filing Governance & Cumulative FY Reconciliation
# ---------------------------------------------------------------------------


@router.get("/governance/policy")
def get_governance_policy(
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve the current filing governance policy for the user's firm."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    policy = get_firm_filing_policy(sb, firm_id)
    return policy.model_dump()


@router.put("/governance/policy")
async def update_governance_policy(
    update: FilingPolicyUpdate,
    current_user: dict = Depends(require_admin_user),
):
    """Update firm-level filing policy (Advisory, Partner Override, or Strict Block).

    Restricted to CA Partners / Admins. Immutable audit trail recorded.
    """
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    updated = await update_firm_filing_policy(
        sb,
        firm_id=firm_id,
        update=update,
        user=current_user,
    )
    return updated.model_dump()


@router.post("/governance/overrides")
async def create_governance_override(
    body: CreateOverrideBody,
    current_user: dict = Depends(require_admin_user),
):
    """Partner override authorizing filing despite critical statutory or reconciliation violations.

    Strict Security:
    - Partner role required (admin/owner). Staff cannot self-approve (HTTP 403).
    - Cryptographically bound to the SHA-256 digest of the filing figures.
    - Tenant isolation enforced against firm_id.
    - Recorded in immutable audit log.
    """
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, body.client_gstin_id.strip())
    gstin = str(client_row["gstin"]).strip().upper()

    override = await create_partner_override(
        sb,
        firm_id=firm_id,
        client_gstin_id=body.client_gstin_id.strip(),
        gstin=gstin,
        period=body.period.strip(),
        return_type=body.return_type.strip(),
        figures_digest=body.figures_digest.strip(),
        justification=body.justification.strip(),
        violations_acknowledged=body.violations_acknowledged,
        user=current_user,
        validation_digest=body.validation_digest,
    )
    return override.to_dict()


@router.get("/cumulative-fy/{client_gstin_id}")
def get_cumulative_fy_reconciliation(
    client_gstin_id: str,
    fy: str = Query(..., description="Financial year e.g. 2024-25 or 2024-2025"),
    current_user: dict = Depends(get_current_active_user),
):
    """12-month FY tie-out across GSTR-1 vs GSTR-3B vs GSTR-2B.

    Reuses GSTR-9/9C rollup logic. Tracks monthly & YTD turnover, ITC deltas,
    amendments, timing differences, and annual DRC-01B/DRC-01C risk with zero double-counting.
    """
    sb = get_supabase()
    _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id.strip())

    recon = assemble_cumulative_fy_reconciliation(
        sb,
        client_gstin_id=client_gstin_id.strip(),
        fy=fy.strip(),
    )
    return recon


router.include_router(gstr3b_router)


