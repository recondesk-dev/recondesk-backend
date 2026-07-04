"""GSTIN Verification service via Sandbox.co.in Public GST API.

This module is fully self-contained and isolated from the rest of the
reconciliation/Razorpay infrastructure.  It exposes two public coroutines:

    get_sandbox_access_token()  – authenticate with Sandbox and return a JWT.
    verify_gstin(gstin)         – look up a GSTIN and return a structured result.

Design notes
------------
- Token is cached in a module-level dict with an expiry timestamp.
  Default cache TTL is 23 hours; if a real ``expiry``/``expires_in`` value is
  present in the auth response it is used instead.  On a 401 from the search
  call the token is discarded and one re-authenticate + retry is attempted.
- httpx.AsyncClient is used throughout (10-second timeout).
- Network errors trigger one automatic retry; 4xx responses do NOT retry.
- The GSTIN is always masked in log output (first 5 chars visible, rest → *).

Environment variables (set in Railway — never hardcode)
-------------------------------------------------------
SANDBOX_API_KEY     – Sandbox API key (also used as x-api-key header).
SANDBOX_API_SECRET  – Sandbox API secret (used only for /authenticate).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.sandbox.co.in"
_AUTH_URL = f"{_BASE_URL}/authenticate"
_GSTIN_SEARCH_URL = f"{_BASE_URL}/gst/compliance/public/gstin/search"

# Default cache TTL for the access token (seconds).  Sandbox tokens are valid
# for 24 hours per their docs; we refresh 1 h early to avoid clock-skew issues.
_TOKEN_DEFAULT_TTL_SECONDS = 23 * 3600

# Sandbox "no records found" error code for GSTIN search.
_ERR_NO_RECORDS = "FO8000"

# Timeout for all outbound HTTP calls (seconds).
_HTTP_TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# Module-level token cache
# ---------------------------------------------------------------------------

_token_cache: dict[str, Any] = {
    "token": None,
    "expires_at": 0.0,  # monotonic timestamp
}


def _mask_gstin(gstin: str) -> str:
    """Return a masked GSTIN for safe logging (first 5 chars visible)."""
    if not gstin:
        return "<empty>"
    visible = gstin[:5]
    masked = "*" * max(0, len(gstin) - 5)
    return f"{visible}{masked}"


def _token_is_valid() -> bool:
    """Return True if a cached token exists and has not yet expired."""
    return bool(_token_cache["token"]) and time.monotonic() < _token_cache["expires_at"]


def _store_token(token: str, ttl_seconds: float) -> None:
    """Persist token and compute its expiry as a monotonic timestamp."""
    _token_cache["token"] = token
    _token_cache["expires_at"] = time.monotonic() + ttl_seconds
    logger.debug("gstin_verification: access token cached for %.0fs", ttl_seconds)


def _evict_token() -> None:
    """Discard cached token (e.g. on 401 from downstream call)."""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0
    logger.debug("gstin_verification: access token evicted from cache")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def get_sandbox_access_token() -> str:
    """Authenticate with Sandbox.co.in and return a valid JWT access token.

    Implements a simple in-memory cache keyed on expiry time.  The first
    call (or any call after the cached token expires) performs a real HTTP
    request; subsequent calls within the TTL return the cached value.

    Returns
    -------
    str
        The raw JWT string to pass as the ``authorization`` header
        (Sandbox does NOT want a "Bearer " prefix on search calls).

    Raises
    ------
    RuntimeError
        If SANDBOX_API_KEY or SANDBOX_API_SECRET env vars are not set.
    httpx.HTTPStatusError
        On non-200 HTTP failures during authentication.
    """
    if _token_is_valid():
        logger.debug("gstin_verification: returning cached access token")
        return _token_cache["token"]  # type: ignore[return-value]

    api_key = os.environ.get("SANDBOX_API_KEY", "").strip()
    api_secret = os.environ.get("SANDBOX_API_SECRET", "").strip()

    if not api_key:
        raise RuntimeError(
            "SANDBOX_API_KEY environment variable is not set. "
            "GSTIN verification is unavailable."
        )
    if not api_secret:
        raise RuntimeError(
            "SANDBOX_API_SECRET environment variable is not set. "
            "GSTIN verification is unavailable."
        )

    headers = {
        "x-api-key": api_key,
        "x-api-secret": api_secret,
        "Content-Type": "application/json",
    }

    logger.info("gstin_verification: authenticating with Sandbox.co.in")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(_AUTH_URL, headers=headers)

    if resp.status_code != 200:
        logger.error(
            "gstin_verification: authentication failed – HTTP %s body=%s",
            resp.status_code,
            resp.text[:300],
        )
        raise httpx.HTTPStatusError(
            f"Sandbox /authenticate returned HTTP {resp.status_code}",
            request=resp.request,
            response=resp,
        )

    body = resp.json()
    # Sandbox auth response envelope: { "code": 200, "data": { "access_token": "...", ... } }
    data = body.get("data") or body
    token: Optional[str] = data.get("access_token")
    if not token:
        # Some Sandbox plans return the token at the top-level key.
        token = body.get("access_token")
    if not token:
        raise ValueError(
            f"Sandbox /authenticate response missing 'access_token'. Body: {body!r}"
        )

    # Determine TTL: prefer explicit expiry/expires_in from the response.
    ttl: float = _TOKEN_DEFAULT_TTL_SECONDS
    raw_expiry = (
        data.get("expiry")
        or data.get("expires_in")
        or body.get("expiry")
        or body.get("expires_in")
    )
    if raw_expiry:
        try:
            ttl = float(raw_expiry)
            # If the value looks like a Unix timestamp rather than a duration,
            # convert it to a remaining-time duration relative to now.
            if ttl > 1_000_000_000:
                ttl = ttl - time.time()
            # Give a 1-hour buffer to avoid using a nearly-expired token.
            ttl = max(60.0, ttl - 3600)
        except (TypeError, ValueError):
            ttl = _TOKEN_DEFAULT_TTL_SECONDS

    _store_token(token, ttl)
    logger.info("gstin_verification: Sandbox authentication successful (TTL=%.0fs)", ttl)
    return token


# ---------------------------------------------------------------------------
# GSTIN verification (public entry point)
# ---------------------------------------------------------------------------

async def verify_gstin(gstin: str) -> dict[str, Any]:
    """Verify a GSTIN using the Sandbox.co.in Public GST Search API.

    Automatically handles token expiry: on a 401 response the token cache
    is purged and authentication is retried once before giving up.

    Parameters
    ----------
    gstin:
        The 15-character GSTIN to verify.

    Returns
    -------
    dict with keys:
        valid             (bool)   – True if the GSTIN is found and active.
        status            (str)    – "Active", "Cancelled", "SEZ", "ISD",
                                     "Not Found", or "Unknown".
        legal_name        (str|None)
        trade_name        (str|None)
        taxpayer_type     (str|None)
        registration_date (str|None) – raw string from the API.
        raw_response      (dict)   – full API response for debugging/logging.

    Notes
    -----
    This function NEVER raises on a clean "GSTIN not found" or "Cancelled"
    result — those are represented in the returned dict.  It only raises on
    unrecoverable infrastructure errors (auth misconfiguration, network
    timeout after retry, Sandbox 5xx after retry).
    """
    masked = _mask_gstin(gstin)
    logger.info("gstin_verification: verifying GSTIN %s", masked)

    result = await _do_verify(gstin, allow_reauth=True)

    logger.info(
        "gstin_verification: GSTIN %s – valid=%s status=%s",
        masked,
        result["valid"],
        result["status"],
    )
    return result


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------

async def _do_verify(gstin: str, *, allow_reauth: bool) -> dict[str, Any]:
    """Perform the actual Sandbox GSTIN search call.

    Parameters
    ----------
    gstin:
        15-character GSTIN string.
    allow_reauth:
        If True, a 401 response triggers a single re-authentication and
        recursive call with allow_reauth=False.
    """
    api_key = os.environ.get("SANDBOX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "SANDBOX_API_KEY environment variable is not set. "
            "GSTIN verification is unavailable."
        )

    token = await get_sandbox_access_token()

    headers = {
        "Content-Type": "application/json",
        "authorization": token,   # NOTE: no "Bearer" prefix — Sandbox requirement
        "x-api-key": api_key,
    }
    payload = {"gstin": gstin}

    last_exc: Optional[Exception] = None
    resp: Optional[httpx.Response] = None

    for attempt in range(2):  # attempt 0 = first try; attempt 1 = network retry
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    _GSTIN_SEARCH_URL,
                    headers=headers,
                    json=payload,
                )
            break  # success — exit retry loop
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning(
                    "gstin_verification: network error on attempt %d – %s. Retrying…",
                    attempt + 1,
                    exc,
                )
                continue
            # Second failure — propagate
            logger.error("gstin_verification: network error after retry – %s", exc)
            raise
    else:
        raise last_exc or RuntimeError("Unknown network failure during GSTIN verification")

    assert resp is not None

    # ── Handle 401: token expired or invalid ─────────────────────────────────
    if resp.status_code == 401:
        if allow_reauth:
            logger.warning(
                "gstin_verification: received 401 – evicting token and re-authenticating"
            )
            _evict_token()
            return await _do_verify(gstin, allow_reauth=False)
        logger.error(
            "gstin_verification: 401 after re-authentication – "
            "SANDBOX_API_KEY/SANDBOX_API_SECRET may be invalid"
        )
        return _error_result(
            status="Auth Error",
            raw={},
            detail="Sandbox authentication failed after retry",
        )

    # ── Parse response body ───────────────────────────────────────────────────
    try:
        body: dict = resp.json()
    except Exception:
        body = {}

    raw_response: dict = body

    # ── "No records found" — error code FO8000 ───────────────────────────────
    # Sandbox returns HTTP 422 or body code FO8000 for "GSTIN not found".
    code_field = str(body.get("code", "")).strip()
    inner_data = body.get("data") or {}
    error_code = str(
        inner_data.get("error_cd", "") or body.get("error_cd", "")
    ).strip()

    if error_code == _ERR_NO_RECORDS or code_field == _ERR_NO_RECORDS:
        logger.info(
            "gstin_verification: GSTIN %s – not found (FO8000)", _mask_gstin(gstin)
        )
        return {
            "valid": False,
            "status": "Not Found",
            "legal_name": None,
            "trade_name": None,
            "taxpayer_type": None,
            "registration_date": None,
            "raw_response": raw_response,
        }

    # ── General non-2xx HTTP errors (not 401 — handled above) ────────────────
    if resp.status_code not in (200, 422):
        logger.error(
            "gstin_verification: unexpected HTTP %s from Sandbox – body=%s",
            resp.status_code,
            resp.text[:300],
        )
        return _error_result(
            status="API Error",
            raw=raw_response,
            detail=f"Sandbox returned HTTP {resp.status_code}",
        )

    # ── Unwrap Sandbox envelope ───────────────────────────────────────────────
    # Envelope: { "code": 200, "data": { ... }, "timestamp": "..." }
    envelope_code = str(body.get("code", "")).strip()
    if envelope_code not in ("200", "200.0"):
        msg = body.get("message") or body.get("error") or "Unknown API error"
        logger.warning(
            "gstin_verification: Sandbox returned body code=%s msg=%s",
            envelope_code,
            msg,
        )
        if not inner_data:
            return _error_result(
                status="API Error", raw=raw_response, detail=str(msg)
            )

    # ── Extract taxpayer details ──────────────────────────────────────────────
    # Sandbox sometimes nests the GSTN payload under data.data.
    if isinstance(inner_data.get("data"), dict):
        taxpayer: dict = inner_data["data"]
    elif inner_data and "lgnm" in inner_data:
        taxpayer = inner_data
    else:
        taxpayer = inner_data

    gstin_status_raw: str = str(
        taxpayer.get("sts") or taxpayer.get("status") or ""
    ).strip()
    legal_name: Optional[str] = (
        taxpayer.get("lgnm") or taxpayer.get("legal_name") or None
    )
    trade_name: Optional[str] = (
        taxpayer.get("tradeNam") or taxpayer.get("trade_name") or None
    )
    taxpayer_type_raw: Optional[str] = (
        taxpayer.get("dty") or taxpayer.get("taxpayer_type") or None
    )
    registration_date: Optional[str] = (
        taxpayer.get("rgdt") or taxpayer.get("registration_date") or None
    )

    # ── Map raw status to canonical status string ─────────────────────────────
    status_str, is_valid = _map_gstin_status(
        gstin_status_raw, taxpayer_type_raw or ""
    )

    return {
        "valid": is_valid,
        "status": status_str,
        "legal_name": legal_name,
        "trade_name": trade_name,
        "taxpayer_type": taxpayer_type_raw,
        "registration_date": registration_date,
        "raw_response": raw_response,
    }


# ---------------------------------------------------------------------------
# Status mapping helper
# ---------------------------------------------------------------------------

def _map_gstin_status(raw_status: str, taxpayer_type: str) -> tuple[str, bool]:
    """Map a raw Sandbox status string to a canonical (status, is_valid) pair.

    Returns
    -------
    tuple[str, bool]
        (status_str, is_valid) where is_valid is True only for active-style
        registrations (Active, SEZ, ISD, Provisional, Migrated).
    """
    s = raw_status.strip().upper()
    tt = taxpayer_type.strip().upper()

    if not s:
        return ("Unknown", False)

    # Active registrations — check taxpayer_type first for special categories
    if s in ("ACTIVE", "ACT"):
        if "SEZ" in tt:
            return ("SEZ", True)
        if "ISD" in tt:
            return ("ISD", True)
        return ("Active", True)

    # Cancelled / suspended registrations
    if s in ("CANCELLED", "CANCEL", "INACTIVE", "SUSPENDED"):
        return ("Cancelled", False)

    # Provisional registrations (newly granted, not fully active)
    if "PROVISIONAL" in s:
        return ("Provisional", True)

    # Migrated registrations (from earlier GST regimes)
    if "MIGRATED" in s:
        return ("Migrated", True)

    # Catch-all — return title-cased raw string; not considered valid
    return (raw_status.strip().title() or "Unknown", False)


# ---------------------------------------------------------------------------
# Error result builder
# ---------------------------------------------------------------------------

def _error_result(*, status: str, raw: dict, detail: str = "") -> dict[str, Any]:
    """Build a structured error result dict (valid=False, no taxpayer fields)."""
    result: dict[str, Any] = {
        "valid": False,
        "status": status,
        "legal_name": None,
        "trade_name": None,
        "taxpayer_type": None,
        "registration_date": None,
        "raw_response": raw,
    }
    if detail:
        result["_error_detail"] = detail
    return result
