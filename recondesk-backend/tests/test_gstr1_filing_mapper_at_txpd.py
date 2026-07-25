"""GSTR-1 AT/TXPD — external-input envelope (no SR Save path)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.filing.gstr1_external_input import TABLE_AT, TABLE_TXPD
from app.filing.gstr1_filing_mapper import map_sales_register_to_gstr1_at_txpd
from app.parsers.sales_register_parser import parse_sales_register


PERIOD = "2025-04"
SAMPLE_SR = (
    Path(__file__).resolve().parent
    / "sample_gstr1_3b_test"
    / "Sales_Register_Sample_Corrected.xlsx"
)


def test_no_advance_rows_omits_cleanly():
    result = map_sales_register_to_gstr1_at_txpd(
        [{
            "invoice_type": "B2B",
            "invoice_type_raw": "Tax Invoice",
            "place_of_supply": "27-Maharashtra",
            "taxable_amount_paise": 100_000,
            "tax_rate": 18.0,
        }],
        filing_period=PERIOD,
    )
    assert result.advance_line_count == 0
    assert result.at is None
    assert result.txpd is None
    assert result.needs_external_input == []
    assert result.blocked_by_external_input is False


def test_any_advances_row_flags_external_input_never_saves():
    result = map_sales_register_to_gstr1_at_txpd(
        [{
            "invoice_type": "ADVANCES",
            "invoice_type_raw": "Advance",
            "place_of_supply": "27-Maharashtra",
            "taxable_amount_paise": 50_000,
            "tax_rate": 18.0,
            "igst_paise": 0,
            "cgst_paise": 4_500,
            "sgst_paise": 4_500,
        }],
        filing_period=PERIOD,
    )
    assert result.advance_line_count == 1
    assert result.at is None
    assert result.txpd is None
    assert result.blocked_by_external_input is True
    tables = {g.table for g in result.needs_external_input}
    assert tables == {TABLE_AT, TABLE_TXPD}
    assert all(g.reason == "sr_lacks_advance_schedule" for g in result.needs_external_input)


def test_repo_sample_sr_has_zero_advances():
    """Coverage anchor: real sample SR never carries advance rows."""
    parsed = parse_sales_register(SAMPLE_SR.read_bytes(), SAMPLE_SR.name)
    result = map_sales_register_to_gstr1_at_txpd(
        parsed["records"], filing_period=PERIOD,
    )
    assert result.advance_line_count == 0
    assert result.needs_external_input == []
    assert result.at is None and result.txpd is None


def test_filing_period_format():
    with pytest.raises(ValueError, match="YYYY-MM"):
        map_sales_register_to_gstr1_at_txpd([], filing_period="2025/04")
