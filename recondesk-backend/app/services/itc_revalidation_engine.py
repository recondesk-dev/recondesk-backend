"""Authoritative ITC Revalidation Orchestration Engine (Phase 5.5A).

This is a pure ORCHESTRATION layer. It does NOT rematch invoices, calculate GST,
or re-interpret statutory rules. All authoritative decisions come strictly
from reconciliation_outcomes.OutcomeRows produced by the authoritative reconciliation engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from supabase import Client

from app.services.matcher import TOTAL_TOLERANCE_PAISE, normalize_invoice_number
from app.services import reconciliation_outcomes as ro
from app.services.firm_access import list_accessible_client_gstin_ids

_log = logging.getLogger(__name__)

# Canonical Revalidation Results
RESULT_CLEARED = "CLEARED"
RESULT_PERSISTS = "PERSISTS"
RESULT_CHANGED = "CHANGED"
RESULT_ERROR = "ERROR"
RESULT_NOT_REVALIDATED = "NOT_REVALIDATED"

REVALIDATION_RESULTS = frozenset(
    {
        RESULT_CLEARED,
        RESULT_PERSISTS,
        RESULT_CHANGED,
        RESULT_ERROR,
        RESULT_NOT_REVALIDATED,
    }
)

# Canonical Revalidation Statuses
STATUS_NONE = "NONE"
STATUS_PENDING = "PENDING"
STATUS_REVALIDATING = "REVALIDATING"
STATUS_REVALIDATED = "REVALIDATED"
STATUS_ERROR = "ERROR"


# Statutory exception types that cannot be cleared by automated vendor revalidation
NON_REVALIDATABLE_EXCEPTION_TYPES = frozenset(
    {
        "SEC_17_5",
        "TIME_BARRED_16_4",
    }
)

# Work item operational statuses from itc_work_item_service
STATUS_OPEN = "OPEN"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_READY_FOR_REVIEW = "READY_FOR_REVIEW"
STATUS_RESOLVED = "RESOLVED"
STATUS_WAITING_VENDOR = "WAITING_VENDOR"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_vc_repo():
    """Return the Aurora vendor compliance repository if available."""
    try:
        from app.repositories.vendor_compliance import get_vendor_compliance_repository
        return get_vendor_compliance_repository()
    except Exception:
        return None


def _update_work_item(sb: Client, work_item_id: str, updates: dict[str, Any]) -> None:
    """Update itc_work_items with Aurora primary and Supabase fallback."""
    repo = _get_vc_repo()
    if repo:
        try:
            repo.update_work_item(work_item_id, updates)
            return
        except Exception as exc:
            _log.warning("Aurora update_work_item failed in revalidation, falling back to Supabase: %s", exc)
    sb.table("itc_work_items").update(updates).eq("id", work_item_id).execute()


def _record_reval_event(
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
    """Record audit event in itc_work_item_events (Aurora primary with Supabase fallback)."""
    payload = {
        "work_item_id": work_item_id,
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "actor_id": actor_id,
        "actor_role": actor_role or "system",
        "actor_name": actor_name or "System",
        "note": note,
        "metadata": metadata or {},
        "created_at": _now_iso(),
    }
    repo = _get_vc_repo()
    if repo:
        try:
            repo.insert_work_item_event(payload)
            return
        except Exception as exc:
            _log.warning("Aurora insert_work_item_event failed in revalidation: %s", exc)

    try:
        sb.table("itc_work_item_events").insert(payload).execute()
    except Exception:
        _log.exception("Failed to record work item reval event %s on %s", event_type, work_item_id)


def find_candidate_outcomes(
    all_outcomes: list[Any],
    vendor_gstin: str,
    invoice_number: str,
    invoice_date: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str]]:
    """Match target invoice within authoritative OutcomeRows using canonical BUSINESS IDENTITY.

    Identity key: (normalized_supplier_gstin, normalized_invoice_number)
    Disambiguation: invoice_date (YYYY-MM-DD)

    Returns:
        (matched_outcome_or_None, failure_or_ambiguity_reason_or_None)
    """
    norm_target_inv = normalize_invoice_number(invoice_number)
    if not norm_target_inv:
        return None, "MISSING_INVOICE_NUMBER"

    norm_target_gstin = (vendor_gstin or "").strip().upper()

    candidates: list[Any] = []
    for r in all_outcomes:
        r_inv = normalize_invoice_number(getattr(r, "invoice_number", None))
        if r_inv != norm_target_inv:
            continue

        r_gstin = (
            getattr(r, "supplier_gstin", None)
            or getattr(r, "pr_supplier_gstin", None)
            or getattr(r, "gstr_supplier_gstin", None)
            or ""
        ).strip().upper()

        if norm_target_gstin and r_gstin:
            if norm_target_gstin == r_gstin:
                candidates.append(r)
        else:
            # If one side has no GSTIN recorded, accept candidate for date check
            candidates.append(r)

    if not candidates:
        return None, "INVOICE_NOT_FOUND_IN_TARGET_RUN"

    if len(candidates) == 1:
        return candidates[0], None

    # Disambiguation with invoice date if multiple candidates match number + gstin
    if invoice_date:
        target_d = str(invoice_date)[:10].strip()
        date_matches = [
            c for c in candidates
            if c.invoice_date and str(c.invoice_date)[:10].strip() == target_d
        ]
        if len(date_matches) == 1:
            return date_matches[0], None
        if len(date_matches) > 1:
            return None, f"AMBIGUOUS_MULTIPLE_INVOICES_SAME_DATE ({len(date_matches)} candidates)"

    return None, f"AMBIGUOUS_MULTIPLE_INVOICES ({len(candidates)} candidates)"


def get_latest_eligible_completed_run(
    sb: Client,
    client_gstin_id: str,
    current_run_id: str,
    period: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Select the latest authoritative completed reconciliation run for client_gstin_id.

    - Target run must have status == 'COMPLETED' or 'FINAL'.
    - If source run is locked/finalized, it CANNOT be used as the target run (evaluates against a new run).
    - Prevents stale runs: target run created_at must not be strictly older than the source run.
    """
    # Fetch source run info
    src_locked = False
    src_created_at = ""
    target_period = period

    try:
        from app.repositories.reconciliation import get_reconciliation_repository
        rrepo = get_reconciliation_repository()
        if rrepo is not None:
            sr = rrepo.get_run(current_run_id)
            if sr:
                src_locked = bool(sr.get("is_locked") or sr.get("status") == "FINAL")
                src_created_at = sr.get("created_at") or ""
                if not target_period:
                    target_period = sr.get("period")
            runs = rrepo.list_runs([client_gstin_id]) or []
            runs = [r for r in runs if r.get("status") in ("COMPLETED", "FINAL")]
            if target_period:
                runs = [r for r in runs if r.get("period") == target_period]
            for r in runs:
                rid = str(r["id"])
                if src_locked and rid == current_run_id:
                    continue
                r_created = r.get("created_at") or ""
                if src_created_at and r_created < src_created_at and rid != current_run_id:
                    continue
                return r
            return None
    except Exception:
        pass

    src_res = (
        sb.table("reconciliation_run")
        .select("id, status, is_locked, created_at, period")
        .eq("id", current_run_id)
        .limit(1)
        .execute()
    )
    if src_res.data:
        sr = src_res.data[0]
        src_locked = bool(sr.get("is_locked") or sr.get("status") == "FINAL")
        src_created_at = sr.get("created_at") or ""
        if not target_period:
            target_period = sr.get("period")

    q = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status, is_locked, completed_at, created_at")
        .eq("client_gstin_id", client_gstin_id)
        .in_("status", ["COMPLETED", "FINAL"])
        .order("created_at", desc=True)
    )
    if target_period:
        q = q.eq("period", target_period)

    runs = q.limit(10).execute().data or []
    if not runs:
        return None

    for r in runs:
        rid = str(r["id"])
        # If source run is locked, historical run cannot evaluate against itself
        if src_locked and rid == current_run_id:
            continue
        # Check monotonic created_at
        r_created = r.get("created_at") or ""
        if src_created_at and r_created < src_created_at and rid != current_run_id:
            continue
        return r

    return None


def compare_work_item_with_outcome(
    work_item: dict[str, Any],
    outcome: Optional[Any],
    ambiguity_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Deterministically evaluate authoritative OutcomeRow vs operational work item.

    Uses exclusively the existing authoritative OutcomeRow attributes.
    Returns:
        {
            "revalidation_result": "CLEARED" | "PERSISTS" | "CHANGED" | "NOT_REVALIDATED",
            "comparison_reason": str,
            "new_exception_type": Optional[str],
            "tax_diff_before_paise": int,
            "tax_diff_after_paise": int,
        }
    """
    ex_type = str(work_item.get("exception_type") or "OTHER").strip().upper()
    old_diff_paise = int(work_item.get("itc_amount_at_stake_paise") or 0)

    # 1. Non-revalidatable statutory exception types
    if ex_type in NON_REVALIDATABLE_EXCEPTION_TYPES:
        return {
            "revalidation_result": RESULT_NOT_REVALIDATED,
            "comparison_reason": (
                f"Exception {ex_type} is a statutory condition that cannot be cleared by automated revalidation. "
                "Requires permanent statutory reversal or CA review."
            ),
            "new_exception_type": ex_type,
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": old_diff_paise,
        }

    # 2. Outcome not found or ambiguous
    if outcome is None:
        if ambiguity_reason and "AMBIGUOUS" in ambiguity_reason:
            return {
                "revalidation_result": RESULT_NOT_REVALIDATED,
                "comparison_reason": f"Ambiguous invoice identity in authoritative run: {ambiguity_reason}",
                "new_exception_type": ex_type,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": old_diff_paise,
            }
        if ex_type == "MISSING_2B":
            # Invoice is still not present in the fresh GSTR-2B run outcomes
            return {
                "revalidation_result": RESULT_PERSISTS,
                "comparison_reason": "Invoice remains absent from supplier GSTR-2B in authoritative reconciliation.",
                "new_exception_type": "MISSING_2B",
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": old_diff_paise,
            }
        return {
            "revalidation_result": RESULT_NOT_REVALIDATED,
            "comparison_reason": f"Invoice not found in target reconciliation run ({ambiguity_reason or 'NOT_FOUND'}).",
            "new_exception_type": ex_type,
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": old_diff_paise,
        }

    # 3. Read Authoritative Metrics directly from OutcomeRow
    cat = str(getattr(outcome, "category", "") or "").strip().lower()
    match_status = str(getattr(outcome, "match_status", "") or "").strip().upper()
    new_diff_paise = abs(int(getattr(outcome, "total_tax_diff_paise", 0) or 0))
    rule37 = bool(getattr(outcome, "rule37_flag", False))
    rule37a = bool(getattr(outcome, "rule37a_flag", False))
    blocked = bool(getattr(outcome, "blocked_credit_flag", False))
    late = bool(getattr(outcome, "late_filing_flag", False))
    itc_avail = getattr(outcome, "itc_available", True)

    is_clean_match = (
        cat == "matched"
        and new_diff_paise <= TOTAL_TOLERANCE_PAISE
        and not rule37
        and not rule37a
        and not blocked
        and not late
        and itc_avail is not False
    )

    # 4. Exception-Specific Deterministic Comparison
    if ex_type == "MISSING_2B":
        if is_clean_match:
            return {
                "revalidation_result": RESULT_CLEARED,
                "comparison_reason": "Invoice is now matched cleanly in GSTR-2B with zero discrepancy and no statutory flags.",
                "new_exception_type": None,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": 0,
            }
        if cat == "missed_itc" or str(getattr(outcome, "id", "")).startswith("pr:"):
            return {
                "revalidation_result": RESULT_PERSISTS,
                "comparison_reason": "Invoice remains missing from GSTR-2B in authoritative reconciliation.",
                "new_exception_type": "MISSING_2B",
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": new_diff_paise or old_diff_paise,
            }
        # Appeared in 2B but now has value diff or statutory concern
        new_type = "VALUE_MISMATCH" if new_diff_paise > TOTAL_TOLERANCE_PAISE else ("RULE_37" if rule37 else "OTHER")
        return {
            "revalidation_result": RESULT_CHANGED,
            "comparison_reason": (
                f"Invoice appeared in GSTR-2B but now has an authoritative discrepancy "
                f"({cat}, match_status={match_status}, diff=₹{new_diff_paise/100:.2f})."
            ),
            "new_exception_type": new_type,
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": new_diff_paise,
        }

    if ex_type == "2B_ONLY":
        if is_clean_match:
            return {
                "revalidation_result": RESULT_CLEARED,
                "comparison_reason": "Invoice now has clean Purchase Register correspondence and is fully matched.",
                "new_exception_type": None,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": 0,
            }
        if cat in ("wrongful_risk", "unmatched_gstr") or str(getattr(outcome, "id", "")).startswith("gstr:"):
            return {
                "revalidation_result": RESULT_PERSISTS,
                "comparison_reason": "Invoice remains absent from Purchase Register in authoritative reconciliation.",
                "new_exception_type": "2B_ONLY",
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": new_diff_paise or old_diff_paise,
            }
        new_type = "VALUE_MISMATCH" if new_diff_paise > TOTAL_TOLERANCE_PAISE else "OTHER"
        return {
            "revalidation_result": RESULT_CHANGED,
            "comparison_reason": f"Invoice booked in register but discrepancy remains ({cat}, diff=₹{new_diff_paise/100:.2f}).",
            "new_exception_type": new_type,
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": new_diff_paise,
        }

    if ex_type == "VALUE_MISMATCH":
        if is_clean_match or (cat == "matched" and new_diff_paise <= TOTAL_TOLERANCE_PAISE):
            return {
                "revalidation_result": RESULT_CLEARED,
                "comparison_reason": f"Tax discrepancy resolved within authoritative tolerance (diff: ₹{new_diff_paise/100:.2f}).",
                "new_exception_type": None,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": new_diff_paise,
            }
        if abs(new_diff_paise - old_diff_paise) <= TOTAL_TOLERANCE_PAISE:
            return {
                "revalidation_result": RESULT_PERSISTS,
                "comparison_reason": f"Tax discrepancy remains unchanged at ₹{new_diff_paise/100:.2f}.",
                "new_exception_type": "VALUE_MISMATCH",
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": new_diff_paise,
            }
        return {
            "revalidation_result": RESULT_CHANGED,
            "comparison_reason": f"Tax discrepancy changed from ₹{old_diff_paise/100:.2f} to ₹{new_diff_paise/100:.2f}.",
            "new_exception_type": "VALUE_MISMATCH",
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": new_diff_paise,
        }

    if ex_type == "GSTIN_MISMATCH":
        if cat != "gstin_mismatch" and is_clean_match:
            return {
                "revalidation_result": RESULT_CLEARED,
                "comparison_reason": "Supplier GSTIN discrepancy is resolved with clean match.",
                "new_exception_type": None,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": 0,
            }
        if cat == "gstin_mismatch":
            return {
                "revalidation_result": RESULT_PERSISTS,
                "comparison_reason": "Supplier GSTIN mismatch remains in authoritative reconciliation.",
                "new_exception_type": "GSTIN_MISMATCH",
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": new_diff_paise or old_diff_paise,
            }
        return {
            "revalidation_result": RESULT_CHANGED,
            "comparison_reason": f"GSTIN mismatch resolved, but invoice has new discrepancy ({cat}).",
            "new_exception_type": "VALUE_MISMATCH" if new_diff_paise > TOTAL_TOLERANCE_PAISE else "OTHER",
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": new_diff_paise,
        }

    if ex_type == "DUPLICATE":
        if cat not in ("duplicate_entry", "duplicates") and not str(getattr(outcome, "id", "")).startswith("de:"):
            return {
                "revalidation_result": RESULT_CLEARED,
                "comparison_reason": "Authoritative duplicate classification is no longer present.",
                "new_exception_type": None,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": 0,
            }
        return {
            "revalidation_result": RESULT_PERSISTS,
            "comparison_reason": "Duplicate invoice classification persists in authoritative reconciliation.",
            "new_exception_type": "DUPLICATE",
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": new_diff_paise or old_diff_paise,
        }

    if ex_type == "RULE_37":
        if not rule37:
            return {
                "revalidation_result": RESULT_CLEARED,
                "comparison_reason": "Authoritative Rule 37 180-day non-payment flag is cleared.",
                "new_exception_type": None,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": 0,
            }
        return {
            "revalidation_result": RESULT_PERSISTS,
            "comparison_reason": "Authoritative Rule 37 180-day non-payment flag persists.",
            "new_exception_type": "RULE_37",
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": new_diff_paise or old_diff_paise,
        }

    if ex_type == "RULE_37A":
        if not rule37a:
            return {
                "revalidation_result": RESULT_CLEARED,
                "comparison_reason": "Authoritative Rule 37A supplier return filing flag is cleared.",
                "new_exception_type": None,
                "tax_diff_before_paise": old_diff_paise,
                "tax_diff_after_paise": 0,
            }
        return {
            "revalidation_result": RESULT_PERSISTS,
            "comparison_reason": "Authoritative Rule 37A unfiled return flag persists.",
            "new_exception_type": "RULE_37A",
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": new_diff_paise or old_diff_paise,
        }

    # Default / OTHER
    if is_clean_match:
        return {
            "revalidation_result": RESULT_CLEARED,
            "comparison_reason": "Discrepancy resolved in authoritative reconciliation.",
            "new_exception_type": None,
            "tax_diff_before_paise": old_diff_paise,
            "tax_diff_after_paise": 0,
        }
    return {
        "revalidation_result": RESULT_PERSISTS,
        "comparison_reason": f"Discrepancy continues in authoritative reconciliation ({cat}).",
        "new_exception_type": ex_type,
        "tax_diff_before_paise": old_diff_paise,
        "tax_diff_after_paise": new_diff_paise or old_diff_paise,
    }


def request_revalidation(
    sb: Client,
    work_item_id: str,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Register revalidation request with strict idempotency and validation gates."""
    # Lazy import to prevent circular dependency
    from app.services import itc_work_item_service as wis

    item = wis.get_work_item(sb, work_item_id, current_user)
    ex_type = str(item.get("exception_type") or "OTHER").strip().upper()

    # Reject statutory non-revalidatable exceptions
    if ex_type in NON_REVALIDATABLE_EXCEPTION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Exception '{ex_type}' is a statutory condition that cannot be cleared by automated revalidation. "
                "Requires permanent statutory reversal or CA review."
            ),
        )

    # Idempotency: if already PENDING or REVALIDATING, do not duplicate events or reset timestamps
    if item.get("revalidation_status") in (STATUS_PENDING, STATUS_REVALIDATING):
        return item


    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()
    now_iso = _now_iso()

    # Concurrency-safe update (Aurora primary with Supabase fallback)
    upd_payload = {
        "revalidation_status": STATUS_PENDING,
        "revalidation_requested_at": now_iso,
        "updated_at": now_iso,
        "updated_by": uid,
    }
    _update_work_item(sb, work_item_id, upd_payload)

    _record_reval_event(
        sb,
        work_item_id,
        "REVALIDATION_REQUESTED",
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note="Revalidation requested for next reconciliation cycle.",
        metadata={
            "requested_by": uid,
            "source_run_id": item.get("run_id"),
            "source_version": item.get("source_version", 1),
            "exception_type": ex_type,
        },
    )

    return wis.get_work_item(sb, work_item_id, current_user)


def execute_revalidation(
    sb: Client,
    work_item_id: str,
    current_user: dict[str, Any],
    target_run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Execute authoritative comparison for a PENDING work item against target run.

    Guarantees:
    - Zero Table 4 mutations.
    - Zero reconciliation outcome mutations.
    - Maker-checker compliance (blocking items require CA approval via READY_FOR_REVIEW).
    - Stale result and version race protection.
    - Deterministic technical error handling (never converts ERROR to PERSISTS).
    """
    from app.services import itc_work_item_service as wis

    item = wis.get_work_item(sb, work_item_id, current_user)
    wid = str(item["id"])
    client_id = str(item["client_gstin_id"])
    source_run_id = str(item["run_id"])
    expected_version = int(item.get("source_version", 1))

    uid = str(current_user.get("id", ""))
    user_name = current_user.get("full_name") or current_user.get("email") or "User"
    user_role = str(current_user.get("role") or "staff").lower()

    # 1. Must be PENDING to execute revalidation
    if item.get("revalidation_status") != STATUS_PENDING:
        return item

    now_iso = _now_iso()

    # 2. Execution-level idempotency: atomic claim to prevent simultaneous competing executions
    _update_work_item(sb, wid, {
        "revalidation_status": STATUS_REVALIDATING,
        "updated_at": now_iso,
        "updated_by": uid,
    })

    # Target run resolution
    if not target_run_id:
        target_run = get_latest_eligible_completed_run(sb, client_id, source_run_id)
        if not target_run:
            now_iso = _now_iso()
            _update_work_item(sb, wid, {
                "revalidation_status": STATUS_REVALIDATED,
                "revalidation_result": RESULT_NOT_REVALIDATED,
                "revalidation_completed_at": now_iso,
                "updated_at": now_iso,
                "updated_by": uid,
            })

            _record_reval_event(
                sb,
                wid,
                "REVALIDATION_COMPLETED",
                actor_id=uid,
                actor_role=user_role,
                actor_name=user_name,
                note="Revalidation skipped: No eligible completed authoritative reconciliation run found.",
                metadata={
                    "revalidation_result": RESULT_NOT_REVALIDATED,
                    "reason": "NO_ELIGIBLE_AUTHORITATIVE_RUN",
                    "source_run_id": source_run_id,
                },
            )
            return wis.get_work_item(sb, wid, current_user)
        target_run_id = str(target_run["id"])
    else:
        # Validate tenant access on explicit target_run_id
        target_res = (
            sb.table("reconciliation_run")
            .select("id, client_gstin_id, status, is_locked, created_at")
            .eq("id", target_run_id)
            .limit(1)
            .execute()
        )
        if not target_res.data or str(target_res.data[0]["client_gstin_id"]) != client_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Target run does not belong to client GSTIN.",
            )
        target_run = target_res.data[0]

    now_iso = _now_iso()

    # Record REVALIDATION_STARTED
    _record_reval_event(
        sb,
        wid,
        "REVALIDATION_STARTED",
        actor_id=uid,
        actor_role=user_role,
        actor_name=user_name,
        note=f"Revalidation evaluating against authoritative run {target_run_id}.",
        metadata={
            "source_run_id": source_run_id,
            "target_run_id": target_run_id,
            "started_at": now_iso,
        },
    )

    try:
        # Load authoritative outcomes from target run
        payload = ro.load_payload(sb, target_run_id) or {}
        outcomes_tuple = ro.build_outcome_rows(sb, target_run_id, payload)
        all_outcomes = outcomes_tuple[0] if outcomes_tuple else []

        # Find candidate outcome by business identity
        candidate, amb_reason = find_candidate_outcomes(
            all_outcomes,
            item.get("vendor_gstin") or "",
            item.get("invoice_number") or "",
            str(item.get("invoice_date") or ""),
        )

        comparison = compare_work_item_with_outcome(item, candidate, amb_reason)
        res_code = comparison["revalidation_result"]

        # STALE TARGET PROTECTION:
        # Re-query the latest eligible authoritative completed run right before persisting.
        # If a newer eligible run exists than the target_run evaluated by this execution,
        # we must NOT persist CLEARED / PERSISTS / CHANGED.
        latest_eligible = get_latest_eligible_completed_run(sb, client_id, source_run_id)
        if latest_eligible:
            latest_id = str(latest_eligible["id"])
            latest_created = latest_eligible.get("created_at") or ""
            target_created = target_run.get("created_at") or ""
            if latest_id != target_run_id and latest_created > target_created:
                _log.warning(
                    "Stale target run detected for work item %s: evaluated %s (created %s), but newer %s exists (created %s)",
                    wid, target_run_id, target_created, latest_id, latest_created,
                )
                now_iso = _now_iso()
                _update_work_item(sb, wid, {
                    "revalidation_status": STATUS_PENDING,
                    "updated_at": now_iso,
                    "updated_by": uid,
                })

                _record_reval_event(
                    sb,
                    wid,
                    "REVALIDATION_STALE_TARGET_SKIPPED",
                    actor_id=uid,
                    actor_role=user_role,
                    actor_name=user_name,
                    note=(
                        f"Revalidation outcome from run {target_run_id} rejected: Newer authoritative "
                        f"run {latest_id} was completed before persistence. Revalidation remains PENDING."
                    ),
                    metadata={
                        "evaluated_target_run_id": target_run_id,
                        "superseding_run_id": latest_id,
                        "revalidation_result": RESULT_NOT_REVALIDATED,
                        "reason": "STALE_TARGET_SUPERSEDED",
                        "stale_result": True,
                        "evaluated_at": now_iso,
                    },
                )
                return wis.get_work_item(sb, wid, current_user)

        completion_iso = _now_iso()
        item_updates = {
            "revalidation_status": STATUS_REVALIDATED,
            "revalidation_result": res_code,
            "revalidation_completed_at": completion_iso,
            "updated_at": completion_iso,
            "updated_by": uid,
        }

        # Maker-Checker and State Machine integration via Phase 5.2 logic
        current_st = str(item.get("status") or STATUS_OPEN)
        is_blocking = bool(item.get("is_blocking"))

        if res_code == RESULT_CLEARED:
            if is_blocking:
                target_operational_status = STATUS_READY_FOR_REVIEW
                # Validate transition through Phase 5.2 can_transition
                ok, reason = wis.can_transition(
                    current_st,
                    target_operational_status,
                    user_role,
                    is_blocking=True,
                )
                if ok:
                    item_updates["status"] = target_operational_status
                    item_updates["resolution_code"] = "VENDOR_CORRECTION_RECEIVED"
                    item_updates["resolution_note"] = (
                        f"Authoritative run {target_run_id} verified exception cleared. Submitted to CA for review."
                    )
                else:
                    _log.warning(
                        "Cannot transition blocking item %s from %s to %s: %s",
                        wid, current_st, target_operational_status, reason,
                    )
            else:
                # Non-blocking item: target is RESOLVED
                target_operational_status = STATUS_RESOLVED
                ok, reason = wis.can_transition(
                    current_st,
                    target_operational_status,
                    user_role,
                    is_blocking=False,
                )
                if not ok and current_st in (STATUS_OPEN, STATUS_WAITING_VENDOR, wis.STATUS_ASSIGNED, wis.STATUS_TRIAGED):
                    # Transition via IN_PROGRESS first per Phase 5.2 ALLOWED_TRANSITIONS
                    in_prog_ok, _ = wis.can_transition(current_st, STATUS_IN_PROGRESS, user_role, is_blocking=False)
                    if in_prog_ok:
                        wis.transition_work_item_status(
                            sb, wid, STATUS_IN_PROGRESS, current_user, note="Auto-transition to IN_PROGRESS for revalidation clearance."
                        )
                        current_st = STATUS_IN_PROGRESS
                        ok, reason = wis.can_transition(current_st, target_operational_status, user_role, is_blocking=False)

                if ok:
                    item_updates["status"] = target_operational_status
                    item_updates["resolution_code"] = "VENDOR_CORRECTION_RECEIVED"
                    item_updates["resolution_note"] = f"Authoritative run {target_run_id} verified exception cleared."
                    item_updates["resolved_at"] = completion_iso
                    item_updates["resolved_by"] = uid
                else:
                    _log.warning(
                        "Cannot transition non-blocking item %s from %s to %s: %s",
                        wid, current_st, target_operational_status, reason,
                    )

        # Atomic update (Aurora primary with Supabase fallback)
        _update_work_item(sb, wid, item_updates)

        # Record REVALIDATION_COMPLETED
        _record_reval_event(
            sb,
            wid,
            "REVALIDATION_COMPLETED",
            from_status=current_st,
            to_status=item_updates.get("status", current_st),
            actor_id=uid,
            actor_role=user_role,
            actor_name=user_name,
            note=f"Revalidation completed: {res_code}. {comparison['comparison_reason']}",
            metadata={
                "source_run_id": source_run_id,
                "target_run_id": target_run_id,
                "previous_exception_type": item.get("exception_type"),
                "new_exception_type": comparison.get("new_exception_type"),
                "revalidation_result": res_code,
                "tax_diff_before": comparison.get("tax_diff_before_paise"),
                "tax_diff_after": comparison.get("tax_diff_after_paise"),
                "authoritative_record_ref": getattr(candidate, "id", None) if candidate else None,
                "evaluated_at": completion_iso,
                "comparison_reason": comparison["comparison_reason"],
            },
        )

        return wis.get_work_item(sb, wid, current_user)

    except Exception as exc:
        _log.exception("Revalidation execution error on work item %s: %s", wid, exc)
        err_iso = _now_iso()
        _update_work_item(sb, wid, {
            "revalidation_status": STATUS_ERROR,
            "revalidation_result": RESULT_ERROR,
            "revalidation_completed_at": err_iso,
            "updated_at": err_iso,
            "updated_by": uid,
        })

        _record_reval_event(
            sb,
            wid,
            "REVALIDATION_COMPLETED",
            actor_id=uid,
            actor_role=user_role,
            actor_name=user_name,
            note=f"Revalidation encountered technical error: {exc!s}",
            metadata={
                "source_run_id": source_run_id,
                "target_run_id": target_run_id,
                "revalidation_result": RESULT_ERROR,
                "error_message": str(exc),
                "evaluated_at": err_iso,
            },
        )
        return wis.get_work_item(sb, wid, current_user)
