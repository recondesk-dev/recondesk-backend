"""GSTR-2B auto-fetch via Sandbox GSTN taxpayer API: OTP auth + document pull."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.auth import get_current_active_user
from app.database import get_supabase
from app.integrations.gstr2b_autofetch import (
    get_gstr2b,
    get_sandbox_token,
    send_otp,
    verify_otp,
)
from app.parsers.gstr2b_parser import parse_gstr2b
from app.services.firm_access import list_accessible_client_gstin_ids

router = APIRouter(redirect_slashes=False)
_log = logging.getLogger(__name__)


class SendOtpRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gstin: str
    username: str

    @field_validator("gstin", "username")
    @classmethod
    def strip_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class VerifyOtpRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gstin: str
    username: str
    otp: str

    @field_validator("gstin", "username", "otp")
    @classmethod
    def strip_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class FetchGstr2bRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    year: str
    month: str

    @field_validator("year", "month")
    @classmethod
    def strip_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


def _assert_client_access(sb, current_user: dict, client_id: str) -> None:
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if client_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )


def _load_client_gstin(sb, client_id: str) -> dict[str, Any]:
    res = (
        sb.table("client_gstins")
        .select("id, gstin, gstn_access_token, gstn_token_expiry")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client not found",
        )
    return res.data[0]


def _gstr2b_payload_for_parser(raw_data: dict) -> dict:
    """Wrap Sandbox document payload into the shape expected by parse_gstr2b()."""
    if isinstance(raw_data, dict) and "data" in raw_data and isinstance(raw_data["data"], dict):
        return raw_data
    return {"data": raw_data}


def _token_expiry_from_ms(token_expiry_ms: Any) -> datetime | None:
    if token_expiry_ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(token_expiry_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _raise_sandbox_http_error(exc: httpx.HTTPStatusError) -> None:
    detail = "Sandbox GST API request failed"
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("error") or detail)
    except Exception:
        pass
    raise HTTPException(
        status_code=exc.response.status_code,
        detail=detail,
    ) from exc


@router.post("/{client_id}/gstn/send-otp")
async def gstn_send_otp(
    client_id: str,
    body: SendOtpRequest,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    cid = client_id.strip()
    _assert_client_access(sb, current_user, cid)

    try:
        sandbox_token = await asyncio.to_thread(get_sandbox_token)
        await asyncio.to_thread(send_otp, sandbox_token, body.gstin, body.username)
    except httpx.HTTPStatusError as exc:
        _raise_sandbox_http_error(exc)
    except Exception as exc:
        _log.exception("GSTN send-otp failed for client %s", cid)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to send OTP via Sandbox API",
        ) from exc

    return {"message": "OTP sent successfully"}


@router.post("/{client_id}/gstn/verify-otp")
async def gstn_verify_otp(
    client_id: str,
    body: VerifyOtpRequest,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    cid = client_id.strip()
    _assert_client_access(sb, current_user, cid)

    try:
        sandbox_token = await asyncio.to_thread(get_sandbox_token)
        data = await asyncio.to_thread(
            verify_otp, sandbox_token, body.gstin, body.username, body.otp
        )
    except httpx.HTTPStatusError as exc:
        _raise_sandbox_http_error(exc)
    except Exception as exc:
        _log.exception("GSTN verify-otp failed for client %s", cid)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to verify OTP via Sandbox API",
        ) from exc

    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Sandbox verify-otp response missing access_token",
        )

    expiry_dt = _token_expiry_from_ms(data.get("token_expiry"))
    update_payload: dict[str, Any] = {"gstn_access_token": access_token}
    if expiry_dt is not None:
        update_payload["gstn_token_expiry"] = expiry_dt.isoformat()

    sb.table("client_gstins").update(update_payload).eq("id", cid).execute()

    return {"message": "GSTN session verified and token saved"}


@router.post("/{client_id}/gstn/fetch")
async def gstn_fetch_gstr2b(
    client_id: str,
    body: FetchGstr2bRequest,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    cid = client_id.strip()
    _assert_client_access(sb, current_user, cid)

    client_row = _load_client_gstin(sb, cid)
    access_token = client_row.get("gstn_access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no GSTN access token stored for this client; verify OTP first",
        )

    gstin = str(client_row.get("gstin") or "").strip()
    if not gstin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client has no GSTIN on file",
        )

    try:
        raw_data = await asyncio.to_thread(
            get_gstr2b, access_token, gstin, body.year, body.month
        )
    except httpx.HTTPStatusError as exc:
        _raise_sandbox_http_error(exc)
    except Exception as exc:
        _log.exception("GSTR-2B fetch failed for client %s", cid)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to fetch GSTR-2B via Sandbox API",
        ) from exc

    try:
        parsed = parse_gstr2b(_gstr2b_payload_for_parser(raw_data))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return parsed
