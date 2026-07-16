"""Persist and load GSTR-1 (sell-side) reconciliation runs.

Purchase-side runs live in ``reconciliation_run`` / ``reconciliation_results``.
GSTR-1 uses a dedicated ``gstr1_reconciliation_run`` table so ITC-centric
columns and billing counters stay untouched.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from supabase import Client

_log = logging.getLogger(__name__)

TABLE = "gstr1_reconciliation_run"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"


def normalise_period(raw: str | None) -> str | None:
    """Return ``YYYY-MM`` when possible from MMYYYY / YYYY-MM / ISO date."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # YYYY-MM
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s
    # MMYYYY
    if re.fullmatch(r"\d{6}", s):
        return f"{s[2:6]}-{s[0:2]}"
    # ISO date YYYY-MM-DD…
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
        return s[:7]
    return s[:7] if len(s) >= 7 else s


def save_gstr1_run(
    sb: Client,
    *,
    client_gstin_id: str,
    result: dict[str, Any],
    created_by: str | None = None,
    period: str | None = None,
) -> dict[str, Any]:
    """Insert a COMPLETED GSTR-1 run and return the inserted row (incl. id)."""
    diag = (result.get("parse_diagnostics") or {}).get("gstr1") or {}
    period_norm = normalise_period(
        period
        or diag.get("filing_period")
        or (result.get("summary") or {}).get("filing_period")
    )
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "client_gstin_id": str(client_gstin_id).strip(),
        "period": period_norm,
        "status": STATUS_COMPLETED,
        "run_summary": result.get("summary") or {},
        "result_payload": result,
        "created_by": created_by,
        "created_at": now,
        "completed_at": now,
    }
    res = sb.table(TABLE).insert(row).execute()
    data = (res.data or [None])[0]
    if not data or not data.get("id"):
        raise RuntimeError("gstr1_reconciliation_run insert returned no id")
    _log.info(
        "save_gstr1_run: id=%s client=%s period=%s",
        data["id"],
        client_gstin_id,
        period_norm,
    )
    return data


def list_gstr1_runs(
    sb: Client,
    *,
    client_gstin_id: str,
    limit: int = 20,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List runs for a client (newest first). Omits heavy result_payload."""
    q = (
        sb.table(TABLE)
        .select(
            "id, client_gstin_id, period, status, run_summary, "
            "created_by, created_at, completed_at"
        )
        .eq("client_gstin_id", str(client_gstin_id).strip())
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 200)))
    )
    if status:
        q = q.eq("status", status)
    res = q.execute()
    return list(res.data or [])


def get_gstr1_run(sb: Client, run_id: str) -> dict[str, Any] | None:
    """Fetch a single run including ``result_payload``."""
    res = (
        sb.table(TABLE)
        .select(
            "id, client_gstin_id, period, status, run_summary, "
            "result_payload, created_by, created_at, completed_at"
        )
        .eq("id", str(run_id).strip())
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def latest_completed_gstr1_run(
    sb: Client, *, client_gstin_id: str
) -> dict[str, Any] | None:
    """Newest COMPLETED run for banner / deep-link (no payload)."""
    rows = list_gstr1_runs(
        sb,
        client_gstin_id=client_gstin_id,
        limit=1,
        status=STATUS_COMPLETED,
    )
    return rows[0] if rows else None
