"""User profile actions: `/api/users`."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr

from app.auth import get_current_active_user
from app.database import get_supabase, get_user_profile
from app.models.user import ProfileUpdateRequest, UserProfileResponse

router = APIRouter()

_GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)
_PHONE_DIGITS_RE = re.compile(r"^[6-9]\d{9}$")


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
    email = str(payload.email).strip().lower()

    row = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "firm_name": firm_name,
        "icai_membership_number": icai,
        "firm_gstin": firm_gstin,
        "firm_city": firm_city,
    }

    sb = get_supabase()
    existing = get_user_profile(uid)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found",
        )

    prev_email = str(existing.get("email") or "").strip().lower()
    if email != prev_email:
        try:
            sb.auth.admin.update_user_by_id(uid, {"email": email})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not update email. It may already be in use.",
            ) from exc

    try:
        sb.table("user_profiles").update(row).eq("id", uid).execute()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save profile",
        ) from exc

    profile = get_user_profile(uid)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Profile saved but could not be loaded",
        )
    profile["role"] = str(profile.get("role") or existing.get("role") or "admin")
    return UserProfileResponse(**profile)
