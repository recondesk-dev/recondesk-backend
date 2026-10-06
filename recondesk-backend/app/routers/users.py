"""User profile actions: `/api/users`."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_active_user
from app.database import get_supabase, get_user_profile
from app.models.user import (
    AutoApproveThresholdUpdate,
    ProfileUpdateRequest,
    UserProfileResponse,
)
from app.services.tenancy_sync import (
    mirror_user_profile_update_to_aurora,
    mirror_user_profile_upsert_to_aurora,
)

router = APIRouter()
_log = logging.getLogger(__name__)

_GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)
_PHONE_DIGITS_RE = re.compile(r"^[6-9]\d{9}$")


def _pg_unique_violation(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    msg = str(exc).lower()
    return (
        code == "23505"
        or "duplicate key" in msg
        or "unique constraint" in msg
        or "already exists" in msg
    )


def _normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if not _PHONE_DIGITS_RE.fullmatch(digits):
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return digits


def _normalize_gstin(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper().replace(" ", "")
    if not text:
        return None
    if not _GSTIN_RE.fullmatch(text):
        raise ValueError("Invalid GSTIN format")
    return text


@router.patch("/onboarding-complete")
async def onboarding_complete(current_user: dict = Depends(get_current_active_user)):
    uid = str(current_user.get("id", "")).strip()
    get_supabase().table("user_profiles").update({"onboarding_completed": True}).eq(
        "id", uid
    ).execute()
    mirror_user_profile_update_to_aurora(uid, {"onboarding_completed": True})
    return {"success": True}


@router.post("/demo-tour-seen")
@router.patch("/demo-tour-seen")
async def set_demo_tour_seen(current_user: dict = Depends(get_current_active_user)):
    uid = str(current_user.get("id", "")).strip()
    get_supabase().table("user_profiles").update({"demo_tour_seen": True}).eq(
        "id", uid
    ).execute()
    mirror_user_profile_update_to_aurora(uid, {"demo_tour_seen": True})
    return {"success": True}


@router.post("/showcase-seen")
@router.patch("/showcase-seen")
async def set_showcase_seen(current_user: dict = Depends(get_current_active_user)):
    uid = str(current_user.get("id", "")).strip()
    get_supabase().table("user_profiles").update({"showcase_seen": True}).eq(
        "id", uid
    ).execute()
    mirror_user_profile_update_to_aurora(uid, {"showcase_seen": True})
    return {"success": True}


@router.patch("/profile", response_model=UserProfileResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_active_user),
):
    uid = str(current_user.get("id", "")).strip()
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    full_name = payload.full_name.strip()
    if not full_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Full name is required",
        )

    try:
        phone = _normalize_phone(payload.phone)
        firm_gstin = _normalize_gstin(payload.firm_gstin)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    firm_name = (payload.firm_name or "").strip() or None
    icai = (payload.icai_membership_number or "").strip() or None
    firm_city = (payload.firm_city or "").strip() or None

    sb = get_supabase()
    existing = get_user_profile(uid)
    stored_email = str(
        (existing or {}).get("email") or current_user.get("email") or ""
    ).strip().lower()

    profile_fields = {
        "full_name": full_name,
        "phone": phone,
        "firm_name": firm_name,
        "icai_membership_number": icai,
        "firm_gstin": firm_gstin,
        "firm_city": firm_city,
        "is_active": True,
    }

    try:
        if existing:
            sb.table("user_profiles").update(profile_fields).eq("id", uid).execute()
            mirror_user_profile_update_to_aurora(uid, profile_fields)
        else:
            insert_row = {"id": uid, **profile_fields}
            if stored_email:
                insert_row["email"] = stored_email
            try:
                sb.table("user_profiles").insert(insert_row).execute()
                mirror_user_profile_upsert_to_aurora(insert_row, uid)
            except Exception as exc:  # noqa: BLE001
                if _pg_unique_violation(exc):
                    sb.table("user_profiles").update(profile_fields).eq(
                        "id", uid
                    ).execute()
                    mirror_user_profile_update_to_aurora(uid, profile_fields)
                else:
                    raise
    except Exception as exc:  # noqa: BLE001
        _log.exception("Profile upsert failed for user_id=%s", uid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    profile = get_user_profile(uid)
    if profile is None:
        _log.error("Profile upsert succeeded but reload failed for user_id=%s", uid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Profile saved but could not be loaded after upsert",
        )
    profile["role"] = str(profile.get("role") or (existing or {}).get("role") or "admin")
    if profile.get("auto_approve_confidence_threshold") is None:
        profile["auto_approve_confidence_threshold"] = 95
    return UserProfileResponse(**profile)


@router.patch("/auto-approve-threshold", response_model=UserProfileResponse)
async def update_auto_approve_threshold(
    payload: AutoApproveThresholdUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """Set firm confidence threshold for Review Required → Auto-Approved triage."""
    uid = str(current_user.get("id", "")).strip()
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    role = str(current_user.get("role") or "admin").strip().lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update the auto-approve threshold",
        )

    threshold = int(payload.auto_approve_confidence_threshold)
    sb = get_supabase()
    existing = get_user_profile(uid)
    try:
        if existing:
            sb.table("user_profiles").update(
                {"auto_approve_confidence_threshold": threshold}
            ).eq("id", uid).execute()
            mirror_user_profile_update_to_aurora(
                uid, {"auto_approve_confidence_threshold": threshold}
            )
        else:
            insert_row = {
                "id": uid,
                "auto_approve_confidence_threshold": threshold,
                "is_active": True,
            }
            email = str(current_user.get("email") or "").strip().lower()
            if email:
                insert_row["email"] = email
            sb.table("user_profiles").insert(insert_row).execute()
            mirror_user_profile_upsert_to_aurora(insert_row, uid)
    except Exception as exc:  # noqa: BLE001
        _log.exception("Failed to update auto-approve threshold for user_id=%s", uid)
        msg = str(exc)
        lowered = msg.lower()
        if (
            "auto_approve_confidence_threshold" in lowered
            and (
                "does not exist" in lowered
                or "could not find" in lowered
                or "schema cache" in lowered
            )
        ):
            msg = (
                "Database is missing column auto_approve_confidence_threshold. "
                "Run alembic revision auto_approve_confidence "
                "(or ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS "
                "auto_approve_confidence_threshold INTEGER NOT NULL DEFAULT 95)."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=msg,
        ) from exc

    profile = get_user_profile(uid)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Threshold saved but profile could not be reloaded",
        )
    profile["role"] = str(profile.get("role") or role or "admin")
    if profile.get("auto_approve_confidence_threshold") is None:
        profile["auto_approve_confidence_threshold"] = threshold
    return UserProfileResponse(**profile)
