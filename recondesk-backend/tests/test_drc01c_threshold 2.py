"""Unit tests for Rule 88D / DRC-01C dual-threshold detection.

Thresholds (50th GST Council para 4.35): excess more than 20% **as well as**
more than ₹25 lakh. Both conditions required.
"""

from __future__ import annotations

from app.services.gstr3b_reconciliation import (
    DRC01C_BELOW_THRESHOLD,
    DRC01C_CLEAR,
    DRC01C_EXCESS_AMOUNT_THRESHOLD,
    DRC01C_EXCESS_PCT_THRESHOLD,
    DRC01C_TRIGGER,
    compute_drc01c_threshold,
)


def test_defaults_match_council_recommendation():
    assert DRC01C_EXCESS_PCT_THRESHOLD == 20.0
    assert DRC01C_EXCESS_AMOUNT_THRESHOLD == 2_500_000.0


def test_clear_when_matched_or_underclaimed():
    r = compute_drc01c_threshold(claimed_total=100_000, available_total=100_000)
    assert r["threshold_status"] == DRC01C_CLEAR
    assert r["triggers_drc01c"] is False
    assert r["excess_amount"] == 0.0
    assert r["excess_pct"] == 0.0

    r2 = compute_drc01c_threshold(claimed_total=80_000, available_total=100_000)
    assert r2["threshold_status"] == DRC01C_CLEAR
    assert r2["excess_amount"] == -20_000.0
    assert r2["triggers_drc01c"] is False


def test_below_threshold_overclaim_pct_only():
    """25% overclaim but only ₹25k — under ₹25L absolute gate."""
    available = 100_000
    claimed = 125_000  # +25%
    r = compute_drc01c_threshold(claimed, available)
    assert r["excess_amount"] == 25_000.0
    assert r["excess_pct"] == 25.0
    assert r["threshold_status"] == DRC01C_BELOW_THRESHOLD
    assert r["triggers_drc01c"] is False


def test_below_threshold_amount_only():
    """₹30L excess but only 15% — under 20% gate."""
    available = 20_000_000
    claimed = 23_000_000  # +15%, excess ₹30L
    r = compute_drc01c_threshold(claimed, available)
    assert r["excess_amount"] == 3_000_000.0
    assert r["excess_pct"] == 15.0
    assert r["threshold_status"] == DRC01C_BELOW_THRESHOLD
    assert r["triggers_drc01c"] is False


def test_triggers_when_both_gates_exceeded():
    """₹30L and 30% → DRC01C_TRIGGER."""
    available = 10_000_000
    claimed = 13_000_000  # +30%, excess ₹30L
    r = compute_drc01c_threshold(claimed, available)
    assert r["excess_amount"] == 3_000_000.0
    assert r["excess_pct"] == 30.0
    assert r["threshold_status"] == DRC01C_TRIGGER
    assert r["triggers_drc01c"] is True
    assert r["pct_threshold"] == 20.0
    assert r["amount_threshold"] == 2_500_000.0


def test_boundary_exactly_at_thresholds_does_not_trigger():
    """Council wording is 'more than' 20% and 'more than' ₹25L — equality is not a trigger."""
    available = 12_500_000
    # Exactly +20% and exactly ₹25L
    claimed = available + 2_500_000
    r = compute_drc01c_threshold(claimed, available)
    assert r["excess_amount"] == 2_500_000.0
    assert r["excess_pct"] == 20.0
    assert r["triggers_drc01c"] is False
    assert r["threshold_status"] == DRC01C_BELOW_THRESHOLD


def test_available_zero_claimed_positive_uses_amount_gate_only():
    """Division by zero: % treated as exceeded; ₹25L gate still required."""
    r = compute_drc01c_threshold(claimed_total=100_000, available_total=0)
    assert r["excess_amount"] == 100_000.0
    assert r["excess_pct"] is None
    assert r["triggers_drc01c"] is False
    assert r["threshold_status"] == DRC01C_BELOW_THRESHOLD

    r2 = compute_drc01c_threshold(claimed_total=3_000_000, available_total=0)
    assert r2["excess_pct"] is None
    assert r2["triggers_drc01c"] is True
    assert r2["threshold_status"] == DRC01C_TRIGGER


def test_configurable_thresholds():
    r = compute_drc01c_threshold(
        claimed_total=120, available_total=100,
        pct_threshold=10.0, amount_threshold=15.0,
    )
    assert r["triggers_drc01c"] is True
    assert r["pct_threshold"] == 10.0
    assert r["amount_threshold"] == 15.0
