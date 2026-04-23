"""Mismatch notes: `/api/notes`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase, get_user_profile
from app.routers.reconciliation_api import _parse_uuid
from app.services import reconciliation_outcomes as ro
from app.services.firm_access import (
    assert_firm_read_notes,
    get_firm_owner_for_client,
    user_can_access_firm,
)

router = APIRouter()


class NoteCreate(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)
    record_type: str = Field(
        ...,
        pattern="^(matched|missed_itc|wrongful_risk|rule37_warning|blocked_credit|credit_note)$",
    )
    run_id: str
    note_type: str = Field(
        ..., pattern="^(dispute|clarification|resolved|escalated)$"
    )
    severity: str = Field(default="low", pattern="^(low|medium|high)$")


class NoteUpdate(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)
    note_type: Optional[str] = Field(
        default=None, pattern="^(dispute|clarification|resolved|escalated)$"
    )
    severity: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")


def _assert_run_not_locked_for_mutation(sb, run_id: str) -> None:
    r = (
        sb.table("reconciliation_run")
        .select("is_locked")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if r.data and bool(r.data[0].get("is_locked")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Notes cannot be edited or deleted after a run is finalized.",
        )


def _assert_record_in_run(sb, run_id: str, record_id: str) -> None:
    p = ro.load_payload(sb, run_id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="reconciliation data not found for run",
        )
    rows, _c, _s = ro.build_outcome_rows(sb, run_id, p)
    if not any(r.id == record_id for r in rows):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="record not found in run results",
        )


@router.post("/{record_id}", status_code=status.HTTP_201_CREATED)
async def add_note(
    record_id: str,
    body: NoteCreate,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(body.run_id, "run_id")
    sb = get_supabase()
    r = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, is_locked, status")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    row = r.data[0]
    cgid = str(row.get("client_gstin_id", ""))
    firm_owner = get_firm_owner_for_client(sb, cgid)
    uid = str(current_user.get("id", ""))
    if not user_can_access_firm(sb, current_user, firm_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed to add notes for this run",
        )
    _assert_record_in_run(sb, rid, record_id)
    now = datetime.now(timezone.utc).isoformat()
    ins = {
        "record_id": record_id,
        "run_id": rid,
        "user_id": uid,
        "firm_owner_id": firm_owner,
        "note": body.note,
        "record_type": body.record_type,
        "note_type": body.note_type,
        "severity": body.severity,
        "created_at": now,
    }
    sb.table("mismatch_notes").insert(ins).execute()
    return {
        "record_id": record_id,
        "run_id": rid,
        "message": "Note added",
    }


@router.get("/{record_id}")
async def list_notes(
    record_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    res = (
        sb.table("mismatch_notes")
        .select("id, run_id, user_id, firm_owner_id, note, note_type, severity, created_at")
        .eq("record_id", record_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return []
    cgid = (
        sb.table("reconciliation_run")
        .select("client_gstin_id")
        .eq("id", str(rows[0].get("run_id")))
        .limit(1)
        .execute()
    )
    cgi = str((cgid.data or [{}])[0].get("client_gstin_id", ""))
    fo = get_firm_owner_for_client(sb, cgi)
    assert_firm_read_notes(sb, current_user, fo, cgi)
    uids = {str(x.get("user_id")) for x in rows if x.get("user_id")}
    profs: dict[str, str] = {}
    for u in uids:
        p = get_user_profile(u) or {}
        if p.get("full_name"):
            profs[u] = str(p.get("full_name"))
    return [
        {
            "author_full_name": profs.get(str(n.get("user_id", "")), "Unknown"),
            "created_at": n.get("created_at"),
            "note": n.get("note"),
            "note_type": n.get("note_type"),
            "severity": n.get("severity"),
        }
        for n in rows
    ]


@router.patch("/entry/{note_id}")
async def patch_note(
    note_id: str,
    body: NoteUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    nid = _parse_uuid(note_id, "note_id")
    sb = get_supabase()
    res = (
        sb.table("mismatch_notes")
        .select("id, run_id, user_id, firm_owner_id")
        .eq("id", nid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="note not found",
        )
    n = res.data[0]
    run_id = str(n.get("run_id", ""))
    _assert_run_not_locked_for_mutation(sb, run_id)
    cgi = (
        sb.table("reconciliation_run")
        .select("client_gstin_id")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    cgid = str((cgi.data or [{}])[0].get("client_gstin_id", ""))
    fo = get_firm_owner_for_client(sb, cgid)
    if not user_can_access_firm(sb, current_user, fo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not allowed",
        )
    updates = {"note": body.note}
    if body.note_type is not None:
        updates["note_type"] = body.note_type
    if body.severity is not None:
        updates["severity"] = body.severity
    sb.table("mismatch_notes").update(updates).eq("id", nid).execute()
    return {"id": nid, "message": "Note updated"}


@router.delete("/entry/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    nid = _parse_uuid(note_id, "note_id")
    sb = get_supabase()
    res = (
        sb.table("mismatch_notes")
        .select("id, run_id")
        .eq("id", nid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="note not found",
        )
    run_id = str(res.data[0].get("run_id", ""))
    _assert_run_not_locked_for_mutation(sb, run_id)
    cgi = (
        sb.table("reconciliation_run")
        .select("client_gstin_id")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    cgid = str((cgi.data or [{}])[0].get("client_gstin_id", ""))
    fo = get_firm_owner_for_client(sb, cgid)
    if not user_can_access_firm(sb, current_user, fo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not allowed",
        )
    sb.table("mismatch_notes").delete().eq("id", nid).execute()
    return None
