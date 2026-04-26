from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.types import User
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWEError, JWKError  # type: ignore[attr-defined]

from app.config import settings
from app.database import get_user_profile
from app.utils.errors import http_401, http_403

bearer_scheme = HTTPBearer(auto_error=False)
_log = logging.getLogger(__name__)

def _decode_bearer_jwt(token: str) -> dict:
    v = settings.jwt_verify_aud_iss
    opts = {
        "verify_signature": True,
        "require_exp": True,
        "verify_aud": v,
        "verify_iss": v,
    }
    return jwt.decode(
        token,
        settings.jwt_signing_key,
        algorithms=["HS256"],
        audience=settings.JWT_AUDIENCE if v else None,
        issuer=settings.JWT_ISSUER if v else None,
        options=opts,
    )


def _user_from_claims(claims: dict) -> User:
    sub = claims.get("sub")
    if not sub:
        raise http_401()
    return User.model_construct(
        id=str(sub),
        email=claims.get("email") or "",
        app_metadata=claims.get("app_metadata") or {},
        user_metadata=claims.get("user_metadata") or {},
        aud=str(claims.get("aud", "")) if claims.get("aud") is not None else "",
    )


# ── Supabase JWT validation (HS256 only; no algorithm confusion) ────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise http_401()
    token = (credentials.credentials or "").strip()
    if not token:
        raise http_401()
    try:
        unverified = jwt.get_unverified_header(token)
        if (unverified or {}).get("alg") != "HS256":
            raise JWTError("invalid algorithm")
    except (JWTError, JWEError, JWKError, TypeError, ValueError):
        raise http_401() from None
    try:
        claims = _decode_bearer_jwt(token)
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (JWTError, JWEError, JWKError, ValueError, TypeError) as exc:
        _log.debug("JWT decode failed (suppressed for client): %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return _user_from_claims(claims)


async def get_current_user_id(user: User = Depends(get_current_user)) -> str:
    return str(user.id)


async def get_user_role(user_id: str) -> str:
    profile = get_user_profile(user_id)
    if profile:
        return str(profile.get("role", "staff") or "staff")
    return "staff"


def require_role(*allowed: str):
    """Dependency factory: 403 if current user's role is not in *allowed*."""
    allow = {a.strip().lower() for a in allowed if a and a.strip()}
    if not allow:
        raise ValueError("require_role requires at least one role name")

    async def _dep(
        user: User = Depends(get_current_user),
    ) -> str:
        user_id = str(user.id)
        role = (await get_user_role(user_id)).strip().lower()
        if role not in allow:
            raise http_403()
        return user_id

    return _dep


async def require_admin(user_id: str = Depends(get_current_user_id)) -> str:
    role = (await get_user_role(user_id)).strip().lower()
    if role != "admin":
        raise http_403()
    return user_id


# ── Backward-compatibility: local HS256 tokens ────────────────────────────────

def create_access_token(subject: str, extra_claims: Optional[dict] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire, **(extra_claims or {})}
    return jwt.encode(
        payload, settings.jwt_signing_key, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=["HS256"],
        )
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (JWTError, JWEError, JWKError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> dict:
    user_id = str(user.id)
    profile = get_user_profile(user_id)
    if profile is None:
        return {
            "id": user_id,
            "email": user.email,
            "is_active": True,
        }
    if not profile.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return {**profile, "id": user_id, "email": user.email or profile.get("email")}
