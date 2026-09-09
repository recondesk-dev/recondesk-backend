"""Unit tests for GST-Compliant Tax Invoice PDF Generation."""

from __future__ import annotations

import io
import pytest
from PyPDF2 import PdfReader

from app.services.billing.invoice_pdf_service import build_gst_invoice_pdf


@pytest.fixture
def mock_invoice_detail_unsubmitted():
    return {
        "id": "inv-1111-2222",
        "invoice_number": "INV/1230003",
        "invoice_date": "2026-08-09",
        "due_date": "2026-08-23",
        "status": "finalized",
        "irp_status": "unsubmitted",
        "irn": None,
        "irn_ack_number": None,
        "irn_ack_date": None,
        "irn_qr_code": None,
        "irp_environment": None,
        "place_of_supply": "29",
        "subtotal_paise": 1000000,
        "total_tax_paise": 180000,
        "total_paise": 1180000,
        "notes": "Payment due within 15 days.",
        "company_profile": {
            "legal_name": "sharma",
            "trade_name": "sharma enterprises",
            "gstin": "27ISBPK1456H1Z5",
            "pan": "ISBPK1456H",
            "address_line1": "Satyaraj City, Flat B3",
            "city": "Pune",
            "state_code": "27",
            "pincode": "411028",
            "bank_name": "HDFC Bank",
            "bank_account_number": "50100234567890",
            "bank_ifsc": "HDFC0001234",
        },
        "customer": {
            "name": "Ravan",
            "gstin": "29ISBPK1456H1ZJ",
            "is_b2b": True,
            "address_line1": "123 Brigade Road",
            "city": "Bengaluru",
            "state_code": "29",
            "pincode": "560001",
        },
        "line_items": [
            {
                "description": "medicine",
                "hsn_or_sac_code": "3004",
                "quantity": 1,
                "unit": "NOS",
                "rate_paise": 1000000,
                "discount_percent": 0,
                "taxable_value_paise": 1000000,
                "tax_rate_percent": 18,
                "cgst_paise": 0,
                "sgst_paise": 0,
                "igst_paise": 180000,
                "cess_paise": 0,
                "line_total_paise": 1180000,
            }
        ],
    }


@pytest.fixture
def mock_invoice_detail_registered(mock_invoice_detail_unsubmitted):
    detail = dict(mock_invoice_detail_unsubmitted)
    detail["irp_status"] = "irp_registered"
    detail["irn"] = "a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890"
    detail["irn_ack_number"] = "122345678901"
    detail["irn_ack_date"] = "2026-08-09T11:00:00Z"
    detail["irn_qr_code"] = "https://einv-apisandbox.nic.in/qr?irn=a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890"
    detail["irp_environment"] = "TEST/SANDBOX"
    return detail


def test_unsubmitted_invoice_pdf_contains_warning_and_no_irn(mock_invoice_detail_unsubmitted):
    pdf_bytes = build_gst_invoice_pdf(mock_invoice_detail_unsubmitted)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
    text = "".join([page.extract_text() for page in reader.pages])

    assert "NOT YET SUBMITTED TO IRP" in text
    assert "NOT A VALID E-INVOICE" in text
    assert "INV/1230003" in text
    assert "sharma" in text
    assert "Ravan" in text
    assert "Rupees Eleven Thousand" in text
    assert "Eight Hundred Only" in text
    assert "a1b2c3d4e5f67890" not in text


def test_registered_invoice_pdf_contains_irn_ack_and_qr_data(mock_invoice_detail_registered):
    pdf_bytes = build_gst_invoice_pdf(mock_invoice_detail_registered)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
    text = "".join([page.extract_text() for page in reader.pages])

    assert "NOT YET SUBMITTED TO IRP" not in text
    assert "E-INVOICE IRP ACKNOWLEDGEMENT & IRN" in text
    assert "122345678901" in text
    assert "a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890" in text
    assert "TEST/SANDBOX" in text
    assert "Rupees Eleven Thousand" in text
    assert "Eight Hundred Only" in text
