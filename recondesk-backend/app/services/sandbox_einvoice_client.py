"""Sandbox e-Invoice API client for live IRP authentications and invoice lookups."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sandbox.co.in"
API_KEY = os.getenv("SANDBOX_API_KEY", "")
API_SECRET = os.getenv("SANDBOX_API_SECRET", "")


class EinvoiceClientError(Exception):
    """Base error for e-Invoice Sandbox API calls."""


class EinvoiceAuthError(EinvoiceClientError):
    """Authentication or credential failure."""


class EinvoiceDownError(EinvoiceClientError):
    """IRP portal downtime, gateway failure, or timeout."""


class SandboxEinvoiceClient:
    """Client wrapper for Sandbox GST e-Invoice endpoints."""

    def __init__(self, api_key: str | None = None, api_secret: str | None = None):
        self.api_key = api_key or os.getenv("SANDBOX_API_KEY", "")
        self.api_secret = api_secret or os.getenv("SANDBOX_API_SECRET", "")

    def _headers(self, source: str = "primary", auth_token: str | None = None) -> dict[str, str]:
        h = {
            "x-api-key": self.api_key,
            "x-api-version": "1.0.0",
            "x-source": source,
            "content-type": "application/json",
        }
        if self.api_secret:
            h["x-api-secret"] = self.api_secret
        if auth_token:
            h["authorization"] = auth_token
        return h

    def authenticate_einvoice(
        self,
        gstin: str,
        username: str,
        password: str,
    ) -> dict[str, Any]:
        """Authenticate taxpayer on e-Invoice portal via Sandbox.
        Returns dict containing session_token and expiry info.
        """
        if not self.api_key:
            raise EinvoiceClientError("SANDBOX_API_KEY environment variable is not configured.")

        url = f"{BASE_URL}/gst/compliance/e-invoice/tax-payer/authenticate"
        body = {
            "gstin": gstin.strip().upper(),
            "username": username.strip(),
            "password": password.strip(),
        }

        for source in ("primary", "secondary"):
            try:
                headers = self._headers(source=source)
                logger.info("Calling e-Invoice Auth (%s) for GSTIN %s", source, gstin)
                r = httpx.post(url, headers=headers, json=body, timeout=15.0)
                if r.status_code in (401, 403):
                    err_msg = "Invalid e-Invoice portal credentials (username or password incorrect)."
                    try:
                        edata = r.json()
                        if isinstance(edata, dict) and edata.get("message"):
                            err_msg = edata["message"]
                    except Exception:
                        pass
                    raise EinvoiceAuthError(err_msg)

                r.raise_for_status()
                envelope = r.json()
                if not isinstance(envelope, dict):
                    raise EinvoiceClientError("Invalid response shape from Sandbox e-Invoice Auth.")

                data = envelope.get("data") or envelope
                status_cd = str(data.get("status_cd", "")).strip()
                if status_cd == "0":
                    err_desc = data.get("error", {}).get("message") or "Authentication failed at IRP."
                    raise EinvoiceAuthError(str(err_desc))

                token = data.get("access_token") or data.get("auth_token") or data.get("token")
                if not token:
                    raise EinvoiceClientError("No access token returned in Sandbox e-Invoice Auth response.")

                return {
                    "session_token": str(token),
                    "token_expiry": data.get("token_expiry") or data.get("expiry") or (int(time.time()) + 21600),
                }

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning("Auth timeout/network error on source=%s: %s", source, exc)
                if source == "secondary":
                    raise EinvoiceDownError("IRP portal timed out or is currently unreachable. Please try again later.") from exc
            except (httpx.HTTPStatusError,) as exc:
                if exc.response.status_code >= 500:
                    logger.warning("Auth 5xx server error on source=%s: %s", source, exc)
                    if source == "secondary":
                        raise EinvoiceDownError("IRP portal server error. Please retry.") from exc
                else:
                    raise

        raise EinvoiceDownError("IRP portal authentication failed across primary and secondary sources.")

    def get_einvoice_by_doc(
        self,
        session_token: str,
        gstin: str,
        doc_number: str,
        doc_date: str,
        doc_type: str = "INV",
    ) -> dict[str, Any] | None:
        """Fetch e-Invoice details from IRP by document data.
        Returns dict of e-invoice fields if found, or None if confirmed missing (404).
        """
        url = f"{BASE_URL}/gst/compliance/e-invoice/tax-payer/invoice"
        params = {
            "doc_type": doc_type,
            "doc_num": doc_number,
            "doc_date": doc_date,
        }

        for source in ("primary", "secondary"):
            try:
                headers = self._headers(source=source, auth_token=session_token)
                logger.info("Calling Get e-Invoice by doc (%s) doc_num=%s doc_date=%s", source, doc_number, doc_date)
                r = httpx.get(url, headers=headers, params=params, timeout=15.0)

                if r.status_code == 404:
                    return None

                if r.status_code == 401:
                    raise EinvoiceAuthError("e-Invoice session token expired. Please re-authenticate.")

                if r.status_code in (400, 422):
                    # Check if 400 is "Invoice not found"
                    try:
                        res_json = r.json()
                        msg = str(res_json.get("message") or res_json.get("data", {}).get("error", {}).get("message") or "").lower()
                        if "not found" in msg or "does not exist" in msg or "no record" in msg:
                            return None
                    except Exception:
                        pass

                r.raise_for_status()
                envelope = r.json()
                data = envelope.get("data") if isinstance(envelope, dict) else envelope

                if isinstance(data, dict):
                    status_cd = str(data.get("status_cd", "")).strip()
                    if status_cd == "0":
                        err_msg = str(data.get("error", {}).get("message") or "").lower()
                        if "not found" in err_msg or "does not exist" in err_msg:
                            return None
                        raise EinvoiceClientError(data.get("error", {}).get("message") or "IRP query error")

                    return data

                return envelope

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning("Get e-invoice timeout/network error on source=%s: %s", source, exc)
                if source == "secondary":
                    raise EinvoiceDownError("IRP portal timed out or is currently unreachable.") from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    logger.warning("Get e-invoice 5xx server error on source=%s: %s", source, exc)
                    if source == "secondary":
                        raise EinvoiceDownError("IRP portal server error. Please retry.") from exc
                else:
                    raise

        raise EinvoiceDownError("IRP lookup failed across primary and secondary sources.")


# Global singleton instance
einvoice_client = SandboxEinvoiceClient()
