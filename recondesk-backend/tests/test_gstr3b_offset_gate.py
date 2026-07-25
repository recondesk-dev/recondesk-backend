"""GSTR-3B Offset period gate — blocks Save/Offset across all run_ids."""

from __future__ import annotations

from typing import Any

import pytest

from app.filing.filing_store import (
    GSTR3B_OFFSET_LOCKED_STATUSES,
    Gstr3bPeriodLockedError,
    assert_gstr3b_offset_allowed,
    assert_gstr3b_save_allowed,
    find_gstr3b_offset_lock,
)


class _FakeQuery:
    """Minimal Supabase-style chain for filing_runs gate queries."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)
        self._filters: list[tuple[str, Any]] = []
        self._in_filters: list[tuple[str, list[Any]]] = []
        self._order_col: str | None = None
        self._order_desc = False
        self._limit: int | None = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col: str, val: Any):
        self._filters.append((col, val))
        return self

    def in_(self, col: str, values: list[Any]):
        self._in_filters.append((col, list(values)))
        return self

    def order(self, col: str, desc: bool = False):
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def execute(self):
        out = self._rows
        for col, val in self._filters:
            out = [r for r in out if r.get(col) == val]
        for col, values in self._in_filters:
            allowed = set(values)
            out = [r for r in out if r.get(col) in allowed]
        if self._order_col:
            out = sorted(
                out,
                key=lambda r: (r.get(self._order_col) is None, r.get(self._order_col)),
                reverse=self._order_desc,
            )
        if self._limit is not None:
            out = out[: self._limit]
        return type("Res", (), {"data": out})()


class _FakeSb:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def table(self, name: str):
        assert name == "filing_runs"
        return _FakeQuery(self._rows)


GSTIN = "27ISKPK1273H1ZF"
PERIOD = "2026-07"


def _run(
    run_id: str,
    status: str,
    *,
    gstin: str = GSTIN,
    period: str = PERIOD,
    return_type: str = "gstr-3b",
    offset_completed_at: str | None = "2026-07-26T10:00:00+00:00",
    tx_pmt_snapshot: dict | None = None,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "gstin": gstin,
        "period": period,
        "return_type": return_type,
        "status": status,
        "offset_completed_at": offset_completed_at,
        "tx_pmt_snapshot": tx_pmt_snapshot,
        "offset_payload": {"pdcash": [], "pditc": {}},
        "reference_id": f"ref-{run_id}",
        "created_at": "2026-07-26T09:00:00+00:00",
        "updated_at": "2026-07-26T10:00:00+00:00",
    }


def test_gate_allows_when_no_offset_complete_run():
    sb = _FakeSb([
        _run("run-a", "saved", offset_completed_at=None),
        _run("run-b", "offset_failed", offset_completed_at=None),
        _run("run-c", "offset_pending", offset_completed_at=None),
    ])
    assert find_gstr3b_offset_lock(sb, gstin=GSTIN, period=PERIOD) is None
    assert_gstr3b_save_allowed(sb, gstin=GSTIN, period=PERIOD)
    assert_gstr3b_offset_allowed(sb, gstin=GSTIN, period=PERIOD)


def test_gate_blocks_offset_when_offset_complete():
    locking = _run(
        "run-lock",
        "offset_complete",
        tx_pmt_snapshot={"tx_py": [{"liab_ldg_id": 1}]},
    )
    sb = _FakeSb([locking, _run("run-other", "saved", offset_completed_at=None)])
    with pytest.raises(Gstr3bPeriodLockedError) as ei:
        assert_gstr3b_offset_allowed(sb, gstin=GSTIN, period=PERIOD)
    err = ei.value
    assert err.action == "offset"
    assert err.locking_run["id"] == "run-lock"
    assert "future period" in str(err).lower()
    assert "tx_pmt" in str(err).lower()


def test_gate_blocks_save_when_offset_complete_hard_not_readonly():
    sb = _FakeSb([_run("run-lock", "offset_complete")])
    with pytest.raises(Gstr3bPeriodLockedError) as ei:
        assert_gstr3b_save_allowed(sb, gstin=GSTIN, period=PERIOD)
    msg = str(ei.value).lower()
    assert ei.value.action == "save"
    assert "do not save again" in msg or "blocked" in msg
    assert "future period" in msg
    # Explicitly not a soft/read-only path
    assert "read-only" not in msg


@pytest.mark.parametrize("later_status", sorted(GSTR3B_OFFSET_LOCKED_STATUSES))
def test_gate_blocks_for_all_locked_statuses(later_status: str):
    sb = _FakeSb([_run("run-lock", later_status)])
    with pytest.raises(Gstr3bPeriodLockedError):
        assert_gstr3b_save_allowed(sb, gstin=GSTIN, period=PERIOD)
    with pytest.raises(Gstr3bPeriodLockedError):
        assert_gstr3b_offset_allowed(sb, gstin=GSTIN, period=PERIOD)


def test_second_run_id_cannot_bypass_period_gate():
    """Critical: a fresh run_id for the same gstin+period must still be blocked.

    Attack / accidental path: create draft run-B after run-A reached
    offset_complete, then try Save/Offset on run-B. Gate must query by
    (gstin, period, gstr-3b), not by the caller's run_id.
    """
    run_a = _run(
        "run-a-offset-done",
        "offset_complete",
        tx_pmt_snapshot={"tx_py": [{"liab_ldg_id": 770673261}]},
    )
    # Hypothetical second run the CA (or buggy client) might create
    run_b = _run("run-b-fresh", "draft", offset_completed_at=None)
    sb = _FakeSb([run_a, run_b])

    lock = find_gstr3b_offset_lock(sb, gstin=GSTIN, period=PERIOD)
    assert lock is not None
    assert lock["id"] == "run-a-offset-done"
    assert lock["id"] != "run-b-fresh"

    # Bypass attempt: act as if only run-b exists in the caller's mind
    with pytest.raises(Gstr3bPeriodLockedError) as save_err:
        assert_gstr3b_save_allowed(sb, gstin=GSTIN, period=PERIOD)
    assert save_err.value.locking_run["id"] == "run-a-offset-done"

    with pytest.raises(Gstr3bPeriodLockedError) as off_err:
        assert_gstr3b_offset_allowed(sb, gstin=GSTIN, period=PERIOD)
    assert off_err.value.locking_run["id"] == "run-a-offset-done"
    assert "run-a-offset-done" in str(off_err.value)


def test_gate_is_scoped_to_gstin_period_and_gstr3b():
    sb = _FakeSb([
        _run("other-period", "offset_complete", period="2026-06"),
        _run("other-gstin", "offset_complete", gstin="29AAACQ3770E1Z5"),
        _run("gstr1-same-period", "filed", return_type="gstr-1"),
        _run("ok", "saved", offset_completed_at=None),
    ])
    assert find_gstr3b_offset_lock(sb, gstin=GSTIN, period=PERIOD) is None
    assert_gstr3b_save_allowed(sb, gstin=GSTIN, period=PERIOD)
    assert_gstr3b_offset_allowed(sb, gstin=GSTIN, period=PERIOD)
