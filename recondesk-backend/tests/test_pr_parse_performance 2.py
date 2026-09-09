"""Performance guards for multi-sheet Purchase Register parsing at real scale."""

from __future__ import annotations

import io
import time

import pandas as pd
import pytest

from app.parsers.purchase_register_parser import (
    _find_best_header_from_raw,
    list_candidate_pr_sheet_names,
    parse_purchase_register,
)


def _xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


def _large_sheet(n: int, inv_col: str, prefix: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["01-04-2026"] * n,
            "GSTIN": [f"27AABCU9603R1Z{i % 10}" for i in range(n)],
            inv_col: [f"{prefix}-{i:05d}" for i in range(n)],
            "Taxable Value": [1000.0 + i for i in range(n)],
            "Central Tax": [90.0] * n,
            "State Tax": [90.0] * n,
            "Integrated Tax": [0.0] * n,
        }
    )


def test_header_detect_does_not_copy_body_per_candidate(monkeypatch):
    """Regression: scanning header rows must not slice/copy the full body each time."""
    n = 3000
    # Leading junk rows so the real header is not row 0.
    junk = pd.DataFrame([[f"x{c}" for c in range(7)] for _ in range(5)])
    body = _large_sheet(n, "Vch No.", "VCH")
    raw = pd.concat([junk, pd.DataFrame([list(body.columns)]), body], ignore_index=True)

    copy_calls = {"n": 0}
    orig_copy = pd.DataFrame.copy

    def counting_copy(self, *args, **kwargs):
        # Only count copies of the large body-sized frames.
        if len(self) >= n:
            copy_calls["n"] += 1
        return orig_copy(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "copy", counting_copy)
    best_df, mapping, header_row = _find_best_header_from_raw(raw, max_rows=20)
    assert mapping is not None
    assert "invoice_number" in mapping
    assert header_row >= 5
    assert best_df is not None and len(best_df) == n
    # One intentional body copy for the winning header (reset_index may add a
    # second). Must not scale with max_rows (old bug: ~20 full-sheet copies).
    assert copy_calls["n"] <= 2, (
        f"expected ≤2 body copies for winning header, got {copy_calls['n']}"
    )
    assert copy_calls["n"] < 10


def test_three_sheet_5k_parse_completes_quickly():
    """3 sheets × ~2k rows must parse well under the soft timeout."""
    sheets = {
        "Tally Export": _large_sheet(2200, "Vch No.", "VCH"),
        "Busy Export": _large_sheet(1800, "Bill No", "BILL"),
        "Manual Excel": _large_sheet(1600, "Invoice Number", "INV"),
    }
    raw = _xlsx_bytes(sheets)
    assert len(list_candidate_pr_sheet_names(raw, "big.xlsx")) == 3

    t0 = time.perf_counter()
    result = parse_purchase_register(raw, "big.xlsx")
    elapsed = time.perf_counter() - t0

    assert result["success"] is True
    assert len(result["records"]) == 5600
    assert int(result.get("missing_invoice_number_count") or 0) == 0
    # Generous CI bound — locally this is typically < 2s.
    assert elapsed < 30.0, f"parse took {elapsed:.1f}s (expected < 30s)"
