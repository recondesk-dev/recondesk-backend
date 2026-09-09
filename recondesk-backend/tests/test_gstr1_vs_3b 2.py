"""
Unit tests for app.reconciliation.gstr1_vs_3b.

Covers aggregation (sections, CDNs, rates), GSTR-3B extraction,
variance detection, tolerance boundaries, and the top-level reconcile
entry point.
"""

from __future__ import annotations

import pytest

from app.reconciliation.gstr1_vs_3b import (
    GSTR1Aggregate,
    GSTR3BSummary,
    TieOutVarianceType,
    FieldVariance,
    DEFAULT_TOLERANCE_PAISE,
    aggregate_gstr1,
    aggregate_gstr1_by_rate,
    gstr3b_to_summary,
    compute_variances,
    reconcile_gstr1_vs_3b,
)


# ──────────────────────────────────────────────────────────────────────────────
# Record builders
# ──────────────────────────────────────────────────────────────────────────────

def _g1_rec(
    *,
    section: str = "b2b",
    inv: str = "INV-001",
    taxable: int = 100000,
    igst: int = 18000,
    cgst: int = 0,
    sgst: int = 0,
    cess: int = 0,
    rate: float | None = 18.0,
) -> dict:
    rec = {
        "section": section,
        "invoice_number": inv,
        "taxable_amount_paise": taxable,
        "igst_paise": igst,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "cess_paise": cess,
    }
    if rate is not None:
        rec["rate"] = rate
    return rec


def _parsed_3b(
    *,
    taxable_value: float = 1000.0,
    igst: float = 180.0,
    cgst: float = 0.0,
    sgst: float = 0.0,
    cess: float = 0.0,
    ret_period: str = "2026-05",
) -> dict:
    """Mimic the output of gstr3b_parser.parse_gstr3b."""
    return {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": ret_period,
        "outward_supply": {
            "taxable_value": taxable_value,
            "igst": igst,
            "cgst": cgst,
            "sgst": sgst,
            "cess": cess,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Aggregation
# ══════════════════════════════════════════════════════════════════════════════

class TestAggregateGSTR1:

    def test_single_b2b_invoice(self):
        records = [_g1_rec(taxable=100000, igst=18000)]
        agg = aggregate_gstr1(records)
        assert agg.taxable_value_paise == 100000
        assert agg.igst_paise == 18000
        assert agg.total_tax_paise == 18000
        assert agg.record_count == 1

    def test_multiple_sections(self):
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
            _g1_rec(section="b2cl", taxable=200000, igst=36000, inv="INV-002"),
            _g1_rec(section="b2cs", taxable=50000, cgst=4500, sgst=4500, igst=0, inv="INV-003"),
        ]
        agg = aggregate_gstr1(records)
        assert agg.taxable_value_paise == 350000
        assert agg.igst_paise == 54000
        assert agg.cgst_paise == 4500
        assert agg.sgst_paise == 4500
        assert agg.record_count == 3

    def test_cdn_subtracted(self):
        """Credit notes reduce the aggregate."""
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
            _g1_rec(section="cdnr", taxable=20000, igst=3600, inv="CN-001"),
        ]
        agg = aggregate_gstr1(records)
        assert agg.taxable_value_paise == 80000
        assert agg.igst_paise == 14400
        assert agg.record_count == 2

    def test_cdn_excluded_when_flag_false(self):
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
            _g1_rec(section="cdnr", taxable=20000, igst=3600, inv="CN-001"),
        ]
        agg = aggregate_gstr1(records, include_cdn=False)
        assert agg.taxable_value_paise == 100000  # CDN not subtracted
        assert agg.record_count == 1

    def test_exports_excluded_by_default(self):
        """Zero-rated (exp) must be excluded so G1 matches Table 3.1(a) scope."""
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
            _g1_rec(section="exp", taxable=50000, igst=0, inv="EXP-001"),
        ]
        agg = aggregate_gstr1(records)
        assert agg.taxable_value_paise == 100000
        assert agg.record_count == 1

    def test_exports_included_when_flag_true(self):
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
            _g1_rec(section="exp", taxable=50000, igst=0, inv="EXP-001"),
        ]
        agg = aggregate_gstr1(records, include_zero_rated=True)
        assert agg.taxable_value_paise == 150000
        assert agg.record_count == 2

    def test_nil_hsn_excluded(self):
        """Informational sections are never included."""
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
            _g1_rec(section="nil", taxable=30000, igst=0, inv="NIL-001"),
            _g1_rec(section="hsn", taxable=100000, igst=18000, inv="HSN-001"),
        ]
        agg = aggregate_gstr1(records)
        assert agg.taxable_value_paise == 100000
        assert agg.record_count == 1

    def test_empty_records(self):
        agg = aggregate_gstr1([])
        assert agg.taxable_value_paise == 0
        assert agg.record_count == 0


class TestAggregateByRate:

    def test_grouping(self):
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000, rate=18.0),
            _g1_rec(section="b2b", taxable=200000, igst=10000, rate=5.0, inv="INV-002"),
            _g1_rec(section="b2b", taxable=50000, igst=9000, rate=18.0, inv="INV-003"),
        ]
        by_rate = aggregate_gstr1_by_rate(records)
        assert 18.0 in by_rate
        assert 5.0 in by_rate
        assert by_rate[18.0].taxable_value_paise == 150000
        assert by_rate[5.0].taxable_value_paise == 200000

    def test_none_rate_bucket(self):
        records = [_g1_rec(rate=None)]
        by_rate = aggregate_gstr1_by_rate(records)
        assert None in by_rate
        assert by_rate[None].record_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# GSTR-3B extraction
# ══════════════════════════════════════════════════════════════════════════════

class TestGSTR3BSummary:

    def test_basic_extraction(self):
        p = _parsed_3b(taxable_value=1000.0, igst=180.0, cgst=0, sgst=0)
        s = gstr3b_to_summary(p)
        assert s.taxable_value_paise == 100000
        assert s.igst_paise == 18000
        assert s.total_tax_paise == 18000

    def test_cgst_sgst(self):
        p = _parsed_3b(taxable_value=500.0, igst=0, cgst=45.0, sgst=45.0)
        s = gstr3b_to_summary(p)
        assert s.cgst_paise == 4500
        assert s.sgst_paise == 4500
        assert s.total_tax_paise == 9000

    def test_missing_outward_supply(self):
        s = gstr3b_to_summary({"outward_supply": None})
        assert s.taxable_value_paise == 0

    def test_cess(self):
        p = _parsed_3b(cess=25.50)
        s = gstr3b_to_summary(p)
        assert s.cess_paise == 2550


# ══════════════════════════════════════════════════════════════════════════════
# Variance detection
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVariances:

    def test_no_variances_exact_match(self):
        agg = GSTR1Aggregate(taxable_value_paise=100000, igst_paise=18000)
        summary = GSTR3BSummary(taxable_value_paise=100000, igst_paise=18000)
        variances = compute_variances(agg, summary)
        assert variances == []

    def test_within_tolerance_no_variance(self):
        """Diff of ₹1 (100 paise) → not flagged."""
        agg = GSTR1Aggregate(taxable_value_paise=100050, igst_paise=18000)
        summary = GSTR3BSummary(taxable_value_paise=100000, igst_paise=18000)
        variances = compute_variances(agg, summary, tolerance_paise=100)
        assert variances == []

    def test_exceeds_tolerance(self):
        """Diff of ₹5 → flagged."""
        agg = GSTR1Aggregate(taxable_value_paise=100500, igst_paise=18000)
        summary = GSTR3BSummary(taxable_value_paise=100000, igst_paise=18000)
        variances = compute_variances(agg, summary)
        assert len(variances) == 1
        assert variances[0].field == "taxable_value"
        assert variances[0].diff_paise == 500
        assert variances[0].variance_type == TieOutVarianceType.TAXABLE_VALUE

    def test_multiple_variances(self):
        agg = GSTR1Aggregate(
            taxable_value_paise=100500, igst_paise=20000,
            cgst_paise=1000, sgst_paise=1000,
        )
        summary = GSTR3BSummary(
            taxable_value_paise=100000, igst_paise=18000,
            cgst_paise=0, sgst_paise=0,
        )
        variances = compute_variances(agg, summary)
        fields = {v.field for v in variances}
        assert "taxable_value" in fields
        assert "igst" in fields
        assert "cgst" in fields
        assert "sgst" in fields
        # total_tax should also be flagged
        assert "total_tax" in fields

    def test_negative_diff_under_reported(self):
        """GSTR-1 < GSTR-3B → negative diff (under-reported in GSTR-1)."""
        agg = GSTR1Aggregate(taxable_value_paise=90000, igst_paise=18000)
        summary = GSTR3BSummary(taxable_value_paise=100000, igst_paise=18000)
        variances = compute_variances(agg, summary)
        assert len(variances) == 1
        assert variances[0].diff_paise == -10000
        assert variances[0].field == "taxable_value"

    def test_custom_tolerance(self):
        agg = GSTR1Aggregate(taxable_value_paise=100500, igst_paise=18000)
        summary = GSTR3BSummary(taxable_value_paise=100000, igst_paise=18000)
        # Widen tolerance to ₹10 → no variance
        variances = compute_variances(agg, summary, tolerance_paise=1000)
        assert variances == []


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

class TestReconcileGSTR1vs3B:

    def test_clean_tieout(self):
        """GSTR-1 totals match GSTR-3B within tolerance → clean."""
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
        ]
        p3b = _parsed_3b(taxable_value=1000.0, igst=180.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        assert result.is_clean is True
        assert result.variances == []
        assert result.mismatches == []
        assert result.ret_period == "2026-05"

    def test_variance_detected(self):
        """GSTR-1 total exceeds GSTR-3B → variance flagged."""
        records = [
            _g1_rec(section="b2b", taxable=120000, igst=21600),
        ]
        p3b = _parsed_3b(taxable_value=1000.0, igst=180.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        assert result.is_clean is False
        assert len(result.variances) >= 1
        assert len(result.mismatches) >= 1
        # Decision text should mention the period
        assert "2026-05" in result.mismatches[0].decision_what

    def test_mismatches_have_decision_format(self):
        """Mismatches follow WHAT/WHY/NEXT contract."""
        records = [_g1_rec(section="b2b", taxable=200000, igst=36000)]
        p3b = _parsed_3b(taxable_value=1000.0, igst=180.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        for m in result.mismatches:
            assert m.decision_what
            assert m.decision_why
            assert m.decision_next
            assert m.rule_id == "G1_3B_TIEOUT"
            # Liability mismatch → DRC-01B (not DRC-01C ITC intimation)
            assert "DRC-01B" in m.decision_why
            assert "DRC-01C" not in m.decision_why

    def test_cdn_affects_tieout(self):
        """CDN reducing GSTR-1 total should reduce variance."""
        records = [
            _g1_rec(section="b2b", taxable=120000, igst=21600),
            _g1_rec(section="cdnr", taxable=20000, igst=3600, inv="CN-001"),
        ]
        # GSTR-1 net = 100000 taxable, 18000 IGST
        p3b = _parsed_3b(taxable_value=1000.0, igst=180.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        assert result.is_clean is True

    def test_exports_do_not_create_false_variance_against_3_1a(self):
        """Exports/zero-rated in GSTR-1 must not skew Table 3.1(a) tie-out.

        Previously include_zero_rated=True inflated G1 taxable value while
        GSTR-3B only exposes osup_det (3.1a), causing a false variance for
        businesses with genuine zero-rated sales.
        """
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000),
            _g1_rec(section="exp", taxable=50000, igst=0, inv="EXP-001"),
            _g1_rec(section="expa", taxable=25000, igst=0, inv="EXP-002"),
        ]
        # 3.1(a) matches B2B only — zero-rated lives in 3.1(b), not compared here
        p3b = _parsed_3b(taxable_value=1000.0, igst=180.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        assert result.is_clean is True
        assert result.variances == []
        assert result.gstr1_aggregate.taxable_value_paise == 100000
        assert result.gstr1_aggregate.record_count == 1

    def test_summary_dict(self):
        records = [_g1_rec(section="b2b", taxable=100000, igst=18000, rate=18.0)]
        p3b = _parsed_3b(taxable_value=1000.0, igst=180.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        summary = result.summary_dict()
        assert summary["is_clean"] is True
        assert summary["ret_period"] == "2026-05"
        assert "18.0" in summary["gstr1_by_rate"]

    def test_rate_breakdown_in_result(self):
        records = [
            _g1_rec(section="b2b", taxable=100000, igst=18000, rate=18.0),
            _g1_rec(section="b2b", taxable=50000, igst=2500, rate=5.0, inv="INV-002"),
        ]
        p3b = _parsed_3b(taxable_value=1500.0, igst=205.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        assert 18.0 in result.gstr1_by_rate
        assert 5.0 in result.gstr1_by_rate
        assert result.gstr1_by_rate[18.0].taxable_value_paise == 100000
        assert result.gstr1_by_rate[5.0].taxable_value_paise == 50000

    def test_decision_output_interop(self):
        """Mismatches can be converted to DecisionOutput."""
        records = [_g1_rec(section="b2b", taxable=200000, igst=36000)]
        p3b = _parsed_3b(taxable_value=1000.0, igst=180.0)
        result = reconcile_gstr1_vs_3b(records, p3b)
        for m in result.mismatches:
            d = m.to_decision_output()
            assert d.what == m.decision_what
            assert d.rule == "G1_3B_TIEOUT"

    def test_empty_gstr1(self):
        """No GSTR-1 records but GSTR-3B has values → under-reported."""
        result = reconcile_gstr1_vs_3b([], _parsed_3b(taxable_value=1000.0, igst=180.0))
        assert result.is_clean is False
        assert any(v.diff_paise < 0 for v in result.variances)

    def test_empty_both(self):
        """No GSTR-1 and zero GSTR-3B → clean."""
        result = reconcile_gstr1_vs_3b(
            [], _parsed_3b(taxable_value=0, igst=0, cgst=0, sgst=0, cess=0),
        )
        assert result.is_clean is True
