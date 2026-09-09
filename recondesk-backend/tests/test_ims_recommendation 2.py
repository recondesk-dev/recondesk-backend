"""Unit tests for IMS recommendation — real matcher confidence + Rule 37 / 17(5)."""

from __future__ import annotations

from app.ims.ims_recommendation import (
    CONFIDENCE_HIGH_MIN,
    HIGH_CONFIDENCE_ACCEPT_MIN,
    InvoiceRecommendationInput,
    is_high_confidence_accept,
    recommend_batch,
    recommend_invoice,
    resolve_confidence,
    unavailable,
)
from app.ims.ims_writeback_client import (
    ConfirmedInvoiceAction,
    ca_action_to_gstn,
    is_override,
    outcome_from_poll,
)
from app.services.sandbox_gst_client import IMSCheckStatusResponse


def test_unavailable_is_not_confirmed_zero():
    batch = unavailable("no_reconcile_payload", run_id="r1")
    assert batch.available is False
    assert batch.invoices == []
    assert batch.reason == "no_reconcile_payload"


def test_confidence_score_comes_from_row_not_constant():
    """Regression: confidence_score must equal the row's match_confidence.

    Fails if the engine reverts to hardcoded 0.92 / 0.88 / etc.
    """
    _HARDCODED_OLD = {0.92, 0.88, 0.58, 0.62, 0.48, 0.5, 0.45, 0.4}
    scores: list[float] = []
    for raw in (0.97, 0.91, 0.73, 0.41):
        rec = recommend_invoice(
            InvoiceRecommendationInput(
                invoice_id=f"pm:{raw}",
                supplier_gstin="27AAAAA0000A1Z5",
                invoice_number=f"INV-{raw}",
                category="matched",
                match_status="MATCHED",
                ims_status="no_action_taken",
                match_confidence=raw,
            )
        )
        assert rec is not None
        assert rec.confidence_score == raw
        assert rec.confidence_source == "matcher_fuzzy"
        assert rec.confidence_score not in _HARDCODED_OLD
        scores.append(rec.confidence_score)
    # Distinct row inputs must produce distinct output scores (not one table stamp).
    assert len(set(scores)) == 4


def test_high_fuzzy_accept_requires_no_rule37_no_175():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-1",
            category="matched",
            match_status="MATCHED",
            ims_status="no_action_taken",
            match_confidence=0.95,
            rule37_flag=False,
            blocked_credit_flag=False,
        )
    )
    assert rec is not None
    assert rec.recommended_action == "accept"
    assert rec.confidence_score == 0.95
    assert is_high_confidence_accept(rec)
    assert "0.95" in rec.human_readable_why or "95%" in rec.human_readable_why


def test_exact_match_without_fuzzy_score_does_not_invent_confidence():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:exact",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-EXACT",
            category="matched",
            match_status="MATCHED",
            ims_status="no_action_taken",
            match_confidence=None,
        )
    )
    assert rec is not None
    assert rec.recommended_action == "accept"
    assert rec.confidence_score is None
    assert rec.confidence_source == "matcher_exact_no_fuzzy_score"
    assert "not fabricated" in rec.human_readable_why.lower() or "blank" in rec.human_readable_why.lower()
    assert is_high_confidence_accept(rec)


def test_low_matcher_confidence_holds_even_when_matched():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:low",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-LOW",
            category="matched",
            match_status="MATCHED",
            ims_status="no_action_taken",
            match_confidence=0.72,
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert rec.confidence_score == 0.72
    assert "72%" in rec.human_readable_why or "0.72" in rec.human_readable_why
    assert not is_high_confidence_accept(rec)


def test_rule37_flag_blocks_accept_even_with_high_confidence():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:r37",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-R37",
            category="matched",
            match_status="MATCHED",
            ims_status="no_action_taken",
            match_confidence=0.99,
            rule37_flag=True,
            rule37_days_remaining=38,
            rule37_status="WARNING_30_DAYS",
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert rec.confidence_score == 0.99
    assert "38" in rec.human_readable_why
    assert "142" in rec.human_readable_why  # 180 - 38
    assert "WARNING_30_DAYS" in rec.human_readable_why
    assert "approaching deadline" not in rec.human_readable_why.lower()


def test_rule37_overdue_uses_negative_day_count():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="r37:pr9",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-OVER",
            category="rule37_warnings",
            ims_status="no_action_taken",
            rule37_flag=True,
            rule37_days_remaining=-12,
            rule37_status="OVERDUE_UNPAID",
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert rec.confidence_score is None
    assert rec.confidence_source == "unavailable"
    assert "12" in rec.human_readable_why
    assert "days_remaining=-12" in rec.human_readable_why


def test_blocked_credit_cites_real_17_5_subclause():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="bc:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-BC",
            category="blocked_credit",
            ims_status="no_action_taken",
            blocked_credit_flag=True,
            blocked_credit_category="Motor vehicles (<13 seater) -- Section 17(5)(a)",
            blocked_credit_reason=(
                "HSN 8703 falls under Motor vehicles (<13 seater) -- Section 17(5)(a). "
                "Verify before claiming ITC -- likely blocked under Section 17(5)"
            ),
            match_confidence=None,
        )
    )
    assert rec is not None
    assert rec.recommended_action == "reject"
    assert rec.confidence_score is None
    assert "17(5)(a)" in rec.human_readable_why
    assert "flagged as blocked ITC" not in rec.human_readable_why.lower()


def test_blocked_flag_on_matched_row_rejects_before_accept():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:bc",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-MATCH-BC",
            category="matched",
            match_status="MATCHED",
            match_confidence=0.96,
            blocked_credit_flag=True,
            blocked_credit_category="Food preparations -- Section 17(5)(b)",
        )
    )
    assert rec is not None
    assert rec.recommended_action == "reject"
    assert rec.confidence_score == 0.96
    assert "17(5)(b)" in rec.human_readable_why


def test_gstin_mismatch_uses_computed_gstins():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="gm:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-GM",
            category="gstin_mismatch",
            ims_status="no_action_taken",
            pr_supplier_gstin="27AAAAA0000A1Z5",
            gstr_supplier_gstin="29BBBBB0000B1Z3",
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert "27AAAAA0000A1Z5" in rec.human_readable_why
    assert "29BBBBB0000B1Z3" in rec.human_readable_why


def test_already_accepted_skipped():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:2",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-2",
            category="matched",
            ims_status="accepted",
            match_confidence=0.99,
        )
    )
    assert rec is None


def test_review_required_holds_with_real_confidence():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="rr:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-4",
            category="review_required",
            ims_status="pending",
            match_confidence=0.81,
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert rec.confidence_score == 0.81
    assert "81%" in rec.human_readable_why


def test_recommend_batch_high_count_uses_real_scores():
    batch = recommend_batch(
        [
            InvoiceRecommendationInput(
                invoice_id="a",
                supplier_gstin="27AAAAA0000A1Z5",
                invoice_number="A",
                category="matched",
                match_status="MATCHED",
                match_confidence=0.95,
            ),
            InvoiceRecommendationInput(
                invoice_id="b",
                supplier_gstin="27AAAAA0000A1Z5",
                invoice_number="B",
                category="matched",
                match_status="MATCHED",
                match_confidence=0.70,
            ),
            InvoiceRecommendationInput(
                invoice_id="c",
                supplier_gstin="27AAAAA0000A1Z5",
                invoice_number="C",
                category="matched",
                match_status="MATCHED",
                match_confidence=None,
            ),
        ],
        run_id="r1",
        period="2024-11",
    )
    assert batch.available is True
    assert batch.high_confidence_accept_count == 2  # 0.95 fuzzy + exact blank
    by_id = {r.invoice_id: r for r in batch.invoices}
    assert by_id["a"].confidence_score == 0.95
    assert by_id["b"].recommended_action == "hold"
    assert by_id["b"].confidence_score == 0.70
    assert by_id["c"].confidence_score is None


def test_resolve_confidence_never_fabricates():
    score, src = resolve_confidence(
        InvoiceRecommendationInput(
            invoice_id="x",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="X",
            category="missed_itc",
            match_confidence=None,
        )
    )
    assert score is None
    assert src == "unavailable"


def test_high_confidence_min_aligned_with_outcomes():
    assert CONFIDENCE_HIGH_MIN == 0.90
    assert HIGH_CONFIDENCE_ACCEPT_MIN == CONFIDENCE_HIGH_MIN


def test_recommend_batch_empty_is_confirmed_empty():
    batch = recommend_batch([], run_id="r1", period="2024-11")
    assert batch.available is True
    assert len(batch.invoices) == 0
    assert batch.as_dict()["invoice_count"] == 0


def test_hold_maps_to_pending():
    assert ca_action_to_gstn("hold") == "pending"
    assert ca_action_to_gstn("accept") == "accept"


def test_override_detection():
    assert is_override("hold", "accept") is True
    assert is_override("accept", "accept") is False
    a = ConfirmedInvoiceAction(
        invoice_id="1",
        chosen_action="accept",
        recommended_action="hold",
        writeback_payload={"stin": "27AAAAA0000A1Z5", "inum": "1"},
    )
    assert a.overridden is True
    assert a.submit_mode == "override"


def test_poll_outcome_pending_confirmed_failed():
    pending = IMSCheckStatusResponse(
        status_cd="IP",
        trans_type_cd="SAV",
        processed_count=0,
        error_count=0,
    )
    assert outcome_from_poll(pending) == "pending"

    ok = IMSCheckStatusResponse(
        status_cd="P",
        trans_type_cd="SAV",
        processed_count=3,
        error_count=0,
    )
    assert outcome_from_poll(ok) == "confirmed"

    bad = IMSCheckStatusResponse(
        status_cd="PE",
        trans_type_cd="SAV",
        processed_count=1,
        error_count=2,
    )
    assert outcome_from_poll(bad) == "failed"


def test_rule37a_flag_holds_recommendation():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="r37a:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-37A",
            category="matched",
            ims_status="no_action_taken",
            rule37a_flag=True,
            match_confidence=1.0,
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert "RULE37A_NON_FILER" in rec.reason_codes
    assert "Rule 37A risk" in rec.human_readable_why


def test_unlinked_credit_note_holds_recommendation():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="cn:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="CN-101",
            category="missed_itc",
            section="cn",
            ims_status="no_action_taken",
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert "UNLINKED_CREDIT_NOTE" in rec.reason_codes
    assert "unlinked in Purchase Register" in rec.human_readable_why
