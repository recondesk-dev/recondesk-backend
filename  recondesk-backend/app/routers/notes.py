"""Mismatch notes: `/api/notes`.

``mismatch_notes`` stores *record_type* as only ``'gstr'`` or ``'pr'`` (DB check).
API bodies may use legacy category names; they are mapped before insert.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_active_user
from app.database import get_supabase
from app.routers.reconciliation_api import _parse_uuid

router = APIRouter()

# API → DB: only 'gstr' and 'pr' are allowed in mismatch_notes.record_type
_PR_LABELS = frozenset(
    {
        "matched",
        "missed_itc",
        "wrongful_risk",
        "credit_note",
        "rule37_warning",
        "blocked_credit",
        "pr",
    }
)


def _normalize_record_type_to_db(value: str) -> str:
    s = (value or "").strip().lower()
    if s == "gstr":
        return "gstr"
    if s == "pr" or s in _PR_LABELS:
        return "pr"
    # Unknown label — safest default is purchase-register side
    return "pr"


def _new_note_row_response(
    sb,
    row: dict,
) -> dict:
    """Shape id, record_id, record_type, run_id, note, created_at, author_full_name."""
    uid = str(row.get("user_id", "") or "")
    names = _full_names_by_user_ids(sb, {uid} if uid else set())
    return {
        "id": row.get("id"),
        "record_id": row.get("record_id"),
        "record_type": row.get("record_type"),
        "run_id": row.get("run_id"),
        "note": row.get("note"),
        "created_at": row.get("created_at"),
        "author_full_name": names.get(uid, "Unknown") if uid else "Unknown",
    }


class NoteCreate(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)
    run_id: str
    # Accept legacy outcome categories or 'gstr' / 'pr' (mapped to DB check constraint)
    record_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
    )

    @field_validator("record_type", mode="before")
    @classmethod
    def strip_record_type(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class NoteUpdate(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)


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


def _full_names_by_user_ids(sb, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    ulist = [u for u in user_ids if u]
    if not ulist:
        return {}
    r = (
        sb.table("user_profiles")
        .select("id, full_name")
        .in_("id", ulist)
        .execute()
    )
    out: dict[str, str] = {}
    for row in r.data or []:
        uid = str(row.get("id", "") or "")
        fn = row.get("full_name")
        if uid and fn is not None:
            out[uid] = str(fn)
    return out


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
        .select("id")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    uid = str(current_user.get("id", ""))
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )
    db_type = _normalize_record_type_to_db(body.record_type)
    now = datetime.now(timezone.utc).isoformat()
    ins = {
        "record_id": record_id,
        "run_id": rid,
        "user_id": uid,
        "note": body.note,
        "record_type": db_type,
        "created_at": now,
    }
    result = sb.table("mismatch_notes").insert(ins).execute()
    if not result.data:
        return {}
    row0 = result.data[0] if isinstance(result.data, list) else result.data
    if not isinstance(row0, dict):
        return {}
    return _new_note_row_response(sb, row0)


@router.get("/{record_id}")
async def list_notes(
    record_id: str,
    _user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    res = (
        sb.table("mismatch_notes")
        .select("id, record_id, record_type, run_id, user_id, note, created_at")
        .eq("record_id", record_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = [n for n in (res.data or []) if isinstance(n, dict)]
    uids = {str(x.get("user_id")) for x in rows if x.get("user_id")}
    profs = _full_names_by_user_ids(sb, uids)
    return [
        {
            "id": n.get("id"),
            "record_id": n.get("record_id"),
            "record_type": n.get("record_type"),
            "run_id": n.get("run_id"),
            "note": n.get("note"),
            "created_at": n.get("created_at"),
            "author_full_name": profs.get(str(n.get("user_id", "")), "Unknown"),
        }
        for n in rows
    ]


@router.patch("/entry/{note_id}")
async def patch_note(
    note_id: str,
    body: NoteUpdate,
    _user: dict = Depends(get_current_active_user),
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
    n = res.data[0]
    run_id = str(n.get("run_id", ""))
    _assert_run_not_locked_for_mutation(sb, run_id)
    sb.table("mismatch_notes").update({"note": body.note}).eq("id", nid).execute()
    return {"id": nid, "message": "Note updated"}


@router.delete("/entry/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: str,
    _user: dict = Depends(get_current_active_user),
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
    n = res.data[0]
    run_id = str(n.get("run_id", ""))
    _assert_run_not_locked_for_mutation(sb, run_id)
    sb.table("mismatch_notes").delete().eq("id", nid).execute()
    return None
