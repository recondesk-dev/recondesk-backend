from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue import User
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import settings
from app.database import get_supabase, get_user_profile

bearer_scheme = HTTPBearer(auto_error=False)


# ── Supabase JWT validation ───────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> User:
    """Validate a Supabase Bearer token and return the authenticated user.

    Raises 401 'Authentication required' for missing/invalid tokens.
    Raises 401 'Token expired' when the JWT has expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    client = get_supabase()

    try:
        response = client.auth.get_user(token)
    except Exception as exc:
        error_str = str(exc).lower()
        if "expired" in error_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not response or not response.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return response.user


async def get_current_user_id(user: User = Depends(get_current_user)) -> str:
    """Dependency that returns just the authenticated user's UUID string."""
    return str(user.id)


async def get_user_role(user_id: str) -> str:
    """Return the role string from *user_profiles* for the given user ID.

    Falls back to 'staff' if the profile row is missing the role field.
    """
    profile = get_user_profile(user_id)
    if profile:
        return profile.get("role", "staff")
    return "staff"


async def require_admin(user_id: str = Depends(get_current_user_id)) -> str:
    """Dependency that raises 403 unless the current user has the 'admin' role."""
    role = await get_user_role(user_id)
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user_id


# ── Backward-compatibility shims ──────────────────────────────────────────────

def create_access_token(subject: str, extra_claims: Optional[dict] = None) -> str:
    """Create a signed JWT (kept for backward compatibility)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire, **(extra_claims or {})}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a locally-issued JWT (kept for backward compatibility)."""
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_active_user(user: User = Depends(get_current_user)) -> dict:
    """Return the *user_profiles* row as a dict.

    Kept for backward compatibility with existing routers.
    Raises 403 if the profile's is_active flag is False.
    """
    user_id = str(user.id)
    profile = get_user_profile(user_id)
    if profile is None:
        return {"id": user_id, "email": user.email, "is_active": True}
    if not profile.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive account",
        )
    return profile
