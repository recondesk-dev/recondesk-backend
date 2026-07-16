"""GSTR-1A amendment-window calculation."""

from __future__ import annotations

from datetime import date

from app.rules.gstr1a_eligibility import (
    Gstr1aWindowStatus,
    compute_gstr1a_window,
    gstr3b_due_date_monthly,
)


def test_monthly_due_date_following_month():
    assert gstr3b_due_date_monthly(2025, 4) == date(2025, 5, 20)
    assert gstr3b_due_date_monthly(2025, 12) == date(2026, 1, 20)


def test_window_closed_when_gstr3b_filed():
    out = compute_gstr1a_window(
        "2025-05-05",
        "2025-05-18",
        period="2025-04",
        as_of=date(2025, 5, 10),
    )
    assert out["status"] == Gstr1aWindowStatus.WINDOW_CLOSED.value
    assert out["days_remaining"] == 0
    assert "already filed" in (out["note"] or "").lower()


def test_days_remaining_until_20th():
    out = compute_gstr1a_window(
        "2025-05-05",
        None,
        period="2025-04",
        as_of=date(2025, 5, 10),
    )
    assert out["status"] == Gstr1aWindowStatus.OPEN.value
    assert out["gstr3b_due_date"] == "2025-05-20"
    assert out["days_remaining"] == 10


def test_expired_after_due_date():
    out = compute_gstr1a_window(
        date(2025, 5, 5),
        None,
        period="042025",
        as_of=date(2025, 5, 25),
    )
    assert out["status"] == Gstr1aWindowStatus.EXPIRED.value
    assert out["days_remaining"] == -5


def test_not_open_without_gstr1_filed_date():
    out = compute_gstr1a_window(None, period="2025-04", as_of=date(2025, 5, 10))
    assert out["status"] == Gstr1aWindowStatus.NOT_OPEN.value
    assert out["days_remaining"] is None


def test_qrmp_requires_manual_review():
    out = compute_gstr1a_window(
        "2025-05-05",
        period="2025-04",
        filing_frequency="qrmp",
        as_of=date(2025, 5, 10),
    )
    assert out["status"] == Gstr1aWindowStatus.REVIEW_REQUIRED.value
    assert out["days_remaining"] is None
    assert "QRMP" in (out["note"] or "")
