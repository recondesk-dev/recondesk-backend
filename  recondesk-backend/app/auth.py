from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase_auth import User
from jose import ExpiredSignatureError, JWTError, jwk, jwt
from jose.exceptions import JWEError, JWKError  # type: ignore[attr-defined]

from app.config import settings
from app.database import get_user_profile
from app.utils.errors import http_401, http_403

bearer_scheme = HTTPBearer(auto_error=False)
_log = logging.getLogger(__name__)

_JWKS_LOCK = threading.Lock()
_JWKS_CACHE: Optional[dict[str, Any]] = None
_JWKS_CACHE_MONO: float = 0.0
_JWKS_TTL_SEC = 3600.0


def _jwks_url() -> str:
    base = (settings.SUPABASE_URL or "").strip().rstrip("/")
    if not base:
        raise JWTError("SUPABASE_URL is not configured")
    return f"{base}/auth/v1/.well-known/jwks.json"


def _fetch_jwks_from_network() -> dict[str, Any]:
    url = _jwks_url()
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        _log.warning("JWKS fetch failed from %s: %s", url, exc)
        raise JWTError("JWKS unavailable") from exc


def _get_jwks_cached(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return Supabase JWKS; refresh after TTL or when ``force_refresh`` is True."""
    global _JWKS_CACHE, _JWKS_CACHE_MONO
    now = time.monotonic()
    with _JWKS_LOCK:
        if (
            not force_refresh
            and _JWKS_CACHE is not None
            and (now - _JWKS_CACHE_MONO) < _JWKS_TTL_SEC
        ):
            return _JWKS_CACHE
    data = _fetch_jwks_from_network()
    with _JWKS_LOCK:
        _JWKS_CACHE = data
        _JWKS_CACHE_MONO = time.monotonic()
        return _JWKS_CACHE


def _jwk_key_for_token(token: str, jwks: dict[str, Any]) -> Any:
    header = jwt.get_unverified_header(token) or {}
    kid = header.get("kid")
    if not kid:
        raise JWTError("token missing kid")
    for key_dict in jwks.get("keys") or []:
        if key_dict.get("kid") == kid:
            return jwk.construct(key_dict)
    raise JWTError("no matching JWK for token")


def _jwt_decode_options() -> dict[str, bool]:
    v = settings.jwt_verify_aud_iss
    return {
        "verify_signature": True,
        "require_exp": True,
        "verify_aud": v,
        "verify_iss": v,
    }


def _decode_hs256(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_signing_key,
        algorithms=["HS256"],
        audience=settings.JWT_AUDIENCE if settings.jwt_verify_aud_iss else None,
        issuer=settings.JWT_ISSUER if settings.jwt_verify_aud_iss else None,
        options=_jwt_decode_options(),
    )


def _decode_es256(token: str) -> dict:
    jwks_data = _get_jwks_cached()
    try:
        key = _jwk_key_for_token(token, jwks_data)
    except JWTError:
        jwks_data = _get_jwks_cached(force_refresh=True)
        key = _jwk_key_for_token(token, jwks_data)
    return jwt.decode(
        token,
        key,
        algorithms=["ES256"],
        audience=settings.JWT_AUDIENCE if settings.jwt_verify_aud_iss else None,
        issuer=settings.JWT_ISSUER if settings.jwt_verify_aud_iss else None,
        options=_jwt_decode_options(),
    )


def _decode_bearer_jwt(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token) or {}
    except (JWTError, JWEError, JWKError, TypeError, ValueError) as exc:
        raise JWTError("invalid token header") from exc
    alg = (header.get("alg") or "").upper()
    if alg == "HS256":
        return _decode_hs256(token)
    if alg == "ES256":
        return _decode_es256(token)
    raise JWTError(f"unsupported algorithm: {alg!r}")


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


# ── Supabase JWT validation (HS256 symmetric + ES256 via JWKS) ─────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise http_401()
    token = (credentials.credentials or "").strip()
    if not token:
        raise http_401()
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
