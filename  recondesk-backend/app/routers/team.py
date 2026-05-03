"""Team membership and invites: `/api/team`."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user, require_admin
from app.database import get_supabase, get_user_profile
from app.routers.clients import _resolve_firm_owner
from app.routers.reconciliation_api import _parse_uuid
from app.utils.audit import log_action
from app.utils.email import send_team_invite_email

router = APIRouter()
_log = logging.getLogger(__name__)


def _pg_unique_violation(exc: BaseException) -> bool:
    """Detect Postgres unique-violation (23505) from Supabase / PostgREST errors."""
    code = getattr(exc, "code", None)
    msg = str(exc).lower()
    return (
        code == "23505"
        or "duplicate key" in msg
        or "unique constraint" in msg
        or "already exists" in msg
    )


def _firm_owner_id(sb, uid: str) -> str:
    prof = get_user_profile(uid) or {}
    role = (prof.get("role") or "staff").lower()
    if role == "admin":
        return uid
    return _resolve_firm_owner(sb, uid)


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


class TeamInviteBody(BaseModel):
    email: str = Field(..., min_length=3)
    role: str


def _parse_invite_expiry(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            s = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _invite_still_valid(row: dict) -> bool:
    dt = _parse_invite_expiry(row.get("invite_expires_at"))
    if dt is None:
        return True
    return dt >= datetime.now(timezone.utc)


async def _invite_email_bg(
    to: str,
    inviter_firm_name: str,
    role: str,
    invite_token: str,
) -> None:
    try:
        await send_team_invite_email(
            to=to,
            inviter_firm_name=inviter_firm_name,
            role=role,
            invite_token=invite_token,
        )
    except Exception:
        _log.exception("team invite email failed to=%s", to)


def _profile_id_for_email(sb, email: str) -> Optional[str]:
    raw = email.strip()
    if not raw:
        return None
    ne = raw.lower()
    for candidate in (raw, ne):
        r = (
            sb.table("user_profiles")
            .select("id")
            .eq("email", candidate)
            .limit(1)
            .execute()
        )
        if r.data:
            return str(r.data[0]["id"])
    return None


@router.get("/members")
async def list_team_members(current_user: dict = Depends(get_current_active_user)):
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    owner_id = _firm_owner_id(sb, uid)

    res = (
        sb.table("team_members")
        .select("*")
        .eq("firm_owner_id", owner_id)
        .execute()
    )
    rows = list(res.data or [])

    included: list[dict[str, Any]] = []
    for r in rows:
        active = bool(r.get("is_active"))
        mid = r.get("member_user_id")
        if active:
            included.append(r)
            continue
        if mid is None or mid == "":
            included.append(r)

    mids = [
        str(r["member_user_id"])
        for r in included
        if r.get("member_user_id") not in (None, "")
    ]
    profiles_by_id: dict[str, dict] = {}
    if mids:
        pres = (
            sb.table("user_profiles")
            .select("id, email, full_name")
            .in_("id", mids)
            .execute()
        )
        for p in pres.data or []:
            profiles_by_id[str(p["id"])] = p

    out: list[dict[str, Any]] = []
    for r in included:
        tid = str(r["id"])
        role = str(r.get("role") or "")
        invite_exp = r.get("invite_expires_at")
        mid = r.get("member_user_id")
        active = bool(r.get("is_active"))

        if active and mid not in (None, ""):
            prof = profiles_by_id.get(str(mid), {})
            joined = r.get("accepted_at") or r.get("invited_at")
            out.append(
                {
                    "id": tid,
                    "member_user_id": str(mid),
                    "full_name": prof.get("full_name") or "",
                    "email": prof.get("email") or "",
                    "role": role,
                    "joined_at": joined,
                    "status": "active",
                    "invite_expires_at": invite_exp,
                }
            )
        elif not active and (mid is None or mid == ""):
            out.append(
                {
                    "id": tid,
                    "member_user_id": None,
                    "full_name": "",
                    "email": str(r.get("invited_email") or ""),
                    "role": role,
                    "joined_at": None,
                    "status": "pending",
                    "invite_expires_at": invite_exp,
                }
            )

    return out


@router.post("/invite")
async def invite_team_member(
    body: TeamInviteBody,
    background_tasks: BackgroundTasks,
    admin_id: str = Depends(require_admin),
):
    role_norm = (body.role or "").strip().lower()
    if role_norm not in ("admin", "staff"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="role must be 'admin' or 'staff'",
        )

    norm_email = _norm_email(body.email)
    if not norm_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email",
        )

    sb = get_supabase()

    admin_prof = get_user_profile(admin_id) or {}
    inviter_email = _norm_email(str(admin_prof.get("email") or ""))
    if inviter_email and norm_email == inviter_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot invite your own firm owner email.",
        )

    pending_for_email = (
        sb.table("team_members")
        .select("id, invite_expires_at")
        .eq("firm_owner_id", admin_id)
        .eq("invited_email", norm_email)
        .is_("member_user_id", "null")
        .eq("is_active", False)
        .execute()
    )
    for er in pending_for_email.data or []:
        if _invite_still_valid(er):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This email already has a pending invitation.",
            )

    pid = _profile_id_for_email(sb, norm_email)
    if pid:
        if pid == admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already the firm owner.",
            )
        active_member = (
            sb.table("team_members")
            .select("id")
            .eq("firm_owner_id", admin_id)
            .eq("member_user_id", pid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if active_member.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This user is already a team member.",
            )

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)
    expires_iso = expires_at.isoformat()
    invited_iso = now.isoformat()

    row_id = str(uuid4())
    insert_payload: dict[str, Any] = {
        "id": row_id,
        "firm_owner_id": admin_id,
        "invited_email": norm_email,
        "role": role_norm,
        "invite_token": token,
        "invite_expires_at": expires_iso,
        "is_active": False,
        "invited_at": invited_iso,
    }

    logged_member_id = row_id

    try:
        sb.table("team_members").insert(insert_payload).execute()
    except Exception as exc:
        if not _pg_unique_violation(exc):
            raise
        sb.table("team_members").update(
            {
                "invite_token": token,
                "invite_expires_at": expires_iso,
                "role": role_norm,
                "invited_at": invited_iso,
                "is_active": False,
            }
        ).eq("firm_owner_id", admin_id).eq("invited_email", norm_email).is_(
            "member_user_id", "null"
        ).execute()
        refreshed = (
            sb.table("team_members")
            .select("id")
            .eq("firm_owner_id", admin_id)
            .eq("invited_email", norm_email)
            .is_("member_user_id", "null")
            .limit(1)
            .execute()
        )
        if not refreshed.data:
            raise
        logged_member_id = str(refreshed.data[0]["id"])

    firm_name = str(admin_prof.get("firm_name") or "").strip()
    background_tasks.add_task(
        _invite_email_bg,
        norm_email,
        firm_name,
        role_norm,
        token,
    )

    await log_action(
        admin_id,
        "TEAM_MEMBER_INVITED",
        "team_member",
        logged_member_id,
        {"invited_email": norm_email, "role": role_norm},
    )

    return {"invited": True}


@router.post("/accept/{token}")
async def accept_team_invite(token: str):
    sb = get_supabase()
    token_s = (token or "").strip()
    if not token_s:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation link.",
        )

    now_iso = datetime.now(timezone.utc).isoformat()

    res = (
        sb.table("team_members")
        .select("*")
        .eq("invite_token", token_s)
        .eq("is_active", False)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation not found or already used.",
        )

    row = res.data[0]
    row_uuid = row.get("id")
    if not row_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation not found or already used.",
        )

    exp = _parse_invite_expiry(row.get("invite_expires_at"))
    if exp is not None and exp < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired.",
        )

    invited_email = str(row.get("invited_email") or "").strip()
    role = str(row.get("role") or "staff")
    firm_owner_id = str(row.get("firm_owner_id") or "").strip()

    uid = _profile_id_for_email(sb, invited_email)

    if uid:
        existing = (
            sb.table("team_members")
            .select("id")
            .eq("firm_owner_id", firm_owner_id)
            .eq("member_user_id", uid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if existing.data:
            sb.table("team_members").update(
                {"is_active": False, "accepted_at": now_iso}
            ).eq("id", str(row_uuid)).execute()
            return {"status": "accepted", "redirect": "/dashboard"}

        update_payload = {
            "member_user_id": str(uid),
            "is_active": True,
            "accepted_at": now_iso,
        }
        try:
            sb.table("team_members").update(update_payload).eq(
                "id", str(row_uuid)
            ).execute()
        except Exception as exc:
            if _pg_unique_violation(exc):
                sb.table("team_members").update(
                    {"is_active": False, "accepted_at": now_iso}
                ).eq("id", str(row_uuid)).execute()
                return {"status": "accepted", "redirect": "/dashboard"}
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not accept invitation.",
            ) from exc

        return {"status": "accepted", "redirect": "/dashboard"}

    return {
        "status": "signup_required",
        "redirect": "/signup",
        "email": invited_email,
        "role": role,
        "token": token_s,
    }


@router.delete("/members/{member_id}")
async def remove_team_member(
    member_id: str,
    admin_id: str = Depends(require_admin),
):
    mid = _parse_uuid(member_id, "member_id")
    sb = get_supabase()

    found = (
        sb.table("team_members")
        .select("id")
        .eq("id", mid)
        .eq("firm_owner_id", admin_id)
        .limit(1)
        .execute()
    )
    if not found.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found",
        )

    sb.table("team_members").update({"is_active": False}).eq("id", mid).eq(
        "firm_owner_id", admin_id
    ).execute()

    await log_action(
        admin_id,
        "TEAM_MEMBER_REMOVED",
        "team_member",
        mid,
        {},
    )

    return {"removed": True}
