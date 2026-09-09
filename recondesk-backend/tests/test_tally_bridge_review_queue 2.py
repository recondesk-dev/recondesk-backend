"""Tests for Tally Bridge weak party match review queue persistence and resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.services.tally_bridge_sync import apply_tally_bridge_sync


def _open_row():
    return {
        "run_id": "run-100",
        "record_id": "r37:pr-999",
        "pr_id": "pr-999",
        "invoice_number": "INV-2026-999",
        "invoice_date": "2026-04-01",
        "supplier_gstin": "27AAACB1234C1Z1",
        "supplier_name": "Reliable Suppliers Pvt Ltd",
        "invoice_amount": 50000.0,
        "client_gstin_id": "client-1",
    }


def test_weak_party_match_persists_pending_review_row():
    open_rows = [_open_row()]
    upsert_mock = MagicMock()
    mock_sb = MagicMock()
    # Mock no existing status found for this (run_id, record_hash)
    mock_sb.table().select().eq().eq().execute.return_value.data = []

    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert_mock,
        ),
    ):
        res = apply_tally_bridge_sync(
            mock_sb,
            account_id="user-123",
            outstanding=[],
            payments=[
                {
                    "party": "Uncertain Enterprise",
                    "bill_ref": "INV-2026-999",
                    "amount": 50000.0,
                    "payment_date": "2026-04-10",
                }
            ],
            company_name="Test Company",
            key_id="key-999",
        )

    assert res["needs_manual_confirmation_count"] == 1
    upsert_mock.assert_called_once()
    kwargs = upsert_mock.call_args.kwargs
    assert kwargs["run_id"] == "run-100"
    assert kwargs["record_id"] == "r37:pr-999"
    assert kwargs["status_value"] == "pending_review"
    assert kwargs["user_id"] == "user-123"
    assert kwargs["source"] == "tally_bridge"
    assert kwargs["review_metadata"]["party"] == "Uncertain Enterprise"
    assert kwargs["review_metadata"]["supplier_name"] == "Reliable Suppliers Pvt Ltd"


def test_already_rejected_or_resolved_row_not_overwritten():
    open_rows = [_open_row()]
    upsert_mock = MagicMock()
    mock_sb = MagicMock()
    # Mock existing row has status 'rejected'
    mock_sb.table().select().eq().eq().execute.return_value.data = [{"status": "rejected"}]

    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=open_rows,
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert_mock,
        ),
    ):
        res = apply_tally_bridge_sync(
            mock_sb,
            account_id="user-123",
            outstanding=[],
            payments=[
                {
                    "party": "Uncertain Enterprise",
                    "bill_ref": "INV-2026-999",
                    "amount": 50000.0,
                    "payment_date": "2026-04-10",
                }
            ],
            company_name="Test Company",
            key_id="key-999",
        )

    # Should append to response needs_manual_confirmation but NOT upsert to DB again
    assert res["needs_manual_confirmation_count"] == 1
    upsert_mock.assert_not_called()


@pytest.mark.asyncio
async def test_approve_pending_review_triggers_full_rule37_settlement():
    from app.routers.tally_sync import tally_bridge_resolve_review, TallyReviewResolveBody

    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {
            "id": "act-123",
            "run_id": "run-100",
            "record_hash": "pr-999",
            "user_id": "user-123",
            "status": "pending_review",
            "amount_paid": 50000.0,
            "settled_date": "2026-04-10",
            "review_metadata": {"party": "Uncertain Enterprise"},
            "source": "tally_bridge",
        }
    ]

    upsert_mock = MagicMock()
    with (
        patch("app.routers.tally_sync.get_supabase", return_value=mock_sb),
        patch("app.routers.tally_sync._account_id_for_user", return_value="user-123"),
        patch("app.routers.reconciliation_api._payload_or_404", return_value={}),
        patch("app.routers.reconciliation_api._notes_count_for_run", return_value={}),
        patch(
            "app.routers.reconciliation_api._build_rule37_rows",
            return_value=[{"id": "r37:pr-999", "invoice_amount": 50000.0, "amount": 50000.0}],
        ),
        patch("app.routers.reconciliation_api._upsert_rule37_action", upsert_mock),
    ):
        res = await tally_bridge_resolve_review(
            "act-123",
            TallyReviewResolveBody(status="resolved"),
            current_user={"id": "user-123"},
        )

    assert res["ok"] is True
    assert res["status"] == "resolved"
    assert res["amount_paid"] == 50000.0
    assert res["total_settled"] == 50000.0
    assert res["remaining_unpaid_amount"] == 0.0
    assert res["payment_coverage"] == "full"

    # Verify _upsert_rule37_action was invoked with full settlement payload
    upsert_mock.assert_called_once()
    kwargs = upsert_mock.call_args.kwargs
    assert kwargs["run_id"] == "run-100"
    assert kwargs["record_id"] == "r37:pr-999"
    assert kwargs["status_value"] == "resolved"
    assert kwargs["user_id"] == "user-123"
    assert kwargs["amount_paid"] == 50000.0
    assert kwargs["total_settled"] == 50000.0
    assert kwargs["remaining_unpaid_amount"] == 0.0
    assert kwargs["payment_coverage"] == "full"
    assert kwargs["source"] == "tally_bridge_manual_confirmation"
