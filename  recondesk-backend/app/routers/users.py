"""User profile actions: `/api/users`."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_active_user
from app.database import get_supabase

router = APIRouter()


@router.patch("/onboarding-complete")
async def onboarding_complete(current_user: dict = Depends(get_current_active_user)):
    uid = str(current_user.get("id", "")).strip()
    get_supabase().table("user_profiles").update({"onboarding_completed": True}).eq(
        "id", uid
    ).execute()
    return {"success": True}
