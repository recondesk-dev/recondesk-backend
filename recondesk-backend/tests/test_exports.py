"""
test_exports.py
Scenario: Excel and PDF export correctness.
Verifies bytes are produced, sheets exist, and key data appears correctly.
Run: PYTHONPATH=. pytest tests/test_exports.py -v
"""
import pytest
from datetime import datetime, date
from io import BytesIO


# ── shared sample data ────────────────────────────────────────────────────────

FIRM_NAME = "Kadam & Associates"
CLIENT_NAME = "Test Client Pvt Ltd"
PERIOD_RAW = "2024-04"
RUN_ID = "test-run-001"
GENERATED_AT = datetime(2024, 5, 1, 10, 0, 0)

SUMMARY = {
    "total_gstr_records": 10,
    "matched_count": 7,
    "match_rate_percent": 70.0,
    "missed_itc_count": 2,
    "missed_itc_total_amount": 50000,
    "wrongful_risk_count": 1,
    "wrongful_risk_total_amount": 18000,
}

MATCHED_PAIRS = [
    (
        {
            "supplier_gstin": "27ABCDE1234F1Z0",
            "invoice_number": "INV001",
            "invoice_date": date(2024, 4, 1),
            "taxable_amount_paise": 1000000,
            "igst_paise": 0,
            "cgst_paise": 90000,
            "sgst_paise": 90000,
            "match_level": 1,
            "decision_what": "Exact match found",
            "decision_why": "All fields match",
            "decision_next": "No action required",
        },
        {
            "supplier_gstin": "27ABCDE1234F1Z0",
            "invoice_number": "INV001",
            "invoice_date": date(2024, 4, 1),
            "taxable_amount_paise": 1000000,
        },
    )
]

MISSED_ROWS = [
    {
        "supplier_gstin": "27XYZDE1234F1Z0",
        "invoice_number": "INV999",
        "invoice_date": date(2024, 4, 5),
        "taxable_amount_paise": 500000,
        "igst_paise": 90000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "decision_what": "Invoice in GSTR-2B not in PR",
        "decision_next": "Add to purchase register",
    }
]

RISK_ROWS = [
    {
        "supplier_gstin": "27PQRDE1234F1Z0",
        "invoice_number": "INV888",
        "invoice_date": date(2024, 4, 10),
        "taxable_amount_paise": 200000,
        "igst_paise": 36000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "decision_what": "Supplier has not filed GSTR-1",
        "decision_next": "Do not claim ITC",
    }
]

RULE37_ROWS = [
    {
        "supplier_gstin": "27ABCDE1234F1Z0",
        "invoice_number": "INV100",
        "invoice_date": date(2023, 10, 1),
        "days_remaining": -5,
        "itc_at_risk_paise": 18000,
        "deadline": "31-Mar-2024",
        "decision_what": "ITC reversal mandatory",
        "decision_next": "Reverse in next GSTR-3B",
    }
]

SECTION17_ROWS = [
    {
        "supplier_gstin": "27ABCDE1234F1Z0",
        "invoice_number": "INV200",
        "hsn_code": "8703",
        "category": "Motor Vehicles",
        "taxable_amount_paise": 500000,
        "decision_what": "Blocked credit",
        "decision_next": "Verify before claiming",
    }
]


# ── Excel tests ───────────────────────────────────────────────────────────────

class TestExcelExport:

    def _build(self, **overrides):
        from app.services.reconcile_export_workbook import build_excel_workbook_bytes
        kwargs = dict(
            run_id=RUN_ID,
            firm_name=FIRM_NAME,
            client_trade_name=CLIENT_NAME,
            period_raw=PERIOD_RAW,
            summary=SUMMARY,
            matched_pairs=MATCHED_PAIRS,
            missed_rows=MISSED_ROWS,
            risk_rows=RISK_ROWS,
            rule37_rows=overrides.get("rule37_rows", RULE37_ROWS),
            section17_rows=overrides.get("section17_rows", SECTION17_ROWS),
            review_required_rows=overrides.get("review_required_rows", []),
            generated_at=overrides.get("generated_at", datetime(2024, 5, 1, 10, 0)),
            generated_by_name="Omkar Kadam",
        )
        kwargs.update(overrides)
        return build_excel_workbook_bytes(**kwargs)

    def test_returns_bytes_and_filename(self):
        """Must return (bytes, str) — not crash, not empty."""
        result = self._build()
        assert isinstance(result, tuple) and len(result) == 2, (
            "build_excel_workbook_bytes must return (bytes, filename) tuple."
        )
        xlsx_bytes, filename = result
        assert isinstance(xlsx_bytes, bytes) and len(xlsx_bytes) > 0, (
            "Excel bytes must not be empty."
        )
        assert isinstance(filename, str) and filename.endswith(".xlsx"), (
            f"Filename must end with .xlsx. Got: '{filename}'"
        )

    def test_output_is_valid_xlsx(self):
        """Bytes must be openable as a real xlsx workbook."""
        from openpyxl import load_workbook
        xlsx_bytes, _ = self._build()
        wb = load_workbook(BytesIO(xlsx_bytes))
        assert wb is not None, "Output must be a valid xlsx workbook."

    def test_summary_sheet_exists(self):
        """Sheet named 'Summary' must exist."""
        from openpyxl import load_workbook
        xlsx_bytes, _ = self._build()
        wb = load_workbook(BytesIO(xlsx_bytes))
        assert "Summary" in wb.sheetnames, (
            f"Summary sheet must exist. Got sheets: {wb.sheetnames}"
        )

    def test_has_at_least_4_sheets(self):
        """Must have at least 4 sheets — Summary, Matched, Missed, Risk."""
        from openpyxl import load_workbook
        xlsx_bytes, _ = self._build()
        wb = load_workbook(BytesIO(xlsx_bytes))
        assert len(wb.sheetnames) >= 4, (
            f"Must have at least 4 sheets. Got: {wb.sheetnames}"
        )

    def test_summary_sheet_contains_firm_name(self):
        """Firm name must appear somewhere in the Summary sheet."""
        from openpyxl import load_workbook
        xlsx_bytes, _ = self._build()
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Summary"]
        all_values = [str(cell.value or "") for row in ws.iter_rows() for cell in row]
        assert any(FIRM_NAME in v for v in all_values), (
            f"Firm name '{FIRM_NAME}' must appear in Summary sheet."
        )

    def test_summary_sheet_contains_client_name(self):
        """Client name must appear in Summary sheet."""
        from openpyxl import load_workbook
        xlsx_bytes, _ = self._build()
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Summary"]
        all_values = [str(cell.value or "") for row in ws.iter_rows() for cell in row]
        assert any(CLIENT_NAME in v for v in all_values), (
            f"Client name '{CLIENT_NAME}' must appear in Summary sheet."
        )

    def test_empty_matched_pairs_does_not_crash(self):
        """Empty matched pairs must not crash the export."""
        result = self._build(matched_pairs=[])
        assert result is not None
        xlsx_bytes, _ = result
        assert len(xlsx_bytes) > 0

    def test_empty_all_lists_does_not_crash(self):
        """All empty lists must not crash."""
        result = self._build(
            matched_pairs=[],
            missed_rows=[],
            risk_rows=[],
            rule37_rows=[],
            section17_rows=[],
        )
        assert result is not None
        xlsx_bytes, _ = result
        assert len(xlsx_bytes) > 0

    def test_none_summary_values_do_not_crash(self):
        """None values in summary dict must not crash."""
        bad_summary = {k: None for k in SUMMARY}
        result = self._build(summary=bad_summary)
        assert result is not None
        xlsx_bytes, _ = result
        assert len(xlsx_bytes) > 0

    def test_filename_contains_period(self):
        """Filename should reference the period so CA knows what they downloaded."""
        _, filename = self._build()
        assert "2024" in filename or "Apr" in filename or "04" in filename, (
            f"Filename must reference the period. Got: '{filename}'"
        )

    def test_large_matched_pairs_does_not_crash(self):
        """100 matched pairs must not crash (cap is 1000)."""
        many_pairs = MATCHED_PAIRS * 100
        result = self._build(matched_pairs=many_pairs)
        assert result is not None
        xlsx_bytes, _ = result
        assert len(xlsx_bytes) > 0


# ── helper function tests ─────────────────────────────────────────────────────

class TestExportHelpers:

    def test_rs_int_formats_correctly(self):
        from app.services.reconcile_export_workbook import _rs_int
        assert _rs_int(100000) == "Rs 1,00,000" or _rs_int(100000) == "Rs 100,000", (
            f"_rs_int(100000) must format as rupees. Got: '{_rs_int(100000)}'"
        )

    def test_rs_int_zero(self):
        from app.services.reconcile_export_workbook import _rs_int
        result = _rs_int(0)
        assert "0" in result

    def test_period_mmm_yyyy_formats_april(self):
        from app.services.reconcile_export_workbook import _period_mmm_yyyy
        result = _period_mmm_yyyy("2024-04")
        assert "Apr" in result and "2024" in result, (
            f"Period must format as 'Apr 2024'. Got: '{result}'"
        )

    def test_period_mmm_yyyy_invalid_returns_input(self):
        from app.services.reconcile_export_workbook import _period_mmm_yyyy
        result = _period_mmm_yyyy("invalid")
        assert result == "invalid" or result == "—", (
            f"Invalid period must return input or dash. Got: '{result}'"
        )

    def test_decision_cell_none_returns_dash(self):
        from app.services.reconcile_export_workbook import _decision_cell
        assert _decision_cell(None) == "—"

    def test_decision_cell_empty_string_returns_dash(self):
        from app.services.reconcile_export_workbook import _decision_cell
        assert _decision_cell("") == "—"
        assert _decision_cell("   ") == "—"

    def test_decision_cell_value_returns_value(self):
        from app.services.reconcile_export_workbook import _decision_cell
        assert _decision_cell("No action required") == "No action required"
