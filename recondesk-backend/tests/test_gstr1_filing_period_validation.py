"""Regression tests for GSTR-1 filing-period validation and parsing."""

from __future__ import annotations

import datetime
import json
import pytest
from fastapi import HTTPException

from app.parsers.gstr1_parser import _parse_filing_period, parse_gstr1
from app.routers.gstr1_reconcile import _run_pipeline


# ── 1. Unit tests for _parse_filing_period ────────────────────────────────────

@pytest.mark.parametrize(
    "input_val, expected_date",
    [
        ("072025", datetime.date(2025, 7, 1)),   # July 2025
        ("042025", datetime.date(2025, 4, 1)),   # April 2025
        ("122025", datetime.date(2025, 12, 1)),  # December 2025
        ("012025", datetime.date(2025, 1, 1)),   # January 2025
        ("202507", datetime.date(2025, 7, 1)),   # YYYYMM
        ("2025-07", datetime.date(2025, 7, 1)),  # YYYY-MM
        ("07-2025", datetime.date(2025, 7, 1)),  # MM-YYYY
        ("07/2025", datetime.date(2025, 7, 1)),  # MM/YYYY
        ("2025-07-01", datetime.date(2025, 7, 1)), # YYYY-MM-DD
    ],
)
def test_parse_filing_period_valid(input_val: str, expected_date: datetime.date):
    assert _parse_filing_period(input_val) == expected_date


@pytest.mark.parametrize(
    "invalid_val",
    [
        "132025",   # Month 13
        "002025",   # Month 00
        "07202",    # 5 digits
        "0720250",  # 7 digits
        "202513",   # YYYYMM month 13
        "202500",   # YYYYMM month 00
        "invalid",  # Non-numeric
        "",         # Empty
        "   ",      # Whitespace
        None,       # None
    ],
)
def test_parse_filing_period_rejects_invalid(invalid_val: str | None):
    with pytest.raises(ValueError, match="invalid_filing_period"):
        _parse_filing_period(invalid_val)


# ── 2. parse_gstr1 fallback behavior ──────────────────────────────────────────

def test_parse_gstr1_standard_fp():
    content = json.dumps({
        "gstin": "27ISKPK1273H1ZF",
        "fp": "072025",
        "b2b": [],
    })
    res = parse_gstr1(content)
    assert res["filing_period"] == "2025-07-01"


def test_parse_gstr1_missing_fp_uses_fallback():
    content = json.dumps({
        "gstin": "27ISKPK1273H1ZF",
        "b2b": [],
    })
    res = parse_gstr1(content, filing_period="072025")
    assert res["filing_period"] == "2025-07-01"


def test_parse_gstr1_unparseable_fp_uses_fallback():
    content = json.dumps({
        "gstin": "27ISKPK1273H1ZF",
        "fp": "not-a-period",
        "b2b": [],
    })
    res = parse_gstr1(content, filing_period="072025")
    assert res["filing_period"] == "2025-07-01"


def test_parse_gstr1_unparseable_fp_without_fallback_raises():
    content = json.dumps({
        "gstin": "27ISKPK1273H1ZF",
        "fp": "132025",
        "b2b": [],
    })
    with pytest.raises(ValueError, match="invalid_filing_period"):
        parse_gstr1(content)


# ── 3. Pipeline integration tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_reconcile_with_072025_reaches_engine():
    sr_csv = b"Type,Invoice Number,Invoice Date,Customer Name,Customer GSTIN,Place of Supply,HSN,Item Description,Taxable Value,IGST Rate,IGST Amount,CGST Rate,CGST Amount,SGST Rate,SGST Amount,Total Value\nSales,INV-001,01/07/2025,Acme Corp,29AABCI1681G1ZX,29,8471,Widgets,100000,18,18000,0,0,0,0,118000\n"
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
                        "rchrg": "N",
                        "inv_typ": "R",
                        "itms": [
                            {
                                "num": 1,
                                "itm_det": {
                                    "txval": 100000,
                                    "rt": 18,
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
        "ret_period": "072025",
        "sup_details": {
            "osup_det": {
                "txval": 100000,
                "iamt": 18000,
                "camt": 0,
                "samt": 0,
                "csamt": 0,
            }
        },
    }).encode("utf-8")

    res = await _run_pipeline(
        sr_file_content=sr_csv,
        sr_filename="sr.csv",
        gstr1_file_content=g1_json,
        gstr3b_file_content=g3b_json,
        gstr1_filing_period="072025",
    )

    assert res["summary"]["matched_count"] == 1
    assert res["parse_diagnostics"]["gstr1"]["filing_period"] == "2025-07-01"
    assert res["summary"]["tie_out_clean"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_period",
    ["132025", "002025", "07202", "0720250"],
)
async def test_pipeline_rejects_invalid_filing_periods(invalid_period: str):
    sr_csv = b"dummy"
    g1_json = b"{}"
    g3b_json = b"{}"

    with pytest.raises(HTTPException) as exc_info:
        await _run_pipeline(
            sr_file_content=sr_csv,
            sr_filename="sr.csv",
            gstr1_file_content=g1_json,
            gstr3b_file_content=g3b_json,
            gstr1_filing_period=invalid_period,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "error": "gstr1_parse_failed",
        "message": "invalid_filing_period",
    }
