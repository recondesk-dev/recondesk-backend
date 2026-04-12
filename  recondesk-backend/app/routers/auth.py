from fastapi import APIRouter, Depends, HTTPException, Request, status
from gotrue import User

from app.auth import get_current_user, get_current_user_id, get_user_role
from app.database import get_db, get_user_profile
from app.models.user import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    UserProfileResponse,
)
from app.utils.rate_limit import limiter

router = APIRouter()

_RATE = "10/minute"


# ── POST /auth/signup ─────────────────────────────────────────────────────────

@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(_RATE)
async def signup(request: Request, payload: SignupRequest):
    """Register a new user and create their profile row."""
    db = get_db()

    try:
        auth_response = db.auth.sign_up(
            {"email": payload.email, "password": payload.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if not auth_response.user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sign-up failed. The email may already be registered.",
        )

    user_id = str(auth_response.user.id)

    profile = {
        "id": user_id,
        "email": payload.email,
        "full_name": payload.full_name,
        "firm_name": payload.firm_name,
        "phone": payload.phone,
        "role": "staff",
        "is_active": True,
    }

    try:
        db.table("user_profiles").insert(profile).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile creation failed: {exc}",
        ) from exc

    return SignupResponse(
        user_id=user_id,
        message="Account created successfully. Please check your email to confirm.",
    )


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
@limiter.limit(_RATE)
async def login(request: Request, payload: LoginRequest):
    """Authenticate with email/password and return a Supabase JWT with role."""
    db = get_db()

    try:
        auth_response = db.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        ) from exc

    if not auth_response.user or not auth_response.session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user_id = str(auth_response.user.id)
    access_token = auth_response.session.access_token
    role = await get_user_role(user_id)

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


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(_RATE)
async def logout(request: Request, user: User = Depends(get_current_user)):
    """Sign out the currently authenticated user."""
    db = get_db()
    try:
        db.auth.sign_out()
    except Exception:
        pass


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfileResponse)
@limiter.limit(_RATE)
async def get_me(
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """Return the authenticated user's profile including their role."""
    profile = get_user_profile(user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found.",
        )
    role = await get_user_role(user_id)
    profile["role"] = role
    return UserProfileResponse(**profile)
