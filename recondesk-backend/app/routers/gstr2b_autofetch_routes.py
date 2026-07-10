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
    SandboxGstnError,
    extract_sandbox_txn,
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
        _log.warning("GSTN access denied: client_id=%s not in accessible set", client_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )


def _load_client_gstin(sb, client_id: str) -> dict[str, Any]:
    """Load GSTN session fields from ``client_gstins`` by primary key ``id``.

    The URL ``client_id`` is ``client_gstins.id`` (same id the clients list returns).
    """
    res = (
        sb.table("client_gstins")
        .select("id, gstin, gstn_access_token, gstn_token_expiry")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        _log.warning("GSTN client_gstins row missing for id=%s", client_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"client_gstins row not found for id={client_id}",
        )
    row = res.data[0]
    _log.info(
        "GSTN client_gstins loaded id=%s gstin=%r has_token=%s expiry=%r keys=%s",
        client_id,
        row.get("gstin"),
        bool(row.get("gstn_access_token")),
        row.get("gstn_token_expiry"),
        sorted(row.keys()),
    )
    return row


def _parse_stored_token_expiry(value: Any) -> datetime | None:
    """Parse ``client_gstins.gstn_token_expiry`` (ISO timestamp from DB)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        # Supabase may return "2026-07-10T11:27:33+00:00" or with space.
        dt = datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _assert_gstn_token_fresh(client_row: dict[str, Any]) -> None:
    expiry = _parse_stored_token_expiry(client_row.get("gstn_token_expiry"))
    if expiry is None:
        return
    now = datetime.now(timezone.utc)
    if expiry <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN session expired; please reconnect via OTP",
        )


def _rtnprd_from_year_month(year: str, month: str) -> str:
    """GSTN rtnprd is MMYYYY (e.g. June 2026 → 062026)."""
    return f"{str(month).strip().zfill(2)}{str(year).strip()}"


def _gstr2b_payload_for_parser(
    raw_data: dict,
    *,
    fallback_gstin: str,
    year: str,
    month: str,
) -> dict:
    """Normalize Sandbox GSTR-2B envelope into ``parse_gstr2b`` shape.

    Sandbox often returns nested ``{status_cd, data: {rtnprd, b2b, ...}}`` and
    may omit buyer ``gstin``. Mirror ``SandboxGSTClient.get_gstr2b``: unwrap one
    nested ``data`` layer and inject gstin / rtnprd from the known client + period.
    """
    if not isinstance(raw_data, dict):
        raise ValueError("invalid_sandbox_gstr2b_payload")

    # Prefer nested GSTN document when present (status_cd wrapper).
    inner = raw_data.get("data") if isinstance(raw_data.get("data"), dict) else raw_data
    if not isinstance(inner, dict):
        raise ValueError("invalid_sandbox_gstr2b_payload")

    # One more unwrap if Sandbox double-nests the document.
    if (
        "b2b" not in inner
        and "cdnr" not in inner
        and isinstance(inner.get("data"), dict)
        and any(k in inner["data"] for k in ("b2b", "cdnr", "rtnprd", "fp", "gstin"))
    ):
        inner = inner["data"]

    doc = dict(inner)
    if not str(doc.get("gstin") or "").strip():
        doc["gstin"] = fallback_gstin
    if not str(doc.get("rtnprd") or doc.get("fp") or "").strip():
        doc["rtnprd"] = _rtnprd_from_year_month(year, month)

    _log.info(
        "GSTR-2B payload for parser keys=%s gstin=%r rtnprd=%r",
        sorted(doc.keys())[:30],
        doc.get("gstin"),
        doc.get("rtnprd") or doc.get("fp"),
    )
    return {"data": doc}


def _token_expiry_from_ms(token_expiry_ms: Any) -> datetime | None:
    if token_expiry_ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(token_expiry_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _raise_sandbox_http_error(
    exc: httpx.HTTPStatusError,
    *,
    context: str = "Sandbox GST API request failed",
) -> None:
    sandbox_msg = None
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict) and err.get("message"):
                sandbox_msg = str(err["message"])
            else:
                sandbox_msg = str(body.get("message") or body.get("error") or "") or None
    except Exception:
        sandbox_msg = None

    code = exc.response.status_code
    # Never pass through bare Sandbox/FastAPI-style "Not Found" — callers confuse
    # it with a missing ReconDesk route or client row.
    if code == 404:
        detail = (
            f"{context}: Sandbox returned 404"
            + (f" ({sandbox_msg})" if sandbox_msg else "")
            + ". Check GSTN session and return period."
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc

    detail = f"{context}: {sandbox_msg}" if sandbox_msg else context
    raise HTTPException(status_code=code, detail=detail) from exc


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
        envelope = await asyncio.to_thread(send_otp, sandbox_token, body.gstin, body.username)
    except SandboxGstnError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.message,
        ) from exc
    except httpx.HTTPStatusError as exc:
        _raise_sandbox_http_error(exc)
    except Exception as exc:
        _log.exception("GSTN send-otp failed for client %s", cid)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to send OTP via Sandbox API",
        ) from exc

    txn = extract_sandbox_txn(envelope)
    response: dict[str, Any] = {"message": "OTP sent"}
    if txn:
        response["txn"] = txn
    return response


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
    except SandboxGstnError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.message,
        ) from exc
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
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN not connected for this client; complete OTP verification first",
        )

    gstin = str(client_row.get("gstin") or "").strip()
    if not gstin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client has no GSTIN on file",
        )

    _assert_gstn_token_fresh(client_row)

    _log.info(
        "GSTR-2B fetch starting client_id=%s gstin=%s period=%s-%s has_token=%s",
        cid,
        gstin,
        body.year,
        body.month,
        bool(access_token),
    )

    try:
        raw_data = await asyncio.to_thread(
            get_gstr2b, access_token, gstin, body.year, body.month
        )
    except SandboxGstnError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.message,
        ) from exc
    except httpx.HTTPStatusError as exc:
        _log.warning(
            "GSTR-2B Sandbox HTTP error client_id=%s status=%s body=%s",
            cid,
            exc.response.status_code,
            (exc.response.text or "")[:300],
        )
        _raise_sandbox_http_error(
            exc,
            context=f"GSTR-2B fetch failed for {gstin} period {body.year}-{body.month}",
        )
    except Exception as exc:
        _log.exception("GSTR-2B fetch failed for client %s", cid)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to fetch GSTR-2B via Sandbox API",
        ) from exc

    try:
        payload = _gstr2b_payload_for_parser(
            raw_data,
            fallback_gstin=gstin,
            year=body.year,
            month=body.month,
        )
        parsed = parse_gstr2b(payload)
    except ValueError as exc:
        msg = str(exc)
        if msg == "missing_gstin":
            msg = (
                "Sandbox GSTR-2B payload missing buyer gstin after normalize; "
                f"client gstin={gstin!r}"
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=msg,
        ) from exc

    return parsed
