import pytest
import concurrent.futures
from unittest.mock import MagicMock, patch
from datetime import date
from fastapi import HTTPException

from app.models.billing import (
    CompanyProfileCreate,
    CustomerCreate,
    InvoiceCreateInput,
    InvoiceLineItemInput,
    InvoiceStatus,
    InvoiceUpdateInput,
)
from app.services.billing import invoice_service
from app.services.normalizer import NormalizationError, normalize_gstin

# Valid test GSTINs (with valid Luhn mod 36 checksums)
VALID_SELLER_GSTIN = "27ABCDE1234F1Z0"
VALID_BUYER_GSTIN = "07ABCDE1234F1Z2"
INVALID_CHECKSUM_GSTIN = "27ABCDE1234F1Z9"  # Invalid checksum digit



# -----------------------------------------------------------------------------
# 1. Tax Split Tests (Intrastate vs Interstate)
# -----------------------------------------------------------------------------
def test_tax_split_intrastate():
    line = InvoiceLineItemInput(
        description="Software Consulting",
        hsn_or_sac_code="998311",
        quantity=2.0,
        unit="HRS",
        rate_paise=100000,  # ₹1000.00
        discount_percent=10.0,  # 10% discount -> Gross = ₹2000, Disc = ₹200, Taxable = ₹1800 (180000 paise)
        tax_rate_percent=18.0,
    )
    # Intrastate (e.g. Maharashtra to Maharashtra)
    res = invoice_service.calculate_line_item_tax(line, is_interstate=False)

    assert res["taxable_value_paise"] == 180000
    assert res["cgst_rate_percent"] == 9.0
    assert res["sgst_rate_percent"] == 9.0
    assert res["igst_rate_percent"] == 0.0

    assert res["cgst_paise"] == 16200  # 9% of 180000
    assert res["sgst_paise"] == 16200  # 9% of 180000
    assert res["igst_paise"] == 0
    assert res["line_total_paise"] == 180000 + 16200 + 16200


def test_tax_split_interstate():
    line = InvoiceLineItemInput(
        description="Software Consulting",
        hsn_or_sac_code="998311",
        quantity=2.0,
        unit="HRS",
        rate_paise=100000,  # ₹1000.00
        discount_percent=10.0,
        tax_rate_percent=18.0,
    )
    # Interstate (e.g. Maharashtra to Delhi)
    res = invoice_service.calculate_line_item_tax(line, is_interstate=True)

    assert res["taxable_value_paise"] == 180000
    assert res["cgst_rate_percent"] == 0.0
    assert res["sgst_rate_percent"] == 0.0
    assert res["igst_rate_percent"] == 18.0

    assert res["cgst_paise"] == 0
    assert res["sgst_paise"] == 0
    assert res["igst_paise"] == 32400  # 18% of 180000
    assert res["line_total_paise"] == 180000 + 32400


# -----------------------------------------------------------------------------
# 2. GSTIN Validation Tests
# -----------------------------------------------------------------------------
def test_gstin_checksum_validation():
    # Valid GSTIN should pass normalization
    cleaned = normalize_gstin(VALID_SELLER_GSTIN)
    assert cleaned == VALID_SELLER_GSTIN

    # Invalid checksum should raise NormalizationError
    with pytest.raises(NormalizationError) as exc_info:
        normalize_gstin(INVALID_CHECKSUM_GSTIN)
    assert exc_info.value.reason == "invalid_checksum"

    # validate_gstin_string helper raises HTTP 400 for invalid GSTIN
    with pytest.raises(HTTPException) as http_exc:
        invoice_service.validate_gstin_string(INVALID_CHECKSUM_GSTIN, "Company GSTIN")
    assert http_exc.value.status_code == 400
    assert "Invalid Company GSTIN" in http_exc.value.detail


# -----------------------------------------------------------------------------
# 3. Finalize & Locking Edits Tests
# -----------------------------------------------------------------------------
def test_finalize_locks_edits():
    mock_db = MagicMock()

    # Existing invoice in 'finalized' status
    mock_db.table().select().eq().eq().limit().execute.return_value.data = [
        {
            "id": "inv-123",
            "client_gstin_id": "client-1",
            "company_profile_id": "prof-1",
            "customer_id": "cust-1",
            "status": "finalized",
            "invoice_number": "INV-0001",
        }
    ]

    # Attempting to update a finalized invoice must raise HTTPException 400
    with pytest.raises(HTTPException) as exc_info:
        invoice_service.update_invoice(
            mock_db,
            invoice_id="inv-123",
            client_gstin_id="client-1",
            invoice_in=InvoiceUpdateInput(notes="Updated notes"),
        )

    assert exc_info.value.status_code == 400
    assert "Cannot edit invoice with status 'finalized'" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 4. Concurrent Invoice Number Sequencing Test
# -----------------------------------------------------------------------------
def test_concurrent_invoice_number_sequencing():
    seq_counter = [1]
    mock_db = MagicMock()

    def mock_rpc(func_name, params):
        if func_name == "increment_invoice_number_seq":
            current_seq = seq_counter[0]
            seq_counter[0] += 1
            mock_result = MagicMock()
            mock_result.execute.return_value.data = [{"prefix": "INV/24-25/", "seq": current_seq}]
            return mock_result
        return MagicMock()

    mock_db.rpc.side_effect = mock_rpc

    # Simulate 10 concurrent requests to generate sequence
    generated_numbers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(invoice_service._atomic_get_next_invoice_number, mock_db, "prof-123")
            for _ in range(10)
        ]
        for f in concurrent.futures.as_completed(futures):
            generated_numbers.append(f.result())

    # All generated invoice numbers must be unique and correctly sequenced
    assert len(generated_numbers) == 10
    assert len(set(generated_numbers)) == 10
    assert "INV/24-25/0001" in generated_numbers
    assert "INV/24-25/0010" in generated_numbers
