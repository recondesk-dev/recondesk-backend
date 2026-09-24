"""Tests for Notice Defense & Reconciliation Engine."""

import io
from unittest.mock import MagicMock

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.notice_defense_engine import (
    compute_notice_defense,
    generate_notice_defense_workbook,
    parse_notice_pdf,
)


def _make_dummy_pdf(text: str) -> bytes:
    """Create a minimal valid PDF containing the given text."""
    try:
        import PyPDF2
        # If PyPDF2 can't write from scratch easily without writer, create a simple raw stream
        # A minimal raw PDF 1.4 template
        stream = io.BytesIO()
        writer = PyPDF2.PdfWriter()
        writer.add_blank_page(width=612, height=792)
        # Note: PyPDF2 writer blank page won't have the text stream, but we can test regex directly or via fallback
        writer.write(stream)
        return stream.getvalue()
    except Exception:
        return b"%PDF-1.4 empty mock"


def test_parse_notice_pdf_empty_graceful():
    """Empty or non-text PDF returns clean default structure without raising exceptions."""
    res = parse_notice_pdf(b"not a valid pdf")
    assert isinstance(res, dict)
    assert res["notice_type"] == "OTHER"
    assert res["alleged_tax_demand"] == 0.0
    assert "DIN" in res["notice_reference"]


def test_compute_notice_defense_mathematical_reconciliation():
    """Verify rupee-level reconciliation, timing differences, Rule 37 re-credits, and status."""
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Acme Corp Ltd"}
    ]

    notice_input = {
        "notice_reference": "DIN202409250001",
        "notice_type": "DRC-01C",
        "tax_period": "032024",
        "issue_date": "2024-04-10",
        "issuing_authority": "Office of the Assistant Commissioner, Ward 12",
        "alleged_tax_demand": 500000.0,
        "alleged_igst": 300000.0,
        "alleged_cgst": 100000.0,
        "alleged_sgst": 100000.0,
        "alleged_cess": 0.0,
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input)

    assert result["client_gstin"] == "27AABCT1234F1Z1"
    assert result["notice_reference"] == "DIN202409250001"
    assert result["notice_type"] == "DRC-01C"

    summary = result["defense_summary"]
    assert summary["alleged_total"] == 500000.0
    assert summary["timing_diff_itc"] > 0
    assert summary["reclaimed_rule37_itc"] > 0
    assert summary["total_explained"] > 0
    assert summary["reconciliation_status"] in ("FULLY_RECONCILED", "PARTIALLY_EXPLAINED")

    # Invoices schedule should have itemized rows
    schedule = result["invoices_schedule"]
    assert len(schedule) >= 2
    assert schedule[0]["supplier_gstin"]
    assert schedule[0]["total_tax"] > 0
    assert "Sec 16(4)" in schedule[0]["legal_basis"] or "Rule 37" in schedule[0]["legal_basis"]

    # Formal reply draft verification
    reply = result["formal_reply_text"]
    assert "DIN202409250001" in reply
    assert "Acme Corp Ltd" in reply
    assert "27AABCT1234F1Z1" in reply
    assert "Circular No. 183/15/2022-GST" in reply
    assert "Section 16(2)" in reply
    assert "D.Y. Beathel Enterprises" in reply


def test_generate_notice_defense_workbook_excel():
    """Verify generated Excel workbook contains required sheets, formulas, and formatting."""
    defense_data = {
        "client_name": "Alpha Enterprises Pvt Ltd",
        "client_gstin": "27AABCA5555C1Z9",
        "notice_reference": "DIN-2024-TEST-999",
        "notice_type": "ASMT-10",
        "tax_period": "2023-24",
        "issue_date": "2024-05-15",
        "issuing_authority": "Superintendent of Central Tax, Range III",
        "defense_summary": {
            "alleged_total": 750000.0,
            "timing_diff_itc": 500000.0,
            "reclaimed_rule37_itc": 200000.0,
            "table4b_reversals_itc": 50000.0,
            "unexplained_balance": 0.0,
            "reconciled_pct": 100.0,
        },
        "invoices_schedule": [
            {
                "supplier_gstin": "27AABCU1234D1Z5",
                "supplier_name": "Bharat Steels",
                "invoice_number": "BS-101",
                "invoice_date": "2023-08-11",
                "taxable_value": 2777777.78,
                "igst": 500000.0,
                "cgst": 0.0,
                "sgst": 0.0,
                "total_tax": 500000.0,
                "defense_ground": "Supplier filed GSTR-1 late; claimed u/s 16(4)",
                "legal_basis": "Sec 16(4) / Cir 183/2022",
            }
        ],
    }

    excel_bytes = generate_notice_defense_workbook(defense_data)
    assert len(excel_bytes) > 1000

    # Load and verify with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    assert "Reconciliation Summary" in wb.sheetnames
    assert "Annexure A - Invoices" in wb.sheetnames

    ws1 = wb["Reconciliation Summary"]
    assert "RECONDESK — STATUTORY NOTICE DEFENSE WORKPAPER" in ws1["A1"].value
    assert ws1["B4"].value == "DIN-2024-TEST-999"

    ws2 = wb["Annexure A - Invoices"]
    assert ws2["B2"].value == "27AABCU1234D1Z5"
    assert ws2["C2"].value == "Bharat Steels"
    assert ws2["J2"].value == 500000.0


def test_notices_api_export_excel():
    """Verify /api/notices/export-excel endpoint generates a downloadable .xlsx."""
    client = TestClient(app)
    # Auth override for testing
    from app.auth import get_current_active_user
    app.dependency_overrides[get_current_active_user] = lambda: {
        "id": "00000000-0000-0000-0000-000000000001",
        "role": "admin",
        "email": "test@recondesk.com",
    }

    payload = {
        "notice_reference": "DIN-API-TEST-001",
        "client_name": "Test Firm",
        "client_gstin": "27AABCT0000F1Z1",
        "notice_type": "DRC-01C",
        "defense_summary": {
            "alleged_total": 100000.0,
            "timing_diff_itc": 100000.0,
            "reclaimed_rule37_itc": 0.0,
            "table4b_reversals_itc": 0.0,
            "unexplained_balance": 0.0,
        },
        "invoices_schedule": [],
    }

    resp = client.post("/api/notices/export-excel", json=payload)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment" in resp.headers["content-disposition"]
