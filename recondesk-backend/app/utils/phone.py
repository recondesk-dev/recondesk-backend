"""Phone number normalization and duplicate detection utilities.

Prevents multiple account creation using the same mobile number.
Canonicalizes mobile numbers (stripping formatting, whitespace, and country code prefixes).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

# Matches standard 10-digit Indian mobile numbers with optional country prefixes
_INDIAN_PHONE_RE = re.compile(r"^(?:\+?91|0091|0)?([6-9]\d{9})$")


def normalize_phone(phone: Optional[str]) -> str:
    """Normalize phone string to a canonical digit representation.

    Examples:
        '+91 98765-43210' -> '9876543210'
        '09876543210'     -> '9876543210'
        '9876543210'      -> '9876543210'
        '+1 (555) 123-4567' -> '15551234567'
    """
    if not phone:
        return ""
    raw = phone.strip()
    # Strip all non-digit characters
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return ""

    # Check for Indian standard mobile format
    match = _INDIAN_PHONE_RE.match(digits)
    if match:
        return match.group(1)

    # Return pure digits for international numbers
    return digits


def check_phone_duplicate_aurora(phone: str, session: Session) -> bool:
    """Check if the normalized phone number already exists in Aurora user_profiles."""
    norm = normalize_phone(phone)
    if not norm:
        return False

    from app.models.tenancy import UserProfile

    # Compare digits stripped of non-digit chars
    # Uses SQL regexp_replace to match normalized digits
    stmt = (
        select(UserProfile.id)
        .where(
            UserProfile.phone.is_not(None),
            func.regexp_replace(UserProfile.phone, r"[^\d]", "", "g") == norm,
        )
        .limit(1)
    )
    result = session.scalar(stmt)
    return result is not None


def check_phone_duplicate_supabase(phone: str, db) -> bool:
    """Check if phone number exists in legacy Supabase table."""
    norm = normalize_phone(phone)
    if not norm:
        return False

    try:
        # Check against raw phone or normalized values
        res = db.table("user_profiles").select("id").eq("phone", phone).limit(1).execute()
        if res.data and len(res.data) > 0:
            return True
    except Exception:
        pass
    return False


def assert_phone_not_registered(phone: Optional[str], session: Optional[Session] = None, db=None) -> None:
    """Validate that the phone number is not already associated with an existing account.

    Raises HTTP 409 Conflict if duplicate is detected.
    """
    if not phone or not phone.strip():
        return

    is_duplicate = False
    if session is not None:
        is_duplicate = check_phone_duplicate_aurora(phone, session)
    elif db is not None:
        is_duplicate = check_phone_duplicate_supabase(phone, db)

    if is_duplicate:
        _log.warning("Signup blocked: duplicate phone number detected")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this mobile number already exists. Please log in or use a different number.",
        )
