"""GSTR-1A per-period filed actions — store helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.gstr1a_period_actions import (
    STATUS_FILED,
    list_gstr1a_period_actions,
    mark_gstr1a_period_filed,
    normalise_action_period,
)


def test_normalise_action_period():
    assert normalise_action_period("042025") == "2025-04"
    assert normalise_action_period("2025-04") == "2025-04"
    assert normalise_action_period("2025-04-01") == "2025-04"


class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]]):
        self._store = store
        self._filters: dict[str, Any] = {}
        self._deleted = False
        self._inserted: dict[str, Any] | None = None

    def select(self, *_a, **_k):
        return self

    def delete(self):
        self._deleted = True
        return self

    def insert(self, row):
        self._inserted = dict(row)
        self._inserted.setdefault("id", "action-1")
        return self

    def eq(self, key, val):
        self._filters[key] = val
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._deleted and not self._inserted:
            self._store[:] = [
                r
                for r in self._store
                if not all(r.get(k) == v for k, v in self._filters.items())
            ]
            return MagicMock(data=[])
        if self._inserted is not None:
            # apply prior delete filters then insert
            if self._deleted:
                self._store[:] = [
                    r
                    for r in self._store
                    if not all(r.get(k) == v for k, v in self._filters.items())
                ]
            self._store.insert(0, dict(self._inserted))
            return MagicMock(data=[self._inserted])
        rows = list(self._store)
        for k, v in self._filters.items():
            rows = [r for r in rows if r.get(k) == v]
        return MagicMock(data=rows)


class _FakeSB:
    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    def table(self, name: str):
        assert name == "gstr1a_period_actions"
        return _FakeQuery(self.rows)


def test_mark_and_list_filed_period():
    sb = _FakeSB()
    saved = mark_gstr1a_period_filed(
        sb,  # type: ignore[arg-type]
        run_id="run-1",
        period="042025",
        user_id="user-1",
        filed_date="2025-05-18",
        note="Portal ARN XYZ",
    )
    assert saved["period"] == "2025-04"
    assert saved["status"] == STATUS_FILED
    assert saved["filed_date"] == "2025-05-18"

    rows = list_gstr1a_period_actions(sb, run_id="run-1")  # type: ignore[arg-type]
    assert len(rows) == 1
    assert rows[0]["period"] == "2025-04"
