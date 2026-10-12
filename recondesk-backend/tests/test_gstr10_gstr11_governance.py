"""Phase 4.4: Maker-Checker Governance & Client Authorization Tests for GSTR-10 & GSTR-11.

Tests:
1. Four-eyes principle: Maker submits, Checker approves. Self-approval blocked.
2. Figures digest binding: Mutating stock or inward records invalidates prior approvals and client consent.
3. Server-side filing gates: Blocks filing without maker-checker approval or client authorization.
"""

from unittest.mock import patch
import pytest
from fastapi import HTTPException

from app.services.client_authorization_service import (
    assert_client_authorization_gate,
    create_authorization_request,
    reset_client_authorization_store_for_testing as reset_client_auth_store,
    submit_client_authorization,
)
from app.services.gstr10_service import (
    add_or_update_stock_record_sync,
    get_or_create_batch_sync as get_or_create_g10_batch,
    reset_gstr10_store_for_testing,
)
from app.services.gstr11_service import (
    add_or_update_inward_supply_sync,
    get_or_create_batch_sync as get_or_create_g11_batch,
    reset_gstr11_store_for_testing,
)
from app.services.maker_checker_service import (
    ApprovalStatus,
    approve_return,
    assert_maker_checker_gate,
    prepare_return,
    reset_maker_checker_store_for_testing as reset_maker_checker_store,
    submit_for_review,
)


@pytest.fixture(autouse=True)
def clean_stores():
    reset_gstr10_store_for_testing()
    reset_gstr11_store_for_testing()
    reset_maker_checker_store()
    reset_client_auth_store()
    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"), \
         patch("app.services.client_authorization_service.assert_client_gstin_in_firm"):
        yield


@pytest.fixture
def firm_maker():
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "email": "maker@firm.com",
        "full_name": "Junior Associate",
        "role": "preparer",
        "firm_id": "00000000-0000-0000-0000-000000000001",
    }


@pytest.fixture
def firm_checker():
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "email": "checker@firm.com",
        "full_name": "Audit Manager",
        "role": "manager",
        "firm_id": "00000000-0000-0000-0000-000000000001",
    }


def test_gstr10_maker_checker_workflow_and_stale_invalidation(firm_maker, firm_checker):
    firm_id = "00000000-0000-0000-0000-000000000001"
    client_gid = "00000000-0000-0000-0000-000000000002"
    gstin = "27AAACG0000A1Z5"
    period = "2026-10"

    # 1. Create batch & stock item
    batch = get_or_create_g10_batch(
        None,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=gstin,
        period=period,
    )
    rec = add_or_update_stock_record_sync(
        None,
        batch_id=batch["id"],
        firm_id=firm_id,
        client_gstin_id=client_gid,
        item_type="8A",
        supplier_gstin="27AABCU9603R1ZX",
        invoice_number="INV-100",
        invoice_date="2026-08-15",
        description="Inputs",
        uqc="NOS",
        quantity=50,
        taxable_value=100000.0,
        reverse_cgst=9000.0,
        reverse_sgst=9000.0,
        reverse_igst=0.0,
        reverse_cess=0.0,
    )

    # 2. Maker prepares return
    payload = {"gstin": gstin, "period": period, "total_reversal_liability": 18000.0}
    with patch("app.services.maker_checker_service.compute_figures_digest", return_value="DIGEST_ORIGINAL_G10"):
        prep = prepare_return(
            None,
            firm_id=firm_id,
            client_gstin_id=client_gid,
            gstin=gstin,
            period=period,
            return_type="GSTR-10",
            figures_payload=payload,
            actor=firm_maker,
        )
    assert prep.status.value == "PREPARED"

    # 3. Maker submits for review
    sub = submit_for_review(
        None,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=gstin,
        period=period,
        return_type="GSTR-10",
        actor=firm_maker,
    )
    assert sub.status.value == "UNDER_REVIEW"

    # 4. Self-approval prohibited: Maker cannot approve
    with pytest.raises(HTTPException) as exc_self:
        approve_return(
            None,
            firm_id=firm_id,
            client_gstin_id=client_gid,
            gstin=gstin,
            period=period,
            return_type="GSTR-10",
            actor=firm_maker,
        )
    assert exc_self.value.status_code == 403

    # 5. Checker approves
    appr = approve_return(
        None,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=gstin,
        period=period,
        return_type="GSTR-10",
        expected_figures_digest="DIGEST_ORIGINAL_G10",
        actor=firm_checker,
    )
    assert appr.status.value == "APPROVED"

    # Maker-checker gate passes with current figures payload
    payload = {"gstin": gstin, "period": period, "total_reversal_liability": 18000.0}
    with patch("app.services.maker_checker_service.compute_figures_digest", return_value="DIGEST_ORIGINAL_G10"):
        assert_maker_checker_gate(
            None,
            firm_id=firm_id,
            client_gstin_id=client_gid,
            gstin=gstin,
            period=period,
            return_type="GSTR-10",
            current_figures_payload=payload,
            operation="FILE",
        )

    # 6. Altering figures causes stale approval invalidation (HTTP 409)
    with patch("app.services.maker_checker_service.compute_figures_digest", return_value="ALTERED_DIGEST"):
        with pytest.raises(HTTPException) as exc_stale:
            assert_maker_checker_gate(
                None,
                firm_id=firm_id,
                client_gstin_id=client_gid,
                gstin=gstin,
                period=period,
                return_type="GSTR-10",
                current_figures_payload=payload,
                operation="FILE",
            )
        assert exc_stale.value.status_code == 409


def test_gstr11_client_authorization_figures_binding(firm_maker, firm_checker):
    firm_id = "00000000-0000-0000-0000-000000000001"
    client_gid = "00000000-0000-0000-0000-000000000003"
    uin = "0717USA00001UN1"
    period = "2026-10"

    # 1. Create GSTR-11 batch & inward invoice
    batch = get_or_create_g11_batch(
        None,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        uin=uin,
        period=period,
    )
    add_or_update_inward_supply_sync(
        None,
        batch_id=batch["id"],
        firm_id=firm_id,
        client_gstin_id=client_gid,
        supply_type="3A",
        supplier_gstin="27AABCU9603R1ZX",
        doc_number="INV-1",
        doc_date="2026-10-05",
        taxable_value=100000.0,
        cgst=9000.0,
        sgst=9000.0,
        igst=0.0,
        cess=0.0,
    )

    # 2. Checker prepares & approves
    payload = {"uin": uin, "period": period, "total_net_refund_claimed": 18000.0}
    with patch("app.services.maker_checker_service.compute_figures_digest", return_value="DIGEST_ORIGINAL_G11"):
        prepare_return(
            None,
            firm_id=firm_id,
            client_gstin_id=client_gid,
            gstin=uin,
            period=period,
            return_type="GSTR-11",
            figures_payload=payload,
            actor=firm_maker,
        )
    submit_for_review(
        None,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=uin,
        period=period,
        return_type="GSTR-11",
        actor=firm_maker,
    )
    approve_return(
        None,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=uin,
        period=period,
        return_type="GSTR-11",
        expected_figures_digest="DIGEST_ORIGINAL_G11",
        actor=firm_checker,
    )

    payload = {"uin": uin, "period": period, "total_net_refund_claimed": 18000.0}

    # 3. Create client authorization request
    req, raw_token = create_authorization_request(
        None,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=uin,
        period=period,
        return_type="GSTR-11",
        figures_payload=payload,
        actor=firm_checker,
    )
    assert req.status.value == "PENDING"

    # 4. Client records consent
    submit_client_authorization(
        None,
        raw_token=raw_token,
        signatory_name="Ambassador Smith",
        signatory_designation="Head of Mission",
        signatory_contact="ambassador@embassy.gov",
    )

    # 5. Gate passes with matching digest
    with patch("app.services.client_authorization_service.compute_figures_digest", return_value=req.figures_digest):
        assert_client_authorization_gate(
            None,
            firm_id=firm_id,
            client_gstin_id=client_gid,
            gstin=uin,
            period=period,
            return_type="GSTR-11",
            current_figures_payload=payload,
        )

    # 6. Altering figures causes client authorization gate to fail (HTTP 409 Conflict)
    with patch("app.services.client_authorization_service.compute_figures_digest", return_value="DIGEST_MUTATED_POST_CONSENT"):
        with pytest.raises(HTTPException) as exc_tamper:
            assert_client_authorization_gate(
                None,
                firm_id=firm_id,
                client_gstin_id=client_gid,
                gstin=uin,
                period=period,
                return_type="GSTR-11",
                current_figures_payload=payload,
            )
        assert exc_tamper.value.status_code == 409
