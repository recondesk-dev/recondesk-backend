"""Tests for deleting reconciliation runs with dependent Table 4 snapshots and reversal ledger rows."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from app.routers.reconciliation_api import (
    _clear_table4_and_ledger_for_run,
    delete_reconcile_run,
)


class MockTable:
    def __init__(self, name: str, db: "MockDatabase"):
        self.name = name
        self.db = db
        self.rows: list[dict] = []
        self._filters: list[tuple[str, any]] = []

    def select(self, columns: str = "*"):
        self._filters = []
        return self

    def eq(self, col: str, val: any):
        self._filters.append((col, val))
        return self

    def limit(self, count: int):
        return self

    def execute(self):
        matched = [
            r for r in self.rows
            if all(r.get(c) == v for c, v in self._filters)
        ]
        res = MagicMock()
        res.data = [dict(m) for m in matched]
        self._filters = []
        return res

    def update(self, values: dict):
        matched = [
            r for r in self.rows
            if all(r.get(c) == v for c, v in self._filters)
        ]
        for r in matched:
            r.update(values)
        res = MagicMock()
        res.data = matched
        self._filters = []
        return self

    def delete(self):
        if self.name == "reconciliation_run":
            for col, val in self._filters:
                if col == "id":
                    has_snaps = any(s.get("run_id") == val for s in self.db.table("gstr3b_table4_summaries").rows)
                    has_reclaims = any(r.get("reclaim_run_id") == val for r in self.db.table("gstr3b_reclaim_events").rows)
                    if has_snaps or has_reclaims:
                        raise RuntimeError(
                            f"FOREIGN KEY RESTRICT VIOLATION (23503): Cannot delete reconciliation_run {val} "
                            "because finalized snapshots or reclaim events depend on it."
                        )
        self.rows = [
            r for r in self.rows
            if not all(r.get(c) == v for c, v in self._filters)
        ]
        self._filters = []
        res = MagicMock()
        res.data = []
        return self


class MockDatabase:
    def __init__(self):
        self._tables: dict[str, MockTable] = {}

    def table(self, name: str) -> MockTable:
        if name not in self._tables:
            self._tables[name] = MockTable(name, self)
        return self._tables[name]

    def rpc(self, func_name: str, params: dict):
        mock_rpc = MagicMock()
        if func_name == "delete_reconciliation_run_cascade":
            # Simulate an outdated or failing RPC (e.g. raises 23503 FK violation)
            def _exec():
                raise RuntimeError(
                    'update or delete on table "reconciliation_run" violates foreign key constraint '
                    '"gstr3b_table4_summaries_run_id_fkey" on table "gstr3b_table4_summaries" — 23503'
                )
            mock_rpc.execute = _exec
        return mock_rpc


@pytest.mark.asyncio
async def test_clear_table4_and_ledger_for_run():
    db = MockDatabase()
    run_id = str(uuid4())
    ledger_id = str(uuid4())

    # Populate tables
    db.table("reconciliation_run").rows = [
        {"id": run_id, "table4_summary_id": "some_summary_id"}
    ]
    db.table("gstr3b_table4_summaries").rows = [
        {"id": str(uuid4()), "run_id": run_id}
    ]
    db.table("gstr3b_reversal_ledger").rows = [
        {"id": ledger_id, "source_run_id": run_id}
    ]
    db.table("gstr3b_reclaim_events").rows = [
        {"id": str(uuid4()), "ledger_id": ledger_id, "reclaim_run_id": run_id}
    ]

    _clear_table4_and_ledger_for_run(db, run_id)

    assert db.table("reconciliation_run").rows[0]["table4_summary_id"] is None
    assert len(db.table("gstr3b_table4_summaries").rows) == 0
    assert len(db.table("gstr3b_reversal_ledger").rows) == 0
    assert len(db.table("gstr3b_reclaim_events").rows) == 0


@pytest.mark.asyncio
async def test_delete_reconcile_run_fallback_cleans_table4_on_rpc_failure():
    db = MockDatabase()
    run_id = str(uuid4())
    user_id = str(uuid4())

    db.table("reconciliation_run").rows = [
        {"id": run_id, "client_gstin_id": "gstin_1", "r2_key": "r2_key_1"}
    ]
    db.table("gstr3b_table4_summaries").rows = [
        {"id": str(uuid4()), "run_id": run_id}
    ]
    db.table("gstr3b_reclaim_events").rows = [
        {"id": str(uuid4()), "reclaim_run_id": run_id}
    ]

    mock_req = MagicMock()
    mock_req.client = None

    current_user = {"id": user_id, "role": "admin"}

    with patch("app.routers.reconciliation_api.get_user_role", AsyncMock(return_value="admin")), \
         patch("app.routers.reconciliation_api.get_supabase", return_value=db), \
         patch("app.routers.reconciliation_api.assert_run_accessible", return_value={"id": run_id}), \
         patch("app.routers.reconciliation_api.delete_file", AsyncMock()), \
         patch("app.routers.reconciliation_api.log_action", AsyncMock()), \
         patch("app.routers.reconciliation_api.invalidate_user_dashboard"), \
         patch("app.routers.reconciliation_api.invalidate_run_bucket_cache"):

        resp = await delete_reconcile_run(mock_req, run_id, current_user=current_user)
        assert resp["message"] == "Run deleted successfully"
        assert len(db.table("reconciliation_run").rows) == 0
        assert len(db.table("gstr3b_table4_summaries").rows) == 0
        assert len(db.table("gstr3b_reclaim_events").rows) == 0
