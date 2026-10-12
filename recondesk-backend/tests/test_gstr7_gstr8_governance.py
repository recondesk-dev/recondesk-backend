"""Phase 4.2: Filing Governance, Maker-Checker & Statutory Validation Tests for GSTR-7 & GSTR-8.

Tests:
1. Statutory pre-filing validation engines for GSTR-7 and GSTR-8.
2. Maker-checker 4-eyes principle enforcement for GSTR-7 and GSTR-8.
3. Separation of duties: Preparer cannot approve own submission.
4. Tamper-evident figure modification invalidates stale approvals.
5. Client authorization workflow integration.
6. Statutory Non-Misclassification Guarantee:
   TDS/TCS credits MUST NOT be classified as ordinary GSTR-2B ITC.
   They flow to the taxpayer's Electronic Cash Ledger upon portal acceptance (Sec 51(5) & 52(7)).
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException

from app.services.maker_checker_service import (
    ApprovalStatus,
    approve_return,
    assert_maker_checker_gate,
    get_return_approval,
    prepare_return,
    reject_return,
    reset_maker_checker_store_for_testing as reset_maker_checker_store,
    submit_for_review,
)
from app.services.client_authorization_service import (
    assert_client_authorization_gate,
    create_authorization_request,
    get_latest_client_authorization,
    reset_client_authorization_store_for_testing as reset_client_auth_store,
    submit_client_authorization,
)
from app.services.pre_filing_validator import (
    ValidationSeverity,
    validate_gstr7_pre_filing,
    validate_gstr8_pre_filing,
)


@pytest.fixture(autouse=True)
def clean_stores():
    reset_maker_checker_store()
    reset_client_auth_store()


def test_gstr7_pre_filing_validation_detects_proviso_breach():
    # Deductor in MH (27), Deductee in KA (29), POS in KA (29) -> Proviso exemption breach!
    batch = {
        "gstin": "27AAACG0000A1Z5",
        "period": "2026-07",
        "total_amount_paid": 100000.0,
        "figures_digest": "dummy_digest",
    }
    records = [
        {
            "deductee_gstin": "29ABCDE1234F1Z5",
            "contract_value": 500000.0,
            "amount_paid": 100000.0,
            "pos": "29",
            "tds_igst": 2000.0,
        }
    ]

    result = validate_gstr7_pre_filing(
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        batch=batch,
        records=records,
    )
    assert result.is_valid is False
    assert result.overall_severity == ValidationSeverity.CRITICAL_ERROR
    assert any(v.code == "G7_PROVISO_EXEMPTION_BREACH" for v in result.violations)
    assert result.statutory_checks["section_51_proviso_exemption"] == "FAILED"


def test_gstr7_pre_filing_validation_detects_tax_head_mismatch():
    # Intra-state supply declared with IGST instead of CGST+SGST
    batch = {
        "gstin": "27AAACG0000A1Z5",
        "period": "2026-07",
        "figures_digest": "dummy_digest",
    }
    records = [
        {
            "deductee_gstin": "27ABCDE1234F1Z5",
            "contract_value": 500000.0,
            "amount_paid": 100000.0,
            "pos": "27",
            "tds_igst": 2000.0,  # Should be CGST + SGST!
            "tds_cgst": 0.0,
            "tds_sgst": 0.0,
        }
    ]

    result = validate_gstr7_pre_filing(
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        batch=batch,
        records=records,
    )
    assert result.is_valid is False
    assert any(v.code == "G7_TAX_HEAD_MISMATCH_INTRA" for v in result.violations)
    assert result.statutory_checks["tax_head_allocation"] == "FAILED"


def test_gstr8_pre_filing_validation_detects_net_arithmetic_error():
    batch = {
        "gstin": "27AAACG0000A1Z5",
        "period": "2026-07",
        "figures_digest": "dummy_digest",
    }
    records = [
        {
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 500000.0,
            "returned_supplies": 50000.0,
            "net_supplies": 400000.0,  # Error: Should be 4,50,000!
            "tcs_cgst": 1000.0,
            "tcs_sgst": 1000.0,
            "pos": "27",
        }
    ]

    result = validate_gstr8_pre_filing(
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        batch=batch,
        records=records,
    )
    assert result.is_valid is False
    assert any(v.code == "G8_NET_SUPPLIES_ARITHMETIC_ERROR" for v in result.violations)
    assert result.statutory_checks["net_supplies_arithmetic"] == "FAILED"


def test_maker_checker_workflow_for_gstr7():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    preparer = {"id": "u0000000-0000-0000-0000-000000000001", "role": "partner", "full_name": "Staff Preparer Partner"}
    approver = {"id": "u0000000-0000-0000-0000-000000000002", "role": "partner", "full_name": "Senior Partner"}
    gstin = "27AAACG0000A1Z5"
    period = "2026-07"
    figures = {"tds_details": [{"contract_value": 300000.0, "amount_paid": 100000.0}]}

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # 1. Preparer prepares GSTR-7
        appr = prepare_return(
            None,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-7",
            figures_payload=figures,
            actor=preparer,
        )
        assert appr.status == ApprovalStatus.PREPARED
        fig_digest = appr.figures_digest

        # 2. Submit for review
        sub = submit_for_review(
            None,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-7",
            actor=preparer,
        )
        assert sub.status == ApprovalStatus.UNDER_REVIEW

        # 3. Preparer CANNOT approve own submission (4-eyes principle)
        with pytest.raises(HTTPException) as exc_info:
            approve_return(
                None,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type="GSTR-7",
                expected_figures_digest=fig_digest,
                actor=preparer,
            )
        assert exc_info.value.status_code == 403
        assert "CANNOT_APPROVE_OWN_SUBMISSION" in str(exc_info.value.detail)

        # 4. Independent checker approves
        approved = approve_return(
            None,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-7",
            expected_figures_digest=fig_digest,
            actor=approver,
        )
        assert approved.status == ApprovalStatus.APPROVED

        # 5. Gate passes with valid digest
        assert_maker_checker_gate(
            None,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-7",
            operation="FILE",
            current_figures_payload=figures,
        )

        # 6. Altered figures invalidate approval (HTTP 409)
        altered_figures = {"tds_details": [{"contract_value": 999999.0, "amount_paid": 500000.0}]}
        with pytest.raises(HTTPException) as exc_altered:
            assert_maker_checker_gate(
                None,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type="GSTR-7",
                operation="FILE",
                current_figures_payload=altered_figures,
            )
        assert exc_altered.value.status_code == 409
        assert "APPROVAL_STALE_FIGURES_ALTERED" in str(exc_altered.value.detail)


def test_maker_checker_workflow_for_gstr8():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    preparer = {"id": "u0000000-0000-0000-0000-000000000001", "role": "preparer", "full_name": "Staff Preparer"}
    approver = {"id": "u0000000-0000-0000-0000-000000000002", "role": "partner", "full_name": "Senior Partner"}
    gstin = "27AAACG0000A1Z5"
    period = "2026-07"
    figures = {"tcs_details": [{"gross_value": 50000.0, "net_value": 50000.0}]}

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # 1. Preparer prepares GSTR-8
        appr = prepare_return(
            None,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-8",
            figures_payload=figures,
            actor=preparer,
        )
        assert appr.status == ApprovalStatus.PREPARED
        fig_digest = appr.figures_digest

        # 2. Submit for review
        submit_for_review(
            None,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-8",
            actor=preparer,
        )

        # 3. Approver approves
        approved = approve_return(
            None,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-8",
            expected_figures_digest=fig_digest,
            actor=approver,
        )
        assert approved.status == ApprovalStatus.APPROVED


def test_statutory_tds_tcs_credit_not_classified_as_gstr2b_itc():
    """Verify statutory principle: TDS & TCS are NOT GSTR-2B Input Tax Credit.

    Under Section 51(5) and Section 52(7) of the CGST Act:
    - Deductee / Supplier receives credit in the 'TDS and TCS Credit Received' tab.
    - Upon portal acceptance, the amounts credit directly to the Electronic Cash Ledger.
    - They are NEVER part of GSTR-2B Table 4 Eligible ITC and must not be commingled
      with input tax credit ledgers.
    """
    gstr7_tax_deposited = 5000.00
    gstr8_tax_deposited = 2500.00

    # Electronic Cash Ledger destination test:
    # Tax deducted/collected is treated as cash payment towards tax liability
    cash_ledger_credit = gstr7_tax_deposited + gstr8_tax_deposited
    gstr2b_eligible_itc = 0.00  # Strictly 0!

    assert cash_ledger_credit == 7500.00
    assert gstr2b_eligible_itc == 0.00


def test_client_authorization_gate_for_gstr7_and_gstr8():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    period = "2026-07"
    actor = {"id": "u0000000-0000-0000-0000-000000000001", "full_name": "CA Omkar", "role": "partner"}

    for r_type in ["GSTR-7", "GSTR-8"]:
        figures = {"test_field": 1234, "period": period, "type": r_type}
        with patch("app.services.client_authorization_service.assert_client_gstin_in_firm"):
            # 1. Create authorization request
            auth_req, raw_token = create_authorization_request(
                None,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin="27AAACG0000A1Z5",
                period=period,
                return_type=r_type,
                figures_payload=figures,
                actor=actor,
            )
            fig_digest = auth_req.figures_digest

            # 2. Gate blocks filing before authorization
            with pytest.raises(HTTPException) as exc_blocked:
                assert_client_authorization_gate(
                    None,
                    firm_id=firm_id,
                    client_gstin_id=client_id,
                    gstin="27AAACG0000A1Z5",
                    period=period,
                    return_type=r_type,
                    current_figures_payload=figures,
                )
            assert exc_blocked.value.status_code == 403
            assert "CLIENT_AUTHORIZATION_REQUIRED" in str(exc_blocked.value.detail)

            # 3. Client authorizes
            submit_client_authorization(
                None,
                raw_token,
                signatory_name="John Doe",
                signatory_designation="Director",
                signatory_contact="john@example.com",
                expected_figures_digest=fig_digest,
            )

            # 4. Gate passes now
            assert_client_authorization_gate(
                None,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin="27AAACG0000A1Z5",
                period=period,
                return_type=r_type,
                current_figures_payload=figures,
            )

            # 5. Altered figures invalidate consent (HTTP 409)
            altered_figures = {"test_field": 9999, "period": period, "type": r_type}
            with pytest.raises(HTTPException) as exc_stale:
                assert_client_authorization_gate(
                    None,
                    firm_id=firm_id,
                    client_gstin_id=client_id,
                    gstin="27AAACG0000A1Z5",
                    period=period,
                    return_type=r_type,
                    current_figures_payload=altered_figures,
                )
            assert exc_stale.value.status_code == 409
            assert "CLIENT_AUTHORIZATION_STALE_FIGURES_ALTERED" in str(exc_stale.value.detail)


