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


def _unmatched_row(invoice: str = "INV-UNMATCHED") -> dict:
    return {
        "invoice_number": invoice,
        "supplier_gstin": "27ABCDE1234F1Z0",
        "taxable_amount": 100000,
        "match_status": "unmatched",
    }


@pytest.mark.asyncio
async def test_two_runs_increment_consecutive_unmatched_runs():
    """Same unmatched invoice across two runs → counter goes 1 → 2."""
    stored: dict | None = None
    mock_sb = MagicMock()

    def _table(name: str):
        t = MagicMock()
        if name != "invoice_tracking":
            return t

        select_chain = MagicMock()

        def _select(*_args, **_kwargs):
            return select_chain

        select_chain.eq.return_value = select_chain
        select_chain.limit.return_value = select_chain

        def _execute_select():
            res = MagicMock()
            res.data = [stored] if stored else []
            return res

        select_chain.execute.side_effect = _execute_select

        insert_chain = MagicMock()

        def _insert(payload: dict):
            nonlocal stored
            stored = {**payload, "id": TRACKING_ID, "is_resolved": False}
            res = MagicMock()
            res.data = [stored]
            return insert_chain

        insert_chain.execute.side_effect = lambda: MagicMock(data=[stored])

        update_chain = MagicMock()

        def _update(payload: dict):
            nonlocal stored
            if stored:
                stored = {**stored, **payload}
            return update_chain

        update_chain.eq.return_value = update_chain
        update_chain.execute.side_effect = lambda: MagicMock(data=[stored])

        t.select.side_effect = _select
        t.insert.side_effect = _insert
        t.update.side_effect = _update
        return t

    mock_sb.table.side_effect = _table

    with patch("app.services.carry_forward.get_supabase", return_value=mock_sb):
        summary1 = await update_invoice_tracking(CLIENT_ID, RUN_1, [_unmatched_row()])
        assert summary1["upserted"] == 1
        assert stored is not None
        assert stored["consecutive_unmatched_runs"] == 1

        summary2 = await update_invoice_tracking(CLIENT_ID, RUN_2, [_unmatched_row()])
        assert summary2["upserted"] == 1
        assert stored["consecutive_unmatched_runs"] == 2
        assert stored["last_seen_run_id"] == str(RUN_2)
        assert len(summary2["chronic_risks"]) == 0


@pytest.mark.asyncio
async def test_third_unmatched_run_flags_chronic_risk():
    stored = {
        "id": TRACKING_ID,
        "consecutive_unmatched_runs": CHRONIC_RISK_THRESHOLD - 1,
        "is_resolved": False,
    }
    mock_sb = MagicMock()

    def _table(name: str):
        t = MagicMock()
        chain = MagicMock()
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=[stored])

        def _update(payload: dict):
            stored.update(payload)
            return chain

        t.select.return_value = chain
        t.update.side_effect = _update
        return t

    mock_sb.table.side_effect = _table

    with patch("app.services.carry_forward.get_supabase", return_value=mock_sb):
        summary = await update_invoice_tracking(
            CLIENT_ID, uuid4(), [_unmatched_row()]
        )
        assert stored["consecutive_unmatched_runs"] == CHRONIC_RISK_THRESHOLD
        assert len(summary["chronic_risks"]) == 1


@pytest.mark.asyncio
async def test_matched_run_resolves_tracking():
    stored = {
        "id": TRACKING_ID,
        "consecutive_unmatched_runs": 2,
        "is_resolved": False,
    }
    mock_sb = MagicMock()

    def _table(name: str):
        t = MagicMock()
        chain = MagicMock()
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=[stored])

        def _update(payload: dict):
            stored.update(payload)
            return chain

        t.select.return_value = chain
        t.update.side_effect = _update
        return t

    mock_sb.table.side_effect = _table

    matched_row = {**_unmatched_row(), "match_status": "matched"}

    with patch("app.services.carry_forward.get_supabase", return_value=mock_sb):
        summary = await update_invoice_tracking(
            CLIENT_ID, uuid4(), [matched_row]
        )
        assert summary["resolved"] == 1
        assert stored["is_resolved"] is True
        assert stored["consecutive_unmatched_runs"] == 0
