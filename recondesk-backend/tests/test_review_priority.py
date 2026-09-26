"""Tests for Review Required Priority & Triage Engine."""

import pytest
from app.services.review_priority import (
    PRIORITY_URGENT,
    PRIORITY_HIGH,
    PRIORITY_MEDIUM,
    PRIORITY_LOW,
    classify_review_priority,
    review_priority_sort_key,
)


def test_urgent_statutory_reasons():
    """Statutory violations and high-risk audit traps must be classified as URGENT."""
    assert classify_review_priority({"review_reason": "DOC_TYPE_NOTE_IN_B2B"}) == PRIORITY_URGENT
    assert classify_review_priority({"review_reason": "PERIOD_BOUNDARY_DATE_MISMATCH"}) == PRIORITY_URGENT
    assert classify_review_priority({"review_reason": "GSTIN_MISMATCH"}) == PRIORITY_URGENT
    assert classify_review_priority({"reason": "GSTIN_MISMATCH: same PAN, different GSTIN"}) == PRIORITY_URGENT


def test_urgent_high_financial_magnitude():
    """Discrepancies >= ₹50,000 (5,000,000 paise) must be URGENT regardless of reason."""
    assert classify_review_priority({
        "review_reason": "AMOUNT_MISMATCH",
        "taxable_diff_paise": 5_000_000,  # ₹50,000
    }) == PRIORITY_URGENT

    assert classify_review_priority({
        "reason": "General variance",
        "amount_diff": 12_500_000,  # ₹1,25,000
    }) == PRIORITY_URGENT


def test_high_duplicate_and_material_discrepancy():
    """Duplicate ambiguities or amount differences >= ₹5,000 or > 2% must be HIGH."""
    assert classify_review_priority({"review_reason": "DUPLICATE_AMBIGUITY"}) == PRIORITY_HIGH
    assert classify_review_priority({"review_reason": "DUPLICATE_CONFLICT"}) == PRIORITY_HIGH

    # ₹10,000 difference (1,000,000 paise)
    assert classify_review_priority({
        "review_reason": "AMOUNT_MISMATCH",
        "taxable_diff_paise": 1_000_000,
    }) == PRIORITY_HIGH

    # > 2% difference with smaller absolute delta
    assert classify_review_priority({
        "review_reason": "AMOUNT_MISMATCH",
        "taxable_diff_paise": 40_000,  # ₹400
        "amount_difference_pct": 5.5,
    }) == PRIORITY_HIGH


def test_medium_moderate_discrepancy_and_typos():
    """Discrepancies >= ₹100 or invoice number typos must be MEDIUM."""
    assert classify_review_priority({
        "review_reason": "AMOUNT_MISMATCH",
        "taxable_diff_paise": 25_000,  # ₹250
    }) == PRIORITY_MEDIUM

    assert classify_review_priority({
        "review_reason": "Invoice number typo in prefix",
        "taxable_diff_paise": 0,
    }) == PRIORITY_MEDIUM


def test_low_trivial_roundoffs():
    """Trivial rounding errors (< ₹100) must be classified as LOW."""
    assert classify_review_priority({
        "review_reason": "AMOUNT_MISMATCH",
        "taxable_diff_paise": 150,  # ₹1.50
    }) == PRIORITY_LOW

    assert classify_review_priority({
        "review_reason": "Exact match with minor format",
        "taxable_diff_paise": 0,
    }) == PRIORITY_LOW


def test_review_priority_sort_key_ordering():
    """Sort key must order: URGENT first, then HIGH, then MEDIUM, then LOW (with highest diff first)."""
    rows = [
        {"id": "low_1", "priority": PRIORITY_LOW, "taxable_diff_paise": 100, "amount": 1000},
        {"id": "urgent_date", "review_reason": "PERIOD_BOUNDARY_DATE_MISMATCH", "taxable_diff_paise": 0, "amount": 50000},
        {"id": "high_1", "priority": PRIORITY_HIGH, "taxable_diff_paise": 600_000, "amount": 80000},
        {"id": "urgent_huge", "review_reason": "AMOUNT_MISMATCH", "taxable_diff_paise": 10_000_000, "amount": 200000},
        {"id": "medium_1", "priority": PRIORITY_MEDIUM, "taxable_diff_paise": 30_000, "amount": 5000},
    ]

    sorted_rows = sorted(rows, key=review_priority_sort_key)
    sorted_ids = [r["id"] for r in sorted_rows]

    # urgent_huge has 10,000,000 paise diff, urgent_date has 0
    assert sorted_ids[0] == "urgent_huge"
    assert sorted_ids[1] == "urgent_date"
    assert sorted_ids[2] == "high_1"
    assert sorted_ids[3] == "medium_1"
    assert sorted_ids[4] == "low_1"
