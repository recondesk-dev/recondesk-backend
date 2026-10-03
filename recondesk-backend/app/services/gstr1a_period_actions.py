"""Persist per-period GSTR-1A filed actions (Rule 37 settlement analogue)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

_log = logging.getLogger(__name__)

TABLE = "gstr1a_period_actions"
STATUS_FILED = "filed"


def normalise_action_period(raw: str | None) -> str | None:
    """Normalise period keys for UNIQUE(run_id, period). Prefer YYYY-MM."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{6}", s):
        return f"{s[2:6]}-{s[0:2]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
        return s[:7]
    return s[:32]


def list_gstr1a_period_actions(
    sb: Client | None = None, *, run_id: str
) -> list[dict[str, Any]]:
    """Return filed-period actions for a run (newest first)."""
    # ── Aurora Primary ────────────────────────────────────────────────────────
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        aurora_actions = repo.list_gstr1a_actions(run_id=run_id)
        if aurora_actions:
            return aurora_actions
    except Exception as exc:
        _log.warning("Aurora list_gstr1a_actions failed, falling back to Supabase: %s", exc)

    if sb is None:
        from app.database import get_supabase
        sb = get_supabase()

    res = (
        sb.table(TABLE)
        .select(
            "id, run_id, period, status, filed_date, note, user_id, created_at"
        )
        .eq("run_id", str(run_id).strip())
        .order("created_at", desc=True)
        .execute()
    )
    return list(res.data or [])


def get_gstr1a_period_action(
    sb: Client | None = None, *, run_id: str, period: str
) -> dict[str, Any] | None:
    period_norm = normalise_action_period(period)
    if not period_norm:
        return None

    # ── Aurora Primary ────────────────────────────────────────────────────────
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        aurora_action = repo.get_gstr1a_action(run_id=run_id, period=period_norm)
        if aurora_action is not None:
            return aurora_action
    except Exception as exc:
        _log.warning("Aurora get_gstr1a_action failed, falling back to Supabase: %s", exc)

    if sb is None:
        from app.database import get_supabase
        sb = get_supabase()

    res = (
        sb.table(TABLE)
        .select(
            "id, run_id, period, status, filed_date, note, user_id, created_at"
        )
        .eq("run_id", str(run_id).strip())
        .eq("period", period_norm)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def mark_gstr1a_period_filed(
    sb: Client | None = None,
    *,
    run_id: str,
    period: str,
    user_id: str,
    filed_date: date | datetime | str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Upsert a filed action for ``(run_id, period)`` (delete-then-insert)."""
    period_norm = normalise_action_period(period)
    if not period_norm:
        raise ValueError("period is required")

    filed_date_iso: str | None = None
    if filed_date is not None:
        if isinstance(filed_date, datetime):
            filed_date_iso = filed_date.date().isoformat()
        elif isinstance(filed_date, date):
            filed_date_iso = filed_date.isoformat()
        else:
            s = str(filed_date).strip()
            if s:
                filed_date_iso = s[:10]

    rid = str(run_id).strip()

    # ── Aurora Primary ────────────────────────────────────────────────────────
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        data = repo.mark_gstr1a_action(
            run_id=rid,
            period=period_norm,
            status=STATUS_FILED,
            user_id=str(user_id or "").strip(),
            note=(str(note).strip() if note else None) or None,
            filed_date=filed_date_iso or date.today().isoformat(),
        )
        if data and data.get("id"):
            _log.info(
                "mark_gstr1a_period_filed (Aurora): run=%s period=%s user=%s",
                rid,
                period_norm,
                user_id,
            )
            return data
    except Exception as exc:
        _log.warning("Aurora mark_gstr1a_action failed, falling back to Supabase: %s", exc)

    if sb is None:
        from app.database import get_supabase
        sb = get_supabase()

    # Delete-then-insert mirrors ``_upsert_rule37_action``.
    sb.table(TABLE).delete().eq("run_id", rid).eq("period", period_norm).execute()

    row = {
        "run_id": rid,
        "period": period_norm,
        "status": STATUS_FILED,
        "filed_date": filed_date_iso or date.today().isoformat(),
        "note": (str(note).strip() if note else None) or None,
        "user_id": str(user_id or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = sb.table(TABLE).insert(row).execute()
    data = (res.data or [None])[0]
    if not data or not data.get("id"):
        raise RuntimeError("gstr1a_period_actions insert returned no id")
    _log.info(
        "mark_gstr1a_period_filed (Supabase fallback): run=%s period=%s user=%s",
        rid,
        period_norm,
        user_id,
    )
    return data
