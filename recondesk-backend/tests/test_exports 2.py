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
        "decision_what": "Invoice not reflected in GSTR-2B",
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
            review_required_rows=[],
            duplicate_rows=[],
            gstr3b_result=None,
            followup_rows=[],
        )
        assert result is not None
        xlsx_bytes, _ = result
        assert len(xlsx_bytes) > 0

    def test_full_workbook_always_includes_every_section_sheet(self):
        """Regression: every Excel export must contain all section sheets with data.

        Previously the UI `bucket` query cleared other sections so only the active
        tab's sheet had rows. The builder must always emit every sheet, and when
        sample data is provided for each category the data sheets must be non-empty.
        """
        from openpyxl import load_workbook

        review_rows = [
            {
                "supplier_gstin": "27REVW1234F1Z5",
                "invoice_number": "REV-1",
                "invoice_date": date(2024, 4, 2),
                "decision_why": "Amount mismatch",
                "amount": 1500.0,
                "match_confidence": 0.82,
                "compared_fields": [],
            }
        ]
        duplicate_rows = [
            {
                "supplier_gstin": "27DUPL1234F1Z5",
                "invoice_number": "DUP-1",
                "invoice_date": "2024-04-03",
                "amount": 25000,  # paise
                "matched_pr_id": "pr-canon",
                "decision_what": "Duplicate Entry",
                "decision_why": "Same invoice booked twice",
                "decision_next": "Remove extra PR row",
            }
        ]
        gstr3b_result = {
            "tax_period": "2024-04",
            "overall_status": "MATCHED",
            "gstr2b_igst_available": 1000,
            "gstr3b_igst_claimed": 1000,
            "igst_difference": 0,
            "igst_status": "MATCHED",
            "gstr2b_cgst_available": 500,
            "gstr3b_cgst_claimed": 500,
            "cgst_difference": 0,
            "cgst_status": "MATCHED",
            "gstr2b_sgst_available": 500,
            "gstr3b_sgst_claimed": 500,
            "sgst_difference": 0,
            "sgst_status": "MATCHED",
        }
        followup_rows = [
            {
                "supplier_name_display": "Acme Suppliers",
                "supplier_gstin": "27ACME1234F1Z5",
                "invoice_numbers_display": "INV001",
                "status": "generated",
                "generated_by_name": "Omkar Kadam",
                "generated_at": "2024-05-01T10:00:00+00:00",
                "template_type": "wrongful_itc",
            }
        ]

        xlsx_bytes, _ = self._build(
            review_required_rows=review_rows,
            duplicate_rows=duplicate_rows,
            gstr3b_result=gstr3b_result,
            followup_rows=followup_rows,
        )
        wb = load_workbook(BytesIO(xlsx_bytes))

        expected_sheets = [
            "Summary",
            "Matched Records",
            "Missed ITC",
            "Compliance Risk",
            "Rule 37 & Section 17-5",
            "Review Required",
            "Duplicate Entries",
            "GSTR-3B Check",
            "Follow-up Log",
            "Export Notes",
        ]
        for name in expected_sheets:
            assert name in wb.sheetnames, (
                f"Missing sheet '{name}'. Got: {wb.sheetnames}"
            )

        # Data sheets must have header + at least one data row (not empty/cleared).
        assert wb["Matched Records"].max_row >= 2
        assert wb["Missed ITC"].max_row >= 2
        assert wb["Compliance Risk"].max_row >= 2
        assert wb["Rule 37 & Section 17-5"].max_row >= 2
        assert wb["Review Required"].max_row >= 2
        assert wb["Duplicate Entries"].max_row >= 2
        assert wb["GSTR-3B Check"].max_row >= 3
        assert wb["Follow-up Log"].max_row >= 2

        # Spot-check that section data actually landed (not a blank placeholder).
        matched_vals = [
            str(c.value or "")
            for row in wb["Matched Records"].iter_rows(min_row=2, max_row=2)
            for c in row
        ]
        assert any("INV001" in v for v in matched_vals)
        dup_vals = [
            str(c.value or "")
            for row in wb["Duplicate Entries"].iter_rows(min_row=2, max_row=2)
            for c in row
        ]
        assert any("DUP-1" in v for v in dup_vals)
        fu_vals = [
            str(c.value or "")
            for row in wb["Follow-up Log"].iter_rows(min_row=2, max_row=2)
            for c in row
        ]
        assert any("Acme" in v for v in fu_vals)

    def test_empty_optional_sections_still_create_sheets_with_status(self):
        """Rule 37 / GSTR-3B / Follow-up sheets exist even when empty."""
        from openpyxl import load_workbook

        xlsx_bytes, _ = self._build(
            rule37_rows=[],
            section17_rows=[],
            gstr3b_result=None,
            followup_rows=[],
            duplicate_rows=[],
        )
        wb = load_workbook(BytesIO(xlsx_bytes))
        assert "Rule 37 & Section 17-5" in wb.sheetnames
        assert "GSTR-3B Check" in wb.sheetnames
        assert "Follow-up Log" in wb.sheetnames
        assert "Duplicate Entries" in wb.sheetnames
        assert "No Rule 37" in str(wb["Rule 37 & Section 17-5"]["A2"].value or "")
        assert "not uploaded" in str(wb["GSTR-3B Check"]["A2"].value or "").lower()
        assert "No supplier follow-up" in str(wb["Follow-up Log"]["A2"].value or "")
        assert "No duplicate" in str(wb["Duplicate Entries"]["A2"].value or "")

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

    def test_format_match_confidence_none_is_dash(self):
        from app.services.reconcile_export_workbook import _format_match_confidence
        assert _format_match_confidence(None) == "—"

    def test_format_match_confidence_fuzzy_percent(self):
        from app.services.reconcile_export_workbook import _format_match_confidence
        assert _format_match_confidence(0.85) == "85%"
        assert _format_match_confidence(0.9) == "90%"

    def test_format_match_rationale_flattens_fields(self):
        from app.services.reconcile_export_workbook import _format_match_rationale
        text = _format_match_rationale(
            [
                {"field_name": "gstin", "match_type": "exact", "field_score": None},
                {"field_name": "invoice_number", "match_type": "fuzzy", "field_score": 87},
                {"field_name": "taxable_amount", "match_type": "exact", "field_score": None},
                {"field_name": "date", "match_type": "not_matched", "field_score": None},
            ]
        )
        assert text == (
            "GSTIN: exact | Invoice#: fuzzy 87% | Amount: exact | Date: not matched"
        )

    def test_format_match_rationale_empty_is_dash(self):
        from app.services.reconcile_export_workbook import _format_match_rationale
        assert _format_match_rationale(None) == "—"
        assert _format_match_rationale([]) == "—"


class TestExcelConfidenceColumns:
    """Append-only Match Confidence / Match Rationale columns."""

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
            rule37_rows=RULE37_ROWS,
            section17_rows=SECTION17_ROWS,
            review_required_rows=[],
            generated_at=GENERATED_AT,
            generated_by_name="Omkar Kadam",
        )
        kwargs.update(overrides)
        return build_excel_workbook_bytes(**kwargs)

    def test_matched_sheet_appends_confidence_columns_without_shifting(self):
        from openpyxl import load_workbook

        xlsx_bytes, _ = self._build()
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Matched Records"]
        headers = [c.value for c in ws[1]]
        # Pre-existing columns keep their positions
        assert headers[:11] == [
            "Supplier GSTIN",
            "Invoice#",
            "Date",
            "Document Type",
            "Taxable Amount",
            "Total Tax",
            "Match Level",
            "Confidence",
            "WHAT IS WRONG",
            "WHY",
            "WHAT TO DO NEXT",
        ]
        assert headers[-2:] == ["Match Confidence", "Match Rationale"]

    def test_matched_l1_row_shows_dash_for_null_match_confidence(self):
        from openpyxl import load_workbook

        pairs = [
            (
                {
                    **MATCHED_PAIRS[0][0],
                    "amount": 1800,
                    "confidence_score": 100,
                    "match_confidence": None,
                    "compared_fields": [
                        {"field_name": "gstin", "match_type": "exact", "field_score": None},
                        {
                            "field_name": "invoice_number",
                            "match_type": "exact",
                            "field_score": None,
                        },
                    ],
                    "gstr2b_data": {"taxable_amount_paise": 1000000},
                },
                MATCHED_PAIRS[0][1],
            )
        ]
        xlsx_bytes, _ = self._build(matched_pairs=pairs)
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Matched Records"]
        headers = [c.value for c in ws[1]]
        conf_col = headers.index("Match Confidence") + 1
        rationale_col = headers.index("Match Rationale") + 1
        assert ws.cell(row=2, column=conf_col).value == "—"
        assert "GSTIN: exact" in str(ws.cell(row=2, column=rationale_col).value)

    def test_matched_fuzzy_row_formats_percent(self):
        from openpyxl import load_workbook

        pairs = [
            (
                {
                    **MATCHED_PAIRS[0][0],
                    "amount": 1800,
                    "confidence_score": 60,
                    "match_confidence": 0.87,
                    "compared_fields": [
                        {
                            "field_name": "invoice_number",
                            "match_type": "fuzzy",
                            "field_score": 87,
                        },
                    ],
                    "gstr2b_data": {"taxable_amount_paise": 1000000},
                },
                MATCHED_PAIRS[0][1],
            )
        ]
        xlsx_bytes, _ = self._build(matched_pairs=pairs)
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Matched Records"]
        headers = [c.value for c in ws[1]]
        conf_col = headers.index("Match Confidence") + 1
        assert ws.cell(row=2, column=conf_col).value == "87%"

    def test_review_required_sheet_appends_columns(self):
        from openpyxl import load_workbook

        review_rows = [
            {
                "supplier_gstin": "27ABCDE1234F1Z0",
                "invoice_number": "INV-TYPO",
                "invoice_date": "2024-04-02",
                "decision_why": "TYPO_MISMATCH",
                "amount": 18000,
                "match_confidence": 0.82,
                "compared_fields": [
                    {
                        "field_name": "invoice_number",
                        "match_type": "fuzzy",
                        "field_score": 82,
                    },
                ],
            }
        ]
        xlsx_bytes, _ = self._build(review_required_rows=review_rows)
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Review Required"]
        headers = [c.value for c in ws[1]]
        assert headers[:5] == [
            "Supplier GSTIN",
            "Invoice Number",
            "Invoice Date",
            "Reason",
            "Amount",
        ]
        assert headers[-2:] == ["Match Confidence", "Match Rationale"]
        assert ws.cell(row=2, column=6).value == "82%"
        assert "Invoice#: fuzzy 82%" in str(ws.cell(row=2, column=7).value)


class TestFuzzyWhatIsWrongAmountDiff:
    """Matched Records FUZZY rows must show the real taxable delta in WHAT IS WRONG."""

    def test_fuzzy_export_what_is_wrong_reflects_nonzero_taxable_delta(self):
        from openpyxl import load_workbook
        from app.decisions.layer import populate_decisions
        from app.services.reconcile_export_workbook import build_excel_workbook_bytes

        gstr_taxable_paise = 348_922_77  # ₹3,48,922.77
        pr_taxable_paise = 344_916_02  # ₹3,44,916.02
        expected_diff_paise = abs(gstr_taxable_paise - pr_taxable_paise)
        expected_rupees = f"₹{expected_diff_paise / 100:,.2f}"

        # Simulate engine clean-matched L2 row after the taxable_diff_paise fix.
        engine_row = {
            "gstr_id": "g-fuzzy-1",
            "pr_id": "p-fuzzy-1",
            "match_level": 2,
            "taxable_diff_paise": expected_diff_paise,
            "gstr_taxable_amount_paise": gstr_taxable_paise,
            "pr_taxable_amount_paise": pr_taxable_paise,
            "source_software": "Tally",
            "supplier_gstin": "23CMMPW9621S6ZO",
            "confidence_score": 90,
        }
        decided = populate_decisions([engine_row])["rows"][0]
        assert expected_rupees in decided["decision_what"], (
            f"decision layer must embed {expected_rupees}, got {decided['decision_what']!r}"
        )
        assert "₹0.00" not in decided["decision_what"]

        pairs = [
            (
                {
                    "supplier_gstin": "23CMMPW9621S6ZO",
                    "invoice_number": "09754",
                    "invoice_date": date(2025, 2, 23),
                    "amount": 348922.77,
                    "match_level": "FUZZY",
                    "confidence_score": 90,
                    "decision_what": decided["decision_what"],
                    "decision_why": decided["decision_why"],
                    "decision_next": decided["decision_next"],
                    "gstr2b_data": {"taxable_amount_paise": gstr_taxable_paise},
                },
                {"taxable_amount_paise": pr_taxable_paise},
            )
        ]
        xlsx_bytes, _ = build_excel_workbook_bytes(
            run_id=RUN_ID,
            firm_name=FIRM_NAME,
            client_trade_name=CLIENT_NAME,
            period_raw=PERIOD_RAW,
            summary=SUMMARY,
            matched_pairs=pairs,
            missed_rows=[],
            risk_rows=[],
            rule37_rows=[],
            section17_rows=[],
            review_required_rows=[],
            generated_at=GENERATED_AT,
            generated_by_name="Omkar Kadam",
        )
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Matched Records"]
        headers = [c.value for c in ws[1]]
        what_col = headers.index("WHAT IS WRONG") + 1
        level_col = headers.index("Match Level") + 1
        assert ws.cell(row=2, column=level_col).value == "FUZZY"
        what_cell = str(ws.cell(row=2, column=what_col).value or "")
        assert expected_rupees in what_cell, (
            f"FUZZY WHAT IS WRONG must contain {expected_rupees}, got {what_cell!r}"
        )
        assert "₹0.00" not in what_cell

    def test_fuzzy_zero_diff_export_says_normalized_not_amount_differs_zero(self):
        """Zero-discrepancy L2 (format-variant) must not export 'amount differs by ₹0.00'."""
        from openpyxl import load_workbook
        from app.decisions.layer import populate_decisions
        from app.services.reconcile_export_workbook import build_excel_workbook_bytes

        engine_row = {
            "gstr_id": "g-fuzzy-0",
            "pr_id": "p-fuzzy-0",
            "match_level": 2,
            "taxable_diff_paise": 0,
            "gstr_taxable_amount_paise": 100_000_00,
            "pr_taxable_amount_paise": 100_000_00,
            "source_software": "Tally",
            "supplier_gstin": "23CMMPW9621S6ZO",
            "confidence_score": 95,
            "gstr_invoice_number": "INV/001",
            "pr_invoice_number": "INV001",
        }
        decided = populate_decisions([engine_row])["rows"][0]
        assert decided["decision_rule"] == "L2_NORMALIZED" or "Normalized" in decided["decision_what"]
        assert "amount differs" not in decided["decision_what"].lower()
        assert "₹0.00" not in decided["decision_what"]

        pairs = [
            (
                {
                    "supplier_gstin": "23CMMPW9621S6ZO",
                    "invoice_number": "INV/001",
                    "invoice_date": date(2025, 2, 23),
                    "amount": 100000.00,
                    "match_level": "FUZZY",
                    "confidence_score": 95,
                    "decision_what": decided["decision_what"],
                    "decision_why": decided["decision_why"],
                    "decision_next": decided["decision_next"],
                    "gstr2b_data": {"taxable_amount_paise": 100_000_00},
                },
                {"taxable_amount_paise": 100_000_00},
            )
        ]
        xlsx_bytes, _ = build_excel_workbook_bytes(
            run_id=RUN_ID,
            firm_name=FIRM_NAME,
            client_trade_name=CLIENT_NAME,
            period_raw=PERIOD_RAW,
            summary=SUMMARY,
            matched_pairs=pairs,
            missed_rows=[],
            risk_rows=[],
            rule37_rows=[],
            section17_rows=[],
            review_required_rows=[],
            generated_at=GENERATED_AT,
            generated_by_name="Omkar Kadam",
        )
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Matched Records"]
        headers = [c.value for c in ws[1]]
        what_col = headers.index("WHAT IS WRONG") + 1
        what_cell = str(ws.cell(row=2, column=what_col).value or "")
        assert "Normalized invoice match" in what_cell
        assert "INV/001" in what_cell and "INV001" in what_cell
        assert "amount differs" not in what_cell.lower()
        assert "₹0.00" not in what_cell


class TestExcelExportNoRowCap:
    """Excel detail sheets must export every row — Summary counts must match sheet depth."""

    def test_matched_records_sheet_exports_all_rows_beyond_former_1000_cap(self):
        from openpyxl import load_workbook
        from app.services.reconcile_export_workbook import build_excel_workbook_bytes

        n = 1005
        pairs = [
            (
                {
                    "supplier_gstin": f"27ABCDE{i:04d}F1Z0",
                    "invoice_number": f"INV{i:04d}",
                    "invoice_date": date(2024, 4, 1),
                    "amount": 1000.0 + i,
                    "match_level": "EXACT" if i % 2 == 0 else "FUZZY",
                    "confidence_score": 100 if i % 2 == 0 else 95,
                    "decision_what": (
                        "Exact match found"
                        if i % 2 == 0
                        else "Normalized invoice match"
                    ),
                    "decision_why": "ok",
                    "decision_next": "No action required",
                    "gstr2b_data": {"taxable_amount_paise": 100_000},
                },
                {"taxable_amount_paise": 100_000},
            )
            for i in range(n)
        ]
        summary = {
            **SUMMARY,
            "matched_count": n,
            "total_gstr_records": n,
            "match_rate_percent": 100.0,
        }
        xlsx_bytes, _ = build_excel_workbook_bytes(
            run_id=RUN_ID,
            firm_name=FIRM_NAME,
            client_trade_name=CLIENT_NAME,
            period_raw=PERIOD_RAW,
            summary=summary,
            matched_pairs=pairs,
            missed_rows=[],
            risk_rows=[],
            rule37_rows=[],
            section17_rows=[],
            review_required_rows=[],
            generated_at=GENERATED_AT,
            generated_by_name="Omkar Kadam",
        )
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Matched Records"]
        # header + n data rows; no truncation footer
        data_rows = [
            r
            for r in ws.iter_rows(min_row=2, values_only=True)
            if r[0] is not None and not str(r[0]).startswith("[Note:")
        ]
        assert len(data_rows) == n, (
            f"Matched Records must export all {n} rows, got {len(data_rows)}"
        )
        notes = wb["Export Notes"]
        note_text = " ".join(
            str(c or "") for row in notes.iter_rows(values_only=True) for c in row
        )
        assert "Capped at" not in note_text
        # Export Notes row count must report full n
        found = False
        for row in notes.iter_rows(values_only=True):
            if row and row[0] == "Matched Records":
                assert str(row[1]) == str(n)
                found = True
        assert found


class TestSection175ExportSheet:
    """Rule 37 & Section 17-5 sheet must not emit ? placeholders or blank shells."""

    def test_section175_export_has_hsn_category_date_amount(self):
        from openpyxl import load_workbook
        from collections import Counter
        from app.services.blocked_credit_checker import check_blocked_credits
        from app.decisions.layer import populate_decisions
        from app.routers.reconciliation_api import _build_section175_rows
        from app.services.reconcile_export_workbook import build_excel_workbook_bytes

        warnings = check_blocked_credits(
            [
                {
                    "invoice_number": "INV-8703",
                    "supplier_gstin": "27ABCDE1234F1Z5",
                    "hsn_code": "8703",
                    "invoice_date": "2024-06-15",
                    "total_tax_paise": 90_000,
                }
            ]
        )
        decided = populate_decisions([], section_175_warnings=warnings)
        payload = {
            "decisions": {"section_175": decided["section_175"]},
            "compliance": {"section_17_5": warnings},
        }
        rows = _build_section175_rows(None, RUN_ID, payload, Counter())
        assert len(rows) == 1
        row = rows[0]
        assert row["invoice_number"] == "INV-8703"
        assert row["invoice_date"] == "2024-06-15"
        assert row["amount"] == 900.0
        assert "?" not in (row["decision_what"] or "")
        assert "?" not in (row["decision_why"] or "")
        assert "8703" in (row["decision_why"] or "")

        xlsx_bytes, _ = build_excel_workbook_bytes(
            run_id=RUN_ID,
            firm_name=FIRM_NAME,
            client_trade_name=CLIENT_NAME,
            period_raw=PERIOD_RAW,
            summary=SUMMARY,
            matched_pairs=[],
            missed_rows=[],
            risk_rows=[],
            rule37_rows=[],
            section17_rows=rows,
            review_required_rows=[],
            generated_at=GENERATED_AT,
            generated_by_name="Omkar Kadam",
        )
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Rule 37 & Section 17-5"]
        headers = [c.value for c in ws[1]]
        assert ws.cell(row=2, column=headers.index("Type") + 1).value == "Section 17(5)"
        assert ws.cell(row=2, column=headers.index("Invoice#") + 1).value == "INV-8703"
        assert "2024-06-15" in str(ws.cell(row=2, column=headers.index("Date") + 1).value)
        what = str(ws.cell(row=2, column=headers.index("WHAT IS WRONG") + 1).value)
        why = str(ws.cell(row=2, column=headers.index("WHY") + 1).value)
        assert "?" not in what
        assert "?" not in why
        assert "8703" in why

    def test_blank_section175_shells_excluded_from_export(self):
        from openpyxl import load_workbook
        from app.services.reconcile_export_workbook import build_excel_workbook_bytes

        blank = {
            "supplier_gstin": "",
            "invoice_number": "",
            "invoice_date": "",
            "amount": 0,
            "decision_what": None,
            "decision_why": None,
            "decision_next": None,
        }
        placeholder = {
            "supplier_gstin": "27ABCDE1234F1Z5",
            "invoice_number": "INV-X",
            "invoice_date": "",
            "amount": 0,
            "decision_what": "Invoice may be under Section 17(5) blocked credit: ?",
            "decision_why": "HSN ? commonly associated with ? -- ineligible for ITC",
            "decision_next": "Verify",
        }
        xlsx_bytes, _ = build_excel_workbook_bytes(
            run_id=RUN_ID,
            firm_name=FIRM_NAME,
            client_trade_name=CLIENT_NAME,
            period_raw=PERIOD_RAW,
            summary=SUMMARY,
            matched_pairs=[],
            missed_rows=[],
            risk_rows=[],
            rule37_rows=[],
            section17_rows=[blank, placeholder],
            review_required_rows=[],
            generated_at=GENERATED_AT,
            generated_by_name="Omkar Kadam",
        )
        wb = load_workbook(BytesIO(xlsx_bytes))
        ws = wb["Rule 37 & Section 17-5"]
        # Only the header + empty-state message (no data rows)
        assert ws.cell(row=2, column=1).value == "No Rule 37 or Section 17(5) flags found."
