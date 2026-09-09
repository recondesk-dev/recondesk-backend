"""slowapi key functions: IP + user id (from JWT) when present."""

from __future__ import annotations

from typing import Optional

from jose import JWTError, jwt
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def _bearer_sub(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        options = {
            "verify_signature": True,
            "verify_aud": bool(settings.jwt_verify_aud_iss),
            "verify_iss": bool(settings.jwt_verify_aud_iss),
        }
        claims = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=["HS256"],
            audience=settings.JWT_AUDIENCE if settings.jwt_verify_aud_iss else None,
            issuer=settings.JWT_ISSUER if settings.jwt_verify_aud_iss else None,
            options=options,
        )
        sub = claims.get("sub")
        if sub is None:
            return None
        return str(sub)
    except (JWTError, ValueError, TypeError):
        return None


def composite_rate_key(request: Request) -> str:
    """IP and authenticated user (from verified JWT) when available."""
    ip = get_remote_address(request) or "unknown"
    sub = _bearer_sub(request)
    if sub:
        return f"{ip}|u:{sub}"
    return f"{ip}"


def ip_only_key(request: Request) -> str:
    return get_remote_address(request) or "unknown"
