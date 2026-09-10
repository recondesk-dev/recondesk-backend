"""Regression tests for GSTR-3B ret_period normalization and formats."""

from __future__ import annotations

import datetime
import json
import pytest

from app.parsers.gstr3b_parser import ParseError, _parse_ret_period, parse_gstr3b
from app.routers.gstr1_reconcile import _run_pipeline


# ── 1. Unit tests for _parse_ret_period ───────────────────────────────────────

@pytest.mark.parametrize(
    "input_val, expected",
    [
        ("072025", "2025-07"),     # MMYYYY (portal format)
        ("202507", "2025-07"),     # YYYYMM
        ("2025-07", "2025-07"),    # YYYY-MM (canonical)
        ("07-2025", "2025-07"),    # MM-YYYY (fuzz fixture format)
        ("07/2025", "2025-07"),    # MM/YYYY
        ("7/2025", "2025-07"),     # M/YYYY
        ("2025-07-01", "2025-07"), # YYYY-MM-DD
        ("01-07-2025", "2025-07"), # DD-MM-YYYY
        ("042025", "2025-04"),     # April 2025
        ("122025", "2025-12"),     # December 2025
        ("012025", "2025-01"),     # January 2025
        (datetime.date(2025, 7, 1), "2025-07"),
    ],
)
def test_parse_ret_period_valid_formats(input_val, expected: str):
    assert _parse_ret_period(input_val) == expected


@pytest.mark.parametrize(
    "invalid_val",
    [
        "132025",   # MMYYYY month 13
        "002025",   # MMYYYY month 00
        "07202",    # 5 digits
        "0720250",  # 7 digits
        "202513",   # YYYYMM month 13
        "202500",   # YYYYMM month 00
        "13-2025",  # MM-YYYY month 13
        "00-2025",  # MM-YYYY month 00
        "2025-13",  # YYYY-MM month 13
        "2025-00",  # YYYY-MM month 00
        "invalid",  # Malformed string
        "",         # Empty
        "   ",      # Whitespace
        None,       # None
    ],
)
def test_parse_ret_period_rejects_invalid_formats(invalid_val):
    with pytest.raises(ParseError, match="ret_period has unrecognised format"):
        _parse_ret_period(invalid_val)


# ── 2. parse_gstr3b full payload tests ────────────────────────────────────────

def test_parse_gstr3b_fuzz_format_07_2025():
    raw = {
        "gstin": "27ISKPK1273H1ZF",
        "ret_period": "07-2025",
        "sup_details": {
            "osup_det": {
                "txval": 100000.0,
                "iamt": 18000.0,
                "camt": 0.0,
                "samt": 0.0,
                "csamt": 0.0,
            }
        },
    }
    parsed = parse_gstr3b(raw)
    assert parsed["gstin"] == "27ISKPK1273H1ZF"
    assert parsed["ret_period"] == "2025-07"
    assert parsed["outward_supply"]["taxable_value"] == 100000.0
    assert parsed["outward_supply"]["igst"] == 18000.0


def test_parse_gstr3b_other_valid_ret_periods():
    for fp in ("072025", "202507", "2025-07", "07/2025", "2025-07-01"):
        raw = {
            "gstin": "27ISKPK1273H1ZF",
            "ret_period": fp,
            "sup_details": {
                "osup_det": {"txval": 50000.0, "iamt": 9000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
            },
        }
        parsed = parse_gstr3b(raw)
        assert parsed["ret_period"] == "2025-07"


def test_parse_gstr3b_invalid_ret_period_raises_parse_error():
    raw = {
        "gstin": "27ISKPK1273H1ZF",
        "ret_period": "13-2025",
        "sup_details": {},
    }
    with pytest.raises(ParseError, match="ret_period has unrecognised format: '13-2025'"):
        parse_gstr3b(raw)


# ── 3. Pipeline integration tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_with_gstr3b_07_2025_ret_period():
    """Verify that GSTR-3B payload with ret_period='07-2025' runs cleanly in pipeline."""
    sr_csv = (
        b"Type,Invoice Number,Invoice Date,Customer Name,Customer GSTIN,Place of Supply,HSN,Item Description,Taxable Value,IGST Rate,IGST Amount,CGST Rate,CGST Amount,SGST Rate,SGST Amount,Total Value\n"
        b"Sales,INV-001,01/07/2025,Acme Corp,29AABCI1681G1ZX,29,8471,Widgets,100000,18,18000,0,0,0,0,118000\n"
    )
    g1_json = json.dumps({
        "gstin": "27ISKPK1273H1ZF",
        "fp": "072025",
        "b2b": [
            {
                "ctin": "29AABCI1681G1ZX",
                "inv": [
                    {
                        "inum": "INV-001",
                        "idt": "01-07-2025",
                        "val": 118000,
                        "pos": "29",
                        "itms": [
                            {
                                "num": 1,
                                "itm_det": {
                                    "rt": 18,
                                    "txval": 100000,
                                    "iamt": 18000,
                                    "camt": 0,
                                    "samt": 0,
                                    "csamt": 0,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }).encode("utf-8")

    g3b_json = json.dumps({
        "gstin": "27ISKPK1273H1ZF",
        "ret_period": "07-2025",  # Fuzz fixture format
        "data": {
            "sup_details": {
                "osup_det": {
                    "txval": 100000,
                    "iamt": 18000,
                    "camt": 0,
                    "samt": 0,
                    "csamt": 0,
                }
            }
        },
    }).encode("utf-8")

    result = await _run_pipeline(
        sr_file_content=sr_csv,
        sr_filename="sales_register.csv",
        gstr1_file_content=g1_json,
        gstr3b_file_content=g3b_json,
        gstr1_filing_period="072025",
    )

    tie_out = result["tie_out"]
    assert tie_out["ret_period"] == "2025-07"
    assert result["summary"]["tie_out_clean"] is True
    assert result["summary"]["tie_out_variance_count"] == 0
