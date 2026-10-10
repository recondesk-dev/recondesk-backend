"""Comprehensive End-to-End tests for GSTR-3B filing pipeline: Save -> Offset -> EVC/DSC -> File."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.filing.filing_store import Gstr3bPeriodLockedError
from app.filing.sandbox_filing_client import FilingApiResult
from app.routers import filing as filing_router
from app.routers.filing import require_gstr3b_filing_enabled


PERIOD = "2026-07"
CLIENT_ID = "00000000-0000-0000-0000-000000000010"
GSTIN = "27AABCU9603R1ZM"
FIRM_ID = "firm-e2e"
SESSION_ID = "session-e2e-1"
RUN_ID = "run-e2e-1"


def _sample_save_body() -> dict[str, Any]:
    return {
        "gstin": GSTIN,
        "ret_period": "072026",
        "tx_pmt": {
            "pdcash": [
                {
                    "liab_ldg_id": 1,
                    "trans_typ": 30002,
                    "ipd": 100,
                    "cpd": 0,
                    "spd": 0,
                    "cspd": 0,
                    "i_intrpd": 0,
                    "c_intrpd": 0,
                    "s_intrpd": 0,
                    "cs_intrpd": 0,
                    "c_lfeepd": 0,
                    "s_lfeepd": 0,
                }
            ],
            "pditc": {
                "liab_ldg_id": 1,
                "trans_typ": 30002,
                "i_pdi": 50,
                "i_pdc": 0,
                "i_pds": 0,
                "c_pdc": 0,
                "c_pdi": 0,
                "s_pds": 0,
                "s_pdi": 0,
                "cs_pdcs": 0,
            },
        },
    }


def _sample_ledger() -> dict[str, Any]:
    return {
        "gstin": GSTIN,
        "itc_bal": {
            "igst_bal": 10000,
            "cgst_bal": 0,
            "sgst_bal": 0,
            "cess_bal": 0,
        },
        "cash_bal": {
            "igst": {"tx": 10000, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
            "cgst": {"tx": 0, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
            "sgst": {"tx": 0, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
            "cess": {"tx": 0, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
        },
    }


class FakeFilingClient:
    def __init__(self):
        self.file_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def save_gstr3b(self, *args, **kwargs):
        return FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-SAVE-100"}}},
            reference_id="REF-SAVE-100",
            data={"reference_id": "REF-SAVE-100"},
        )

    def get_gstr3b_details(self, *args, **kwargs):
        return FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": _sample_save_body()}},
            data=_sample_save_body(),
        )

    def get_ledger_balance(self, *args, **kwargs):
        return FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": _sample_ledger()}},
            data=_sample_ledger(),
        )

    def offset_gstr3b_liability(self, *args, **kwargs):
        return FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-OFFSET-200"}}},
            reference_id="REF-OFFSET-200",
            data={"reference_id": "REF-OFFSET-200"},
        )

    def generate_evc_otp_gstr3b(self, *args, **kwargs):
        return FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"success": True}}},
            data={"success": True},
        )

    def file_gstr3b(self, *args, **kwargs):
        self.file_calls.append(kwargs)
        return FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"ack_num": "AA2707260000001"}}},
            ack_number="AA2707260000001",
            data={"ack_num": "AA2707260000001"},
        )


@contextmanager
def _mock_filing_pipeline(fake_client: FakeFilingClient, initial_status: str = "saved"):
    sb = MagicMock()
    run_state = {
        "id": RUN_ID,
        "firm_id": FIRM_ID,
        "status": initial_status,
        "gstin": GSTIN,
        "period": PERIOD,
        "return_type": "gstr-3b",
    }

    def _get_run(*args, **kwargs):
        return dict(run_state)

    def _update_run(sb_mock, rid, **kwargs):
        run_state.update(kwargs)
        return dict(run_state)

    def _load_run(sb_mock, fid, rid):
        return dict(run_state)

    patches = [
        patch.object(filing_router, "get_supabase", return_value=sb),
        patch.object(filing_router, "_firm_id", return_value=FIRM_ID),
        patch.object(filing_router, "_assert_client_access", return_value={"id": CLIENT_ID, "gstin": GSTIN}),
        patch.object(filing_router, "_resolve_token", return_value=("tok_123", {"id": SESSION_ID})),
        patch.object(filing_router, "get_filing_client", return_value=fake_client),
        patch.object(filing_router, "require_gstr3b_filing_enabled", return_value=None),
        patch.object(filing_router, "_load_run_for_firm", side_effect=_load_run),
        patch.object(filing_router.filing_store, "assert_gstr3b_offset_allowed", return_value=None),
        patch.object(filing_router.filing_store, "assert_gstr3b_save_allowed", return_value=None),
        patch.object(filing_router.filing_store, "get_run", side_effect=_get_run),
        patch.object(filing_router.filing_store, "update_run", side_effect=_update_run),
    ]
    for p in patches:
        p.start()
    try:
        yield run_state
    finally:
        for p in reversed(patches):
            p.stop()


def test_e2e_gstr3b_filing_pipeline_evc():
    """Verifies complete lifecycle with EVC: Save -> Preview -> Offset -> EVC OTP -> File -> ACK."""
    fake_client = FakeFilingClient()
    with _mock_filing_pipeline(fake_client, initial_status="saved") as run_state:
        user = {"id": "user-e2e"}

        # Step 1: Save GSTR-3B
        save_body = filing_router.SaveGstr3bBody(
            client_gstin_id=CLIENT_ID,
            period=PERIOD,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            save_body=_sample_save_body(),
        )
        save_res = filing_router.save_gstr3b(PERIOD, save_body, current_user=user)
        assert save_res["status"] == "save_pending"
        assert save_res["reference_id"] == "REF-SAVE-100"

        # Step 2: Offset Preview (re-affirm run status as saved after GSTN confirmation)
        run_state["status"] = "saved"
        preview_res = filing_router.gstr3b_offset_preview(
            PERIOD,
            client_gstin_id=CLIENT_ID,
            session_id=SESSION_ID,
            current_user=user,
        )
        assert "pdcash" in preview_res
        assert "pditc" in preview_res

        # Step 3: Execute Offset
        offset_body = filing_router.OffsetGstr3bBody(
            client_gstin_id=CLIENT_ID,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            pdcash=preview_res["pdcash"],
            pditc=preview_res["pditc"],
        )
        offset_res = filing_router.offset_gstr3b(PERIOD, offset_body, current_user=user)
        assert offset_res["status"] == "offset_pending"
        assert offset_res["reference_id"] == "REF-OFFSET-200"

        # Advance state to offset_complete / saved for evc
        run_state["status"] = "offset_complete"

        # Step 4: Request EVC OTP
        evc_body = filing_router.EvcOtpGstr3bBody(
            client_gstin_id=CLIENT_ID,
            pan="AABCU9603R",
            session_id=SESSION_ID,
            run_id=RUN_ID,
        )
        evc_res = filing_router.generate_evc_otp_gstr3b(
            PERIOD,
            evc_body,
            current_user=user,
        )
        assert evc_res["message"] == "EVC OTP sent to authorized signatory"

        # Step 5: File with EVC OTP
        file_body = filing_router.FileGstr3bBody(
            client_gstin_id=CLIENT_ID,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            signing_method="evc",
            otp="123456",
            pan="AABCU9603R",
        )
        file_res = filing_router.file_gstr3b(PERIOD, file_body, current_user=user)
        assert file_res["status"] == "filed"
        assert file_res["ack_number"] == "AA2707260000001"
        assert len(fake_client.file_calls) == 1
        assert fake_client.file_calls[0]["otp"] == "123456"
        assert fake_client.file_calls[0]["signing_method"] == "evc"


def test_e2e_gstr3b_filing_pipeline_dsc():
    """Verifies complete corporate lifecycle with DSC: File with PKCS#7 -> ACK."""
    fake_client = FakeFilingClient()
    with _mock_filing_pipeline(fake_client, initial_status="offset_complete"):
        user = {"id": "user-e2e"}

        dsc_signature = "MIAGCSqGSIb3DQEHAqCAMIIBxwYJKoZIhvcNAQcBoIIBtASCAWgwggFkAgEAMQA="
        file_body = filing_router.FileGstr3bBody(
            client_gstin_id=CLIENT_ID,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            signing_method="dsc",
            signature=dsc_signature,
            pan="AABCU9603R",
        )
        file_res = filing_router.file_gstr3b(PERIOD, file_body, current_user=user)
        assert file_res["status"] == "filed"
        assert file_res["ack_number"] == "AA2707260000001"

        assert len(fake_client.file_calls) == 1
        assert fake_client.file_calls[0]["signature"] == dsc_signature
        assert fake_client.file_calls[0]["signing_method"] == "dsc"
        assert fake_client.file_calls[0]["otp"] is None


def test_gstr3b_safety_gate_disabled_in_production(monkeypatch):
    """Mutating offset and filing endpoints must reject with HTTP 503 GSTR3B_FILING_DISABLED when disabled."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("GSTR3B_FILING_ENABLED", raising=False)
    get_settings.cache_clear()

    try:
        # 1. Direct call to gate raises 503
        with pytest.raises(HTTPException) as exc_info:
            require_gstr3b_filing_enabled()
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "GSTR3B_FILING_DISABLED"

        # 2. Gate settings verification
        s = get_settings()
        assert s.gstr3b_filing_enabled is False
    finally:
        get_settings.cache_clear()


def test_gstr3b_stale_offset_protection():
    """Offset call must raise HTTP 409 GSTR3B_OFFSET_STALE if proposed offset mismatches live computation."""
    fake_client = FakeFilingClient()
    with _mock_filing_pipeline(fake_client, initial_status="saved"):
        # Submit stale/tampered pdcash that does not match live calculation
        stale_body = filing_router.OffsetGstr3bBody(
            client_gstin_id=CLIENT_ID,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            pdcash=[{"tampered": True}],
            pditc={},
        )
        with pytest.raises(HTTPException) as exc_info:
            filing_router.offset_gstr3b(PERIOD, stale_body, current_user={"id": "u"})
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "GSTR3B_OFFSET_STALE"


def test_gstr3b_period_locked_prevents_refiling():
    """Offset or filing must reject when period has already been filed or locked."""
    fake_client = FakeFilingClient()
    with _mock_filing_pipeline(fake_client, initial_status="saved"):
        with patch.object(
            filing_router.filing_store,
            "assert_gstr3b_offset_allowed",
            side_effect=Gstr3bPeriodLockedError(
                message="Period already filed",
                action="Offset",
                gstin=GSTIN,
                period=PERIOD,
                locking_run={"id": "lock-1", "status": "filed"},
            ),
        ):
            offset_body = filing_router.OffsetGstr3bBody(
                client_gstin_id=CLIENT_ID,
                session_id=SESSION_ID,
                run_id=RUN_ID,
                pdcash=[],
                pditc={},
            )
            with pytest.raises(HTTPException) as exc_info:
                filing_router.offset_gstr3b(PERIOD, offset_body, current_user={"id": "u"})
            assert exc_info.value.status_code == 409
            assert exc_info.value.detail["code"] == "GSTR3B_PERIOD_LOCKED"
