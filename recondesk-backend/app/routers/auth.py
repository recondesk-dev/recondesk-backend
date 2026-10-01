from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, ValidationError

from app.auth import (
    AuthenticatedUser,
    get_current_active_user,
    get_current_user,
    get_current_user_id,
    get_user_role,
)
from app.database import get_db, get_supabase, get_user_profile
from app.models.user import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    UserProfileResponse,
)
from app.utils.audit import log_action
from app.utils.email import (
    send_monthly_reminder_email,
    send_team_invite_email,
    send_welcome_email,
)
from app.utils.email_domain import validate_email_mx
from app.utils.login_throttle import (
    is_login_locked,
    record_login_failure,
    record_login_success,
)
from app.utils.rate_limit import limiter

router = APIRouter()
webhook_router = APIRouter()
test_router = APIRouter()
_log = logging.getLogger(__name__)


class _UserProfileWebhookRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    full_name: str | None = None
    firm_name: str | None = None


class UserProfileInsertWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    table: str
    record: _UserProfileWebhookRecord
    schema: str = "public"


async def _webhook_error(
    request: Request,
    message: str,
    *,
    entity_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    meta: dict[str, Any] = {"error_message": message[:2000]}
    if extra:
        meta.update(extra)
    await log_action(
        None,
        "WEBHOOK_ERROR",
        "webhook",
        entity_id,
        meta,
        ip_address=_client_ip(request),
    )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _signup_welcome_email_task(to: str, full_name: str) -> None:
    try:
        await send_welcome_email(to=to, full_name=full_name)
    except Exception:
        _log.exception("welcome email background task failed to=%s", to)


# ── POST /auth/signup ─────────────────────────────────────────────────────────

@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def signup(
    request: Request,
    payload: SignupRequest,
    background_tasks: BackgroundTasks,
):
    """Register a new user and create their profile row."""
    # Check domain MX records to reject invalid/nonexistent domains before creating account
    validate_email_mx(str(payload.email))

    db = get_db()
    ip = _client_ip(request)
    full_name = str(payload.full_name or "").strip()
    firm_name = str(payload.firm_name or "").strip()
    phone = str(payload.phone or "").strip() if payload.phone else ""

    try:
        auth_response = db.auth.sign_up(
            {
                "email": payload.email,
                "password": payload.password,
                "options": {
                    "data": {
                        "full_name": full_name,
                        "firm_name": firm_name,
                        "phone": phone,
                    }
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("sign_up failed: %s", type(exc).__name__)
        await log_action(
            None,
            "SIGNUP",
            "user",
            None,
            {"result": "failed"},
            ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to complete sign up. Check your details and try again.",
        ) from exc

    if not auth_response.user:
        await log_action(
            None,
            "SIGNUP",
            "user",
            None,
            {"result": "no_user"},
            ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sign-up failed. The email may already be registered.",
        )

    user_id = str(auth_response.user.id)
    await log_action(
        user_id,
        "SIGNUP",
        "user",
        user_id,
        {},
        ip_address=ip,
    )

    profile = {
        "id": user_id,
        "email": payload.email,
        "full_name": full_name or None,
        "firm_name": firm_name or None,
        "phone": phone or None,
        "role": "admin",
        "is_active": True,
        # Free tier: match DB default free_runs_remaining (2) from billing migration.
        "runs_limit": 2,
    }

    try:
        db.table("user_profiles").upsert(profile, on_conflict="id").execute()
        # Direct signup API always creates a workspace owner.
        db.table("user_profiles").update(
            {"role": "admin", "full_name": full_name or None}
        ).eq("id", user_id).execute()
        from app.services.tenancy_sync import mirror_user_profile_upsert_to_aurora
        mirror_user_profile_upsert_to_aurora(profile, user_id)
    except Exception as exc:  # noqa: BLE001
        _log.error("Profile insert failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again.",
        ) from exc

    background_tasks.add_task(
        _signup_welcome_email_task,
        str(payload.email).strip(),
        str(payload.full_name or ""),
    )

    return SignupResponse(
        user_id=user_id,
        message="Account created successfully. Please check your email to confirm.",
    )


# ── POST /api/v1/auth/onboarding-complete ─────────────────────────────────────

@router.post("/onboarding-complete")
async def onboarding_complete(
    current_user: dict = Depends(get_current_active_user),
):
    """Set onboarding_completed so middleware allows dashboard / reconcile routes."""
    uid = str(current_user.get("id", "")).strip()
    get_supabase().table("user_profiles").update({"onboarding_completed": True}).eq(
        "id", uid
    ).execute()
    from app.services.tenancy_sync import mirror_user_profile_update_to_aurora
    mirror_user_profile_update_to_aurora(uid, {"onboarding_completed": True})
    return {"success": True}


# ── POST /api/auth/webhook/signup (Supabase DB webhook: user_profiles INSERT) ─

@webhook_router.post("/webhook/signup")
async def webhook_signup(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Inbound Supabase Database Webhook when a row is inserted into *user_profiles*."""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        await _webhook_error(
            request,
            f"invalid_json: {type(exc).__name__}: {exc}",
        )
        return {"received": True}

    if not isinstance(body, dict):
        await _webhook_error(request, "payload_must_be_object")
        return {"received": True}

    try:
        payload = UserProfileInsertWebhook.model_validate(body)
    except ValidationError as exc:
        await _webhook_error(
            request,
            f"invalid_payload: {exc!s}",
            extra={"errors": exc.errors()[:20]},
        )
        return {"received": True}

    if payload.type != "INSERT" or payload.table != "user_profiles":
        await _webhook_error(
            request,
            "unexpected_event",
            extra={"type": payload.type, "table": payload.table},
        )
        return {"received": True}

    user_id = str(payload.record.id).strip()
    if not user_id:
        await _webhook_error(request, "missing_record_id")
        return {"received": True}

    profile = get_user_profile(user_id)
    if not profile:
        await _webhook_error(
            request,
            "user_profile_not_found",
            entity_id=user_id,
        )
        return {"received": True}

    from app.services.tenancy_sync import mirror_user_profile_upsert_to_aurora
    mirror_user_profile_upsert_to_aurora(profile, user_id)

    email = str(profile.get("email") or "").strip()
    if not email:
        await _webhook_error(
            request,
            "missing_email_on_profile",
            entity_id=user_id,
        )
        return {"received": True}

    full_name = str(
        profile.get("full_name") or payload.record.full_name or ""
    ).strip()

    background_tasks.add_task(_signup_welcome_email_task, email, full_name)
    return {"received": True}


# ── POST /auth/login ─────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest):
    """Authenticate with email/password and return a Supabase JWT with role."""
    ip = _client_ip(request)
    if is_login_locked(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
        )
    db = get_db()
    try:
        auth_response = db.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
    except Exception:  # noqa: BLE001
        record_login_failure(ip)
        await log_action(
            None,
            "LOGIN",
            "user",
            None,
            {"result": "failed"},
            ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        ) from None

    if not auth_response.user or not auth_response.session:
        record_login_failure(ip)
        await log_action(
            None,
            "LOGIN",
            "user",
            None,
            {"result": "failed"},
            ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    record_login_success(ip)
    user_id = str(auth_response.user.id)
    access_token = auth_response.session.access_token
    role = await get_user_role(user_id)
    await log_action(
        user_id,
        "LOGIN",
        "user",
        user_id,
        {"result": "ok"},
        ip_address=ip,
    )
    user_dict = {
        "id": user_id,
        "email": auth_response.user.email,
    }
    profile = get_user_profile(user_id)
    if profile:
        user_dict.update(
            {
                "full_name": profile.get("full_name"),
                "firm_name": profile.get("firm_name"),
                "phone": profile.get("phone"),
                "is_active": profile.get("is_active", True),
            }
        )
    return LoginResponse(
        access_token=access_token,
        user=user_dict,
        role=role,
    )


# ── POST /auth/logout ───────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("200/minute")
async def logout(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Sign out the currently authenticated user."""
    db = get_db()
    ip = _client_ip(request)
    await log_action(
        str(user.id),
        "LOGOUT",
        "user",
        str(user.id),
        {"auth_provider": user.auth_provider},
        ip_address=ip,
    )
    if user.auth_provider == "supabase":
        try:
            db.auth.sign_out()
        except Exception:
            pass


# ── GET /auth/me ─────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfileResponse)
@limiter.limit("200/minute")
async def get_me(
    request: Request,  # noqa: ARG001
    response: Response,
    user_id: str = Depends(get_current_user_id),
):
    """Return the authenticated user's profile including their role."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

    profile = get_user_profile(user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User profile not found.",
        )
    role = await get_user_role(user_id)
    profile["role"] = role
    if profile.get("auto_approve_confidence_threshold") is None:
        profile["auto_approve_confidence_threshold"] = 95
    return UserProfileResponse(**profile)


# ── GET /api/test/send-emails (temporary; remove before production) ───────────

@test_router.get("/send-emails")
async def test_send_emails():
    """Fire test transactional emails via Resend. No authentication."""
    await send_team_invite_email(
        to="kadamomkar9988@gmail.com",
        inviter_firm_name="Test CA Firm",
        role="staff",
        invite_token="test-token-123",
    )
    await send_monthly_reminder_email(
        to="kadamomkar9988@gmail.com",
        full_name="Omkar Kadam",
        pending_clients=[
            {
                "client_name": "ABC Corp",
                "gstin": "27AABCU9603R1ZX",
                "last_reconciled_period": "Mar 2025",
            }
        ],
    )
    return {"sent": True}
