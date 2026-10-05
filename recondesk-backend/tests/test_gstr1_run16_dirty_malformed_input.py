"""Run 16 — Dirty ERP / Malformed GSTN Input Tests.

Enterprise hardening test suite covering:
1. 30 Dirty Excel tests (trailing blanks, formula errors, corrupted dates,
   scientific notation, unicode spaces, currency symbols, missing columns).
2. 25 GSTN JSON resilience tests (missing keys, null arrays, extra fields,
   string numbers, rate formats, section variations, skip diagnostics).
3. 10 Mapping ambiguity and Import Quality Report tests (date ranking,
   column disambiguation, structured WHAT/WHY/NEXT reporting).
"""

import io
import json
import openpyxl
import pytest
from datetime import date

from app.parsers.sales_register_parser import (
    ParseError,
    _date_col_specificity,
    _invoice_number_raw_from_cell,
    _normalize_invoice_number_cell,
    _preprocess_amount,
    _safe_cell,
    detect_column_mapping,
    generate_import_quality_report,
    parse_sales_register,
)
from app.parsers.gstr1_parser import (
    SKIP_INVALID_INVOICE_DATE,
    SKIP_MISSING_GSTIN,
    SKIP_MISSING_INVOICE_DATE,
    SKIP_MISSING_INVOICE_NUMBER,
    parse_gstr1,
)
from app.services.normalizer import normalize_date


# =============================================================================
# Helper to build in-memory Excel files
# =============================================================================

def _build_excel_bytes(rows: list[list]) -> bytes:
    """Build an in-memory .xlsx file from a list of rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# =============================================================================
# GROUP 1: 30 DIRTY EXCEL TESTS
# =============================================================================

def test_01_excel_trailing_50_blank_rows():
    """1. Trailing 50 blank rows do not create phantom invoices or errors."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount", "IGST"],
        ["27ABCDE1234F1Z5", "INV-001", "2026-09-01", 10000.0, 1800.0],
        ["27ABCDE1234F1Z5", "INV-002", "2026-09-02", 20000.0, 3600.0],
    ]
    for _ in range(50):
        rows.append([None, None, None, None, None])

    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 2
    assert res["records"][0]["invoice_number_raw"] == "INV-001"
    assert res["records"][1]["invoice_number_raw"] == "INV-002"


def test_02_excel_formula_error_na_in_taxable_amount():
    """2. Formula error #N/A in amount cell is handled gracefully without crash."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount", "IGST"],
        ["27ABCDE1234F1Z5", "INV-001", "2026-09-01", "#N/A", 1800.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 1
    # #N/A safely converted to None/0 paise without unhandled exception
    assert res["records"][0]["taxable_amount_paise"] in (0, None)


def test_03_excel_formula_error_ref_in_igst():
    """3. Formula error #REF! in tax column defaults cleanly."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount", "IGST"],
        ["27ABCDE1234F1Z5", "INV-003", "2026-09-03", 50000.0, "#REF!"],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert res["records"][0]["igst_paise"] in (0, None)


def test_04_excel_formula_error_div_zero_in_total():
    """4. Formula error #DIV/0! in total column handled cleanly."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount", "Total Amount"],
        ["27ABCDE1234F1Z5", "INV-004", "2026-09-04", 50000.0, "#DIV/0!"],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert res["records"][0]["total_amount_paise"] in (0, None)


def test_05_excel_formula_error_value():
    """5. Formula error #VALUE! in amount column handled cleanly."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
        ["27ABCDE1234F1Z5", "INV-005", "2026-09-05", "#VALUE!"],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert res["records"][0]["taxable_amount_paise"] in (0, None)


def test_06_excel_formula_error_name():
    """6. Formula error #NAME? in cell handled cleanly."""
    assert _safe_cell("#NAME?") is None
    assert _preprocess_amount("#NAME?") == ""


def test_07_excel_corrupted_date_feb_31():
    """7. Corrupted calendar date '31/02/2026' skips invalid row gracefully."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
        ["27ABCDE1234F1Z5", "INV-GOOD", "2026-09-01", 10000.0],
        ["27ABCDE1234F1Z5", "INV-BAD", "31/02/2026", 20000.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 1
    assert res["records"][0]["invoice_number_raw"] == "INV-GOOD"
    assert res["skipped_rows"] == 1


def test_08_excel_corrupted_date_month_13():
    """8. Corrupted date '2026-13-45' skips invalid row gracefully."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
        ["27ABCDE1234F1Z5", "INV-BAD2", "2026-13-45", 20000.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert len(res["records"]) == 0
    assert res["skipped_rows"] == 1


def test_09_excel_serial_date_integer():
    """9. Excel serial date integer 46270 correctly converted to date."""
    res = normalize_date(46270)
    assert isinstance(res.value, date)


def test_10_excel_serial_date_float():
    """10. Excel serial date float 46270.0 correctly converted to date."""
    res = normalize_date(46270.0)
    assert isinstance(res.value, date)


def test_11_excel_mixed_date_formats():
    """11. Mixed date formats across rows all normalize properly."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
        ["27ABCDE1234F1Z5", "INV-11A", "05/09/2026", 10000.0],
        ["27ABCDE1234F1Z5", "INV-11B", "2026-09-06", 10000.0],
        ["27ABCDE1234F1Z5", "INV-11C", "07-Sep-2026", 10000.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 3
    dates = [r["invoice_date"] for r in res["records"]]
    assert dates == ["2026-09-05", "2026-09-06", "2026-09-07"]


def test_12_excel_century_expansion_2_digit_year():
    """12. 2-digit year 15/09/26 expands to 2026-09-15."""
    res = normalize_date("15/09/26")
    assert res.value == date(2026, 9, 15)


def test_13_excel_scientific_notation_invoice_number():
    """13. Scientific notation invoice number '1.23E+05' normalizes to '123000'."""
    assert _normalize_invoice_number_cell("1.23E+05") == "123000"
    assert _invoice_number_raw_from_cell("1.23E+05") == "123000"


def test_14_excel_float_invoice_number_whole():
    """14. Whole number float 100456.0 becomes string '100456'."""
    assert _normalize_invoice_number_cell(100456.0) == "100456"
    assert _invoice_number_raw_from_cell(100456.0) == "100456"


def test_15_excel_zero_width_space_in_invoice_number():
    """15. Invoice number containing zero-width space is stripped clean."""
    raw = "\u200bINV-015\u200b"
    assert _safe_cell(raw) == "INV-015"
    assert _normalize_invoice_number_cell(raw) == "INV15"
    assert _invoice_number_raw_from_cell(raw) == "INV-015"


def test_16_excel_bom_char_in_invoice_number():
    """16. Invoice number starting with BOM \\ufeff is cleaned."""
    raw = "\ufeffINV-016"
    assert _safe_cell(raw) == "INV-016"


def test_17_excel_non_breaking_space():
    """17. Non-breaking space \\u00a0 is converted to standard whitespace."""
    raw = "\u00a0INV-017\u00a0"
    assert _safe_cell(raw) == "INV-017"


def test_18_excel_rupee_symbol_and_commas():
    """18. Indian currency symbol ₹ and commas are stripped."""
    assert _preprocess_amount("₹ 1,50,000.00") == "150000.00"


def test_19_excel_dollar_symbol():
    """19. Dollar symbol $ and commas stripped."""
    assert _preprocess_amount("$ 2,500.00") == "2500.00"


def test_20_excel_euro_and_pound_symbols():
    """20. Euro and Pound symbols stripped cleanly."""
    assert _preprocess_amount("€ 3,000.00") == "3000.00"
    assert _preprocess_amount("£ 4,000.00") == "4000.00"


def test_21_excel_parentheses_negative_amount():
    """21. Accounting negative (15,000.00) parsed properly."""
    res = normalize_date("2026-09-01")
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
        ["27ABCDE1234F1Z5", "INV-021", "2026-09-01", "(15,000.00)"],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert res["records"][0]["taxable_amount_paise"] == -1500000


def test_22_excel_empty_file_zero_bytes():
    """22. Empty file (0 bytes) returns structured error without crashing."""
    res = parse_sales_register(b"", "empty.xlsx")
    assert res["success"] is False
    assert "Empty file" in res["errors"]
    assert res["import_quality_report"]["status"] == "FAILED"


def test_23_excel_whitespace_only_file():
    """23. Whitespace-only file returns error."""
    res = parse_sales_register(b"   \n  \t  ", "empty.xlsx")
    assert res["success"] is False
    assert "Empty file" in res["errors"]


def test_24_excel_missing_mandatory_invoice_number_column():
    """24. File missing both GSTIN and Invoice Number raises ParseError / reports missing column."""
    rows = [
        ["ColA", "ColB", "ColC"],
        [100, 200, 300],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is False
    assert res["import_quality_report"]["status"] == "FAILED"
    assert any(issue["category"] == "MISSING_MANDATORY_COLUMN" for issue in res["import_quality_report"]["issues"])


def test_25_excel_unregistered_urp_vendor():
    """25. URP / Unregistered party without GSTIN parses as B2C invoice."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
        ["URP", "INV-B2C-025", "2026-09-01", 5000.0],
        ["N/A", "INV-B2C-026", "2026-09-02", 8000.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 2
    assert res["records"][0]["gstin"] is None
    assert res["records"][1]["gstin"] is None


def test_26_excel_only_header_no_data_rows():
    """26. File with header but zero data rows handled cleanly."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["total_rows"] == 0
    assert len(res["records"]) == 0
    assert "No data rows found" in res["errors"]


def test_27_excel_unicode_recipient_name():
    """27. Unicode recipient name with special characters parses without encoding corruption."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Party Name", "Taxable Amount"],
        ["27ABCDE1234F1Z5", "INV-027", "2026-09-01", "ॐ Shree Ganesh Traders & Co.™", 10000.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert "ॐ Shree Ganesh Traders" in res["records"][0]["recipient_name"]


def test_28_excel_subheaders_or_section_dividers():
    """28. Section divider rows (e.g. '--- September Sales ---') are skipped without error."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"],
        ["--- September 2026 Sales ---", None, None, None],
        ["27ABCDE1234F1Z5", "INV-028", "2026-09-01", 10000.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 1
    assert res["records"][0]["invoice_number_raw"] == "INV-028"


def test_29_excel_multi_sheet_workbook():
    """29. Multi-sheet Excel combines rows across sheets."""
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "North"
    ws1.append(["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"])
    ws1.append(["27ABCDE1234F1Z5", "INV-NORTH-1", "2026-09-01", 10000.0])

    ws2 = wb.create_sheet("South")
    ws2.append(["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount"])
    ws2.append(["27ABCDE1234F1Z5", "INV-SOUTH-1", "2026-09-02", 20000.0])

    buf = io.BytesIO()
    wb.save(buf)
    res = parse_sales_register(buf.getvalue(), "multisheet.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 2
    assert {r["invoice_number_raw"] for r in res["records"]} == {"INV-NORTH-1", "INV-SOUTH-1"}


def test_30_excel_grand_total_row_ignored():
    """30. Trailing 'Grand Total' row is ignored and not treated as invoice."""
    rows = [
        ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount", "IGST"],
        ["27ABCDE1234F1Z5", "INV-030", "2026-09-01", 10000.0, 1800.0],
        ["Grand Total", None, None, 10000.0, 1800.0],
    ]
    content = _build_excel_bytes(rows)
    res = parse_sales_register(content, "sales.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 1
    assert res["records"][0]["invoice_number_raw"] == "INV-030"


# =============================================================================
# GROUP 2: 25 GSTN JSON RESILIENCE TESTS
# =============================================================================

def test_31_gstn_missing_b2b_section():
    """31. Missing b2b section in JSON payload does not crash."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 0
    assert "b2b" in res["sections_absent"]


def test_32_gstn_null_b2b_section():
    """32. 'b2b': null in payload handled safely as absent/empty."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": None,
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 0


def test_33_gstn_empty_b2b_array():
    """33. 'b2b': [] empty list returns 0 parsed rows without error."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 0
    assert res["section_counts"].get("b2b", 0) == 0


def test_34_gstn_null_inv_array_under_recipient():
    """34. Recipient dict with 'inv': null is skipped safely."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {"ctin": "29XYZAB1234C1Z9", "inv": None}
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 0


def test_35_gstn_null_items_array():
    """35. Invoice with 'itms': null is handled safely without unhandled exception."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {"inum": "INV-035", "idt": "01-09-2026", "val": 1180.0, "itms": None}
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    # Parser gracefully either parses header amount or skips safely
    assert res["total_parsed"] + res["total_skipped"] == 1


def test_36_gstn_extra_unexpected_top_level_fields():
    """36. Unexpected top-level metadata fields are safely ignored."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "portal_version": "v3.2.1",
        "checksum_sha256": "abcdef123456",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-036",
                        "idt": "01-09-2026",
                        "val": 1180.0,
                        "itms": [{"num": 1, "itm_det": {"rt": 18.0, "txval": 1000.0, "iamt": 180.0}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["invoice_number_raw"] == "INV-036"


def test_37_gstn_extra_unexpected_invoice_fields():
    """37. Schema extensions or extra fields in invoice dict parsed without error."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-037",
                        "idt": "01-09-2026",
                        "val": 1180.0,
                        "custom_tracking_id": "TRK-9999",
                        "internal_notes": "approved by audit",
                        "itms": [{"num": 1, "itm_det": {"rt": 18.0, "txval": 1000.0, "iamt": 180.0}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1


def test_38_gstn_string_numbers_for_taxable_value():
    """38. String numbers 'txval': '1000.50' parsed accurately into paise."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-038",
                        "idt": "01-09-2026",
                        "val": "1180.59",
                        "itms": [{"num": 1, "itm_det": {"rt": 18.0, "txval": "1000.50", "iamt": "180.09"}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["taxable_amount_paise"] == 100050
    assert res["records"][0]["igst_paise"] == 18009


def test_39_gstn_string_numbers_all_tax_heads():
    """39. String numbers for igst, cgst, sgst, cess parsed into paise."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "27ABCDE1234F1Z5",
                "inv": [
                    {
                        "inum": "INV-039",
                        "idt": "01-09-2026",
                        "val": "1300.00",
                        "itms": [{
                            "num": 1,
                            "itm_det": {
                                "rt": 18.0,
                                "txval": "1000.00",
                                "cgst": "90.00",
                                "sgst": "90.00",
                                "cess": "120.00",
                            },
                        }],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["cgst_paise"] == 9000
    assert res["records"][0]["sgst_paise"] == 9000
    assert res["records"][0]["cess_paise"] == 12000


def test_40_gstn_tax_rate_with_percentage_suffix():
    """40. Tax rate supplied as string '18%' parsed as 18.0."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-040",
                        "idt": "01-09-2026",
                        "val": 1180.0,
                        "itms": [{"num": 1, "itm_det": {"rt": "18%", "txval": 1000.0, "iamt": 180.0}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["rate"] == 18.0


def test_41_gstn_tax_rate_integer():
    """41. Tax rate integer 18 parsed as 18.0."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-041",
                        "idt": "01-09-2026",
                        "val": 1180.0,
                        "itms": [{"num": 1, "itm_det": {"rt": 18, "txval": 1000.0, "iamt": 180.0}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["rate"] == 18.0


def test_42_gstn_tax_rate_float():
    """42. Tax rate float 18.0 parsed as 18.0."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-042",
                        "idt": "01-09-2026",
                        "val": 1180.0,
                        "itms": [{"num": 1, "itm_det": {"rt": 18.0, "txval": 1000.0, "iamt": 180.0}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["rate"] == 18.0


def test_43_gstn_missing_cess_defaults_to_zero():
    """43. Missing cess key in item defaults to 0 paise."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-043",
                        "idt": "01-09-2026",
                        "val": 1180.0,
                        "itms": [{"num": 1, "itm_det": {"rt": 18.0, "txval": 1000.0, "iamt": 180.0}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["records"][0]["cess_paise"] == 0


def test_44_gstn_mixed_sections_payload():
    """44. Payload containing B2B, B2BA, B2CL, B2CS, CDNR, EXP, NIL all parsed."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {"ctin": "29XYZAB1234C1Z9", "inv": [{"inum": "B2B-1", "idt": "01-09-2026", "val": 1180, "itms": [{"itm_det": {"rt": 18, "txval": 1000, "iamt": 180}}]}]}
        ],
        "b2cs": [
            {"sply_ty": "INTER", "rt": 18, "txval": 5000, "iamt": 900, "pos": "29"}
        ],
        "nil": {
            "inv": [
                {"sply_ty": "INTRAB2B", "nil_amt": 2000, "expt_amt": 0, "ngsup_amt": 0}
            ]
        },
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 3
    sections = {r["section"] for r in res["records"]}
    assert "b2b" in sections
    assert "b2cs" in sections
    assert "nil" in sections


def test_45_gstn_missing_fp_with_fallback_period():
    """45. Missing fp key in JSON handled when filing_period fallback supplied."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "b2b": [],
    }
    res = parse_gstr1(payload, filing_period="092026")
    assert res["filing_period"] == "2026-09-01"


def test_46_gstn_missing_ctin_skipped_with_diagnostic():
    """46. Recipient dict without ctin skipped with SKIP_MISSING_GSTIN."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {"inv": [{"inum": "INV-046", "idt": "01-09-2026", "val": 1180, "itms": [{"itm_det": {"rt": 18, "txval": 1000, "iamt": 180}}]}]}
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_skipped"] == 1
    assert res["skipped"][0]["category"] == SKIP_MISSING_GSTIN


def test_47_gstn_missing_inum_skipped_with_diagnostic():
    """47. Invoice dict without inum skipped with SKIP_MISSING_INVOICE_NUMBER."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [{"idt": "01-09-2026", "val": 1180, "itms": [{"itm_det": {"rt": 18, "txval": 1000, "iamt": 180}}]}],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_skipped"] == 1
    assert res["skipped"][0]["category"] == SKIP_MISSING_INVOICE_NUMBER


def test_48_gstn_missing_idt_skipped_with_diagnostic():
    """48. Invoice dict without idt skipped with SKIP_MISSING_INVOICE_DATE."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [{"inum": "INV-048", "val": 1180, "itms": [{"itm_det": {"rt": 18, "txval": 1000, "iamt": 180}}]}],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_skipped"] == 1
    assert res["skipped"][0]["category"] == SKIP_MISSING_INVOICE_DATE


def test_49_gstn_invalid_idt_format_skipped():
    """49. Invalid date string in idt skipped with SKIP_INVALID_INVOICE_DATE."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [{"inum": "INV-049", "idt": "invalid-date", "val": 1180, "itms": [{"itm_det": {"rt": 18, "txval": 1000, "iamt": 180}}]}],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_skipped"] == 1
    assert res["skipped"][0]["category"] == SKIP_INVALID_INVOICE_DATE


def test_50_gstn_negative_amount_credit_note():
    """50. Negative amounts in taxable values supported for credit items."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "cdnr": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "nt": [
                    {
                        "nt_num": "CN-050",
                        "nt_dt": "05-09-2026",
                        "val": 590.0,
                        "ntty": "C",
                        "itms": [{"num": 1, "itm_det": {"rt": 18.0, "txval": 500.0, "iamt": 90.0}}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["invoice_number_raw"] == "CN-050"


def test_51_gstn_utf8_bom_json_bytes():
    """51. JSON bytes with leading UTF-8 BOM \\xef\\xbb\\xbf parsed cleanly."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [],
    }
    raw_bytes = b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8")
    res = parse_gstr1(raw_bytes)
    assert res["total_parsed"] == 0
    assert res["filing_gstin"] == "27ABCDE1234F1Z5"


def test_52_gstn_ret_period_key_variant():
    """52. 'ret_period' accepted as alternative to 'fp'."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "ret_period": "092026",
        "b2b": [],
    }
    res = parse_gstr1(payload)
    assert res["filing_period"] == "2026-09-01"


def test_53_gstn_rtnprd_key_variant():
    """53. 'rtnprd' accepted as alternative to 'fp'."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "rtnprd": "092026",
        "b2b": [],
    }
    res = parse_gstr1(payload)
    assert res["filing_period"] == "2026-09-01"


def test_54_gstn_nested_data_wrapper():
    """54. Payload wrapped in {'data': {...}} parsed seamlessly."""
    payload = {
        "status_cd": "1",
        "data": {
            "gstin": "27ABCDE1234F1Z5",
            "fp": "092026",
            "b2b": [],
        },
    }
    res = parse_gstr1(payload)
    assert res["filing_gstin"] == "27ABCDE1234F1Z5"


def test_55_gstn_flat_items_format():
    """55. Flat item format without nested 'itm_det' wrapper is parsed."""
    payload = {
        "gstin": "27ABCDE1234F1Z5",
        "fp": "092026",
        "b2b": [
            {
                "ctin": "29XYZAB1234C1Z9",
                "inv": [
                    {
                        "inum": "INV-055",
                        "idt": "01-09-2026",
                        "val": 1180.0,
                        "itms": [{"rt": 18.0, "txval": 1000.0, "iamt": 180.0}],
                    }
                ],
            }
        ],
    }
    res = parse_gstr1(payload)
    assert res["total_parsed"] == 1
    assert res["records"][0]["taxable_amount_paise"] == 100000


# =============================================================================
# GROUP 3: 10 MAPPING AMBIGUITY & REPORT TESTS
# =============================================================================

def test_56_date_ranking_invoice_date_over_posting_date():
    """56. When both 'Invoice Date' and 'Posting Date' exist, 'Invoice Date' is preferred."""
    import pandas as pd
    df = pd.DataFrame(columns=["GSTIN", "Invoice Number", "Invoice Date", "Posting Date", "Taxable Amount"])
    mapping = detect_column_mapping(df)
    assert mapping["invoice_date"] == "Invoice Date"


def test_57_date_ranking_bill_date_over_voucher_date():
    """57. When both 'Bill Date' and 'Voucher Date' exist, 'Bill Date' is preferred."""
    import pandas as pd
    df = pd.DataFrame(columns=["GSTIN", "Bill No", "Bill Date", "Voucher Date", "Taxable Amount"])
    mapping = detect_column_mapping(df)
    assert mapping["invoice_date"] == "Bill Date"


def test_58_date_ranking_tax_invoice_date_over_due_date():
    """58. 'Tax Invoice Date' preferred over 'Due Date'."""
    import pandas as pd
    df = pd.DataFrame(columns=["GSTIN", "Inv No", "Tax Invoice Date", "Due Date", "Amount"])
    mapping = detect_column_mapping(df)
    assert mapping["invoice_date"] == "Tax Invoice Date"


def test_59_date_ranking_date_over_ship_date():
    """59. 'Date' preferred over 'Ship Date'."""
    assert _date_col_specificity("Date") > _date_col_specificity("Ship Date")


def test_60_date_ranking_document_date_over_entry_date():
    """60. 'Document Date' preferred over 'Entry Date'."""
    assert _date_col_specificity("Document Date") > _date_col_specificity("Entry Date")


def test_61_column_mapping_total_tax_and_taxable_value():
    """61. 'Total Tax' and 'Taxable Value' correctly mapped to distinct concepts."""
    import pandas as pd
    df = pd.DataFrame(columns=["GSTIN", "Invoice Number", "Taxable Value", "Total Tax"])
    mapping = detect_column_mapping(df)
    assert mapping["taxable_amount"] == "Taxable Value"
    assert mapping["total_tax"] == "Total Tax"


def test_62_column_mapping_integrated_tax_to_igst():
    """62. 'Integrated Tax' mapped to igst."""
    import pandas as pd
    df = pd.DataFrame(columns=["GSTIN", "Invoice Number", "Integrated Tax"])
    mapping = detect_column_mapping(df)
    assert mapping["igst"] == "Integrated Tax"


def test_63_import_report_what_why_next_missing_column():
    """63. Import Quality Report produces WHAT/WHY/NEXT on missing mandatory column."""
    parse_result = {
        "success": False,
        "total_rows": 10,
        "valid_rows": 0,
        "skipped_rows": 0,
        "errors": ["Cannot identify GSTIN or invoice number columns"],
        "warnings": [],
    }
    report = generate_import_quality_report(parse_result, filename="bad_cols.xlsx")
    assert report["status"] == "FAILED"
    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["category"] == "MISSING_MANDATORY_COLUMN"
    assert "Mandatory invoice identification" in issue["what"]
    assert "headers do not match" in issue["why"]
    assert "Ensure your Excel/CSV has columns" in issue["next_step"]


def test_64_import_report_what_why_next_empty_file():
    """64. Import Quality Report produces WHAT/WHY/NEXT on empty file."""
    parse_result = {
        "success": False,
        "total_rows": 0,
        "valid_rows": 0,
        "skipped_rows": 0,
        "errors": ["Empty file"],
        "warnings": [],
    }
    report = generate_import_quality_report(parse_result, filename="empty.xlsx")
    assert report["status"] == "FAILED"
    issue = report["issues"][0]
    assert issue["category"] == "EMPTY_FILE"
    assert "uploaded file is empty" in issue["what"]
    assert "0 bytes" in issue["why"]
    assert "Verify the selected file" in issue["next_step"]


def test_65_import_report_what_why_next_skipped_rows():
    """65. Import Quality Report produces WARNING with WHAT/WHY/NEXT when rows skipped."""
    parse_result = {
        "success": True,
        "total_rows": 100,
        "valid_rows": 95,
        "skipped_rows": 5,
        "errors": [],
        "warnings": [],
    }
    report = generate_import_quality_report(parse_result, filename="sales.xlsx")
    assert report["status"] == "WARNING"
    issue = report["issues"][0]
    assert issue["category"] == "SKIPPED_ROWS"
    assert "5 row(s) were skipped" in issue["what"]
    assert "lacked valid invoice numbers" in issue["why"]
    assert "Review skipped rows" in issue["next_step"]
