"""G1M8 — Invoice series continuity, duplicate detection, and out-of-order checks.

Covers:
- Gap detection within a series
- Duplicate invoice number detection
- Out-of-order date detection
- Multiple concurrent series (no cross-series false positives)
- Small series below threshold (no false positives)
- Pure numeric invoice numbers
- Integration with sample data (Sales_Register_Sample_Corrected.xlsx)
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.rules.gstr1_mismatch_rules import (
    MismatchType,
    MismatchSeverity,
    MismatchResult,
    check_invoice_series_continuity,
)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_gstr1_3b_test"
SAMPLE_SR = SAMPLE_DIR / "Sales_Register_Sample_Corrected.xlsx"


# ──────────────────────────────────────────────────────────────────────────────
# Record builder
# ──────────────────────────────────────────────────────────────────────────────

def _sr(
    *,
    inv: str,
    inv_date: str = "2026-05-10",
    gstin: str = "27BBBFV1234A1ZP",
    taxable: int = 100000,
) -> dict:
    return {
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": inv_date,
        "gstin": gstin,
        "taxable_amount_paise": taxable,
        "total_tax_paise": 18000,
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Gap detection
# ══════════════════════════════════════════════════════════════════════════════

class TestGapDetection:

    def test_basic_gap(self):
        """INV/001–002, INV/006 → contiguous gap 003–005 (min run length 3)."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/002", inv_date="2026-05-02"),
            _sr(inv="INV/006", inv_date="2026-05-06"),
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 1
        assert gap_results[0].mismatch_type == MismatchType.INVOICE_SERIES_ISSUE
        assert gap_results[0].severity == MismatchSeverity.MEDIUM
        assert gap_results[0].rule_id == "G1M_008"
        assert gap_results[0].details["missing_numbers"] == [3, 4, 5]
        assert gap_results[0].details["series_prefix"] == "INV/"

    def test_multiple_gaps(self):
        """Two contiguous runs of 3+ missing numbers → two gap flags."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/005", inv_date="2026-05-05"),  # missing 2–4
            _sr(inv="INV/010", inv_date="2026-05-10"),  # missing 6–9
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 2
        missing_sets = {tuple(r.details["missing_numbers"]) for r in gap_results}
        assert missing_sets == {(2, 3, 4), (6, 7, 8, 9)}

    def test_singleton_hole_not_flagged(self):
        """A single missing number is ignored (often a cancellation)."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/002", inv_date="2026-05-02"),
            _sr(inv="INV/004", inv_date="2026-05-04"),
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert gap_results == []

    def test_no_gap_when_complete(self):
        """INV/001 through INV/005 complete → no gap flagged."""
        records = [_sr(inv=f"INV/{i:03d}", inv_date=f"2026-05-{i:02d}") for i in range(1, 6)]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 0

    def test_gap_cap_at_max(self):
        """Large gap range is capped at _MAX_GAPS_PER_SERIES (20)."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/002", inv_date="2026-05-02"),
            _sr(inv="INV/100", inv_date="2026-05-30"),
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 1
        # Should be capped at 20
        assert len(gap_results[0].details["missing_numbers"]) == 20


# ══════════════════════════════════════════════════════════════════════════════
# Duplicate detection
# ══════════════════════════════════════════════════════════════════════════════

class TestDuplicateDetection:

    def test_basic_duplicate(self):
        """Same invoice number appearing twice → flagged as duplicate."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/001", inv_date="2026-05-02"),
            _sr(inv="INV/002", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        dup_results = [r for r in results if r.details.get("issue_type") == "duplicate"]
        assert len(dup_results) == 1
        assert dup_results[0].severity == MismatchSeverity.HIGH
        assert dup_results[0].details["invoice_number"] == "INV/001"
        assert dup_results[0].details["occurrence_count"] == 2

    def test_triple_duplicate(self):
        """Same invoice number three times → flagged with count=3."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/001", inv_date="2026-05-02"),
            _sr(inv="INV/001", inv_date="2026-05-03"),
            _sr(inv="INV/002", inv_date="2026-05-04"),
            _sr(inv="INV/003", inv_date="2026-05-05"),
        ]
        results = check_invoice_series_continuity(records)
        dup_results = [r for r in results if r.details.get("issue_type") == "duplicate"]
        assert len(dup_results) == 1
        assert dup_results[0].details["occurrence_count"] == 3

    def test_no_duplicates(self):
        """All unique invoice numbers → no duplicate flagged."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/002", inv_date="2026-05-02"),
            _sr(inv="INV/003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        dup_results = [r for r in results if r.details.get("issue_type") == "duplicate"]
        assert len(dup_results) == 0

    def test_duplicates_have_high_severity(self):
        """Duplicate results should sort before gap results (HIGH > MEDIUM)."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/001", inv_date="2026-05-02"),
            _sr(inv="INV/005", inv_date="2026-05-05"),  # gap 2–4
        ]
        results = check_invoice_series_continuity(records)
        assert len(results) >= 2
        # Duplicates (HIGH) should come before gaps (MEDIUM)
        assert results[0].details.get("issue_type") == "duplicate"


# ══════════════════════════════════════════════════════════════════════════════
# Out-of-order date detection
# ══════════════════════════════════════════════════════════════════════════════

class TestOutOfOrderDetection:

    def test_basic_out_of_order(self):
        """Out-of-order dates are no longer flagged (too noisy on real filings)."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-10"),
            _sr(inv="INV/002", inv_date="2026-05-05"),  # Earlier date, later number
            _sr(inv="INV/003", inv_date="2026-05-15"),
        ]
        results = check_invoice_series_continuity(records)
        ooo_results = [r for r in results if r.details.get("issue_type") == "out_of_order"]
        assert ooo_results == []

    def test_no_out_of_order_when_chronological(self):
        """Dates follow numeric order → no out-of-order flag."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/002", inv_date="2026-05-02"),
            _sr(inv="INV/003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        ooo_results = [r for r in results if r.details.get("issue_type") == "out_of_order"]
        assert len(ooo_results) == 0

    def test_same_date_not_flagged(self):
        """Invoices on the same date with sequential numbers → not flagged."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-10"),
            _sr(inv="INV/002", inv_date="2026-05-10"),  # Same date is fine
            _sr(inv="INV/003", inv_date="2026-05-10"),
        ]
        results = check_invoice_series_continuity(records)
        ooo_results = [r for r in results if r.details.get("issue_type") == "out_of_order"]
        assert len(ooo_results) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Multiple concurrent series — no cross-series false positives
# ══════════════════════════════════════════════════════════════════════════════

class TestMultipleSeries:

    def test_two_complete_series_no_flags(self):
        """INV/ and EXP/ series both complete → no false gap across series."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/002", inv_date="2026-05-02"),
            _sr(inv="INV/003", inv_date="2026-05-03"),
            _sr(inv="EXP/001", inv_date="2026-05-01"),
            _sr(inv="EXP/002", inv_date="2026-05-02"),
            _sr(inv="EXP/003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        # No gaps, no duplicates, no out-of-order
        assert len(results) == 0

    def test_gap_in_one_series_not_other(self):
        """Gap in INV/ series but EXP/ is complete → only INV/ flagged."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/005", inv_date="2026-05-05"),  # missing 2–4
            _sr(inv="INV/006", inv_date="2026-05-06"),
            _sr(inv="EXP/001", inv_date="2026-05-01"),
            _sr(inv="EXP/002", inv_date="2026-05-02"),
            _sr(inv="EXP/003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 1
        assert gap_results[0].details["series_prefix"] == "INV/"

    def test_cross_series_numbers_not_flagged_as_gap(self):
        """INV/005 and EXP/001 → no cross-series gap detected."""
        records = [
            _sr(inv="INV/005", inv_date="2026-05-05"),
            _sr(inv="INV/006", inv_date="2026-05-06"),
            _sr(inv="INV/007", inv_date="2026-05-07"),
            _sr(inv="EXP/001", inv_date="2026-05-01"),
            _sr(inv="EXP/002", inv_date="2026-05-02"),
            _sr(inv="EXP/003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        # Both series are complete within themselves
        assert len(results) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Small series below threshold
# ══════════════════════════════════════════════════════════════════════════════

class TestSmallSeriesThreshold:

    def test_two_invoices_not_analysed(self):
        """Series with only 2 invoices → skipped (below _MIN_SERIES_SIZE=3)."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/005", inv_date="2026-05-05"),  # Big gap but only 2 records
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 0

    def test_single_invoice_not_analysed(self):
        """Single invoice → no analysis."""
        records = [_sr(inv="INV/001", inv_date="2026-05-01")]
        results = check_invoice_series_continuity(records)
        assert len(results) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Pure numeric invoice numbers
# ══════════════════════════════════════════════════════════════════════════════

class TestPureNumericInvoices:

    def test_numeric_gap(self):
        """Pure numeric series: '001', '002', '006' → gap at 3–5."""
        records = [
            _sr(inv="001", inv_date="2026-05-01"),
            _sr(inv="002", inv_date="2026-05-02"),
            _sr(inv="006", inv_date="2026-05-06"),
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 1
        assert gap_results[0].details["series_prefix"] == ""
        assert gap_results[0].details["missing_numbers"] == [3, 4, 5]

    def test_numeric_complete(self):
        """Complete numeric series → no flags."""
        records = [
            _sr(inv="001", inv_date="2026-05-01"),
            _sr(inv="002", inv_date="2026-05-02"),
            _sr(inv="003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Empty / edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_empty_records(self):
        """Empty list → no results."""
        results = check_invoice_series_continuity([])
        assert results == []

    def test_records_without_invoice_number(self):
        """Records missing invoice_number → skipped gracefully."""
        records = [
            {"gstin": "27BBBFV1234A1ZP", "invoice_date": "2026-05-01"},
            {"gstin": "27BBBFV1234A1ZP", "invoice_date": "2026-05-02"},
        ]
        results = check_invoice_series_continuity(records)
        assert results == []

    def test_non_numeric_invoice_number(self):
        """Invoice numbers with no digits → skipped for series analysis."""
        records = [
            _sr(inv="ABC", inv_date="2026-05-01"),
            _sr(inv="DEF", inv_date="2026-05-02"),
            _sr(inv="GHI", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 0

    def test_result_has_decision_fields(self):
        """Verify G1M8 results have WHAT/WHY/NEXT decision text."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/001", inv_date="2026-05-02"),
            _sr(inv="INV/003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        for r in results:
            assert r.decision_what, "decision_what must be non-empty"
            assert r.decision_why, "decision_why must be non-empty"
            assert r.decision_next, "decision_next must be non-empty"
            assert r.rule_id == "G1M_008"
            assert r.gst_ref == "Rule 46 CGST Rules"

    def test_to_dict_serialisation(self):
        """Verify .to_dict() and .to_decision_output() work for G1M8."""
        records = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/001", inv_date="2026-05-02"),
            _sr(inv="INV/003", inv_date="2026-05-03"),
        ]
        results = check_invoice_series_continuity(records)
        assert len(results) > 0
        for r in results:
            d = r.to_dict()
            assert "mismatch_type" in d
            assert d["mismatch_type"] == "G1M8_INVOICE_SERIES_ISSUE"
            # Decision output interop
            do = r.to_decision_output()
            assert do.what
            assert do.rule == "G1M_008"


# ══════════════════════════════════════════════════════════════════════════════
# Integration with real sample data
# ══════════════════════════════════════════════════════════════════════════════

class TestSampleDataIntegration:
    """Parse Sales_Register_Sample_Corrected.xlsx and inject issues."""

    @pytest.fixture()
    def parsed_sr_records(self):
        """Parse the sample SR file."""
        from app.parsers.sales_register_parser import parse_sales_register

        if not SAMPLE_SR.exists():
            pytest.skip(f"Sample SR file not found: {SAMPLE_SR}")

        content = SAMPLE_SR.read_bytes()
        result = parse_sales_register(content, SAMPLE_SR.name)
        assert result.get("success"), f"SR parse failed: {result.get('errors')}"
        return result["records"]

    def test_sample_data_parses_with_invoice_numbers(self, parsed_sr_records):
        """Confirm sample data has invoice_number populated per record."""
        assert len(parsed_sr_records) > 0
        for rec in parsed_sr_records:
            inv = rec.get("invoice_number") or rec.get("invoice_number_normalized")
            assert inv, f"Record missing invoice_number: {rec}"

    def test_inject_gap_detected(self, parsed_sr_records):
        """Inject a gap by removing a middle record's invoice number
        and confirm detection works with real data format.
        """
        records = [copy.deepcopy(r) for r in parsed_sr_records]

        # Create a controlled series with a contiguous gap of 3
        for i, rec in enumerate(records[:3]):
            rec["invoice_date"] = f"2026-05-{i + 1:02d}"
        records[0]["invoice_number"] = records[0]["invoice_number_normalized"] = "TEST/001"
        records[1]["invoice_number"] = records[1]["invoice_number_normalized"] = "TEST/002"
        records[2]["invoice_number"] = records[2]["invoice_number_normalized"] = "TEST/006"

        test_records = records[:3]  # TEST/001, TEST/002, TEST/006 → gap 3–5

        results = check_invoice_series_continuity(test_records)
        gap_results = [r for r in results if r.details.get("issue_type") == "gap"]
        assert len(gap_results) == 1
        assert gap_results[0].details["missing_numbers"] == [3, 4, 5]

    def test_inject_duplicate_detected(self, parsed_sr_records):
        """Inject a duplicate invoice number and confirm detection."""
        records = [copy.deepcopy(r) for r in parsed_sr_records]

        # Force the first two records to have the same invoice number
        dup_inv = "DUP/TEST/001"
        records[0]["invoice_number"] = dup_inv
        records[0]["invoice_number_normalized"] = dup_inv
        records[1]["invoice_number"] = dup_inv
        records[1]["invoice_number_normalized"] = dup_inv

        results = check_invoice_series_continuity(records)
        dup_results = [r for r in results if r.details.get("issue_type") == "duplicate"]

        # Should find our injected duplicate
        dup_invs = [d.details["invoice_number"] for d in dup_results]
        assert dup_inv in dup_invs

    def test_duplicate_source_label_display(self):
        """Confirm that duplicate messages distinguish between Sales Register and GSTR-1."""
        sr_recs = [
            _sr(inv="INV/001", inv_date="2026-05-01"),
            _sr(inv="INV/001", inv_date="2026-05-02"),
        ]
        g1_recs = [
            _sr(inv="G1INV/999", inv_date="2026-05-01"),
            _sr(inv="G1INV/999", inv_date="2026-05-02"),
        ]
        results = check_invoice_series_continuity(sr_recs, g1_recs)
        dup_results = {
            r.details["invoice_number"]: r
            for r in results
            if r.details.get("issue_type") == "duplicate"
        }
        assert "INV/001" in dup_results
        assert "G1INV/999" in dup_results

        sr_dup = dup_results["INV/001"]
        assert "in the Sales Register" in sr_dup.decision_what
        assert sr_dup.details.get("source") == "sales_register"

        g1_dup = dup_results["G1INV/999"]
        assert "in GSTR-1" in g1_dup.decision_what
        assert "in GSTR-1" in g1_dup.decision_next
        assert g1_dup.details.get("source") == "gstr1"
