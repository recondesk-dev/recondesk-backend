"""ITC Work Item Service.

Orchestrates the operational lifecycle of GST reconciliation exceptions for CA firms:
- Unique canonical exception identity (run_id, record_id, exception_type)
- Idempotent synchronization from reconciliation outcomes
- Centralized lifecycle state machine and maker-checker validation
- Ownership assignment, priority override tracking, due dates, and SLA status
- Immutable activity timeline and audit events
- Strict finalized-run protection (no mutation of statutory snapshots or outcome decisions)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from supabase import Client

from app.services import reconciliation_outcomes as ro
from app.services.gstr3b_table4_engine import (
    check_finalization_blocking_exceptions,
    load_exception_dispositions,
    paise_to_rupees,
)
from app.services.firm_access import list_accessible_client_gstin_ids

_log = logging.getLogger(__name__)

# Valid Operational Statuses
STATUS_OPEN = "OPEN"
STATUS_TRIAGED = "TRIAGED"
STATUS_ASSIGNED = "ASSIGNED"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_WAITING_VENDOR = "WAITING_VENDOR"
STATUS_READY_FOR_REVIEW = "READY_FOR_REVIEW"
STATUS_RESOLVED = "RESOLVED"
STATUS_DISMISSED = "DISMISSED"
STATUS_NOT_ACTIONABLE = "NOT_ACTIONABLE"
STATUS_CARRIED_FORWARD = "CARRIED_FORWARD"

ALL_STATUSES = {
    STATUS_OPEN,
    STATUS_TRIAGED,
    STATUS_ASSIGNED,
    STATUS_IN_PROGRESS,
    STATUS_WAITING_VENDOR,
    STATUS_READY_FOR_REVIEW,
    STATUS_RESOLVED,
    STATUS_DISMISSED,
    STATUS_NOT_ACTIONABLE,
    STATUS_CARRIED_FORWARD,
}

# Valid Priorities
PRIORITY_CRITICAL = "CRITICAL"
PRIORITY_HIGH = "HIGH"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_LOW = "LOW"
ALL_PRIORITIES = {PRIORITY_CRITICAL, PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW}

# Valid Structured Resolution Codes
RESOLUTION_CODES = {
    "VENDOR_CONTACTED",
    "VENDOR_CORRECTION_EXPECTED",
    "VENDOR_CORRECTION_RECEIVED",
    "PAYMENT_VERIFIED",
    "DOCUMENT_VERIFIED",
    "CLIENT_CONFIRMATION",
    "DUPLICATE_CONFIRMED",
    "STATUTORY_DISPOSITION_APPLIED",
    "NOT_ACTIONABLE",
    "DISMISSED",
    "CARRIED_FORWARD",
}

# Resolution codes that indicate the vendor or books corrected, qualifying for revalidation
REVALIDATION_QUALIFYING_CODES = {
    "VENDOR_CORRECTION_RECEIVED",
    "PAYMENT_VERIFIED",
    "DOCUMENT_VERIFIED",
    "CLIENT_CONFIRMATION",
    "DUPLICATE_CONFIRMED",
    "STATUTORY_DISPOSITION_APPLIED",
}

# Centralized Lifecycle State Transition Matrix
# Mapping of current_status -> set of allowed target_statuses
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATUS_OPEN: {STATUS_TRIAGED, STATUS_ASSIGNED, STATUS_DISMISSED, STATUS_NOT_ACTIONABLE, STATUS_IN_PROGRESS},
    STATUS_TRIAGED: {STATUS_ASSIGNED, STATUS_IN_PROGRESS, STATUS_DISMISSED, STATUS_NOT_ACTIONABLE},
    STATUS_ASSIGNED: {STATUS_IN_PROGRESS, STATUS_WAITING_VENDOR, STATUS_DISMISSED, STATUS_NOT_ACTIONABLE, STATUS_READY_FOR_REVIEW},
    STATUS_IN_PROGRESS: {STATUS_WAITING_VENDOR, STATUS_READY_FOR_REVIEW, STATUS_RESOLVED, STATUS_DISMISSED, STATUS_NOT_ACTIONABLE},
    STATUS_WAITING_VENDOR: {STATUS_IN_PROGRESS, STATUS_READY_FOR_REVIEW, STATUS_DISMISSED},
    STATUS_READY_FOR_REVIEW: {STATUS_RESOLVED, STATUS_IN_PROGRESS, STATUS_DISMISSED},
    STATUS_RESOLVED: {STATUS_IN_PROGRESS}, # Reopen
    STATUS_DISMISSED: {STATUS_OPEN},      # Reopen
    STATUS_NOT_ACTIONABLE: {STATUS_OPEN}, # Reopen
    STATUS_CARRIED_FORWARD: {STATUS_OPEN},# Reopen
}


def can_transition(
    current_status: str,
    target_status: str,
    user_role: str,
    *,
    is_blocking: bool = False,
) -> tuple[bool, Optional[str]]:
    """Validate whether an operational state transition is allowed."""
    c_status = (current_status or "").strip().upper()
    t_status = (target_status or "").strip().upper()
    role = (user_role or "").strip().lower()
    is_admin = role in ("admin", "owner")

    if t_status not in ALL_STATUSES:
        return False, f"Invalid target status: {target_status}"

    if c_status == t_status:
        return True, None

    allowed_targets = ALLOWED_TRANSITIONS.get(c_status, set())
    if t_status not in allowed_targets:
        return False, f"Transition from {c_status} to {t_status} is not permitted."

    # Maker-Checker Role Guardrails
    if t_status == STATUS_RESOLVED and not is_admin and is_blocking:
        return False, "Only an Admin or CA Owner can mark a blocking exception as RESOLVED. Staff must submit to READY_FOR_REVIEW."

    if c_status == STATUS_RESOLVED and t_status == STATUS_IN_PROGRESS and not is_admin:
        return False, "Only an Admin or CA Owner can reopen a RESOLVED work item."

    if c_status == STATUS_DISMISSED and t_status == STATUS_OPEN and not is_admin:
        return False, "Only an Admin or CA Owner can reopen a DISMISSED work item."

    return True, None


def compute_sla_status(due_at: Optional[datetime]) -> str:
    """Compute SLA status from a due date timestamp."""
    if not due_at:
        return "NO_DUE_DATE"
    now = datetime.now(timezone.utc)
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    if now > due_at:
        return "OVERDUE"
    if due_at - now <= timedelta(hours=48):
        return "DUE_SOON"
    return "ON_TRACK"


def _record_event(
    sb: Client,
    work_item_id: str,
    event_type: str,
    *,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    actor_name: Optional[str] = None,
    note: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Append an immutable event into itc_work_item_events."""
    try:
        payload = {
            "work_item_id": work_item_id,
            "event_type": event_type,
            "from_status": from_status,
            "to_status": to_status,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "actor_name": actor_name,
            "note": note,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        sb.table("itc_work_item_events").insert(payload).execute()
    except Exception:
        _log.exception("Failed to record work item event %s on %s", event_type, work_item_id)


def sync_work_items_for_run(
    sb: Client,
    client_id: str,
    run_id: str,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotently sync reconciliation exceptions into itc_work_items without mutating existing operational fields."""
    # 1. Fetch Client Profile & Firm Owner
    client_res = (
        sb.table("client_gstins")
        .select("id, gstin, trade_name, legal_name, firm_owner_id, assigned_to")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    if not client_res.data:
        raise ValueError(f"Client not found: {client_id}")
    client_data = client_res.data[0]
    firm_owner_id = str(client_data.get("firm_owner_id") or user_id or "").strip()
    if not firm_owner_id:
        firm_owner_id = str(user_id or client_id)

    # 2. Fetch Run
    run_res = (
        sb.table("reconciliation_run")
        .select("id, period, status, is_locked")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not run_res.data:
        raise ValueError(f"Run not found: {run_id}")
    run_data = run_res.data[0]

    # 3. Load payload, outcomes, blockers, and dispositions
    p = ro.load_payload(sb, run_id) or {}
    outcome_tuple = ro.build_outcome_rows(sb, run_id, p)
    all_outcomes = outcome_tuple[0]
    dispositions = load_exception_dispositions(sb, run_id)

    gate = check_finalization_blocking_exceptions(sb, run_id, payload=p)
    blocking_record_ids: set[str] = {
        str(b.get("record_id")) for b in gate.get("blocking_records", [])
    }

    # 4. Fetch existing work items for run
    existing_items_res = (
        sb.table("itc_work_items")
        .select("id, record_id, exception_type, status, priority, manual_priority, assigned_to")
        .eq("run_id", run_id)
        .execute()
    )
    existing_map: dict[tuple[str, str], dict[str, Any]] = {
        (r["record_id"], r["exception_type"]): r
        for r in (existing_items_res.data or [])
    }

    created_count = 0
    preserved_count = 0

    now_iso = datetime.now(timezone.utc).isoformat()

    # 5. Formulate work items for exceptions
    for r in all_outcomes:
        rec_id = r.id
        # Skip clean matches with 0 diff
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

        # Priority Evaluation
        tax_paise = abs(r.total_tax_diff_paise) if r.total_tax_diff_paise else int(r.amount * 100 if r.amount else 0)
        sys_priority = PRIORITY_LOW
        if is_blocking or ex_type in ("RULE_37", "SEC_17_5"):
            sys_priority = PRIORITY_CRITICAL
        elif ex_type == "MISSING_2B":
            sys_priority = PRIORITY_HIGH
        elif ex_type in ("2B_ONLY", "VALUE_MISMATCH") or tax_paise >= 5000000:
            sys_priority = PRIORITY_MEDIUM

        # CA Guidance (WHAT / WHY / NEXT)
        what_text = getattr(r, "decision_what", None) or f"Exception '{ex_type}' identified on invoice {r.invoice_number or rec_id}."
        why_text = getattr(r, "decision_why", None) or "Discrepancy impacts statutory ITC eligibility under GST laws."
        next_action_text = getattr(r, "decision_next", None) or "Review invoice with vendor and verify GST status."

        if ex_type == "RULE_37":
            if "Rule 37" not in what_text:
                what_text = f"Rule 37: {what_text}"
            if not getattr(r, "decision_why", None):
                why_text = "Proviso to Section 16(2) and Rule 37 mandate ITC reversal in Table 4(B)(2) with interest."
            if not getattr(r, "decision_next", None):
                next_action_text = "Verify bank payment proof or record 180-day reversal."
        elif ex_type == "SEC_17_5":
            what_text = f"ITC blocked under Section 17(5) ({r.itc_reason or 'Motor vehicle, food, club membership, or personal consumption'})."
            why_text = "Statutorily ineligible credit must be permanently reversed in Table 4(B)(1)."
            next_action_text = "Confirm 17(5) classification and record permanent reversal disposition."
        elif ex_type == "MISSING_2B":
            what_text = f"Invoice {r.invoice_number} is booked in Purchase Register but missing from supplier's GSTR-2B."
            why_text = "Section 16(2)(aa) bars ITC unless the supplier has furnished details in GSTR-1/IFF."
            next_action_text = "Contact vendor to file outward return or hold ITC in GSTR-3B."
        elif ex_type == "2B_ONLY":
            what_text = f"Supplier filed invoice {r.invoice_number} in GSTR-1/2B, but invoice is not recorded in client's Purchase Register."
            why_text = "Potential unbooked expenditure or missed purchase invoice eligible for credit."
            next_action_text = "Check internal accounting entries and book purchase register entry."
        elif ex_type == "VALUE_MISMATCH":
            what_text = f"Tax differential of ₹{paise_to_rupees(tax_paise):,.2f} between books and supplier GSTR-2B."
            why_text = "ITC claimed cannot exceed tax reflected in GSTR-2B per Section 16(2)(aa)."
            next_action_text = "Reconcile taxable value and rate differences with vendor."

        existing = existing_map.get((rec_id, ex_type))
        if existing:
            # Preserve operational state, update context/snapshot fields if needed
            preserved_count += 1
            continue

        # Create New Work Item
        inv_date_val = str(r.invoice_date)[:10] if r.invoice_date else None
        item_row = {
            "firm_owner_id": firm_owner_id,
            "client_gstin_id": client_id,
            "run_id": run_id,
            "record_id": rec_id,
            "exception_type": ex_type,
            "status": STATUS_OPEN,
            "priority": sys_priority,
            "system_priority": sys_priority,
            "category": ex_type,
            "title": f"{ex_type}: {r.invoice_number or rec_id}",
            "what": what_text,
            "why": why_text,
            "next_action": next_action_text,
            "assigned_to": client_data.get("assigned_to"),
            "assigned_at": now_iso if client_data.get("assigned_to") else None,
            "vendor_gstin": r.supplier_gstin,
            "vendor_name": r.supplier_name,
            "invoice_number": r.invoice_number,
            "invoice_date": inv_date_val,
            "taxable_value": float(getattr(r, "taxable_value", 0) or getattr(r, "taxable_value_diff", 0) or 0),
            "igst": float(getattr(r, "igst", 0) or getattr(r, "igst_diff", 0) or 0),
            "cgst": float(getattr(r, "cgst", 0) or getattr(r, "cgst_diff", 0) or 0),
            "sgst": float(getattr(r, "sgst", 0) or getattr(r, "sgst_diff", 0) or 0),
            "cess": float(getattr(r, "cess", 0) or 0),
            "total_tax": float(getattr(r, "total_tax", 0) or getattr(r, "amount", 0) or 0),
            "itc_amount_at_stake": paise_to_rupees(tax_paise),
            "itc_amount_at_stake_paise": tax_paise,
            "is_blocking": is_blocking,
            "created_at": now_iso,
            "created_by": user_id,
            "updated_at": now_iso,
        }

        try:
            ins_res = sb.table("itc_work_items").insert(item_row).execute()
            if ins_res.data:
                wi_id = str(ins_res.data[0]["id"])
                _record_event(
                    sb,
                    wi_id,
                    "WORK_ITEM_CREATED",
                    to_status=STATUS_OPEN,
                    actor_id=user_id,
                    actor_role="system",
                    note=f"Created from reconciliation run {run_id} exception {ex_type}.",
                )
                created_count += 1
        except Exception:
            _log.exception("Insert itc_work_item failed for (%s, %s, %s)", run_id, rec_id, ex_type)

    return {
        "run_id": run_id,
        "client_id": client_id,
        "created_count": created_count,
        "preserved_count": preserved_count,
        "total_work_items": created_count + preserved_count,
    }


def list_work_items(
    sb: Client,
    client_id: str,
    *,
    period: Optional[str] = None,
    run_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    assigned_to_filter: Optional[str] = None,
    sla_filter: Optional[str] = None,
    exception_type_filter: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    current_user: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Retrieve filtered, paginated work items for a client."""
    # Build query
    q = sb.table("itc_work_items").select("*", count="exact").eq("client_gstin_id", client_id)

    if run_id:
        q = q.eq("run_id", run_id)
    if status_filter:
        s_norm = status_filter.strip().upper()
        if s_norm == "BLOCKERS":
            q = q.eq("is_blocking", True)
        elif s_norm != "ALL":
            q = q.eq("status", s_norm)
    if priority_filter and priority_filter.strip().upper() != "ALL":
        q = q.eq("priority", priority_filter.strip().upper())
    if exception_type_filter:
        q = q.eq("exception_type", exception_type_filter.strip())

    # Assigned To Filter
    if assigned_to_filter:
        a_norm = assigned_to_filter.strip()
        if a_norm == "UNASSIGNED":
            q = q.is_("assigned_to", "null")
        elif a_norm == "MY_WORK" and current_user:
            uid = str(current_user.get("id", ""))
            q = q.eq("assigned_to", uid)
        elif a_norm != "ALL":
            q = q.eq("assigned_to", a_norm)

    if search:
        s = search.strip()
        q = q.or_(f"invoice_number.ilike.%{s}%,vendor_name.ilike.%{s}%,vendor_gstin.ilike.%{s}%,record_id.ilike.%{s}%")

    # Order by priority weight & creation
    q = q.order("is_blocking", desc=True).order("created_at", desc=True)

    offset = max(0, (page - 1) * page_size)
    q = q.range(offset, offset + page_size - 1)

    res = q.execute()
    items = res.data or []
    total_count = res.count or len(items)

    # Resolve user profiles for assignees
    assignee_ids = {str(item["assigned_to"]) for item in items if item.get("assigned_to")}
    user_names: dict[str, str] = {}
    if assignee_ids:
        try:
            prof_res = (
                sb.table("user_profiles")
                .select("id, full_name, email")
                .in_("id", list(assignee_ids))
                .execute()
            )
            for p in (prof_res.data or []):
                uid = str(p["id"])
                user_names[uid] = p.get("full_name") or p.get("email") or "Staff"
        except Exception:
            _log.warning("Failed to resolve user names for work items", exc_info=True)

    # Decorate with dynamic SLA and names
    now = datetime.now(timezone.utc)
    for itm in items:
        due_str = itm.get("due_at")
        if due_str:
            try:
                d_val = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                itm["sla_status"] = compute_sla_status(d_val)
            except Exception:
                itm["sla_status"] = "NO_DUE_DATE"
        else:
            itm["sla_status"] = "NO_DUE_DATE"

        aid = str(itm.get("assigned_to") or "")
        itm["assigned_to_name"] = user_names.get(aid)

    # If sla_filter is applied client-side or query-level
    if sla_filter and sla_filter.upper() != "ALL":
        slaf = sla_filter.upper()
        items = [i for i in items if i.get("sla_status") == slaf]

    return {
        "work_items": items,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total_count + page_size - 1) // page_size),
    }


def get_work_item(sb: Client, work_item_id: str, current_user: dict[str, Any]) -> dict[str, Any]:
    """Retrieve full work item details and activity timeline."""
    item_res = (
        sb.table("itc_work_items")
        .select("*")
        .eq("id", work_item_id)
        .limit(1)
        .execute()
    )
    if not item_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
    item = item_res.data[0]

    # Verify accessibility
    cid = str(item["client_gstin_id"])
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for this client")

    # Fetch Timeline Events
    events_res = (
        sb.table("itc_work_item_events")
        .select("*")
        .eq("work_item_id", work_item_id)
        .order("created_at", desc=False)
        .execute()
    )
    events = events_res.data or []

    # Assignee name
    aid = str(item.get("assigned_to") or "")
    if aid:
        try:
            p_res = sb.table("user_profiles").select("full_name, email").eq("id", aid).limit(1).execute()
            if p_res.data:
                item["assigned_to_name"] = p_res.data[0].get("full_name") or p_res.data[0].get("email")
        except Exception:
            pass

    item["events"] = events
    return item


def assign_work_item(
    sb: Client,
    work_item_id: str,
    assigned_to: Optional[str],
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Assign or reassign a work item to a team member."""
    item = get_work_item(sb, work_item_id, current_user)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "CA User"
    user_role = str(current_user.get("role") or "staff").lower()

    old_assigned = item.get("assigned_to")
    old_status = item.get("status")

    updates: dict[str, Any] = {
        "assigned_to": assigned_to,
        "assigned_at": datetime.now(timezone.utc).isoformat() if assigned_to else None,
        "assigned_by": uid,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": uid,
    }

    # Automatically move from OPEN or TRIAGED to ASSIGNED if newly assigned
    target_status = old_status
    if assigned_to and old_status in (STATUS_OPEN, STATUS_TRIAGED):
        target_status = STATUS_ASSIGNED
        updates["status"] = STATUS_ASSIGNED

    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    ev_type = "REASSIGNED" if old_assigned else "ASSIGNED"
    _record_event(
        sb,
        work_item_id,
        ev_type,
        from_status=old_status,
        to_status=target_status,
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=f"Assigned to {assigned_to or 'Unassigned'}.",
    )
    return get_work_item(sb, work_item_id, current_user)


def transition_work_item_status(
    sb: Client,
    work_item_id: str,
    target_status: str,
    current_user: dict[str, Any],
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Transition work item status with centralized validation and audit recording."""
    item = get_work_item(sb, work_item_id, current_user)
    current_status = str(item.get("status") or STATUS_OPEN)
    t_status = target_status.strip().upper()
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    ok, reason = can_transition(
        current_status,
        t_status,
        user_role,
        is_blocking=bool(item.get("is_blocking")),
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)

    updates: dict[str, Any] = {
        "status": t_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": uid,
    }

    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    ev_type = "STATUS_CHANGED"
    if t_status == STATUS_READY_FOR_REVIEW:
        ev_type = "SUBMITTED_FOR_REVIEW"
    elif t_status == STATUS_WAITING_VENDOR:
        ev_type = "WAITING_VENDOR"

    _record_event(
        sb,
        work_item_id,
        ev_type,
        from_status=current_status,
        to_status=t_status,
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=note or f"Status changed from {current_status} to {t_status}.",
    )
    return get_work_item(sb, work_item_id, current_user)


def override_work_item_priority(
    sb: Client,
    work_item_id: str,
    new_priority: str,
    reason: str,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Manually override priority while preserving system_priority."""
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Priority override reason is required.",
        )
    p_norm = new_priority.strip().upper()
    if p_norm not in ALL_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid priority: {new_priority}. Must be one of {ALL_PRIORITIES}.",
        )

    item = get_work_item(sb, work_item_id, current_user)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    now_iso = datetime.now(timezone.utc).isoformat()
    updates = {
        "priority": p_norm,
        "manual_priority": p_norm,
        "priority_override_reason": reason.strip(),
        "priority_changed_by": uid,
        "priority_changed_at": now_iso,
        "updated_at": now_iso,
        "updated_by": uid,
    }

    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    _record_event(
        sb,
        work_item_id,
        "PRIORITY_CHANGED",
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=f"Priority overridden to {p_norm}: {reason.strip()}",
        metadata={"old_priority": item.get("priority"), "new_priority": p_norm, "reason": reason.strip()},
    )
    return get_work_item(sb, work_item_id, current_user)


def set_work_item_due_date(
    sb: Client,
    work_item_id: str,
    due_at: Optional[str],
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Assign or update target due date for an exception work item."""
    item = get_work_item(sb, work_item_id, current_user)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    d_val: Optional[datetime] = None
    if due_at:
        try:
            d_val = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid due date format")

    sla = compute_sla_status(d_val)
    now_iso = datetime.now(timezone.utc).isoformat()

    updates = {
        "due_at": d_val.isoformat() if d_val else None,
        "sla_status": sla,
        "updated_at": now_iso,
        "updated_by": uid,
    }

    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    _record_event(
        sb,
        work_item_id,
        "DUE_DATE_CHANGED",
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=f"Due date set to {due_at or 'None'}.",
        metadata={"due_at": due_at, "sla_status": sla},
    )
    return get_work_item(sb, work_item_id, current_user)


def add_work_item_note(
    sb: Client,
    work_item_id: str,
    note_text: str,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Append a timestamped operational note to the activity timeline."""
    if not note_text or not note_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Note text cannot be empty.",
        )
    item = get_work_item(sb, work_item_id, current_user)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    _record_event(
        sb,
        work_item_id,
        "NOTE_ADDED",
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=note_text.strip(),
    )
    return get_work_item(sb, work_item_id, current_user)


def resolve_work_item(
    sb: Client,
    work_item_id: str,
    resolution_code: str,
    resolution_note: str,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Record structured operational resolution with maker-checker guardrails."""
    if not resolution_code or resolution_code.strip() not in RESOLUTION_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid resolution code. Must be one of {RESOLUTION_CODES}",
        )
    if not resolution_note or not resolution_note.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Resolution note is required explaining how the exception was resolved.",
        )

    item = get_work_item(sb, work_item_id, current_user)
    current_status = str(item.get("status") or STATUS_OPEN)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()
    is_admin = user_role in ("admin", "owner")
    is_blocking = bool(item.get("is_blocking"))

    # Maker-Checker: If staff and item is blocking, staff cannot resolve directly
    if not is_admin and is_blocking:
        # Move to READY_FOR_REVIEW
        updates = {
            "status": STATUS_READY_FOR_REVIEW,
            "resolution_code": resolution_code.strip(),
            "resolution_note": resolution_note.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": uid,
        }
        sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()
        _record_event(
            sb,
            work_item_id,
            "RESOLUTION_PROPOSED",
            from_status=current_status,
            to_status=STATUS_READY_FOR_REVIEW,
            actor_id=uid,
            actor_role=user_role,
            actor_name=user_name,
            note=f"Resolution proposed ({resolution_code}): {resolution_note.strip()}",
            metadata={"resolution_code": resolution_code, "proposed_by": uid},
        )
        return get_work_item(sb, work_item_id, current_user)

    # Admin/Owner or non-blocking staff: complete resolution
    now_iso = datetime.now(timezone.utc).isoformat()
    reval_status = "PENDING" if resolution_code in REVALIDATION_QUALIFYING_CODES else "NONE"

    updates = {
        "status": STATUS_RESOLVED,
        "resolution_code": resolution_code.strip(),
        "resolution_note": resolution_note.strip(),
        "resolved_at": now_iso,
        "resolved_by": uid,
        "revalidation_status": reval_status,
        "revalidation_requested_at": now_iso if reval_status == "PENDING" else None,
        "updated_at": now_iso,
        "updated_by": uid,
    }
    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    _record_event(
        sb,
        work_item_id,
        "RESOLUTION_APPROVED",
        from_status=current_status,
        to_status=STATUS_RESOLVED,
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=f"Exception marked RESOLVED ({resolution_code}): {resolution_note.strip()}",
        metadata={"resolution_code": resolution_code, "revalidation_status": reval_status},
    )
    return get_work_item(sb, work_item_id, current_user)


def dismiss_work_item(
    sb: Client,
    work_item_id: str,
    reason: str,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Dismiss a work item with mandatory justification."""
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dismissal reason is required.",
        )
    item = get_work_item(sb, work_item_id, current_user)
    current_status = str(item.get("status") or STATUS_OPEN)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    now_iso = datetime.now(timezone.utc).isoformat()
    updates = {
        "status": STATUS_DISMISSED,
        "dismissal_reason": reason.strip(),
        "dismissed_at": now_iso,
        "dismissed_by": uid,
        "updated_at": now_iso,
        "updated_by": uid,
    }
    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    _record_event(
        sb,
        work_item_id,
        "DISMISSED",
        from_status=current_status,
        to_status=STATUS_DISMISSED,
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=f"Item dismissed: {reason.strip()}",
        metadata={"reason": reason.strip()},
    )
    return get_work_item(sb, work_item_id, current_user)


def reopen_work_item(
    sb: Client,
    work_item_id: str,
    reason: str,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Reopen a DISMISSED or RESOLVED work item with mandatory reason."""
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reopen reason is required.",
        )
    item = get_work_item(sb, work_item_id, current_user)
    current_status = str(item.get("status") or STATUS_OPEN)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    if user_role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an Admin or CA Owner can reopen an exception work item.",
        )

    target_status = STATUS_OPEN if current_status == STATUS_DISMISSED else STATUS_IN_PROGRESS
    now_iso = datetime.now(timezone.utc).isoformat()

    updates = {
        "status": target_status,
        "reopen_reason": reason.strip(),
        "reopened_at": now_iso,
        "reopened_by": uid,
        "updated_at": now_iso,
        "updated_by": uid,
    }
    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    _record_event(
        sb,
        work_item_id,
        "REOPENED",
        from_status=current_status,
        to_status=target_status,
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=f"Item reopened to {target_status}: {reason.strip()}",
        metadata={"reopen_reason": reason.strip()},
    )
    return get_work_item(sb, work_item_id, current_user)


def request_work_item_revalidation(
    sb: Client,
    work_item_id: str,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Register revalidation request hook for Phase 5.5 without altering reconciliation engines."""
    item = get_work_item(sb, work_item_id, current_user)
    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    now_iso = datetime.now(timezone.utc).isoformat()
    updates = {
        "revalidation_status": "PENDING",
        "revalidation_requested_at": now_iso,
        "updated_at": now_iso,
        "updated_by": uid,
    }
    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()

    _record_event(
        sb,
        work_item_id,
        "REVALIDATION_REQUESTED",
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note="Revalidation requested for next reconciliation cycle.",
    )
    return get_work_item(sb, work_item_id, current_user)


def execute_bulk_action(
    sb: Client,
    action_type: str,
    work_item_ids: list[str],
    payload: dict[str, Any],
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Execute bulk operation across work items with per-item authorization and audit tracking."""
    act = action_type.strip().lower()
    successes: list[str] = []
    failures: list[dict[str, Any]] = []

    for wid in work_item_ids:
        try:
            if act == "assign":
                assign_work_item(sb, wid, payload.get("assigned_to"), current_user)
            elif act == "status":
                transition_work_item_status(sb, wid, payload.get("status"), current_user, note=payload.get("note"))
            elif act == "priority":
                override_work_item_priority(sb, wid, payload.get("priority"), payload.get("reason", "Bulk update"), current_user)
            elif act == "due_date":
                set_work_item_due_date(sb, wid, payload.get("due_at"), current_user)
            else:
                failures.append({"id": wid, "error": f"Unknown bulk action: {act}"})
                continue
            successes.append(wid)
        except HTTPException as he:
            failures.append({"id": wid, "error": he.detail})
        except Exception as exc:
            failures.append({"id": wid, "error": str(exc)})

    return {
        "action": act,
        "total": len(work_item_ids),
        "success_count": len(successes),
        "failure_count": len(failures),
        "successes": successes,
        "failures": failures,
    }


# Convenient Aliases
transition_status = transition_work_item_status
override_priority = override_work_item_priority
set_due_date = set_work_item_due_date
add_note = add_work_item_note
reopen_item = reopen_work_item
dismiss_item = dismiss_work_item
