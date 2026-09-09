"""Admin-only utilities (digest, monitoring helpers)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth import get_current_active_user
from app.config import settings
from app.database import supabase_client

router = APIRouter()


def _admin_user_ids() -> list[str]:
    aid = (settings.ADMIN_USER_ID or "").strip()
    return [aid] if aid else []


@router.get("/digest")
async def admin_digest(
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    """Aggregated daily stats for operations; restricted to configured admin user(s)."""
    uid = str(current_user.get("id") or "").strip()
    if uid not in _admin_user_ids():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    iso = today_start.isoformat()

    def _count(table: str, apply_filters):
        q = db.table(table).select("id", count="exact", head=True)
        q = apply_filters(q)
        r = q.execute()
        return int(r.count or 0)

    new_signups_today = _count("user_profiles", lambda q: q.gte("created_at", iso))
    runs_completed_today = _count(
        "reconciliation_run",
        lambda q: q.in_("status", ["COMPLETED", "FINAL"]).gte("completed_at", iso),
    )
    runs_failed_today = _count(
        "reconciliation_run",
        lambda q: q.in_("status", ["FAILED", "failed"]).gte("updated_at", iso),
    )
    pay_rows = (
        db.table("payments")
        .select("total_amount_paise, amount_paise")
        .eq("status", "paid")
        .gte("created_at", iso)
        .execute()
    )
    pdata = pay_rows.data or []
    payments_today = len(pdata)
    revenue_today_paise = sum(
        int(
            (r.get("total_amount_paise") if r.get("total_amount_paise") is not None else r.get("amount_paise"))
            or 0,
        )
        for r in pdata
    )

    total_users = _count("user_profiles", lambda q: q)
    total_runs_ever = _count("reconciliation_run", lambda q: q)

    return {
        "date": now.date().isoformat(),
        "new_signups_today": new_signups_today,
        "runs_completed_today": runs_completed_today,
        "runs_failed_today": runs_failed_today,
        "payments_today": payments_today,
        "revenue_today_paise": revenue_today_paise,
        "total_users": total_users,
        "total_runs_ever": total_runs_ever,
    }
