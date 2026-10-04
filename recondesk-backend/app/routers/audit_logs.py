"""Workspace audit log listing — admin only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.auth import require_admin
from app.database import get_db

router = APIRouter()


import logging

logger = logging.getLogger(__name__)


def _parse_iso_datetime(value: str, param: str) -> datetime:
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
        return dt
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

    parsed_from = _parse_iso_datetime(from_date, "from_date") if isinstance(from_date, str) and from_date.strip() else None
    parsed_to = _parse_iso_datetime(to_date, "to_date") if isinstance(to_date, str) and to_date.strip() else None
    user_id_val = user_id.strip() if isinstance(user_id, str) and user_id.strip() else None
    action_val = action.strip() if isinstance(action, str) and action.strip() else None
    limit_val = limit if isinstance(limit, int) else 50
    offset_val = offset if isinstance(offset, int) else 0

    # 1. Primary: AWS Aurora PostgreSQL repository
    try:
        from app.repositories.portal_and_audit import get_portal_and_audit_repository
        repo = get_portal_and_audit_repository()
        rows, total = repo.list_audit_logs(
            firm_id=effective_firm,
            user_id=user_id_val,
            action=action_val,
            from_date=parsed_from,
            to_date=parsed_to,
            limit=limit_val,
            offset=offset_val,
        )
        return {
            "data": rows,
            "total": total,
            "limit": limit_val,
            "offset": offset_val,
        }
    except Exception as aurora_exc:
        logger.warning(
            "Aurora list_audit_logs failed firm_id=%s: %s; falling back to Supabase",
            effective_firm,
            aurora_exc,
        )

    # 2. Supabase Fallback (temporary, non-blocking)
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

    if user_id_val:
        q = q.eq("user_id", user_id_val)
    if action_val:
        q = q.eq("action", action_val)
    if parsed_from:
        q = q.gte("created_at", parsed_from.isoformat())
    if parsed_to:
        q = q.lte("created_at", parsed_to.isoformat())

    end = offset_val + limit_val - 1
    res = q.range(offset_val, end).execute()
    rows: list[dict[str, Any]] = list(res.data or [])
    total = int(res.count or len(rows))

    return {
        "data": rows,
        "total": total,
        "limit": limit_val,
        "offset": offset_val,
    }
