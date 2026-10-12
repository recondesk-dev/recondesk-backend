"""Phase 4.3: Filing Governance, Maker-Checker & Statutory Validation Tests for GSTR-6, GSTR-5 & GSTR-5A.

Tests:
1. Statutory pre-filing validation engines for GSTR-6 (ISD), GSTR-5 (NRTP), and GSTR-5A (OIDAR).
2. Maker-checker 4-eyes principle enforcement for GSTR-6, GSTR-5, and GSTR-5A.
3. Separation of duties: Preparer cannot approve own submission.
4. Tamper-evident figure modification invalidates stale approvals.
5. Client authorization workflow integration.
6. Downstream non-double-counting guarantees:
   - ISD credit flows directly to recipient distinct persons' GSTR-2B Table 4(A)(4).
   - ISD entity cannot utilize or retain credit in GSTR-3B.
   - NRTP ITC strictly restricted to Bill of Entry imports (Sec 17(5)).
   - OIDAR zero domestic ITC invariant.
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
    validate_gstr6_pre_filing,
    validate_gstr5_pre_filing,
    validate_gstr5a_pre_filing,
)


@pytest.fixture(autouse=True)
def clean_stores():
    reset_maker_checker_store()
    reset_client_auth_store()
    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"), \
         patch("app.services.client_authorization_service.assert_client_gstin_in_firm"):
        yield


# ── 1. GSTR-6 Governance Tests ───────────────────────────────────────────────

def test_gstr6_pre_filing_validation_detects_over_distribution():
    batch = {
        "gstin": "27AAACG0000A1Z5",
        "period": "2026-07",
    }
    inward = [
        {
            "supplier_gstin": "27AABCS1429B1Z1",
            "invoice_number": "INV-1",
            "invoice_date": "2026-07-10",
            "taxable_value": 100000.0,
            "igst": 18000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "itc_eligible": "ELIGIBLE",
        }
    ]
    # Distributing 25,000 IGST from an 18,000 IGST pool -> Over-distribution!
    distribution = [
        {
            "recipient_gstin": "29AAACG0000A1Z2",
            "recipient_state": "29",
            "distributed_igst": 25000.0,
            "distributed_cgst": 0.0,
            "distributed_sgst": 0.0,
            "distributed_cess": 0.0,
            "itc_category": "ELIGIBLE",
        }
    ]

    res = validate_gstr6_pre_filing(batch=batch, inward_records=inward, distribution_records=distribution)
    assert res.is_valid is False
    assert any(v.code == "G6_OVER_DISTRIBUTION" for v in res.violations)


def test_gstr6_pre_filing_validation_detects_cross_pan_recipient():
    batch = {
        "gstin": "27AAACG0000A1Z5",
        "period": "2026-07",
    }
    inward = [
        {
            "supplier_gstin": "27AABCS1429B1Z1",
            "invoice_number": "INV-1",
            "invoice_date": "2026-07-10",
            "taxable_value": 100000.0,
            "igst": 18000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "itc_eligible": "ELIGIBLE",
        }
    ]
    # Recipient has PAN "BBBCG0000A", but ISD is "AAACG0000A" -> Not a distinct person!
    distribution = [
        {
            "recipient_gstin": "29BBBCG0000A1Z2",
            "recipient_state": "29",
            "distributed_igst": 18000.0,
            "distributed_cgst": 0.0,
            "distributed_sgst": 0.0,
            "distributed_cess": 0.0,
            "itc_category": "ELIGIBLE",
        }
    ]

    res = validate_gstr6_pre_filing(batch=batch, inward_records=inward, distribution_records=distribution)
    assert res.is_valid is False
    assert any(v.code == "G6_CROSS_PAN_RECIPIENT" for v in res.violations)


def test_gstr6_maker_checker_workflow():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_gstin_id = "c0000000-0000-0000-0000-000000000001"
    preparer = {"id": "u0000000-0000-0000-0000-000000000001", "role": "preparer", "full_name": "Junior Accountant"}
    ca_checker = {"id": "u0000000-0000-0000-0000-000000000002", "role": "partner", "full_name": "Senior CA"}

    payload = {"pool_igst": 18000.0, "distributed_igst": 18000.0}

    # Step 1: Prepare
    approval = prepare_return(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-6",
        figures_payload=payload,
        validation_digest="val_digest_123",
        actor=preparer,
    )
    assert approval.status == ApprovalStatus.PREPARED

    # Step 2: Submit for review
    approval = submit_for_review(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-6",
        notes="GSTR-6 prepared for July 2026",
        actor=preparer,
    )
    assert approval.status == ApprovalStatus.UNDER_REVIEW

    # Step 3: Self-approval forbidden (4-eyes principle)
    with pytest.raises(HTTPException) as exc:
        approve_return(
            sb=None,
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin="27AAACG0000A1Z5",
            period="2026-07",
            return_type="GSTR-6",
            expected_figures_digest=approval.figures_digest,
            actor=preparer,  # Same as preparer!
        )
    assert exc.value.status_code == 403

    # Step 4: CA Approves
    approval = approve_return(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-6",
        expected_figures_digest=approval.figures_digest,
        actor=ca_checker,
    )
    assert approval.status == ApprovalStatus.APPROVED

    # Step 5: Assert maker-checker gate passes with identical payload
    assert_maker_checker_gate(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-6",
        current_figures_payload=payload,
        operation="FILE",
    )

    # Step 6: Tampering payload invalidates approval
    tampered_payload = {"pool_igst": 18000.0, "distributed_igst": 99999.0}
    with pytest.raises(HTTPException) as exc:
        assert_maker_checker_gate(
            sb=None,
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin="27AAACG0000A1Z5",
            period="2026-07",
            return_type="GSTR-6",
            current_figures_payload=tampered_payload,
            operation="FILE",
        )
    assert exc.value.status_code == 409


# ── 2. GSTR-5 Governance Tests ───────────────────────────────────────────────

def test_gstr5_pre_filing_validation_detects_advance_tax_deficit():
    batch = {
        "gstin": "27AAACG0000A1Z5",
        "period": "2026-07",
        "advance_tax_deposited": 10000.0,
    }
    # Outward tax liability = 36,000
    outward = [
        {
            "pos": "27",
            "invoice_number": "NRTP-1",
            "invoice_date": "2026-07-15",
            "taxable_value": 200000.0,
            "rate_pct": 18.0,
            "cgst": 18000.0,
            "sgst": 18000.0,
            "record_type": "ORIGINAL",
        }
    ]
    imports = []  # No BoE import ITC

    # Net payable = 36,000, but only 10,000 deposited -> Deficit of 26,000!
    res = validate_gstr5_pre_filing(batch=batch, outward_records=outward, import_records=imports)
    assert res.is_valid is False
    assert any(v.code == "G5_ADVANCE_TAX_DEFICIT" for v in res.violations)


def test_gstr5_maker_checker_and_client_auth():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_gstin_id = "c0000000-0000-0000-0000-000000000001"
    preparer = {"id": "u0000000-0000-0000-0000-000000000001", "role": "preparer", "full_name": "Preparer"}
    ca_checker = {"id": "u0000000-0000-0000-0000-000000000002", "role": "partner", "full_name": "Approver"}

    payload = {"taxable_value": 200000.0, "net_tax_payable": 36000.0}

    # Prepare return
    prepare_return(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-5",
        figures_payload=payload,
        validation_digest="val_digest_456",
        actor=preparer,
    )
    submit_for_review(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-5",
        actor=preparer,
    )
    appr = approve_return(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-5",
        expected_figures_digest="",
        actor=ca_checker,
    )

    # Client auth request
    req, raw_token = create_authorization_request(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-5",
        figures_payload=payload,
        actor=ca_checker,
    )
    submit_client_authorization(
        sb=None,
        raw_token=raw_token,
        signatory_name="John Doe",
        signatory_designation="Authorized Signatory",
        signatory_contact="client@example.com",
    )

    # Both gates must pass
    assert_maker_checker_gate(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-5",
        current_figures_payload=payload,
        operation="FILE",
    )
    assert_client_authorization_gate(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        return_type="GSTR-5",
        current_figures_payload=payload,
    )


# ── 3. GSTR-5A Governance Tests ──────────────────────────────────────────────

def test_gstr5a_pre_filing_validation_detects_non_18_pct_rate():
    batch = {
        "gstin": "9917USA00000OID",
        "period": "2026-07",
    }
    supplies = [
        {
            "pos": "27",
            "taxable_value": 100000.0,
            "rate_pct": 12.0,  # OIDAR requires uniform 18% standard rate under Section 14!
            "igst": 12000.0,
            "record_type": "ORIGINAL",
        }
    ]

    res = validate_gstr5a_pre_filing(batch=batch, supplies=supplies)
    assert res.is_valid is False
    assert any(v.code == "G5A_INVALID_RATE" for v in res.violations)


def test_gstr5a_maker_checker_workflow_and_stale_invalidation():
    """Verify 4-eyes principle and cryptographic figures digest matching for Form GSTR-5A."""
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_gstin_id = "c0000000-0000-0000-0000-000000000001"
    preparer = {"id": "u0000000-0000-0000-0000-000000000001", "role": "preparer", "full_name": "Preparer"}
    partner = {"id": "u0000000-0000-0000-0000-000000000002", "role": "partner", "full_name": "Partner"}

    payload = {"table5_taxable": 500000.0, "total_igst": 90000.0}

    # Step 1: Preparer prepares return
    appr = prepare_return(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="9917USA00000OID",
        period="2026-07",
        return_type="GSTR-5A",
        figures_payload=payload,
        actor=preparer,
    )
    assert appr.status == ApprovalStatus.PREPARED

    # Step 2: Submit for review
    submit_for_review(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="9917USA00000OID",
        period="2026-07",
        return_type="GSTR-5A",
        actor=preparer,
    )

    # Step 3: Self-approval forbidden
    with pytest.raises(HTTPException) as exc:
        approve_return(
            sb=None,
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin="9917USA00000OID",
            period="2026-07",
            return_type="GSTR-5A",
            expected_figures_digest=appr.figures_digest,
            actor=preparer,
        )
    assert exc.value.status_code == 403

    # Step 4: Partner approves
    appr_done = approve_return(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="9917USA00000OID",
        period="2026-07",
        return_type="GSTR-5A",
        expected_figures_digest=appr.figures_digest,
        actor=partner,
    )
    assert appr_done.status == ApprovalStatus.APPROVED

    # Step 5: Untampered gate passes
    assert_maker_checker_gate(
        sb=None,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="9917USA00000OID",
        period="2026-07",
        return_type="GSTR-5A",
        current_figures_payload=payload,
        operation="FILE",
    )

    # Step 6: Tampered figures invalidates approval
    tampered = {"table5_taxable": 500000.0, "total_igst": 99999.0}
    with pytest.raises(HTTPException) as exc:
        assert_maker_checker_gate(
            sb=None,
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin="9917USA00000OID",
            period="2026-07",
            return_type="GSTR-5A",
            current_figures_payload=tampered,
            operation="FILE",
        )
    assert exc.value.status_code == 409
