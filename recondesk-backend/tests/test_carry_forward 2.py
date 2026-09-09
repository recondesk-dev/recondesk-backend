"""Tests for cross-run invoice_tracking carry-forward."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.carry_forward import (
    CHRONIC_RISK_THRESHOLD,
    update_invoice_tracking,
)


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
RUN_1 = UUID("22222222-2222-2222-2222-222222222222")
RUN_2 = UUID("33333333-3333-3333-3333-333333333333")
TRACKING_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
INVOICE = "INV-UNMATCHED"
GSTIN = "27ABCDE1234F1Z0"


def _unmatched_row(invoice: str = INVOICE) -> dict:
    return {
        "invoice_number": invoice,
        "supplier_gstin": GSTIN,
        "taxable_amount": 100000,
        "match_status": "unmatched",
    }


def _make_mock_supabase(initial_tracking_rows: list) -> MagicMock:
    """
    Build a mock supabase that:
    - Returns initial_tracking_rows when the bulk-fetch select chain executes
    - Captures upsert payloads so tests can inspect them
    """
    mock_sb = MagicMock()
    captured_upserts = []
    select_call_count = [0]

    def _table(name):
        t = MagicMock()
        if name != "invoice_tracking":
            return t

        # SELECT chain (for _bulk_fetch_tracking_rows paginated read)
        select_chain = MagicMock()
        select_chain.eq.return_value = select_chain
        select_chain.order.return_value = select_chain
        select_chain.range.return_value = select_chain
        select_chain.gte.return_value = select_chain
        select_chain.limit.return_value = select_chain

        def _select_execute():
            res = MagicMock()
            n = select_call_count[0]
            select_call_count[0] += 1
            # First page returns the initial rows; subsequent pages return empty
            res.data = list(initial_tracking_rows) if n == 0 else []
            return res

        select_chain.execute.side_effect = _select_execute
        t.select.return_value = select_chain

        # UPSERT chain (for _batched_upsert)
        upsert_chain = MagicMock()
        upsert_res = MagicMock()
        upsert_res.data = []
        upsert_chain.execute.return_value = upsert_res

        def _upsert(payload, **kwargs):
            captured_upserts.append(payload)
            return upsert_chain

        t.upsert.side_effect = _upsert
        return t

    mock_sb.table.side_effect = _table
    mock_sb._captured_upserts = captured_upserts
    return mock_sb


@pytest.mark.asyncio
async def test_two_runs_increment_consecutive_unmatched_runs():
    """First run: inserts a new row. Second run: increments counter to 2."""

    # Run 1: no existing rows
    mock_sb1 = _make_mock_supabase(initial_tracking_rows=[])
    with patch("app.services.carry_forward.get_supabase", return_value=mock_sb1):
        summary1 = await update_invoice_tracking(CLIENT_ID, RUN_1, [_unmatched_row()])

    assert summary1["upserted"] >= 1
    inserts = mock_sb1._captured_upserts
    assert len(inserts) == 1
    inserted_row = inserts[0][0]
    assert inserted_row["invoice_number"] == INVOICE
    assert inserted_row["consecutive_unmatched_runs"] == 1
    assert inserted_row["is_resolved"] is False

    # Run 2: existing row with count=1
    existing = {
        "id": TRACKING_ID,
        "invoice_number": INVOICE,
        "supplier_gstin": GSTIN,
        "consecutive_unmatched_runs": 1,
        "is_resolved": False,
    }
    mock_sb2 = _make_mock_supabase(initial_tracking_rows=[existing])
    with patch("app.services.carry_forward.get_supabase", return_value=mock_sb2):
        summary2 = await update_invoice_tracking(CLIENT_ID, RUN_2, [_unmatched_row()])

    assert summary2["upserted"] >= 1
    updates = mock_sb2._captured_upserts
    assert len(updates) == 1
    updated_row = updates[0][0]
    assert updated_row["consecutive_unmatched_runs"] == 2
    assert updated_row["last_seen_run_id"] == str(RUN_2)
    assert len(summary2["chronic_risks"]) == 0


@pytest.mark.asyncio
async def test_third_unmatched_run_flags_chronic_risk():
    """When counter hits CHRONIC_RISK_THRESHOLD, chronic_risks list is populated."""
    existing = {
        "id": TRACKING_ID,
        "invoice_number": INVOICE,
        "supplier_gstin": GSTIN,
        "consecutive_unmatched_runs": CHRONIC_RISK_THRESHOLD - 1,
        "is_resolved": False,
    }
    mock_sb = _make_mock_supabase(initial_tracking_rows=[existing])

    with patch("app.services.carry_forward.get_supabase", return_value=mock_sb):
        summary = await update_invoice_tracking(CLIENT_ID, uuid4(), [_unmatched_row()])

    assert len(summary["chronic_risks"]) == 1
    updates = mock_sb._captured_upserts
    assert updates[0][0]["consecutive_unmatched_runs"] == CHRONIC_RISK_THRESHOLD


@pytest.mark.asyncio
async def test_matched_run_resolves_tracking():
    """A matched invoice previously unmatched sets is_resolved=True, resets counter."""
    existing = {
        "id": TRACKING_ID,
        "invoice_number": INVOICE,
        "supplier_gstin": GSTIN,
        "consecutive_unmatched_runs": 2,
        "is_resolved": False,
    }
    mock_sb = _make_mock_supabase(initial_tracking_rows=[existing])
    matched_row = {**_unmatched_row(), "match_status": "matched"}

    with patch("app.services.carry_forward.get_supabase", return_value=mock_sb):
        summary = await update_invoice_tracking(CLIENT_ID, uuid4(), [matched_row])

    assert summary["resolved"] == 1
    updates = mock_sb._captured_upserts
    assert updates[0][0]["is_resolved"] is True
    assert updates[0][0]["consecutive_unmatched_runs"] == 0
