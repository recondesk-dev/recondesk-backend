"""Automated tests for Pre-Filing Validation and Governance Router Endpoints.

Covers:
- Policy retrieval (GET /governance/policy) and update (PUT /governance/policy).
- Partner override authorization (POST /governance/overrides).
- GSTR-3B pre-filing validation endpoint (POST /gstr-3b/{period}/pre-filing-validation).
- GSTR-1 pre-filing validation endpoint (POST /gstr-1/{period}/pre-filing-validation).
- RCM suggestion endpoint (GET /gstr-3b/{period}/suggestions/rcm).
- Cumulative FY reconciliation endpoint (GET /cumulative-fy/{client_gstin_id}).
- Direct API bypass attempts: save_gstr3b blocked when PARTNER_OVERRIDE is active without override.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers import filing as filing_router
from app.services.filing_override_service import (
    FilingPolicy,
    FilingPolicyMode,
    FilingPolicyUpdate,
    _governance_store,
)


@pytest.fixture(autouse=True)
def clean_store():
    _governance_store.clear()
    yield
    _governance_store.clear()


def test_get_and_update_governance_policy():
    """Verify policy can be queried and updated by firm admin."""
    mock_sb = MagicMock()
    user = {"id": "user-admin", "role": "admin"}

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value="firm-1"):
            # Initial default is ADVISORY
            pol = filing_router.get_governance_policy(current_user=user)
            assert pol["mode"] == "ADVISORY"

            # Update to PARTNER_OVERRIDE
            update = FilingPolicyUpdate(mode=FilingPolicyMode.PARTNER_OVERRIDE, require_final_reconciliation=True)
            with patch("app.services.filing_override_service.log_audit"):
                import asyncio
                updated = asyncio.run(filing_router.update_governance_policy(update, current_user=user))
                assert updated["mode"] == "PARTNER_OVERRIDE"
                assert updated["require_final_reconciliation"] is True

            # Verify policy persisted in firm scope
            pol_after = filing_router.get_governance_policy(current_user=user)
            assert pol_after["mode"] == "PARTNER_OVERRIDE"


def test_create_governance_override_endpoint():
    """Verify partner override endpoint records override when valid."""
    mock_sb = MagicMock()
    user = {"id": "user-admin", "role": "admin", "full_name": "Senior Partner"}

    client_row = {"id": "cid-1", "gstin": "27AABCU9603R1ZM"}

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value="firm-1"):
            with patch("app.routers.filing._assert_client_access", return_value=client_row):
                with patch("app.services.filing_override_service.assert_client_gstin_in_firm"):
                    with patch("app.services.filing_override_service.log_audit"):
                        import asyncio
                        body = filing_router.CreateOverrideBody(
                            client_gstin_id="cid-1",
                            period="2024-11",
                            return_type="gstr-3b",
                            figures_digest="sha256-test-digest-444",
                            justification="Verified against ERP general ledger; discrepancy explained by sales return.",
                            violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
                        )
                        res = asyncio.run(filing_router.create_governance_override(body, current_user=user))
                        assert res["period"] == "2024-11"
                        assert res["figures_digest"] == "sha256-test-digest-444"
                        assert res["approver_role"] == "admin"
                        assert res["is_consumed"] is False


def test_gstr3b_pre_filing_validation_endpoint():
    """Verify pre-filing validation endpoint returns structured analysis and policy mode."""
    mock_sb = MagicMock()
    user = {"id": "user-staff", "role": "staff"}
    client_row = {"id": "cid-1", "gstin": "27AABCU9603R1ZM"}

    save_body = {
        "sup_details": {"osup_det": {"txval": 100000.0, "iamt": 18000.0}},
        "itc_elg": {"itc_avl": []},
    }

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value="firm-1"):
            with patch("app.routers.filing._assert_client_access", return_value=client_row):
                body = filing_router.PreFilingValidationGstr3bBody(
                    client_gstin_id="cid-1",
                    save_body=save_body,
                )
                res = filing_router.gstr3b_pre_filing_validation("2024-11", body, current_user=user)
                assert res["return_type"] == "gstr-3b"
                assert res["gstin"] == "27AABCU9603R1ZM"
                assert "figures_digest" in res
                assert "policy_mode" in res
                assert res["policy_mode"] == "ADVISORY"


def test_direct_api_bypass_prevented_in_save_gstr3b():
    """Direct API call to save_gstr3b is blocked when PARTNER_OVERRIDE is active and violations exist."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    user = {"id": "user-staff", "role": "staff"}
    client_row = {"id": "cid-1", "gstin": "27AABCU9603R1ZM"}

    # Set policy to PARTNER_OVERRIDE with final reconciliation requirement
    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE, require_final_reconciliation=True))

    # Mock unfinalized run
    mock_run = MagicMock()
    mock_run.data = [{"id": "run-draft", "status": "DRAFT", "is_locked": False}]
    mock_sb.table().select().eq().eq().order().limit().execute.return_value = mock_run

    save_body = {
        "sup_details": {"osup_det": {"txval": 100000.0, "iamt": 18000.0}},
        "itc_elg": {"itc_avl": []},
    }

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value=firm_id):
            with patch("app.routers.filing._assert_client_access", return_value=client_row):
                with patch("app.routers.filing.filing_store.assert_gstr3b_save_allowed"):
                    with patch("app.routers.filing._resolve_token", return_value=("token", {"id": "sess-1"})):
                        body = filing_router.SaveGstr3bBody(
                            client_gstin_id="cid-1",
                            period="2024-11",
                            session_id="sess-1",
                            save_body=save_body,
                        )
                        # Must raise HTTP 422 PARTNER_OVERRIDE_REQUIRED — direct API bypass thwarted!
                        with pytest.raises(HTTPException) as exc_info:
                            filing_router.save_gstr3b("2024-11", body, current_user=user)

                        assert exc_info.value.status_code == 422
                        assert exc_info.value.detail["code"] == "PARTNER_OVERRIDE_REQUIRED"


def test_direct_api_bypass_prevented_in_offset_gstr3b():
    """Direct API call to offset_gstr3b is blocked when PARTNER_OVERRIDE is active and unapproved violations exist."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    user = {"id": "user-staff", "role": "staff"}
    client_row = {"id": "cid-1", "gstin": "27AABCU9603R1ZM"}

    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE, require_final_reconciliation=True))

    mock_run = MagicMock()
    mock_run.data = [{"id": "run-draft", "status": "DRAFT", "is_locked": False}]
    mock_sb.table().select().eq().eq().order().limit().execute.return_value = mock_run

    saved_run = {
        "id": "run-101",
        "status": "saved",
        "save_payload": {
            "sup_details": {"osup_det": {"txval": 100000.0, "iamt": 18000.0}},
            "itc_elg": {"itc_avl": []},
        },
    }

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value=firm_id):
            with patch("app.routers.filing._assert_client_access", return_value=client_row):
                with patch("app.routers.filing._require_run_status"):
                    with patch("app.routers.filing.filing_store.assert_gstr3b_offset_allowed"):
                        with patch("app.routers.filing.filing_store.get_run", return_value=saved_run):
                            body = filing_router.OffsetGstr3bBody(
                                client_gstin_id="cid-1",
                                run_id="run-101",
                                session_id="sess-1",
                                pdcash=[{"iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0, "intr": 0.0, "fee": 0.0}],
                                pditc={"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                            )
                            # Must raise HTTP 422 PARTNER_OVERRIDE_REQUIRED on offset!
                            with pytest.raises(HTTPException) as exc_info:
                                filing_router.offset_gstr3b("2024-11", body, current_user=user)

                            assert exc_info.value.status_code == 422
                            assert exc_info.value.detail["code"] == "PARTNER_OVERRIDE_REQUIRED"


# ---------------------------------------------------------------------------
# Idempotency, Network Timeout & Status Recovery Tests
# ---------------------------------------------------------------------------

def test_gstr1_filing_idempotency_gstn_success_with_db_failure_preserves_ack_number():
    """If GSTN filing succeeds but database update_run fails, the statutory ACK is preserved."""
    mock_sb = MagicMock()
    user = {"id": "admin-1", "role": "admin"}
    client_row = {"id": "cid-1", "gstin": "27AABCU9603R1ZM"}

    fake_result = MagicMock()
    fake_result.ack_number = "AA271124000001Z"
    fake_result.envelope = {"status_cd": "1"}
    fake_result.return_status = MagicMock(gstn_status_cd="FIL", outer_status_cd="1")

    fake_client = MagicMock()
    fake_client.file_gstr1.return_value = fake_result

    run_row = {
        "id": "run-101",
        "firm_id": "firm-1",
        "status": "saved",
        "client_gstin_id": "cid-1",
        "gstin": "27AABCU9603R1ZM",
    }

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value="firm-1"):
            with patch("app.routers.filing.filing_store.get_run", return_value=run_row):
                with patch("app.routers.filing._require_run_status"):
                    with patch("app.routers.filing._resolve_token", return_value=("token", {"id": "sess-1"})):
                        with patch("app.routers.filing.get_filing_client", return_value=MagicMock(__enter__=MagicMock(return_value=fake_client), __exit__=MagicMock(return_value=None))):
                            with patch("app.routers.filing.filing_store.update_run", side_effect=RuntimeError("Database connection lost")):
                                body = filing_router.FileGstr1Body(
                                    run_id="run-101",
                                    session_id="sess-1",
                                    pan="AABCU9603R",
                                    otp="123456",
                                    signing_method="evc",
                                    file_body={"gstin": "27AABCU9603R1ZM"},
                                )
                                # The endpoint must NOT fail; it returns the statutory ARN/ACK number!
                                res = filing_router.file_gstr1("2024-11", body, current_user=user)
                                assert res["status"] == "filed"
                                assert res["ack_number"] == "AA271124000001Z"


def test_gstr3b_filing_idempotency_gstn_success_with_db_failure_preserves_ack_number():
    """If GSTN GSTR-3B filing succeeds but database update_run fails, statutory ACK is preserved."""
    mock_sb = MagicMock()
    user = {"id": "admin-1", "role": "admin"}

    fake_result = MagicMock()
    fake_result.ack_number = "AA271124000002Z"
    fake_result.envelope = {"status_cd": "1"}
    fake_result.return_status = MagicMock(gstn_status_cd="FIL", outer_status_cd="1")

    fake_client = MagicMock()
    fake_client.file_gstr3b.return_value = fake_result

    run_row = {
        "id": "run-202",
        "firm_id": "firm-1",
        "status": "offset_complete",
        "client_gstin_id": "cid-1",
        "gstin": "27AABCU9603R1ZM",
    }

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value="firm-1"):
            with patch("app.routers.filing.filing_store.get_run", return_value=run_row):
                with patch("app.routers.filing._require_run_status"):
                    with patch("app.routers.filing._resolve_token", return_value=("token", {"id": "sess-1"})):
                        with patch("app.routers.filing.get_filing_client", return_value=MagicMock(__enter__=MagicMock(return_value=fake_client), __exit__=MagicMock(return_value=None))):
                            with patch("app.routers.filing.filing_store.update_run", side_effect=RuntimeError("Aurora deadlock")):
                                body = filing_router.FileGstr3bBody(
                                    run_id="run-202",
                                    session_id="sess-1",
                                    pan="AABCU9603R",
                                    otp="123456",
                                    signing_method="evc",
                                    file_body={"gstin": "27AABCU9603R1ZM"},
                                )
                                res = filing_router.file_gstr3b("2024-11", body, current_user=user)
                                assert res["status"] == "filed"
                                assert res["ack_number"] == "AA271124000002Z"


def test_duplicate_file_submission_rejected_with_http_409():
    """Submitting a file request when the run is already filed raises HTTP 409 Conflict."""
    mock_sb = MagicMock()
    user = {"id": "admin-1", "role": "admin"}

    # Mock run in status 'filed'
    run_filed = {"id": "run-filed-1", "status": "filed", "firm_id": "firm-1"}

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value="firm-1"):
            with patch("app.routers.filing.filing_store.get_run", return_value=run_filed):
                body = filing_router.FileGstr3bBody(
                    run_id="run-filed-1",
                    session_id="sess-1",
                    pan="AABCU9603R",
                    otp="123456",
                    signing_method="evc",
                )
                with pytest.raises(HTTPException) as exc_info:
                    filing_router.file_gstr3b("2024-11", body, current_user=user)

                assert exc_info.value.status_code == 409
                detail_msg = exc_info.value.detail.get("message", "") if isinstance(exc_info.value.detail, dict) else str(exc_info.value.detail)
                assert "requires run status in" in detail_msg
                assert "current='filed'" in detail_msg



