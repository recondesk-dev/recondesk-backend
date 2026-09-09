"""Unit tests for Tally Bridge matching, party gate, and settle semantics."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.services.tally_bridge_sync import (
    _PARTY_AUTO_SETTLE_MIN,
    _UNIQUE_GAP_MIN,
    _UNIQUE_GAP_UNCLEAR_PARTY,
    apply_tally_bridge_sync,
    is_confident_bill_match,
    party_clears_autosettle_gate,
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


def test_ambiguous_near_tie_rejected_with_default_gap():
    assert not is_confident_bill_match(0.90, 0.88)
    assert is_confident_bill_match(0.90, 0.70)


def test_unclear_party_uses_wider_unique_gap():
    # 0.10 gap clears default 0.05 but fails unclear-party 0.15
    assert is_confident_bill_match(0.95, 0.85, unique_gap=_UNIQUE_GAP_MIN)
    assert not is_confident_bill_match(
        0.95, 0.85, unique_gap=_UNIQUE_GAP_UNCLEAR_PARTY
    )


def test_party_gate_requires_both_names_and_threshold():
    ok, sim = party_clears_autosettle_gate("Acme Traders Pvt Ltd", "ACME TRADERS")
    assert ok is True
    assert sim >= _PARTY_AUTO_SETTLE_MIN

    ok_blank, sim_blank = party_clears_autosettle_gate("", "ACME TRADERS")
    assert ok_blank is False
    assert sim_blank == 0.0

    ok_weak, _ = party_clears_autosettle_gate("Totally Different Co", "ACME TRADERS")
    assert ok_weak is False


def _open_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "run_id": "run-1",
        "record_id": "r37:pr-1",
        "pr_id": "pr-1",
        "invoice_number": "INV/2024/001",
        "invoice_date": "2024-01-15",
        "supplier_gstin": "27AABCU9603R1ZM",
        "supplier_name": "Acme Traders Pvt Ltd",
        "invoice_amount": 10000.0,
        "client_gstin_id": "client-1",
    }
    row.update(overrides)
    return row


def test_outstanding_only_never_settles():
    open_rows = [_open_row()]
    upsert = MagicMock()
    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert,
        ),
        patch(
            "app.routers.reconciliation_api._rule37_payment_coverage",
            return_value="full",
        ),
    ):
        result = apply_tally_bridge_sync(
            MagicMock(),
            account_id="acct-1",
            outstanding=[
                {
                    "party": "Acme Traders Pvt Ltd",
                    "bill_ref": "INV/2024/001",
                    "bill_date": "2024-01-15",
                    "amount": 10000.0,
                }
            ],
            payments=[],
            company_name="Demo Co",
            key_id="key-1",
        )

    upsert.assert_not_called()
    assert result["settled_count"] == 0
    assert result["still_outstanding_count"] == 1
    assert result["still_outstanding"][0]["pending_due"] == 10000.0


def test_payment_strong_party_settles_with_payment_amount_and_tds_unconfirmed():
    open_rows = [_open_row()]
    upsert = MagicMock()
    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert,
        ),
        patch(
            "app.routers.reconciliation_api._rule37_payment_coverage",
            side_effect=lambda paid, inv: "full" if paid + 0.005 >= inv else "partial",
        ),
    ):
        result = apply_tally_bridge_sync(
            MagicMock(),
            account_id="acct-1",
            outstanding=[],
            payments=[
                {
                    "party": "Acme Traders",
                    "bill_ref": "INV-2024-001",
                    "amount": 10000.0,
                    "payment_date": "2024-06-01",
                    "voucher_number": "PMT-9",
                    "voucher_type": "Payment",
                }
            ],
            company_name="Demo Co",
            key_id="key-1",
        )

    assert result["settled_count"] == 1
    assert result["needs_manual_confirmation_count"] == 0
    upsert.assert_called_once()
    kwargs = upsert.call_args.kwargs
    assert kwargs["status_value"] == "resolved"
    assert kwargs["amount_paid"] == 10000.0
    assert kwargs["tds_deducted"] == 0.0
    assert kwargs["tds_confirmed"] is False
    assert kwargs["settled_date"] == "2024-06-01"
    assert kwargs["source"] == "tally_bridge"
    assert result["settled"][0]["tds_confirmed"] is False


def test_payment_weak_party_flags_manual_and_upserts_pending_review():
    open_rows = [_open_row()]
    upsert = MagicMock()
    mock_sb = MagicMock()
    mock_sb.table().select().eq().eq().execute.return_value.data = []
    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert,
        ),
        patch(
            "app.routers.reconciliation_api._rule37_payment_coverage",
            return_value="full",
        ),
    ):
        result = apply_tally_bridge_sync(
            mock_sb,
            account_id="acct-1",
            outstanding=[],
            payments=[
                {
                    "party": "Completely Unrelated Vendor LLP",
                    "bill_ref": "INV/2024/001",
                    "amount": 10000.0,
                    "payment_date": "2024-06-01",
                }
            ],
            company_name="Demo Co",
            key_id="key-1",
        )

    upsert.assert_called_once()
    kwargs = upsert.call_args.kwargs
    assert kwargs["status_value"] == "pending_review"
    assert kwargs["review_metadata"]["reason"] == "party_confidence_below_gate"
    assert result["settled_count"] == 0
    assert result["needs_manual_confirmation_count"] == 1
    assert (
        result["needs_manual_confirmation"][0]["reason"]
        == "party_confidence_below_gate"
    )


def test_payment_missing_party_flags_manual_not_settle():
    open_rows = [_open_row()]
    upsert = MagicMock()
    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert,
        ),
        patch(
            "app.routers.reconciliation_api._rule37_payment_coverage",
            return_value="full",
        ),
    ):
        result = apply_tally_bridge_sync(
            MagicMock(),
            account_id="acct-1",
            outstanding=[],
            payments=[
                {
                    "party": "",
                    "bill_ref": "INV/2024/001",
                    "amount": 10000.0,
                    "payment_date": "2024-06-01",
                }
            ],
            company_name="Demo Co",
        )

    upsert.assert_called_once()
    assert upsert.call_args.kwargs["status_value"] == "pending_review"
    assert result["needs_manual_confirmation_count"] == 1


def test_payment_plus_outstanding_pending_is_partial():
    open_rows = [_open_row()]
    upsert = MagicMock()
    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert,
        ),
        patch(
            "app.routers.reconciliation_api._rule37_payment_coverage",
            return_value="full",
        ),
    ):
        result = apply_tally_bridge_sync(
            MagicMock(),
            account_id="acct-1",
            outstanding=[
                {
                    "party": "Acme Traders Pvt Ltd",
                    "bill_ref": "INV/2024/001",
                    "amount": 2500.0,  # remaining due
                }
            ],
            payments=[
                {
                    "party": "Acme Traders Pvt Ltd",
                    "bill_ref": "INV/2024/001",
                    "amount": 7500.0,  # amount paid
                    "payment_date": "2024-06-01",
                }
            ],
            company_name="Demo Co",
        )

    upsert.assert_called_once()
    kwargs = upsert.call_args.kwargs
    assert kwargs["amount_paid"] == 7500.0
    assert kwargs["remaining_unpaid_amount"] == 2500.0
    assert kwargs["payment_coverage"] == "partial"
    assert kwargs["tds_confirmed"] is False
    assert result["settled"][0]["payment_coverage"] == "partial"


def test_missing_payment_amount_does_not_assume_full_invoice():
    open_rows = [_open_row()]
    upsert = MagicMock()
    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert,
        ),
        patch(
            "app.routers.reconciliation_api._rule37_payment_coverage",
            return_value="full",
        ),
    ):
        result = apply_tally_bridge_sync(
            MagicMock(),
            account_id="acct-1",
            outstanding=[],
            payments=[
                {
                    "party": "Acme Traders Pvt Ltd",
                    "bill_ref": "INV/2024/001",
                    "amount": None,
                    "payment_date": "2024-06-01",
                }
            ],
            company_name="Demo Co",
        )

    upsert.assert_not_called()
    assert result["settled_count"] == 0
    assert any(
        s.get("reason") == "missing_or_non_positive_payment_amount"
        for s in result["skipped"]
    )


def test_score_bill_ref_no_longer_boosts_on_party():
    """Soft +0.05 party boost must be gone — party is a hard gate instead."""
    base = score_bill_ref_against_invoice("INV/2024/001", "INV-2024-001")
    # Old API accepted party=; new signature is bill_ref + invoice only.
    assert base == 1.0
