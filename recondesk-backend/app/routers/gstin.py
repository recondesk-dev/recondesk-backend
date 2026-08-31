"""GSTIN verification API: `/api/gstin`.

Exposes a single endpoint:
    POST /api/gstin/verify  – verify a GSTIN via Sandbox.co.in Public GST API.

This router is fully isolated; it only imports from:
    - app.auth          (authentication dependency)
    - app.services.gstin_verification  (the new service)

No existing routers, reconciliation logic, or Razorpay code is touched.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.auth import get_current_user
from app.services.gstin_verification import verify_gstin

router = APIRouter(redirect_slashes=False)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class GSTINVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gstin: str

    @field_validator("gstin")
    @classmethod
    def gstin_not_empty(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("gstin must not be empty")
        return v


class GSTINVerifyResponse(BaseModel):
    """Structured result from the Sandbox GSTIN search call."""

    model_config = ConfigDict(extra="allow")

    valid: bool
    status: str
    legal_name: str | None = None
    trade_name: str | None = None
    taxpayer_type: str | None = None
    registration_date: str | None = None
    raw_response: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/verify", response_model=GSTINVerifyResponse)
async def verify_gstin_endpoint(
    body: GSTINVerifyRequest,
    current_user: dict = Depends(get_current_user),
) -> Any:
    """Verify a GSTIN against the Sandbox.co.in Public GST API.

    Returns a structured result regardless of the GSTIN's validity — the
    caller should inspect the ``valid`` and ``status`` fields rather than
    treating HTTP errors as the only failure signal.

    If the Sandbox API is unavailable (timeout, misconfiguration, 5xx), the
    endpoint returns HTTP 503 with a clear error message so the frontend can
    let the user proceed manually rather than silently blocking them.
    """
    gstin = body.gstin  # already stripped + uppercased by the validator

    try:
        result = await verify_gstin(gstin)
    except RuntimeError as exc:
        # Configuration error: env vars not set
        _log.error("gstin_verify: configuration error – %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GSTIN verification is temporarily unavailable "
                "(service not configured). You may proceed manually."
            ),
        ) from exc
    except httpx.TimeoutException as exc:
        _log.error("gstin_verify: API timed out – %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GSTIN verification timed out. "
                "The GST portal service may be temporarily unavailable. "
                "You may proceed manually."
            ),
        ) from exc
    except httpx.HTTPStatusError as exc:
        _log.error(
            "gstin_verify: Sandbox API returned HTTP %s – %s",
            exc.response.status_code,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GSTIN verification is temporarily unavailable "
                "(external API error). You may proceed manually."
            ),
        ) from exc
    except Exception as exc:
        _log.exception("gstin_verify: unexpected error – %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GSTIN verification is temporarily unavailable. "
                "You may proceed manually."
            ),
        ) from exc

    return result
