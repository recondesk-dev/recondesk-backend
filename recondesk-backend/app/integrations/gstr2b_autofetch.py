import logging
import os
from typing import Any

import httpx

BASE_URL = "https://api.sandbox.co.in"
API_KEY = os.getenv("SANDBOX_API_KEY")
API_SECRET = os.getenv("SANDBOX_API_SECRET")

_log = logging.getLogger(__name__)
_logged_send_otp_response_shape = False


class SandboxGstnError(Exception):
    """GSTN business error nested inside a Sandbox HTTP 200 envelope."""

    def __init__(self, message: str, error_cd: str | None = None):
        super().__init__(message)
        self.message = message
        self.error_cd = error_cd


def get_sandbox_token() -> str:
    r = httpx.post(f"{BASE_URL}/authenticate", headers={
        "x-api-key": API_KEY,
        "x-api-secret": API_SECRET,
        "x-api-version": "1.0.0",
    })
    return r.json()["data"]["access_token"]


def _log_send_otp_response_once(envelope: dict[str, Any]) -> None:
    global _logged_send_otp_response_shape
    if _logged_send_otp_response_shape:
        return
    _logged_send_otp_response_shape = True
    data = envelope.get("data")
    data_keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
    _log.info(
        "Sandbox send-otp raw response shape: top_level_keys=%s data_keys=%s "
        "transaction_id=%s",
        list(envelope.keys()) if isinstance(envelope, dict) else type(envelope).__name__,
        data_keys,
        envelope.get("transaction_id") if isinstance(envelope, dict) else None,
    )


def extract_sandbox_txn(envelope: dict[str, Any]) -> str | None:
    """Extract Sandbox request transaction id from a send-otp envelope.

    Live Sandbox response (2026-07) puts ``transaction_id`` on the outer
    envelope, not inside ``data``. Verify-otp does not accept this value;
    it only needs gstin, username, and otp.
    """
    if not isinstance(envelope, dict):
        return None
    for key in ("transaction_id", "txn", "txn_id"):
        val = envelope.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    data = envelope.get("data")
    if isinstance(data, dict):
        for key in ("transaction_id", "txn", "txn_id"):
            val = data.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return None


def _raise_if_gstn_error(envelope: dict[str, Any]) -> None:
    data = envelope.get("data")
    if not isinstance(data, dict):
        return
    err = data.get("error")
    if isinstance(err, dict) and err.get("message"):
        raise SandboxGstnError(str(err["message"]), err.get("error_cd"))
    status_cd = str(data.get("status_cd", "")).strip()
    if status_cd and status_cd not in ("1",):
        raise SandboxGstnError("GSTN OTP request failed")


def send_otp(sandbox_token: str, gstin: str, username: str) -> dict[str, Any]:
    r = httpx.post(f"{BASE_URL}/gst/compliance/tax-payer/otp",
        headers={
            "authorization": sandbox_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
            "x-source": "primary",
        },
        json={"gstin": gstin, "username": username})
    r.raise_for_status()
    envelope = r.json()
    if not isinstance(envelope, dict):
        raise SandboxGstnError("Unexpected Sandbox send-otp response")
    _log_send_otp_response_once(envelope)
    _raise_if_gstn_error(envelope)
    return envelope


def verify_otp(sandbox_token: str, gstin: str, username: str, otp: str) -> dict:
    r = httpx.post(
        f"{BASE_URL}/gst/compliance/tax-payer/otp/verify",
        params={"otp": otp},
        headers={
            "authorization": sandbox_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
            "x-source": "primary",
        },
        json={"gstin": gstin, "username": username},
    )
    r.raise_for_status()
    envelope = r.json()
    if not isinstance(envelope, dict):
        raise SandboxGstnError("Unexpected Sandbox verify-otp response")
    _raise_if_gstn_error(envelope)
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise SandboxGstnError("Sandbox verify-otp response missing data")
    return data


def refresh_token(access_token: str) -> dict:
    r = httpx.post(f"{BASE_URL}/gst/compliance/tax-payer/session/refresh",
        headers={
            "authorization": access_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
        })
    r.raise_for_status()
    return r.json()["data"]


def get_gstr2b(
    access_token: str,
    gstin: str,
    year: str = "",
    month: str = "",
    ret_period: str | None = None,
) -> dict:
    """Fetch GSTR-2B for the authenticated taxpayer session.

    Sandbox docs: GET /gst/compliance/tax-payer/gstrs/gstr-2b/{year}/{month}
    Auth is the GSTN taxpayer access token from verify-otp (not the platform JWT).
    ``gstin`` is kept for logging/callers; the session token already scopes the taxpayer.
    """
    if ret_period and (not year or not month):
        ret_s = str(ret_period).strip().replace("-", "")
        if len(ret_s) == 6:
            month = ret_s[:2]
            year = ret_s[2:]

    year_s = str(year).strip()
    month_s = str(month).strip().zfill(2)
    url = f"{BASE_URL}/gst/compliance/tax-payer/gstrs/gstr-2b/{year_s}/{month_s}"
    _log.info("Sandbox GSTR-2B GET %s gstin=%s", url, gstin)
    r = httpx.get(
        url,
        headers={
            "authorization": access_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
        },
    )
    r.raise_for_status()
    envelope = r.json()
    if not isinstance(envelope, dict):
        raise SandboxGstnError("Unexpected Sandbox GSTR-2B response")
    data = envelope.get("data")
    if data is None:
        raise SandboxGstnError("Sandbox GSTR-2B response missing data")
    return data
