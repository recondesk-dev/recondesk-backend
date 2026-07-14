"""Unit tests for confidence-threshold auto-triage."""

from app.services.auto_approve import (
    DEFAULT_AUTO_APPROVE_THRESHOLD,
    apply_confidence_auto_approve,
    normalize_confidence_threshold,
)


def test_normalize_threshold_clamps():
    assert normalize_confidence_threshold(95) == 95
    assert normalize_confidence_threshold(-10) == 0
    assert normalize_confidence_threshold(150) == 100
    assert normalize_confidence_threshold("bad") == DEFAULT_AUTO_APPROVE_THRESHOLD


def test_promotes_high_confidence_gstr_rows():
    clean = [{"gstr_id": "g1", "pr_id": "p1", "confidence_score": 100}]
    review = [
        {
            "gstr_id": "g2",
            "pr_id": "p2",
            "confidence_score": 96,
            "review_reason": "Amount/Date mismatch",
        },
        {
            "gstr_id": "g3",
            "pr_id": "p3",
            "confidence_score": 75,
            "review_reason": "AMOUNT_MISMATCH",
        },
    ]
    matched, remaining, n = apply_confidence_auto_approve(clean, review, 95)
    assert n == 1
    assert len(matched) == 2
    assert len(remaining) == 1
    promoted = matched[1]
    assert promoted["auto_approved"] is True
    assert promoted["match_status"] == "matched"
    assert promoted["match_status_text"] == "Auto-Approved"
    assert remaining[0]["gstr_id"] == "g3"


def test_skips_pr_only_markers():
    clean: list = []
    review = [
        {"gstr_id": "", "pr_id": "p1", "confidence_score": 100},
        {"pr_id": "p2", "confidence_score": 99},
    ]
    matched, remaining, n = apply_confidence_auto_approve(clean, review, 95)
    assert n == 0
    assert matched == []
    assert len(remaining) == 2


def test_match_confidence_fallback():
    clean: list = []
    review = [{"gstr_id": "g1", "pr_id": "p1", "match_confidence": 0.97}]
    matched, remaining, n = apply_confidence_auto_approve(clean, review, 95)
    assert n == 1
    assert len(matched) == 1
    assert remaining == []
