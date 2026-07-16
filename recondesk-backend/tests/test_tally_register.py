"""Tally Export profiles, Purchase vs Sales type detection, and quirks."""

from __future__ import annotations

import io

import pandas as pd
import pytest
from openpyxl import Workbook

from app.parsers.purchase_register_parser import (
    COLUMN_ALIASES as PR_ALIASES,
    detect_column_mapping as pr_detect_mapping,
    detect_source_software as pr_detect_software,
    parse_purchase_register,
)
from app.parsers.sales_register_parser import (
    COLUMN_ALIASES as SR_ALIASES,
    detect_column_mapping as sr_detect_mapping,
    detect_source_software as sr_detect_software,
    parse_sales_register,
)
from app.parsers.tally_register import (
    TALLY_PURCHASE_ALIASES,
    TALLY_SALES_ALIASES,
    detect_register_type,
    extract_gstin_from_party_cell,
    inspect_register_file,
    looks_like_tally_headers,
    normalize_header,
    validate_tally_export,
)


def _xlsx(rows: list[list], sheet: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Alias profiles
# ---------------------------------------------------------------------------

def test_tally_purchase_aliases_merged_into_pr_parser():
    for field, aliases in TALLY_PURCHASE_ALIASES.items():
        assert field in PR_ALIASES
        for alias in aliases:
            assert normalize_header(alias) in {
                normalize_header(a) for a in PR_ALIASES[field]
            }


def test_tally_sales_aliases_merged_into_sr_parser():
    for field, aliases in TALLY_SALES_ALIASES.items():
        assert field in SR_ALIASES
        for alias in aliases:
            assert normalize_header(alias) in {
                normalize_header(a) for a in SR_ALIASES[field]
            }


def test_tally_purchase_headers_map_to_canonical_fields():
    df = pd.DataFrame(
        columns=[
            "Date",
            "Party's A/c Name",
            "Vch Type",
            "Vch No.",
            "GSTIN/UIN",
            "Invoice No.",
            "Invoice Date",
            "Taxable Amt",
            "CGST",
            "SGST",
            "IGST",
            "Gross Total",
        ]
    )
    mapping = pr_detect_mapping(df)
    assert mapping["supplier_name"] == "Party's A/c Name"
    assert mapping["invoice_number"] in ("Vch No.", "Invoice No.")
    assert mapping["gstin"] == "GSTIN/UIN"
    assert mapping["taxable_amount"] == "Taxable Amt"
    assert mapping["total_amount"] == "Gross Total"
    assert pr_detect_software(list(df.columns)) == "Tally"


def test_tally_sales_headers_map_including_invoice_type():
    df = pd.DataFrame(
        columns=[
            "Date",
            "Particulars",
            "Vch Type",
            "Vch No.",
            "GSTIN/UIN",
            "Taxable Amt",
            "CGST",
            "SGST",
            "IGST",
            "Gross Total",
            "Invoice Type",
        ]
    )
    mapping = sr_detect_mapping(df)
    assert mapping["recipient_name"] == "Particulars"
    assert mapping["gstin"] == "GSTIN/UIN"
    assert mapping["invoice_number"] == "Vch No."
    assert mapping["invoice_type"] in ("Invoice Type", "Vch Type")
    assert sr_detect_software(list(df.columns)) == "Tally"


# ---------------------------------------------------------------------------
# Type detection
# ---------------------------------------------------------------------------

def test_detect_purchase_from_sheet_title_and_headers():
    det = detect_register_type(
        headers=[
            "Date",
            "Supplier Name",
            "Vch Type",
            "Vch No.",
            "GSTIN/UIN",
            "Taxable Amt",
            "CGST",
            "SGST",
            "IGST",
        ],
        sample_rows=[
            ["2025-04-01", "Acme", "Purchase", "V-1", "27AABCU9603R1ZM", 1000, 90, 90, 0]
        ],
        sheet_names=["Purchase Register"],
        title_texts=["GSTR-2 Purchase Register"],
    )
    assert det.register_type == "purchase"
    assert det.confidence in ("high", "medium")
    assert det.suggested_pipeline == "gstr2b"
    assert det.requires_manual_choice is False


def test_detect_sales_from_voucher_type_samples():
    det = detect_register_type(
        headers=[
            "Date",
            "Particulars",
            "Vch Type",
            "Vch No.",
            "GST Reg No",
            "Taxable Amt",
            "CGST",
            "SGST",
            "IGST",
            "Gross Total",
        ],
        sample_rows=[
            ["2025-04-01", "Buyer A", "Sales", "S-1", "27AABCU9603R1ZM", 1000, 90, 90, 0, 1180],
            ["2025-04-02", "Buyer B", "Sales", "S-2", "29AABCU9603R1ZN", 2000, 0, 0, 360, 2360],
            ["2025-04-03", "Buyer C", "Credit Note", "CN-1", "27AABCU9603R1ZM", -500, -45, -45, 0, -590],
        ],
        sheet_names=["Sales Register"],
    )
    assert det.register_type == "sales"
    assert det.is_tally_export is True
    assert det.suggested_pipeline == "gstr1"


def test_ambiguous_when_headers_generic():
    det = detect_register_type(
        headers=["Col1", "Col2", "Col3"],
        sample_rows=[["a", "b", "c"]],
        sheet_names=["Sheet1"],
    )
    assert det.register_type == "ambiguous"
    assert det.requires_manual_choice is True


def test_inspect_register_file_purchase_sheet():
    content = _xlsx(
        [
            ["Purchase Register — April 2025"],
            [],
            [
                "Date",
                "Party's A/c Name",
                "Vch Type",
                "Vch No.",
                "GSTIN/UIN",
                "Taxable Amt",
                "CGST",
                "SGST",
                "IGST",
                "Gross Total",
            ],
            [
                "2025-04-01",
                "Vendor One",
                "Purchase",
                "P-1001",
                "27AABCU9603R1ZM",
                1000,
                90,
                90,
                0,
                1180,
            ],
            ["Grand Total", "", "", "", "", 1000, 90, 90, 0, 1180],
        ],
        sheet="Purchase Register",
    )
    det = inspect_register_file(content, "pr_tally.xlsx", expected_type="purchase")
    assert det.register_type == "purchase"
    assert det.is_tally_export is True
    assert det.suggested_pipeline == "gstr2b"


# ---------------------------------------------------------------------------
# Quirks
# ---------------------------------------------------------------------------

def test_extract_gstin_from_party_cell_variants():
    name, gstin = extract_gstin_from_party_cell("ABC Traders - 27AABCU9603R1ZM")
    assert gstin == "27AABCU9603R1ZM"
    assert name == "ABC Traders"

    name2, gstin2 = extract_gstin_from_party_cell("27AABCU9603R1ZM - XYZ Corp")
    assert gstin2 == "27AABCU9603R1ZM"
    assert name2 == "XYZ Corp"

    name3, gstin3 = extract_gstin_from_party_cell("No GSTIN Here")
    assert gstin3 is None
    assert name3 == "No GSTIN Here"


def test_parse_purchase_extracts_embedded_gstin_and_skips_grand_total():
    content = _xlsx(
        [
            [
                "Date",
                "Particulars",
                "Vch Type",
                "Vch No.",
                "Taxable Amt",
                "CGST",
                "SGST",
                "IGST",
                "Gross Total",
            ],
            [
                "2025-04-01",
                "Om Sai Enterprises - 27AAECO5678G1Z2",
                "Purchase",
                "P-01",
                1000,
                90,
                90,
                0,
                1180,
            ],
            ["Grand Total", "", "", "", 1000, 90, 90, 0, 1180],
        ],
        sheet="Tally Export",
    )
    result = parse_purchase_register(content, "tally_pr.xlsx")
    assert result["success"] is True
    assert result.get("export_profile") == "Tally Export" or result.get("source_software") == "Tally"
    assert len(result["records"]) == 1
    rec = result["records"][0]
    assert rec["gstin"] == "27AAECO5678G1Z2"
    assert "Om Sai" in (rec.get("supplier_name") or "")


def test_parse_sales_multiline_party_and_leading_zero_invoice():
    content = _xlsx(
        [
            [
                "Date",
                "Particulars",
                "Vch Type",
                "Vch No.",
                "GST Reg No",
                "Taxable Amt",
                "CGST",
                "SGST",
                "IGST",
                "Gross Total",
            ],
            [
                "2025-04-01",
                "Shree Balaji\nMumbai",
                "Sales",
                "00123",  # leading zeros — Excel may keep as text
                "27AAECS4567P1Z9",
                5000,
                450,
                450,
                0,
                5900,
            ],
        ],
        sheet="Sales Register",
    )
    result = parse_sales_register(content, "tally_sr.xlsx")
    assert result["success"] is True
    assert len(result["records"]) == 1
    rec = result["records"][0]
    assert rec["recipient_name"] == "Shree Balaji"
    # matcher.normalize_invoice strips leading zeros from numeric segments
    assert rec["invoice_number_normalized"] in ("123", "00123", "123")
    assert "123" in (rec["invoice_number_normalized"] or "")


def test_validate_tally_sales_missing_invoice_type_warns():
    issues = validate_tally_export(
        register_type="sales",
        headers=["Date", "Particulars", "Vch No.", "GSTIN/UIN", "Taxable Amt"],
        is_tally_export=True,
    )
    codes = {i["code"] for i in issues}
    assert "tally_missing_invoice_type" in codes


def test_validate_tally_purchase_missing_gstin_errors():
    issues = validate_tally_export(
        register_type="purchase",
        headers=["Date", "Particulars", "Vch No.", "Taxable Amt"],
        is_tally_export=True,
    )
    assert any(i["code"] == "tally_missing_gstin_column" and i["severity"] == "error" for i in issues)


def test_looks_like_tally_headers():
    assert looks_like_tally_headers(
        ["Date", "Particulars", "Vch Type", "Vch No.", "GSTIN/UIN", "Taxable Amt"]
    )
    assert not looks_like_tally_headers(["Foo", "Bar", "Baz"])
