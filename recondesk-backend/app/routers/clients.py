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
from app.models.roles import ALL_ROLES, is_admin_or_partner, is_manager_or_above, is_writer_or_above, normalize_role
from app.database import ensure_user_profile, get_supabase, get_user_profile
from app.routers.reconciliation_api import _parse_uuid
from app.services.normalizer import NormalizationError, normalize_gstin
from app.services.billing_gate import assert_gstin_capacity
from app.services.firm_access import list_accessible_client_gstin_ids
from app.services.carry_forward import get_chronic_risks
from app.services.gstin_verification import verify_gstin as _verify_gstin
from app.services.tenancy_sync import (
    mirror_client_create_to_aurora,
    mirror_client_delete_to_aurora,
    mirror_client_update_to_aurora,
)
from app.utils.audit import log_audit
from app.utils.redis_cache import invalidate_user_dashboard

router = APIRouter(redirect_slashes=False)
# Alias for `app.include_router(clients_router, ...)` in main.py
clients_router = router

_log = logging.getLogger(__name__)

GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")


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
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

PAN_ENTITY_TYPES: dict[str, str] = {
    "C": "Company",
    "F": "Partnership / LLP",
    "P": "Proprietorship / Individual",
    "H": "HUF",
    "T": "Trust",
    "A": "Association of Persons (AOP)",
    "B": "Body of Individuals (BOI)",
    "G": "Government Entity",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
}


def extract_pan_from_gstin(gstin: str) -> Optional[str]:
    """Extract 10-char PAN from 15-char GSTIN if present and valid."""
    g = (gstin or "").strip().upper()
    if len(g) >= 12:
        candidate = g[2:12]
        if PAN_RE.match(candidate):
            return candidate
        return candidate
    if len(g) == 10 and PAN_RE.match(g):
        return g
    return None


def get_entity_type_from_pan(pan: str) -> str:
    """Infer legal entity category from 4th character of 10-char PAN."""
    p = (pan or "").strip().upper()
    if len(p) >= 4:
        code = p[3]
        return PAN_ENTITY_TYPES.get(code, "Other")
    return "Other"


def requires_dsc_for_pan(pan: str) -> bool:
    """CGST Rule 26: Companies ('C') and LLPs/Firms ('F') must file with DSC."""
    p = (pan or "").strip().upper()
    if len(p) >= 4:
        return p[3] in ("C", "F")
    return False


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


class BulkAssignBody(BaseModel):
    client_ids: list[str]
    assigned_to: str
    assignment_role: Optional[str] = "preparer"


class CreateClientAssignmentBody(BaseModel):
    user_id: str
    assignment_role: Optional[str] = "preparer"


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

    # 1. Primary: active team membership in firm (invited staff/partner/manager)
    try:
        tm = (
            sb.table("team_members")
            .select("firm_owner_id")
            .eq("member_user_id", uid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if (
            isinstance(getattr(tm, "data", None), list)
            and len(tm.data) > 0
            and isinstance(tm.data[0], dict)
            and tm.data[0].get("firm_owner_id")
        ):
            return str(tm.data[0]["firm_owner_id"]).strip()
    except Exception:
        pass

    if resolved_role == "partner":
        return uid

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
        if (
            isinstance(getattr(tm_email, "data", None), list)
            and len(tm_email.data) > 0
            and isinstance(tm_email.data[0], dict)
            and tm_email.data[0].get("firm_owner_id")
        ):
            return str(tm_email.data[0]["firm_owner_id"]).strip()

    # 3. Fallback: client assignment
    r = (
        sb.table("client_gstins")
        .select("firm_owner_id")
        .eq("assigned_to", uid)
        .limit(1)
        .execute()
    )
    if (
        isinstance(getattr(r, "data", None), list)
        and len(r.data) > 0
        and isinstance(r.data[0], dict)
        and r.data[0].get("firm_owner_id")
    ):
        return str(r.data[0].get("firm_owner_id", "")).strip()

    if resolved_role == "staff":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="staff must belong to a firm team before performing this action",
        )

    # Standalone user with no explicit staff role is their own firm owner
    ensure_user_profile(uid, client=sb)
    return uid


SENSITIVE_CLIENT_FIELDS = {
    "gstn_access_token",
    "gstn_refresh_token",
    "einvoice_password",
    "api_secret",
}


def serialize_client(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Sanitize client row before returning to client/browser.

    Strips raw secrets and provides safe presence flags.
    """
    if not row or not isinstance(row, dict):
        return row
    safe = {k: v for k, v in row.items() if k not in SENSITIVE_CLIENT_FIELDS}
    token = row.get("gstn_access_token")
    safe["has_gstn_token"] = bool(token)
    safe["gstn_access_token"] = None
    safe["is_gstn_connected"] = bool(token and row.get("gstn_token_expiry"))
    return safe


async def _get_accessible_clients_list(current_user: dict) -> list[dict[str, Any]]:
    uid = str(current_user.get("id", "")).strip()
    prof = get_user_profile(uid) or {}
    role = (current_user.get("role") or prof.get("role") or "").strip().lower()

    # 1. Dual-Read: Check Aurora tenancy repository first
    aurora_clients = None
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            aurora_clients = repo.list_accessible_clients(uid, role=role, limit=500)
    except Exception as exc:
        _log.warning("Aurora bulk client read failed: %s", type(exc).__name__)
        aurora_clients = None

    if aurora_clients is not None:
        return [serialize_client(r) for r in aurora_clients if r]

    # 2. Aurora miss: Supabase fallback
    sb = get_supabase()
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
    return [serialize_client(r) for r in (res.data or []) if r]


@router.get("")
async def list_clients(current_user: dict = Depends(get_current_active_user)):
    return await _get_accessible_clients_list(current_user)


@router.get("/organizations")
async def list_client_organizations(current_user: dict = Depends(get_current_active_user)):
    """Groups accessible client GSTINs by legal organization (10-digit PAN).

    Returns PAN-level company groups with:
    - Multi-state GSTIN registration breakdown
    - Legal entity categorization (Company, LLP, Proprietorship)
    - CGST Rule 26 DSC compliance requirements
    - Combined portal connection status
    """
    raw_clients = await _get_accessible_clients_list(current_user)

    groups: dict[str, list[dict[str, Any]]] = {}
    for c in raw_clients:
        gstin = str(c.get("gstin") or "").strip().upper()
        pan = extract_pan_from_gstin(gstin)
        if not pan:
            pan = gstin[2:12] if len(gstin) >= 12 else (gstin or "UNKNOWN")
        groups.setdefault(pan, []).append(c)

    orgs: list[dict[str, Any]] = []
    for pan, clients in groups.items():
        legal_names = [c.get("legal_name") for c in clients if c.get("legal_name")]
        trade_names = [c.get("trade_name") for c in clients if c.get("trade_name")]
        best_legal_name = legal_names[0] if legal_names else None
        best_trade_name = trade_names[0] if trade_names else None
        company_name = best_trade_name or best_legal_name or f"Organization ({pan})"

        entity_type = get_entity_type_from_pan(pan)
        requires_dsc = requires_dsc_for_pan(pan)

        states_dict: dict[str, str] = {}
        enriched_gstins: list[dict[str, Any]] = []
        for c in clients:
            sc = serialize_client(c) or c
            gstin = str(sc.get("gstin") or "").strip().upper()
            st_code = str(sc.get("state_code") or (gstin[:2] if len(gstin) >= 2 else "")).strip()
            st_name = GSTIN_STATE_NAMES.get(st_code, f"State {st_code}" if st_code else "Unknown")
            if st_code:
                states_dict[st_code] = st_name
            cg = dict(sc)
            cg["state_name"] = st_name
            enriched_gstins.append(cg)

        enriched_gstins.sort(key=lambda x: str(x.get("state_code") or x.get("gstin") or ""))

        state_list = [
            {"code": code, "name": name}
            for code, name in sorted(states_dict.items(), key=lambda x: x[0])
        ]

        total_gstins = len(enriched_gstins)
        connected_count = sum(1 for c in enriched_gstins if c.get("is_gstn_connected"))
        has_active = any(c.get("is_active", True) for c in enriched_gstins)
        primary_client_id = enriched_gstins[0].get("id") if enriched_gstins else None

        orgs.append({
            "pan": pan,
            "company_name": company_name,
            "legal_name": best_legal_name,
            "trade_name": best_trade_name,
            "entity_type": entity_type,
            "requires_dsc": requires_dsc,
            "total_gstins": total_gstins,
            "connected_count": connected_count,
            "all_connected": (connected_count == total_gstins and total_gstins > 0),
            "is_active": has_active,
            "states": state_list,
            "primary_client_id": str(primary_client_id) if primary_client_id else None,
            "gstins": enriched_gstins,
        })

    orgs.sort(key=lambda o: (o["company_name"] or "").lower())
    return orgs


@router.post("")
async def create_client(
    body: ClientCreate,
    current_user: dict = Depends(get_current_active_user),
):
    role = (current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only manager or partner can add clients",
        )
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
        restored_data = dict(out.data or {})
        mirror_client_create_to_aurora(restored_data, owner, current_user_id=uid)
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
            content=serialize_client(dict(restored_data or out.data or {})),
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
                mirror_client_create_to_aurora(raced.data[0], owner, current_user_id=uid)
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content=serialize_client(raced.data[0]),
                )
        raise
    out = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", ins["id"])
        .single()
        .execute()
    )
    created_data = dict(out.data or ins)
    mirror_client_create_to_aurora(created_data, owner, current_user_id=uid)
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
    response_body: dict = dict(serialize_client(out.data) or {})
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

        if repo is not None:
            owner = repo.get_firm_owner_id_for_user(uid) or uid
        else:
            sb = get_supabase()
            owner = _resolve_firm_owner(sb, uid, role=role)
        if is_manager_or_above(role):
            ownership_ok = (
                repo.verify_firm_ownership(cid, owner)
                if repo is not None
                else (str(aurora_client.get("firm_owner_id", "")).strip() == owner)
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
    owner = _resolve_firm_owner(sb, uid, role=role)
    if is_manager_or_above(role):
        if fo != owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not allowed",
            )
    else:
        is_assigned = str(row.get("assigned_to", "")) == uid
        if not is_assigned:
            try:
                ca_check = (
                    sb.table("client_assignments")
                    .select("id")
                    .eq("client_gstin_id", cid)
                    .eq("user_id", uid)
                    .limit(1)
                    .execute()
                )
                if not ca_check.data:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="not allowed",
                    )
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="not allowed",
                )
    return serialize_client(row)


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
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required to update client details",
        )
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
    owner = _resolve_firm_owner(sb, uid, role=role)
    if is_manager_or_above(role):
        if fo != owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    else:
        is_assigned = str(row.get("assigned_to", "")) == uid
        if not is_assigned:
            try:
                ca_check = (
                    sb.table("client_assignments")
                    .select("id")
                    .eq("client_gstin_id", cid)
                    .eq("user_id", uid)
                    .limit(1)
                    .execute()
                )
                if not ca_check.data:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
            except HTTPException:
                raise
            except Exception:
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
        if not is_manager_or_above(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only manager or above can change assigned_to",
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
        mirror_client_update_to_aurora(cid, updates, fo, current_user_id=uid)
        if updates.get("assigned_to"):
            try:
                from app.repositories.tenancy import get_tenancy_repository
                repo = get_tenancy_repository()
                if repo is not None:
                    repo.assign_client_multi_role(cid, updates["assigned_to"], fo, assignment_role="preparer", assigned_by=uid)
            except Exception:
                pass

    out = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .single()
        .execute()
    )
    return serialize_client(out.data)


@router.patch("/{client_id}/assign")
async def assign_client(
    client_id: str,
    body: AssignClientBody,
    current_user: Optional[dict] = Depends(get_current_active_user),
    admin_id: Optional[str] = None,
):
    cid = _parse_uuid(client_id, "client_id")
    if admin_id and (not current_user or not isinstance(current_user, dict)):
        current_user = {"id": admin_id, "role": "admin"}
    elif not current_user:
        current_user = {}
    role = (current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only manager or partner can assign clients",
        )

    assignee_id = (body.assigned_to or "").strip()
    try:
        UUID(assignee_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid assigned_to",
        ) from exc

    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    owner = _resolve_firm_owner(sb, uid, role=role)

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
    if fo != owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    if not row.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if assignee_id != owner:
        tm = (
            sb.table("team_members")
            .select("id")
            .eq("firm_owner_id", owner)
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
    mirror_client_update_to_aurora(cid, {"assigned_to": assignee_id}, owner, current_user_id=uid)
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            repo.assign_client_multi_role(cid, assignee_id, owner, assignment_role="preparer", assigned_by=uid)
    except Exception as exc:
        _log.warning("Aurora assign_client_multi_role failed: %s", exc)

    out = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .single()
        .execute()
    )
    return serialize_client(out.data)


@router.post("/bulk-assign")
async def bulk_assign_clients_endpoint(
    body: BulkAssignBody,
    current_user: dict = Depends(get_current_active_user),
):
    role = (current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only manager or partner can perform bulk client assignments",
        )
    if not body.client_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_ids cannot be empty",
        )
    uid = str(current_user.get("id", "")).strip()
    sb = get_supabase()
    owner = _resolve_firm_owner(sb, uid, role=role)

    assignee_id = body.assigned_to.strip()
    try:
        UUID(assignee_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid assigned_to user id",
        ) from exc

    if assignee_id != owner:
        tm = (
            sb.table("team_members")
            .select("id")
            .eq("firm_owner_id", owner)
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

    clean_cids = [_parse_uuid(c, "client_id") for c in body.client_ids]
    res = (
        sb.table("client_gstins")
        .select("id, firm_owner_id")
        .in_("id", clean_cids)
        .eq("firm_owner_id", owner)
        .eq("is_active", True)
        .execute()
    )
    found_ids = {str(r["id"]) for r in (res.data or [])}
    forbidden_ids = [c for c in clean_cids if c not in found_ids]
    if forbidden_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied or client not found in firm: {forbidden_ids[0]}",
        )

    as_role = (body.assignment_role or "preparer").strip().lower()
    valid_roles = ALL_ROLES.union({"preparer", "reviewer", "manager", "partner", "viewer"})
    if as_role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid assignment_role: {as_role}",
        )

    reassigned = []
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            reassigned = repo.bulk_reassign_clients(
                clean_cids,
                user_id=assignee_id,
                firm_owner_id=owner,
                assignment_role=as_role,
                assigned_by=uid,
            )
    except Exception as exc:
        _log.warning("Aurora bulk_reassign_clients failed: %s", exc)

    if as_role == "preparer":
        sb.table("client_gstins").update({"assigned_to": assignee_id}).in_("id", clean_cids).eq("firm_owner_id", owner).execute()

    for cid in clean_cids:
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            sb.table("client_assignments").upsert(
                {
                    "client_gstin_id": cid,
                    "firm_owner_id": owner,
                    "user_id": assignee_id,
                    "assignment_role": as_role,
                    "assigned_at": now_iso,
                    "assigned_by": uid,
                },
                on_conflict="client_gstin_id,user_id,assignment_role",
            ).execute()
        except Exception as exc:
            _log.debug("Supabase client_assignments upsert: %s", exc)

    await log_audit(
        sb,
        current_user,
        "CLIENTS_BULK_REASSIGNED",
        "client_gstins",
        owner,
        f"{len(clean_cids)} clients reassigned",
        {"count": len(clean_cids), "assigned_to": assignee_id, "role": as_role},
    )

    return {
        "success": True,
        "reassigned_count": len(clean_cids),
        "client_ids": clean_cids,
        "assigned_to": assignee_id,
        "assignment_role": as_role,
    }


@router.get("/{client_id}/assignments")
async def list_client_assignments_endpoint(
    client_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_id, "client_id")
    sb = get_supabase()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this client",
        )
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            assignments = repo.list_client_assignments(cid)
            return {"client_gstin_id": cid, "assignments": assignments}
    except Exception:
        pass
    try:
        res = (
            sb.table("client_assignments")
            .select("*, user_profiles(full_name, email, role)")
            .eq("client_gstin_id", cid)
            .execute()
        )
        return {"client_gstin_id": cid, "assignments": res.data or []}
    except Exception:
        return {"client_gstin_id": cid, "assignments": []}


@router.post("/{client_id}/assignments")
async def create_client_assignment_endpoint(
    client_id: str,
    body: CreateClientAssignmentBody,
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_id, "client_id")
    role = (current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only manager or partner can add client assignments",
        )
    uid = str(current_user.get("id", "")).strip()
    sb = get_supabase()
    owner = _resolve_firm_owner(sb, uid, role=role)

    res = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", cid)
        .eq("firm_owner_id", owner)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found in firm")

    target_user_id = body.user_id.strip()
    try:
        UUID(target_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid user_id") from exc

    as_role = (body.assignment_role or "preparer").strip().lower()
    assignment_res = None
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            assignment_res = repo.assign_client_multi_role(
                cid, target_user_id, owner, assignment_role=as_role, assigned_by=uid
            )
    except Exception as exc:
        _log.warning("Aurora assign_client_multi_role failed: %s", exc)

    if as_role == "preparer":
        sb.table("client_gstins").update({"assigned_to": target_user_id}).eq("id", cid).execute()

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("client_assignments").upsert(
            {
                "client_gstin_id": cid,
                "firm_owner_id": owner,
                "user_id": target_user_id,
                "assignment_role": as_role,
                "assigned_at": now_iso,
                "assigned_by": uid,
            },
            on_conflict="client_gstin_id,user_id,assignment_role",
        ).execute()
    except Exception:
        pass

    return assignment_res or {"client_gstin_id": cid, "user_id": target_user_id, "assignment_role": as_role}


@router.delete("/{client_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_assignment_endpoint(
    client_id: str,
    assignment_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_id, "client_id")
    aid = _parse_uuid(assignment_id, "assignment_id")
    role = (current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only manager or partner can remove client assignments",
        )
    uid = str(current_user.get("id", "")).strip()
    sb = get_supabase()
    owner = _resolve_firm_owner(sb, uid, role=role)

    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            repo.remove_client_assignment(cid, aid, owner)
    except Exception:
        pass

    try:
        sb.table("client_assignments").delete().eq("id", aid).eq("client_gstin_id", cid).eq("firm_owner_id", owner).execute()
    except Exception:
        pass
    return None


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
    if not is_admin_or_partner(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only partner or admin can remove clients",
        )
    owner = _resolve_firm_owner(sb, uid, role=role)
    ex = (
        sb.table("client_gstins")
        .update({"is_active": False})
        .eq("id", cid)
        .eq("firm_owner_id", owner)
        .execute()
    )
    if not ex.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    mirror_client_delete_to_aurora(cid, owner, current_user_id=uid)
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
    invalidate_user_dashboard(owner)
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

