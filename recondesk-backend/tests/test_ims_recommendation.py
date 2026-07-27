"""Unit tests for IMS recommendation + writeback pure logic."""

from __future__ import annotations

from app.ims.ims_recommendation import (
    HIGH_CONFIDENCE_ACCEPT_MIN,
    InvoiceRecommendationInput,
    is_high_confidence_accept,
    recommend_batch,
    recommend_invoice,
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


def test_matched_clean_recommends_accept():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-1",
            category="matched",
            match_status="MATCHED",
            ims_status="no_action_taken",
            match_confidence=0.95,
        )
    )
    assert rec is not None
    assert rec.recommended_action == "accept"
    assert rec.confidence_score >= HIGH_CONFIDENCE_ACCEPT_MIN
    assert is_high_confidence_accept(rec)


def test_already_accepted_skipped():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="pm:2",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-2",
            category="matched",
            ims_status="accepted",
        )
    )
    assert rec is None


def test_blocked_credit_rejects():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="bc:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-3",
            category="blocked_credit",
            ims_status="no_action_taken",
        )
    )
    assert rec is not None
    assert rec.recommended_action == "reject"


def test_review_required_holds():
    rec = recommend_invoice(
        InvoiceRecommendationInput(
            invoice_id="rr:1",
            supplier_gstin="27AAAAA0000A1Z5",
            invoice_number="INV-4",
            category="review_required",
            ims_status="pending",
        )
    )
    assert rec is not None
    assert rec.recommended_action == "hold"


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
