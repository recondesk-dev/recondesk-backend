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
