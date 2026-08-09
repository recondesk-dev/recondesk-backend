"""Unit tests for Credit Notes / Debit Notes (CDNR) Module."""

from __future__ import annotations

import io
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from PyPDF2 import PdfReader

from app.models.billing import CdnCreateInput, CdnNoteType, CdnReason, InvoiceLineItemInput
from app.services.billing import cdn_service
from app.services.billing.invoice_pdf_service import build_gst_invoice_pdf


def test_cdn_creation_rejected_if_invoice_not_irp_registered():
    """Verify CDN creation is strictly rejected if original invoice is not irp_registered."""
    mock_db = MagicMock()

    # Mock client GSTIN access check
    mock_db.table("client_gstins").select().eq().limit().execute.return_value.data = [
        {"id": "client-111", "firm_owner_id": "user-123", "assigned_to": "user-123"}
    ]

    # Original invoice is finalized but NOT irp_registered
    mock_db.table("billing_invoices").select().eq().eq().limit().execute.return_value.data = [
        {
            "id": "inv-999",
            "client_gstin_id": "client-111",
            "irp_status": "not_submitted",
            "irn": None,
            "is_interstate": False,
            "company_profile_id": "cp-111",
        }
    ]

    payload = CdnCreateInput(
        client_gstin_id="client-111",
        original_invoice_id="inv-999",
        note_type=CdnNoteType.CREDIT,
        reason=CdnReason.SALES_RETURN,
        line_items=[
            InvoiceLineItemInput(
                description="Returned item",
                hsn_or_sac_code="3004",
                quantity=1.0,
                unit="NOS",
                rate_paise=100000,
                discount_percent=0.0,
                tax_rate_percent=18.0,
            )
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        cdn_service.create_credit_debit_note(mock_db, payload, user_or_id="user-123")

    assert exc_info.value.status_code == 400
    assert "Credit Notes or Debit Notes can only be issued against invoices that have been registered on IRP" in str(exc_info.value.detail)


def test_cdn_tax_calculation_matches_invoice_reversal_amount():
    """Verify CDN tax calculation correctly computes taxable, CGST, SGST, IGST sums."""
    mock_db = MagicMock()

    # Mock table routing
    def table_router(table_name):
        mock_table = MagicMock()
        if table_name == "client_gstins":
            mock_table.select().eq().limit().execute.return_value.data = [
                {"id": "client-111", "firm_owner_id": "user-123"}
            ]
        elif table_name == "billing_invoices":
            mock_table.select().eq().eq().limit().execute.return_value.data = [
                {
                    "id": "inv-999",
                    "client_gstin_id": "client-111",
                    "company_profile_id": "cp-111",
                    "customer_id": "cust-111",
                    "invoice_number": "INV/1230003",
                    "invoice_date": "2026-08-09",
                    "place_of_supply": "27",
                    "is_interstate": False,
                    "subtotal_paise": 1000000,
                    "total_tax_paise": 180000,
                    "total_paise": 1180000,
                    "status": "finalized",
                    "irp_status": "irp_registered",
                    "irn": "a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890",
                }
            ]
        elif table_name == "billing_company_profiles":
            mock_table.select().eq().limit().execute.return_value.data = [
                {"cdn_number_prefix": "CRN/", "cdn_number_next_seq": 5, "legal_name": "Sharma Ent", "gstin": "27ISBPK1456H1Z5", "state_code": "27"}
            ]
            mock_table.select().eq().eq().limit().execute.return_value.data = [
                {"id": "cp-111", "legal_name": "Sharma Ent", "gstin": "27ISBPK1456H1Z5", "state_code": "27"}
            ]
        elif table_name == "billing_customers":
            mock_table.select().eq().eq().limit().execute.return_value.data = [
                {"id": "cust-111", "name": "Ravan", "gstin": "27ISBPK1456H1ZJ", "state_code": "27"}
            ]
        elif table_name == "billing_credit_debit_notes":
            mock_table.insert().execute.return_value.data = [{"id": "cdn-555"}]
            mock_table.select().eq().eq().limit().execute.return_value.data = [
                {
                    "id": "cdn-555",
                    "client_gstin_id": "client-111",
                    "original_invoice_id": "inv-999",
                    "note_type": "credit",
                    "note_number": "CRN/0000005",
                    "note_date": "2026-08-09",
                    "reason": "1-Sales Return",
                    "subtotal_paise": 1000000,
                    "total_tax_paise": 180000,
                    "total_paise": 1180000,
                    "status": "draft",
                }
            ]
        elif table_name == "billing_cdn_line_items":
            mock_table.insert().execute.return_value.data = []
            mock_table.select().eq().execute.return_value.data = [
                {
                    "description": "Returned medicine",
                    "hsn_or_sac_code": "3004",
                    "quantity": 1.0,
                    "unit": "NOS",
                    "rate_paise": 1000000,
                    "discount_percent": 0.0,
                    "taxable_value_paise": 1000000,
                    "cgst_paise": 90000,
                    "sgst_paise": 90000,
                    "igst_paise": 0,
                    "line_total_paise": 1180000,
                }
            ]
        elif table_name == "billing_invoice_line_items":
            mock_table.select().eq().execute.return_value.data = []
        return mock_table

    mock_db.table.side_effect = table_router

    payload = CdnCreateInput(
        client_gstin_id="client-111",
        original_invoice_id="inv-999",
        note_type=CdnNoteType.CREDIT,
        reason=CdnReason.SALES_RETURN,
        line_items=[
            InvoiceLineItemInput(
                description="Returned medicine",
                hsn_or_sac_code="3004",
                quantity=1.0,
                unit="NOS",
                rate_paise=1000000,
                discount_percent=0.0,
                tax_rate_percent=18.0,
            )
        ],
    )

    cdn_detail = cdn_service.create_credit_debit_note(mock_db, payload, user_or_id="user-123")

    assert cdn_detail["note_number"] == "CRN/0000005"
    assert cdn_detail["subtotal_paise"] == 1000000
    assert cdn_detail["total_tax_paise"] == 180000
    assert cdn_detail["total_paise"] == 1180000


def test_cdn_note_numbering_series_does_not_collide_with_invoice():
    """Verify CDN uses cdn_number_prefix (CRN/) and separate sequence from invoice_number_prefix (INV/)."""
    mock_db = MagicMock()
    mock_db.table().select().eq().limit().execute.return_value.data = [
        {"cdn_number_prefix": "CRN/", "cdn_number_next_seq": 1}
    ]

    cdn_num = cdn_service._generate_next_cdn_number(mock_db, "cp-111")
    assert cdn_num.startswith("CRN/")
    assert cdn_num != "INV/1230001"
    assert cdn_num == "CRN/0000001"


def test_cdn_pdf_generation_format():
    """Verify CDN PDF generation includes CREDIT NOTE header, original invoice reference, and reason."""
    mock_cdn_detail = {
        "id": "cdn-123",
        "note_number": "CRN/0000001",
        "note_date": "2026-08-09",
        "note_type": "credit",
        "reason": "1-Sales Return",
        "reason_detail": "Defective batch returned",
        "status": "finalized",
        "irp_status": "irp_registered",
        "irn": "b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1",
        "irn_ack_number": "122345678999",
        "irn_ack_date": "2026-08-09T12:00:00Z",
        "irn_qr_code": "https://einv-apisandbox.nic.in/qr?irn=b2c3d4e5f67890a1",
        "subtotal_paise": 1000000,
        "total_tax_paise": 180000,
        "total_paise": 1180000,
        "company_profile": {
            "legal_name": "sharma enterprises",
            "gstin": "27ISBPK1456H1Z5",
            "state_code": "27",
        },
        "customer": {
            "name": "Ravan",
            "gstin": "29ISBPK1456H1ZJ",
            "state_code": "29",
        },
        "original_invoice": {
            "invoice_number": "INV/1230003",
            "invoice_date": "2026-08-09",
            "place_of_supply": "29",
            "is_interstate": True,
        },
        "line_items": [
            {
                "description": "Returned medicine batch",
                "hsn_or_sac_code": "3004",
                "quantity": 1,
                "unit": "NOS",
                "rate_paise": 1000000,
                "taxable_value_paise": 1000000,
                "tax_rate_percent": 18,
                "igst_paise": 180000,
                "line_total_paise": 1180000,
            }
        ],
    }

    pdf_bytes = build_gst_invoice_pdf(mock_cdn_detail)
    assert len(pdf_bytes) > 1000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join([page.extract_text() for page in reader.pages])

    assert "CREDIT NOTE" in text
    assert "CRN/0000001" in text
    assert "INV/1230003" in text
    assert "1-Sales Return" in text
    assert "Defective" in text
    assert "b2c3d4e5f67890a1" in text
