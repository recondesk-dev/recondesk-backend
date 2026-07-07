"""Tests for the review-required decision layer (populate_review_decisions)."""
from app.decisions.layer import populate_review_decisions, _decision_for_review_row


def _make_review_row(review_reason, *, confidence=50, taxable_diff=10000, match_level=3):
    return {
        "gstr_id": "gstr-1",
        "pr_id": "pr-1",
        "confidence_score": confidence,
        "match_status": "review_required",
        "review_reason": review_reason,
        "reason": review_reason,
        "match_level": match_level,
        "taxable_diff_paise": taxable_diff,
        "supplier_gstin": "27AAACE1234F1Z5",
    }


class TestDecisionForReviewRow:
    """Each known review_reason produces a non-empty, non-fallback decision."""

    def test_amount_mismatch(self):
        d = _decision_for_review_row(_make_review_row("Amount/Date mismatch"))
        assert d.rule == "REVIEW_AMOUNT_MISMATCH"
        assert "50%" in d.what  # confidence
        assert "₹100.00" in d.what  # diff

    def test_gstin_mismatch(self):
        d = _decision_for_review_row(_make_review_row("GSTIN_MISMATCH"))
        assert d.rule == "REVIEW_GSTIN_MISMATCH"
        assert "GSTIN" in d.what
        assert "27AAACE1234F1Z5" in d.next

    def test_duplicate_ambiguity(self):
        d = _decision_for_review_row(_make_review_row("DUPLICATE_AMBIGUITY"))
        assert d.rule == "REVIEW_DUPLICATE_AMBIGUITY"
        assert "Duplicate" in d.what or "duplicate" in d.what.lower()

    def test_duplicate_conflict(self):
        d = _decision_for_review_row(_make_review_row("DUPLICATE_CONFLICT"))
        assert d.rule == "REVIEW_DUPLICATE_AMBIGUITY"

    def test_multiple_candidates(self):
        d = _decision_for_review_row(_make_review_row("MULTIPLE_CANDIDATES"))
        assert d.rule == "REVIEW_MULTIPLE_CANDIDATES"
        assert "Multiple" in d.what or "candidates" in d.what.lower()

    def test_possible_match(self):
        d = _decision_for_review_row(_make_review_row("POSSIBLE_MATCH"))
        assert d.rule == "REVIEW_POSSIBLE_MATCH"
        assert "50%" in d.what

    def test_unknown_reason_uses_generic(self):
        d = _decision_for_review_row(_make_review_row("SOME_NEW_REASON"))
        assert d.rule == "REVIEW_GENERIC"
        assert "50%" in d.what

    def test_all_reasons_produce_nonempty(self):
        for reason in (
            "AMOUNT_MISMATCH", "Amount/Date mismatch", "GSTIN_MISMATCH",
            "DUPLICATE_AMBIGUITY", "DUPLICATE_AMBIGUITY_PR", "DUPLICATE_CONFLICT",
            "MULTIPLE_CANDIDATES", "POSSIBLE_MATCH", "UNKNOWN_REASON",
        ):
            d = _decision_for_review_row(_make_review_row(reason))
            assert d.what and d.what != "—", f"Empty what for {reason}"
            assert d.why and d.why != "—", f"Empty why for {reason}"
            assert d.next and d.next != "—", f"Empty next for {reason}"
            assert d.confidence == "LOW"


class TestPopulateReviewDecisions:
    """populate_review_decisions enriches all rows with decision_* fields."""

    def test_enriches_all_rows(self):
        rows = [
            _make_review_row("Amount/Date mismatch"),
            _make_review_row("GSTIN_MISMATCH"),
            _make_review_row("POSSIBLE_MATCH"),
        ]
        enriched = populate_review_decisions(rows)
        assert len(enriched) == 3
        for r in enriched:
            assert r.get("decision_what"), f"Missing decision_what: {r}"
            assert r.get("decision_why"), f"Missing decision_why: {r}"
            assert r.get("decision_next"), f"Missing decision_next: {r}"
            assert r.get("decision_rule"), f"Missing decision_rule: {r}"
            assert r.get("decision_confidence") == "LOW"

    def test_preserves_original_fields(self):
        """Decision enrichment must not lose existing row fields."""
        rows = [_make_review_row("GSTIN_MISMATCH")]
        enriched = populate_review_decisions(rows)
        assert enriched[0]["gstr_id"] == "gstr-1"
        assert enriched[0]["pr_id"] == "pr-1"
        assert enriched[0]["review_reason"] == "GSTIN_MISMATCH"
        assert enriched[0]["taxable_diff_paise"] == 10000

    def test_empty_list_returns_empty(self):
        assert populate_review_decisions([]) == []

    def test_zero_confidence_renders_zero(self):
        row = _make_review_row("POSSIBLE_MATCH", confidence=0)
        enriched = populate_review_decisions([row])
        assert "0%" in enriched[0]["decision_what"]

    def test_zero_diff_renders_zero(self):
        row = _make_review_row("Amount/Date mismatch", taxable_diff=0)
        enriched = populate_review_decisions([row])
        assert "₹0.00" in enriched[0]["decision_what"]
