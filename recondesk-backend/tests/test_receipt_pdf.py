"""Unit tests for ReconDesk Subscription Tax Invoice PDF Generation."""

from __future__ import annotations

import io
from PyPDF2 import PdfReader
import pytest

from app.services.receipt_pdf import build_tax_invoice_pdf, invoice_filename_and_number


def test_intra_state_b2b_tax_invoice_generation():
    """Verify Maharashtra (27) to Maharashtra (27) generates CGST 9% + SGST 9%."""
    payment = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "plan": "firm",
        "billing_cycle": "yearly",
        "gstin_limit": 75,
        "base_amount_paise": 799900,
        "gst_paise": 143982,
        "total_amount_paise": 943882,
        "created_at": "2026-09-23T10:00:00Z",
    }
    bill_to = {
        "firm_name": "Kadam & Associates, Chartered Accountants",
        "firm_city": "Pune",
        "firm_gstin": "27AABCU9603R1ZM",
    }

    fname, inv_no = invoice_filename_and_number(payment)
    assert fname.startswith("ReconDesk-RD-2026-")
    assert inv_no.startswith("RD-2026-")

    pdf_bytes = build_tax_invoice_pdf(payment, bill_to)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    text = "".join([page.extract_text() for page in reader.pages])

    assert "TAX INVOICE" in text
    assert "Kadam & Associates" in text
    assert "27AABCU9603R1ZM" in text
    assert "998314" in text
    assert "Firm Plan — Annual Subscription" in text
    assert "Central Tax (CGST)" in text
    assert "State Tax (SGST)" in text
    assert "Section 31" in text


def test_inter_state_b2b_tax_invoice_generation():
    """Verify Maharashtra (27) to Gujarat (24) generates IGST 18%."""
    payment = {
        "id": "660e8400-e29b-41d4-a716-446655440000",
        "plan": "solo",
        "billing_cycle": "yearly",
        "gstin_limit": 25,
        "base_amount_paise": 499900,
        "gst_paise": 89982,
        "total_amount_paise": 589882,
        "created_at": "2026-09-23T10:00:00Z",
    }
    bill_to = {
        "firm_name": "Patel & Co Tax Consultants",
        "firm_city": "Ahmedabad",
        "firm_gstin": "24AAACR5678Q1Z3",
    }

    pdf_bytes = build_tax_invoice_pdf(payment, bill_to)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join([page.extract_text() for page in reader.pages])

    assert "TAX INVOICE" in text
    assert "Patel & Co Tax Consultants" in text
    assert "24AAACR5678Q1Z3" in text
    assert "Integrated Tax (IGST)" in text
    assert "Inter-State (IGST)" in text
    assert "Gujarat" in text
    assert "Solo Plan — Annual Subscription" in text


def test_unregistered_urp_tax_invoice_generation():
    """Verify unregistered buyer generates clean invoice with URP notice."""
    payment = {
        "id": "770e8400-e29b-41d4-a716-446655440000",
        "plan": "solo",
        "billing_cycle": "monthly",
        "gstin_limit": 25,
        "base_amount_paise": 79900,
        "gst_paise": 14382,
        "total_amount_paise": 94282,
        "created_at": "2026-09-23T10:00:00Z",
    }
    bill_to = {
        "firm_name": "Sharma Tax Services",
        "firm_city": "Mumbai",
        "firm_gstin": "",
    }

    pdf_bytes = build_tax_invoice_pdf(payment, bill_to)
    assert isinstance(pdf_bytes, bytes)

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join([page.extract_text() for page in reader.pages])

    assert "URP (Unregistered Person)" in text
    assert "Solo Plan — Monthly Subscription" in text
