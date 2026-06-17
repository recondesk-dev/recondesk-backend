"""Supplier intelligence scoring — pure functions over pre-fetched run/GSTR rows."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from app.services.reconciliation_outcomes import parse_optional_date

_log = logging.getLogger(__name__)

TOLERANCE_PAISE = 100
FILING_RELIABLE_THRESHOLD = Decimal("0.80")
_D2 = Decimal("0.01")


def _ratio_pct_decimal(numer: int, denom: int) -> Decimal:
    if denom == 0:
        return Decimal("0")
    return Decimal(numer) * Decimal(100) / Decimal(denom)


def _final_quantize(d: Decimal) -> Decimal:
    return d.quantize(_D2, rounding=ROUND_HALF_UP)


def _is_grouped_by_run(runs_history: list[dict[str, Any]]) -> bool:
    """True when *runs_history* is [{run_id, period_end_date?, records: [...]}, ...]."""
    if not runs_history:
        return False
    h0 = runs_history[0]
    return bool(
        isinstance(h0, dict)
        and "records" in h0
        and isinstance(h0.get("records"), list)
    )


def expand_runs_history(runs_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Flatten grouped runs into invoice-level dicts with reconciliation_run_id
    and period_end_date filled from the parent run when missing.
    If already flat (legacy), return shallow copies.
    """
    if not runs_history:
        return []
    if _is_grouped_by_run(runs_history):
        out: list[dict[str, Any]] = []
        for run in runs_history:
            run_id = str(run.get("run_id") or "").strip()
            pend = run.get("period_end_date") or run.get("gstr_period_end")
            for rec in run.get("records") or []:
                if not isinstance(rec, dict):
                    continue
                merged = dict(rec)
                if run_id and not str(merged.get("reconciliation_run_id") or "").strip():
                    merged["reconciliation_run_id"] = run_id
                if pend is not None and merged.get("period_end_date") is None:
                    merged["period_end_date"] = pend
                out.append(merged)
        return out
    return [dict(x) for x in runs_history]


def _parse_created_at(rec: dict[str, Any]) -> str:
    v = rec.get("created_at")
    if v is None:
        return ""
    return str(v)


def _invoice_date_key(rec: dict[str, Any]) -> str:
    raw = rec.get("invoice_date")
    d = parse_optional_date(raw)
    if d is None:
        return str(raw).strip() if raw is not None else ""
    return d.isoformat()


def _dedup_key(rec: dict[str, Any]) -> tuple[str, str, str, str]:
    sg = str(rec.get("supplier_gstin") or "").strip().upper()
    inv = str(rec.get("invoice_number") or "").strip()
    idate = _invoice_date_key(rec)
    rid = str(rec.get("reconciliation_run_id") or "").strip()
    return (sg, inv, idate, rid)


def dedupe_gstr_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Within each reconciliation_run_id, keep latest created_at per dedup key."""
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in rows:
        rid = str(rec.get("reconciliation_run_id") or "").strip()
        by_run[rid].append(rec)
    out: list[dict[str, Any]] = []
    for rid, group in by_run.items():
        del rid
        best: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for rec in group:
            k = _dedup_key(rec)
            cur = best.get(k)
            if cur is None or _parse_created_at(rec) > _parse_created_at(cur):
                best[k] = rec
        out.extend(best.values())
    return out


def _is_tolerance_match(amount_difference_paise: Any) -> bool:
    if amount_difference_paise is None:
        return False
    try:
        v = int(amount_difference_paise)
    except (TypeError, ValueError):
        return False
    return abs(v) <= TOLERANCE_PAISE


def _is_l1_exact(amount_difference_paise: Any) -> bool:
    if amount_difference_paise is None:
        return False
    try:
        return int(amount_difference_paise) == 0
    except (TypeError, ValueError):
        return False


def _is_mismatch(amount_difference_paise: Any) -> bool:
    if amount_difference_paise is None:
        return True
    try:
        return abs(int(amount_difference_paise)) > TOLERANCE_PAISE
    except (TypeError, ValueError):
        return True


def _parse_period_end(rec: dict[str, Any]) -> date | None:
    return parse_optional_date(rec.get("period_end_date"))


def _parse_reflection(rec: dict[str, Any]) -> date | None:
    return parse_optional_date(rec.get("gstr2b_reflection_date"))


def supplier_distinct_run_ids(rows: Iterable[dict[str, Any]], supplier_gstin: str) -> set[str]:
    sg = supplier_gstin.strip().upper()
    return {
        str(r.get("reconciliation_run_id") or "").strip()
        for r in rows
        if str(r.get("supplier_gstin") or "").strip().upper() == sg
        and str(r.get("reconciliation_run_id") or "").strip()
    }


def _runs_appeared_run_ids(
    runs_history: list[dict[str, Any]], supplier_gstin: str
) -> set[str]:
    """Distinct run ids where *supplier_gstin* has at least one record (one count per run)."""
    sg_u = supplier_gstin.strip().upper()
    if not runs_history:
        return set()
    if _is_grouped_by_run(runs_history):
        runs_appeared: set[str] = set()
        for run in runs_history:
            run_id = str(run.get("run_id") or "").strip()
            for record in run.get("records") or []:
                if not isinstance(record, dict):
                    continue
                if str(record.get("supplier_gstin") or "").strip().upper() == sg_u:
                    if run_id:
                        runs_appeared.add(run_id)
                    break
        return runs_appeared
    return supplier_distinct_run_ids(runs_history, supplier_gstin)


def supplier_gstins_from_runs_history(
    runs_history: list[dict[str, Any]],
) -> set[str]:
    """Distinct supplier GSTINs appearing in *runs_history* (grouped or flat)."""
    suppliers: set[str] = set()
    if not runs_history:
        return suppliers
    if _is_grouped_by_run(runs_history):
        for run in runs_history:
            for record in run.get("records") or []:
                if not isinstance(record, dict):
                    continue
                gstin = record.get("supplier_gstin")
                if gstin:
                    suppliers.add(str(gstin).strip().upper())
        return suppliers
    for rec in runs_history:
        if not isinstance(rec, dict):
            continue
        gstin = rec.get("supplier_gstin")
        if gstin:
            suppliers.add(str(gstin).strip().upper())
    return suppliers


def count_ineligible_suppliers(
    all_rows: list[dict[str, Any]], min_runs: int = 2
) -> tuple[set[str], int]:
    """Return (eligible supplier_gstin set, count of ineligible distinct suppliers)."""
    flat = expand_runs_history(all_rows)
    by_supplier: dict[str, set[str]] = defaultdict(set)
    for rec in flat:
        sg = str(rec.get("supplier_gstin") or "").strip().upper()
        if not sg:
            continue
        rid = str(rec.get("reconciliation_run_id") or "").strip()
        if rid:
            by_supplier[sg].add(rid)
    eligible: set[str] = set()
    ineligible_count = 0
    for sg, runs in by_supplier.items():
        if len(runs) >= min_runs:
            eligible.add(sg)
        else:
            ineligible_count += 1
    return eligible, ineligible_count


def calculate_supplier_score(
    supplier_gstin: str,
    trade_name: str,
    runs_history: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """
    Pure function: metrics from pre-fetched history for *all* suppliers; filters to *supplier_gstin*.

    Returns ``None`` when the supplier appears in fewer than two distinct runs (ineligible).

    *runs_history* is either:

    - Grouped: ``[{"run_id", "period_end_date"?, "records": [ {...}, ... ]}, ...]``
    - Flat (legacy): list of invoice dicts with ``reconciliation_run_id`` on each row.

    Invoice dicts use: supplier_gstin, invoice_number, invoice_date,
    amount_difference_paise, gstr2b_reflection_date (optional), period_end_date (optional),
    created_at (optional); ``reconciliation_run_id`` is injected from the parent run when grouped.
    """
    del trade_name  # caller attaches trade_name in API layer; scoring must not invent it
    sg_u = supplier_gstin.strip().upper()
    flat = expand_runs_history(runs_history)
    mine = [r for r in flat if str(r.get("supplier_gstin") or "").strip().upper() == sg_u]
    run_ids_raw = _runs_appeared_run_ids(runs_history, supplier_gstin)
    runs_appeared_in = len(run_ids_raw)
    if runs_appeared_in < 2:
        return None
    reliable_runs = 0
    if runs_appeared_in > 0:
        deduped = dedupe_gstr_rows(mine)
        by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rec in deduped:
            by_run[str(rec.get("reconciliation_run_id") or "").strip()].append(rec)
        for rid in run_ids_raw:
            invs = by_run.get(rid, [])
            n = len(invs)
            if n == 0:
                continue
            tol = sum(1 for r in invs if _is_tolerance_match(r.get("amount_difference_paise")))
            if Decimal(tol) / Decimal(n) >= FILING_RELIABLE_THRESHOLD:
                reliable_runs += 1

    filing_pct = _final_quantize(
        _ratio_pct_decimal(reliable_runs, runs_appeared_in)
    )

    deduped_all = dedupe_gstr_rows(mine)
    denom = len(deduped_all)
    exact_n = sum(1 for r in deduped_all if _is_l1_exact(r.get("amount_difference_paise")))
    accuracy_raw = _ratio_pct_decimal(exact_n, denom)
    accuracy_pct = _final_quantize(accuracy_raw)
    mismatch_count = sum(
        1 for r in deduped_all if _is_mismatch(r.get("amount_difference_paise"))
    )

    late_days_vals: list[int] = []
    for rec in deduped_all:
        ref = _parse_reflection(rec)
        if ref is None:
            continue
        pend = _parse_period_end(rec)
        if pend is None:
            continue
        if ref <= pend:
            continue
        inv_d = parse_optional_date(rec.get("invoice_date"))
        if inv_d is None:
            continue
        late_days = (ref - inv_d).days
        if late_days <= 0:
            _log.warning(
                "avg_late_days: skipping non-positive late_days=%s invoice_number=%s",
                late_days,
                rec.get("invoice_number"),
            )
            continue
        late_days_vals.append(late_days)

    if not late_days_vals:
        avg_late_raw = Decimal("0")
    else:
        s = sum(late_days_vals)
        avg_late_raw = Decimal(s) / Decimal(len(late_days_vals))
    avg_late = _final_quantize(avg_late_raw)

    if filing_pct >= Decimal("95"):
        risk_level = "LOW"
    elif filing_pct >= Decimal("80"):
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    return {
        "filing_reliability_pct": filing_pct,
        "amount_accuracy_pct": accuracy_pct,
        "avg_late_days": avg_late,
        "mismatch_count": int(mismatch_count),
        "runs_appeared_in": int(runs_appeared_in),
        "risk_level": risk_level,
    }


def score_to_api_dict(
    supplier_gstin: str,
    trade_name: str,
    score: dict[str, Any],
) -> dict[str, Any]:
    """Emit API row; floats from ROUND_HALF_UP 2dp Decimals."""
    out = {
        "supplier_gstin": supplier_gstin,
        "trade_name": trade_name,
        "filing_reliability_pct": float(score["filing_reliability_pct"]),
        "amount_accuracy_pct": float(score["amount_accuracy_pct"]),
        "avg_late_days": float(score["avg_late_days"]),
        "mismatch_count": int(score["mismatch_count"]),
        "runs_appeared_in": int(score["runs_appeared_in"]),
        "risk_level": str(score["risk_level"]),
    }
    return out
