"""Rule 37 counts and resolve lookups from ``reconciliation_results`` JSON (payload/record_data).

The table is expected to expose only: id, run_id, record_data, created_at, payload.
Per-line fields such as pr_id or rule37_flag are **inside** the JSON, not table columns.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Tuple

from supabase import Client

from app.services.reconciliation_outcomes import RULE37_CONCERNS


def _as_dict(blob: Any) -> dict[str, Any]:
    if blob is None:
        return {}
    if isinstance(blob, dict):
        return blob
    if isinstance(blob, str):
        try:
            p = json.loads(blob)
        except (json.JSONDecodeError, TypeError):
            return {}
        return p if isinstance(p, dict) else {}
    return {}


def _merged_result_doc(record_data: Any, payload: Any) -> dict[str, Any]:
    """Prefer *payload* when present, otherwise *record_data*."""
    p = _as_dict(payload)
    if p:
        return p
    return _as_dict(record_data)


def _rule37_items(doc: dict[str, Any]) -> list[dict[str, Any]]:
    comp = doc.get("compliance")
    if not isinstance(comp, dict):
        return []
    r = comp.get("rule37")
    if not isinstance(r, list):
        return []
    out: list[dict[str, Any]] = []
    for x in r:
        if isinstance(x, dict):
            out.append(x)
    return out


def _is_rule37_concern(item: dict[str, Any]) -> bool:
    if item.get("rule37_flag") is True:
        return True
    if (item.get("status") or "") in RULE37_CONCERNS:
        return True
    return False


def _rule37_record_id(item: dict[str, Any]) -> str | None:
    """Stable record id for a rule37 payload entry.

    Must match the id format produced by ``_rule37_stable_id`` in
    ``app.routers.reconciliation_api``. When ``pr_id`` is missing we hash the
    invoice identifiers so the id stays stable across requests.
    """
    pr_id = str(item.get("pr_id") or "").strip()
    if pr_id:
        return f"r37:{pr_id}"
    key = "|".join(
        [
            str(item.get("supplier_gstin") or ""),
            str(item.get("invoice_number") or ""),
            str(item.get("invoice_date") or ""),
            str(item.get("itc_at_risk_paise") or 0),
        ]
    )
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"r37:h:{digest}"


def _rule37_action_record_ids(sb: Client, run_id: str) -> set[str]:
    try:
        r = (
            sb.table("mismatch_notes")
            .select("record_id, note")
            .eq("run_id", run_id)
            .eq("note_type", "rule37_action")
            .execute()
        )
    except Exception:
        return set()
    acted: set[str] = set()
    for row in r.data or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("note") or "").strip().lower()
        record_id = str(row.get("record_id") or "").strip()
        if status in {"resolved", "acknowledged"} and record_id:
            acted.add(record_id)
    return acted


def count_rule37_needs_in_doc(doc: dict[str, Any]) -> int:
    """Count Rule 37 line items in *doc* that require resolution (flag or concern status)."""
    return sum(1 for it in _rule37_items(doc) if _is_rule37_concern(it))


def _fetch_result_docs(sb: Client, run_id: str) -> list[dict[str, Any]]:
    r = (
        sb.table("reconciliation_results")
        .select("id, run_id, record_data, payload, created_at")
        .eq("run_id", run_id)
        .execute()
    )
    return [d for d in (r.data or []) if isinstance(d, dict)]


def sync_rule37_invoice_results(sb: Client, run_id: str) -> None:
    """No-op: outcomes live in the stored JSON; there are no per-line columns to sync.

    Kept for call-site compatibility; counting reads JSON directly in
    :func:`count_unresolved_rule37`.
    """
    del sb, run_id


def count_unresolved_rule37(sb: Client, run_id: str) -> Tuple[int, int, int]:
    """Returns (need, have, unresolved) for finalize pre-check.

    *need* = number of compliance.rule37 entries in stored JSON (payload or
    record_data) with ``rule37_flag is True`` or a ``status`` in
    :data:`RULE37_CONCERNS`, summed across all ``reconciliation_results`` rows
    for this *run_id*.

    *have* = number of ``rule37_resolutions`` for this run.

    *unresolved* = max(0, need - have).
    """
    sync_rule37_invoice_results(sb, run_id)
    need = 0
    acted = _rule37_action_record_ids(sb, run_id)
    acted_needed = 0
    for row in _fetch_result_docs(sb, run_id):
        doc = _merged_result_doc(row.get("record_data"), row.get("payload"))
        for item in _rule37_items(doc):
            if not _is_rule37_concern(item):
                continue
            need += 1
            record_id = _rule37_record_id(item)
            if record_id and record_id in acted:
                acted_needed += 1

    n2 = (
        sb.table("rule37_resolutions")
        .select("id", count="exact")
        .eq("run_id", run_id)
        .limit(0)
        .execute()
    )
    legacy_have = int(n2.count or 0)
    have = min(need, acted_needed + legacy_have)
    return need, have, max(0, need - have)


def find_invoice_result_id_for_pr(
    sb: Client, run_id: str, pr_id: str
) -> Optional[str]:
    """Return ``reconciliation_results.id`` for a row whose JSON lists *pr_id* as a Rule 37 concern.

    Scans *payload* first, then *record_data*. Returns ``None`` if no match.
    """
    pr_key = str(pr_id).strip()
    for row in _fetch_result_docs(sb, run_id):
        doc = _merged_result_doc(row.get("record_data"), row.get("payload"))
        for it in _rule37_items(doc):
            if str(it.get("pr_id", "")).strip() != pr_key:
                continue
            if not _is_rule37_concern(it):
                continue
            rid = row.get("id")
            if rid is not None:
                return str(rid).strip() or None
    return None
