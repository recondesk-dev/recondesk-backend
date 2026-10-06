from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import httpx
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK
from jwt.exceptions import (
    ExpiredSignatureError as PyJWTExpiredSignatureError,
    InvalidTokenError as PyJWTInvalidTokenError,
    PyJWTError,
)

from app.cognito_config import CognitoConfig, get_cognito_config

_log = logging.getLogger(__name__)
cognito_bearer_scheme = HTTPBearer(auto_error=False)

# Thread-safe JWKS cache for Cognito User Pool public keys
_COGNITO_JWKS_LOCK = threading.Lock()
_COGNITO_JWKS_CACHE: Optional[dict[str, Any]] = None
_COGNITO_JWKS_CACHE_MONO: float = 0.0
_COGNITO_JWKS_LAST_FETCH_MONO: float = 0.0
_COGNITO_JWKS_COOLDOWN_SEC: float = 10.0


class CognitoAuthError(Exception):
    """Base exception for all Cognito authentication errors."""


class CognitoTokenVerificationError(CognitoAuthError):
    """Raised when a Cognito JWT fails verification."""


class CognitoTokenExpiredError(CognitoTokenVerificationError):
    """Raised when a Cognito JWT has expired."""


class CognitoTokenInvalidError(CognitoTokenVerificationError):
    """Raised when a Cognito JWT has an invalid signature, claims, or format."""


class CognitoJwksUnavailableError(CognitoAuthError):
    """Raised when the Cognito JWKS endpoint cannot be reached or returns invalid keys."""


def _fetch_cognito_jwks(jwks_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch public JWKS keys from Cognito with strict timeout and validation."""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(jwks_url)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        _log.warning("Failed to fetch Cognito JWKS from %s: %s", jwks_url, exc)
        raise CognitoJwksUnavailableError(f"Cognito JWKS unavailable from {jwks_url}") from exc

    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(keys, list) or not keys:
        _log.warning("Cognito JWKS response was empty or malformed: %r", data)
        raise CognitoJwksUnavailableError("Cognito JWKS contained no keys")
    return data


def get_cached_cognito_jwks(
    config: Optional[CognitoConfig] = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached Cognito JWKS keys, refreshing when expired or forced."""
    global _COGNITO_JWKS_CACHE, _COGNITO_JWKS_CACHE_MONO, _COGNITO_JWKS_LAST_FETCH_MONO
    cfg = config or get_cognito_config()
    ttl = float(cfg.COGNITO_JWKS_CACHE_TTL_SECONDS)
    now = time.monotonic()

    with _COGNITO_JWKS_LOCK:
        can_use_cache = (
            _COGNITO_JWKS_CACHE is not None
            and (
                (not force_refresh and (now - _COGNITO_JWKS_CACHE_MONO) < ttl)
                or (force_refresh and (now - _COGNITO_JWKS_LAST_FETCH_MONO) < _COGNITO_JWKS_COOLDOWN_SEC)
            )
        )
        if can_use_cache:
            assert _COGNITO_JWKS_CACHE is not None
            return _COGNITO_JWKS_CACHE

    data = _fetch_cognito_jwks(cfg.jwks_url, timeout=cfg.COGNITO_JWKS_TIMEOUT_SECONDS)

    with _COGNITO_JWKS_LOCK:
        _COGNITO_JWKS_CACHE = data
        _COGNITO_JWKS_CACHE_MONO = time.monotonic()
        _COGNITO_JWKS_LAST_FETCH_MONO = _COGNITO_JWKS_CACHE_MONO
        return _COGNITO_JWKS_CACHE


def invalidate_cognito_jwks_cache() -> None:
    """Explicitly invalidate cached Cognito JWKS keys."""
    global _COGNITO_JWKS_CACHE, _COGNITO_JWKS_CACHE_MONO, _COGNITO_JWKS_LAST_FETCH_MONO
    with _COGNITO_JWKS_LOCK:
        _COGNITO_JWKS_CACHE = None
        _COGNITO_JWKS_CACHE_MONO = 0.0
        _COGNITO_JWKS_LAST_FETCH_MONO = 0.0


def set_cognito_jwks_cache_for_testing(jwks: Optional[dict[str, Any]]) -> None:
    """Inject mock JWKS data for testing without network requests."""
    global _COGNITO_JWKS_CACHE, _COGNITO_JWKS_CACHE_MONO, _COGNITO_JWKS_LAST_FETCH_MONO
    with _COGNITO_JWKS_LOCK:
        _COGNITO_JWKS_CACHE = jwks
        _COGNITO_JWKS_CACHE_MONO = time.monotonic() if jwks is not None else 0.0
        _COGNITO_JWKS_LAST_FETCH_MONO = _COGNITO_JWKS_CACHE_MONO


def _find_jwk_for_token(header: dict[str, Any], jwks: dict[str, Any]) -> dict[str, Any]:
    kid = header.get("kid")
    if not kid or not isinstance(kid, str):
        raise CognitoTokenInvalidError("Token header missing 'kid' claim")
    keys = jwks.get("keys") or []
    for k in keys:
        if k.get("kid") == kid:
            return k
    raise CognitoTokenInvalidError(f"No matching Cognito public key found for kid={kid!r}")


def _safe_token_summary(token: str) -> str:
    """Format safe token metadata for logging without leaking signatures or raw tokens."""
    try:
        header = pyjwt.get_unverified_header(token)
        claims = pyjwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        return (
            f"alg={header.get('alg')!r} kid={header.get('kid')!r} "
            f"iss={claims.get('iss')!r} sub={claims.get('sub')!r} "
            f"token_use={claims.get('token_use')!r} len={len(token)}"
        )
    except Exception:
        return f"len={len(token)} (unparseable)"


def verify_cognito_token(
    token: str,
    *,
    expected_token_use: Optional[str] = None,
    config: Optional[CognitoConfig] = None,
    jwks_override: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Verify an Amazon Cognito RS256 JWT using JWKS public keys.

    Strict validation:
      1. alg == 'RS256'
      2. Signature verified with Cognito RSA public key matching 'kid'
      3. iss == Cognito User Pool issuer URL
      4. exp > current UTC time
      5. token_use in ('id', 'access') and matches expected_token_use if specified
      6. Client ID / Audience check:
         - For 'id' token: aud == config.COGNITO_CLIENT_ID
         - For 'access' token: client_id == config.COGNITO_CLIENT_ID
      7. sub is present and non-empty

    Fails closed if any verification step fails. Never returns unverified claims.
    """
    cfg = config or get_cognito_config()
    clean_token = (token or "").strip()
    if not clean_token or clean_token.count(".") < 2:
        raise CognitoTokenInvalidError("Invalid or empty JWT token format")

    try:
        header = pyjwt.get_unverified_header(clean_token)
    except PyJWTError as exc:
        raise CognitoTokenInvalidError(f"Cannot parse token header: {exc}") from exc

    alg = header.get("alg")
    if alg != "RS256":
        raise CognitoTokenInvalidError(f"Unsupported algorithm {alg!r}; Cognito requires RS256")

    kid = header.get("kid")
    if not kid or not isinstance(kid, str):
        raise CognitoTokenInvalidError("Token header missing 'kid' claim")

    # Locate JWK key material
    if jwks_override is not None:
        key_dict = _find_jwk_for_token(header, jwks_override)
    else:
        try:
            jwks = get_cached_cognito_jwks(cfg)
            key_dict = _find_jwk_for_token(header, jwks)
        except CognitoTokenInvalidError:
            # Retry once with refreshed JWKS cache to support key rotation
            _log.info("Key ID not found in cached JWKS; refreshing Cognito JWKS once")
            invalidate_cognito_jwks_cache()
            jwks = get_cached_cognito_jwks(cfg, force_refresh=True)
            key_dict = _find_jwk_for_token(header, jwks)

    try:
        signing_key = PyJWK.from_dict(key_dict)
    except Exception as exc:
        raise CognitoTokenInvalidError(f"Malformed JWK public key: {exc}") from exc

    # Decode and verify signature, issuer, and expiration
    expected_issuer = cfg.issuer
    try:
        claims = pyjwt.decode(
            clean_token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=expected_issuer,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                # Aud is checked explicitly below because Cognito Access tokens use client_id, not aud
                "verify_aud": False,
                "require": ["exp", "iss", "sub"],
            },
        )
    except PyJWTExpiredSignatureError as exc:
        _log.warning("Cognito token expired: %s", _safe_token_summary(clean_token))
        raise CognitoTokenExpiredError("Cognito token has expired") from exc
    except PyJWTInvalidTokenError as exc:
        _log.warning("Cognito token signature/claim invalid: %s: %s", exc, _safe_token_summary(clean_token))
        raise CognitoTokenInvalidError(f"Cognito token validation failed: {exc}") from exc

    # Validate token_use
    token_use = claims.get("token_use")
    if token_use not in ("id", "access"):
        raise CognitoTokenInvalidError(f"Invalid token_use claim: {token_use!r}")
    if expected_token_use and token_use != expected_token_use:
        raise CognitoTokenInvalidError(
            f"Expected token_use={expected_token_use!r}, but token has token_use={token_use!r}"
        )

    # Validate Client ID / Audience based on token_use
    if token_use == "id":
        aud = claims.get("aud")
        if aud != cfg.COGNITO_CLIENT_ID:
            raise CognitoTokenInvalidError(
                f"Audience mismatch: expected {cfg.COGNITO_CLIENT_ID!r}, got {aud!r}"
            )
    elif token_use == "access":
        client_id = claims.get("client_id")
        if client_id != cfg.COGNITO_CLIENT_ID:
            raise CognitoTokenInvalidError(
                f"Client ID mismatch: expected {cfg.COGNITO_CLIENT_ID!r}, got {client_id!r}"
            )

    # Validate sub
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise CognitoTokenInvalidError("Cognito token missing or invalid 'sub' claim")

    return claims


async def get_current_cognito_claims(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(cognito_bearer_scheme),
    config: CognitoConfig = Depends(get_cognito_config),
) -> dict[str, Any]:
    """FastAPI dependency for verifying Cognito Bearer tokens.

    Fails closed:
      - If COGNITO_AUTH_ENABLED is False -> 501 Not Implemented
      - If credentials missing or invalid -> 401 Unauthorized
    """
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is currently disabled on this server.",
        )

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    try:
        return verify_cognito_token(token, expected_token_use="access", config=config)
    except CognitoTokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="The token is expired"'},
        ) from exc
    except CognitoAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unverifiable authentication token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
