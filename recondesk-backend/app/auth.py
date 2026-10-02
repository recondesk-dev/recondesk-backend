from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Any, Literal, Optional

from app.cognito_aurora_store import get_identity_store
from app.cognito_config import get_cognito_config
from app.cognito_identity import CognitoIdentityStore
from app.cognito_verifier import (
    CognitoAuthError,
    CognitoTokenExpiredError,
    CognitoTokenInvalidError,
    verify_cognito_token,
)
from app.config import settings
from app.database import get_user_profile, get_supabase, _is_invited_user
from app.utils.errors import http_401, http_403

AuthProvider = Literal["supabase", "cognito"]


@dataclass(frozen=True)
class AuthenticatedUser:
    """Minimal immutable provider-neutral authenticated user context.

    Anchors authentication to canonical user_profiles.id while recording
    the verified identity provider and provider subject.
    Contains NO default authorization role or privileges.
    """

    id: str
    auth_provider: AuthProvider
    provider_subject: str

    def __str__(self) -> str:
        return self.id


bearer_scheme = HTTPBearer(auto_error=False)
_log = logging.getLogger(__name__)

def _token_debug_bits(token: str) -> str:
    """Safe, non-secret header/claim bits for production logs."""
    try:
        header = pyjwt.get_unverified_header(token) or {}
        claims = pyjwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        ) or {}
        iss = claims.get("iss")
        sig = token.rsplit(".", 1)[-1] if token.count(".") >= 2 else ""
        return (
            f"alg={header.get('alg')!r} kid={header.get('kid')!r} "
            f"iss={iss!r} token_use={claims.get('token_use')!r} "
            f"token_len={len(token)} sig_len={len(sig)}"
        )
    except Exception:
        return f"alg=? kid=? token_len={len(token)}"


def _detect_auth_provider_hint(token: str) -> Optional[AuthProvider]:
    """Inspect unverified token structure strictly as a routing hint."""
    try:
        header = pyjwt.get_unverified_header(token) or {}
        claims = pyjwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        ) or {}
    except Exception:
        return None

    alg = (header.get("alg") or "").upper()
    iss = str(claims.get("iss") or "")
    token_use = claims.get("token_use")

    if alg == "RS256":
        if "cognito" in iss or token_use in ("access", "id") or "client_id" in claims:
            return "cognito"

    if "cognito" in iss:
        return "cognito"

    return None


def _verify_supabase_bearer_token(token: str) -> AuthenticatedUser:
    """Permanently disabled: Supabase authentication has been removed."""
    _log.warning("Rejected attempt to authenticate using disabled Supabase token")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Supabase authentication has been disabled. Please authenticate with Amazon Cognito.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _verify_cognito_bearer_token(
    token: str,
    store: Optional[CognitoIdentityStore] = None,
) -> AuthenticatedUser:
    """Verify an Amazon Cognito access token and return AuthenticatedUser.

    Requirements:
      1. Strictly requires token_use='access' (ID tokens fail closed).
      2. Validates RS256 signature, issuer, client_id, and unexpired.
      3. Queries Aurora store for trusted 1:1 mapping (sub + pool_id).
      4. Requires is_verified == True and mapped user_profiles.is_active == True.
      5. Returns AuthenticatedUser(id=mapped_user_id, auth_provider="cognito", provider_subject=cognito_sub).
      6. Never trusts Cognito email for mapping or profile lookup.
    """
    config = get_cognito_config()
    if not config.COGNITO_AUTH_ENABLED:
        _log.warning("Cognito token presented but COGNITO_AUTH_ENABLED is False")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cognito authentication is not enabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = verify_cognito_token(token, expected_token_use="access", config=config)
    except CognitoTokenExpiredError as exc:
        _log.warning("Cognito access token expired: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="The token is expired"'},
        ) from exc
    except CognitoAuthError as exc:
        _log.warning("Cognito access token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unverifiable authentication token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verified token missing or invalid 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    configured_pool = config.COGNITO_USER_POOL_ID.strip()
    active_store = store or get_identity_store()

    def _profile_lookup(uid: str) -> Optional[dict[str, Any]]:
        if hasattr(active_store, "get_user_profile_by_id"):
            prof = active_store.get_user_profile_by_id(uid)
            if prof is not None:
                return prof
        return get_user_profile(uid)

    mapping_result = None
    if hasattr(active_store, "lookup_trusted_mapping"):
        mapping_result = active_store.lookup_trusted_mapping(
            sub,
            pool_id=configured_pool,
            profile_lookup_fn=_profile_lookup,
        )
    else:
        mapping = active_store.get_mapping_by_sub(sub, pool_id=configured_pool)
        if (
            mapping
            and mapping.verified
            and mapping.cognito_user_pool_id == configured_pool
            and mapping.cognito_sub == sub
        ):
            prof = _profile_lookup(mapping.user_id)
            if prof and prof.get("is_active", True):
                mapping_result = {
                    "user_id": mapping.user_id,
                    "cognito_sub": mapping.cognito_sub,
                    "is_verified": True,
                    "profile": prof,
                }

    if not mapping_result or not mapping_result.get("is_verified") or not mapping_result.get("user_id"):
        # Distinguish between unmapped identity vs mapped but disabled/inactive user profile
        existing = active_store.get_mapping_by_sub(sub, pool_id=configured_pool)
        if existing and existing.verified:
            prof = _profile_lookup(existing.user_id)
            if prof and not prof.get("is_active", True):
                _log.warning("Cognito mapped user %s is disabled or inactive", existing.user_id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is inactive or disabled",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        _log.warning(
            "Cognito token verified for sub %s, but no trusted verified Aurora mapping exists in pool %s",
            sub,
            configured_pool,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No verified account mapping found for this identity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    mapped_user_id = str(mapping_result["user_id"]).strip()
    if not mapped_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mapped user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    profile = mapping_result.get("profile")
    if profile is None:
        profile = _profile_lookup(mapped_user_id)

    if not profile or not profile.get("is_active", True):
        _log.warning("Cognito mapped user %s is disabled or profile missing", mapped_user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedUser(
        id=mapped_user_id,
        auth_provider="cognito",
        provider_subject=sub,
    )


# ── Cognito-Only Authentication (100% AWS Cognito) ────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    store: Optional[CognitoIdentityStore] = Depends(get_identity_store),
) -> AuthenticatedUser:
    """Cognito-only authentication dependency.

    Verifies Amazon Cognito access token, validates RS256 signature against AWS JWKS,
    and resolves to canonical user_profiles.id via Aurora mapping store.
    Fails closed with HTTP 401 if token is missing, invalid, expired, or unmapped.
    """
    if credentials is None:
        raise http_401()
    token = (credentials.credentials or "").strip()
    if not token:
        raise http_401()

    return _verify_cognito_bearer_token(token, store=store)


async def get_current_user_id(
    user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    return str(user.id)


async def get_user_role(user_id: str, sb: Optional[Client] = None) -> str:
    store = get_identity_store()
    profile = None
    if hasattr(store, "get_user_profile_by_id"):
        profile = store.get_user_profile_by_id(user_id)
    if profile is None:
        profile = get_user_profile(user_id)
    if profile:
        return str(profile.get("role") or "admin")
    try:
        if sb is None:
            sb = get_supabase()
        if _is_invited_user(sb, user_id=user_id, email=None):
            return "staff"
    except Exception:
        pass
    return "admin"


def require_role(*allowed: str):
    """Dependency factory: 403 if current user's role is not in *allowed*."""
    allow = {a.strip().lower() for a in allowed if a and a.strip()}
    if not allow:
        raise ValueError("require_role requires at least one role name")

    async def _dep(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> str:
        user_id = str(user.id)
        role = (await get_user_role(user_id)).strip().lower()
        if role not in allow:
            raise http_403()
        return user_id

    return _dep


async def require_admin(user_id: str = Depends(get_current_user_id)) -> str:
    role = (await get_user_role(user_id)).strip().lower()
    if role not in ("admin", "owner"):
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
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    user_id = str(user.id)
    store = get_identity_store()
    profile = None
    if hasattr(store, "get_user_profile_by_id"):
        profile = store.get_user_profile_by_id(user_id)
    if profile is None:
        profile = get_user_profile(user_id)
    if profile is None:
        return _attach_firm_id(
            {
                "id": user_id,
                "email": "",
                "is_active": True,
                "auth_provider": user.auth_provider,
                "provider_subject": user.provider_subject,
            }
        )
    if not profile.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return _attach_firm_id(
        {
            **profile,
            "id": user_id,
            "email": profile.get("email") or "",
            "auth_provider": user.auth_provider,
            "provider_subject": user.provider_subject,
        }
    )
