"""Run-level confidence summary aggregation (read-only)."""

from __future__ import annotations

from app.services.reconciliation_outcomes import (
    OutcomeRow,
    build_confidence_summary,
    confidence_bucket,
)


def _row(
    *,
    id: str,
    category: str,
    match_confidence=None,
) -> OutcomeRow:
    return OutcomeRow(
        id=id,
        category=category,
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV1",
        invoice_date="2026-01-15",
        match_status="MATCHED",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="x",
        decision_why="y",
        decision_next="z",
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=100,
        match_confidence=match_confidence,
    )


def test_confidence_bucket_thresholds_match_badge():
    assert confidence_bucket(None, linked=True) == "high"
    assert confidence_bucket(0.90, linked=True) == "high"
    assert confidence_bucket(0.95, linked=True) == "high"
    assert confidence_bucket(0.75, linked=True) == "medium"
    assert confidence_bucket(0.89, linked=True) == "medium"
    assert confidence_bucket(0.74, linked=True) == "low"
    assert confidence_bucket(0.50, linked=True) == "low"
    assert confidence_bucket(None, linked=False) == "unmatched"
    # Accidental 0–100 scale still buckets correctly
    assert confidence_bucket(92, linked=True) == "high"
    assert confidence_bucket(80, linked=True) == "medium"
    assert confidence_bucket(60, linked=True) == "low"


def test_build_confidence_summary_buckets_sum_to_total():
    rows = [
        _row(id="pm:1", category="matched", match_confidence=None),  # high exact
        _row(id="pm:2", category="matched", match_confidence=0.95),  # high fuzzy
        _row(id="rrp:3-a", category="review_required", match_confidence=0.80),  # med
        _row(id="rrp:4-b", category="review_required", match_confidence=0.60),  # low
        _row(id="mi:5", category="missed_itc"),  # unmatched
        _row(id="dp:6", category="review_required"),  # PR marker — skipped
        _row(id="wr:7", category="wrongful_itc_risk"),  # ignored
    ]
    summary = build_confidence_summary("run-abc", rows)
    assert summary == {
        "run_id": "run-abc",
        "total_invoices": 5,
        "high_confidence": 2,
        "medium_confidence": 1,
        "low_confidence": 1,
        "unmatched": 1,
    }
    assert (
        summary["high_confidence"]
        + summary["medium_confidence"]
        + summary["low_confidence"]
        + summary["unmatched"]
        == summary["total_invoices"]
    )


def test_empty_rows_zero_summary():
    summary = build_confidence_summary("run-empty", [])
    assert summary["total_invoices"] == 0
    assert summary["high_confidence"] == 0
    assert summary["unmatched"] == 0
