"""Tests for Statutory GSTR-3B Excel Export Workbook enhancements."""

import io
from datetime import date, datetime, timezone
import openpyxl
import pytest

from app.services.reconcile_export_workbook import build_excel_workbook_bytes


def test_summary_sheet_contains_statutory_3b_breakdown():
    summary = {
        "total_gstr_records": 100,
        "matched_count": 80,
        "matched_eligible_itc_amount": 125000.50,
        "rcm_count": 5,
        "rcm_itc_amount": 18000.00,
        "rcm_liability_amount": 18000.00,
        "time_barred_count": 3,
        "time_barred_itc_amount": 45000.00,
        "ineligible_itc_count": 2,
        "ineligible_itc_amount": 12000.00,
    }

    xlsx_bytes, _ = build_excel_workbook_bytes(
        run_id="run-stat-summary-1",
        firm_name="Apex Chartered Accountants",
        client_trade_name="Bharat Retail Ltd",
        period_raw="2024-04",
        summary=summary,
        matched_pairs=[],
        missed_rows=[],
        risk_rows=[],
        rule37_rows=[],
        section17_rows=[],
        review_required_rows=[],
        generated_at=datetime.now(timezone.utc),
        generated_by_name="Senior Partner",
    )

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb["Summary"]
    content = {str(row[0]): str(row[1]) for row in ws.iter_rows(values_only=True) if row and row[0]}

    assert "Statutory GSTR-3B Allocation" in content
    assert "Eligible Domestic ITC [Table 4(A)(5)]" in content
    assert "Inward RCM Eligible ITC [Table 4(A)(3)]" in content
    assert "Inward RCM Cash Liability [Table 3.1(d)]" in content
    assert "Section 16(4) Time-Barred ITC (Dead Credit)" in content
    assert "Ineligible / Blocked ITC [Table 4(D)(2)]" in content

    assert content["Eligible Domestic ITC [Table 4(A)(5)]"] in ("Rs 125,000", "Rs 1,25,000")
    assert content["Inward RCM Eligible ITC [Table 4(A)(3)]"] in ("Rs 18,000", "Rs 18,000")
    assert content["Section 16(4) Time-Barred ITC (Dead Credit)"] in ("Rs 45,000", "Rs 45,000")


def test_matched_records_sheet_has_supply_type_and_3b_table():
    regular_invoice = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "REG-001",
        "invoice_date": "2024-04-10",
        "document_type": "INVOICE",
        "amount": 5400.0,
        "match_level": "EXACT",
        "confidence_score": 100,
        "is_rcm": False,
        "itc_available": True,
        "decision_what": "Matched perfectly",
        "decision_why": "All fields match",
        "decision_next": "Claim ITC",
        "gstr2b_data": {"taxable_amount_paise": 3000000},
    }
    rcm_invoice = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "RCM-002",
        "invoice_date": "2024-04-12",
        "document_type": "INVOICE",
        "amount": 9000.0,
        "match_level": "EXACT",
        "confidence_score": 100,
        "is_rcm": True,
        "itc_available": True,
        "decision_what": "Matched RCM",
        "decision_why": "Reverse charge applies",
        "decision_next": "Pay cash and claim RCM ITC",
        "gstr2b_data": {"taxable_amount_paise": 5000000},
    }

    pairs = [
        (regular_invoice, {"is_rcm": False, "itc_available": True}),
        (rcm_invoice, {"is_rcm": True, "itc_available": True}),
    ]

    xlsx_bytes, _ = build_excel_workbook_bytes(
        run_id="run-stat-matched-1",
        firm_name="Apex CA",
        client_trade_name="Bharat Retail Ltd",
        period_raw="2024-04",
        summary={},
        matched_pairs=pairs,
        missed_rows=[],
        risk_rows=[],
        rule37_rows=[],
        section17_rows=[],
        review_required_rows=[],
        generated_at=datetime.now(timezone.utc),
        generated_by_name="Senior Partner",
    )

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb["Matched Records"]
    headers = [cell.value for cell in ws[1]]

    assert "Supply Type" in headers
    assert "3B Table" in headers

    supply_col = headers.index("Supply Type") + 1
    table_col = headers.index("3B Table") + 1

    # Row 2 is regular
    assert ws.cell(row=2, column=supply_col).value == "REGULAR"
    assert ws.cell(row=2, column=table_col).value == "Table 4(A)(5)"

    # Row 3 is RCM
    assert ws.cell(row=3, column=supply_col).value == "RCM"
    assert ws.cell(row=3, column=table_col).value == "Table 4(A)(3)"


def test_compliance_risk_and_time_barred_sheets_partitioning():
    recoverable_risk = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "RISK-REC-1",
        "invoice_date": "2024-03-01",
        "document_type": "INVOICE",
        "amount": 2000.0,
        "section_16_4_status": "CLAIM_WINDOW_OPEN",
        "decision_what": "Invoice not in GSTR-2B",
        "decision_why": "Supplier not filed yet",
        "decision_next": "Follow up with supplier",
    }
    time_barred_risk = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "RISK-TB-1",
        "invoice_date": "2022-05-15",
        "document_type": "INVOICE",
        "amount": 15000.0,
        "section_16_4_status": "ITC_TIME_BARRED",
        "statutory_deadline": "30-Nov-2023",
        "decision_what": "ITC Time-Barred under Section 16(4)",
        "decision_why": "Invoice date exceeds 30th November statutory deadline",
        "decision_next": "Do not claim in GSTR-3B Table 4(A)(5). Expense off.",
    }

    # Pass unpartitioned risk_rows to verify automatic internal partitioning
    xlsx_bytes, _ = build_excel_workbook_bytes(
        run_id="run-stat-partition-1",
        firm_name="Apex CA",
        client_trade_name="Bharat Retail Ltd",
        period_raw="2024-04",
        summary={},
        matched_pairs=[],
        missed_rows=[],
        risk_rows=[recoverable_risk, time_barred_risk],
        rule37_rows=[],
        section17_rows=[],
        review_required_rows=[],
        generated_at=datetime.now(timezone.utc),
        generated_by_name="Senior Partner",
    )

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))

    # Sheet 4: Compliance Risk should ONLY have RISK-REC-1
    ws_risk = wb["Compliance Risk"]
    risk_invoices = [str(cell.value) for cell in ws_risk["B"] if cell.value]
    assert "RISK-REC-1" in risk_invoices
    assert "RISK-TB-1" not in risk_invoices

    # Sheet 4b: Time-Barred ITC (Sec 16-4) should have RISK-TB-1
    assert "Time-Barred ITC (Sec 16-4)" in wb.sheetnames
    ws_tb = wb["Time-Barred ITC (Sec 16-4)"]
    tb_headers = [c.value for c in ws_tb[1]]
    assert "Statutory Cutoff" in tb_headers
    assert "Section 16(4) Status" in tb_headers

    tb_invoices = [str(cell.value) for cell in ws_tb["B"] if cell.value]
    assert "RISK-TB-1" in tb_invoices
    assert "RISK-REC-1" not in tb_invoices


def test_rule37_and_section175_statutory_columns():
    r37_row = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "R37-1",
        "invoice_date": "2023-09-01",
        "amount": 5000.0,
        "rule37_urgency": "HIGH",
        "rule37_flag": True,
        "decision_what": "Payment pending > 180 days",
        "decision_why": "Rule 37 180-day reversal condition",
        "decision_next": "Reverse in Table 4(B)(2)",
    }
    r37a_row = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "R37A-1",
        "invoice_date": "2023-11-01",
        "amount": 7500.0,
        "rule37a_flag": True,
        "decision_what": "Supplier non-filer under Rule 37A",
        "decision_why": "GSTR-3B not filed by supplier",
        "decision_next": "Reverse in Table 4(B)(2)",
    }
    s175_row = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "S17-1",
        "invoice_date": "2024-01-15",
        "amount": 12000.0,
        "decision_what": "Blocked credit: Motor Vehicles",
        "decision_why": "Section 17(5)(a) blocked",
        "decision_next": "Do not claim in 3B",
    }
    pos_row = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "POS-1",
        "invoice_date": "2024-02-10",
        "amount": 4000.0,
        "decision_what": "Place of Supply restriction",
        "decision_why": "Recipient state differs from POS",
        "decision_next": "Report in Table 4(D)(2)",
    }

    xlsx_bytes, _ = build_excel_workbook_bytes(
        run_id="run-stat-r37-1",
        firm_name="Apex CA",
        client_trade_name="Bharat Retail Ltd",
        period_raw="2024-04",
        summary={},
        matched_pairs=[],
        missed_rows=[],
        risk_rows=[],
        rule37_rows=[r37_row, r37a_row],
        section17_rows=[s175_row, pos_row],
        review_required_rows=[],
        generated_at=datetime.now(timezone.utc),
        generated_by_name="Senior Partner",
    )

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb["Rule 37 & Section 17-5"]
    headers = [c.value for c in ws[1]]

    assert "Statutory Provision" in headers
    assert "GSTR-3B Table" in headers

    prov_col = headers.index("Statutory Provision") + 1
    table_col = headers.index("GSTR-3B Table") + 1

    # Check each row's provision and table
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    row_map = {r[2]: r for r in rows if r and len(r) > 2}

    assert "Rule 37(1) CGST Rules (180 Days)" in row_map["R37-1"][prov_col - 1]
    assert "Table 4(B)(2)" in row_map["R37-1"][table_col - 1]

    assert "Rule 37A CGST Rules" in row_map["R37A-1"][prov_col - 1]
    assert "Table 4(B)(2)" in row_map["R37A-1"][table_col - 1]

    assert "Section 17(5)" in row_map["S17-1"][prov_col - 1]
    assert "Table 4(B)(1)" in row_map["S17-1"][table_col - 1]

    assert "Section 12(3)" in row_map["POS-1"][prov_col - 1]
    assert "Table 4(D)(2)" in row_map["POS-1"][table_col - 1]


def test_export_notes_sheet_tracks_all_sheets_including_time_barred():
    xlsx_bytes, _ = build_excel_workbook_bytes(
        run_id="run-stat-notes-1",
        firm_name="Apex CA",
        client_trade_name="Bharat Retail Ltd",
        period_raw="2024-04",
        summary={},
        matched_pairs=[],
        missed_rows=[],
        risk_rows=[],
        rule37_rows=[],
        section17_rows=[],
        review_required_rows=[],
        generated_at=datetime.now(timezone.utc),
        generated_by_name="Senior Partner",
    )

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws_notes = wb["Export Notes"]
    note_rows = list(ws_notes.iter_rows(min_row=9, values_only=True))
    sheet_names_in_notes = [r[0] for r in note_rows if r and r[0]]

    assert "Time-Barred ITC (Sec 16-4)" in sheet_names_in_notes
    assert "Matched Records" in sheet_names_in_notes
    assert "Compliance Risk" in sheet_names_in_notes
    assert "Rule 37 & 17(5)" in sheet_names_in_notes
