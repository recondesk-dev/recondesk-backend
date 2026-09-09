"""GSTN taxpayer token lookup + refresh for GSTR-1/2A/3B fetch routes.

Separate from the GSTR-2B autofetch routes module so 2B keeps its
load-and-409 freshness behavior unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from app.integrations.gstr2b_autofetch import refresh_token

_log = logging.getLogger(__name__)

# Refresh when expiry is within this window (or already past).
_REFRESH_SKEW = timedelta(minutes=5)


def load_client_gstin(sb, client_id: str) -> dict[str, Any]:
    """Load GSTN session fields from ``client_gstins`` by primary key ``id``."""
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
    return res.data[0]


def _parse_stored_token_expiry(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _token_expiry_from_ms(token_expiry_ms: Any) -> datetime | None:
    if token_expiry_ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(token_expiry_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _needs_refresh(client_row: dict[str, Any]) -> bool:
    expiry = _parse_stored_token_expiry(client_row.get("gstn_token_expiry"))
    if expiry is None:
        return False
    return expiry <= datetime.now(timezone.utc) + _REFRESH_SKEW


def ensure_fresh_gstn_token(sb, client_row: dict[str, Any]) -> str:
    """Return a usable GSTN access token, refreshing when near/past expiry.

    On refresh failure (or missing token), raises HTTP 409 so the client can
    reconnect via OTP. Does not modify GSTR-2B route behavior.
    """
    access_token = client_row.get("gstn_access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN not connected for this client; complete OTP verification first",
        )
    access_token = str(access_token)

    if not _needs_refresh(client_row):
        return access_token

    cid = str(client_row.get("id") or "")
    _log.info("GSTN token near/past expiry; refreshing client_id=%s", cid)
    try:
        data = refresh_token(access_token)
    except Exception as exc:
        _log.warning("GSTN session refresh failed client_id=%s: %s", cid, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN session expired; please reconnect via OTP",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN session expired; please reconnect via OTP",
        )

    new_token = data.get("access_token")
    if not new_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN session expired; please reconnect via OTP",
        )
    new_token = str(new_token)

    update_payload: dict[str, Any] = {"gstn_access_token": new_token}
    expiry_dt = _token_expiry_from_ms(data.get("token_expiry"))
    if expiry_dt is not None:
        update_payload["gstn_token_expiry"] = expiry_dt.isoformat()

    if cid:
        sb.table("client_gstins").update(update_payload).eq("id", cid).execute()

    client_row["gstn_access_token"] = new_token
    if expiry_dt is not None:
        client_row["gstn_token_expiry"] = expiry_dt.isoformat()

    return new_token
