import io

import pandas as pd
import pytest

from app.services.reconciliation_service import reconcile
from app.models.reconciliation import MatchStatus


def _make_df(data: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(data)


def test_perfect_match():
    source = _make_df([{"id": "1", "amount": "100"}, {"id": "2", "amount": "200"}])
    target = _make_df([{"id": "1", "amount": "100"}, {"id": "2", "amount": "200"}])
    rows, summary = reconcile(source, target, match_columns=["id", "amount"])
    assert summary["matched"] == 2
    assert summary["unmatched"] == 0


def test_partial_match():
    source = _make_df([{"id": "1", "amount": "100"}])
    target = _make_df([{"id": "1", "amount": "150"}])
    rows, summary = reconcile(source, target, match_columns=["id"])
    assert len(rows) == 1
    assert rows[0].match_status in (MatchStatus.MATCHED, MatchStatus.PARTIAL)


def test_unmatched_row():
    source = _make_df([{"id": "99", "amount": "500"}])
    target = _make_df([{"id": "1", "amount": "100"}])
    rows, summary = reconcile(source, target, match_columns=["id"])
    assert summary["unmatched"] == 1


def test_tolerance_numeric():
    source = _make_df([{"id": "1", "amount": "100.00"}])
    target = _make_df([{"id": "1", "amount": "100.50"}])
    rows, summary = reconcile(source, target, match_columns=["id"], tolerance=1.0)
    assert rows[0].match_status == MatchStatus.MATCHED


def test_empty_source():
    source = _make_df([])
    target = _make_df([{"id": "1", "amount": "100"}])
    rows, summary = reconcile(source, target, match_columns=["id"])
    assert summary["total"] == 0
