"""Unit tests for SandboxFilingClient (httpx mocked — no live network)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.filing import filing_store
from app.filing.sandbox_filing_client import (
    FilingGstnError,
    SandboxFilingClient,
    build_save_body,
    filing_run_status_after_save_poll,
    parse_return_status,
    period_to_fp,
    period_to_year_month,
)


def _client() -> SandboxFilingClient:
    return SandboxFilingClient(
        api_key="k",
        api_secret="s",
        base_url="https://api.sandbox.co.in",
    )


def _resp(status: int, body: dict, url: str = "https://api.sandbox.co.in/x") -> httpx.Response:
    req = httpx.Request("POST", url)
    return httpx.Response(status, json=body, request=req)


def test_period_helpers():
    assert period_to_year_month("2025-04") == ("2025", "04")
    assert period_to_fp("2025-04") == "042025"
    with pytest.raises(ValueError):
        period_to_year_month("2025/04")


def test_build_save_body_merges_orchestrator_payload():
    body = build_save_body(
        {"b2b": [{"ctin": "27AAECO5678G1Z2", "inv": []}]},
        gstin="27ISKPK1273H1ZF",
        period="2025-04",
        gt=1.0,
        cur_gt=2.0,
    )
    assert body["fp"] == "042025"
    assert body["gstin"] == "27ISKPK1273H1ZF"
    assert body["gt"] == 1.0
    assert "b2b" in body


def test_verify_otp_builds_session():
    c = _client()
    c._platform_jwt = "platform"
    exp_ms = int(datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc).timestamp() * 1000)
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "access_token": "taxpayer-tok",
                    "token_expiry": exp_ms,
                    "session_expiry": exp_ms,
                },
            },
            url="https://api.sandbox.co.in/gst/compliance/tax-payer/otp/verify?otp=111111",
        )
        session = c.verify_otp(username="u", gstin="27ISKPK1273H1ZF", otp="111111")
    assert session.access_token == "taxpayer-tok"
    assert session.token_expires_at.year == 2026
    # OTP must be passed as query param, never logged via sensitive flag path
    kwargs = req.call_args.kwargs
    assert kwargs["params"]["otp"] == "111111"


def test_logout_tec4002_is_non_fatal():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "0",
                    "error": {
                        "error_cd": "TEC4002",
                        "message": "Invalid Data Format.",
                    },
                },
            },
        )
        result = c.logout("taxpayer-tok")
    assert result.ok is False
    assert result.error_cd == "TEC4002"


def test_save_gstr1_returns_reference_id():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {"reference_id": "ref-123"},
                },
            },
        )
        result = c.save_gstr1(
            "tok",
            period="2025-04",
            save_body={"gstin": "27ISKPK1273H1ZF", "fp": "042025", "b2b": []},
        )
    assert result.reference_id == "ref-123"
    # request(method, url, ...)
    assert req.call_args.args[0] == "POST"
    assert "/gstr-1/2025/04" in req.call_args.args[1]


def test_file_gstr1_puts_otp_in_query_params_only():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {"ack_num": "ACK1"},
                },
            },
            url=(
                "https://api.sandbox.co.in/gst/compliance/tax-payer/gstrs/"
                "gstr-1/2025/04/file?pan=AAACQ3770E&otp=999888"
            ),
        )
        result = c.file_gstr1(
            "tok",
            period="2025-04",
            pan="AAACQ3770E",
            otp="999888",
            file_body={"gstin": "27ISKPK1273H1ZF", "chksum": "abc", "sec_sum": []},
        )
    assert result.ack_number == "ACK1"
    assert req.call_args.kwargs["params"]["otp"] == "999888"
    assert req.call_args.kwargs["params"]["pan"] == "AAACQ3770E"
    # OTP must not appear in JSON body
    assert "otp" not in (req.call_args.kwargs.get("json") or {})


def test_gstn_error_on_save_raises():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "0",
                    "error": {"error_cd": "AUTH117", "message": "already filed"},
                },
            },
        )
        with pytest.raises(FilingGstnError) as ei:
            c.save_gstr1("tok", period="2025-04", save_body={"fp": "042025"})
    assert ei.value.error_cd == "AUTH117"


def test_parse_return_status_success_is_inner_p_not_outer_1():
    envelope = {
        "code": 200,
        "data": {
            "status_cd": "1",
            "data": {
                "action": "SAVE",
                "form_typ": "R1",
                "status_cd": "P",
            },
        },
    }
    info = parse_return_status(envelope)
    assert info.outer_status_cd == "1"
    assert info.gstn_status_cd == "P"
    assert info.is_success is True
    assert info.is_failed is False
    assert filing_run_status_after_save_poll(info) == ("saved", None, None)


def test_save_outer_ok_inner_er_marks_save_failed_not_saved():
    """Outer status_cd \"1\" + inner ER must end the run as save_failed, not saved.

    Mirrors Sandbox OpenAPI example \"RET191106 Error in JSON structure\" and the
    live probe where Save returned reference_id then Status showed ER.
    """
    save_envelope = {
        "code": 200,
        "data": {
            "status_cd": "1",
            "data": {"reference_id": "ref-er-1"},
        },
    }
    status_envelope = {
        "code": 200,
        "data": {
            "status_cd": "1",
            "data": {
                "action": "SAVE",
                "error_report": {
                    "error_cd": "RET191106",
                    "error_msg": "Error in Json structure validation.",
                },
                "form_typ": "R1",
                "status_cd": "ER",
            },
        },
    }

    c = _client()
    with patch.object(c._http, "request") as req:
        req.side_effect = [
            _resp(200, save_envelope),
            _resp(200, status_envelope),
        ]
        save_result = c.save_gstr1(
            "tok",
            period="2025-04",
            save_body={"gstin": "27ISKPK1273H1ZF", "fp": "042025"},
        )
        assert save_result.reference_id == "ref-er-1"
        # Save acceptance alone must not be treated as GSTN success.
        assert not (
            save_result.return_status and save_result.return_status.is_success
        )

        status_result = c.get_return_status(
            "tok", period="2025-04", reference_id="ref-er-1",
        )

    info = status_result.return_status
    assert info is not None
    assert info.outer_status_cd == "1"
    assert info.gstn_status_cd == "ER"
    assert info.is_failed is True
    assert info.error_cd == "RET191106"

    run_status, err_cd, err_msg = filing_run_status_after_save_poll(info)
    assert run_status == "save_failed"
    assert run_status != "saved"
    assert err_cd == "RET191106"
    assert "Json structure" in (err_msg or "")

    # Persist path: filing_runs ends as save_failed with error fields stored.
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(
            data=[
                {
                    "id": "run-1",
                    "status": "save_failed",
                    "error_code": "RET191106",
                    "error_message": err_msg,
                }
            ]
        )
    )
    updated = filing_store.apply_save_status_to_run(
        sb,
        "run-1",
        return_status=info,
        envelope=status_envelope,
    )
    assert updated["status"] == "save_failed"
    update_payload = sb.table.return_value.update.call_args.args[0]
    assert update_payload["status"] == "save_failed"
    assert update_payload["error_code"] == "RET191106"
    assert update_payload["status"] != "saved"


def test_get_return_status_does_not_raise_on_inner_er():
    """Status poll must return ER so the run can be marked save_failed."""
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {
                        "action": "SAVE",
                        "status_cd": "ER",
                        "error_report": {
                            "error_cd": "RET191106",
                            "error_msg": "Error in Json structure validation.",
                        },
                    },
                },
            },
        )
        result = c.get_return_status("tok", period="2025-04", reference_id="r1")
    assert result.return_status is not None
    assert result.return_status.is_failed is True


def test_proceed_raises_when_inner_status_is_er():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {
                        "status_cd": "ER",
                        "error_report": {
                            "error_cd": "RET192421",
                            "error_msg": "prior return not filed",
                        },
                    },
                },
            },
        )
        with pytest.raises(FilingGstnError) as ei:
            c.proceed_to_file("tok", period="2025-04")
    assert ei.value.error_cd in {"RET192421", "ER"}
