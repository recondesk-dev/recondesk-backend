"""Standard JSON error responses."""

from __future__ import annotations

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse


def error_response(
    status_code: int, detail: str, headers: dict | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"detail": detail}, headers=headers
    )


def http_400(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def http_401() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def http_403() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
    )


def http_413() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail="Request body too large (max 1MB)",
    )


def http_429() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests. Please try again later.",
    )
