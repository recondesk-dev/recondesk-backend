"""Tests for GSTR-2B Excel adapter (alt flat schema sheets)."""

from __future__ import annotations

import json
from pathlib import Path

from app.parsers.gstr2b_excel import (
    excel_to_alt_2b_dict,
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



