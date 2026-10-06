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


import base64
import gzip
import json
import os
import uuid

from app.services.r2_service import (
    download_file_from_r2,
    is_r2_configured,
    upload_bytes_to_r2,
)


def _hydrate_result_payload(payload: Any) -> Any:
    """Transparently unpack R2 or compressed result payloads."""
    if isinstance(payload, dict) and payload.get("_storage") == "r2":
        path = payload.get("path")
        if path:
            try:
                raw = download_file_from_r2(path)
                return json.loads(gzip.decompress(raw).decode("utf-8"))
            except Exception as exc:
                _log.error("Failed to load GSTR-1 R2 payload from %s: %s", path, exc)
                return payload
    if isinstance(payload, dict) and payload.get("_storage") == "gzip_b64":
        data_b64 = payload.get("data")
        if data_b64:
            try:
                return json.loads(gzip.decompress(base64.b64decode(data_b64)).decode("utf-8"))
            except Exception as exc:
                _log.error("Failed to decode gzip_b64 GSTR-1 payload: %s", exc)
                return payload
    if isinstance(payload, str) and not payload.strip().startswith(("{", "[")):
        try:
            return json.loads(gzip.decompress(base64.b64decode(payload)).decode("utf-8"))
        except Exception:
            pass
    return payload


def save_gstr1_run(
    sb: Client,
    *,
    client_gstin_id: str,
    result: dict[str, Any],
    created_by: str | None = None,
    period: str | None = None,
    gstr1_filed_date: date | datetime | str | None = None,
    gstr3b_filed_date: date | datetime | str | None = None,
    run_id: str | None = None,
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
    target_run_id = str(run_id or uuid.uuid4()).strip()

    # Offload large payload to R2 or compress to avoid PostgREST statement timeouts
    stored_payload: Any = result
    try:
        raw_bytes = json.dumps(result).encode("utf-8")
        raw_size = len(raw_bytes)
        compressed_bytes = gzip.compress(raw_bytes)
        comp_size = len(compressed_bytes)

        if is_r2_configured():
            target_path = f"gstr1-payloads/{target_run_id}.json.gz"
            upload_bytes_to_r2(compressed_bytes, target_path, content_type="application/gzip")
            stored_payload = {
                "_storage": "r2",
                "path": target_path,
                "size": raw_size,
                "compressed_size": comp_size,
            }
            _log.info(
                "save_gstr1_run: offloaded payload to R2 path=%s (raw=%.2fMB, comp=%.2fMB)",
                target_path,
                raw_size / (1024 * 1024),
                comp_size / (1024 * 1024),
            )
        elif raw_size > 500 * 1024:
            # Fallback to compressed b64 payload in DB
            stored_payload = {
                "_storage": "gzip_b64",
                "data": base64.b64encode(compressed_bytes).decode("utf-8"),
                "size": raw_size,
                "compressed_size": comp_size,
            }
    except Exception as exc:
        _log.warning("save_gstr1_run: payload offload/compression failed (%s); using raw result", exc)
        stored_payload = result

    row = {
        "id": target_run_id,
        "client_gstin_id": str(client_gstin_id).strip(),
        "period": period_norm,
        "status": STATUS_COMPLETED,
        "run_summary": summary,
        "result_payload": stored_payload,
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
        "save_gstr1_run: id=%s client=%s period=%s g1_filed=%s g3_filed=%s",
        data["id"],
        client_gstin_id,
        period_norm,
        g1_filed,
        g3_filed,
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
        .select(_RUN_LIST_COLS)
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
        .select(_RUN_DETAIL_COLS)
        .eq("id", str(run_id).strip())
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    run = dict(rows[0])
    if "result_payload" in run:
        run["result_payload"] = _hydrate_result_payload(run["result_payload"])
    return run


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
