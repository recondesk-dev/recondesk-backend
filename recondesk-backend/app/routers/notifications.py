from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from app.auth import get_current_active_user
from app.database import supabase_client

router = APIRouter()
_log = logging.getLogger(__name__)


class NotificationPreferencesModel(BaseModel):
    run_completed: bool
    runs_expiring_soon: bool
    payment_receipts: bool
    rule37_alerts: bool = True


def _prefs_from_row(pref: dict) -> NotificationPreferencesModel:
    return NotificationPreferencesModel(
        run_completed=pref.get("run_completed", True),
        runs_expiring_soon=pref.get("runs_expiring_soon", True),
        payment_receipts=pref.get("payment_receipts", True),
        rule37_alerts=pref.get("rule37_alerts", True),
    )


@router.get("/preferences", response_model=NotificationPreferencesModel)
async def get_preferences(
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    """Retrieve the current user's notification preferences.

    If no preferences record exists yet, it creates one with defaults.
    """
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User identity not found",
        )

    # 1. Primary: AWS Aurora PostgreSQL repository
    try:
        from app.repositories.portal_and_audit import get_portal_and_audit_repository
        repo = get_portal_and_audit_repository()
        pref = repo.get_notification_preferences(user_id)
        if pref:
            return _prefs_from_row(pref)
        # Create default preferences in Aurora
        created = repo.upsert_notification_preferences(
            user_id,
            run_completed=True,
            runs_expiring_soon=True,
            payment_receipts=True,
            rule37_alerts=True,
        )
        return _prefs_from_row(created)
    except Exception as aurora_exc:
        _log.warning(
            "Aurora get_preferences failed for user %s: %s; falling back to Supabase",
            user_id,
            aurora_exc,
        )

    # 2. Supabase Fallback (temporary, non-blocking)
    try:
        res = (
            db.table("notification_preferences")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return _prefs_from_row(res.data[0])

        # Create defaults
        now_str = datetime.now(timezone.utc).isoformat()
        default_pref = {
            "user_id": user_id,
            "run_completed": True,
            "runs_expiring_soon": True,
            "payment_receipts": True,
            "rule37_alerts": True,
            "created_at": now_str,
            "updated_at": now_str,
        }
        db.table("notification_preferences").insert(default_pref).execute()
        return NotificationPreferencesModel(
            run_completed=True,
            runs_expiring_soon=True,
            payment_receipts=True,
            rule37_alerts=True,
        )
    except Exception as exc:
        _log.exception(
            "Failed to get/create notification preferences for user %s", user_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch notification preferences: {exc}",
        )


@router.put("/preferences", response_model=NotificationPreferencesModel)
async def update_preferences(
    payload: NotificationPreferencesModel,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    """Update user notification preferences."""
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User identity not found",
        )

    # 1. Primary: AWS Aurora PostgreSQL repository
    try:
        from app.repositories.portal_and_audit import get_portal_and_audit_repository
        repo = get_portal_and_audit_repository()
        updated = repo.upsert_notification_preferences(
            user_id,
            run_completed=payload.run_completed,
            runs_expiring_soon=payload.runs_expiring_soon,
            payment_receipts=payload.payment_receipts,
            rule37_alerts=payload.rule37_alerts,
        )
        return _prefs_from_row(updated)
    except Exception as aurora_exc:
        _log.warning(
            "Aurora update_preferences failed for user %s: %s; falling back to Supabase",
            user_id,
            aurora_exc,
        )

    # 2. Supabase Fallback (temporary, non-blocking)
    try:
        now_str = datetime.now(timezone.utc).isoformat()
        upsert_data = {
            "user_id": user_id,
            "run_completed": payload.run_completed,
            "runs_expiring_soon": payload.runs_expiring_soon,
            "payment_receipts": payload.payment_receipts,
            "rule37_alerts": payload.rule37_alerts,
            "updated_at": now_str,
        }
        res = (
            db.table("notification_preferences")
            .upsert(upsert_data, on_conflict="user_id")
            .execute()
        )
        if res.data and len(res.data) > 0:
            return _prefs_from_row(res.data[0])

        return payload
    except Exception as exc:
        _log.exception(
            "Failed to update notification preferences for user %s", user_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update notification preferences: {exc}",
        )
