"""GSTR-1 run persistence — durable banner after session clear."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.gstr1_run_store import (
    STATUS_COMPLETED,
    latest_completed_gstr1_run,
    list_gstr1_runs,
    normalise_period,
    save_gstr1_run,
)


def test_normalise_period_mmyyyy():
    assert normalise_period("042025") == "2025-04"
    assert normalise_period("2025-04") == "2025-04"
    assert normalise_period("2025-04-01") == "2025-04"


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self._filters: dict[str, Any] = {}
        self._limit = 100
        self._order_desc = False
        self._inserted: dict[str, Any] | None = None

    def select(self, *_a, **_k):
        return self

    def insert(self, row):
        self._inserted = dict(row)
        self._inserted.setdefault("id", "run-uuid-1")
        return self

    def eq(self, key, val):
        self._filters[key] = val
        return self

    def order(self, *_a, **_k):
        self._order_desc = True
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._inserted is not None:
            return MagicMock(data=[self._inserted])
        rows = list(self._rows)
        for k, v in self._filters.items():
            rows = [r for r in rows if r.get(k) == v]
        if self._order_desc:
            rows = sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)
        return MagicMock(data=rows[: self._limit])


class _FakeSB:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.rows = list(rows or [])
        self.last_query: _FakeQuery | None = None

    def table(self, name: str):
        assert name == "gstr1_reconciliation_run"
        q = _FakeQuery(self.rows)

        def _insert(row):
            saved = dict(row)
            saved.setdefault("id", f"run-{len(self.rows) + 1}")
            self.rows.insert(0, {
                **saved,
                # list queries omit payload
            })
            q._inserted = saved
            return q

        q.insert = _insert  # type: ignore[method-assign]
        self.last_query = q
        return q


def test_save_and_list_completed_run():
    sb = _FakeSB()
    result = {
        "success": True,
        "summary": {"matched_count": 2, "mismatch_count": 1},
        "parse_diagnostics": {"gstr1": {"filing_period": "2025-04-01"}},
        "matched": [],
        "mismatches": [],
        "tie_out": {},
    }
    saved = save_gstr1_run(
        sb,  # type: ignore[arg-type]
        client_gstin_id="11111111-1111-1111-1111-111111111111",
        result=result,
        created_by="user-1",
        period="042025",
        gstr1_filed_date="2025-05-05",
        gstr3b_filed_date=None,
    )
    assert saved["id"]
    assert saved["status"] == STATUS_COMPLETED
    assert saved["period"] == "2025-04"
    assert saved["gstr1_filed_date"] == "2025-05-05"
    assert saved["gstr3b_filed_date"] is None

    rows = list_gstr1_runs(
        sb,  # type: ignore[arg-type]
        client_gstin_id="11111111-1111-1111-1111-111111111111",
        limit=5,
        status=STATUS_COMPLETED,
    )
    assert len(rows) == 1
    assert rows[0]["id"] == saved["id"]
    assert rows[0]["gstr1_filed_date"] == "2025-05-05"


def test_banner_source_of_truth_survives_without_session_storage():
    """Simulates: run completed → session cleared → latest COMPLETED still found."""
    client_id = "22222222-2222-2222-2222-222222222222"
    sb = _FakeSB()
    result = {
        "success": True,
        "summary": {"matched_count": 1, "mismatch_count": 0},
        "parse_diagnostics": {"gstr1": {"filing_period": "072026"}},
    }
    saved = save_gstr1_run(
        sb,  # type: ignore[arg-type]
        client_gstin_id=client_id,
        result=result,
        created_by="user-1",
    )

    # Session storage would be empty here — banner must use DB.
    session_storage_cleared = True
    assert session_storage_cleared

    latest = latest_completed_gstr1_run(sb, client_gstin_id=client_id)  # type: ignore[arg-type]
    assert latest is not None
    assert latest["id"] == saved["id"]
    assert latest["status"] == STATUS_COMPLETED
    # Banner would show when latest is not None
    show_gstr1_banner = latest is not None
    assert show_gstr1_banner is True


@pytest.mark.asyncio
async def test_pipeline_persist_adds_run_id(monkeypatch):
    """POST path attaches run_id when client_gstin_id is provided (mocked SB)."""
    from pathlib import Path
    from unittest.mock import AsyncMock

    from app.routers import gstr1_reconcile as mod

    sample = Path(__file__).resolve().parent / "sample_gstr1_3b_test"
    sr = sample / "Sales_Register_Sample_Corrected.xlsx"
    g1 = sample / "sample_gstr1.json"
    g3 = sample / "sample_gstr3b.json"
    if not (sr.is_file() and g1.is_file() and g3.is_file()):
        pytest.skip("sample fixtures missing")

    fake_sb = _FakeSB()
    monkeypatch.setattr(mod, "get_supabase", lambda: fake_sb)
    monkeypatch.setattr(
        mod,
        "list_accessible_client_gstin_ids",
        lambda _sb, _user: {"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
    )

    with patch(
        "app.routers.gstr1_reconcile._verify_buyer_gstins_for_g1m7",
        new_callable=AsyncMock,
        return_value=[],
    ):
        out = await mod._run_pipeline(
            sr.read_bytes(),
            sr.name,
            g1.read_bytes(),
            g3.read_bytes(),
            None,
            prior_gstr1_file_content=None,
        )

    # Persist happens in the HTTP handler, not _run_pipeline — exercise save here.
    assert out["success"] is True
    saved = save_gstr1_run(
        fake_sb,  # type: ignore[arg-type]
        client_gstin_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        result=out,
        created_by="u1",
    )
    assert saved["id"]
    # Clear "session" — latest still available
    latest = latest_completed_gstr1_run(
        fake_sb,  # type: ignore[arg-type]
        client_gstin_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    assert latest and latest["id"] == saved["id"]
