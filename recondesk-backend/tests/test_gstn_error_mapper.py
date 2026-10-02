"""Tests for GSTN error mapping and GSP brand leakage prevention."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from app.filing.sandbox_filing_client import (
    FilingApiError,
    FilingAuthError,
    FilingClientError,
    FilingGstnError,
)
from app.integrations.gstn_error_mapper import (
    DEFAULT_GENERIC_ERROR_MESSAGE,
    MSG_2B_NOT_FILED,
    MSG_2B_STILL_PROCESSING,
    MSG_INVALID_GSTIN,
    MSG_NETWORK_TIMEOUT,
    MSG_OTP_ERROR,
    MSG_RATE_LIMIT,
    MSG_SESSION_EXPIRED,
    gstn_http_exception,
    map_gstn_error,
    sanitize_message_text,
    to_http_status_code,
)
from app.integrations.gstr2b_autofetch import SandboxGstnError
from app.services.sandbox_gst_client import (
    Gstr2bNotFiledError,
    Gstr2bStillProcessingError,
    SandboxApiError,
    SandboxAuthError,
    SandboxClientError,
    SandboxRateLimitError,
)


# ---------------------------------------------------------------------------
# 1. Known pattern mapping tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw_msg,expected",
    [
        ("Sandbox GST API request failed: Invalid GSTIN pattern", MSG_INVALID_GSTIN),
        ("Invalid GSTIN pattern", MSG_INVALID_GSTIN),
        ("Invalid GSTIN format", MSG_INVALID_GSTIN),
        ("GSTIN is invalid", MSG_INVALID_GSTIN),
        ("format of GSTIN is invalid", MSG_INVALID_GSTIN),
        ("missing_gstin", MSG_INVALID_GSTIN),
    ],
)
def test_gstin_pattern_mapping(raw_msg: str, expected: str):
    assert map_gstn_error(raw_msg) == expected


@pytest.mark.parametrize(
    "error_cd,expected",
    [
        ("RET11403", MSG_INVALID_GSTIN),
        ("RET11416", MSG_INVALID_GSTIN),
        ("ER0001", MSG_INVALID_GSTIN),
    ],
)
def test_gstin_error_code_mapping(error_cd: str, expected: str):
    assert map_gstn_error("some error", error_code=error_cd) == expected


@pytest.mark.parametrize(
    "raw_msg,expected",
    [
        ("Invalid OTP", MSG_OTP_ERROR),
        ("OTP expired", MSG_OTP_ERROR),
        ("OTP has expired", MSG_OTP_ERROR),
        ("Incorrect OTP entered", MSG_OTP_ERROR),
        ("Max OTP attempts exceeded", MSG_OTP_ERROR),
        ("OTP verification failed", MSG_OTP_ERROR),
        ("EVC filing requires an OTP", MSG_OTP_ERROR),
    ],
)
def test_otp_error_mapping(raw_msg: str, expected: str):
    assert map_gstn_error(raw_msg) == expected


@pytest.mark.parametrize(
    "error_cd,expected",
    [
        ("RET11406", MSG_OTP_ERROR),
        ("RET11407", MSG_OTP_ERROR),
        ("AUTH4037", MSG_OTP_ERROR),
        ("AUTH4038", MSG_OTP_ERROR),
        ("AUTH5004", MSG_OTP_ERROR),
    ],
)
def test_otp_error_code_mapping(error_cd: str, expected: str):
    assert map_gstn_error("error", error_code=error_cd) == expected


@pytest.mark.parametrize(
    "raw_msg,expected",
    [
        ("Session expired", MSG_SESSION_EXPIRED),
        ("Token expired", MSG_SESSION_EXPIRED),
        ("JWT expired", MSG_SESSION_EXPIRED),
        ("Invalid session token", MSG_SESSION_EXPIRED),
        ("Unauthorized access", MSG_SESSION_EXPIRED),
        ("Access token expired. Please reconnect.", MSG_SESSION_EXPIRED),
        ("no active filing session; complete OTP verify first", MSG_SESSION_EXPIRED),
    ],
)
def test_session_expiry_mapping(raw_msg: str, expected: str):
    assert map_gstn_error(raw_msg) == expected


@pytest.mark.parametrize(
    "error_cd,expected",
    [
        ("AUTH5001", MSG_SESSION_EXPIRED),
        ("AUTH5002", MSG_SESSION_EXPIRED),
        ("AUTH5003", MSG_SESSION_EXPIRED),
        ("TEC4002", MSG_SESSION_EXPIRED),
    ],
)
def test_session_error_code_mapping(error_cd: str, expected: str):
    assert map_gstn_error("error", error_code=error_cd) == expected


@pytest.mark.parametrize(
    "raw_msg,expected",
    [
        ("Rate limit exceeded", MSG_RATE_LIMIT),
        ("Too many requests from this IP", MSG_RATE_LIMIT),
        ("Monthly quota exceeded", MSG_RATE_LIMIT),
        ("Request limit reached", MSG_RATE_LIMIT),
    ],
)
def test_rate_limit_mapping(raw_msg: str, expected: str):
    assert map_gstn_error(raw_msg) == expected


def test_2b_not_filed_mapping():
    assert map_gstn_error("GSTR-2B not filed yet for period 2026-07") == MSG_2B_NOT_FILED
    assert map_gstn_error("Error", error_code="RET2B1023") == MSG_2B_NOT_FILED
    assert map_gstn_error(Gstr2bNotFiledError("27AABCU9603R1ZM", 2026, 7)) == MSG_2B_NOT_FILED


def test_2b_still_processing_mapping():
    assert map_gstn_error("GSTR-2B is still being generated") == MSG_2B_STILL_PROCESSING
    assert map_gstn_error("still processing", error_code="RET2B1024") == MSG_2B_STILL_PROCESSING
    assert map_gstn_error(Gstr2bStillProcessingError("27AABCU9603R1ZM", 2026, 7)) == MSG_2B_STILL_PROCESSING


def test_network_timeout_mapping():
    assert map_gstn_error("Connection timed out after 10s") == MSG_NETWORK_TIMEOUT
    assert map_gstn_error("Connection refused by peer") == MSG_NETWORK_TIMEOUT
    assert map_gstn_error(httpx.TimeoutException("Read timed out")) == MSG_NETWORK_TIMEOUT


# ---------------------------------------------------------------------------
# 2. Fallback & Unrecognized Errors (Never pass raw string)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "unknown_err",
    [
        "Unexpected JSON Schema validation error in section B2B row 43",
        "Sandbox internal database lock timeout",
        "Some bizarre internal error 99238491823",
        "Random failure message from 3rd party",
        "",
        None,
    ],
)
def test_unrecognized_error_returns_generic_safe_message(unknown_err):
    result = map_gstn_error(unknown_err)
    assert result == DEFAULT_GENERIC_ERROR_MESSAGE
    assert "Sandbox" not in result
    assert "schema" not in result.lower()
    assert "99238491823" not in result


# ---------------------------------------------------------------------------
# 3. Strict Provider Brand Leak Invariant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw_input",
    [
        "Sandbox GST API request failed: Invalid GSTIN pattern",
        "Sandbox.co.in returned 500 internal server error",
        "Failed to authenticate with Sandbox GSP",
        "Sandbox API rate limit exceeded",
        "Sandbox verify-otp response missing access_token",
        "Sandbox GSTR-2B payload missing buyer gstin",
        "Sandbox send-otp raw response error",
        "Unexpected Sandbox response",
        "Sandbox returned 404 Not Found",
    ],
)
def test_word_sandbox_never_appears_in_mapped_output(raw_input: str):
    mapped = map_gstn_error(raw_input)
    assert "sandbox" not in mapped.lower()
    assert "gsp" not in mapped.lower()


def test_sanitize_message_text():
    assert "sandbox" not in sanitize_message_text("Sandbox failed").lower()
    assert sanitize_message_text("Clean message") == "Clean message"


# ---------------------------------------------------------------------------
# 4. Exception Mapping to HTTPException
# ---------------------------------------------------------------------------

def test_gstn_http_exception_from_sandbox_gstn_error():
    exc = SandboxGstnError("Sandbox GST API request failed: Invalid GSTIN pattern")
    http_exc = gstn_http_exception(exc)
    assert isinstance(http_exc, HTTPException)
    assert http_exc.status_code == 422
    assert http_exc.detail == MSG_INVALID_GSTIN
    assert "Sandbox" not in str(http_exc.detail)


def test_gstn_http_exception_from_filing_auth_error():
    exc = FilingAuthError("Sandbox API authentication failed (HTTP 401)")
    http_exc = gstn_http_exception(exc)
    assert http_exc.status_code == 401
    assert http_exc.detail == MSG_SESSION_EXPIRED


def test_gstn_http_exception_from_filing_gstn_error_with_code():
    exc = FilingGstnError("OTP verification failed", error_cd="AUTH4038")
    http_exc = gstn_http_exception(exc, include_error_cd=True)
    assert http_exc.status_code == 502
    assert isinstance(http_exc.detail, dict)
    assert http_exc.detail["message"] == MSG_OTP_ERROR
    assert http_exc.detail["error_cd"] == "AUTH4038"


def test_gstn_http_exception_from_httpx_429():
    req = httpx.Request("POST", "https://api.sandbox.co.in/gst/otp")
    resp = httpx.Response(429, request=req, json={"message": "Sandbox rate limit exceeded"})
    exc = httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp)

    http_exc = gstn_http_exception(exc)
    assert http_exc.status_code == 429
    assert http_exc.detail == MSG_RATE_LIMIT
    assert "Sandbox" not in str(http_exc.detail)


def test_gstn_http_exception_from_httpx_404():
    req = httpx.Request("GET", "https://api.sandbox.co.in/gst/returns")
    resp = httpx.Response(404, request=req, text="Not Found")
    exc = httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    # External 404 mapped to 502 with safe message so frontend does not mistake for route 404
    http_exc = gstn_http_exception(exc)
    assert http_exc.status_code == 502
    assert http_exc.detail == DEFAULT_GENERIC_ERROR_MESSAGE
    assert "Sandbox" not in str(http_exc.detail)


# ---------------------------------------------------------------------------
# 5. Internal Logging Verification
# ---------------------------------------------------------------------------

def test_internal_logging_preserves_raw_error(caplog):
    caplog.set_level(logging.WARNING)
    raw_error_message = "Sandbox API returned HTTP 500 with stack trace: Traceback..."

    result = map_gstn_error(raw_error_message, log_context="test_context")

    # User facing string is sanitized
    assert result == DEFAULT_GENERIC_ERROR_MESSAGE
    assert "Sandbox" not in result

    # Internal log captures full raw details for engineering debugging
    assert any("Sandbox API returned HTTP 500" in record.message for record in caplog.records)
    assert any("test_context" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 6. Router Integration Helpers Verification
# ---------------------------------------------------------------------------

def test_filing_router_map_client_error_sanitization():
    from app.routers.filing import _map_client_error

    # FilingAuthError
    auth_err = FilingAuthError("Sandbox API authentication failed (HTTP 401). Verify SANDBOX_API_KEY")
    res_auth = _map_client_error(auth_err)
    assert res_auth.status_code == 401
    assert "Sandbox" not in str(res_auth.detail)
    assert res_auth.detail == MSG_SESSION_EXPIRED

    # FilingGstnError with invalid GSTIN
    gstin_err = FilingGstnError("Sandbox GST API request failed: Invalid GSTIN pattern", error_cd="RET11403")
    res_gstin = _map_client_error(gstin_err)
    assert res_gstin.status_code == 502
    assert "Sandbox" not in str(res_gstin.detail)
    assert res_gstin.detail == {"message": MSG_INVALID_GSTIN, "error_cd": "RET11403"}

    # FilingApiError
    api_err = FilingApiError("HTTP 500 on /gst/save: Sandbox server crashed")
    res_api = _map_client_error(api_err)
    assert res_api.status_code == 502
    assert "Sandbox" not in str(res_api.detail)
    assert res_api.detail == DEFAULT_GENERIC_ERROR_MESSAGE


def test_gstr2b_autofetch_routes_raise_http_error_sanitization():
    from app.routers.gstr2b_autofetch_routes import _raise_sandbox_http_error

    req = httpx.Request("POST", "https://api.sandbox.co.in/gst/compliance/tax-payer/otp")
    resp = httpx.Response(400, request=req, json={"error": {"message": "Invalid GSTIN pattern"}})
    exc = httpx.HTTPStatusError("400 Bad Request", request=req, response=resp)

    with pytest.raises(HTTPException) as exc_info:
        _raise_sandbox_http_error(exc, context="Sandbox GST API request failed")

    err = exc_info.value
    assert "Sandbox" not in str(err.detail)
    assert err.detail == MSG_INVALID_GSTIN


def test_gstr1_not_filed_mapping():
    from app.integrations.gstn_error_mapper import MSG_GSTR1_NOT_FILED, MSG_RETURN_ALREADY_FILED

    # By error code
    assert map_gstn_error("Some error", error_code="RT-R3BQ1004") == MSG_GSTR1_NOT_FILED
    assert map_gstn_error("Some error", error_code="RET19101") == MSG_GSTR1_NOT_FILED

    # By raw message pattern
    assert map_gstn_error("You have not filed GSTR-1 of the selected tax period.") == MSG_GSTR1_NOT_FILED
    assert map_gstn_error("GSTR-1 not filed for this period") == MSG_GSTR1_NOT_FILED
    assert map_gstn_error("Return already filed", error_code="RET11405") == MSG_RETURN_ALREADY_FILED


def test_filing_gstn_error_with_clean_message():
    from app.routers.filing import _map_client_error

    # When FilingGstnError has RT-R3BQ1004
    exc = FilingGstnError("You have not filed GSTR-1 of the selected tax period.", error_cd="RT-R3BQ1004")
    res = _map_client_error(exc)
    assert res.status_code == 502
    assert "GSTR-1" in res.detail["message"]
    assert res.detail["error_cd"] == "RT-R3BQ1004"


