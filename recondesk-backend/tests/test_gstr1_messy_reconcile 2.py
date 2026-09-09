"""Regression: messy Sales Register / GSTR-1 must not crash reconciliation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.gstr1_reconcile import _run_pipeline
from app.rules.gstr1_mismatch_rules import validate_hsn_rate_mapping

DOWNLOADS = Path.home() / "Downloads"
MESSY_SR = DOWNLOADS / "Sales_Register_MESSY.xlsx"
MESSY_G1 = DOWNLOADS / "GSTR1_MESSY.json"
MESSY_G3 = DOWNLOADS / "GSTR3B_MESSY.json"


def _messy_fixtures_present() -> bool:
    return MESSY_SR.is_file() and MESSY_G1.is_file() and MESSY_G3.is_file()


@pytest.mark.asyncio
async def test_messy_files_pipeline_returns_success():
    """Production 502 regression — full pipeline must return 200-equivalent success."""
    if not _messy_fixtures_present():
        pytest.skip("MESSY fixtures not present in ~/Downloads")

    with patch(
        "app.routers.gstr1_reconcile._verify_buyer_gstins_for_g1m7",
        new_callable=AsyncMock,
        return_value=[],
    ):
        out = await _run_pipeline(
            MESSY_SR.read_bytes(),
            MESSY_SR.name,
            MESSY_G1.read_bytes(),
            MESSY_G3.read_bytes(),
            None,
        )

    assert out["success"] is True
    assert out["summary"]["sr_total_records"] == 25
    assert out["summary"]["gstr1_total_records"] == 7


def test_messy_g1m9_does_not_raise():
    """G1M9 on messy fixtures must complete and return flags, not exceptions."""
    if not _messy_fixtures_present():
        pytest.skip("MESSY fixtures not present in ~/Downloads")

    from app.parsers.gstr1_parser import parse_gstr1
    from app.parsers.sales_register_parser import parse_sales_register

    sr = parse_sales_register(MESSY_SR.read_bytes(), MESSY_SR.name)
    g1 = parse_gstr1(MESSY_G1.read_bytes())
    assert sr.get("success")

    results = validate_hsn_rate_mapping(sr.get("records", []), g1.get("records", []))
    assert isinstance(results, list)
    # Messy SR has no HSN column — must not crash; missing_hsn is no longer flooded.
    missing = [r for r in results if r.details.get("issue_type") == "missing_hsn"]
    assert missing == []
