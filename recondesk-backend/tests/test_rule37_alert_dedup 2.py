"""Unit tests for Rule 37 alert dedup / tier escalation helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.rule37_alert_scan import (
    WARNING_30_DAYS,
    WARNING_60_DAYS,
    OVERDUE_UNPAID,
    _should_send_for_dedup,
)


def test_first_alert_always_sends():
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    assert _should_send_for_dedup(None, WARNING_60_DAYS, now=now) is True


def test_same_tier_within_cooldown_skips():
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    prior = {
        "last_alert_tier": WARNING_60_DAYS,
        "last_sent_at": (now - timedelta(days=2)).isoformat(),
    }
    assert _should_send_for_dedup(prior, WARNING_60_DAYS, now=now) is False


def test_same_tier_after_cooldown_sends():
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    prior = {
        "last_alert_tier": WARNING_60_DAYS,
        "last_sent_at": (now - timedelta(days=8)).isoformat(),
    }
    assert _should_send_for_dedup(prior, WARNING_60_DAYS, now=now) is True


def test_tier_escalation_sends_immediately():
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    prior = {
        "last_alert_tier": WARNING_60_DAYS,
        "last_sent_at": now.isoformat(),
    }
    assert _should_send_for_dedup(prior, WARNING_30_DAYS, now=now) is True
    assert _should_send_for_dedup(prior, OVERDUE_UNPAID, now=now) is True
