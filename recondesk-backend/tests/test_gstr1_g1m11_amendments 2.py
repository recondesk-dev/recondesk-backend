"""G1M11 — Amendment detection (GSTR-1 Tables 9A / 9B / 9C)."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.rules.gstr1_mismatch_rules import (
    MismatchSeverity,
    MismatchType,
    detect_amendments,
)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_gstr1_3b_test"
SAMPLE_SR = SAMPLE_DIR / "Sales_Register_Sample_Corrected.xlsx"
SAMPLE_GSTR1 = SAMPLE_DIR / "sample_gstr1.json"
SAMPLE_GSTR3B = SAMPLE_DIR / "sample_gstr3b.json"

DOWNLOADS = Path.home() / "Downloads"
MESSY_SR = DOWNLOADS / "Sales_Register_MESSY.xlsx"
MESSY_G1 = DOWNLOADS / "GSTR1_MESSY.json"
MESSY_G3 = DOWNLOADS / "GSTR3B_MESSY.json"


def _sr(
    *,
    inv: str = "INV/001",
    taxable: int = 100000,
    igst: int = 18000,
    gstin: str = "27AAECS4567P1Z9",
    invoice_type: str = "B2B",
) -> dict:
    return {
        "invoice_number": inv,
        "invoice_number_normalized": inv.replace("/", "").replace("-", ""),
        "invoice_type": invoice_type,
        "document_type": invoice_type,
        "gstin": gstin,
        "taxable_amount_paise": taxable,
        "igst_paise": igst,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": igst,
        "rate": 18.0,
    }


def _g1(
    *,
    inv: str = "INV/001",
    taxable: int = 100000,
    igst: int = 18000,
    gstin: str = "27AAECS4567P1Z9",
    invoice_type: str = "B2B",
    section: str = "b2b",
) -> dict:
    return {
        "invoice_number": inv,
        "invoice_number_normalized": inv.replace("/", "").replace("-", ""),
        "invoice_type": invoice_type,
        "section": section,
        "gstin": gstin,
        "recipient_gstin": gstin,
        "taxable_amount_paise": taxable,
        "igst_paise": igst,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": igst,
        "rate": 18.0,
    }


class TestDetectAmendments:

    def test_skipped_when_prior_not_provided(self):
        results = detect_amendments([_sr()], None, prior_provided=False)
        assert len(results) == 1
        assert results[0].mismatch_type == MismatchType.AMENDMENT_REQUIRED
        assert results[0].severity == MismatchSeverity.LOW
        assert results[0].details["issue_type"] == "amendment_detection_skipped"
        assert "prior period" in results[0].decision_what.lower()

    def test_changed_amount_flags_9a(self):
        sr = [_sr(inv="RD/001", taxable=200000, igst=36000)]
        prior = [_g1(inv="RD/001", taxable=100000, igst=18000)]
        results = detect_amendments(sr, prior, prior_provided=True)
        assert len(results) == 1
        assert results[0].details["issue_type"] == "amendment_missing"
        assert results[0].details["amendment_table"] == "9A"
        assert "taxable_amount" in results[0].details["differed_fields"]
        assert results[0].severity == MismatchSeverity.HIGH
        assert "9A" in results[0].decision_what

    def test_identical_values_not_flagged(self):
        sr = [_sr(inv="RD/001", taxable=100000, igst=18000)]
        prior = [_g1(inv="RD/001", taxable=100000, igst=18000)]
        results = detect_amendments(sr, prior, prior_provided=True)
        assert results == []

    def test_correctly_amended_silent_when_b2ba_matches_books(self):
        sr = [_sr(inv="RD/001", taxable=200000, igst=36000)]
        prior = [_g1(inv="RD/001", taxable=100000, igst=18000)]
        filed = [
            _g1(
                inv="RD/001",
                taxable=200000,
                igst=36000,
                section="b2ba",
            )
        ]
        filed[0]["is_amendment"] = True
        results = detect_amendments(
            sr,
            prior,
            prior_provided=True,
            current_amendment_records=filed,
        )
        assert results == []

    def test_amendment_still_wrong_when_b2ba_differs(self):
        sr = [_sr(inv="RD/001", taxable=200000, igst=36000)]
        prior = [_g1(inv="RD/001", taxable=100000, igst=18000)]
        filed = [
            _g1(
                inv="RD/001",
                taxable=150000,
                igst=27000,
                section="b2ba",
            )
        ]
        filed[0]["is_amendment"] = True
        results = detect_amendments(
            sr,
            prior,
            prior_provided=True,
            current_amendment_records=filed,
        )
        assert len(results) == 1
        assert results[0].details["issue_type"] == "amendment_still_wrong"
        assert "taxable_amount" in results[0].details["differed_fields"]

    def test_new_invoice_not_in_prior_ignored(self):
        sr = [_sr(inv="NEW/999", taxable=100000)]
        prior = [_g1(inv="OLD/001", taxable=100000)]
        results = detect_amendments(sr, prior, prior_provided=True)
        assert results == []

    def test_credit_note_maps_to_9b(self):
        sr = [_sr(inv="CN/001", taxable=50000, igst=9000, invoice_type="CREDIT_NOTE")]
        prior = [
            _g1(
                inv="CN/001",
                taxable=40000,
                igst=7200,
                invoice_type="CREDIT_NOTE",
                section="cdnr",
            )
        ]
        results = detect_amendments(sr, prior, prior_provided=True)
        assert len(results) == 1
        assert results[0].details["amendment_table"] == "9B"

    def test_export_maps_to_9c(self):
        sr = [
            _sr(
                inv="EXP/001",
                taxable=500000,
                igst=0,
                gstin="",
                invoice_type="EXPORT",
            )
        ]
        prior = [
            _g1(
                inv="EXP/001",
                taxable=400000,
                igst=0,
                gstin="",
                invoice_type="EXPORT",
                section="exp",
            )
        ]
        results = detect_amendments(sr, prior, prior_provided=True)
        assert len(results) == 1
        assert results[0].details["amendment_table"] == "9C"

    def test_gstin_change_flagged(self):
        sr = [_sr(inv="RD/001", gstin="27AAAAA0000A1Z5")]
        prior = [_g1(inv="RD/001", gstin="27BBBBB0000B1Z5")]
        results = detect_amendments(sr, prior, prior_provided=True)
        assert len(results) == 1
        assert "gstin" in results[0].details["differed_fields"]


class TestSampleDataAmendments:

    def test_sample_sr_vs_modified_prior_fires(self):
        from app.parsers.gstr1_parser import parse_gstr1
        from app.parsers.sales_register_parser import parse_sales_register

        if not SAMPLE_SR.exists() or not SAMPLE_GSTR1.exists():
            pytest.skip("Sample fixtures missing")

        sr = parse_sales_register(SAMPLE_SR.read_bytes(), SAMPLE_SR.name)
        g1 = parse_gstr1(SAMPLE_GSTR1.read_bytes())
        assert sr.get("success")

        prior = [copy.deepcopy(r) for r in g1["records"] if r.get("section") == "b2b"]
        assert prior, "expected B2B rows in sample GSTR-1"
        # Mutate one invoice so books ≠ prior filed values
        target = prior[0]
        target["taxable_amount_paise"] = _safe_lower(target.get("taxable_amount_paise"))
        target["total_tax_paise"] = max(0, int(target.get("total_tax_paise") or 0) // 2)
        target["igst_paise"] = target["total_tax_paise"]

        results = detect_amendments(
            sr["records"], prior, prior_provided=True,
        )
        amendments = [
            r for r in results
            if r.details.get("issue_type") in {
                "amendment_required",
                "amendment_missing",
                "amendment_still_wrong",
            }
        ]
        assert len(amendments) >= 1
        assert amendments[0].details["amendment_table"] == "9A"

    @pytest.mark.asyncio
    async def test_pipeline_skips_when_prior_omitted(self):
        """Full pipeline without prior → skip note, no error."""
        from app.routers.gstr1_reconcile import _run_pipeline

        if not (SAMPLE_SR.exists() and SAMPLE_GSTR1.exists() and SAMPLE_GSTR3B.exists()):
            pytest.skip("Sample fixtures missing")

        with patch(
            "app.routers.gstr1_reconcile._verify_buyer_gstins_for_g1m7",
            new_callable=AsyncMock,
            return_value=[],
        ):
            out = await _run_pipeline(
                SAMPLE_SR.read_bytes(),
                SAMPLE_SR.name,
                SAMPLE_GSTR1.read_bytes(),
                SAMPLE_GSTR3B.read_bytes(),
                None,
                prior_gstr1_file_content=None,
            )

        assert out["success"] is True
        assert out["summary"]["amendment_detection_skipped"] is True
        assert out["summary"]["amendment_count"] == 0
        skipped = [
            m for m in out["mismatches"]
            if m.get("issue_type") == "amendment_detection_skipped"
        ]
        assert len(skipped) == 1

    @pytest.mark.asyncio
    async def test_pipeline_with_changed_prior_fires_g1m11(self):
        from app.parsers.gstr1_parser import parse_gstr1
        from app.routers.gstr1_reconcile import _run_pipeline

        if not (SAMPLE_SR.exists() and SAMPLE_GSTR1.exists() and SAMPLE_GSTR3B.exists()):
            pytest.skip("Sample fixtures missing")

        # Build a minimal prior JSON containing only one invoice with a
        # different taxable value so that invoice is amendment-linked.
        # (A full clone of current GSTR-1 would mark every invoice as prior-
        # linked and exclude them all from current-period matching.)
        raw = json.loads(SAMPLE_GSTR1.read_text())
        party = copy.deepcopy(raw["b2b"][0])
        inv = party["inv"][0]
        inv["itms"][0]["itm_det"]["txval"] = float(inv["itms"][0]["itm_det"]["txval"]) * 0.5
        inv["itms"][0]["itm_det"]["iamt"] = float(inv["itms"][0]["itm_det"].get("iamt") or 0) * 0.5
        party["inv"] = [inv]
        prior_payload = {
            "gstin": raw.get("gstin"),
            "fp": raw.get("fp"),
            "b2b": [party],
        }
        prior_bytes = json.dumps(prior_payload).encode()

        # Sanity: parse confirms invoice-level rows
        assert parse_gstr1(prior_bytes).get("records")

        with patch(
            "app.routers.gstr1_reconcile._verify_buyer_gstins_for_g1m7",
            new_callable=AsyncMock,
            return_value=[],
        ):
            out = await _run_pipeline(
                SAMPLE_SR.read_bytes(),
                SAMPLE_SR.name,
                SAMPLE_GSTR1.read_bytes(),
                SAMPLE_GSTR3B.read_bytes(),
                None,
                prior_gstr1_file_content=prior_bytes,
            )

        assert out["success"] is True
        assert out["summary"]["amendment_detection_skipped"] is False
        assert out["summary"]["amendment_count"] >= 1
        g1m11 = [
            m for m in out["mismatches"]
            if "G1M11" in str(m.get("mismatch_type", ""))
            and m.get("issue_type") in {
                "amendment_required",
                "amendment_missing",
                "amendment_still_wrong",
            }
        ]
        assert len(g1m11) >= 1
        assert g1m11[0].get("amendment_table") == "9A"


def _safe_lower(v) -> int:
    n = int(v or 0)
    return max(0, n // 2) if n else 0


class TestMessyAmendmentRegression:

    @pytest.mark.asyncio
    async def test_messy_with_prior_no_oom(self):
        if not (MESSY_SR.is_file() and MESSY_G1.is_file() and MESSY_G3.is_file()):
            pytest.skip("MESSY fixtures not present in ~/Downloads")

        from app.routers.gstr1_reconcile import _run_pipeline

        # Use messy GSTR-1 itself as "prior" (values mostly same → few/no amendments)
        # but comparison must complete without OOM on pathological invoice numbers.
        prior_bytes = MESSY_G1.read_bytes()
        t0 = time.perf_counter()
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
                prior_gstr1_file_content=prior_bytes,
            )
        elapsed = time.perf_counter() - t0
        assert elapsed < 5.0, f"pipeline too slow ({elapsed:.2f}s) — possible OOM path"
        assert out["success"] is True
        assert out["summary"]["amendment_detection_skipped"] is False
        assert "amendment_count" in out["summary"]
