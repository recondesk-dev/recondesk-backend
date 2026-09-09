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


