"""HSN / nil / advance aggregates must never appear as Extra-in-GSTR-1."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.gstr1_reconcile import (
    _is_invoice_level_gstr1_record,
    _run_pipeline,
)


def test_hsn_summary_is_not_invoice_level():
    assert not _is_invoice_level_gstr1_record(
        {
            "section": "hsn",
            "invoice_type": "HSN_SUMMARY",
            "invoice_number": "HSN-8203-0",
        }
    )
    assert _is_invoice_level_gstr1_record(
        {
            "section": "b2b",
            "invoice_type": "B2B",
            "invoice_number": "RD2026273001",
        }
    )
    assert not _is_invoice_level_gstr1_record(
        {
            "section": "b2cs",
            "invoice_type": "B2C_SMALL",
            "invoice_number": "B2CS-27-Maharashtra-18.0-0",
        }
    )
    assert _is_invoice_level_gstr1_record(
        {
            "section": "b2cl",
            "invoice_type": "B2C_LARGE",
            "invoice_number": "B2CL-2026-001",
        }
    )


@pytest.mark.asyncio
async def test_messy_gstr1_extra_excludes_hsn_row():
    """GSTR1_MESSY: 7 invoice-level rows, 1 HSN → Extra must not include HSN."""
    downloads = Path.home() / "Downloads"
    sr_path = downloads / "Sales_Register_MESSY.xlsx"
    g1_path = downloads / "GSTR1_MESSY.json"
    g3_path = downloads / "GSTR3B_MESSY.json"
    if not (sr_path.is_file() and g1_path.is_file() and g3_path.is_file()):
        pytest.skip("MESSY fixtures not present in ~/Downloads")

    # Avoid live Sandbox.co.in calls during matching-focused regression.
    with patch(
        "app.routers.gstr1_reconcile._verify_buyer_gstins_for_g1m7",
        new_callable=AsyncMock,
        return_value=[],
    ):
        out = await _run_pipeline(
            sr_path.read_bytes(),
            sr_path.name,
            g1_path.read_bytes(),
            g3_path.read_bytes(),
            None,
        )
    summary = out["summary"]
    assert summary["gstr1_total_records"] == 7
    assert summary.get("gstr1_metadata_record_count") == 1
    # Invoice-primary matching can pair GSTIN-typo / blank-GSTIN rows that
    # the old GSTIN+invoice key left unmatched.
    assert summary["matched_count"] == 3
    assert summary["unmatched_gstr1_count"] == 4  # 7 − 3 matched

    extras = out["unmatched_gstr1"]
    invs = [
        (r.get("record") or {}).get("invoice_number")
        or (r.get("record") or {}).get("invoice_number_normalized")
        for r in extras
    ]
    assert not any(str(i).startswith("HSN-") for i in invs)
    sections = {(r.get("record") or {}).get("section") for r in extras}
    assert "hsn" not in sections


def test_classify_path_never_sees_hsn_when_filtered():
    """Synthetic: HSN-only leftover must not become G1M2 once filtered."""
    from app.rules.gstr1_mismatch_rules import classify_all_mismatches, MismatchType

    hsn = {
        "section": "hsn",
        "invoice_type": "HSN_SUMMARY",
        "invoice_number": "HSN-8203-0",
    }
    # Caller responsibility: filter before classify (as _run_pipeline does).
    filtered = [r for r in [hsn] if _is_invoice_level_gstr1_record(r)]
    results = classify_all_mismatches(
        unmatched_sr=[],
        unmatched_gstr1=filtered,
        matched_pairs=[],
        gstr1_filing_period=None,
    )
    assert not any(
        r.mismatch_type == MismatchType.EXTRA_INVOICE for r in results
    )
