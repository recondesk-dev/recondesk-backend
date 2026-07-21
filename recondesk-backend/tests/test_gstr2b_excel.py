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
