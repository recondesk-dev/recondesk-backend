from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import httpx
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWEError, JWKError  # type: ignore[attr-defined]
from jwt import PyJWK
from jwt.exceptions import (
    ExpiredSignatureError as PyJWTExpiredSignatureError,
    InvalidTokenError as PyJWTInvalidTokenError,
)
from supabase import Client

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


def _user_from_supabase_network(token: str) -> dict[str, Any]:
    """Last-resort validation via Supabase Auth /user (network)."""
    try:
        resp = get_supabase().auth.get_user(token)
    except Exception as exc:  # noqa: BLE001
        raise JWTError(f"supabase auth get_user failed: {exc}") from exc
    user = getattr(resp, "user", None) if resp is not None else None
    if user is None or not getattr(user, "id", None):
        raise JWTError("supabase auth get_user returned no user")
    return {
        "id": str(user.id),
        "email": getattr(user, "email", None) or "",
        "sub": str(user.id),
    }


def _decode_and_verify_token_network_first(token: str) -> dict[str, Any]:
    """Verify Supabase token either via local JWT decode or Supabase Auth network call."""
    try:
        return _decode_bearer_jwt(token)
    except Exception:
        return _user_from_supabase_network(token)


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


def _detect_auth_provider_hint(token: str) -> Optional[AuthProvider]:
    """Inspect unverified token structure strictly as a routing hint.

    SECURITY INVARIANT:
    This hint is NEVER trusted as authentication or authorization evidence.
    The selected provider independently and completely cryptographically
    validates the token, signature, issuer, audience/client_id, and expiration.
    """
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

    # Cognito indicators:
    # 1. alg is RS256 AND (issuer contains cognito OR token_use is access/id OR client_id in claims)
    if alg == "RS256":
        if "cognito" in iss or token_use in ("access", "id") or "client_id" in claims:
            return "cognito"

    # Supabase indicators:
    # 1. alg is HS256 or ES256
    # 2. or issuer contains supabase
    if alg in ("HS256", "ES256"):
        return "supabase"

    if "cognito" in iss:
        return "cognito"

    if "supabase" in iss:
        return "supabase"

    return None


def _verify_supabase_bearer_token(token: str) -> AuthenticatedUser:
    """Verify a Supabase JWT (HS256 symmetric or ES256 via JWKS) and return AuthenticatedUser.

    Preserves existing Supabase verification behavior:
    - First attempts local cryptographic decode (HS256 or ES256).
    - If local decode fails (other than expiration), falls back to Supabase Auth /user network call.
    - If all fail, raises HTTP 401 Unauthorized.
    """
    try:
        claims = _decode_bearer_jwt(token)
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise http_401()
        return AuthenticatedUser(
            id=sub,
            auth_provider="supabase",
            provider_subject=sub,
        )
    except ExpiredSignatureError as exc:
        _log.warning(
            "Supabase JWT expired: %s - %s (%s)",
            type(exc).__name__,
            str(exc),
            _token_debug_bits(token),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (JWTError, JWEError, JWKError, ValueError, TypeError, Exception) as exc:
        _log.warning(
            "Supabase JWT local decode failed (%s - %s; %s); trying Supabase Auth network fallback",
            type(exc).__name__,
            str(exc),
            _token_debug_bits(token),
        )
        try:
            data = _user_from_supabase_network(token)
            sub = str(data.get("id") or data.get("sub") or "").strip()
            if not sub:
                raise http_401()
            return AuthenticatedUser(
                id=sub,
                auth_provider="supabase",
                provider_subject=sub,
            )
        except Exception as fallback_exc:  # noqa: BLE001
            _log.warning(
                "Supabase JWT decode failed (suppressed for client): %s - %s; fallback=%s - %s (%s)",
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
            if prof and prof.get("is_active", True):
                mapping_result = {
                    "user_id": str(existing.user_id),
                    "cognito_sub": existing.cognito_sub,
                    "is_verified": True,
                    "profile": prof,
                }

        # Direct lookup by sub in Aurora if pool-scoped check returned nothing
        if not mapping_result:
            try:
                from app.aurora_client import get_aurora_engine
                from sqlalchemy import text
                engine = get_aurora_engine()
                with engine.connect() as conn:
                    matched_sub = conn.execute(
                        text("SELECT user_id, cognito_sub, email, is_verified FROM public.cognito_user_mappings WHERE cognito_sub = :s AND is_verified = true LIMIT 1"),
                        {"s": sub},
                    ).first()
                    if matched_sub:
                        m_uid = str(matched_sub.user_id)
                        prof = _profile_lookup(m_uid)
                        if prof and prof.get("is_active", True):
                            mapping_result = {
                                "user_id": m_uid,
                                "cognito_sub": sub,
                                "is_verified": True,
                                "profile": prof,
                            }
            except Exception as sub_err:
                _log.warning("Direct sub mapping lookup error: %s", sub_err)

        # Auto-link fallback: if no mapping found, look up profile by token username / email
        if not mapping_result:
            candidate_email = (claims.get("email") or claims.get("username") or "").strip().lower()
            if candidate_email and "@" in candidate_email:
                from app.aurora_client import get_aurora_engine
                from sqlalchemy import text
                import uuid
                try:
                    engine = get_aurora_engine()
                    with engine.connect() as conn:
                        matched = conn.execute(
                            text("SELECT id, email, full_name, role, is_active FROM public.user_profiles WHERE LOWER(email) = :em AND is_active = true LIMIT 1"),
                            {"em": candidate_email},
                        ).first()
                        if matched:
                            m_uid = str(matched.id)
                            conn.execute(
                                text("""
                                    INSERT INTO public.cognito_user_mappings
                                    (id, cognito_user_pool_id, cognito_sub, user_id, email, mapping_method, is_verified, provisioned_by)
                                    VALUES (:id, :pool, :sub, :uid, :em, 'admin_provisioned', true, 'bearer_token_auto_link')
                                    ON CONFLICT (cognito_user_pool_id, cognito_sub) DO UPDATE
                                    SET user_id = EXCLUDED.user_id, email = EXCLUDED.email
                                """),
                                {
                                    "id": str(uuid.uuid4()),
                                    "pool": configured_pool,
                                    "sub": sub,
                                    "uid": m_uid,
                                    "em": candidate_email,
                                },
                            )
                            conn.commit()
                            prof = _profile_lookup(m_uid)
                            mapping_result = {
                                "user_id": m_uid,
                                "cognito_sub": sub,
                                "is_verified": True,
                                "profile": prof or dict(matched._mapping),
                            }
                except Exception as auto_link_err:
                    _log.warning("Auto-link fallback exception for sub %s: %s", sub, auto_link_err)

        if not mapping_result or not mapping_result.get("is_verified") or not mapping_result.get("user_id"):
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


# ── Dual-Auth Provider Dispatch (Supabase + Cognito) ──────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    store: Optional[CognitoIdentityStore] = Depends(get_identity_store),
) -> AuthenticatedUser:
    """Provider-neutral authentication dependency.

    Dispatches to Cognito or Supabase verifier based on safe unverified inspection,
    then executes complete, independent cryptographic verification.
    Fails closed with HTTP 401 if token is missing, invalid, expired, or unmapped.
    """
    if credentials is None:
        raise http_401()
    token = (credentials.credentials or "").strip()
    if not token:
        raise http_401()

    provider_hint = _detect_auth_provider_hint(token)

    if provider_hint == "cognito":
        return _verify_cognito_bearer_token(token, store=store)
    elif provider_hint == "supabase":
        return _verify_supabase_bearer_token(token)
    else:
        _log.warning("Unknown or unparseable token provider hint (%s)", _token_debug_bits(token))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


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


async def require_admin_user(
    current_user: dict = Depends(get_current_active_user),
) -> dict:
    """Enforce that the authenticated user holds an admin or owner role.

    Used for legally binding or financial operations (filing, liability offset, IMS writeback).
    """
    role = (current_user.get("role") or "").strip().lower()
    if role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for this operation",
        )
    return current_user
