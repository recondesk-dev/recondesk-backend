"""Tests for GSTR-2B Excel adapter (alt flat schema sheets)."""

from __future__ import annotations

import json
from pathlib import Path

from app.parsers.gstr2b_excel import (
    excel_to_alt_2b_dict,
    load_gstr2b_upload_payload,
    parse_2b_excel,
)
from app.parsers.gstr2b_parser import normalize_alt_2b_schema, parse_gstr2b

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "test_fixtures" / "sandbox"
_JSON = _FIXTURE_DIR / "sample_alt_gstr2b.json"
_XLSX = _FIXTURE_DIR / "sample_alt_gstr2b.xlsx"


def _canonical_portal_root(payload: dict) -> dict:
    """Normalize for comparison: drop source meta, sort suppliers by ctin."""
    root = payload["data"]
    out = {
        "gstin": root["gstin"],
        "rtnprd": root["rtnprd"],
        "b2b": sorted(root.get("b2b") or [], key=lambda s: s.get("ctin") or ""),
    }
    if root.get("cdnr"):
        out["cdnr"] = sorted(root["cdnr"], key=lambda s: s.get("ctin") or "")
    return out


def test_parse_2b_excel_matches_alt_json_normalizer():
    json_payload = json.loads(_JSON.read_text(encoding="utf-8"))
    # Excel title supplies gstin; strip top-level for apples-to-apples on mapping,
    # then re-apply fixture gstin so both paths share the same buyer.
    expected = normalize_alt_2b_schema(json_payload)

    xlsx_bytes = _XLSX.read_bytes()
    from_excel = parse_2b_excel(xlsx_bytes, "sample_alt_gstr2b.xlsx")

    assert _canonical_portal_root(from_excel) == _canonical_portal_root(expected)
    assert from_excel["_alt_buyer_gstin_source"] in {"file", "client"}


def test_excel_to_alt_extracts_title_gstin_and_skips_blank_sr():
    alt = excel_to_alt_2b_dict(_XLSX.read_bytes(), "sample_alt_gstr2b.xlsx")
    assert alt["gstin"] == "27ARLPM8253B1ZO"
    assert len(alt["invoice"]) == 3  # includes totals row; normalizer skips it
    blank_sr = [r for r in alt["invoice"] if not str(r.get("Sr") or "").strip()]
    assert len(blank_sr) == 1

    normalized = normalize_alt_2b_schema(alt)
    inums = [inv["inum"] for s in normalized["data"]["b2b"] for inv in s["inv"]]
    assert inums == ["SLA243379976690", "TSC/FY26-27/997"]


def test_parse_gstr2b_end_to_end_from_excel_bytes():
    portal = parse_2b_excel(_XLSX.read_bytes(), "sample_alt_gstr2b.xlsx")
    result = parse_gstr2b(portal)
    assert result["total_parsed"] == 3
    assert result["buyer_gstin"] == "27ARLPM8253B1ZO"
    invoices = [r for r in result["records"] if r["doc_type"] == "INVOICE"]
    assert {r["invoice_number_raw"] for r in invoices} == {
        "SLA243379976690",
        "TSC/FY26-27/997",
    }


def test_excel_detects_isd_impg_sheets_without_parsing():
    import io

    import pandas as pd

    from app.parsers.gstr2b_parser import (
        _UNPARSED_IMPG_COUNT_KEY,
        _UNPARSED_ISD_COUNT_KEY,
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Sr": 1,
                    "GSTIN": "27AABCT1332L1ZV",
                    "Invoice No": "INV-1",
                    "Invoice Date": "01-Apr-24",
                    "Taxable Value": 1000,
                    "Integrated Tax": 180,
                }
            ]
        ).to_excel(writer, sheet_name="invoice", index=False)
        pd.DataFrame(
            [
                {"Doc No": "ISD-1", "Amount": 100},
                {"Doc No": "ISD-2", "Amount": 200},
            ]
        ).to_excel(writer, sheet_name="ISD", index=False)
        pd.DataFrame(
            [{"BoE": "1234567", "IGST": 500}]
        ).to_excel(writer, sheet_name="IMPG", index=False)
    raw = buf.getvalue()

    alt = excel_to_alt_2b_dict(raw, "mixed.xlsx")
    assert alt[_UNPARSED_ISD_COUNT_KEY] == 2
    assert alt[_UNPARSED_IMPG_COUNT_KEY] == 1

    portal = parse_2b_excel(raw, "mixed.xlsx", fallback_period="2024-04")
    result = parse_gstr2b(portal, fallback_period="2024-04")
    assert result["isd_count"] == 2
    assert result["impg_count"] == 1
    assert result["isd_present"] is True
    assert result["impg_present"] is True
    assert result["total_parsed"] >= 1


def test_gstr2b_excel_handles_gstn_portal_headers_without_sr_column():
    """GSTN portal GSTR-2B Excel downloads use sheet names like 'B2B', 'B2B-CDNR' and column headers
    like 'GSTIN of Supplier', 'Trade/Legal Name of Supplier', 'Invoice Number', etc. without an 'Sr' column.
    """
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "27AABCT1332L1ZV",
                    "Trade/Legal Name of Supplier": "MAHARASHTRA LOGISTICS",
                    "Invoice Number": "INV-2026-001",
                    "Invoice Date": "15-06-2026",
                    "Invoice Value": 11800.0,
                    "Taxable Value": 10000.0,
                    "Integrated Tax": 0.0,
                    "Central Tax": 900.0,
                    "State/UT Tax": 900.0,
                    "Reverse Charge": "Y",
                }
            ]
        ).to_excel(writer, sheet_name="B2B", index=False)
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "27AABCT1332L1ZV",
                    "Trade/Legal Name of Supplier": "MAHARASHTRA LOGISTICS",
                    "Document Number": "CN-2026-001",
                    "Document Date": "20-06-2026",
                    "Document Type": "Credit Note",
                    "Taxable Value": 1000.0,
                    "Central Tax": 90.0,
                    "State/UT Tax": 90.0,
                }
            ]
        ).to_excel(writer, sheet_name="B2B-CDNR", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "GSTR2B_27ISKPK1273H1ZF_2026-06.xlsx", fallback_buyer_gstin="27ISKPK1273H1ZF")
    result = parse_gstr2b(portal)

    assert result["total_parsed"] == 2
    assert result["total_skipped"] == 0
    records = result["records"]
    inv = next(r for r in records if r["doc_type"] == "INVOICE")
    assert inv["supplier_gstin"] == "27AABCT1332L1ZV"
    assert inv["invoice_number_raw"] == "INV-2026-001"
    assert inv["reverse_charge"] is True
    cn = next(r for r in records if r["doc_type"] == "CREDIT_NOTE")
    assert cn["invoice_number_raw"] == "CN-2026-001"


def test_gstr2b_excel_existing_invoice_sheet():
    """Existing 'invoice' sheet name is handled by the named-sheet path."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Sr": 1,
                    "GSTIN": "27AABCT1332L1ZV",
                    "Party": "SUPPLIER ONE",
                    "Invoice No": "INV-001",
                    "Invoice Date": "10-09-2026",
                    "Taxable Value": 5000.0,
                    "Integrated Tax": 900.0,
                }
            ]
        ).to_excel(writer, sheet_name="invoice", index=False)

    raw = buf.getvalue()
    alt = excel_to_alt_2b_dict(raw, "invoice_test.xlsx")
    assert len(alt["invoice"]) == 1
    assert alt["invoice"][0]["Invoice No"] == "INV-001"

    portal = parse_2b_excel(
        raw,
        "invoice_test.xlsx",
        fallback_buyer_gstin="27ISKPK1273H1ZF",
        fallback_period="2026-09",
    )
    result = parse_gstr2b(portal)
    assert result["total_parsed"] == 1
    assert result["records"][0]["invoice_number_raw"] == "INV-001"


def test_gstr2b_excel_existing_b2b_sheet():
    """Existing 'b2b' sheet name is handled by the named-sheet path."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "27AABCT1332L1ZV",
                    "Trade/Legal Name of Supplier": "SUPPLIER ONE",
                    "Invoice Number": "INV-002",
                    "Invoice Date": "12-09-2026",
                    "Taxable Value": 4000.0,
                    "Central Tax": 360.0,
                    "State/UT Tax": 360.0,
                }
            ]
        ).to_excel(writer, sheet_name="b2b", index=False)

    raw = buf.getvalue()
    alt = excel_to_alt_2b_dict(raw, "b2b_test.xlsx")
    assert len(alt["invoice"]) == 1

    portal = parse_2b_excel(
        raw,
        "b2b_test.xlsx",
        fallback_buyer_gstin="27ISKPK1273H1ZF",
        fallback_period="2026-09",
    )
    result = parse_gstr2b(portal)
    assert result["total_parsed"] == 1
    assert result["records"][0]["invoice_number_raw"] == "INV-002"


def test_gstr2b_excel_data_on_gstr2b_sheet():
    """GSTR-2B data on sheet named 'GSTR-2B' is detected and parsed via content fallback."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "27AABCT1332L1ZV",
                    "Trade/Legal Name of Supplier": "SUPPLIER GSTR2B",
                    "Invoice Number": "INV-2B-100",
                    "Invoice Date": "15-09-2026",
                    "Invoice Value": 1180.0,
                    "Taxable Value": 1000.0,
                    "Central Tax": 90.0,
                    "State/UT Tax": 90.0,
                }
            ]
        ).to_excel(writer, sheet_name="GSTR-2B", index=False)

    raw = buf.getvalue()
    alt = excel_to_alt_2b_dict(raw, "GSTR2B_2026-09.xlsx")
    assert len(alt["invoice"]) == 1
    assert alt["invoice"][0]["Invoice Number"] == "INV-2B-100"

    portal = parse_2b_excel(
        raw,
        "GSTR2B_2026-09.xlsx",
        fallback_buyer_gstin="27ISKPK1273H1ZF",
        fallback_period="2026-09",
    )
    result = parse_gstr2b(portal)
    assert result["total_parsed"] == 1
    assert result["records"][0]["invoice_number_raw"] == "INV-2B-100"
    assert result["records"][0]["supplier_gstin"] == "27AABCT1332L1ZV"


def test_gstr2b_excel_data_on_sheet1():
    """GSTR-2B data on generic sheet named 'Sheet1' is detected by content and parsed."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "27AABCT1332L1ZV",
                    "Trade/Legal Name of Supplier": "SUPPLIER SHEET1",
                    "Invoice Number": "INV-S1-999",
                    "Invoice Date": "18-09-2026",
                    "Invoice Value": 2360.0,
                    "Taxable Value": 2000.0,
                    "Central Tax": 180.0,
                    "State/UT Tax": 180.0,
                }
            ]
        ).to_excel(writer, sheet_name="Sheet1", index=False)

    raw = buf.getvalue()
    alt = excel_to_alt_2b_dict(raw, "sheet1_test.xlsx")
    assert len(alt["invoice"]) == 1
    assert alt["invoice"][0]["Invoice Number"] == "INV-S1-999"

    portal = parse_2b_excel(
        raw,
        "sheet1_test.xlsx",
        fallback_buyer_gstin="27ISKPK1273H1ZF",
        fallback_period="2026-09",
    )
    result = parse_gstr2b(portal)
    assert result["total_parsed"] == 1
    assert result["records"][0]["invoice_number_raw"] == "INV-S1-999"
    assert result["records"][0]["taxable_value_paise"] == 200000


def test_gstr2b_excel_workbook_with_no_valid_gstr2b_sheet():
    """Workbook with no valid GSTR-2B sheet (e.g. employee roster or random numbers) raises ValueError."""
    import io
    import pandas as pd
    import pytest

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {"Employee ID": 101, "Full Name": "Jane Doe", "Department": "Finance", "Salary": 85000},
                {"Employee ID": 102, "Full Name": "John Smith", "Department": "Engineering", "Salary": 92000},
            ]
        ).to_excel(writer, sheet_name="Sheet1", index=False)

    raw = buf.getvalue()
    with pytest.raises(ValueError, match="gstr2b_excel_no_invoice_sheet"):
        excel_to_alt_2b_dict(raw, "employees.xlsx")

    with pytest.raises(ValueError, match="gstr2b_excel_no_invoice_sheet"):
        parse_2b_excel(raw, "employees.xlsx")


def test_gstr2b_excel_purchase_register_accidentally_supplied():
    """Purchase Register accidentally supplied as GSTR-2B must NOT be accepted as GSTR-2B."""
    import io
    import pandas as pd
    import pytest

    # Case A: Sheet named 'Purchase Register' with PR headers
    buf_a = io.BytesIO()
    with pd.ExcelWriter(buf_a, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Supplier Name": "VENDOR A",
                    "Invoice No": "PR-INV-001",
                    "Invoice Date": "05-09-2026",
                    "Invoice Value": 1180.0,
                    "Taxable Value": 1000.0,
                    "Central Tax": 90.0,
                    "State Tax": 90.0,
                    "ITC Eligibility": "Eligible",
                }
            ]
        ).to_excel(writer, sheet_name="Purchase Register", index=False)

    raw_a = buf_a.getvalue()
    with pytest.raises(ValueError, match="gstr2b_excel_no_invoice_sheet"):
        excel_to_alt_2b_dict(raw_a, "purchase_register.xlsx")

    with pytest.raises(ValueError, match="gstr2b_excel_no_invoice_sheet"):
        parse_2b_excel(raw_a, "purchase_register.xlsx")

    # Case B: Sheet named 'Sheet1' but containing PR accounting columns (Voucher No, ITC Eligibility)
    buf_b = io.BytesIO()
    with pd.ExcelWriter(buf_b, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Party Name": "VENDOR B",
                    "Voucher No": "VCH-100",
                    "Invoice No": "INV-100",
                    "Invoice Date": "06-09-2026",
                    "Taxable Value": 5000.0,
                    "Integrated Tax": 900.0,
                    "ITC Eligibility": "Ineligible",
                }
            ]
        ).to_excel(writer, sheet_name="Sheet1", index=False)

    raw_b = buf_b.getvalue()
    with pytest.raises(ValueError, match="gstr2b_excel_no_invoice_sheet"):
        excel_to_alt_2b_dict(raw_b, "pr_sheet1.xlsx")

    # Case C: Real PR file if present in Downloads
    from pathlib import Path
    downloads_pr = Path("/Users/omkarkadam/Downloads/PurchaseRegister_27ISKPK1273H1ZF_Sep2026.xlsx")
    if downloads_pr.exists():
        try:
            real_pr_bytes = downloads_pr.read_bytes()
            with pytest.raises(ValueError, match="gstr2b_excel_no_invoice_sheet"):
                excel_to_alt_2b_dict(real_pr_bytes, downloads_pr.name)
        except PermissionError:
            pass  # Sandbox environment without access to user Downloads


def test_gstr2b_excel_normalizes_taxable_amount_and_aliases():
    """Verify that 'Taxable Amount', 'Invoice Amount', and '*_amount' aliases are correctly recognized."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Invoice Number": "INV-TXAMT-01",
                    "Invoice Date": "10-08-2026",
                    "Taxable Amount": 50000.0,
                    "IGST Amount": 9000.0,
                    "Invoice Amount": 59000.0,
                },
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Invoice Number": "INV-TXAMT-02",
                    "Invoice Date": "11-08-2026",
                    "Taxable Amt": 20000.0,
                    "CGST Amount": 1800.0,
                    "SGST Amount": 1800.0,
                    "Total Amount": 23600.0,
                },
            ]
        ).to_excel(writer, sheet_name="invoice", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "taxable_amount_test.xlsx", fallback_period="2026-08")
    result = parse_gstr2b(portal, fallback_period="2026-08")

    assert result["total_parsed"] == 2
    rec1 = next(r for r in result["records"] if r["invoice_number_raw"] == "INV-TXAMT-01")
    assert rec1["taxable_value_paise"] == 5000000
    assert rec1["taxable_value"] == 50000
    assert rec1["igst_paise"] == 900000
    assert rec1["invoice_value_paise"] == 5900000

    rec2 = next(r for r in result["records"] if r["invoice_number_raw"] == "INV-TXAMT-02")
    assert rec2["taxable_value_paise"] == 2000000
    assert rec2["taxable_value"] == 20000
    assert rec2["cgst_paise"] == 180000
    assert rec2["sgst_paise"] == 180000
    assert rec2["invoice_value_paise"] == 2360000


def test_gstr2b_excel_derives_invoice_value_when_absent():
    """Verify that when 'Invoice Value' is absent/zero, it is derived from taxable value + tax components."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Invoice Number": "INV-DERIVED-01",
                    "Invoice Date": "15-08-2026",
                    "Taxable Amount": 10000.0,
                    "CGST": 900.0,
                    "SGST": 900.0,
                    # No Invoice Value column at all!
                },
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Invoice Number": "INV-DERIVED-02",
                    "Invoice Date": "16-08-2026",
                    "Taxable Value": 15000.0,
                    "IGST": 2700.0,
                    "Cess": 150.0,
                    "Invoice Value": 0.0,  # Explicit 0.0 value
                },
            ]
        ).to_excel(writer, sheet_name="invoice", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "derived_val_test.xlsx", fallback_period="2026-08")
    result = parse_gstr2b(portal, fallback_period="2026-08")

    assert result["total_parsed"] == 2
    rec1 = next(r for r in result["records"] if r["invoice_number_raw"] == "INV-DERIVED-01")
    assert rec1["taxable_value_paise"] == 1000000
    assert rec1["invoice_value_paise"] == 1180000  # 10000 + 900 + 900 = 11800 -> 1180000 paise

    rec2 = next(r for r in result["records"] if r["invoice_number_raw"] == "INV-DERIVED-02")
    assert rec2["taxable_value_paise"] == 1500000
    assert rec2["invoice_value_paise"] == 1785000  # 15000 + 2700 + 150 = 17850 -> 1785000 paise


def test_gstr2b_excel_note_rows_normalize_taxable_amount_and_derive_val():
    """Verify that credit/debit note rows normalize 'Taxable Amount' and derive note value when absent."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Document Number": "INV-BASE-01",
                    "Document Date": "01-08-2026",
                    "Taxable Amount": 5000.0,
                    "IGST": 900.0,
                }
            ]
        ).to_excel(writer, sheet_name="invoice", index=False)
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "27AABCT1332L1ZV",
                    "Note Number": "CN-2026-001",
                    "Note Type": "Credit",
                    "Note Date": "20-08-2026",
                    "Taxable Amount": 2000.0,
                    "Integrated Tax Amount": 360.0,
                    # No Note Value column
                }
            ]
        ).to_excel(writer, sheet_name="note", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "note_taxable_amount_test.xlsx", fallback_period="2026-08")
    result = parse_gstr2b(portal, fallback_period="2026-08")

    assert result["total_parsed"] == 2
    notes = [r for r in result["records"] if r.get("doc_type") in ("CREDIT_NOTE", "DEBIT_NOTE", "CR")]
    assert len(notes) == 1
    cn = notes[0]
    assert cn["taxable_value_paise"] == 200000
    assert cn["taxable_value"] == 2000
    assert cn["igst_paise"] == 36000
    assert cn["invoice_value_paise"] == 236000  # 2000 + 360 = 2360 -> 236000 paise


def test_gstr2b_excel_with_gstin_uin_header_and_currency_symbols():
    """Verify GST portal Excel exports with 'GSTIN/UIN' and currency symbols in headers parse cleanly."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN/UIN": "27AABCT1332L1ZV",
                    "Trade/Legal name": "Acme Industrial Supplies",
                    "Invoice number": "INV/2026/089",
                    "Invoice Date": "14-05-2026",
                    "Invoice Value(₹)": 11800.0,
                    "Taxable Value (₹)": 10000.0,
                    "Integrated Tax(₹)": 0.0,
                    "Central Tax(₹)": 900.0,
                    "State/UT Tax(₹)": 900.0,
                },
                {
                    "GSTIN/UIN": "29ABCDE1234F1Z5",
                    "Trade/Legal name": "Southern Tech Corp",
                    "Invoice number": "ST-9988",
                    "Invoice Date": "18-05-2026",
                    "Invoice Value(₹)": 5900.0,
                    "Taxable Value (₹)": 5000.0,
                    "Integrated Tax(₹)": 900.0,
                    "Central Tax(₹)": 0.0,
                    "State/UT Tax(₹)": 0.0,
                },
            ]
        ).to_excel(writer, sheet_name="B2B", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "gstr2b_gstin_uin.xlsx", fallback_period="2026-05")
    result = parse_gstr2b(portal, fallback_period="2026-05")

    assert result["total_parsed"] == 2
    assert result["total_skipped"] == 0
    invoices = result["records"]
    assert {inv["invoice_number_raw"] for inv in invoices} == {"INV/2026/089", "ST-9988"}
    assert {inv["supplier_gstin"] for inv in invoices} == {"27AABCT1332L1ZV", "29ABCDE1234F1Z5"}
    assert invoices[0]["taxable_value"] in (10000.0, 5000.0)


def test_gstr2b_excel_leading_zero_stripped_gstin_repaired():
    """Verify that state code 01-09 stripped to 14 chars by Excel number export is repaired."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "7AAAAA0000A1Z5",  # 14 chars, stripped leading 0 of Delhi (07)
                    "Invoice Number": "DEL-INV-01",
                    "Invoice Date": "01-06-2026",
                    "Taxable Value": 2500.0,
                    "Integrated Tax": 450.0,
                }
            ]
        ).to_excel(writer, sheet_name="invoice", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "stripped_gstin.xlsx", fallback_period="2026-06")
    result = parse_gstr2b(portal, fallback_period="2026-06")

    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 0
    assert result["records"][0]["supplier_gstin"] == "07AAAAA0000A1Z5"
    assert result["records"][0]["gstin_format_invalid"] is False


def test_gstr2b_excel_corrupted_gstin_retained_in_records():
    """Verify that invoices with corrupted GSTIN are retained (not skipped) with gstin_format_invalid=True."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "UNKNOWN",
                    "Invoice Number": "CORRUPT-INV-01",
                    "Invoice Date": "10-06-2026",
                    "Taxable Value": 3000.0,
                    "Integrated Tax": 540.0,
                }
            ]
        ).to_excel(writer, sheet_name="invoice", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "corrupt_gstin.xlsx", fallback_period="2026-06")
    result = parse_gstr2b(portal, fallback_period="2026-06")

    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 0
    rec = result["records"][0]
    assert rec["invoice_number_raw"] == "CORRUPT-INV-01"
    assert rec["gstin_format_invalid"] is True


def test_gstr2b_excel_currency_headers_and_derived_taxable_value():
    """Verify headers with (Rs) currency indicators and missing Taxable Value derive txval = val - tax."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "06JBUTK7684P6ZA",
                    "Trade/Legal Name": "QSWUKZ SERVICES",
                    "Invoice Number": "INV1894/274/25-26",
                    "Invoice Date": "11-03-2025",
                    "Invoice Value (Rs)": 812583.39,
                    "Place of Supply": "06-Haryana",
                    "Reverse Charge": "N",
                    "Integrated Tax (Rs)": 87062.51,
                    "Central Tax (Rs)": 0.0,
                    "State/UT Tax (Rs)": 0.0,
                    "Cess (Rs)": 0.0,
                    "ITC Availability": "Yes",
                    "Reason if ITC N/A": "",
                }
            ]
        ).to_excel(writer, sheet_name="B2B", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "2b_currency.xlsx", fallback_period="2025-03")
    result = parse_gstr2b(portal, fallback_period="2025-03")

    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 0
    rec = result["records"][0]
    assert rec["invoice_number_raw"] == "INV1894/274/25-26"
    assert rec["supplier_gstin"] == "06JBUTK7684P6ZA"
    assert rec["supplier_name"] == "QSWUKZ SERVICES"
    assert rec["invoice_value_paise"] == 81258339
    assert rec["taxable_value_paise"] == 72552088
    assert rec["igst_paise"] == 8706251
    assert rec["cgst_paise"] == 0
    assert rec["sgst_paise"] == 0
    assert rec["itc_available"] is True


def test_gstr2b_excel_derived_total_value_and_sgst_matching():
    """Verify headers with (₹) currency indicators, SGST matching, and derived total value."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "GSTIN of Supplier": "27AABCT1332L1ZV",
                    "Trade/Legal Name": "LOCAL VENDOR",
                    "Invoice Number": "INV-LOCAL-001",
                    "Invoice Date": "15-03-2025",
                    "Taxable Value (₹)": 100000.0,
                    "Place of Supply": "27-Maharashtra",
                    "Central Tax (₹)": 9000.0,
                    "State/UT Tax (₹)": 9000.0,
                }
            ]
        ).to_excel(writer, sheet_name="B2B", index=False)

    raw = buf.getvalue()
    portal = parse_2b_excel(raw, "2b_sgst.xlsx", fallback_period="2025-03")
    result = parse_gstr2b(portal, fallback_period="2025-03")

    assert result["total_parsed"] == 1
    rec = result["records"][0]
    assert rec["taxable_value_paise"] == 10000000
    assert rec["cgst_paise"] == 900000
    assert rec["sgst_paise"] == 900000
    assert rec["invoice_value_paise"] == 11800000


def test_gstr2b_excel_synthetic_16char_gstin_and_metadata_sheet():
    """Verify that benchmark exports with 16-char synthetic GSTINs and Metadata sheet parse cleanly."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "Supplier GSTIN": "27TESTX00001A1Z1",
                    "Supplier Name": "Supplier 0001",
                    "Invoice No": "INV-0001",
                    "Invoice Date": "2026-05-20",
                    "Taxable Value": 50000.0,
                    "Integrated Tax": 0.0,
                    "Central Tax": 3000.0,
                    "State Tax": 3000.0,
                    "Invoice Value": 56000.0,
                }
            ]
        ).to_excel(writer, sheet_name="GSTR-2B", index=False)
        pd.DataFrame(
            [
                {"Field": "Recipient GSTIN", "Value": "27ISKPK1273H1ZF"},
                {"Field": "Return Period", "Value": "05-2026"},
            ]
        ).to_excel(writer, sheet_name="Metadata", index=False)

    raw = buf.getvalue()
    payload = load_gstr2b_upload_payload(raw, "GSTR2B_2000_Invoices_27ISKPK1273H1ZF_May2026.xlsx")
    assert payload["data"]["gstin"] == "27ISKPK1273H1ZF"
    assert payload["data"]["rtnprd"] == "052026"

    result = parse_gstr2b(payload)
    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 0
    rec = result["records"][0]
    assert rec["supplier_gstin"] == "27TESTX00001A1Z1"
    assert rec["gstin_format_invalid"] is True
    assert rec["invoice_number_raw"] == "INV-0001"


def test_consolidated_period_range_in_title_extracts_end_month():
    """Verify ranges like 'Consolidated Apr-Sep 2026' or 'Apr–Sep 2026' resolve to the end month (092026)."""
    from app.parsers.gstr2b_parser import _alt_parse_period_to_rtnprd
    assert _alt_parse_period_to_rtnprd("Return Period: Consolidated Apr-Sep 2026") == "092026"
    assert _alt_parse_period_to_rtnprd("Synthetic period: Apr–Sep 2026") == "092026"
    assert _alt_parse_period_to_rtnprd("April 2026 - September 2026") == "092026"
    assert _alt_parse_period_to_rtnprd("Q2 (Jul-Sep 2026)") == "092026"


def test_multi_period_rows_respect_fallback_period():
    """When an export has mixed/multi-period rows, the user's explicit fallback_period takes precedence."""
    from app.parsers.gstr2b_parser import normalize_alt_2b_schema
    payload = {
        "invoice": [
            {"Sr": 1, "GSTIN": "27AACCV1726H1ZE", "Period": "072026", "Invoice No": "INV-1", "Invoice Date": "15-07-2026", "Invoice Value": 1000.0, "Taxable Value": 1000.0, "IGST": 180.0},
            {"Sr": 2, "GSTIN": "27AACCV1726H1ZE", "Period": "072026", "Invoice No": "INV-2", "Invoice Date": "16-07-2026", "Invoice Value": 1000.0, "Taxable Value": 1000.0, "IGST": 180.0},
            {"Sr": 3, "GSTIN": "27AACCV1726H1ZE", "Period": "092026", "Invoice No": "INV-3", "Invoice Date": "15-09-2026", "Invoice Value": 1000.0, "Taxable Value": 1000.0, "IGST": 180.0},
        ]
    }
    normalized = normalize_alt_2b_schema(payload, fallback_period="2026-09")
    assert normalized["data"]["rtnprd"] == "092026"








