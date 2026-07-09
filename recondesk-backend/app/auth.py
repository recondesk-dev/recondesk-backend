from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase_auth import User
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWEError, JWKError  # type: ignore[attr-defined]
from jwt import PyJWK
from jwt.exceptions import (
    ExpiredSignatureError as PyJWTExpiredSignatureError,
    InvalidTokenError as PyJWTInvalidTokenError,
)

from app.config import settings
from app.database import get_user_profile, get_supabase, _is_invited_user
from app.utils.errors import http_401, http_403

bearer_scheme = HTTPBearer(auto_error=False)
_log = logging.getLogger(__name__)

_JWKS_LOCK = threading.Lock()
_JWKS_CACHE: Optional[dict[str, Any]] = None
_JWKS_CACHE_MONO: float = 0.0
_JWKS_LAST_FETCH_MONO: float = 0.0
_JWKS_TTL_SEC = 3600.0
_JWKS_COOLDOWN_SEC = 10.0


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
            data = response.json()
    except httpx.HTTPError as exc:
        _log.warning("JWKS fetch failed from %s: %s", url, exc)
        raise JWTError("JWKS unavailable") from exc
    except ValueError as exc:
        _log.warning("JWKS response was not JSON from %s: %s", url, exc)
        raise JWTError("JWKS unavailable") from exc
    return _require_nonempty_jwks(data, source=url)


def _require_nonempty_jwks(data: Any, *, source: str) -> dict[str, Any]:
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(keys, list) or not keys:
        _log.warning("JWKS empty/invalid from %s: %r", source, data)
        raise JWTError("JWKS empty")
    return data


def _get_jwks_cached(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return Supabase JWKS; refresh after TTL or when ``force_refresh`` is True.

    ``force_refresh`` bypasses the normal TTL but still respects a short cooldown
    so a thundering herd of kid-misses cannot stampede the JWKS endpoint.
    Callers that already know verification failed should use
    ``_invalidate_jwks_cache`` + a plain fetch instead of relying on cooldown.
    """
    global _JWKS_CACHE, _JWKS_CACHE_MONO, _JWKS_LAST_FETCH_MONO
    now = time.monotonic()
    with _JWKS_LOCK:
        can_use_cache = (
            _JWKS_CACHE is not None
            and (
                (not force_refresh and (now - _JWKS_CACHE_MONO) < _JWKS_TTL_SEC)
                or (force_refresh and (now - _JWKS_LAST_FETCH_MONO) < _JWKS_COOLDOWN_SEC)
            )
        )
        if can_use_cache:
            assert _JWKS_CACHE is not None  # type guard
            return _JWKS_CACHE
    data = _require_nonempty_jwks(_fetch_jwks_from_network(), source="jwks-cache-store")
    with _JWKS_LOCK:
        _JWKS_CACHE = data
        _JWKS_CACHE_MONO = time.monotonic()
        _JWKS_LAST_FETCH_MONO = _JWKS_CACHE_MONO
        return _JWKS_CACHE


def _invalidate_jwks_cache() -> None:
    """Drop the in-memory JWKS cache so the next fetch hits the network."""
    global _JWKS_CACHE, _JWKS_CACHE_MONO, _JWKS_LAST_FETCH_MONO
    with _JWKS_LOCK:
        _JWKS_CACHE = None
        _JWKS_CACHE_MONO = 0.0
        # Keep last-fetch timestamp so cooldown still applies to stampede protection
        # for kid-miss force_refresh; signature-failure path clears it below.
        _JWKS_LAST_FETCH_MONO = 0.0


def _jwk_dict_for_token(token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    header = jwt.get_unverified_header(token) or {}
    kid = header.get("kid")
    if not kid:
        raise JWTError("token missing kid")
    for key_dict in jwks.get("keys") or []:
        if key_dict.get("kid") == kid:
            return key_dict
    raise JWTError(f"no matching JWK for token kid={kid!r}")


def _jwt_decode_options() -> dict[str, bool]:
    v = settings.jwt_verify_aud_iss
    return {
        "verify_signature": True,
        "require_exp": True,
        "verify_aud": v,
        "verify_iss": v,
    }


def _pyjwt_decode_options() -> dict[str, bool]:
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


def _decode_es256_with_jwks(token: str, jwks_data: dict[str, Any]) -> dict:
    """Verify an ES256 Supabase JWT using PyJWT + a JWKS key dict."""
    key_dict = _jwk_dict_for_token(token, jwks_data)
    try:
        signing_key = PyJWK.from_dict(key_dict)
    except Exception as exc:  # noqa: BLE001 — malformed/stale JWK material
        raise JWTError(f"invalid JWK for token: {exc}") from exc
    try:
        return pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience=settings.JWT_AUDIENCE if settings.jwt_verify_aud_iss else None,
            issuer=settings.JWT_ISSUER if settings.jwt_verify_aud_iss else None,
            options=_pyjwt_decode_options(),
        )
    except PyJWTExpiredSignatureError as exc:
        raise ExpiredSignatureError(str(exc)) from exc
    except PyJWTInvalidTokenError as exc:
        raise JWTError(str(exc)) from exc


def _decode_es256(token: str) -> dict:
    """ES256 via JWKS. Refresh and retry once on kid-miss or signature failure."""
    jwks_data = _get_jwks_cached()
    try:
        return _decode_es256_with_jwks(token, jwks_data)
    except JWTError as first_exc:
        msg = str(first_exc).lower()
        # Kid miss, bad cached JWK material, or signature failure → refresh JWKS once.
        should_refresh = (
            "no matching jwk" in msg
            or "signature" in msg
            or "invalid jwk" in msg
        )
        if not should_refresh:
            raise
        _log.warning(
            "ES256 local verify failed (%s); invalidating JWKS cache and retrying",
            first_exc,
        )
        _invalidate_jwks_cache()
        jwks_data = _get_jwks_cached(force_refresh=True)
        try:
            return _decode_es256_with_jwks(token, jwks_data)
        except JWTError:
            # Prefer the original failure context if retry also fails.
            raise first_exc


def _expected_issuer() -> str:
    base = (settings.SUPABASE_URL or "").strip().rstrip("/")
    return f"{base}/auth/v1" if base else ""


def _token_debug_bits(token: str) -> str:
    """Safe, non-secret header/claim bits for production logs."""
    expected = _expected_issuer()
    try:
        header = jwt.get_unverified_header(token) or {}
        claims = jwt.get_unverified_claims(token) or {}
        iss = claims.get("iss")
        sig = token.rsplit(".", 1)[-1] if token.count(".") >= 2 else ""
        return (
            f"alg={header.get('alg')!r} kid={header.get('kid')!r} "
            f"iss={iss!r} expected_iss={expected!r} iss_match={iss == expected} "
            f"token_len={len(token)} sig_len={len(sig)} "
            f"supabase_host={(settings.SUPABASE_URL or '').strip()!r}"
        )
    except Exception:  # noqa: BLE001
        return (
            f"alg=? kid=? expected_iss={expected!r} token_len={len(token)} "
            f"supabase_host={(settings.SUPABASE_URL or '').strip()!r}"
        )


def _user_from_supabase_auth(token: str) -> User:
    """Last-resort validation via Supabase Auth /user (network)."""
    try:
        resp = get_supabase().auth.get_user(token)
    except Exception as exc:  # noqa: BLE001
        raise JWTError(f"supabase auth get_user failed: {exc}") from exc
    user = getattr(resp, "user", None) if resp is not None else None
    if user is None or not getattr(user, "id", None):
        raise JWTError("supabase auth get_user returned no user")
    return User.model_construct(
        id=str(user.id),
        email=getattr(user, "email", None) or "",
        app_metadata=getattr(user, "app_metadata", None) or {},
        user_metadata=getattr(user, "user_metadata", None) or {},
        aud=str(getattr(user, "aud", "") or ""),
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
        return _user_from_claims(claims)
    except ExpiredSignatureError as exc:
        _log.warning(
            "JWT decode failed (suppressed for client): %s - %s (%s)",
            type(exc).__name__,
            str(exc),
            _token_debug_bits(token),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (JWTError, JWEError, JWKError, ValueError, TypeError) as exc:
        _log.warning(
            "JWT local decode failed (%s - %s; %s); trying Supabase Auth fallback",
            type(exc).__name__,
            str(exc),
            _token_debug_bits(token),
        )
        try:
            return _user_from_supabase_auth(token)
        except Exception as fallback_exc:  # noqa: BLE001
            _log.warning(
                "JWT decode failed (suppressed for client): %s - %s; fallback=%s - %s (%s)",
                type(exc).__name__,
                str(exc),
                type(fallback_exc).__name__,
                str(fallback_exc),
                _token_debug_bits(token),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc


async def get_current_user_id(user: User = Depends(get_current_user)) -> str:
    return str(user.id)


async def get_user_role(user_id: str) -> str:
    profile = get_user_profile(user_id)
    if profile:
        return str(profile.get("role") or "admin")
    sb = get_supabase()
    if _is_invited_user(sb, user_id=user_id, email=None):
        return "staff"
    return "admin"


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
        _log.warning(
            "JWT decode failed (suppressed for client): %s - %s (%s)",
            type(exc).__name__,
            str(exc),
            _token_debug_bits(token),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (JWTError, JWEError, JWKError) as exc:
        _log.warning(
            "JWT decode failed (suppressed for client): %s - %s (%s)",
            type(exc).__name__,
            str(exc),
            _token_debug_bits(token),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _attach_firm_id(user: dict) -> dict:
    """Best-effort firm anchor on the user context for audit logging; never raises."""
    try:
        from app.utils.audit import resolve_firm_id

        user["firm_id"] = resolve_firm_id(get_supabase(), user)
    except Exception:  # noqa: BLE001
        user.setdefault("firm_id", None)
    return user


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> dict:
    user_id = str(user.id)
    profile = get_user_profile(user_id)
    if profile is None:
        return _attach_firm_id(
            {
                "id": user_id,
                "email": user.email,
                "is_active": True,
            }
        )
    if not profile.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return _attach_firm_id(
        {**profile, "id": user_id, "email": user.email or profile.get("email")}
    )
