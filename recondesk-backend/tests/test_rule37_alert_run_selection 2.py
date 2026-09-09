"""Unit tests for Rule 37 alert per-period run selection + empty-PR fallback."""

from __future__ import annotations

from app.services.rule37_alert_scan import select_alert_run_ids_by_period


def test_picks_latest_run_per_period_not_client_global_latest():
    """Newer May run must not hide an older April run for another period."""
    runs = [
        {"id": "may-new", "period": "2025-05", "created_at": "2025-06-10T00:00:00Z"},
        {"id": "apr-old", "period": "2025-04", "created_at": "2025-05-01T00:00:00Z"},
    ]
    nonempty = {"may-new", "apr-old"}
    got = select_alert_run_ids_by_period(
        runs, has_pr_records=lambda rid: rid in nonempty
    )
    assert set(got) == {"may-new", "apr-old"}
    # Newer period first
    assert got[0] == "may-new"


def test_falls_back_when_newest_run_for_period_has_no_pr():
    """Thin re-run for same period must not drop Rule 37 from the older PR-bearing run."""
    runs = [
        {"id": "apr-thin", "period": "2025-04", "created_at": "2025-05-20T00:00:00Z"},
        {"id": "apr-full", "period": "2025-04", "created_at": "2025-05-01T00:00:00Z"},
        {"id": "may-full", "period": "2025-05", "created_at": "2025-06-01T00:00:00Z"},
    ]
    nonempty = {"apr-full", "may-full"}  # apr-thin has no PR
    got = select_alert_run_ids_by_period(
        runs, has_pr_records=lambda rid: rid in nonempty
    )
    assert set(got) == {"apr-full", "may-full"}
    assert "apr-thin" not in got


def test_skips_period_when_no_run_has_pr():
    runs = [
        {"id": "apr-empty-1", "period": "2025-04", "created_at": "2025-05-20T00:00:00Z"},
        {"id": "apr-empty-2", "period": "2025-04", "created_at": "2025-05-01T00:00:00Z"},
    ]
    got = select_alert_run_ids_by_period(runs, has_pr_records=lambda _rid: False)
    assert got == []


def test_normalizes_period_formats_before_grouping():
    """YYYY-MM-DD and YYYY-MM for the same month collapse to one period slot."""
    runs = [
        {
            "id": "newer-ymd",
            "period": "2025-04-01",
            "created_at": "2025-05-20T00:00:00Z",
        },
        {
            "id": "older-ym",
            "period": "2025-04",
            "created_at": "2025-05-01T00:00:00Z",
        },
    ]
    nonempty = {"newer-ymd", "older-ym"}
    got = select_alert_run_ids_by_period(
        runs, has_pr_records=lambda rid: rid in nonempty
    )
    assert got == ["newer-ymd"]


def test_prefers_newest_when_both_have_pr():
    runs = [
        {"id": "apr-new", "period": "2025-04", "created_at": "2025-05-20T00:00:00Z"},
        {"id": "apr-old", "period": "2025-04", "created_at": "2025-05-01T00:00:00Z"},
    ]
    nonempty = {"apr-new", "apr-old"}
    got = select_alert_run_ids_by_period(
        runs, has_pr_records=lambda rid: rid in nonempty
    )
    assert got == ["apr-new"]
