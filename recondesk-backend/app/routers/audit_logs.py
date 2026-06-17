"""Workspace audit log listing — admin only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.auth import require_admin
from app.database import get_db

router = APIRouter()


def _parse_iso_datetime(value: str, param: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {param}",
        )
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {param}",
        ) from exc


@router.get("")
async def list_audit_logs(
    firm_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin_id: str = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """List audit log entries for the admin's workspace. Insert-only table — no mutations."""
    effective_firm = (firm_id or admin_id).strip()
    if effective_firm != admin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another firm's audit logs",
        )

    q = (
        db.table("audit_logs")
        .select(
            "id, firm_id, user_id, user_name, role, action, entity_type, "
            "entity_id, entity_label, metadata, created_at",
            count="exact",
        )
        .eq("firm_id", effective_firm)
        .order("created_at", desc=True)
    )

    if user_id:
        q = q.eq("user_id", user_id.strip())
    if action:
        q = q.eq("action", action.strip())
    if from_date:
        q = q.gte("created_at", _parse_iso_datetime(from_date, "from_date"))
    if to_date:
        q = q.lte("created_at", _parse_iso_datetime(to_date, "to_date"))

    end = offset + limit - 1
    res = q.range(offset, end).execute()
    rows: list[dict[str, Any]] = list(res.data or [])
    total = int(res.count or len(rows))

    return {
        "data": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
