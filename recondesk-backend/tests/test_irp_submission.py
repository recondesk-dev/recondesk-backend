"""Unit tests for E-Invoice IRP Submission, Pre-Validation, Timeout Recovery & Cancellation."""

import datetime
from datetime import timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.services.billing import irp_submission_service
from app.services.sandbox_einvoice_client import EinvoiceDownError, EinvoiceClientError


# -----------------------------------------------------------------------------
# Test Fixtures & Sample Data
# -----------------------------------------------------------------------------
@pytest.fixture
def valid_company():
    return {
        "id": "comp-123",
        "client_gstin_id": "client-456",
        "legal_name": "ACME Enterprises Pvt Ltd",
        "trade_name": "ACME Solutions",
        "address_line1": "123 Business Park",
        "city": "Mumbai",
        "state": "Maharashtra",
        "state_code": "27",
        "pincode": "400001",
        "gstin": "27ISKPK1273H1ZF",
    }


@pytest.fixture
def valid_customer():
    return {
        "id": "cust-789",
        "client_gstin_id": "client-456",
        "name": "Global Tech Services Ltd",
        "gstin": "27ISKPK1273H1ZF",
        "address_line1": "456 Tech Street",
        "city": "Pune",
        "state": "Maharashtra",
        "state_code": "27",
        "pincode": "411001",
        "is_b2b": True,
    }


@pytest.fixture
def valid_invoice():
    return {
        "id": "inv-001",
        "client_gstin_id": "client-456",
        "company_profile_id": "comp-123",
        "customer_id": "cust-789",
        "invoice_number": "INV-2026-0001",
        "invoice_date": "2026-08-09",
        "place_of_supply": "27",
        "is_interstate": False,
        "subtotal_paise": 100000,
        "total_tax_paise": 18000,
        "total_paise": 118000,
        "status": "finalized",
        "irp_status": "not_submitted",
        "irp_environment": "test",
    }


@pytest.fixture
def valid_line_items():
    return [
        {
            "id": "item-line-1",
            "invoice_id": "inv-001",
            "description": "IT Consulting Services",
            "hsn_or_sac_code": "998311",
            "quantity": 1.0,
            "unit": "HRS",
            "rate_paise": 100000,
            "discount_percent": 0.0,
            "taxable_value_paise": 100000,
            "cgst_rate_percent": 9.0,
            "cgst_paise": 9000,
            "sgst_rate_percent": 9.0,
            "sgst_paise": 9000,
            "igst_rate_percent": 0.0,
            "igst_paise": 0,
            "cess_paise": 0,
            "line_total_paise": 118000,
        }
    ]


# -----------------------------------------------------------------------------
# 1. Pre-Submission Local Validation Tests
# -----------------------------------------------------------------------------
def test_pre_submission_validation_passes(valid_invoice, valid_company, valid_customer, valid_line_items):
    errors = irp_submission_service.validate_invoice_for_irp(
        valid_invoice, valid_company, valid_customer, valid_line_items
    )
    assert errors == []


def test_pre_submission_validation_rejects_invalid_gstin_checksum(
    valid_invoice, valid_company, valid_customer, valid_line_items
):
    bad_company = dict(valid_company)
    bad_company["gstin"] = "27AAPCB1308R1ZT"  # Invalid checksum

    errors = irp_submission_service.validate_invoice_for_irp(
        valid_invoice, bad_company, valid_customer, valid_line_items
    )
    assert any("Invalid Seller GSTIN" in e and "invalid_checksum" in e for e in errors)


def test_pre_submission_validation_rejects_inconsistent_tax_sums(
    valid_invoice, valid_company, valid_customer, valid_line_items
):
    bad_items = [
        dict(
            valid_line_items[0],
            taxable_value_paise=100000,
            cgst_paise=9000,
            sgst_paise=9000,
            line_total_paise=150000,  # 100000 + 18000 != 150000
        )
    ]
    errors = irp_submission_service.validate_invoice_for_irp(
        valid_invoice, valid_company, valid_customer, bad_items
    )
    assert any("Internal tax calculation mismatch" in e for e in errors)


def test_pre_submission_validation_rejects_invalid_uqc_unit(
    valid_invoice, valid_company, valid_customer, valid_line_items
):
    bad_items = [dict(valid_line_items[0], unit="INVALID_UQC_CODE")]
    errors = irp_submission_service.validate_invoice_for_irp(
        valid_invoice, valid_company, valid_customer, bad_items
    )
    assert any("Unit Quantity Code (UQC) 'INVALID_UQC_CODE' is invalid" in e for e in errors)


def test_pre_submission_validation_catches_missing_and_invalid_fields(
    valid_invoice, valid_company, valid_customer, valid_line_items
):
    invalid_inv = dict(valid_invoice)
    invalid_inv["status"] = "draft"  # Not finalized
    invalid_inv["total_paise"] = 99999  # Mismatch with header

    invalid_comp = dict(valid_company)
    invalid_comp["pincode"] = "123"  # Invalid pincode

    invalid_cust = dict(valid_customer)
    invalid_cust["gstin"] = ""  # Missing B2B GSTIN

    invalid_items = [
        dict(valid_line_items[0], hsn_or_sac_code="12")  # HSN too short (<4 digits)
    ]

    errors = irp_submission_service.validate_invoice_for_irp(
        invalid_inv, invalid_comp, invalid_cust, invalid_items
    )

    assert any("must be in 'finalized' status" in e for e in errors)
    assert any("Pincode must be a 6-digit number" in e for e in errors)
    assert any("Buyer GSTIN is required for B2B" in e for e in errors)
    assert any("HSN/SAC Code must be at least 4 digits" in e for e in errors)
    assert any("Invoice Total Amount mismatch" in e for e in errors)


# -----------------------------------------------------------------------------
# 2. IRP Payload Formatting Tests (Govt Schema V1.03)
# -----------------------------------------------------------------------------
def test_build_irp_payload_format(valid_invoice, valid_company, valid_customer, valid_line_items):
    payload = irp_submission_service.build_irp_payload(
        valid_invoice, valid_company, valid_customer, valid_line_items
    )

    assert payload["Version"] == "1.03"
    assert payload["TranDtls"]["SupTyp"] == "B2B"
    assert payload["DocDtls"]["No"] == "INV-2026-0001"
    assert payload["DocDtls"]["Dt"] == "09/08/2026"

    assert payload["SellerDtls"]["Gstin"] == "27ISKPK1273H1ZF"
    assert payload["SellerDtls"]["Pin"] == 400001

    assert payload["BuyerDtls"]["Gstin"] == "27ISKPK1273H1ZF"
    assert payload["BuyerDtls"]["Pos"] == "27"

    assert len(payload["ItemList"]) == 1
    line1 = payload["ItemList"][0]
    assert line1["HsnCd"] == "998311"
    assert line1["IsServc"] == "Y"
    assert line1["UnitPrice"] == 1000.0
    assert line1["AssVal"] == 1000.0
    assert line1["CgstAmt"] == 90.0
    assert line1["SgstAmt"] == 90.0
    assert line1["TotItemVal"] == 1180.0

    assert payload["ValDtls"]["AssVal"] == 1000.0
    assert payload["ValDtls"]["TotInvVal"] == 1180.0


# -----------------------------------------------------------------------------
# 3. Timeout Recovery Check-Before-Resubmit Tests
# -----------------------------------------------------------------------------
@patch("app.services.billing.irp_submission_service._assert_access")
@patch("app.services.billing.irp_submission_service.get_invoice_detail")
@patch("app.services.billing.irp_submission_service.get_client_credentials")
@patch("app.services.billing.irp_submission_service.get_valid_session_token")
@patch("app.services.billing.irp_submission_service.einvoice_client")
@patch("app.services.billing.irp_submission_service.log_submission_attempt")
def test_timeout_handling_recovers_generated_irn(
    mock_log, mock_client, mock_token, mock_creds, mock_get_inv, mock_assert_access, valid_invoice, valid_company, valid_customer, valid_line_items
):
    mock_db = MagicMock()
    full_inv = dict(valid_invoice)
    full_inv["company_profile"] = valid_company
    full_inv["customer"] = valid_customer
    full_inv["line_items"] = valid_line_items
    mock_get_inv.return_value = full_inv

    mock_creds.return_value = {"id": "cred-1", "einvoice_username": "user", "einvoice_password": "enc"}
    mock_token.return_value = "session_token_123"

    # Step 1: generate_einvoice times out
    mock_client.generate_einvoice.side_effect = EinvoiceDownError("IRP portal timed out")

    # Step 2: get_einvoice_by_doc finds active IRN on IRP!
    mock_client.get_einvoice_by_doc.return_value = {
        "irn": "RECOVERED_IRN_64_HEX_HASH_STRING_1234567890ABCDEF1234567890ABCDEF",
        "ack_no": "122410000999",
        "ack_date": "2026-08-09 09:30:00",
        "signed_qr_code": "BASE64_QR_CODE_DATA",
    }

    res = irp_submission_service.submit_to_irp(
        db=mock_db,
        invoice_id="inv-001",
        client_gstin_id="client-456",
        user_id="user-1",
    )

    # Verifies get_einvoice_by_doc was called for recovery
    mock_client.get_einvoice_by_doc.assert_called_once_with(
        session_token="session_token_123",
        gstin="27ISKPK1273H1ZF",
        doc_number="INV-2026-0001",
        doc_date="2026-08-09",
        doc_type="INV",
    )

    # Verifies audit log recorded timeout_recovered
    mock_log.assert_called_once()
    assert mock_log.call_args[1]["response_status"] == "timeout_recovered"

    # Verifies DB was updated with recovered IRN
    mock_db.table("billing_invoices").update.assert_called()


# -----------------------------------------------------------------------------
# 4. 24-Hour Cancel Window Enforcement Tests
# -----------------------------------------------------------------------------
@patch("app.services.billing.irp_submission_service._assert_access")
@patch("app.services.billing.irp_submission_service.get_invoice_detail")
@patch("app.services.billing.irp_submission_service.get_client_credentials")
@patch("app.services.billing.irp_submission_service.get_valid_session_token")
@patch("app.services.billing.irp_submission_service.einvoice_client")
def test_cancel_irn_within_24h_window_succeeds(
    mock_client, mock_token, mock_creds, mock_get_inv, mock_assert_access, valid_invoice, valid_company
):
    mock_db = MagicMock()
    now_utc = datetime.datetime.now(timezone.utc)

    # Generated 2 hours ago (within 24h window) -> Allowed
    recent_ack = (now_utc - datetime.timedelta(hours=2)).isoformat()
    inv_recent = dict(valid_invoice)
    inv_recent["irp_status"] = "irp_registered"
    inv_recent["irn"] = "SAMPLE_IRN_HASH"
    inv_recent["irn_ack_date"] = recent_ack
    inv_recent["company_profile"] = valid_company
    mock_get_inv.return_value = inv_recent

    mock_creds.return_value = {"id": "cred-1"}
    mock_token.return_value = "token"
    mock_client.cancel_einvoice.return_value = {"status": "CANCELLED"}

    res = irp_submission_service.cancel_irn(
        db=mock_db,
        invoice_id="inv-001",
        client_gstin_id="client-456",
        reason_code="2",
        remarks="Data entry error",
        user_id="user-1",
    )
    mock_client.cancel_einvoice.assert_called_once()


@patch("app.services.billing.irp_submission_service._assert_access")
@patch("app.services.billing.irp_submission_service.get_invoice_detail")
@patch("app.services.billing.irp_submission_service.get_client_credentials")
@patch("app.services.billing.irp_submission_service.get_valid_session_token")
@patch("app.services.billing.irp_submission_service.einvoice_client")
def test_cancel_irn_outside_24h_window_rejected(
    mock_client, mock_token, mock_creds, mock_get_inv, mock_assert_access, valid_invoice, valid_company
):
    mock_db = MagicMock()
    now_utc = datetime.datetime.now(timezone.utc)

    # Generated 26 hours ago (outside 24h window) -> Blocked
    old_ack = (now_utc - datetime.timedelta(hours=26)).isoformat()
    inv_old = dict(valid_invoice)
    inv_old["irp_status"] = "irp_registered"
    inv_old["irn"] = "SAMPLE_IRN_HASH"
    inv_old["irn_ack_date"] = old_ack
    inv_old["company_profile"] = valid_company
    mock_get_inv.return_value = inv_old

    with pytest.raises(HTTPException) as exc_info:
        irp_submission_service.cancel_irn(
            db=mock_db,
            invoice_id="inv-001",
            client_gstin_id="client-456",
            reason_code="2",
            remarks="Late cancellation",
            user_id="user-1",
        )
    assert exc_info.value.status_code == 400
    assert "only allowed within 24 hours" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 5. Submission Log Audit Trail Test
# -----------------------------------------------------------------------------
def test_submission_log_records_every_attempt():
    mock_db = MagicMock()
    irp_submission_service.log_submission_attempt(
        db=mock_db,
        invoice_id="inv-001",
        client_gstin_id="client-456",
        environment="test",
        request_payload={"DocDtls": {"No": "INV-001"}},
        response_status="success",
        response_body={"irn": "SAMPLE_IRN"},
    )
    mock_db.table.assert_called_with("billing_irp_submission_log")
    mock_db.table().insert.assert_called_once()
