"""ITC Command Center Service.

Aggregates client-level reconciliation, statutory Table 4, and actionable exceptions
into the executive Command Center representation for Chartered Accountants.
Conforms strictly to Phase 5.1 specifications.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from supabase import Client

from app.services import reconciliation_outcomes as ro
from app.services.gstr3b_table4_engine import (
    check_finalization_blocking_exceptions,
    compile_gstr3b_table4,
    load_exception_dispositions,
    paise_to_rupees,
)

_log = logging.getLogger(__name__)


def _parse_date_safe(d_str: Optional[str]) -> Optional[date]:
    if not d_str:
        return None
    d_clean = str(d_str).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(d_clean, fmt).date()
        except ValueError:
            pass
    return None


def _calculate_age_days(invoice_date_str: Optional[str], ref_date: Optional[date] = None) -> int:
    inv_d = _parse_date_safe(invoice_date_str)
    if not inv_d:
        return 0
    today = ref_date or datetime.now(timezone.utc).date()
    delta = (today - inv_d).days
    return max(0, delta)


def get_itc_command_center_data(
    sb: Client,
    client_id: str,
    *,
    period: Optional[str] = None,
    priority_filter: Optional[str] = None,
    exception_type_filter: Optional[str] = None,
    search: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Compile the ITC Command Center executive dashboard and actionable work queue for a client."""
    # 1. Fetch Client Profile
    client_res = (
        sb.table("client_gstins")
        .select("id, gstin, trade_name, legal_name, pan, is_active, assigned_to")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    if not client_res.data:
        raise ValueError(f"Client not found: {client_id}")
    client_data = client_res.data[0]

    # 2. Fetch All Reconciliation Runs for Client
    runs_res = (
        sb.table("reconciliation_run")
        .select("id, period, status, is_locked, table4_summary_id, run_summary, created_at, finalized_at, finalized_by")
        .eq("client_gstin_id", client_id)
        .order("period", desc=True)
        .execute()
    )
    all_runs = runs_res.data or []

    # Map available periods
    period_options: list[dict[str, Any]] = []
    run_by_period: dict[str, dict[str, Any]] = {}
    for r in all_runs:
        p = str(r.get("period") or "").strip()
        if p and p not in run_by_period:
            run_by_period[p] = r
            period_options.append({
                "period": p,
                "run_id": str(r.get("id")),
                "status": str(r.get("status") or "DRAFT"),
                "is_locked": bool(r.get("is_locked")),
                "finalized_at": r.get("finalized_at"),
            })

    # 3. Resolve Target Run for Selected Period
    selected_period = period or (period_options[0]["period"] if period_options else None)
    target_run = run_by_period.get(selected_period) if selected_period else (all_runs[0] if all_runs else None)

    # 4. Compile Authoritative KPI Values
    eligible_itc_paise = 0
    on_hold_itc_paise = 0
    at_risk_itc_paise = 0
    missed_itc_paise = 0
    reversed_itc_paise = 0
    reclaimed_itc_paise = 0
    net_itc_paise = 0

    run_id: Optional[str] = None
    run_status: Optional[str] = None
    is_locked: bool = False
    audit_hash: Optional[str] = None
    finalized_at: Optional[str] = None
    finalized_by: Optional[str] = None

    all_outcomes: list[Any] = []
    blocking_record_ids: set[str] = set()
    dispositions: dict[str, dict[str, Any]] = {}

    if target_run:
        run_id = str(target_run["id"])
        run_status = str(target_run.get("status") or "").upper()
        is_locked = bool(target_run.get("is_locked"))
        finalized_at = target_run.get("finalized_at")
        finalized_by = target_run.get("finalized_by")

        # Load payload & outcome rows
        p = ro.load_payload(sb, run_id) or {}
        outcome_tuple = ro.build_outcome_rows(sb, run_id, p)
        all_outcomes = outcome_tuple[0]
        stats = outcome_tuple[2] or {}
        dispositions = load_exception_dispositions(sb, run_id)

        # Gate Audit check
        gate = check_finalization_blocking_exceptions(sb, run_id, payload=p)
        for b in gate.get("blocking_records", []):
            blocking_record_ids.add(str(b.get("record_id")))

        # Check Table 4 Snapshot if finalized
        snap_res = (
            sb.table("gstr3b_table4_summaries")
            .select("*")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
        )
        if snap_res.data and snap_res.data[0].get("status") == "FINALIZED":
            snap = snap_res.data[0]
            audit_hash = snap.get("audit_hash")
            eligible_itc_paise = snap.get("table_4a5", {}).get("total_tax_paise", 0)
            reversed_itc_paise = snap.get("table_4b_total", {}).get("total_tax_paise", 0)
            reclaimed_itc_paise = snap.get("table_4d1", {}).get("total_tax_paise", 0)
            net_itc_paise = snap.get("table_4c", {}).get("total_tax_paise", 0)
        else:
            # Aggregate via Table 4 Engine
            try:
                compiled = compile_gstr3b_table4(sb, run_id, payload=p)
                audit_hash = compiled.get("audit_hash")
                t4 = compiled.get("table_4", {})
                eligible_itc_paise = t4.get("section_4a", {}).get("row_4a5_all_other_itc", {}).get("total_tax_paise", 0)
                reversed_itc_paise = t4.get("section_4b", {}).get("total_4b", {}).get("total_tax_paise", 0)
                reclaimed_itc_paise = t4.get("section_4d", {}).get("row_4d1_reclaimed", {}).get("total_tax_paise", 0)
                net_itc_paise = t4.get("section_4c_net_itc", {}).get("total_tax_paise", 0)
            except Exception:
                _log.warning("compile_gstr3b_table4 fallback in command center for %s", run_id, exc_info=True)

        # Sourced from run outcome stats / run summary
        rs = target_run.get("run_summary") if isinstance(target_run.get("run_summary"), dict) else {}
        missed_itc_paise = int(stats.get("missed_itc_paise") or rs.get("missed_itc_paise") or 0)
        at_risk_itc_paise = int(
            stats.get("wrongful_risk_paise")
            or rs.get("wrongful_itc")
            or rs.get("itc_at_risk")
            or 0
        )

        # On hold credits (goods not received / hold dispositions)
        for r in all_outcomes:
            d = dispositions.get(r.id) or dispositions.get(f"{r.id}:{r.category.upper()}")
            d_code = str(d.get("disposition", "")).upper() if d else ""
            if d_code in ("HELD_GOODS_NOT_RECEIVED", "HOLD", "GOODS_IN_TRANSIT") or r.match_status == "HOLD":
                on_hold_itc_paise += int(r.amount or 0)

    # 5. Formulate Prioritized Work Items
    work_items: list[dict[str, Any]] = []

    for r in all_outcomes:
        rec_id = r.id
        # Skip matched invoices with 0 diff and 0 flags (not an exception)
        is_clean_match = (
            r.category == "matched"
            and not r.rule37_flag
            and not r.rule37a_flag
            and not r.blocked_credit_flag
            and not r.late_filing_flag
            and r.total_tax_diff_paise == 0
        )
        if is_clean_match:
            continue

        # Classify Exception Type
        ex_type = "OTHER"
        if r.category == "missed_itc" or rec_id.startswith("pr:"):
            ex_type = "MISSING_2B"
        elif r.category in ("wrongful_risk", "unmatched_gstr") or rec_id.startswith("gstr:"):
            ex_type = "2B_ONLY"
        elif r.blocked_credit_flag or r.category == "blocked_credit" or "17(5)" in (r.itc_reason or ""):
            ex_type = "SEC_17_5"
        elif r.rule37_flag or r.category == "rule37_warnings":
            ex_type = "RULE_37"
        elif r.rule37a_flag or r.match_status == "RULE37A":
            ex_type = "RULE_37A"
        elif r.category == "gstin_mismatch":
            ex_type = "GSTIN_MISMATCH"
        elif abs(r.total_tax_diff_paise) > 0:
            ex_type = "VALUE_MISMATCH"
        elif r.category == "duplicate_entry" or rec_id.startswith("de:"):
            ex_type = "DUPLICATE"
        elif r.itc_available is False or "16(4)" in (r.itc_reason or ""):
            ex_type = "TIME_BARRED_16_4"

        is_blocking = rec_id in blocking_record_ids

        # Compute ITC Impact
        impact_paise = abs(r.amount or r.total_tax_diff_paise or 0)

        # Compute Operational Priority Score
        priority_score = 0
        if is_blocking:
            priority_score += 1000
        if impact_paise >= 100_000_00:  # >= ₹1,00,000
            priority_score += 300
        elif impact_paise >= 25_000_00:  # >= ₹25,000
            priority_score += 150
        elif impact_paise >= 5_000_00:   # >= ₹5,000
            priority_score += 50

        if ex_type in ("SEC_17_5", "RULE_37", "RULE_37A"):
            priority_score += 200
        elif ex_type == "MISSING_2B":
            priority_score += 100
        elif ex_type == "2B_ONLY":
            priority_score += 75

        # Priority Bucket
        if priority_score >= 500:
            priority = "CRITICAL"
        elif priority_score >= 250:
            priority = "HIGH"
        elif priority_score >= 100:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        # Resolve Existing Disposition
        disp_entry = dispositions.get(f"{rec_id}:{ex_type}") or dispositions.get(rec_id)
        is_resolved = bool(disp_entry)
        disposition_label = str(disp_entry.get("disposition") or "") if disp_entry else None
        disposition_reason = str(disp_entry.get("reason") or "") if disp_entry else None

        # Work Item Status
        if is_resolved:
            status_label = "RESOLVED"
        elif is_blocking:
            status_label = "ACTION_REQUIRED"
        elif ex_type == "MISSING_2B":
            status_label = "AWAITING_VENDOR"
        else:
            status_label = "OPEN"

        # Age Calculation
        age_days = _calculate_age_days(r.invoice_date)

        # WHAT / WHY / NEXT
        what_text = r.decision_what or f"{ex_type.replace('_', ' ')} detected on invoice {r.invoice_number or '—'}"
        why_text = r.decision_why or (
            f"Tax discrepancy of ₹{impact_paise / 100:,.2f} identified between books and GSTR-2B data."
        )
        next_text = r.decision_next or (
            "Review invoice documentation and record CA audit disposition."
        )

        work_items.append({
            "work_item_id": f"wi:{run_id}:{rec_id}:{ex_type}",
            "run_id": run_id,
            "record_id": rec_id,
            "exception_type": ex_type,
            "priority": priority,
            "priority_score": priority_score,
            "supplier_name": r.supplier_name or "—",
            "supplier_gstin": r.supplier_gstin or "—",
            "invoice_number": r.invoice_number or "—",
            "invoice_date": r.invoice_date,
            "itc_impact": paise_to_rupees(impact_paise),
            "itc_impact_paise": impact_paise,
            "age_days": age_days,
            "what": what_text,
            "why": why_text,
            "next_action": next_text,
            "status": status_label,
            "is_blocking": is_blocking,
            "disposition": disposition_label,
            "disposition_reason": disposition_reason,
            "owner": client_data.get("assigned_to"),
        })

    # Sort work items: blockers & high priority first, then descending impact
    work_items.sort(key=lambda x: (x["priority_score"], x["itc_impact_paise"]), reverse=True)

    # 6. Apply Query Filters
    filtered_items = work_items

    if priority_filter:
        p_clean = priority_filter.upper().strip()
        if p_clean == "BLOCKER":
            filtered_items = [item for item in filtered_items if item["is_blocking"]]
        elif p_clean == "RESOLVED":
            filtered_items = [item for item in filtered_items if item["status"] == "RESOLVED"]
        else:
            filtered_items = [item for item in filtered_items if item["priority"] == p_clean]

    if exception_type_filter:
        ex_clean = exception_type_filter.upper().strip()
        filtered_items = [item for item in filtered_items if item["exception_type"] == ex_clean]

    if search:
        s_clean = search.lower().strip()
        filtered_items = [
            item for item in filtered_items
            if s_clean in item["supplier_name"].lower()
            or s_clean in item["supplier_gstin"].lower()
            or s_clean in item["invoice_number"].lower()
            or s_clean in item["what"].lower()
        ]

    # Summary Counts
    total_items = len(work_items)
    critical_count = sum(1 for w in work_items if w["priority"] == "CRITICAL")
    high_count = sum(1 for w in work_items if w["priority"] == "HIGH")
    medium_count = sum(1 for w in work_items if w["priority"] == "MEDIUM")
    low_count = sum(1 for w in work_items if w["priority"] == "LOW")
    resolved_count = sum(1 for w in work_items if w["status"] == "RESOLVED")
    blocking_count = sum(1 for w in work_items if w["is_blocking"])
    total_impact_paise = sum(w["itc_impact_paise"] for w in work_items)

    total_position_paise = max(0, eligible_itc_paise - reversed_itc_paise)

    return {
        "client": {
            "id": str(client_data["id"]),
            "gstin": str(client_data["gstin"]),
            "trade_name": client_data.get("trade_name") or client_data.get("legal_name") or "—",
            "legal_name": client_data.get("legal_name") or "—",
            "pan": client_data.get("pan"),
        },
        "periods": period_options,
        "selected_period": selected_period,
        "run_id": run_id,
        "run_status": run_status,
        "is_locked": is_locked,
        "audit_hash": audit_hash,
        "finalized_at": finalized_at,
        "finalized_by": finalized_by,
        "kpis": {
            "eligible_itc": paise_to_rupees(eligible_itc_paise),
            "on_hold_itc": paise_to_rupees(on_hold_itc_paise),
            "at_risk_itc": paise_to_rupees(at_risk_itc_paise),
            "missed_itc": paise_to_rupees(missed_itc_paise),
            "reversed_itc": paise_to_rupees(reversed_itc_paise),
            "reclaimed_itc": paise_to_rupees(reclaimed_itc_paise),
            "net_itc": paise_to_rupees(net_itc_paise),
            "total_itc_position": paise_to_rupees(total_position_paise),
            "eligible_itc_paise": eligible_itc_paise,
            "on_hold_itc_paise": on_hold_itc_paise,
            "at_risk_itc_paise": at_risk_itc_paise,
            "missed_itc_paise": missed_itc_paise,
            "reversed_itc_paise": reversed_itc_paise,
            "reclaimed_itc_paise": reclaimed_itc_paise,
            "net_itc_paise": net_itc_paise,
        },
        "summary_counts": {
            "total_items": total_items,
            "critical_count": critical_count,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "resolved_count": resolved_count,
            "blocking_count": blocking_count,
            "total_impact_paise": total_impact_paise,
            "total_impact": paise_to_rupees(total_impact_paise),
        },
        "work_items": filtered_items,
    }
