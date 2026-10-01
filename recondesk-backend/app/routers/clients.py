"""Client (client_gstins) management: `/api/clients`."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.auth import AuthenticatedUser, get_current_active_user, get_current_user, require_admin
from app.database import ensure_user_profile, get_supabase, get_user_profile
from app.routers.reconciliation_api import _parse_uuid
from app.services.billing_gate import assert_gstin_capacity
from app.services.firm_access import list_accessible_client_gstin_ids
from app.services.carry_forward import get_chronic_risks
from app.services.gstin_verification import verify_gstin as _verify_gstin
from app.utils.audit import log_audit
from app.utils.redis_cache import invalidate_user_dashboard

router = APIRouter(redirect_slashes=False)
# Alias for `app.include_router(clients_router, ...)` in main.py
clients_router = router

_log = logging.getLogger(__name__)

GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)


def _pg_unique_violation(exc: BaseException) -> bool:
    """Detect Postgres unique-violation (23505) from Supabase / PostgREST errors."""
    code = getattr(exc, "code", None)
    parts: list[str] = [str(exc).lower()]
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        parts.append(str(cause).lower())
        code = code or getattr(cause, "code", None)
    msg = " ".join(parts)
    return (
        code == "23505"
        or "23505" in msg
        or "duplicate key" in msg
        or "unique constraint" in msg
    )


GSTIN_STATE_NAMES: dict[str, str] = {
    "27": "Maharashtra",
    "29": "Karnataka",
    "07": "Delhi",
    "33": "Tamil Nadu",
    "09": "Uttar Pradesh",
    "24": "Gujarat",
    "06": "Haryana",
    "19": "West Bengal",
    "32": "Kerala",
}


def _validate_gstin_error_message(reason: str) -> str:
    if reason == "invalid_checksum":
        return "Invalid checksum"
    if reason == "invalid_length":
        return "Wrong length"
    return "Invalid format"


class GSTINValidateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gstin: str


@router.post("/validate-gstin")
async def validate_gstin_endpoint(
    body: GSTINValidateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Normalize GSTIN; always 200 with {valid: bool, ...}."""
    raw = body.gstin
    try:
        normalized = normalize_gstin(raw)
        code = normalized[:2]
        state = GSTIN_STATE_NAMES.get(code, code)
        return {"valid": True, "normalized": normalized, "state": state}
    except NormalizationError as exc:
        return {"valid": False, "error": _validate_gstin_error_message(exc.reason)}


VALID_SCHEME_TYPES = {
    "regular",
    "composition",
    "casual",
    "nrtp",
    "isd",
    "tds_tcs_deductor",
}
VALID_FILING_FREQUENCIES = {"monthly", "qrmp"}


class ClientCreate(BaseModel):
    gstin: str
    trade_name: str
    legal_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    assigned_to: Optional[str] = None
    scheme_type: Optional[str] = "regular"
    filing_frequency: Optional[str] = "monthly"


class ClientUpdate(BaseModel):
    trade_name: Optional[str] = None
    legal_name: Optional[str] = None
    state_code: Optional[str] = None
    registration_type: Optional[str] = None
    assigned_to: Optional[str] = None
    scheme_type: Optional[str] = None
    filing_frequency: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


class AssignClientBody(BaseModel):
    assigned_to: str


def _resolve_firm_owner(sb, uid: str, role: str | None = None) -> str:
    # Phase 3C: Try Aurora tenancy repository first
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            owner_id = repo.get_firm_owner_id_for_user(uid)
            if owner_id is not None:
                return owner_id
    except Exception:
        pass

    user_role = (role or "").strip().lower()
    if user_role in ("admin", "owner"):
        return uid

    prof = get_user_profile(uid) or {}
    resolved_role = (user_role or prof.get("role") or "").strip().lower()
    if resolved_role in ("admin", "owner"):
        return uid

    # 1. Primary: active team membership in firm
    tm = (
        sb.table("team_members")
        .select("firm_owner_id")
        .eq("member_user_id", uid)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if tm.data and tm.data[0].get("firm_owner_id"):
        return str(tm.data[0]["firm_owner_id"]).strip()

    # 2. Fallback: match by invited email
    em = (prof.get("email") or "").strip().lower()
    if em:
        tm_email = (
            sb.table("team_members")
            .select("firm_owner_id")
            .eq("invited_email", em)
            .limit(1)
            .execute()
        )
        if tm_email.data and tm_email.data[0].get("firm_owner_id"):
            return str(tm_email.data[0]["firm_owner_id"]).strip()

    # 3. Fallback: client assignment
    r = (
        sb.table("client_gstins")
        .select("firm_owner_id")
        .eq("assigned_to", uid)
        .limit(1)
        .execute()
    )
    if r.data and r.data[0].get("firm_owner_id"):
        return str(r.data[0].get("firm_owner_id", "")).strip()

    if resolved_role == "staff":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="staff must belong to a firm team before performing this action",
        )

    # Standalone user with no explicit staff role is their own firm owner
    ensure_user_profile(uid, client=sb)
    return uid


@router.get("")
async def list_clients(current_user: dict = Depends(get_current_active_user)):
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    prof = get_user_profile(uid) or {}
    role = (current_user.get("role") or prof.get("role") or "").strip().lower()
    if role in ("admin", "owner") or not role:
        res = (
            sb.table("client_gstins")
            .select("*")
            .eq("firm_owner_id", uid)
            .eq("is_active", True)
            .order("added_at", desc=True)
            .limit(500)
            .execute()
        )
    else:
        res = (
            sb.table("client_gstins")
            .select("*")
            .eq("assigned_to", uid)
            .eq("is_active", True)
            .order("added_at", desc=True)
            .limit(500)
            .execute()
        )
    return res.data or []


@router.post("")
async def create_client(
    body: ClientCreate,
    current_user: dict = Depends(get_current_active_user),
):
    g = (body.gstin or "").strip().upper()
    if not GSTIN_RE.match(g):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid GSTIN format",
        )
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    owner = _resolve_firm_owner(sb, uid, role=current_user.get("role"))
    ensure_user_profile(owner, client=sb)

    st = (body.scheme_type or "regular").lower().strip()
    if st not in VALID_SCHEME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid scheme_type. Must be one of: {sorted(VALID_SCHEME_TYPES)}",
        )
    ff = (body.filing_frequency or "monthly").lower().strip()
    if ff not in VALID_FILING_FREQUENCIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid filing_frequency. Must be one of: {sorted(VALID_FILING_FREQUENCIES)}",
        )

    # Soft-deleted row for this GSTIN: restore it (does not consume a new free slot).
    existing = (
        sb.table("client_gstins")
        .select("*")
        .eq("firm_owner_id", owner)
        .eq("gstin", g)
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        if row.get("is_active"):
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=row,
            )
        updates: dict[str, Any] = {
            "is_active": True,
            "trade_name": body.trade_name,
            "legal_name": body.legal_name,
            "contact_name": body.contact_name,
            "contact_email": body.contact_email,
            "contact_phone": body.contact_phone,
            "state_code": g[:2],
            "scheme_type": st,
            "filing_frequency": ff,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        assigned_to_val = (body.assigned_to or "").strip()
        if assigned_to_val:
            try:
                UUID(assigned_to_val)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid assigned_to",
                ) from exc
            updates["assigned_to"] = assigned_to_val
        sb.table("client_gstins").update(updates).eq("id", row["id"]).execute()
        out = (
            sb.table("client_gstins")
            .select("*")
            .eq("id", row["id"])
            .single()
            .execute()
        )
        client_label = (
            str(body.trade_name or "").strip()
            or str(body.legal_name or "").strip()
            or g
        )
        await log_audit(
            sb,
            current_user,
            "CLIENT_RESTORED",
            "client",
            str(row["id"]),
            client_label,
            {"gstin": g},
        )
        invalidate_user_dashboard(uid)
        invalidate_user_dashboard(owner)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=dict(out.data or {}),
        )

    try:
        assert_gstin_capacity(sb, owner)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    ins: dict[str, Any] = {
        "id": str(uuid4()),
        "gstin": g,
        "trade_name": body.trade_name,
        "legal_name": body.legal_name,
        "contact_name": body.contact_name,
        "contact_email": body.contact_email,
        "contact_phone": body.contact_phone,
        "state_code": g[:2],
        "scheme_type": st,
        "filing_frequency": ff,
        "firm_owner_id": owner,
        "is_active": True,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    assigned_to_val = (body.assigned_to or "").strip()
    if assigned_to_val:
        try:
            UUID(assigned_to_val)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid assigned_to",
            ) from exc
        ins["assigned_to"] = assigned_to_val
    try:
        sb.table("client_gstins").insert(ins).execute()
    except Exception as e:
        if _pg_unique_violation(e):
            raced = (
                sb.table("client_gstins")
                .select("*")
                .eq("firm_owner_id", owner)
                .eq("gstin", g)
                .limit(1)
                .execute()
            )
            if raced.data:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content=raced.data[0],
                )
        raise
    out = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", ins["id"])
        .single()
        .execute()
    )
    client_label = (
        str(body.trade_name or "").strip()
        or str(body.legal_name or "").strip()
        or g
    )
    await log_audit(
        sb,
        current_user,
        "CLIENT_ADDED",
        "client",
        ins["id"],
        client_label,
        {"gstin": g},
    )

    # ── GSTIN verification (non-blocking) ────────────────────────────────────
    # Verification runs after the record is saved so the CA is never blocked.
    # If Sandbox is down or misconfigured we still return a 201 without a
    # warning; we just log the error.
    response_body: dict = dict(out.data or {})
    gstin_verification_warning: str | None = None
    try:
        verification = await _verify_gstin(g)
        v_status = verification.get("status", "")
        if v_status in ("Cancelled", "Not Found"):
            gstin_verification_warning = (
                f"GSTIN verification warning: status is '{v_status}'. "
                "Please double-check this GSTIN before proceeding."
            )
            _log.warning(
                "create_client: GSTIN %s has verification status '%s'",
                g[:5] + "*" * max(0, len(g) - 5),
                v_status,
            )
    except Exception as _exc:  # noqa: BLE001
        _log.error(
            "create_client: GSTIN verification failed (non-blocking) – %s", _exc
        )

    if gstin_verification_warning:
        response_body["gstin_verification_warning"] = gstin_verification_warning

    invalidate_user_dashboard(uid)
    invalidate_user_dashboard(owner)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=response_body,
    )


@router.get("/{client_id}")
async def get_client(
    client_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_id, "client_id")
    uid = str(current_user.get("id", "")).strip()
    prof = get_user_profile(uid) or {}
    role = (current_user.get("role") or prof.get("role") or "").strip().lower()

    # 1. Dual-Read: Check Aurora tenancy repository first
    repo = None
    aurora_client = None
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            aurora_client = repo.get_client_gstin(cid)
    except Exception:
        # Aurora infrastructure failure: fall through to established Supabase path
        aurora_client = None

    if aurora_client is not None:
        # Authoritative Aurora hit: DO NOT query Supabase under any circumstances
        if not aurora_client.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        if role in ("admin", "owner") or not role:
            ownership_ok = (
                repo.verify_firm_ownership(cid, uid)
                if repo is not None
                else (str(aurora_client.get("firm_owner_id", "")).strip() == uid)
            )
            if ownership_ok is not True:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="not allowed",
                )
        else:
            assignment_ok = (
                repo.verify_staff_assignment(cid, uid)
                if repo is not None
                else (str(aurora_client.get("assigned_to", "")).strip() == uid)
            )
            if assignment_ok is not True:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="not allowed",
                )

        return aurora_client

    # 2. Aurora miss: Supabase fallback
    sb = get_supabase()
    res = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    row = res.data[0]
    if not row.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    fo = str(row.get("firm_owner_id", ""))
    if role in ("admin", "owner") or not role:
        if fo != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not allowed",
            )
    elif str(row.get("assigned_to", "")) != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed",
        )
    # Do not embed reconciliation_history here — rebuilding per-run outcomes from
    # full payloads makes this endpoint seconds-to-minutes for chatty clients.
    # History belongs on GET /api/reconcile/runs?client_gstin_id=… (and the
    # dedicated /history/{gstin} route). Frontend never consumed the embedded list.
    return row


@router.patch("/{client_id}")
async def update_client(
    client_id: str,
    body: ClientUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_id, "client_id")
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    prof = get_user_profile(uid) or {}
    role = (current_user.get("role") or prof.get("role") or "").strip().lower()
    res = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    row = res.data[0]
    fo = str(row.get("firm_owner_id", ""))
    if role in ("admin", "owner") or not role:
        if fo != uid:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    elif str(row.get("assigned_to", "")) != uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    updates: dict[str, Any] = {}
    for k in (
        "trade_name",
        "legal_name",
        "state_code",
        "registration_type",
        "scheme_type",
        "filing_frequency",
        "contact_name",
        "contact_email",
        "contact_phone",
    ):
        v = getattr(body, k, None)
        if v is not None:
            if k == "scheme_type" and str(v).lower().strip() not in VALID_SCHEME_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"invalid scheme_type. Must be one of: {sorted(VALID_SCHEME_TYPES)}",
                )
            if k == "filing_frequency" and str(v).lower().strip() not in VALID_FILING_FREQUENCIES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"invalid filing_frequency. Must be one of: {sorted(VALID_FILING_FREQUENCIES)}",
                )
            updates[k] = str(v).lower().strip() if k in ("scheme_type", "filing_frequency") else v
    if body.assigned_to is not None:
        if role not in ("admin", "owner") and role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can change assigned_to",
            )
        assigned_to_clean = str(body.assigned_to).strip()
        if assigned_to_clean:
            try:
                UUID(assigned_to_clean)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid assigned_to",
                ) from exc
            updates["assigned_to"] = assigned_to_clean
        else:
            updates["assigned_to"] = None
    if updates:
        sb.table("client_gstins").update(updates).eq("id", cid).execute()
    out = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .single()
        .execute()
    )
    return out.data


@router.patch("/{client_id}/assign")
async def assign_client(
    client_id: str,
    body: AssignClientBody,
    admin_id: str = Depends(require_admin),
):
    cid = _parse_uuid(client_id, "client_id")
    assignee_id = (body.assigned_to or "").strip()
    try:
        UUID(assignee_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid assigned_to",
        ) from exc

    sb = get_supabase()
    res = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    row = res.data[0]
    fo = str(row.get("firm_owner_id", ""))
    if fo != admin_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    if not row.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if assignee_id != fo:
        tm = (
            sb.table("team_members")
            .select("id")
            .eq("firm_owner_id", fo)
            .eq("member_user_id", assignee_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not tm.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_to is not an active member of this firm",
            )

    sb.table("client_gstins").update({"assigned_to": assignee_id}).eq("id", cid).execute()
    out = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .single()
        .execute()
    )
    return out.data


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_id, "client_id")
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    prof = get_user_profile(uid) or {}
    role = (current_user.get("role") or prof.get("role") or "").strip().lower()
    if role not in ("admin", "owner") and role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can remove clients",
        )
    ex = (
        sb.table("client_gstins")
        .update({"is_active": False})
        .eq("id", cid)
        .eq("firm_owner_id", uid)
        .execute()
    )
    if not ex.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    row = ex.data[0]
    client_label = (
        str(row.get("trade_name") or "").strip()
        or str(row.get("legal_name") or "").strip()
        or str(row.get("gstin") or "").strip()
        or "Client"
    )
    await log_audit(
        sb,
        current_user,
        "CLIENT_DELETED",
        "client",
        cid,
        client_label,
    )
    invalidate_user_dashboard(uid)
    return None


@router.get("/{client_gstin_id}/chronic-risks")
async def list_chronic_risks(
    client_gstin_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Invoices unmatched for >= 3 consecutive reconciliation runs."""
    cg = _parse_uuid(client_gstin_id, "client_gstin_id")
    sb = get_supabase()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cg not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )
    risks = await get_chronic_risks(UUID(cg))
    return {"client_gstin_id": cg, "chronic_risks": risks}


@router.get("/{client_id}/command-center")
@router.get("/{client_id}/itc-command-center")
async def get_client_itc_command_center(
    client_id: str,
    period: Optional[str] = None,
    priority: Optional[str] = None,
    exception_type: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve the executive ITC Command Center data and prioritized work items."""
    cid = _parse_uuid(client_id, "client_id")
    sb = get_supabase()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )
    try:
        from app.services.itc_command_center_service import get_itc_command_center_data
        data = get_itc_command_center_data(
            sb,
            cid,
            period=period,
            priority_filter=priority,
            exception_type_filter=exception_type,
            search=search,
            user_id=str(current_user.get("id", "")),
        )
        return data
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as exc:
        _log.exception("get_client_itc_command_center failed for %s", cid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compile ITC Command Center: {exc}",
        )

