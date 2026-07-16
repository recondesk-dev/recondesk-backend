"""Regression: GSTIN column must not corrupt to literal \"NAN\" / lose values.

Blank B2C cells and populated GSTIN cells commonly share one Excel column.
Pandas missing markers must become ``None``, while populated cells keep their
exact original string (upper-cased).
"""

from __future__ import annotations

import io

import pandas as pd
import pytest
from openpyxl import Workbook

from app.parsers.sales_register_parser import (
    _normalize_gstin_cell,
    _safe_cell,
    _series_as_optional_str,
    parse_sales_register,
)


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales Register"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_safe_cell_treats_pandas_nan_as_missing():
    assert _safe_cell(float("nan")) is None
    assert _safe_cell(pd.NA) is None
    assert _safe_cell("nan") is None
    assert _safe_cell("NAN") is None
    assert _safe_cell("27AAECO5678G1Z2") == "27AAECO5678G1Z2"


def test_normalize_gstin_cell_never_returns_literal_nan():
    assert _normalize_gstin_cell(float("nan")) is None
    assert _normalize_gstin_cell(None) is None
    assert _normalize_gstin_cell("") is None
    assert _normalize_gstin_cell("27aaeco5678g1z2") == "27AAECO5678G1Z2"


def test_series_as_optional_str_keeps_none_not_float_nan():
    ser = pd.Series(["27AAECO5678G1Z2", None, "07AABCN6789S1Z8", float("nan")])
    out = _series_as_optional_str(ser, _normalize_gstin_cell)
    assert out.dtype == object
    assert out.tolist() == ["27AAECO5678G1Z2", None, "07AABCN6789S1Z8", None]
    for v in out.tolist():
        assert v is None or (isinstance(v, str) and v.upper() != "NAN")


def test_mixed_gstin_column_preserves_populated_values():
    """Populated GSTINs survive; blanks stay None — never the string NAN."""
    populated = {
        "INV-B2B-001": "27AAECO5678G1Z2",
        "INV-B2B-002": "07AABCN6789S1Z8",
        "INV-B2B-003": "29AABCS2345L1Z7",
    }
    blank_invoices = {"INV-B2C-001", "INV-B2C-002"}

    rows = [
        [
            "Invoice Date",
            "Invoice No",
            "Customer Name",
            "GSTIN",
            "Place of Supply",
            "Taxable Value (₹)",
            "CGST (₹)",
            "SGST (₹)",
            "IGST (₹)",
            "Invoice Value (₹)",
        ],
        ["2025-04-01", "INV-B2B-001", "Om Sai", "27AAECO5678G1Z2", "Maharashtra", 1000, 90, 90, 0, 1180],
        ["2025-04-02", "INV-B2C-001", "Walk-in", None, "Maharashtra", 500, 45, 45, 0, 590],
        ["2025-04-03", "INV-B2B-002", "Delhi Co", "07AABCN6789S1Z8", "Delhi", 2000, 0, 0, 360, 2360],
        ["2025-04-04", "INV-B2C-002", "Cash Sale", "", "Maharashtra", 300, 27, 27, 0, 354],
        ["2025-04-05", "INV-B2B-003", "Blr Co", "29AABCS2345L1Z7", "Karnataka", 1500, 0, 0, 270, 1770],
    ]

    result = parse_sales_register(_xlsx_bytes(rows), "mixed_gstin.xlsx")
    assert result["success"] is True
    records = result["records"]
    assert len(records) == 5

    # Invoice numbers are normalised (punctuation stripped); match on GSTIN /
    # document_type instead so the assertion targets the GSTIN bug.
    by_gstin = {r["gstin"]: r for r in records if r.get("gstin")}
    for expected in populated.values():
        key = expected.upper()
        assert key in by_gstin, (
            f"populated GSTIN {expected!r} missing from parse output; "
            f"got {[r.get('gstin') for r in records]!r}"
        )
        assert by_gstin[key]["gstin"] == key

    blank_rows = [r for r in records if r.get("gstin") is None]
    assert len(blank_rows) == len(blank_invoices)
    for r in blank_rows:
        assert r["gstin"] is None
        assert r.get("document_type") == "B2C"

    # Hard invariant: no record may carry the literal pandas NaN string.
    for r in records:
        g = r.get("gstin")
        assert g is None or (isinstance(g, str) and g.upper() != "NAN")


def test_iterrows_nan_no_longer_becomes_string_nan():
    """Simulate the old bug path: float nan after DataFrame round-trip."""
    from app.parsers.sales_register_parser import _safe_cell
    from app.services.normalizer import NormalizationError, normalize_gstin

    raw = float("nan")
    cleaned = _safe_cell(raw)
    assert cleaned is None
    # Old buggy path:
    #   gstin_value = str(raw).strip().upper()  → "NAN"
    if cleaned is None:
        gstin_value = None
    else:
        try:
            gstin_value = normalize_gstin(cleaned)
        except NormalizationError:
            gstin_value = cleaned.strip().upper() or None
    assert gstin_value is None


def test_na_placeholders_normalize_to_absent_gstin():
    """NA / N/A / blank must become None — never a literal mismatch string."""
    from app.parsers.sales_register_parser import (
        _is_absent_gstin_token,
        _normalize_gstin_cell,
    )

    for raw in ("NA", "N/A", "n/a", "N.A.", "nil", "  ", None, ""):
        assert _is_absent_gstin_token(str(raw) if raw is not None else None) or raw in (
            None,
            "",
            "  ",
        )
        assert _normalize_gstin_cell(raw) is None

    assert _normalize_gstin_cell(" 27aaeco5678g1z2 ") == "27AAECO5678G1Z2"


def test_tally_gst_reg_no_column_is_mapped():
    """Tally 'GST Reg No' header must map to gstin (root cause of messy 1/8)."""
    import pandas as pd
    from app.parsers.sales_register_parser import detect_column_mapping

    df = pd.DataFrame(
        columns=[
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
        ]
    )
    mapping = detect_column_mapping(df)
    assert mapping.get("gstin") == "GST Reg No"
    assert mapping.get("invoice_number") == "Vch No."
    assert mapping.get("recipient_name") == "Particulars"
    assert mapping.get("total_amount") == "Gross Total"


def test_messy_sales_register_normalizes_gstin_dates_amounts_invoices():
    """Mixed formats from the stress-test Sales Register must parse cleanly."""
    rows = [
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
        # slash invoice, datetime date, clean GSTIN, ₹ taxable
        [
            "2026-04-01 00:00:00",
            "Shree Balaji",
            "Sales",
            "RD/2026-27/3001",
            "27AAECS4567P1Z9",
            "₹117,882.04",
            7072.92,
            7072.92,
            0,
            132027.88,
        ],
        # dash invoice, DD/MM/YYYY, whitespace GSTIN
        [
            "24/06/2026",
            "Om Enterprises",
            "Sales",
            "RD-3002",
            " 27AAGFO7890Q1Z3 ",
            44242.48,
            1106.06,
            1106.06,
            0,
            46454.6,
        ],
        # bare number invoice, DD-MM-YY, lowercase GSTIN
        [
            "07-07-26",
            "Kavya Textiles",
            "Sales",
            "3003",
            "24aabck3456r1z7",
            152381.03,
            0,
            0,
            7619.05,
            160000.08,
        ],
        # DD.MM.YYYY + N/A GSTIN (B2C)
        [
            "15.04.2026",
            "Cash Sale",
            "Sales",
            "RD-3008",
            "N/A",
            "₹123,656.03",
            11129.05,
            11129.05,
            0,
            145914.13,
        ],
        # NA GSTIN
        [
            "12/05/2026",
            "Walk-in",
            "Sales",
            "3015",
            "NA",
            128488.59,
            0,
            0,
            0,
            128488.59,
        ],
    ]

    result = parse_sales_register(_xlsx_bytes(rows), "messy_sr.xlsx")
    assert result["success"] is True
    assert result.get("detected_columns", {}).get("gstin") == "GST Reg No"
    records = result["records"]
    assert len(records) == 5

    by_inv = {r["invoice_number_normalized"]: r for r in records}

    r1 = by_inv["RD2026273001"]
    assert r1["gstin"] == "27AAECS4567P1Z9"
    assert r1["invoice_date"] == "2026-04-01"
    assert r1["taxable_amount_paise"] == 11788204
    assert r1["invoice_type"] == "B2B"

    r2 = by_inv["RD3002"]
    assert r2["gstin"] == "27AAGFO7890Q1Z3"
    assert r2["invoice_date"] == "2026-06-24"

    r3 = by_inv["3003"]
    assert r3["gstin"] == "24AABCK3456R1Z7"
    assert r3["invoice_date"] == "2026-07-07"

    r8 = by_inv["RD3008"]
    assert r8["gstin"] is None
    assert r8["invoice_date"] == "2026-04-15"
    assert r8["taxable_amount_paise"] == 12365603
    assert r8["invoice_type"] == "B2C"

    r15 = by_inv["3015"]
    assert r15["gstin"] is None
    assert r15["invoice_type"] == "B2C"


def test_matcher_treats_na_gstin_as_both_absent():
    """NA on SR + blank on GSTR-1 must pass the identity gate (B2C/B2CL)."""
    from app.matching.generic_matcher import (
        SALES_MATCH_CONFIG,
        _gstin_both_absent,
        _gstin_identity_ok,
        generic_match_pair,
    )

    sr = {
        "gstin": "N/A",
        "recipient_name": "Cash",
        "invoice_number": "RD2026273010",
        "invoice_number_normalized": "RD2026273010",
        "invoice_date": "2026-04-10",
        "taxable_amount_paise": 28813559,
        "igst_paise": 5186441,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": 5186441,
    }
    g1 = {
        "recipient_gstin": None,
        "recipient_name": "",
        "invoice_number": "RD2026273010",
        "invoice_number_normalized": "RD2026273010",
        "invoice_date": "2026-04-10",
        "taxable_amount_paise": 28813559,
        "igst_paise": 5186441,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": 5186441,
    }
    assert _gstin_both_absent(sr, g1, SALES_MATCH_CONFIG)
    assert _gstin_identity_ok(sr, g1, SALES_MATCH_CONFIG)
    r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert r.matched is True
    assert r.level <= 2
