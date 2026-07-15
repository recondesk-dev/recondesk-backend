"""
Unit tests for app.rules.gstr1_mismatch_rules.

Covers all six mismatch types (G1M1–G1M6), edge cases, tolerance
boundaries, the batch classifier, and DecisionOutput interop.
"""

from __future__ import annotations

import pytest

from app.rules.gstr1_mismatch_rules import (
    MismatchType,
    MismatchSeverity,
    MismatchResult,
    classify_missing_invoice,
    classify_extra_invoice,
    classify_amount_mismatch,
    classify_wrong_classification,
    classify_rate_mismatch,
    classify_period_mismatch,
    classify_all_mismatches,
    AMOUNT_TOLERANCE_PAISE,
    AMOUNT_TOLERANCE_PCT,
)


# ──────────────────────────────────────────────────────────────────────────────
# Record builders
# ──────────────────────────────────────────────────────────────────────────────

def _sr(
    *,
    inv: str = "SR-100",
    gstin: str = "27BBBFV1234A1ZP",
    taxable: int = 200000,
    tax: int = 36000,
    igst: int = 36000,
    inv_date: str = "2026-05-10",
    rate: float | None = None,
    name: str = "XYZ Enterprises",
) -> dict:
    rec = {
        "invoice_number": inv,
        "gstin": gstin,
        "recipient_name": name,
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "igst_paise": igst,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }
    if rate is not None:
        rec["gst_rate"] = rate
    return rec


def _g1(
    *,
    inv: str = "SR-100",
    gstin: str = "27BBBFV1234A1ZP",
    taxable: int = 200000,
    tax: int = 36000,
    igst: int = 36000,
    inv_date: str = "2026-05-10",
    rate: float | None = None,
    name: str = "XYZ Enterprises",
    fp: str | None = None,
) -> dict:
    rec = {
        "invoice_number": inv,
        "recipient_gstin": gstin,
        "recipient_name": name,
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "igst_paise": igst,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }
    if rate is not None:
        rec["gst_rate"] = rate
    if fp is not None:
        rec["filing_period"] = fp
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# G1M1 — Missing invoice
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingInvoice:

    def test_basic(self):
        r = classify_missing_invoice(_sr())
        assert r.mismatch_type == MismatchType.MISSING_INVOICE
        assert r.severity == MismatchSeverity.CRITICAL
        assert r.rule_id == "G1M_001"
        assert "SR-100" in r.decision_what
        assert "missing" in r.decision_what.lower()

    def test_decision_output_interop(self):
        r = classify_missing_invoice(_sr())
        d = r.to_decision_output()
        assert d.what == r.decision_what
        assert d.why == r.decision_why
        assert d.next == r.decision_next
        assert d.rule == "G1M_001"
        assert d.confidence == "HIGH"  # CRITICAL → HIGH confidence

    def test_to_dict(self):
        r = classify_missing_invoice(_sr())
        d = r.to_dict()
        assert d["mismatch_type"] == "G1M1_MISSING_INVOICE"
        assert d["decision_what"] == r.decision_what
        assert d["invoice_number"] == "SR-100"


# ══════════════════════════════════════════════════════════════════════════════
# G1M2 — Extra invoice
# ══════════════════════════════════════════════════════════════════════════════

class TestExtraInvoice:

    def test_basic(self):
        r = classify_extra_invoice(_g1())
        assert r.mismatch_type == MismatchType.EXTRA_INVOICE
        assert r.severity == MismatchSeverity.HIGH
        assert r.rule_id == "G1M_002"
        assert "SR-100" in r.decision_what
        assert "Sales Register" in r.decision_what

    def test_decision_output_interop(self):
        r = classify_extra_invoice(_g1())
        d = r.to_decision_output()
        assert d.rule == "G1M_002"
        assert d.confidence == "MEDIUM"  # HIGH → MEDIUM confidence


# ══════════════════════════════════════════════════════════════════════════════
# G1M3 — Amount mismatch
# ══════════════════════════════════════════════════════════════════════════════

class TestAmountMismatch:

    def test_within_tolerance_returns_none(self):
        """Amount diff ≤ ₹1 → no mismatch."""
        r = classify_amount_mismatch(
            _sr(taxable=100000, tax=18000),
            _g1(taxable=100050, tax=18000),
        )
        assert r is None

    def test_exceeds_tolerance(self):
        """Taxable diff > ₹1 and > 1% → mismatch."""
        r = classify_amount_mismatch(
            _sr(taxable=100000, tax=18000),
            _g1(taxable=105000, tax=18900),
        )
        assert r is not None
        assert r.mismatch_type == MismatchType.AMOUNT_MISMATCH
        assert r.rule_id == "G1M_003"
        assert "taxable_amount" in r.details["differed_fields"]

    def test_large_diff_critical_severity(self):
        """Taxable diff > ₹500 → CRITICAL severity."""
        r = classify_amount_mismatch(
            _sr(taxable=100000, tax=18000),
            _g1(taxable=200000, tax=36000),
        )
        assert r is not None
        assert r.severity == MismatchSeverity.CRITICAL

    def test_tax_only_diff(self):
        """Taxable matches but tax differs → flags total_tax."""
        r = classify_amount_mismatch(
            _sr(taxable=100000, tax=18000),
            _g1(taxable=100000, tax=12000),
        )
        assert r is not None
        assert "total_tax" in r.details["differed_fields"]

    def test_pct_tolerance(self):
        """Within pct tolerance even though > abs tolerance → None."""
        # 0.5% of 10,00,000 = 5,000 paise (₹50)
        # 200 paise diff > 100 abs tol but 0.02% < 1% pct tol
        r = classify_amount_mismatch(
            _sr(taxable=1000000, tax=180000),
            _g1(taxable=1000200, tax=180000),
        )
        assert r is None

    def test_custom_tolerance(self):
        """Custom tolerances can widen the acceptance band."""
        r = classify_amount_mismatch(
            _sr(taxable=100000, tax=18000),
            _g1(taxable=110000, tax=19800),
            tolerance_paise=50000,
            tolerance_pct=0.15,
        )
        assert r is None


# ══════════════════════════════════════════════════════════════════════════════
# G1M4 — Wrong classification
# ══════════════════════════════════════════════════════════════════════════════

class TestWrongClassification:

    def test_same_classification_returns_none(self):
        """Both B2B → no mismatch."""
        r = classify_wrong_classification(_sr(), _g1())
        assert r is None

    def test_b2b_vs_b2c(self):
        """SR has GSTIN (B2B) but GSTR-1 is URP (B2C)."""
        r = classify_wrong_classification(
            _sr(gstin="27BBBFV1234A1ZP"),
            _g1(gstin="URP"),
        )
        assert r is not None
        assert r.mismatch_type == MismatchType.WRONG_CLASSIFICATION
        assert r.severity == MismatchSeverity.CRITICAL
        assert r.details["sr_classification"] == "B2B"
        assert r.details["gstr1_classification"] == "B2C"

    def test_b2c_vs_b2b(self):
        """SR has no GSTIN (B2C) but GSTR-1 has one (B2B)."""
        r = classify_wrong_classification(
            _sr(gstin=""),
            _g1(gstin="27BBBFV1234A1ZP"),
        )
        assert r is not None
        assert r.details["sr_classification"] == "B2C"
        assert r.details["gstr1_classification"] == "B2B"

    def test_both_b2c_returns_none(self):
        r = classify_wrong_classification(
            _sr(gstin=""),
            _g1(gstin=""),
        )
        assert r is None


# ══════════════════════════════════════════════════════════════════════════════
# G1M5 — Rate mismatch
# ══════════════════════════════════════════════════════════════════════════════

class TestRateMismatch:

    def test_same_rate_returns_none(self):
        r = classify_rate_mismatch(
            _sr(rate=18.0),
            _g1(rate=18.0),
        )
        assert r is None

    def test_different_rate(self):
        r = classify_rate_mismatch(
            _sr(rate=18.0),
            _g1(rate=12.0),
        )
        assert r is not None
        assert r.mismatch_type == MismatchType.RATE_MISMATCH
        assert r.details["sr_rate"] == 18.0
        assert r.details["gstr1_rate"] == 12.0

    def test_computed_rate_from_amounts(self):
        """Rate detected from taxable/tax amounts when no explicit field."""
        r = classify_rate_mismatch(
            _sr(taxable=100000, tax=18000),    # 18%
            _g1(taxable=100000, tax=12000),    # 12%
        )
        assert r is not None
        assert r.details["sr_rate"] == 18.0
        assert r.details["gstr1_rate"] == 12.0

    def test_rate_within_tolerance_returns_none(self):
        """Rates within 0.5pp tolerance → no mismatch."""
        r = classify_rate_mismatch(
            _sr(rate=18.0),
            _g1(rate=18.3),
        )
        assert r is None

    def test_both_missing_returns_none(self):
        """No rate info on either side → None."""
        r = classify_rate_mismatch(
            _sr(taxable=0, tax=0),
            _g1(taxable=0, tax=0),
        )
        assert r is None


# ══════════════════════════════════════════════════════════════════════════════
# G1M6 — Filing period mismatch
# ══════════════════════════════════════════════════════════════════════════════

class TestPeriodMismatch:

    def test_same_period_returns_none(self):
        r = classify_period_mismatch(
            _sr(inv_date="2026-05-10"),
            _g1(inv_date="2026-05-10", fp="052026"),
        )
        assert r is None

    def test_different_period(self):
        r = classify_period_mismatch(
            _sr(inv_date="2026-04-28"),
            _g1(inv_date="2026-04-28", fp="052026"),
        )
        assert r is not None
        assert r.mismatch_type == MismatchType.PERIOD_MISMATCH
        assert r.details["months_diff"] == 1
        assert "Apr-2026" in r.decision_what
        assert "May-2026" in r.decision_what

    def test_multi_month_high_severity(self):
        """More than 1 month gap → HIGH severity."""
        r = classify_period_mismatch(
            _sr(inv_date="2026-03-15"),
            _g1(inv_date="2026-03-15", fp="062026"),
        )
        assert r is not None
        assert r.severity == MismatchSeverity.HIGH
        assert r.details["months_diff"] == 3

    def test_explicit_filing_period_override(self):
        """gstr1_filing_period kwarg overrides record field."""
        r = classify_period_mismatch(
            _sr(inv_date="2026-05-10"),
            _g1(inv_date="2026-05-10"),  # no fp field
            gstr1_filing_period="072026",
        )
        assert r is not None
        assert r.details["months_diff"] == 2

    def test_missing_date_returns_none(self):
        r = classify_period_mismatch(
            _sr(inv_date=""),
            _g1(fp="052026"),
        )
        assert r is None


# ══════════════════════════════════════════════════════════════════════════════
# Batch classifier
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchClassifier:

    def test_all_types_detected(self):
        results = classify_all_mismatches(
            unmatched_sr=[_sr(inv="MISS-1")],
            unmatched_gstr1=[_g1(inv="EXTRA-1")],
            matched_pairs=[
                (_sr(taxable=100000, tax=18000), _g1(taxable=120000, tax=21600)),
                (_sr(gstin="27BBBFV1234A1ZP"), _g1(gstin="URP")),
                (_sr(rate=18.0), _g1(rate=12.0)),
                (_sr(inv_date="2026-04-28"), _g1(inv_date="2026-04-28", fp="062026")),
            ],
        )
        types = {r.mismatch_type for r in results}
        assert MismatchType.MISSING_INVOICE in types
        assert MismatchType.EXTRA_INVOICE in types
        assert MismatchType.AMOUNT_MISMATCH in types
        assert MismatchType.WRONG_CLASSIFICATION in types
        assert MismatchType.RATE_MISMATCH in types
        assert MismatchType.PERIOD_MISMATCH in types

    def test_sorted_by_severity(self):
        results = classify_all_mismatches(
            unmatched_sr=[_sr(inv="MISS-1")],
            matched_pairs=[
                (_sr(inv_date="2026-04-28"), _g1(inv_date="2026-04-28", fp="052026")),
            ],
        )
        # CRITICAL (missing) should come before MEDIUM (period 1-month)
        assert results[0].severity == MismatchSeverity.CRITICAL
        assert results[-1].severity == MismatchSeverity.MEDIUM

    def test_empty_inputs(self):
        results = classify_all_mismatches()
        assert results == []

    def test_no_mismatches_on_clean_pairs(self):
        """Matched pair with no discrepancies → empty result."""
        results = classify_all_mismatches(
            matched_pairs=[(_sr(), _g1())],
        )
        assert results == []
