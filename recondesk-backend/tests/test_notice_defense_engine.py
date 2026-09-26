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


def test_notice_defense_oversized_alleged_demand_isolates_residual():
    """When the department's alleged demand exceeds all explained items, cleanly isolate DRC-03 residual."""
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Acme Corp Ltd"}
    ]

    # Large demand of 2,000,000 INR
    notice_input = {
        "notice_reference": "DIN-OVERSIZED-001",
        "notice_type": "ASMT-10",
        "tax_period": "032024",
        "alleged_tax_demand": 2000000.0,
        "alleged_igst": 2000000.0,
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input)
    summary = result["defense_summary"]

    assert summary["alleged_total"] == 2000000.0
    assert summary["total_explained"] < summary["alleged_total"]
    assert summary["unexplained_balance"] > 0.0
    assert summary["unexplained_balance"] == round(summary["alleged_total"] - summary["total_explained"], 2)
    assert summary["reconciliation_status"] == "PARTIALLY_EXPLAINED"
    # Ensure formal reply explicitly isolates the residual for voluntary DRC-03
    assert "BALANCE UNEXPLAINED" in result["formal_reply_text"]
    assert "DRC-03" in result["formal_reply_text"]


def test_notice_defense_zero_or_negative_demand_safety():
    """Verify engine handles 0.0 demand gracefully without DivisionByZero errors."""
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Zero Demand Client"}
    ]

    notice_input = {
        "notice_reference": "DIN-ZERO-001",
        "notice_type": "DRC-01C",
        "tax_period": "032024",
        "alleged_tax_demand": 0.0,
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input)
    summary = result["defense_summary"]

    assert summary["alleged_total"] == 0.0
    assert summary["reconciled_pct"] == 100.0
    assert summary["unexplained_balance"] == 0.0
    assert summary["reconciliation_status"] == "FULLY_RECONCILED"


def test_notice_defense_drc01b_form_support():
    """Verify DRC-01B outward liability mismatch notice behavior."""
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Sales Corp"}
    ]

    notice_input = {
        "notice_reference": "DIN-DRC01B-001",
        "notice_type": "DRC-01B",
        "tax_period": "032024",
        "alleged_tax_demand": 150000.0,
        "discrepancy_category": "OUTWARD_LIABILITY_1_VS_3B",
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input)
    assert result["notice_type"] == "DRC-01B"
    assert "DRC-01B" in result["formal_reply_text"]
    assert "DIN-DRC01B-001" in result["formal_reply_text"]


def test_notice_defense_unlinked_run_fallback():
    """When run_id is None, engine must generate valid representative statutory defense."""
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Unlinked Client"}
    ]

    notice_input = {
        "notice_reference": "DIN-UNLINKED-001",
        "notice_type": "DRC-01C",
        "tax_period": "092023",
        "alleged_tax_demand": 300000.0,
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input, run_id=None)
    assert result["reconciliation_run_id"] is None
    assert len(result["invoices_schedule"]) >= 2
    assert result["defense_summary"]["total_explained"] > 0
    assert "DIN-UNLINKED-001" in result["formal_reply_text"]


def test_find_matching_reconciliation_runs_scoring():
    """Verify period normalization sorts exact period match to top."""
    from app.services.notice_defense_engine import find_matching_reconciliation_runs

    mock_sb = MagicMock()
    mock_sb.table().select().eq().order().execute.return_value.data = [
        {"id": "run-older", "period": "012024", "status": "COMPLETED"},
        {"id": "run-target", "period": "032024", "status": "COMPLETED"},
        {"id": "run-other", "period": "022024", "status": "QUEUED"},
    ]

    runs = find_matching_reconciliation_runs(mock_sb, "client-1", tax_period="2024-03")
    assert len(runs) == 3
    # Target period (032024 vs 2024-03) must be ranked first
    assert runs[0]["id"] == "run-target"


def test_notice_defense_zero_hallucination_on_empty_run(monkeypatch):
    """When a linked run has no matched invoices, strictly output 0 invoices and unverified status."""
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Test Client"}
    ]

    import app.services.reconciliation_outcomes as ro
    monkeypatch.setattr(ro, "load_payload", lambda sb, run_id: {"engine": {"matched": []}})

    notice_input = {
        "notice_reference": "DIN-EMPTY-001",
        "notice_type": "DRC-01C",
        "tax_period": "092024",
        "alleged_tax_demand": 200000.0,
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input, run_id="run-empty")
    assert result["reconciliation_run_id"] == "run-empty"
    # Must NOT hallucinate dummy rows when run_id is passed
    assert len(result["invoices_schedule"]) == 0
    assert result["defense_summary"]["unexplained_balance"] == 200000.0
    assert result["defense_summary"]["reconciliation_status"] == "DEFENSE_UNVERIFIED_NO_EVIDENCE"


def test_notice_defense_anomalous_run_blocks_defense(monkeypatch):
    """When a run has <15% match rate, it must flag CANNOT_DEFEND_ANOMALOUS_RUN."""
    mock_sb = MagicMock()
    # 1st call for client, 2nd call for run_meta
    client_mock = MagicMock()
    client_mock.data = [{"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Test Client"}]
    run_mock = MagicMock()
    run_mock.data = [{"id": "run-anom", "period": "092024", "total_records": 100}]

    mock_sb.table().select().eq().limit().execute.side_effect = [client_mock, run_mock]

    # Only 2 matches out of 100 records (2% match rate)
    import app.services.reconciliation_outcomes as ro
    dummy_matches = [
        {"supplier_gstin": "27A", "invoice_number": "1", "total_tax_paise": 100000, "is_late_filing": True}
    ]
    monkeypatch.setattr(
        ro,
        "load_payload",
        lambda sb, run_id: {
            "engine": {
                "matched": dummy_matches,
                "missing_in_gstr": [{}] * 50,
                "missing_in_pr": [{}] * 49,
            }
        },
    )

    notice_input = {
        "notice_reference": "DIN-ANOM-001",
        "notice_type": "DRC-01C",
        "tax_period": "092024",
        "alleged_tax_demand": 100000.0,
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input, run_id="run-anom")
    assert result["is_anomalous"] is True
    assert result["run_quality_status"] == "ANOMALOUS_LOW_MATCH_RATE"
    assert result["defense_summary"]["reconciliation_status"] == "CANNOT_DEFEND_ANOMALOUS_RUN"
    assert any("abnormally low" in w for w in result["run_integrity_warnings"])


def test_notice_defense_period_mismatch_flags_warning():
    """When notice period differs from run period, flag DEFENSE_PERIOD_MISMATCH."""
    mock_sb = MagicMock()
    client_mock = MagicMock()
    client_mock.data = [{"id": "client-1", "gstin": "27AABCT1234F1Z1", "trade_name": "Test Client"}]
    run_mock = MagicMock()
    # Run is for July 2024, but notice is for Sept 2024
    run_mock.data = [{"id": "run-july", "period": "072024", "total_records": 50}]

    mock_sb.table().select().eq().limit().execute.side_effect = [client_mock, run_mock]

    notice_input = {
        "notice_reference": "DIN-PERIOD-001",
        "notice_type": "DRC-01C",
        "tax_period": "092024",
        "alleged_tax_demand": 50000.0,
    }

    result = compute_notice_defense(mock_sb, "client-1", notice_input, run_id="run-july")
    assert result["run_quality_status"] == "PERIOD_MISMATCH"
    assert result["defense_summary"]["reconciliation_status"] == "DEFENSE_PERIOD_MISMATCH"
    assert any("does not match reconciliation run period" in w for w in result["run_integrity_warnings"])
