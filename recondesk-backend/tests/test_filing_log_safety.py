"""Unit tests for EVC OTP / PAN URL scrubbing (no network)."""

from __future__ import annotations

import httpx

from app.filing.log_safety import (
    mask_gstin,
    safe_httpx_error_text,
    scrub_data_recursively,
    scrub_query_params,
    scrub_url,
    sentry_scrub_breadcrumb,
    sentry_scrub_event,
    sentry_scrub_transaction,
)


def test_scrub_url_redacts_otp_and_pan():
    raw = (
        "https://api.sandbox.co.in/gst/compliance/tax-payer/gstrs/"
        "gstr-1/2025/04/file?pan=AAACQ3770E&otp=575757&keep=1"
    )
    out = scrub_url(raw)
    assert "575757" not in out
    assert "AAACQ3770E" not in out
    assert "otp=%5BREDACTED%5D" in out or "otp=[REDACTED]" in out
    assert "keep=1" in out


def test_scrub_params_dict():
    assert scrub_query_params({
        "otp": "123456",
        "pan": "ABCDE1234F",
        "gstr": "gstr-1",
        "signature": "MIIK...BASE64",
        "pkcs7_signature": "MIIK...BASE64",
    }) == {
        "otp": "[REDACTED]",
        "pan": "[REDACTED]",
        "gstr": "gstr-1",
        "signature": "[REDACTED]",
        "pkcs7_signature": "[REDACTED]",
    }


def test_safe_httpx_error_text_scrubs_request_url():
    req = httpx.Request(
        "POST",
        "https://api.sandbox.co.in/gst/compliance/tax-payer/gstrs/gstr-1/2025/04/file",
        params={"pan": "AAACQ3770E", "otp": "999888"},
    )
    resp = httpx.Response(502, request=req)
    exc = httpx.HTTPStatusError("boom", request=req, response=resp)
    text = safe_httpx_error_text(exc)
    assert "999888" not in text
    assert "AAACQ3770E" not in text
    assert "HTTP 502" in text


def test_sentry_before_send_scrubs_request_url():
    event = {
        "request": {
            "url": "https://app.example/api/file?otp=111222&pan=ABCDE1234F",
            "query_string": "otp=111222&other=1",
        },
        "exception": {
            "values": [
                {
                    "value": (
                        "POST https://api.sandbox.co.in/.../file?otp=111222 "
                        "→ HTTP 500"
                    )
                }
            ]
        },
    }
    out = sentry_scrub_event(event)
    assert "111222" not in out["request"]["url"]
    assert "111222" not in out["request"]["query_string"]
    assert "111222" not in out["exception"]["values"][0]["value"]


# ── REM-07 GSTIN PII Masking Tests ──────────────────────────────────────────


def test_mask_gstin_preserves_state_and_suffix():
    # 27 = Maharashtra, AABCU9603R = PAN, 1ZM = Entity vertical + 'Z' + Checksum
    raw = "27AABCU9603R1ZM"
    masked = mask_gstin(raw)
    assert masked == "27XXXXXXXXXX1ZM"
    assert "AABCU9603R" not in masked


def test_mask_gstin_handles_lowercase():
    raw = "27aabcu9603r1zm"
    masked = mask_gstin(raw)
    assert masked == "27XXXXXXXXXX1ZM"
    assert "aabcu9603r" not in masked.lower()


def test_mask_gstin_collision_avoidance():
    # UUID should not be mutated
    uuid_val = "123e4567-e89b-12d3-a456-426614174000"
    assert mask_gstin(uuid_val) == uuid_val

    # SHA256 hex digest (64 chars) should not be mutated
    sha256_val = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert mask_gstin(sha256_val) == sha256_val

    # Timestamp should not be mutated
    ts_val = "2026-09-22T14:30:00Z"
    assert mask_gstin(ts_val) == ts_val

    # Simple invoice numbers should not be mutated
    inv_val = "INV-2026-001"
    assert mask_gstin(inv_val) == inv_val

    # Alphanumeric continuation (16+ chars) should not match boundary
    longer_alphanumeric = "PREFIX27AABCU9603R1ZMSUFFIX"
    assert mask_gstin(longer_alphanumeric) == longer_alphanumeric

    # None and empty strings
    assert mask_gstin(None) == ""
    assert mask_gstin("") == ""


def test_mask_gstin_in_url_paths_and_queries():
    path = "/api/vendors/scorecard/27AABCU9603R1ZM"
    assert mask_gstin(path) == "/api/vendors/scorecard/27XXXXXXXXXX1ZM"

    query = "/api/v1/invoices?supplier_gstin=27AABCU9603R1ZM&status=matched"
    assert mask_gstin(query) == "/api/v1/invoices?supplier_gstin=27XXXXXXXXXX1ZM&status=matched"


def test_sentry_scrub_breadcrumb():
    crumb = {
        "category": "httpx",
        "message": "Outgoing call to GST portal for 27AABCU9603R1ZM",
        "data": {
            "url": "https://api.sandbox.co.in/taxpayer/27AABCU9603R1ZM/returns?otp=123456",
            "supplier": "27AABCU9603R1ZM",
        },
    }
    scrubbed = sentry_scrub_breadcrumb(crumb)
    assert scrubbed["message"] == "Outgoing call to GST portal for 27XXXXXXXXXX1ZM"
    assert "27AABCU9603R1ZM" not in scrubbed["data"]["url"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["data"]["url"]
    assert "123456" not in scrubbed["data"]["url"]
    assert scrubbed["data"]["supplier"] == "27XXXXXXXXXX1ZM"


def test_sentry_scrub_transaction():
    tx_event = {
        "type": "transaction",
        "transaction": "GET /api/vendors/scorecard/27AABCU9603R1ZM",
        "request": {
            "url": "https://api.recondesk.in/api/vendors/scorecard/27AABCU9603R1ZM",
            "query_string": "supplier_gstin=27AABCU9603R1ZM&otp=999888",
        },
        "spans": [
            {
                "op": "http.client",
                "description": "GET https://api.sandbox.co.in/taxpayer/27AABCU9603R1ZM/status",
            }
        ],
        "breadcrumbs": {
            "values": [
                {
                    "category": "query",
                    "message": "SELECT * FROM vendors WHERE gstin = '27AABCU9603R1ZM'",
                }
            ]
        },
    }

    scrubbed = sentry_scrub_transaction(tx_event)
    assert scrubbed["transaction"] == "GET /api/vendors/scorecard/27XXXXXXXXXX1ZM"
    assert "27AABCU9603R1ZM" not in scrubbed["request"]["url"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["request"]["url"]
    assert "27AABCU9603R1ZM" not in scrubbed["request"]["query_string"]
    assert "999888" not in scrubbed["request"]["query_string"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["request"]["query_string"]
    assert "27AABCU9603R1ZM" not in scrubbed["spans"][0]["description"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["spans"][0]["description"]
    assert "27AABCU9603R1ZM" not in scrubbed["breadcrumbs"]["values"][0]["message"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["breadcrumbs"]["values"][0]["message"]


def test_sentry_scrub_event_with_gstin():
    event = {
        "exception": {
            "values": [
                {
                    "value": "GSTINValidationError: Invalid tax filing response for 27AABCU9603R1ZM"
                }
            ]
        },
        "request": {
            "url": "https://api.recondesk.in/api/reconcile/27AABCU9603R1ZM?otp=444555",
            "query_string": "otp=444555",
        },
        "breadcrumbs": {
            "values": [
                {
                    "message": "Failed filing for 27AABCU9603R1ZM",
                }
            ]
        },
    }
    scrubbed = sentry_scrub_event(event)
    assert "27AABCU9603R1ZM" not in scrubbed["exception"]["values"][0]["value"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["exception"]["values"][0]["value"]
    assert "27AABCU9603R1ZM" not in scrubbed["request"]["url"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["request"]["url"]
    assert "444555" not in scrubbed["request"]["url"]
    assert "27AABCU9603R1ZM" not in scrubbed["breadcrumbs"]["values"][0]["message"]
    assert "27XXXXXXXXXX1ZM" in scrubbed["breadcrumbs"]["values"][0]["message"]

