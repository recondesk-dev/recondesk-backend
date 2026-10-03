"""Persist and load GSTR-1 (sell-side) reconciliation runs.

Purchase-side runs live in ``reconciliation_run`` / ``reconciliation_results``.
GSTR-1 uses a dedicated ``gstr1_reconciliation_run`` table so ITC-centric
columns and billing counters stay untouched.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

_log = logging.getLogger(__name__)

TABLE = "gstr1_reconciliation_run"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

_RUN_LIST_COLS = (
    "id, client_gstin_id, period, status, run_summary, "
    "gstr1_filed_date, gstr3b_filed_date, "
    "created_by, created_at, completed_at"
)
_RUN_DETAIL_COLS = (
    "id, client_gstin_id, period, status, run_summary, "
    "result_payload, gstr1_filed_date, gstr3b_filed_date, "
    "created_by, created_at, completed_at"
)


def normalise_period(raw: str | None) -> str | None:
    """Return ``YYYY-MM`` when possible from MMYYYY / YYYY-MM / ISO date."""
    if not raw:
        return None
    try:
        from app.services.normalizer import normalize_period_to_yyyy_mm
        return normalize_period_to_yyyy_mm(raw)
    except Exception:
        s = str(raw).strip()
        return s[:7] if len(s) >= 7 else s


def _normalise_filed_date(raw: date | datetime | str | None) -> str | None:
    """Return ``YYYY-MM-DD`` for DB date columns, or ``None``."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    s = str(raw).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


def save_gstr1_run(
    sb: Client | None = None,
    *,
    client_gstin_id: str,
    result: dict[str, Any],
    created_by: str | None = None,
    period: str | None = None,
    gstr1_filed_date: date | datetime | str | None = None,
    gstr3b_filed_date: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Insert a COMPLETED GSTR-1 run and return the inserted row (incl. id)."""
    diag = (result.get("parse_diagnostics") or {}).get("gstr1") or {}
    summary = result.get("summary") or {}
    period_norm = normalise_period(
        period
        or diag.get("filing_period")
        or summary.get("filing_period")
    )
    g1_filed = _normalise_filed_date(
        gstr1_filed_date
        or summary.get("gstr1_filed_date")
        or result.get("gstr1_filed_date")
    )
    g3_filed = _normalise_filed_date(
        gstr3b_filed_date
        or summary.get("gstr3b_filed_date")
        or result.get("gstr3b_filed_date")
    )
    now = datetime.now(timezone.utc).isoformat()

    # ── Aurora Primary ────────────────────────────────────────────────────────
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        data = repo.create_gstr1_run(
            client_gstin_id=client_gstin_id,
            status=STATUS_COMPLETED,
            result_payload=result,
            run_summary=summary,
            period=period_norm,
            gstr1_filed_date=g1_filed,
            gstr3b_filed_date=g3_filed,
            created_by=created_by,
            created_at=now,
            completed_at=now,
        )
        if data and data.get("id"):
            _log.info(
                "save_gstr1_run (Aurora): id=%s client=%s period=%s",
                data["id"],
                client_gstin_id,
                period_norm,
            )
            return data
    except Exception as exc:
        _log.warning("Aurora save_gstr1_run failed, falling back to Supabase: %s", exc)

    if sb is None:
        from app.database import get_supabase
        sb = get_supabase()

    row = {
        "client_gstin_id": str(client_gstin_id).strip(),
        "period": period_norm,
        "status": STATUS_COMPLETED,
        "run_summary": summary,
        "result_payload": result,
        "gstr1_filed_date": g1_filed,
        "gstr3b_filed_date": g3_filed,
        "created_by": created_by,
        "created_at": now,
        "completed_at": now,
    }
    res = sb.table(TABLE).insert(row).execute()
    data = (res.data or [None])[0]
    if not data or not data.get("id"):
        raise RuntimeError("gstr1_reconciliation_run insert returned no id")
    _log.info(
        "save_gstr1_run (Supabase fallback): id=%s client=%s period=%s g1_filed=%s g3_filed=%s",
        data["id"],
        client_gstin_id,
        period_norm,
        g1_filed,
        g3_filed,
    )
    return data


def list_gstr1_runs(
    sb: Client | None = None,
    *,
    client_gstin_id: str,
    limit: int = 20,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List runs for a client (newest first). Omits heavy result_payload."""
    # ── Aurora Primary ────────────────────────────────────────────────────────
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        aurora_runs = repo.list_gstr1_runs(
            client_gstin_id=client_gstin_id,
            limit=limit,
            status=status,
            include_payload=False,
        )
        if aurora_runs:
            return aurora_runs
    except Exception as exc:
        _log.warning("Aurora list_gstr1_runs failed, falling back to Supabase: %s", exc)

    if sb is None:
        from app.database import get_supabase
        sb = get_supabase()

    q = (
        sb.table(TABLE)
        .select(_RUN_LIST_COLS)
        .eq("client_gstin_id", str(client_gstin_id).strip())
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 200)))
    )
    if status:
        q = q.eq("status", status)
    res = q.execute()
    return list(res.data or [])


def get_gstr1_run(sb: Client | None, run_id: str) -> dict[str, Any] | None:
    """Fetch a single run including ``result_payload``."""
    # ── Aurora Primary ────────────────────────────────────────────────────────
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        aurora_run = repo.get_gstr1_run(run_id=run_id, include_payload=True)
        if aurora_run is not None:
            return aurora_run
    except Exception as exc:
        _log.warning("Aurora get_gstr1_run failed, falling back to Supabase: %s", exc)

    if sb is None:
        from app.database import get_supabase
        sb = get_supabase()

    res = (
        sb.table(TABLE)
        .select(_RUN_DETAIL_COLS)
        .eq("id", str(run_id).strip())
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def latest_completed_gstr1_run(
    sb: Client | None, *, client_gstin_id: str
) -> dict[str, Any] | None:
    """Newest COMPLETED run for banner / deep-link (no payload)."""
    rows = list_gstr1_runs(
        sb,
        client_gstin_id=client_gstin_id,
        limit=1,
        status=STATUS_COMPLETED,
    )
    return rows[0] if rows else None
