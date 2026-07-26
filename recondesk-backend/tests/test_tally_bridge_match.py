"""Unit tests for Tally Bridge bill_ref → invoice matching (reuse matcher helpers)."""

from app.services.tally_bridge_sync import (
    is_confident_bill_match,
    score_bill_ref_against_invoice,
)


def test_exact_normalized_bill_ref_is_confident():
    score = score_bill_ref_against_invoice("INV/2024/001", "INV-2024-001")
    assert score >= 0.85
    assert is_confident_bill_match(score)


def test_weak_similarity_not_confident():
    score = score_bill_ref_against_invoice("ABC123", "XYZ999")
    assert score < 0.85
    assert not is_confident_bill_match(score)


def test_ambiguous_near_tie_rejected():
    assert not is_confident_bill_match(0.90, 0.88)
    assert is_confident_bill_match(0.90, 0.70)
