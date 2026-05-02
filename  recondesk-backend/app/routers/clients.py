"""Client (client_gstins) management: `/api/clients`."""

from __future__ import annotations

import re
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user, require_admin
from app.database import get_supabase, get_user_profile
from app.routers.reconciliation_api import _parse_uuid
from app.routers.reconciliation_api import _history_row

router = APIRouter()
# Alias for `app.include_router(clients_router, ...)` in main.py
clients_router = router

GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)


def _history_for_client(sb, cgid: str) -> list[dict]:
    runs = (
        sb.table("reconciliation_run")
        .select(
            "id, period, status, run_summary, created_at, finalized_at, finalized_by, client_gstin_id"
        )
        .eq("client_gstin_id", cgid)
        .execute()
    )
    data = list(runs.data or [])

    def _period_sort_key(period: str) -> tuple[int, int]:
        try:
            y, m = (period or "0000-00").split("-", 1)
            return (int(y), int(m))
        except ValueError:
            return (0, 0)

    data.sort(
        key=lambda d: (
            _period_sort_key(str(d.get("period") or "")),
            str(d.get("created_at") or ""),
        )
    )
    uids: set[str] = set()
    for x in data:
        if x.get("finalized_by"):
            uids.add(str(x.get("finalized_by")))
    name_by: dict[str, str] = {}
    for u in uids:
        p2 = get_user_profile(u) or {}
        if p2.get("full_name"):
            name_by[u] = str(p2.get("full_name"))
    by_period: dict[str, int] = {}
    out_asc: list[dict] = []
    for i, run in enumerate(data):
        pkey = str(run.get("period") or "")
        by_period[pkey] = by_period.get(pkey, 0) + 1
        rnum = by_period[pkey]
        prev = data[i - 1] if i > 0 else None
        out_asc.append(_history_row(sb, run, prev, rnum, name_by))
    return list(reversed(out_asc))


class ClientCreate(BaseModel):
    gstin: str
    trade_name: str
    legal_name: Optional[str] = None
    contact_name: str
    contact_email: str
    contact_phone: str
    assigned_to: Optional[str] = None


class ClientUpdate(BaseModel):
    trade_name: Optional[str] = None
    legal_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    assigned_to: Optional[str] = None


class AssignClientBody(BaseModel):
    assigned_to: str


def _resolve_firm_owner(sb, uid: str) -> str:
    prof = get_user_profile(uid) or {}
    role = (prof.get("role") or "staff").lower()
    if role == "admin":
        return uid
    r = (
        sb.table("client_gstins")
        .select("firm_owner_id")
        .eq("assigned_to", uid)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="staff must belong to a firm (assign a client first) before creating clients",
        )
    return str(r.data[0].get("firm_owner_id", "")).strip()


@router.get("/")
async def list_clients(current_user: dict = Depends(get_current_active_user)):
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    prof = get_user_profile(uid) or {}
    role = (prof.get("role") or "staff").lower()
    if role == "admin":
        res = (
            sb.table("client_gstins")
            .select("*")
            .eq("firm_owner_id", uid)
            .eq("is_active", True)
            .execute()
        )
    else:
        res = (
            sb.table("client_gstins")
            .select("*")
            .eq("assigned_to", uid)
            .eq("is_active", True)
            .execute()
        )
    return res.data or []


@router.post("/", status_code=status.HTTP_201_CREATED)
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
    owner = _resolve_firm_owner(sb, uid)
    ins: dict[str, Any] = {
        "id": str(uuid4()),
        "gstin": g,
        "trade_name": body.trade_name,
        "legal_name": body.legal_name,
        "contact_name": body.contact_name,
        "contact_email": body.contact_email,
        "contact_phone": body.contact_phone,
        "firm_owner_id": owner,
        "is_active": True,
    }
    if body.assigned_to:
        try:
            UUID(body.assigned_to.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid assigned_to",
            ) from exc
        ins["assigned_to"] = str(body.assigned_to).strip()
    sb.table("client_gstins").insert(ins).execute()
    return ins


@router.get("/{client_id}")
async def get_client(
    client_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_id, "client_id")
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    prof = get_user_profile(uid) or {}
    role = (prof.get("role") or "staff").lower()
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
    if role == "admin":
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
    hist = _history_for_client(sb, cid)
    return {**row, "reconciliation_history": hist}


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
    role = (prof.get("role") or "staff").lower()
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
    if role == "admin":
        if fo != uid:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    elif str(row.get("assigned_to", "")) != uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    updates: dict[str, Any] = {}
    for k in ("trade_name", "legal_name", "contact_name", "contact_email", "contact_phone"):
        v = getattr(body, k, None)
        if v is not None:
            updates[k] = v
    if body.assigned_to is not None:
        if role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can change assigned_to",
            )
        updates["assigned_to"] = body.assigned_to
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
    if (prof.get("role") or "staff").lower() != "admin":
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
    return None
