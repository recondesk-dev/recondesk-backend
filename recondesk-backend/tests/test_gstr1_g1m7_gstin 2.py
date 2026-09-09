"""G1M7 — sell-side buyer GSTIN format + Sandbox verification flags."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.parsers.sales_register_parser import parse_sales_register
from app.rules.gstr1_mismatch_rules import (
    MismatchType,
    build_g1m7_mismatches,
    clean_buyer_gstin,
    collect_unique_buyer_gstins,
    gstin_format_ok,
)
from app.routers.gstr1_reconcile import (
    _run_pipeline,
    _verify_buyer_gstins_for_g1m7,
)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_gstr1_3b_test"
SAMPLE_SR = SAMPLE_DIR / "Sales_Register_Sample_Corrected.xlsx"
SAMPLE_G1 = SAMPLE_DIR / "sample_gstr1.json"
SAMPLE_G3 = SAMPLE_DIR / "sample_gstr3b.json"

# Deliberately malformed — fails regex before any Sandbox call.
INVALID_GSTIN = "INVALIDGSTIN!!!"


def test_gstin_format_ok_rejects_malformed():
    assert not gstin_format_ok(INVALID_GSTIN)
    assert not gstin_format_ok("27AAAAA0000A1Z")  # too short
    assert gstin_format_ok("27AAPFU0939F1ZV")


def test_collect_unique_buyer_gstins_dedupes_across_invoices():
    sr = [
        {"invoice_number": "A1", "gstin": "27AAPFU0939F1ZV"},
        {"invoice_number": "A2", "gstin": "27AAPFU0939F1ZV"},
        {"invoice_number": "A3", "gstin": "NA"},
        {"invoice_number": "A4", "gstin": INVALID_GSTIN},
    ]
    refs = collect_unique_buyer_gstins(sr_records=sr)
    assert "27AAPFU0939F1ZV" in refs
    assert len(refs["27AAPFU0939F1ZV"]) == 2
    cleaned_invalid = clean_buyer_gstin(INVALID_GSTIN)
    assert cleaned_invalid is not None
    assert cleaned_invalid in refs
    assert "NA" not in refs


def test_build_g1m7_flags_invalid_format_and_inactive():
    gstin_refs = {
        "BADFORMAT123": [
            {"source": "sales_register", "invoice_number": "INV-1"},
            {"source": "gstr1", "invoice_number": "INV-1"},
        ],
        "27AAPFU0939F1ZV": [
            {"source": "sales_register", "invoice_number": "INV-2"},
        ],
        "29AAAAA0000A1Z5": [
            {"source": "gstr1", "invoice_number": "INV-3"},
        ],
    }
    cache = {
        "BADFORMAT123": {
            "valid": False,
            "status": "Invalid Format",
            "reason": "invalid_format",
        },
        "27AAPFU0939F1ZV": {
            "valid": True,
            "status": "Active",
            "legal_name": "Ok Buyer",
        },
        "29AAAAA0000A1Z5": {
            "valid": False,
            "status": "Cancelled",
            "legal_name": "Gone Pvt Ltd",
        },
    }
    results = build_g1m7_mismatches(
        gstin_refs=gstin_refs,
        verification_by_gstin=cache,
    )
    types = {r.mismatch_type for r in results}
    assert types == {MismatchType.INVALID_GSTIN}
    # Two invoice refs for BADFORMAT + one cancelled
    assert len(results) == 3
    reasons = {r.details["reason"] for r in results}
    assert "invalid_format" in reasons
    assert "cancelled" in reasons
    assert all(r.rule_id == "G1M_007" for r in results)


@pytest.mark.asyncio
async def test_verify_skips_api_for_invalid_format():
    """Format failures must not call verify_gstin."""
    sr = [
        {"invoice_number": "X1", "gstin": INVALID_GSTIN},
        {"invoice_number": "X2", "gstin": INVALID_GSTIN},
    ]
    mock_verify = AsyncMock()
    with patch(
        "app.services.gstin_verification.verify_gstin",
        mock_verify,
    ):
        results = await _verify_buyer_gstins_for_g1m7(sr, [])
    mock_verify.assert_not_called()
    assert len(results) == 2  # one mismatch per invoice ref
    assert all(r.mismatch_type == MismatchType.INVALID_GSTIN for r in results)
    assert all(r.details["reason"] == "invalid_format" for r in results)


@pytest.mark.asyncio
async def test_verify_caches_one_api_call_per_unique_gstin():
    good = "27AAPFU0939F1ZV"
    sr = [
        {"invoice_number": "Y1", "gstin": good},
        {"invoice_number": "Y2", "gstin": good},
    ]
    mock_verify = AsyncMock(
        return_value={
            "valid": False,
            "status": "Cancelled",
            "legal_name": None,
            "trade_name": None,
            "taxpayer_type": None,
            "registration_date": None,
            "raw_response": {},
        }
    )
    with patch(
        "app.services.gstin_verification.verify_gstin",
        mock_verify,
    ):
        results = await _verify_buyer_gstins_for_g1m7(
            sr, [], rate_limit_seconds=0,
        )
    mock_verify.assert_called_once_with(good)
    assert len(results) == 2
    assert all(r.details["reason"] == "cancelled" for r in results)


@pytest.mark.asyncio
async def test_verify_ignores_not_found_api_results():
    """Sandbox 'Not Found' must not flood G1M7 for every synthetic GSTIN."""
    good = "27AAPFU0939F1ZV"
    sr = [{"invoice_number": "Y1", "gstin": good}]
    mock_verify = AsyncMock(
        return_value={
            "valid": False,
            "status": "Not Found",
            "legal_name": None,
            "trade_name": None,
            "taxpayer_type": None,
            "registration_date": None,
            "raw_response": {},
        }
    )
    with patch(
        "app.services.gstin_verification.verify_gstin",
        mock_verify,
    ):
        results = await _verify_buyer_gstins_for_g1m7(
            sr, [], rate_limit_seconds=0,
        )
    mock_verify.assert_called_once_with(good)
    assert results == []


@pytest.mark.asyncio
async def test_sample_sr_with_injected_invalid_gstin_flags_g1m7():
    """Parse Sales_Register_Sample_Corrected.xlsx, inject a bad GSTIN, run pipeline."""
    if not (SAMPLE_SR.is_file() and SAMPLE_G1.is_file() and SAMPLE_G3.is_file()):
        pytest.skip("sample_gstr1_3b_test fixtures missing")

    parsed = parse_sales_register(SAMPLE_SR.read_bytes(), SAMPLE_SR.name)
    assert parsed.get("success"), parsed.get("errors")
    records = parsed.get("records") or []
    assert records, "sample SR produced no records"

    # Inject a malformed GSTIN on the first B2B-ish row (or first row).
    target = records[0]
    target["gstin"] = INVALID_GSTIN
    if "recipient_gstin" in target:
        target["recipient_gstin"] = INVALID_GSTIN

    # Re-run via verify helper on mutated records (format path, no API).
    results = await _verify_buyer_gstins_for_g1m7(records, [])
    assert any(
        r.mismatch_type == MismatchType.INVALID_GSTIN
        and r.details.get("reason") == "invalid_format"
        for r in results
    ), results

    # Full pipeline: mock verify so only format-invalid hits (and any
    # format-ok GSTINs from sample are treated as Active).
    async def _fake_verify(gstin: str):
        if not gstin_format_ok(gstin):
            return {
                "valid": False,
                "status": "Invalid Format",
                "reason": "invalid_format",
            }
        return {
            "valid": True,
            "status": "Active",
            "legal_name": "Mock Buyer",
            "trade_name": None,
            "taxpayer_type": None,
            "registration_date": None,
            "raw_response": {},
        }

    # Mutate bytes path: write is heavy — instead patch collect to include
    # the invalid GSTIN by patching verification after parse inside pipeline.
    # Simpler: call build path already covered; for pipeline, inject via
    # monkeypatch on parse_sales_register return.
    original_parse = parse_sales_register

    def _parse_with_invalid(content: bytes, filename: str):
        out = original_parse(content, filename)
        recs = out.get("records") or []
        if recs:
            recs[0]["gstin"] = INVALID_GSTIN
        return out

    with (
        patch(
            "app.routers.gstr1_reconcile.parse_sales_register",
            side_effect=_parse_with_invalid,
        ),
        patch(
            "app.services.gstin_verification.verify_gstin",
            new_callable=AsyncMock,
            side_effect=_fake_verify,
        ),
    ):
        out = await _run_pipeline(
            SAMPLE_SR.read_bytes(),
            SAMPLE_SR.name,
            SAMPLE_G1.read_bytes(),
            SAMPLE_G3.read_bytes(),
            None,
        )

    g1m7 = [
        m
        for m in out["mismatches"]
        if str(m.get("mismatch_type", "")).startswith("G1M7")
    ]
    assert g1m7, f"expected G1M7 in mismatches, got: {out['mismatches']}"
    assert any(
        m.get("reason") == "invalid_format"
        or "invalid format" in str(m.get("decision_what", "")).lower()
        for m in g1m7
    )
    assert out["summary"]["mismatch_count"] >= len(g1m7)
