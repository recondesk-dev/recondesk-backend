"""Unit tests for EVC OTP / PAN URL scrubbing (no network)."""

from __future__ import annotations

import httpx

from app.filing.log_safety import (
    safe_httpx_error_text,
    scrub_query_params,
    scrub_url,
    sentry_scrub_event,
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
