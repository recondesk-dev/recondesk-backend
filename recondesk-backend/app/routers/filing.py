"""GSTR-1 / GSTR-3B filing API: taxpayer OTP session + Save→File chain."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth import get_current_active_user
from app.config import get_settings
from app.database import get_supabase
from app.filing import filing_store
from app.filing.gstr1_orchestrator import (
    map_sales_register_to_gstr1,
    serialize_gstr1_readiness,
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

# File / EVC require a GSTN-confirmed Save (inner status_cd P) or later.
_EVC_OR_FILE_STATUSES = frozenset({"saved", "proceeded", "evc_pending"})
_PROCEED_STATUSES = frozenset({"saved"})
# GSTR-3B: Offset after confirmed Save; EVC/File after Offset complete.
_GSTR3B_OFFSET_STATUSES = frozenset({"saved"})
_GSTR3B_EVC_OR_FILE_STATUSES = frozenset({"offset_complete", "evc_pending"})
_GSTR3B_OFFSET_STATUS_ACTIONS = frozenset({"RETOFFSET", "OFFSET", "OFFLIAB"})
from app.services.firm_access import list_accessible_client_gstin_ids
from app.utils.audit import resolve_firm_id

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


# GSTR-3B money path — gated until live Save→Offset→File is proven.
# Included under the same /api/filing prefix; returns 503 (not 404).
gstr3b_router = APIRouter(
    redirect_slashes=False,
    dependencies=[Depends(require_gstr3b_filing_enabled)],
)


@router.get("/features")
def filing_features():
    """Public feature flags for filing UI entry points (no auth)."""
    return {
        "gstr1_filing_enabled": True,
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

    @field_validator("client_gstin_id", "period")
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
    otp: str
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    # Optional override; otherwise built from GET summary on the run.
    file_body: Optional[dict[str, Any]] = None

    @field_validator("pan", "otp")
    @classmethod
    def _req(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


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
    otp: str
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    # Must include post-Offset ``tx_pmt``; when omitted, re-fetched from Get Details.
    file_body: Optional[dict[str, Any]] = None

    @field_validator("pan", "otp")
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
    if isinstance(exc, FilingAuthError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, FilingGstnError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "error_cd": exc.error_cd},
        )
    if isinstance(exc, FilingApiError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


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
    sb = get_supabase()
    _firm_id(sb, current_user)
    if body.client_gstin_id:
        _assert_client_access(sb, current_user, body.client_gstin_id)
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
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = None
    if body.client_gstin_id:
        client_row = _assert_client_access(sb, current_user, body.client_gstin_id)
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
                    "gstn_access_token": session.access_token,
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
                    "message": result.error_message,
                }
        except Exception as exc:
            _log.warning("logout unexpected error (non-fatal): %s", exc)
            sandbox_error = {"message": str(exc)}

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


def _readiness_payload_for_client(
    *,
    sb,
    current_user: dict,
    client_gstin_id: str,
    period: str,
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], Any, str]:
    client_row = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = str(client_row["gstin"]).strip().upper()
    mapped = map_sales_register_to_gstr1(
        records,
        filer_state=gstin[:2],
        filing_period=period,
    )
    payload = serialize_gstr1_readiness(mapped)
    payload["gstin"] = gstin
    payload["client_gstin_id"] = client_gstin_id
    payload["record_count"] = len(records)
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
) -> dict[str, Any]:
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
        filing_store.mark_run_failed(
            sb,
            run["id"],
            error_code=getattr(exc, "error_cd", None),
            error_message=str(exc),
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
    )
    return payload


@router.post("/gstr-1/{period}/readiness-upload")
async def gstr1_readiness_upload(
    period: str,
    client_gstin_id: str = Form(...),
    sales_register_file: UploadFile = File(...),
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
    payload, _, _ = _readiness_payload_for_client(
        sb=sb,
        current_user=current_user,
        client_gstin_id=client_gstin_id.strip(),
        period=period,
        records=records,
    )
    payload["source_filename"] = sales_register_file.filename
    return payload


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
    return _execute_save(
        sb=sb,
        firm_id=firm_id,
        client_gstin_id=body.client_gstin_id,
        gstin=gstin,
        period=period,
        session_id=body.session_id,
        records=body.records,
        gt=body.gt,
        cur_gt=body.cur_gt,
    )


@router.post("/gstr-1/{period}/save-upload")
async def save_gstr1_upload(
    period: str,
    client_gstin_id: str = Form(...),
    sales_register_file: UploadFile = File(...),
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
    return _execute_save(
        sb=sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id.strip(),
        gstin=gstin,
        period=period,
        session_id=(session_id.strip() if session_id else None),
        records=records,
        gt=gt,
        cur_gt=cur_gt,
    )


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
        "error_message": info.error_message if info else None,
    }


@router.post("/gstr-1/{period}/proceed")
def proceed_to_file(
    period: str,
    body: ProceedBody,
    current_user: dict = Depends(get_current_active_user),
):
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
            filing_store.mark_run_failed(
                sb,
                body.run_id,
                error_code=getattr(exc, "error_cd", None),
                error_message=str(exc),
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
        "error_message": info.error_message if info else None,
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
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _require_run_status(
        sb,
        firm_id,
        body.run_id,
        allowed=_EVC_OR_FILE_STATUSES,
        action="EVC OTP",
    )
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
    current_user: dict = Depends(get_current_active_user),
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
                file_body=file_body,
            )
    except FilingClientError as exc:
        if body.run_id:
            filing_store.mark_run_failed(
                sb,
                body.run_id,
                error_code=getattr(exc, "error_cd", None),
                error_message=str(exc),
                raw_response=getattr(exc, "envelope", None),
            )
        raise _map_client_error(exc) from exc

    if body.run_id:
        filing_store.update_run(
            sb,
            body.run_id,
            status="filed",
            ack_number=result.ack_number,
            raw_response=result.envelope,
            clear_error=True,
        )
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
            result = client.save_gstr3b(
                token, period=period, save_body=save_body, sb=sb,
            )
    except filing_store.Gstr3bPeriodLockedError as exc:
        _raise_gstr3b_locked(exc)
    except FilingClientError as exc:
        filing_store.mark_run_failed(
            sb,
            run_id,
            error_code=getattr(exc, "error_cd", None),
            error_message=str(exc),
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
        "error_message": info.error_message if info else None,
    }


@gstr3b_router.post("/gstr-3b/{period}/offset")
def offset_gstr3b(
    period: str,
    body: OffsetGstr3bBody,
    current_user: dict = Depends(get_current_active_user),
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
        filing_store.mark_run_failed(
            sb,
            body.run_id,
            error_code=getattr(exc, "error_cd", None),
            error_message=str(exc),
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
    period = _assert_period_yyyy_mm(period)
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _require_run_status(
        sb,
        firm_id,
        body.run_id,
        allowed=_GSTR3B_EVC_OR_FILE_STATUSES,
        action="EVC OTP",
    )
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


@gstr3b_router.post("/gstr-3b/{period}/file")
def file_gstr3b(
    period: str,
    body: FileGstr3bBody,
    current_user: dict = Depends(get_current_active_user),
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
                file_body=file_body,
            )
    except FilingClientError as exc:
        if body.run_id:
            filing_store.mark_run_failed(
                sb,
                body.run_id,
                error_code=getattr(exc, "error_cd", None),
                error_message=str(exc),
                raw_response=getattr(exc, "envelope", None),
            )
        raise _map_client_error(exc) from exc

    if body.run_id:
        filing_store.update_run(
            sb,
            body.run_id,
            status="filed",
            ack_number=result.ack_number,
            raw_response=result.envelope,
            clear_error=True,
        )
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


router.include_router(gstr3b_router)

