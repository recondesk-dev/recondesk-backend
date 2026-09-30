"""Reconciliation results, history, diff, summary, finalize — `/api/reconciliation`."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json as _json
import logging
import math
import re
import threading
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Callable, Literal, Mapping, Optional, TypeVar
from urllib.parse import unquote

TSeq = TypeVar("TSeq")
TRet = TypeVar("TRet")

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from uuid import UUID

from app.auth import get_current_active_user, get_user_role
from app.utils.redis_cache import (
    BUCKET_CACHE_TTL_SECONDS,
    bucket_cache_key,
    cache_get,
    cache_set,
    invalidate_run_bucket_cache,
    invalidate_user_dashboard,
)
from app.constants import RunStatus
from app.database import get_supabase, get_user_profile
from app.services.decision_templates import generate_decision
from app.services import reconciliation_outcomes as ro
from app.parsers.gstr2b_parser import resolve_itc_available, resolve_itc_reason
from app.services.firm_access import (
    assert_run_accessible,
    list_accessible_client_gstin_ids,
)
from app.services.reconciliation_display import get_display_type
from app.services.followup_audit_export import build_followup_history_xlsx_bytes
from app.services.gstr9c_itc_fy_rollup import (
    build_gstr9c_itc_fy_rollup,
    default_fy_label,
    parse_fy_label,
    periods_match_yyyy_mm,
)
from app.services.reconcile_export_workbook import build_excel_workbook_bytes
from app.utils.audit import client_display_label, log_action, log_audit
from app.utils.supabase_errors import supabase_error_message
from app.utils.storage import delete_file
from app.worker.reconciliation_task import execute_reconciliation
from app.services.invoice_results_sync import (
    count_unresolved_rule37,
    find_invoice_result_id_for_pr,
    sync_rule37_invoice_results,
)
from app.services.gstr3b_table4_engine import (
    check_finalization_blocking_exceptions,
    compile_and_save_final_table4_snapshot,
    compile_gstr3b_table4,
    compute_table4_adjustments_digest,
    get_table4_drilldown,
    load_table4_adjustments,
    rupees_to_paise,
)
from app.services.gstr3b_table4_export import generate_table4_excel_workpaper
from app.services.gstr3b_reversal_ledger import (
    ReversalStatus,
    StatutoryTemporaryReason,
    StatutoryEvidenceType,
    ReclaimEventType,
    ReclaimEventCreate,
    execute_reclaim_event,
    fulfill_reversal_condition,
    authorize_reclaim,
    get_reversal_ledger_entry,
    calculate_available_balance,
    get_reclaimable_reversals,
    get_authoritative_reclaim_history,
)


_log = logging.getLogger(__name__)
router = APIRouter()

# Singleflight locks so parallel /summary + /matched (etc.) do not rebuild the
# same Redis bucket twice when the cache is cold.
_bucket_build_locks: dict[str, threading.Lock] = {}
_bucket_build_locks_guard = threading.Lock()


def _bucket_build_lock(key: str) -> threading.Lock:
    with _bucket_build_locks_guard:
        lock = _bucket_build_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _bucket_build_locks[key] = lock
        return lock


async def _run_sync(fn: Callable[..., TRet], /, *args: Any, **kwargs: Any) -> TRet:
    """Run blocking Supabase/outcome work off the uvicorn event loop.

    One sync results rebuild must not freeze every other page on the single
    worker. HTTPException raised inside ``fn`` propagates to the caller.
    """
    if kwargs:
        return await asyncio.to_thread(lambda: fn(*args, **kwargs))
    return await asyncio.to_thread(fn, *args)


def _run_entity_label(sb, run_row: dict) -> str:
    cg_id = str(run_row.get("client_gstin_id") or "")
    period = str(run_row.get("period") or "")
    client_name = client_display_label(sb, cg_id) if cg_id else "Client"
    return f"{client_name} ({period})" if period else client_name


async def _log_result_export(
    sb,
    current_user: dict,
    run_row: dict,
    run_id: str,
    export_type: str,
) -> None:
    await log_audit(
        sb,
        current_user,
        "RESULT_EXPORTED",
        "reconciliation",
        run_id,
        _run_entity_label(sb, run_row),
        {"export_type": export_type},
    )


def _parse_uuid(s: str, name: str = "id") -> str:
    try:
        return str(UUID(s.strip()))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid {name}",
        ) from exc


def _safe_int_paise(val: Any, default: int = 0) -> int:
    """Coerce engine/DB paise fields without raising during record assembly."""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def _wrongful_risk_itc_paise(
    w: dict[str, Any], matcher: Optional[dict[str, Any]] = None
) -> int:
    """ITC at risk in paise (total tax/GST), not taxable invoice value."""
    mt = matcher or {}
    return _safe_int_paise(
        w.get("total_tax_paise"),
        _safe_int_paise(mt.get("total_tax_paise"), 0),
    )


def _wrongful_risk_taxable_paise(
    w: dict[str, Any], matcher: Optional[dict[str, Any]] = None
) -> int:
    """Taxable purchase value in paise for wrongful ITC risk rows."""
    mt = matcher or {}
    return _safe_int_paise(
        w.get("taxable_amount_paise"),
        _safe_int_paise(mt.get("taxable_amount_paise"), 0),
    )


def _wrongful_risk_invoice_value_paise(
    w: dict[str, Any], matcher: Optional[dict[str, Any]] = None
) -> int:
    """Full invoice value in paise for wrongful ITC risk rows."""
    mt = matcher or {}
    val = _safe_int_paise(
        w.get("invoice_value_paise"),
        _safe_int_paise(mt.get("invoice_value_paise"), 0),
    )
    if val <= 0:
        val = _wrongful_risk_taxable_paise(w, matcher) + _wrongful_risk_itc_paise(w, matcher)
    return val


def _wrongful_risk_record_ids_for_run(sb, rid: str) -> set[str]:
    """API record ids (``wr:{pr_id}``) from stored engine payload — no PR table scan."""
    p = _payload_or_404(sb, rid)
    engine = p.get("engine") or {}
    out: set[str] = set()
    for w in engine.get("wrongful_itc_risk") or []:
        pid = str(w.get("id", "")).strip()
        if pid:
            out.add(f"wr:{pid}")
    return out


def _assert_wr_record_ids_in_run(sb, rid: str, record_ids: list[str]) -> None:
    """Validate wrongful-ITC ids without rebuilding full display rows."""
    wanted = {str(x).strip() for x in record_ids if str(x).strip()}
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="record_ids cannot be empty",
        )
    valid = _wrongful_risk_record_ids_for_run(sb, rid)
    missing = sorted(x for x in wanted if x not in valid)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"record not found in this run: {missing[0]}",
        )


def _require_completed_run(row: dict) -> None:
    st = str(row.get("status") or "").strip().upper()
    if st != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"reconciliation results not ready (status={row.get('status')})",
        )


@router.get("/results/{run_id}")
async def get_reconciliation_results(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    row = assert_run_accessible(sb, rid, current_user)
    _require_completed_run(row)
    p = ro.load_payload(sb, rid)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no reconciliation payload for this run",
        )
    _rows, ccounts, stats = ro.build_outcome_rows(sb, rid, p)
    comp = p.get("compliance") or {}
    blocked_credit_warnings = list(comp.get("section_17_5") or [])
    return {
        "run_id": rid,
        "stats": {
            "total_invoices": stats.get("total_invoices"),
            "matched_count": stats.get("matched_count"),
            "mismatched_count": stats.get("mismatched_count"),
            "missing_in_2b_count": stats.get("missing_in_2b_count"),
            "missing_in_books_count": stats.get("missing_in_books_count"),
            "rule37_warnings_count": stats.get("rule37_warnings_count"),
            "blocked_credit_count": stats.get("blocked_credit_count"),
            "total_itc_in_gstr_paise": stats.get("total_itc_in_gstr_paise"),
            "matched_itc_paise": stats.get("matched_itc_paise"),
            "missed_itc_paise": stats.get("missed_itc_paise"),
            "wrongful_risk_paise": stats.get("wrongful_risk_paise"),
            "net_claimable_itc_paise": stats.get("net_claimable_itc_paise"),
            "match_rate_percent": stats.get("match_rate_percent"),
        },
        "category_counts": {
            "matched": ccounts.get("matched", 0),
            "missed_itc": ccounts.get("missed_itc", 0),
            "wrongful_risk": ccounts.get("wrongful_risk", 0),
            "rule37_warnings": ccounts.get("rule37_warnings", 0),
            "blocked_credit": ccounts.get("blocked_credit", 0),
            "credit_notes": ccounts.get("credit_notes", 0),
            "gstin_mismatch": ccounts.get("gstin_mismatch", 0),
            "review_required": ccounts.get("review_required", 0),
            "duplicate_entry": ccounts.get("duplicate_entry", 0),
        },
        "blocked_credit_warnings": blocked_credit_warnings,
    }


@router.get("/results/{run_id}/invoices")
async def get_reconciliation_invoices(
    run_id: str,
    category: Literal[
        "matched",
        "missed_itc",
        "wrongful_risk",
        "time_barred_itc",
        "rule37_warnings",
        "blocked_credit",
        "credit_notes",
        "gstin_mismatch",
        "review_required",
        "duplicate_entry",
        "unmatched_notes",
    ] = Query(..., description="Invoice bucket"),
    supplier_gstin: Optional[str] = None,
    invoice_search: Optional[str] = None,
    min_amount_paise: Optional[int] = None,
    max_amount_paise: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    row = assert_run_accessible(sb, rid, current_user)
    _require_completed_run(row)
    p = ro.load_payload(sb, rid)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no reconciliation payload for this run",
        )
    rows, _cc, _st = ro.build_outcome_rows(sb, rid, p)
    d_from = ro.parse_optional_date(date_from) if date_from else None
    d_to = ro.parse_optional_date(date_to) if date_to else None
    filt = ro.filter_invoices(
        rows,
        category,
        supplier_gstin=supplier_gstin,
        invoice_search=invoice_search,
        min_amount_paise=min_amount_paise,
        max_amount_paise=max_amount_paise,
        date_from=d_from,
        date_to=d_to,
    )
    page_rows, total = ro.paginate(filt, page, page_size)
    return {
        "run_id": rid,
        "category": category,
        "page": page,
        "page_size": page_size,
        "total": total,
        "invoices": [x.as_dict() for x in page_rows],
    }


@router.get("/summary/{run_id}")
async def get_reconciliation_summary(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    row = assert_run_accessible(sb, rid, current_user)
    st = str(row.get("status") or "").strip().upper()
    rres = (
        sb.table("reconciliation_run")
        .select("client_gstin_id, period, created_at")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    meta = (rres.data or [{}])[0]
    p = ro.load_payload(sb, rid)
    if not p:
        alt = _summary_without_payload(sb, row, rid=rid)
        if alt is not None:
            # Legacy /summary/{run_id} shape (paise KPI fields).
            return {
                "run_id": rid,
                "client_gstin": "",
                "period": meta.get("period") or alt.get("period"),
                "status": alt["status"],
                "status_message": alt.get("status_message"),
                "total_itc_in_gstr_paise": 0,
                "matched_itc_paise": 0,
                "missed_itc_paise": 0,
                "wrongful_risk_paise": 0,
                "net_claimable_itc_paise": 0,
                "match_rate_percent": 0,
                "created_at": meta.get("created_at"),
            }
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no reconciliation payload for this run",
        )
    _r, _c, stats = ro.build_outcome_rows(sb, rid, p)
    cgin = str(meta.get("client_gstin_id", "")).strip()
    cg = (
        sb.table("client_gstins")
        .select("gstin")
        .eq("id", cgin)
        .limit(1)
        .execute()
    )
    gstin = ""
    if cg.data:
        gstin = str(cg.data[0].get("gstin") or "")

    return {
        "run_id": rid,
        "client_gstin": gstin,
        "period": meta.get("period"),
        "status": st,
        "total_itc_in_gstr_paise": stats.get("total_itc_in_gstr_paise"),
        "matched_itc_paise": stats.get("matched_itc_paise"),
        "missed_itc_paise": stats.get("missed_itc_paise"),
        "wrongful_risk_paise": stats.get("wrongful_risk_paise"),
        "net_claimable_itc_paise": stats.get("net_claimable_itc_paise"),
        "match_rate_percent": stats.get("match_rate_percent"),
        "created_at": meta.get("created_at"),
    }


class FinalizeResponse(BaseModel):
    run_id: str
    status: str
    finalized_at: str
    finalized_by: str
    finalized_by_name: Optional[str]
    message: str


class CanonicalFinalizeResult:
    """Authoritative DTO representing the result of a canonical finalization operation."""

    def __init__(
        self,
        *,
        run_row: dict[str, Any],
        payload: dict[str, Any],
        snapshot: Optional[dict[str, Any]],
        now_iso: str,
        finalized_by: str,
        finalized_by_name: Optional[str],
        was_already_final: bool = False,
    ):
        self.run_row = run_row
        self.payload = payload
        self.snapshot = snapshot
        self.now_iso = now_iso
        self.finalized_by = finalized_by
        self.finalized_by_name = finalized_by_name
        self.was_already_final = was_already_final


async def execute_canonical_finalization(
    request: Request,
    sb: Any,
    *,
    rid: str,
    current_user: dict[str, Any],
    checklist_snapshot: Optional[dict[str, Any]] = None,
    allow_idempotent_return: bool = True,
    required_role: Optional[str] = None,
) -> CanonicalFinalizeResult:
    """Canonical, authoritative finalization service for reconciliation runs.

    Execution Pipeline:
    1. Verify tenant access (assert_run_accessible).
    2. Enforce role-based authorization (staff rejected; admin required if required_role='admin').
    3. Status validation & idempotency handling:
       - If already FINAL / locked:
         - If allow_idempotent_return=False -> HTTP 422 ("run is already final").
         - If allow_idempotent_return=True -> return existing finalized state (idempotent, no duplicates).
       - If status != COMPLETED -> HTTP 422 ("run must be complete before finalization").
    4. Validate reconciliation payload presence -> HTTP 422 ("no reconciliation payload for this run").
    5. Authoritative Gate Check (check_finalization_blocking_exceptions) -> HTTP 422 if unresolved blocking exceptions.
    6. Authoritative Table 4 Snapshot compilation & persistence (compile_and_save_final_table4_snapshot):
       - Inserts immutable snapshot into gstr3b_table4_summaries.
       - Links table4_summary_id onto reconciliation_run.
       - Auto-registers 4(B)(2) temporary reversals into gstr3b_reversal_ledger.
       - If this fails, raises exception immediately; the run remains unlocked and COMPLETED.
    7. Optimistic Run Locking:
       - Transitions reconciliation_run to status=FINAL, is_locked=True.
       - Updates finalized_at, finalized_by, updated_at, checklist_snapshot.
       - Conditional on status == COMPLETED. If 0 rows updated -> HTTP 409 Conflict (concurrent finalization).
    8. Audit Logging:
       - Emits RECON_FINALIZED audit log entry.
    9. Invalidate user dashboard cache.
    10. Return CanonicalFinalizeResult.
    """
    uid = str(current_user.get("id", ""))
    run_row = assert_run_accessible(sb, rid, current_user)
    role = await get_user_role(uid)
    role_str = (role or "").strip().lower()

    if required_role == "admin" and role_str != "admin":
        await log_action(
            uid,
            "FINALIZATION_BLOCKED",
            "reconciliation_run",
            rid,
            {"role": role},
            ip_address=(request.client.host if request.client else None),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users can finalize a reconciliation.",
        )
    if role_str == "staff":
        await log_action(
            uid,
            "FINALIZATION_BLOCKED",
            "reconciliation_run",
            rid,
            {"role": role},
            ip_address=(request.client.host if request.client else None),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    raw_status = str(run_row.get("status") or "").strip()
    st = raw_status.upper()
    is_already_final = (st == RunStatus.FINAL or raw_status.lower() == "final" or bool(run_row.get("is_locked")))

    if is_already_final:
        if not allow_idempotent_return:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="run is already final",
            )
        p = ro.load_payload(sb, rid) or {}
        try:
            patch_row = dict(run_row)
            _backfill_matched_itc_paise(sb, patch_row, persist=True)
            if isinstance(patch_row.get("run_summary"), dict):
                run_row = {**run_row, "run_summary": patch_row["run_summary"]}
        except Exception:
            _log.exception("finalize backfill matched_itc_paise failed for %s", rid)
        prof = get_user_profile(uid)
        name = (prof or {}).get("full_name")
        return CanonicalFinalizeResult(
            run_row=run_row,
            payload=p,
            snapshot=None,
            now_iso=str(run_row.get("finalized_at") or datetime.now(timezone.utc).isoformat()),
            finalized_by=str(run_row.get("finalized_by") or uid),
            finalized_by_name=name,
            was_already_final=True,
        )

    if st != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="run must be complete before finalization",
        )

    p = ro.load_payload(sb, rid)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no reconciliation payload for this run",
        )

    gate = check_finalization_blocking_exceptions(sb, rid, payload=p)
    if not gate["can_finalize"]:
        summary_msg = "; ".join(gate["blocking_summary"][:3])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{gate['unresolved_blocking_exceptions']} ITC-affecting exception(s) require disposition before finalizing. "
                f"({summary_msg})"
            ),
        )

    # 1. Compile and save Table 4 snapshot + auto-register 4B2 reversals.
    # Executed BEFORE locking run so that any failure leaves the run in COMPLETED (unlocked) state.
    try:
        snapshot = compile_and_save_final_table4_snapshot(sb, rid, uid)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve),
        )
    except Exception as exc:
        _log.exception("compile_and_save_final_table4_snapshot failed for %s", rid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Table 4 snapshot compilation failed: {exc}",
        )

    # 2. Optimistic transition to FINAL + is_locked=True
    now = datetime.now(timezone.utc).isoformat()
    update_fields: dict[str, Any] = {
        "status": RunStatus.FINAL,
        "finalized_at": now,
        "finalized_by": uid,
        "is_locked": True,
        "updated_at": now,
    }
    if checklist_snapshot is not None:
        update_fields["checklist_snapshot"] = checklist_snapshot

    try:
        patch_row = dict(run_row)
        _backfill_matched_itc_paise(sb, patch_row, persist=False)
        rs_enriched = patch_row.get("run_summary")
        if isinstance(rs_enriched, dict) and rs_enriched.get("matched_itc_paise") is not None:
            update_fields["run_summary"] = rs_enriched
            if rs_enriched.get("itc_at_risk") is not None:
                update_fields["itc_at_risk"] = rs_enriched.get("itc_at_risk")
            elif rs_enriched.get("missed_itc_paise") is not None:
                update_fields["itc_at_risk"] = rs_enriched.get("missed_itc_paise")
            if rs_enriched.get("wrongful_itc") is not None:
                update_fields["wrongful_itc"] = rs_enriched.get("wrongful_itc")
    except Exception:
        _log.exception("could not enrich run_summary before finalize for %s", rid)

    def _do_update(fields: dict[str, Any]):
        return (
            sb.table("reconciliation_run")
            .update(fields)
            .eq("id", rid)
            .eq("status", RunStatus.COMPLETED)
            .execute()
        )

    ex: Any = None
    try:
        ex = _do_update(update_fields)
    except Exception as exc:
        err = str(exc).lower()
        if checklist_snapshot is not None and (
            "checklist_snapshot" in err
            or "column" in err
            or "schema" in err
            or "pgrst" in err
        ):
            rs_raw = run_row.get("run_summary")
            summary_dict: dict[str, Any] = (
                dict(rs_raw) if isinstance(rs_raw, dict) else {}
            )
            summary_dict["finalization"] = {
                "checklist": checklist_snapshot,
                "finalized_by": uid,
                "finalized_at": now,
            }
            fields2 = {
                k: v for k, v in update_fields.items() if k != "checklist_snapshot"
            }
            fields2["run_summary"] = summary_dict
            ex = _do_update(fields2)
        else:
            raise

    if not ex.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="could not finalize run; refresh and retry",
        )

    # 3. Log audit
    await log_audit(
        sb,
        current_user,
        "RECON_FINALIZED",
        "reconciliation",
        rid,
        _run_entity_label(sb, run_row),
        ip_address=(request.client.host if request.client else None),
    )

    try:
        invalidate_user_dashboard(uid)
    except Exception:
        pass

    refreshed = (
        sb.table("reconciliation_run")
        .select("*")
        .eq("id", rid)
        .limit(1)
        .execute()
    ).data or []
    refreshed_row = refreshed[0] if refreshed else {}
    prof = get_user_profile(uid)
    name = (prof or {}).get("full_name")

    return CanonicalFinalizeResult(
        run_row={**run_row, **refreshed_row},
        payload=p,
        snapshot=snapshot,
        now_iso=now,
        finalized_by=uid,
        finalized_by_name=name,
        was_already_final=False,
    )


@router.post("/finalize/{run_id}", response_model=FinalizeResponse)
async def finalize_reconciliation(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    res = await execute_canonical_finalization(
        request,
        sb,
        rid=rid,
        current_user=current_user,
        allow_idempotent_return=False,
        required_role=None,
    )
    return FinalizeResponse(
        run_id=rid,
        status=RunStatus.FINAL,
        finalized_at=res.now_iso,
        finalized_by=res.finalized_by,
        finalized_by_name=res.finalized_by_name,
        message="Reconciliation run finalized and locked.",
    )


def _history_row(
    sb,
    run: dict,
    prev: Optional[dict],
    run_number: int,
    name_by_id: dict,
) -> dict:
    rid = str(run.get("id"))
    p = ro.load_payload(sb, rid)
    stats: dict[str, Any] = {}
    if p:
        _r, _c, stats = ro.build_outcome_rows(sb, rid, p)
    itc_d: Optional[int] = None
    mrd: Optional[float] = None
    if prev:
        pprev = ro.load_payload(sb, str(prev.get("id")))
        if pprev and p:
            _r, _c, sp = ro.build_outcome_rows(sb, str(prev.get("id")), pprev)
            itc_d = int(
                (stats.get("missed_itc_paise") or 0)
                - (sp.get("missed_itc_paise") or 0)
            )
            mrd = round(
                float(stats.get("match_rate_percent") or 0)
                - float(sp.get("match_rate_percent") or 0),
                2,
            )
    fb = str(run.get("finalized_by", "") or "")
    mc = stats.get("matched_count")
    if mc is None and isinstance(run.get("run_summary"), dict):
        mc = (run.get("run_summary") or {}).get("matched_count")
    return {
        "run_id": rid,
        "period": run.get("period"),
        "run_number": run_number,
        "status": str(run.get("status") or ""),
        "matched_count": mc,
        "missed_itc_amount_paise": stats.get("missed_itc_paise"),
        "wrongful_risk_amount_paise": stats.get("wrongful_risk_paise"),
        "match_rate_percent": stats.get("match_rate_percent"),
        "itc_delta_paise": itc_d,
        "match_rate_delta": mrd,
        "finalized_at": run.get("finalized_at"),
        "finalized_by_name": name_by_id.get(fb) if fb else None,
        "created_at": run.get("created_at"),
    }


@router.get("/history/{client_gstin}")
async def get_reconciliation_history(
    client_gstin: str,
    current_user: dict = Depends(get_current_active_user),
):
    cg = re.sub(r"\s+", "", (client_gstin or "")).upper()
    if not ro.is_valid_gstin(cg):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid GSTIN format",
        )
    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    r = (
        sb.table("client_gstins")
        .select("id, firm_owner_id, gstin, assigned_to")
        .eq("gstin", cg)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client not found for this GSTIN",
        )
    row = r.data[0]
    prof = get_user_profile(uid) or {}
    role = (prof.get("role") or "staff").lower()
    if role == "admin":
        if str(row.get("firm_owner_id", "")) != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not allowed for this client",
            )
    elif str(row.get("assigned_to", "")) != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )
    cgid = str(row["id"])
    res = (
        sb.table("reconciliation_run")
        .select(
            "id, period, status, run_summary, created_at, finalized_at, finalized_by, client_gstin_id"
        )
        .eq("client_gstin_id", cgid)
        .execute()
    )
    data = list(res.data or [])

    def _period_sort_key(period: str) -> tuple[int, int]:
        try:
            y, m = (period or "0000-00").split("-", 1)
            return (int(y), int(m))
        except ValueError:
            return (0, 0)

    data.sort(
        key=lambda d: (
            _period_sort_key(str(d.get("period") or "")),
            str(d.get("created_at") or ""),
        )
    )
    uids: set[str] = set()
    for x in data:
        if x.get("finalized_by"):
            uids.add(str(x.get("finalized_by")))
    name_by: dict[str, str] = {}
    for uu in uids:
        p2 = get_user_profile(uu) or {}
        if p2.get("full_name"):
            name_by[uu] = str(p2.get("full_name"))
    by_period: dict[str, int] = {}
    out_asc: list[dict] = []
    for i, run in enumerate(data):
        pkey = str(run.get("period") or "")
        by_period[pkey] = by_period.get(pkey, 0) + 1
        rnum = by_period[pkey]
        prev = data[i - 1] if i > 0 else None
        out_asc.append(_history_row(sb, run, prev, rnum, name_by))
    return list(reversed(out_asc))


@router.get("/diff/{run_id_1}/{run_id_2}")
async def get_reconciliation_diff(
    run_id_1: str,
    run_id_2: str,
    current_user: dict = Depends(get_current_active_user),
):
    a = _parse_uuid(run_id_1, "run_id_1")
    b = _parse_uuid(run_id_2, "run_id_2")
    if a == b:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="select two different runs",
        )
    sb = get_supabase()
    r1 = assert_run_accessible(sb, a, current_user)
    r2 = assert_run_accessible(sb, b, current_user)
    if str(r1.get("client_gstin_id")) != str(r2.get("client_gstin_id")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="runs must belong to the same client",
        )
    if str(r1.get("period", "")) != str(r2.get("period", "")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="compares must be for the same tax period",
        )
    p1 = ro.load_payload(sb, a)
    p2 = ro.load_payload(sb, b)
    if not p1 or not p2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="reconciliation payload missing for one of the runs",
        )
    g1, g2 = ro.load_gstr_map(sb, a), ro.load_gstr_map(sb, b)
    pr1, pr2 = ro.load_pr_map(sb, a), ro.load_pr_map(sb, b)
    cgid = str(r1.get("client_gstin_id", ""))
    cgr = (
        sb.table("client_gstins")
        .select("gstin")
        .eq("id", cgid)
        .limit(1)
        .execute()
    )
    gl = str((cgr.data or [{}])[0].get("gstin") or "")
    d = ro.compare_runs_simple(
        p1,
        p2,
        g1,
        g2,
        pr1,
        pr2,
        str(r1.get("period", "")),
        gl,
        a,
        b,
    )
    invs = d.pop("invoices", [])
    return {**d, "changed_invoices": invs}


class Rule37ResolveResponse(BaseModel):
    invoice_result_id: str
    resolved_by: str
    resolved_at: str
    resolution_note: Optional[str] = None


class Rule37ActionPatch(BaseModel):
    status: Literal["resolved", "acknowledged"]
    amount_paid: Optional[float] = Field(None, ge=0)
    tds_deducted: float = Field(default=0, ge=0)
    tds_confirmed: bool = False
    total_settled: Optional[float] = Field(None, ge=0)


class Rule37ActionResponse(BaseModel):
    id: str
    status: Literal["resolved", "acknowledged"]
    acted_by: str
    acted_at: str
    amount_paid: Optional[float] = None
    tds_deducted: float = 0
    tds_confirmed: bool = False
    total_settled: Optional[float] = None
    remaining_unpaid_amount: Optional[float] = None
    payment_coverage: Optional[Literal["full", "partial"]] = None


class Rule37SummaryStats(BaseModel):
    total_itc_at_risk: float
    itc_saved: float
    itc_reversed: float
    pending_action: float
    # Past-180 invoices with blank payment_status — not in confirmed at-risk.
    pending_verification_count: int = 0
    pending_verification_exposure: float = 0.0
    # Matched ITC-claimed invoices vs those with an explicit PR payment_status.
    claimed_invoice_count: int = 0
    payment_status_known_count: int = 0
    payment_status_unknown_count: int = 0
    # False for older runs that predate coverage metrics.
    coverage_available: bool = False


class Rule37ActionHistoryItem(BaseModel):
    id: str
    invoice_number: str
    supplier_gstin: str
    amount: float
    action: Literal["mark_paid", "reverse_itc"]
    created_at: str
    generated_by: str
    generated_by_name: str
    amount_paid: Optional[float] = None
    tds_deducted: float = 0
    total_settled: Optional[float] = None
    remaining_unpaid_amount: Optional[float] = None
    payment_coverage: Optional[Literal["full", "partial"]] = None


class Rule37SummaryResponse(BaseModel):
    summary: Rule37SummaryStats
    action_history: list[Rule37ActionHistoryItem]


class ConfidenceSummaryResponse(BaseModel):
    """Run-level match-confidence buckets (read-only aggregation)."""

    run_id: str
    total_invoices: int
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    unmatched: int


class DecisionStatusPatch(BaseModel):
    status: Optional[Literal["acted", "ignored", "pending"]] = None
    decision_status: Optional[Literal["acted", "ignored", "pending"]] = None


class DecisionBulkUpdateBody(BaseModel):
    run_id: Optional[str] = None
    record_ids: list[str] = Field(default_factory=list, min_length=1)
    decision_status: Literal["acted", "ignored", "pending"]


class DecisionStatusResponse(BaseModel):
    id: str
    status: Literal["acted", "ignored", "pending"]


class DecisionBulkUpdateResponse(BaseModel):
    updated_count: int


class FollowupInvoiceSnapshotItem(BaseModel):
    record_id: str = Field(..., min_length=1)
    supplier_gstin: str = Field(..., min_length=1)
    invoice_number: str = ""
    invoice_date: str = ""
    amount: float = 0.0
    decision_what: Optional[str] = None
    decision_why: Optional[str] = None
    decision_next: Optional[str] = None
    trade_name: Optional[str] = None


class SupplierFollowupAuditBody(BaseModel):
    supplier_gstin: str = Field(..., min_length=1)
    record_ids: list[str] = Field(..., min_length=1)
    tax_period: str = Field(..., min_length=4, max_length=7)
    invoice_snapshot: list[FollowupInvoiceSnapshotItem] = Field(..., min_length=1)
    template_type: Literal["wrongful_itc_single", "wrongful_itc_bulk"]
    status: Literal["generated", "downloaded", "copied"]
    supplier_name_display: Optional[str] = Field(None, max_length=200)
    # Full letter text at action time (generated draft, or edited copy/download).
    letter_body: str = Field(..., min_length=1, max_length=100_000)


class SupplierFollowupAuditResponse(BaseModel):
    id: str
    status: str
    generated_at: str


class SupplierFollowupAuditListItem(BaseModel):
    id: str
    run_id: str
    tax_period: str
    supplier_gstin: str
    supplier_name_display: Optional[str] = None
    template_type: str
    status: str
    generated_by: str
    generated_by_name: str
    generated_at: str
    invoice_numbers_display: str = ""
    letter_body: Optional[str] = None


_FOLLOWUP_AUDIT_STATUSES = frozenset({"generated", "downloaded", "copied"})
_FOLLOWUP_AUDIT_RUN_CHUNK = 100


def _followup_audit_invoice_numbers_display(row: dict[str, Any]) -> str:
    snap = row.get("invoice_snapshot")
    if isinstance(snap, str):
        try:
            import json

            snap = json.loads(snap)
        except Exception:
            return ""
    if not isinstance(snap, list) or not snap:
        return ""
    nums: list[str] = []
    for item in snap:
        if not isinstance(item, dict):
            continue
        n = str(item.get("invoice_number") or "").strip()
        if n:
            nums.append(n)
    if not nums:
        return ""
    if len(nums) == 1:
        return nums[0]
    if len(nums) <= 3:
        return ", ".join(nums)
    return f"{nums[0]} +{len(nums) - 1} more"


def _followup_audit_user_names(uids: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for uid in uids:
        if not uid:
            continue
        prof = get_user_profile(uid) or {}
        fn = (prof.get("full_name") or "").strip()
        out[uid] = fn or uid
    return out


def _followup_audit_query(
    sb,
    *,
    run_id: Optional[str] = None,
    run_ids: Optional[list[str]] = None,
    status: Optional[str] = None,
    supplier_gstin: Optional[str] = None,
    tax_period: Optional[str] = None,
) -> list[dict[str, Any]]:
    if run_id:
        ids = [run_id]
    elif run_ids is not None:
        ids = [str(x).strip() for x in run_ids if str(x).strip()]
        if not ids:
            return []
    else:
        return []

    st = (status or "").strip().lower() or None
    sg = (supplier_gstin or "").strip().upper() or None
    tp = (tax_period or "").strip() or None

    rows: list[dict[str, Any]] = []
    for i in range(0, len(ids), _FOLLOWUP_AUDIT_RUN_CHUNK):
        chunk = ids[i : i + _FOLLOWUP_AUDIT_RUN_CHUNK]
        q = (
            sb.table("supplier_followup_audit")
            .select(
                "id, run_id, tax_period, supplier_gstin, supplier_name_display, "
                "template_type, status, generated_by, generated_at, invoice_snapshot, "
                "letter_body"
            )
            .in_("run_id", chunk)
        )
        if st:
            q = q.eq("status", st)
        if sg:
            q = q.eq("supplier_gstin", sg)
        if tp:
            q = q.eq("tax_period", tp)
        res = q.order("generated_at", desc=True).execute()
        rows.extend(list(res.data or []))

    rows.sort(key=lambda r: str(r.get("generated_at") or ""), reverse=True)
    return rows


def _followup_audit_list_response(rows: list[dict[str, Any]]) -> list[SupplierFollowupAuditListItem]:
    uids = {
        str(r.get("generated_by") or "").strip()
        for r in rows
        if r.get("generated_by")
    }
    names = _followup_audit_user_names(uids)
    out: list[SupplierFollowupAuditListItem] = []
    for r in rows:
        gb = str(r.get("generated_by") or "").strip()
        out.append(
            SupplierFollowupAuditListItem(
                id=str(r.get("id") or ""),
                run_id=str(r.get("run_id") or ""),
                tax_period=str(r.get("tax_period") or ""),
                supplier_gstin=str(r.get("supplier_gstin") or ""),
                supplier_name_display=r.get("supplier_name_display"),
                template_type=str(r.get("template_type") or ""),
                status=str(r.get("status") or ""),
                generated_by=gb,
                generated_by_name=names.get(gb, ""),
                generated_at=str(r.get("generated_at") or ""),
                invoice_numbers_display=_followup_audit_invoice_numbers_display(r),
                letter_body=(
                    str(r["letter_body"])
                    if r.get("letter_body") is not None
                    and str(r.get("letter_body") or "").strip()
                    else None
                ),
            )
        )
    return out


def _parse_followup_audit_status_filter(status: Optional[str]) -> Optional[str]:
    if not status or not str(status).strip():
        return None
    st = str(status).strip().lower()
    if st not in _FOLLOWUP_AUDIT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must be generated, downloaded, or copied",
        )
    return st


@router.post(
    "/runs/{run_id}/rule37/{pr_id}/resolve",
    response_model=Rule37ResolveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def mark_rule37_resolved(
    run_id: str,
    pr_id: str,
    resolution_note: Optional[str] = Body(None, max_length=500),
    current_user: dict = Depends(get_current_active_user),
):
    """Record Rule 37 resolution in ``rule37_resolutions`` (required before finalize)."""
    rid = _parse_uuid(run_id, "run_id")
    pr_key = str(pr_id).strip()
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    row = (
        sb.table("reconciliation_run")
        .select("id, status, client_gstin_id, is_locked")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not row.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    r0 = row.data[0]
    if bool(r0.get("is_locked")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="locked runs cannot be modified",
        )
    st = str(r0.get("status", "")).upper()
    if st == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="run is final"
        )
    if resolution_note is not None and len(resolution_note) > 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="resolution_note max 500 characters",
        )
    sync_rule37_invoice_results(sb, rid)
    inv_res_id = find_invoice_result_id_for_pr(sb, rid, pr_key)
    if not inv_res_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no rule37 concern in stored payload for this pr_id",
        )
    exist = (
        sb.table("rule37_resolutions")
        .select("id")
        .eq("invoice_result_id", inv_res_id)
        .limit(1)
        .execute()
    )
    if exist.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this invoice is already marked resolved",
        )
    uid = str(current_user.get("id", ""))
    now = datetime.now(timezone.utc).isoformat()
    ins: dict = {
        "run_id": rid,
        "invoice_result_id": inv_res_id,
        "resolved_by": uid,
        "resolved_at": now,
    }
    if resolution_note is not None:
        ins["resolution_note"] = resolution_note
    sb.table("rule37_resolutions").insert(ins).execute()
    return Rule37ResolveResponse(
        invoice_result_id=inv_res_id,
        resolved_by=uid,
        resolved_at=now,
        resolution_note=resolution_note,
    )



# ── Phase 3D: GSTR-3B Table 4 Reversal & Reclaim Ledger Endpoints ───────────


class FulfillReversalConditionRequest(BaseModel):
    evidence_type: Optional[str] = None
    evidence_reference: Optional[str] = None
    evidence_document_date: Optional[date] = None
    condition_fulfilled_date: Optional[date] = None
    payment_reference: Optional[str] = None
    payment_date: Optional[date] = None
    supplier_filing_date: Optional[date] = None
    supplier_filing_arn: Optional[str] = None
    goods_receipt_date: Optional[date] = None
    notes: Optional[str] = None


class AuthorizeReclaimRequest(BaseModel):
    reclaim_target_period: Optional[str] = None
    reclaim_eligibility_date: Optional[date] = None
    authorization_notes: Optional[str] = None
    authorization_reference: Optional[str] = None


class ReclaimExecutionRequest(BaseModel):
    ledger_id: str
    reclaim_igst_paise: int = 0
    reclaim_cgst_paise: int = 0
    reclaim_sgst_paise: int = 0
    reclaim_cess_paise: int = 0
    statutory_evidence_type: Optional[str] = None
    evidence_reference: Optional[str] = None
    evidence_document_date: Optional[date] = None
    reclaim_notes: Optional[str] = "Reclaim executed via API"
    idempotency_key: Optional[str] = None


def _resolve_client_gstin_id(sb: Any, client_id_or_gstin: str) -> str:
    s = str(client_id_or_gstin).strip()
    try:
        UUID(s)
        return s
    except ValueError:
        pass
    row = sb.table("client_gstins").select("id").eq("gstin", s.upper()).limit(1).execute()
    if row.data and row.data[0].get("id"):
        return str(row.data[0]["id"]).strip()
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Client '{s}' not found")


def _assert_client_accessible(sb: Any, client_gstin_id: str, current_user: dict) -> None:
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if client_gstin_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: client is outside your authorized firm scope",
        )


@router.get("/{run_id}/table4/reversal-ledger")
async def get_run_table4_reversal_ledger(
    run_id: str,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (comma-separated or single)"),
    is_reclaimable: Optional[bool] = Query(None, description="Filter by reclaimability"),
    current_user: dict = Depends(get_current_active_user),
):
    """Source-run provenance view: returns Table 4(B)(2) reversals originating from this run."""
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)

    q = sb.table("gstr3b_reversal_ledger").select("*").eq("source_run_id", rid)
    if status_filter:
        statuses = [s.strip().upper() for s in status_filter.split(",") if s.strip()]
        if statuses:
            q = q.in_("status", statuses)
    if is_reclaimable is not None:
        q = q.eq("is_reclaimable", is_reclaimable)

    res = q.order("created_at", desc=False).execute()
    rows = res.data or []

    rev_igst = sum(int(r.get("reversed_igst_paise") or 0) for r in rows)
    rev_cgst = sum(int(r.get("reversed_cgst_paise") or 0) for r in rows)
    rev_sgst = sum(int(r.get("reversed_sgst_paise") or 0) for r in rows)
    rev_cess = sum(int(r.get("reversed_cess_paise") or 0) for r in rows)

    rec_igst = sum(int(r.get("cached_reclaimed_igst_paise") or 0) for r in rows)
    rec_cgst = sum(int(r.get("cached_reclaimed_cgst_paise") or 0) for r in rows)
    rec_sgst = sum(int(r.get("cached_reclaimed_sgst_paise") or 0) for r in rows)
    rec_cess = sum(int(r.get("cached_reclaimed_cess_paise") or 0) for r in rows)

    items = []
    for r in rows:
        item = dict(r)
        rem_igst = max(0, int(r.get("reversed_igst_paise") or 0) - int(r.get("cached_reclaimed_igst_paise") or 0))
        rem_cgst = max(0, int(r.get("reversed_cgst_paise") or 0) - int(r.get("cached_reclaimed_cgst_paise") or 0))
        rem_sgst = max(0, int(r.get("reversed_sgst_paise") or 0) - int(r.get("cached_reclaimed_sgst_paise") or 0))
        rem_cess = max(0, int(r.get("reversed_cess_paise") or 0) - int(r.get("cached_reclaimed_cess_paise") or 0))
        item["remaining_balances_paise"] = {
            "igst": rem_igst,
            "cgst": rem_cgst,
            "sgst": rem_sgst,
            "cess": rem_cess,
            "total": rem_igst + rem_cgst + rem_sgst + rem_cess,
        }
        items.append(item)

    return {
        "source_run_id": rid,
        "client_gstin_id": run_row.get("client_gstin_id"),
        "period": run_row.get("period"),
        "total_count": len(items),
        "summary": {
            "reversed": {
                "igst_paise": rev_igst,
                "cgst_paise": rev_cgst,
                "sgst_paise": rev_sgst,
                "cess_paise": rev_cess,
                "total_paise": rev_igst + rev_cgst + rev_sgst + rev_cess,
            },
            "reclaimed": {
                "igst_paise": rec_igst,
                "cgst_paise": rec_cgst,
                "sgst_paise": rec_sgst,
                "cess_paise": rec_cess,
                "total_paise": rec_igst + rec_cgst + rec_sgst + rec_cess,
            },
            "outstanding": {
                "igst_paise": max(0, rev_igst - rec_igst),
                "cgst_paise": max(0, rev_cgst - rec_cgst),
                "sgst_paise": max(0, rev_sgst - rec_sgst),
                "cess_paise": max(0, rev_cess - rec_cess),
                "total_paise": max(0, (rev_igst + rev_cgst + rev_sgst + rev_cess) - (rec_igst + rec_cgst + rec_sgst + rec_cess)),
            },
        },
        "items": items,
    }


@router.get("/{client_id}/reversal-ledger")
async def get_client_reversal_ledger(
    client_id: str,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (comma-separated or single)"),
    statutory_reason: Optional[str] = Query(None, description="Filter by statutory_reason"),
    is_reclaimable: Optional[bool] = Query(None, description="Filter by reclaimability"),
    tax_period: Optional[str] = Query(None, description="Filter by reversal_tax_period"),
    reversal_tax_period: Optional[str] = Query(None, description="Alias for tax_period"),
    current_user: dict = Depends(get_current_active_user),
):
    """Client lifecycle view: returns all reversal records for a client across periods."""
    sb = get_supabase()
    cid = _resolve_client_gstin_id(sb, client_id)
    _assert_client_accessible(sb, cid, current_user)

    q = sb.table("gstr3b_reversal_ledger").select("*").eq("client_gstin_id", cid)
    if status_filter:
        statuses = [s.strip().upper() for s in status_filter.split(",") if s.strip()]
        if statuses:
            q = q.in_("status", statuses)
    if statutory_reason:
        q = q.eq("statutory_reason", statutory_reason.strip().upper())
    if is_reclaimable is not None:
        q = q.eq("is_reclaimable", is_reclaimable)
    period_filter = (tax_period or reversal_tax_period or "").strip()
    if period_filter:
        q = q.eq("reversal_tax_period", period_filter)

    res = q.order("reversal_tax_period", desc=False).order("created_at", desc=False).execute()
    rows = res.data or []

    rev_igst = sum(int(r.get("reversed_igst_paise") or 0) for r in rows)
    rev_cgst = sum(int(r.get("reversed_cgst_paise") or 0) for r in rows)
    rev_sgst = sum(int(r.get("reversed_sgst_paise") or 0) for r in rows)
    rev_cess = sum(int(r.get("reversed_cess_paise") or 0) for r in rows)

    rec_igst = sum(int(r.get("cached_reclaimed_igst_paise") or 0) for r in rows)
    rec_cgst = sum(int(r.get("cached_reclaimed_cgst_paise") or 0) for r in rows)
    rec_sgst = sum(int(r.get("cached_reclaimed_sgst_paise") or 0) for r in rows)
    rec_cess = sum(int(r.get("cached_reclaimed_cess_paise") or 0) for r in rows)

    items = []
    for r in rows:
        item = dict(r)
        rem_igst = max(0, int(r.get("reversed_igst_paise") or 0) - int(r.get("cached_reclaimed_igst_paise") or 0))
        rem_cgst = max(0, int(r.get("reversed_cgst_paise") or 0) - int(r.get("cached_reclaimed_cgst_paise") or 0))
        rem_sgst = max(0, int(r.get("reversed_sgst_paise") or 0) - int(r.get("cached_reclaimed_sgst_paise") or 0))
        rem_cess = max(0, int(r.get("reversed_cess_paise") or 0) - int(r.get("cached_reclaimed_cess_paise") or 0))
        item["remaining_balances_paise"] = {
            "igst": rem_igst,
            "cgst": rem_cgst,
            "sgst": rem_sgst,
            "cess": rem_cess,
            "total": rem_igst + rem_cgst + rem_sgst + rem_cess,
        }
        items.append(item)

    return {
        "client_gstin_id": cid,
        "total_count": len(items),
        "summary": {
            "reversed": {
                "igst_paise": rev_igst,
                "cgst_paise": rev_cgst,
                "sgst_paise": rev_sgst,
                "cess_paise": rev_cess,
                "total_paise": rev_igst + rev_cgst + rev_sgst + rev_cess,
            },
            "reclaimed": {
                "igst_paise": rec_igst,
                "cgst_paise": rec_cgst,
                "sgst_paise": rec_sgst,
                "cess_paise": rec_cess,
                "total_paise": rec_igst + rec_cgst + rec_sgst + rec_cess,
            },
            "outstanding": {
                "igst_paise": max(0, rev_igst - rec_igst),
                "cgst_paise": max(0, rev_cgst - rec_cgst),
                "sgst_paise": max(0, rev_sgst - rec_sgst),
                "cess_paise": max(0, rev_cess - rec_cess),
                "total_paise": max(0, (rev_igst + rev_cgst + rev_sgst + rev_cess) - (rec_igst + rec_cgst + rec_sgst + rec_cess)),
            },
        },
        "items": items,
    }


@router.get("/{client_id}/reclaimable-balances")
async def get_client_reclaimable_balances(
    client_id: str,
    tax_period: Optional[str] = Query(None, description="Filter up to tax period"),
    current_user: dict = Depends(get_current_active_user),
):
    """Aggregate outstanding reclaimable balances for a client across tax heads."""
    sb = get_supabase()
    cid = _resolve_client_gstin_id(sb, client_id)
    _assert_client_accessible(sb, cid, current_user)

    entries = get_reclaimable_reversals(sb, cid, tax_period=tax_period)

    auth_igst = auth_cgst = auth_sgst = auth_cess = 0
    pend_igst = pend_cgst = pend_sgst = pend_cess = 0

    for e in entries:
        bal = e.get("available_balance", {})
        st = e.get("status")
        igst = int(bal.get("igst_paise") or 0)
        cgst = int(bal.get("cgst_paise") or 0)
        sgst = int(bal.get("sgst_paise") or 0)
        cess = int(bal.get("cess_paise") or 0)

        if st in (ReversalStatus.RECLAIM_AUTHORIZED.value, ReversalStatus.PARTIALLY_RECLAIMED.value):
            auth_igst += igst
            auth_cgst += cgst
            auth_sgst += sgst
            auth_cess += cess
        else:
            pend_igst += igst
            pend_cgst += cgst
            pend_sgst += sgst
            pend_cess += cess

    return {
        "client_gstin_id": cid,
        "as_of_period": tax_period,
        "total_reclaimable_authorized": {
            "igst_paise": auth_igst,
            "cgst_paise": auth_cgst,
            "sgst_paise": auth_sgst,
            "cess_paise": auth_cess,
            "total_paise": auth_igst + auth_cgst + auth_sgst + auth_cess,
        },
        "total_pending_authorization": {
            "igst_paise": pend_igst,
            "cgst_paise": pend_cgst,
            "sgst_paise": pend_sgst,
            "cess_paise": pend_cess,
            "total_paise": pend_igst + pend_cgst + pend_sgst + pend_cess,
        },
        "items": entries,
    }


@router.post("/{run_id}/table4/reversal-ledger/{ledger_id}/fulfill")
async def post_fulfill_reversal_condition(
    run_id: str,
    ledger_id: str,
    body: FulfillReversalConditionRequest,
    request: Request,
    current_user: dict = Depends(get_current_active_user),
):
    """Transition an OPEN reversal entry to CONDITION_FULFILLED with required statutory evidence."""
    rid = _parse_uuid(run_id, "run_id")
    lid = _parse_uuid(ledger_id, "ledger_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)

    try:
        ledger = get_reversal_ledger_entry(sb, lid)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Reversal ledger entry not found: {lid}") from exc

    # Client isolation check
    if str(ledger.get("client_gstin_id", "")).strip() != str(run_row.get("client_gstin_id", "")).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Ledger entry belongs to a different client than the specified run.",
        )

    # Reclaimability guardrail
    if not ledger.get("is_reclaimable") or ledger.get("status") == ReversalStatus.NON_RECLAIMABLE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Non-reclaimable reversal entry ({lid}) cannot fulfill reclaim conditions.",
        )

    # State check: must be OPEN
    cur_status = ledger.get("status")
    if cur_status != ReversalStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot fulfill condition: Entry is in '{cur_status}' state, but must be 'OPEN'.",
        )

    # Statutory evidence validation based on reason
    stat_reason = str(ledger.get("statutory_reason", "")).upper()
    if stat_reason == StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value:
        if not (body.payment_reference or body.evidence_reference or body.payment_date):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Rule 37 condition fulfillment requires payment reference / payment date evidence.",
            )
    elif stat_reason == StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING.value:
        if not (body.supplier_filing_date or body.supplier_filing_arn or body.evidence_reference):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Rule 37A condition fulfillment requires supplier filing date and ARN evidence.",
            )
    elif stat_reason == StatutoryTemporaryReason.SECTION_16_2_B_NOT_RECEIVED.value:
        if not (body.goods_receipt_date or body.evidence_reference or body.notes):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Section 16(2)(b) condition fulfillment requires goods receipt confirmation date or evidence reference.",
            )

    # Resolve evidence type
    ev_type = None
    if body.evidence_type:
        try:
            ev_type = StatutoryEvidenceType(body.evidence_type.upper())
        except ValueError:
            pass
    if not ev_type:
        if stat_reason == StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value:
            ev_type = StatutoryEvidenceType.PAYMENT_TO_SUPPLIER
        elif stat_reason == StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING.value:
            ev_type = StatutoryEvidenceType.SUPPLIER_GSTR3B_FILED
        elif stat_reason == StatutoryTemporaryReason.SECTION_16_2_B_NOT_RECEIVED.value:
            ev_type = StatutoryEvidenceType.GOODS_RECEIVED_GRN
        elif stat_reason == StatutoryTemporaryReason.SECTION_16_2_C_SUPPLIER_TAX_CONDITION.value:
            ev_type = StatutoryEvidenceType.TAX_DISCHARGE_CONFIRMED
        else:
            ev_type = StatutoryEvidenceType.OTHER_STATUTORY_PROOF

    ev_ref = (
        body.evidence_reference
        or body.payment_reference
        or body.supplier_filing_arn
        or f"FULFILL-{lid[:8]}"
    )
    ev_doc_date = body.evidence_document_date or body.payment_date or body.supplier_filing_date or body.goods_receipt_date

    updated = fulfill_reversal_condition(
        sb,
        lid,
        evidence_type=ev_type,
        evidence_reference=ev_ref,
        evidence_document_date=ev_doc_date,
        condition_fulfilled_date=body.condition_fulfilled_date or date.today(),
        notes=body.notes,
    )

    if stat_reason == StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING.value:
        r37a_updates = {}
        if body.supplier_filing_date:
            r37a_updates["subsequent_supplier_filing_date"] = str(body.supplier_filing_date)
        if body.supplier_filing_arn:
            r37a_updates["subsequent_filing_arn"] = str(body.supplier_filing_arn)
        if r37a_updates:
            sb.table("gstr3b_reversal_ledger").update(r37a_updates).eq("id", lid).execute()
            updated.update(r37a_updates)

    uid = str(current_user.get("id", "")).strip() or None
    await log_action(
        uid,
        "TABLE4_REVERSAL_CONDITION_FULFILLED",
        "gstr3b_reversal_ledger",
        lid,
        {
            "statutory_reason": stat_reason,
            "evidence_type": ev_type.value,
            "evidence_reference": ev_ref,
            "client_gstin_id": ledger.get("client_gstin_id"),
            "source_run_id": rid,
        },
        ip_address=(request.client.host if request.client else None),
    )

    return {
        "success": True,
        "ledger_id": lid,
        "status": updated.get("status"),
        "condition_fulfilled_date": updated.get("condition_fulfilled_date"),
        "entry": updated,
    }


@router.post("/{run_id}/table4/reversal-ledger/{ledger_id}/authorize")
async def post_authorize_reversal_reclaim(
    run_id: str,
    ledger_id: str,
    body: AuthorizeReclaimRequest,
    request: Request,
    current_user: dict = Depends(get_current_active_user),
):
    """Transition a CONDITION_FULFILLED reversal entry to RECLAIM_AUTHORIZED."""
    rid = _parse_uuid(run_id, "run_id")
    lid = _parse_uuid(ledger_id, "ledger_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)

    try:
        ledger = get_reversal_ledger_entry(sb, lid)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Reversal ledger entry not found: {lid}") from exc

    if str(ledger.get("client_gstin_id", "")).strip() != str(run_row.get("client_gstin_id", "")).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Ledger entry belongs to a different client than the specified run.",
        )

    if not ledger.get("is_reclaimable") or ledger.get("status") == ReversalStatus.NON_RECLAIMABLE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Non-reclaimable reversal entry ({lid}) cannot be authorized for reclaim.",
        )

    cur_status = ledger.get("status")
    if cur_status == ReversalStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot authorize reclaim: Entry condition has not been fulfilled. Must be in 'CONDITION_FULFILLED' state.",
        )
    if cur_status in (ReversalStatus.FULLY_RECLAIMED.value,):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot authorize reclaim: Entry is already 'FULLY_RECLAIMED'.",
        )
    if cur_status == ReversalStatus.RECLAIM_AUTHORIZED.value:
        return {
            "success": True,
            "ledger_id": lid,
            "status": cur_status,
            "entry": ledger,
        }

    uid = current_user.get("id") or "system"
    updated = authorize_reclaim(
        sb,
        lid,
        authorized_by=uid,
        reclaim_eligibility_date=body.reclaim_eligibility_date or date.today(),
    )
    if body.authorization_notes or body.reclaim_target_period or body.authorization_reference:
        sp = updated.get("source_payload") or {}
        sp["reclaim_authorization"] = {
            "target_period": body.reclaim_target_period,
            "notes": body.authorization_notes,
            "reference": body.authorization_reference,
            "authorized_by": uid,
            "authorized_at": datetime.now(timezone.utc).isoformat(),
        }
        sb.table("gstr3b_reversal_ledger").update({"source_payload": sp}).eq("id", lid).execute()
        updated["source_payload"] = sp

    uid_str = str(current_user.get("id", "")).strip() or None
    await log_action(
        uid_str,
        "TABLE4_REVERSAL_RECLAIM_AUTHORIZED",
        "gstr3b_reversal_ledger",
        lid,
        {
            "target_period": body.reclaim_target_period,
            "authorization_reference": body.authorization_reference,
            "client_gstin_id": ledger.get("client_gstin_id"),
            "source_run_id": rid,
        },
        ip_address=(request.client.host if request.client else None),
    )

    return {
        "success": True,
        "ledger_id": lid,
        "status": updated.get("status"),
        "reclaim_eligibility_date": updated.get("reclaim_eligibility_date"),
        "entry": updated,
    }


@router.post("/{target_run_id}/table4/reclaim")
async def post_execute_table4_reclaim(
    target_run_id: str,
    body: ReclaimExecutionRequest,
    request: Request,
    current_user: dict = Depends(get_current_active_user),
):
    """Execute an authorized reclaim against an active (unlocked, non-final) target reconciliation run."""
    trid = _parse_uuid(target_run_id, "target_run_id")
    lid = _parse_uuid(body.ledger_id, "ledger_id")
    sb = get_supabase()
    target_run = assert_run_accessible(sb, trid, current_user)

    # Immutable historical run guardrail
    if bool(target_run.get("is_locked")) or str(target_run.get("status", "")).upper() == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot execute reclaim into a finalized reconciliation run. Historical finalized runs are immutable.",
        )

    try:
        ledger = get_reversal_ledger_entry(sb, lid)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Reversal ledger entry not found: {lid}") from exc

    if str(ledger.get("client_gstin_id", "")).strip() != str(target_run.get("client_gstin_id", "")).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Ledger entry belongs to a different client than the target run.",
        )

    if not ledger.get("is_reclaimable") or ledger.get("status") == ReversalStatus.NON_RECLAIMABLE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Reversal entry ({lid}) is marked non-reclaimable and cannot be reclaimed.",
        )

    cur_status = ledger.get("status")
    if cur_status not in (ReversalStatus.RECLAIM_AUTHORIZED.value, ReversalStatus.PARTIALLY_RECLAIMED.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot execute reclaim: Reversal entry is in '{cur_status}' state, expected 'RECLAIM_AUTHORIZED'.",
        )

    igst = body.reclaim_igst_paise
    cgst = body.reclaim_cgst_paise
    sgst = body.reclaim_sgst_paise
    cess = body.reclaim_cess_paise

    if igst < 0 or cgst < 0 or sgst < 0 or cess < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reclaim amounts must be non-negative integer paise.",
        )
    tot = igst + cgst + sgst + cess
    if tot <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Total reclaim amount across all tax heads must be greater than zero.",
        )

    bal = calculate_available_balance(sb, lid)
    if igst > bal.igst_paise:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"EXCESS_RECLAIM_IGST: Requested {igst} paise exceeds available {bal.igst_paise} paise.",
        )
    if cgst > bal.cgst_paise:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"EXCESS_RECLAIM_CGST: Requested {cgst} paise exceeds available {bal.cgst_paise} paise.",
        )
    if sgst > bal.sgst_paise:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"EXCESS_RECLAIM_SGST: Requested {sgst} paise exceeds available {bal.sgst_paise} paise.",
        )
    if cess > bal.cess_paise:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"EXCESS_RECLAIM_CESS: Requested {cess} paise exceeds available {bal.cess_paise} paise.",
        )

    clean_idemp = body.idempotency_key.strip() if body.idempotency_key and body.idempotency_key.strip() else None

    # Dedicated Database-Level Idempotency Query:
    if clean_idemp:
        ev_query = (
            sb.table("gstr3b_reclaim_events")
            .select("*")
            .eq("client_gstin_id", ledger["client_gstin_id"])
            .eq("idempotency_key", clean_idemp)
            .limit(1)
            .execute()
        )
        if ev_query.data:
            ev = ev_query.data[0]
            cur_bal = calculate_available_balance(sb, lid)
            return {
                "success": True,
                "is_idempotent_replay": True,
                "event_id": str(ev.get("id")),
                "ledger_id": lid,
                "source_run_id": ledger.get("source_run_id"),
                "target_run_id": trid,
                "status": ledger.get("status"),
                "reclaimed_paise": {
                    "igst": int(ev.get("reclaimed_igst_paise") or 0),
                    "cgst": int(ev.get("reclaimed_cgst_paise") or 0),
                    "sgst": int(ev.get("reclaimed_sgst_paise") or 0),
                    "cess": int(ev.get("reclaimed_cess_paise") or 0),
                    "total": (
                        int(ev.get("reclaimed_igst_paise") or 0)
                        + int(ev.get("reclaimed_cgst_paise") or 0)
                        + int(ev.get("reclaimed_sgst_paise") or 0)
                        + int(ev.get("reclaimed_cess_paise") or 0)
                    ),
                },
                "remaining_paise": {
                    "igst": cur_bal.igst_paise,
                    "cgst": cur_bal.cgst_paise,
                    "sgst": cur_bal.sgst_paise,
                    "cess": cur_bal.cess_paise,
                    "total": cur_bal.total_paise,
                },
            }

    ev_type = StatutoryEvidenceType.OTHER_STATUTORY_PROOF
    if body.statutory_evidence_type:
        try:
            ev_type = StatutoryEvidenceType(body.statutory_evidence_type.upper())
        except ValueError:
            pass

    reclaim_req = ReclaimEventCreate(
        ledger_id=lid,
        client_gstin_id=ledger.get("client_gstin_id"),
        reclaim_run_id=trid,
        reclaim_tax_period=target_run.get("period") or "2024-03",
        event_type=ReclaimEventType.RECLAIM,
        reclaimed_igst_paise=igst,
        reclaimed_cgst_paise=cgst,
        reclaimed_sgst_paise=sgst,
        reclaimed_cess_paise=cess,
        statutory_evidence_type=ev_type,
        evidence_reference=body.evidence_reference or f"REC-{lid[:8]}",
        evidence_document_date=body.evidence_document_date,
        authorized_by=current_user.get("id"),
        reclaim_notes=(body.reclaim_notes or "Reclaim executed via API").strip(),
        idempotency_key=clean_idemp,
    )

    try:
        res = execute_reclaim_event(sb, reclaim_req)
    except Exception as exc:
        err_str = str(exc)
        if "uq_reclaim_events_client_idempotency" in err_str or "UNIQUE CONSTRAINT" in err_str:
            ev_row = (
                sb.table("gstr3b_reclaim_events")
                .select("*")
                .eq("client_gstin_id", ledger["client_gstin_id"])
                .eq("idempotency_key", clean_idemp)
                .limit(1)
                .execute()
            )
            if ev_row.data:
                ev = ev_row.data[0]
                cur_bal = calculate_available_balance(sb, lid)
                return {
                    "success": True,
                    "is_idempotent_replay": True,
                    "event_id": str(ev.get("id")),
                    "ledger_id": lid,
                    "source_run_id": ledger.get("source_run_id"),
                    "target_run_id": trid,
                    "status": ledger.get("status"),
                    "reclaimed_paise": {
                        "igst": int(ev.get("reclaimed_igst_paise") or 0),
                        "cgst": int(ev.get("reclaimed_cgst_paise") or 0),
                        "sgst": int(ev.get("reclaimed_sgst_paise") or 0),
                        "cess": int(ev.get("reclaimed_cess_paise") or 0),
                        "total": (
                            int(ev.get("reclaimed_igst_paise") or 0)
                            + int(ev.get("reclaimed_cgst_paise") or 0)
                            + int(ev.get("reclaimed_sgst_paise") or 0)
                            + int(ev.get("reclaimed_cess_paise") or 0)
                        ),
                    },
                    "remaining_paise": {
                        "igst": cur_bal.igst_paise,
                        "cgst": cur_bal.cgst_paise,
                        "sgst": cur_bal.sgst_paise,
                        "cess": cur_bal.cess_paise,
                        "total": cur_bal.total_paise,
                    },
                }
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_str,
        ) from exc

    if not res.is_idempotent_replay:
        uid = str(current_user.get("id", "")).strip() or None
        await log_action(
            uid,
            "TABLE4_RECLAIM_EXECUTED",
            "gstr3b_reclaim_events",
            res.event_id,
            {
                "ledger_id": lid,
                "client_gstin_id": ledger.get("client_gstin_id"),
                "source_run_id": ledger.get("source_run_id"),
                "target_run_id": trid,
                "idempotency_key": clean_idemp,
                "reclaimed_paise": {
                    "igst": res.reclaimed_igst_paise,
                    "cgst": res.reclaimed_cgst_paise,
                    "sgst": res.reclaimed_sgst_paise,
                    "cess": res.reclaimed_cess_paise,
                    "total": tot,
                },
            },
            ip_address=(request.client.host if request.client else None),
        )

    return {
        "success": True,
        "is_idempotent_replay": res.is_idempotent_replay,
        "event_id": res.event_id,
        "ledger_id": res.ledger_id,
        "source_run_id": ledger.get("source_run_id"),
        "target_run_id": trid,
        "status": res.status,
        "reclaimed_paise": {
            "igst": res.reclaimed_igst_paise,
            "cgst": res.reclaimed_cgst_paise,
            "sgst": res.reclaimed_sgst_paise,
            "cess": res.reclaimed_cess_paise,
            "total": res.reclaimed_igst_paise + res.reclaimed_cgst_paise + res.reclaimed_sgst_paise + res.reclaimed_cess_paise,
        },
        "remaining_paise": {
            "igst": res.remaining_igst_paise,
            "cgst": res.remaining_cgst_paise,
            "sgst": res.remaining_sgst_paise,
            "cess": res.remaining_cess_paise,
            "total": res.remaining_igst_paise + res.remaining_cgst_paise + res.remaining_sgst_paise + res.remaining_cess_paise,
        },
    }



# ── `/api/reconcile/runs/{run_id}/…` (mounted from ``main.py`` with prefix `/api/reconcile`)

reconcile_runs_router = APIRouter()


def _display_status(st: Optional[str]) -> str:
    s = (st or "").strip().lower()
    if s == RunStatus.COMPLETED.lower():
        return "completed"
    if s == RunStatus.FINAL.lower():
        return "final"
    if s == RunStatus.PENDING.lower():
        return "pending"
    if s == RunStatus.PROCESSING.lower():
        return "processing"
    return (st or "").lower() or ""


def _paise_to_rupees(paise: Optional[int]) -> float:
    """Convert paise integer to rounded rupees (2 dp). Use for per-row display.

    For totals that must avoid cumulative rounding drift, sum raw paise integers
    and call this function once on the final sum — do NOT sum the return values
    of multiple per-row calls.
    """
    if paise is None:
        return 0.0
    try:
        return round(float(paise) / 100.0, 2)
    except (TypeError, ValueError):
        return 0.0


def _paise_to_rupees_exact(paise: Optional[int]) -> float:
    """Convert paise integer to rupees WITHOUT rounding.

    Use this inside aggregation loops so that accumulated float values retain
    full precision; apply round(..., 2) once on the final sum.
    """
    if paise is None:
        return 0.0
    try:
        return float(paise) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _notes_count_for_run(sb, run_id: str) -> Counter[str]:
    try:
        r = (
            sb.table("mismatch_notes")
            .select("record_id")
            .eq("run_id", run_id)
            .execute()
        )
    except Exception:
        _log.exception("notes count reconciliation_run=%s", run_id)
        return Counter()
    c: Counter[str] = Counter()
    for row in r.data or []:
        cid = row.get("record_id")
        if cid is not None and str(cid):
            c[str(cid)] += 1
    return c


# API outcome-row ids are tagged as ``<kind>:<uuid>`` (e.g. ``pm:…``, ``wr:…``).
# ``mismatch_notes.record_id`` is a UUID column — strip the tag before PostgREST.
_RECORD_ID_PREFIXES: tuple[str, ...] = (
    "s175-db:",
    "s175:",
    "r37:",
    "pm:",
    "mi:",
    "wr:",
    "rrp:",
    "rrg:",
    "rr:",
    "dp:",
)


def _normalize_record_id(record_id: str) -> str:
    """URL-decode a path ``record_id`` (handles single and double encoding)."""
    decoded = str(record_id or "").strip()
    for _ in range(3):
        next_val = unquote(decoded)
        if next_val == decoded:
            break
        decoded = next_val
    return decoded


def _db_record_id(record_id: str) -> str:
    """Strip API record-type prefixes; leave already-bare ids unchanged.

    Frontend/API row ids look like ``pm:<uuid>``, ``wr:<uuid>``, ``r37:<uuid>``,
    etc.  DB UUID columns and PostgREST ``.eq("record_id", …)`` filters need the
    bare UUID only.
    """
    rid = _normalize_record_id(record_id)
    for prefix in _RECORD_ID_PREFIXES:
        if rid.startswith(prefix):
            rid = rid[len(prefix) :]
            break
    # If a compound key was passed (e.g. gid-pid from rrp:), extract the primary UUID
    if "-" in rid and len(rid) > 36:
        parts = rid.split("-")
        if len(parts) >= 10:
            rid = "-".join(parts[:5])
    return rid


def _rule37_db_record_key(record_id: str) -> str:
    """``mismatch_notes.record_id`` is a UUID column — strip API prefixes."""
    return _db_record_id(record_id)


def _rule37_api_record_id(db_record_id: str) -> str:
    """Map a DB ``record_id`` back to the frontend ``r37:…`` identifier."""
    rid = str(db_record_id or "").strip()
    if not rid:
        return rid
    if rid.startswith("r37:"):
        return rid
    return f"r37:{rid}"


def _rule37_db_record_lookup_keys(record_id: str) -> list[str]:
    """Candidate keys for lookup (stripped UUID plus legacy full prefixed value)."""
    full = _normalize_record_id(record_id)
    bare = _db_record_id(full)
    keys: list[str] = []
    for key in (bare, full):
        if key and key not in keys:
            keys.append(key)
    return keys


def _lookup_by_record_id(mapping: dict[str, Any], record_id: str, default: Any = None) -> Any:
    """Resolve a value keyed by either the API id or the bare DB UUID."""
    if record_id in mapping:
        return mapping[record_id]
    bare = _db_record_id(record_id)
    if bare != record_id and bare in mapping:
        return mapping[bare]
    return default


def _is_schema_compat_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(
        token in msg
        for token in (
            "pgrst204",
            "pgrst205",
            "42703",
            "42p01",
            "could not find the column",
            "could not find the table",
            "schema cache",
        )
    ):
        return True
    return any(
        token in msg
        for token in (
            "column",
            "note_type",
            "firm_owner_id",
            "severity",
        )
    )


def _rule37_record_hash(record_id: str) -> str:
    """Strip the ``r37:`` prefix → bare TEXT key for ``rule37_actions.record_hash``."""
    rid = _normalize_record_id(record_id)
    return rid[4:] if rid.startswith("r37:") else rid


def _rule37_payment_coverage(
    total_settled: float, invoice_amount: float
) -> Literal["full", "partial"]:
    if invoice_amount <= 0:
        return "full"
    if total_settled + 0.005 >= invoice_amount:
        return "full"
    return "partial"


def _rule37_invoice_amount_from_item(item: dict[str, Any]) -> float:
    inv_paise = int(item.get("total_invoice_value_paise") or 0)
    if inv_paise > 0:
        return _paise_to_rupees(inv_paise)
    return _paise_to_rupees(int(item.get("itc_at_risk_paise") or 0))


_RULE37_SETTLEMENT_COLUMNS = frozenset(
    {
        "amount_paid",
        "tds_deducted",
        "tds_confirmed",
        "total_settled",
        "remaining_unpaid_amount",
        "payment_coverage",
        "source",
        "settled_date",
        "review_metadata",
    }
)


def _rule37_action_insert_payload(
    *,
    run_id: str,
    record_hash: str,
    status_value: str,
    user_id: str,
    amount_paid: Optional[float] = None,
    tds_deducted: float = 0,
    tds_confirmed: bool = False,
    total_settled: Optional[float] = None,
    remaining_unpaid_amount: Optional[float] = None,
    payment_coverage: Optional[str] = None,
    source: Optional[str] = None,
    settled_date: Optional[str] = None,
    review_metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "record_hash": record_hash,
        "status": status_value,
        "user_id": user_id,
    }
    if status_value == "resolved":
        payload.update(
            {
                "amount_paid": round(float(amount_paid or 0), 2),
                "tds_deducted": round(float(tds_deducted or 0), 2),
                "tds_confirmed": bool(tds_confirmed),
                "total_settled": (
                    round(float(total_settled), 2)
                    if total_settled is not None
                    else None
                ),
                "remaining_unpaid_amount": (
                    round(float(remaining_unpaid_amount), 2)
                    if remaining_unpaid_amount is not None
                    else None
                ),
                "payment_coverage": payment_coverage,
                "source": (str(source).strip() if source else None),
                "settled_date": settled_date,
            }
        )
    else:
        payload.update(
            {
                "amount_paid": (
                    round(float(amount_paid), 2)
                    if amount_paid is not None
                    else None
                ),
                "tds_deducted": 0,
                "tds_confirmed": False,
                "total_settled": None,
                "remaining_unpaid_amount": None,
                "payment_coverage": payment_coverage,
                "source": (str(source).strip() if source else None),
                "settled_date": settled_date,
            }
        )
    if review_metadata is not None:
        payload["review_metadata"] = review_metadata
    return payload


def _persist_rule37_action_row(sb, payload: dict[str, Any]) -> None:
    """Delete-then-insert into ``rule37_actions`` (idempotent per run + record_hash)."""
    import traceback

    run_id = str(payload["run_id"])
    record_hash = str(payload["record_hash"])
    print("rule37 update payload:", payload)
    _log.info("rule37_actions insert payload run_id=%s hash=%s", run_id, record_hash)
    try:
        sb.table("rule37_actions").delete().eq("run_id", run_id).eq(
            "record_hash", record_hash
        ).execute()
        sb.table("rule37_actions").insert(payload).execute()
    except Exception as e:
        print("rule37 update error:", str(e))
        traceback.print_exc()
        if _is_schema_compat_error(e):
            minimal = {
                k: v
                for k, v in payload.items()
                if k not in _RULE37_SETTLEMENT_COLUMNS
            }
            print("rule37 retry payload (base columns only):", minimal)
            _log.warning(
                "rule37_actions settlement columns unavailable; retrying base insert "
                "run_id=%s hash=%s",
                run_id,
                record_hash,
            )
            sb.table("rule37_actions").delete().eq("run_id", run_id).eq(
                "record_hash", record_hash
            ).execute()
            sb.table("rule37_actions").insert(minimal).execute()
            return
        _log.exception(
            "rule37_actions insert failed run_id=%s hash=%s payload=%s",
            run_id,
            record_hash,
            payload,
        )
        raise


def _upsert_rule37_action(
    sb,
    *,
    run_id: str,
    record_id: str,
    status_value: str,
    user_id: str,
    amount_paid: Optional[float] = None,
    tds_deducted: float = 0,
    tds_confirmed: bool = False,
    total_settled: Optional[float] = None,
    remaining_unpaid_amount: Optional[float] = None,
    payment_coverage: Optional[str] = None,
    source: Optional[str] = None,
    settled_date: Optional[str] = None,
    review_metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Persist a Rule 37 action in the dedicated ``rule37_actions`` table.

    Uses delete-then-insert keyed on (run_id, record_hash) so clicking the same
    button twice is idempotent.  ``record_hash`` is the bare string after
    stripping the ``r37:`` prefix — plain TEXT, never treated as UUID.

    Optional ``source`` / ``settled_date`` support Tally Bridge auto-settle
    without duplicating this path (dashboard Mark as Settled omits them).

    Optional ``review_metadata`` stores Tally Bridge weak-match context
    (party_sim, bill_ref_score, reason) for pending_review rows.
    """
    record_hash = _rule37_record_hash(record_id)
    _log.debug(
        "rule37 action persist run_id=%s record_id=%s hash=%s status=%s",
        run_id, record_id, record_hash, status_value,
    )
    payload = _rule37_action_insert_payload(
        run_id=run_id,
        record_hash=record_hash,
        status_value=status_value,
        user_id=user_id,
        amount_paid=amount_paid,
        tds_deducted=tds_deducted,
        tds_confirmed=tds_confirmed,
        total_settled=total_settled,
        remaining_unpaid_amount=remaining_unpaid_amount,
        payment_coverage=payment_coverage,
        source=source,
        settled_date=settled_date,
        review_metadata=review_metadata,
    )
    _persist_rule37_action_row(sb, payload)


def _rule37_record_exists_in_run(
    sb,
    rid: str,
    rec_id: str,
    payload: dict[str, Any],
    notes: Counter[str],
) -> bool:
    rows_payload = _build_rule37_rows(sb, rid, payload, notes)
    if any(_normalize_record_id(str(row.get("id") or "")) == rec_id for row in rows_payload):
        return True
    if not rec_id.startswith("r37:"):
        return False
    pr_id_part = rec_id[4:]
    # Hash-based ids (r37:h:…) only exist in the payload JSON.
    if pr_id_part.startswith("h:"):
        return False
    for run_col in ("run_id", "reconciliation_run_id"):
        for col in ("pr_id", "id"):
            try:
                res = (
                    sb.table("rule37_warnings")
                    .select("id")
                    .eq(run_col, rid)
                    .eq(col, pr_id_part)
                    .limit(1)
                    .execute()
                )
                if res.data:
                    return True
            except Exception:
                continue
    return False


def _rule37_status_to_action(status: str) -> Optional[str]:
    st = (status or "").strip().lower()
    if st == "resolved":
        return "mark_paid"
    if st == "acknowledged":
        return "reverse_itc"
    return None


def _rule37_actions_history_for_run(sb, run_id: str) -> list[dict[str, Any]]:
    try:
        r = (
            sb.table("rule37_actions")
            .select(
                "id, record_hash, status, user_id, created_at, amount_paid, "
                "tds_deducted, tds_confirmed, total_settled, remaining_unpaid_amount, "
                "payment_coverage"
            )
            .eq("run_id", run_id)
            .order("created_at", desc=True)
            .execute()
        )
        return list(r.data or [])
    except Exception:
        _log.exception("rule37 actions history read failed run_id=%s", run_id)
        return []


def _rule37_action_details_for_run(sb, run_id: str) -> dict[str, dict[str, Any]]:
    try:
        r = (
            sb.table("rule37_actions")
            .select(
                "id, record_hash, status, amount_paid, tds_deducted, tds_confirmed, "
                "total_settled, remaining_unpaid_amount, payment_coverage, review_metadata, source"
            )
            .eq("run_id", run_id)
            .execute()
        )
    except Exception:
        _log.exception("rule37 action details read failed run_id=%s", run_id)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in r.data or []:
        record_hash = str(row.get("record_hash") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        if not record_hash or status not in {"resolved", "acknowledged", "pending_review", "rejected"}:
            continue
        api_id = record_hash if record_hash.startswith("r37:") else f"r37:{record_hash}"
        out[api_id] = row
    return out


def _all_rule37_rows_for_run(
    sb,
    rid: str,
    payload: dict[str, Any],
    notes: Counter[str],
) -> list[dict[str, Any]]:
    """Return all Rule 37 rows for a run (unpaginated)."""
    actions = _rule37_actions_for_run(sb, rid)
    action_details = _rule37_action_details_for_run(sb, rid)
    for col in ("reconciliation_run_id", "run_id"):
        try:
            qr = sb.table("rule37_warnings").select("*").eq(col, rid)  # type: ignore[arg-type]
            exe = qr.execute()
            chunk = exe.data or []
            if chunk:
                body = [_db_rule37_warning_to_frontend(row) for row in chunk]
                for row in body:
                    record_id = str(row.get("id") or "")
                    if record_id in actions:
                        row["rule37_action_status"] = actions[record_id]
                    detail = action_details.get(record_id, {})
                    if detail:
                        row["rule37_action_id"] = detail.get("id")
                        row["rule37_review_metadata"] = detail.get("review_metadata")
                    coverage = str(detail.get("payment_coverage") or "").strip().lower()
                    row["rule37_payment_coverage"] = (
                        coverage if coverage in {"full", "partial", "pending_review"} else None
                    )
                return body
        except Exception:
            continue
    return _build_rule37_rows(sb, rid, payload, notes)


def _rule37_pending_verification_from_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return PENDING_VERIFICATION rows from stored compliance (not the at-risk list)."""
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    dec = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    rows: list[dict[str, Any]] = []
    for src in (
        comp.get("rule37_pending_verification"),
        dec.get("rule37_pending_verification"),
    ):
        if isinstance(src, list):
            rows.extend(r for r in src if isinstance(r, dict))
    # Deduplicate by pr_id when both blobs exist.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = str(r.get("pr_id") or r.get("id") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(r)
    return out


def _rule37_coverage_from_payload(
    payload: dict[str, Any],
    *,
    run_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Payment-status coverage for ITC-claimed matched invoices.

    Prefer ``compliance.rule37_coverage`` written at reconcile time; fall back to
    run_summary scalars for older payloads that only stored summary metrics.
    """
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    cov = comp.get("rule37_coverage") if isinstance(comp.get("rule37_coverage"), dict) else {}
    rs = run_summary if isinstance(run_summary, dict) else {}

    def _int(primary: object, fallback: object) -> int | None:
        for v in (primary, fallback):
            if v is None or v == "":
                continue
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
        return None

    claimed = _int(cov.get("claimed_invoice_count"), rs.get("rule37_claimed_invoice_count"))
    known = _int(
        cov.get("payment_status_known_count"),
        rs.get("rule37_payment_status_known_count"),
    )
    unknown = _int(
        cov.get("payment_status_unknown_count"),
        rs.get("rule37_payment_status_unknown_count"),
    )
    if claimed is None and known is None and unknown is None:
        return {
            "claimed_invoice_count": 0,
            "payment_status_known_count": 0,
            "payment_status_unknown_count": 0,
            "coverage_available": False,
        }
    claimed_n = claimed if claimed is not None else (known or 0) + (unknown or 0)
    known_n = known if known is not None else 0
    unknown_n = unknown if unknown is not None else max(claimed_n - known_n, 0)
    return {
        "claimed_invoice_count": claimed_n,
        "payment_status_known_count": known_n,
        "payment_status_unknown_count": unknown_n,
        "coverage_available": True,
    }


def _rule37_pending_exposure_paise(row: dict[str, Any]) -> int:
    for key in ("potential_itc_paise", "total_tax_paise"):
        if row.get(key) is not None:
            try:
                return int(row[key])
            except (TypeError, ValueError):
                continue
    return 0


def _build_rule37_summary_payload(
    sb,
    rid: str,
    payload: dict[str, Any],
    notes: Counter[str],
    *,
    run_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _all_rule37_rows_for_run(sb, rid, payload, notes)
    row_by_id = {str(r.get("id") or ""): r for r in rows}

    # Use integer paise accumulators to avoid cumulative float rounding drift.
    # row["amount"] is already a rounded-float (rupees); instead we recover the
    # raw paise from itc_at_risk_paise when available, falling back to the
    # pre-rounded float only for DB-sourced rows that lack the paise key.
    total_exact = 0.0
    saved_exact = 0.0
    reversed_exact = 0.0
    pending_exact = 0.0
    action_details = _rule37_action_details_for_run(sb, rid)

    for row in rows:
        # Prefer raw paise (no per-row rounding); fall back to stored float.
        raw_paise = row.get("itc_at_risk_paise")
        if raw_paise is not None:
            amt_exact = _paise_to_rupees_exact(int(raw_paise))
        else:
            amt_exact = float(row.get("amount") or 0)
        total_exact += amt_exact
        row_id = str(row.get("id") or "")
        status = str(row.get("rule37_action_status") or "").strip().lower()
        detail = action_details.get(row_id, {})
        coverage = str(detail.get("payment_coverage") or "").strip().lower()
        if status == "resolved":
            if coverage == "partial":
                pending_exact += amt_exact
            else:
                saved_exact += amt_exact
        elif status == "acknowledged":
            reversed_exact += amt_exact
        else:
            pending_exact += amt_exact

    pending_verification_rows = _rule37_pending_verification_from_payload(payload)
    pending_verification_count = len(pending_verification_rows)
    pending_verification_exposure_exact = sum(
        _paise_to_rupees_exact(_rule37_pending_exposure_paise(r))
        for r in pending_verification_rows
    )
    # Fallback when payload list is empty but run_summary still has scalars
    # (e.g. older slim payloads that dropped the list but kept counts).
    rs = run_summary if isinstance(run_summary, dict) else {}
    if pending_verification_count == 0:
        try:
            rs_count = int(rs.get("rule37_pending_verification_count") or 0)
        except (TypeError, ValueError):
            rs_count = 0
        if rs_count > 0:
            pending_verification_count = rs_count
            try:
                pending_verification_exposure_exact = _paise_to_rupees_exact(
                    int(rs.get("rule37_pending_verification_paise") or 0)
                )
            except (TypeError, ValueError):
                pending_verification_exposure_exact = 0.0

    cov = _rule37_coverage_from_payload(payload, run_summary=rs)

    action_rows = _rule37_actions_history_for_run(sb, rid)
    uids = {
        str(a.get("user_id") or "").strip()
        for a in action_rows
        if a.get("user_id")
    }
    names = _followup_audit_user_names(uids)

    history: list[dict[str, Any]] = []
    for action_row in action_rows:
        record_hash = str(action_row.get("record_hash") or "").strip()
        api_id = (
            record_hash if record_hash.startswith("r37:") else f"r37:{record_hash}"
        )
        rec = row_by_id.get(api_id, {})
        action = _rule37_status_to_action(str(action_row.get("status") or ""))
        if not action:
            continue
        uid = str(action_row.get("user_id") or "").strip()
        tds = float(action_row.get("tds_deducted") or 0)
        amt_paid = action_row.get("amount_paid")
        total_settled = action_row.get("total_settled")
        remaining_unpaid = action_row.get("remaining_unpaid_amount")
        coverage = str(action_row.get("payment_coverage") or "").strip().lower()
        history.append(
            {
                "id": str(action_row.get("id") or ""),
                "invoice_number": str(rec.get("invoice_number") or ""),
                "supplier_gstin": str(rec.get("supplier_gstin") or ""),
                "amount": round(float(rec.get("amount") or 0), 2),
                "action": action,
                "created_at": str(action_row.get("created_at") or ""),
                "generated_by": uid,
                "generated_by_name": names.get(uid, ""),
                "amount_paid": (
                    round(float(amt_paid), 2) if amt_paid is not None else None
                ),
                "tds_deducted": round(tds, 2),
                "total_settled": (
                    round(float(total_settled), 2)
                    if total_settled is not None
                    else None
                ),
                "remaining_unpaid_amount": (
                    round(float(remaining_unpaid), 2)
                    if remaining_unpaid is not None
                    else None
                ),
                "payment_coverage": coverage if coverage in {"full", "partial"} else None,
            }
        )

    return {
        "summary": {
            # Round once on the accumulated sum — not per-row — to eliminate
            # cumulative drift from summing multiple round(paise/100, 2) values.
            "total_itc_at_risk": round(total_exact, 2),
            "itc_saved": round(saved_exact, 2),
            "itc_reversed": round(reversed_exact, 2),
            "pending_action": round(pending_exact, 2),
            "pending_verification_count": pending_verification_count,
            "pending_verification_exposure": round(
                pending_verification_exposure_exact, 2
            ),
            "claimed_invoice_count": int(cov["claimed_invoice_count"]),
            "payment_status_known_count": int(cov["payment_status_known_count"]),
            "payment_status_unknown_count": int(cov["payment_status_unknown_count"]),
            "coverage_available": bool(cov["coverage_available"]),
        },
        "action_history": history,
    }


def _rule37_actions_for_run(sb, run_id: str) -> dict[str, str]:
    """Return {api_record_id: status} for all Rule 37 actions on this run.

    Reads from the dedicated ``rule37_actions`` table.  The ``record_hash``
    stored there is the bare value without the ``r37:`` prefix; we re-attach
    it here so callers get the full API id back.
    """
    try:
        r = (
            sb.table("rule37_actions")
            .select("record_hash, status")
            .eq("run_id", run_id)
            .execute()
        )
    except Exception:
        _log.exception("rule37 actions read failed reconciliation_run=%s", run_id)
        return {}
    out: dict[str, str] = {}
    for row in r.data or []:
        record_hash = str(row.get("record_hash") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        if record_hash and status in {"resolved", "acknowledged", "pending_review", "rejected"}:
            api_id = record_hash if record_hash.startswith("r37:") else f"r37:{record_hash}"
            out[api_id] = status
    return out


def _decision_statuses_for_run(sb, run_id: str) -> dict[str, str]:
    if not sb:
        return {}
    rows: list[dict] = []
    for use_note_type in (True, False):
        try:
            q = (
                sb.table("mismatch_notes")
                .select("record_id, note")
                .eq("run_id", run_id)
            )
            if use_note_type:
                q = q.eq("note_type", "decision_status")
            r = q.execute()
            rows = r.data or []
            break
        except Exception as exc:
            if use_note_type and _is_schema_compat_error(exc):
                _log.warning(
                    "decision_statuses: note_type filter unavailable run_id=%s", run_id
                )
                continue
            _log.exception("decision statuses reconciliation_run=%s", run_id)
            return {}
    out: dict[str, str] = {}
    for row in rows:
        record_id = str(row.get("record_id") or "").strip()
        note = str(row.get("note") or "").strip().lower()
        if record_id and note in {"acted", "ignored", "pending"}:
            out[record_id] = note
    return out


def _upsert_decision_status(
    sb, *, run_id: str, record_id: str, status_value: str, user_id: str
) -> None:
    """Persist a decision status in ``mismatch_notes`` (schema-tolerant).

    Uses delete-then-insert (same pattern as ``_upsert_rule37_action``) to
    avoid PostgREST coercing a TEXT record_id through UUID type-checking and
    to eliminate the unprotected SELECT that previously caused unhandled 500s.

    API ids may carry a type tag (``pm:``, ``wr:``, …); strip it so the UUID
    column accepts the value.
    """
    now = datetime.now(timezone.utc).isoformat()
    db_rid = _db_record_id(record_id)

    # ── Step 1: remove any prior status row for this (run, record) pair ──
    try:
        sb.table("mismatch_notes").delete().eq("run_id", run_id).eq(
            "record_id", db_rid
        ).execute()
    except Exception:
        _log.warning(
            "decision_status delete failed (non-fatal) run_id=%s record_id=%s",
            run_id,
            db_rid,
        )

    # ── Step 2: insert the fresh status row ───────────────────────────────
    ins: dict[str, Any] = {
        "record_id": db_rid,
        "run_id": run_id,
        "user_id": user_id,
        "firm_owner_id": user_id,
        "note": status_value,
        "record_type": "pr",
        "note_type": "decision_status",
        "severity": "low",
        "created_at": now,
    }
    while True:
        try:
            sb.table("mismatch_notes").insert(ins).execute()
            invalidate_run_bucket_cache(run_id)
            return
        except Exception as exc:
            msg = str(exc)
            _log.warning(
                "decision_status insert attempt failed run_id=%s record_id=%s keys=%s err=%s",
                run_id,
                record_id,
                sorted(ins.keys()),
                msg,
            )
            removed = False
            for col in ("firm_owner_id", "note_type", "severity"):
                if col in msg and col in ins:
                    ins.pop(col, None)
                    removed = True
                    break
            if removed:
                continue
            _log.exception(
                "decision_status insert failed run_id=%s record_id=%s",
                run_id,
                record_id,
            )
            raise


def _merged_record_data(rd: Optional[dict[str, Any]], matcher: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not matcher and not rd:
        return {}
    merged: dict[str, Any] = {}
    if isinstance(rd, dict):
        merged.update(rd)
    if isinstance(matcher, dict):
        for k, v in matcher.items():
            if k == "supplier_gstin" and merged.get(k) is None:
                merged[k] = v
            elif k not in merged:
                merged[k] = v
    out: dict[str, Any] = {}
    for k, v in merged.items():
        if isinstance(v, (int, float, str)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v) if v is not None else ""
    return _enrich_reconcile_display_fields(out)


def _enrich_reconcile_display_fields(merged: dict[str, Any]) -> dict[str, Any]:
    """Map canonical paise fields to rupee keys expected by the results UI."""
    out = dict(merged)

    def set_rupees_from_paise(paise_key: str, *display_keys: str) -> None:
        if paise_key not in merged:
            return
        try:
            rupees = _paise_to_rupees(int(merged[paise_key]))
        except (TypeError, ValueError):
            return
        for dk in display_keys:
            if dk not in out or out[dk] in (None, ""):
                out[dk] = rupees

    set_rupees_from_paise(
        "taxable_amount_paise",
        "taxable_amount",
        "Taxable Amount",
        "taxable",
        "taxable_val",
    )
    set_rupees_from_paise("igst_paise", "igst", "IGST", "integrated_tax")
    set_rupees_from_paise("cgst_paise", "cgst", "CGST", "central_tax")
    set_rupees_from_paise("sgst_paise", "sgst", "SGST", "state_tax")

    sg = merged.get("supplier_gstin")
    if sg not in (None, ""):
        if not out.get("gstin"):
            out["gstin"] = sg
        if not out.get("GSTIN"):
            out["GSTIN"] = sg

    inv = merged.get("invoice_number_normalized") or merged.get("invoice_number")
    if inv not in (None, ""):
        if not out.get("invoice_number"):
            out["invoice_number"] = inv
        if not out.get("Invoice Number"):
            out["Invoice Number"] = inv

    inv_d = merged.get("invoice_date")
    if inv_d not in (None, ""):
        if not out.get("Invoice Date"):
            out["Invoice Date"] = inv_d

    return out


def _matched_ui_match_level(
    engine_row: dict[str, Any],
    match_status_display: Optional[str],
    *,
    for_matched_tab: bool = True,
) -> str:
    """Return the match_level string for UI display.

    For the Matched tab (for_matched_tab=True) the frontend MatchLevelBadge only
    accepts EXACT | FUZZY | MANUAL | UNMATCHED.  Trust engine ``match_level``:
    L1 → EXACT, L2+ → FUZZY.  Do NOT map financial match_status==MATCHED to
    EXACT — that status means amounts align, not that the invoice string was
    an exact raw match (normalized/format-variant pairs are also MATCHED).

    For the Review Required tab (for_matched_tab=False) the granular label is
    returned as-is because that tab renders it as raw text with no badge map.
    """
    if engine_row.get("is_late_filing"):
        return "MANUAL"
    lvl = engine_row.get("match_level")
    if for_matched_tab:
        if isinstance(lvl, int) and lvl == 1:
            return "EXACT"
        if isinstance(lvl, int) and lvl >= 2:
            return "FUZZY"
        # Legacy payloads missing match_level: confidence 100 was only emitted
        # by L1 (and historically by promoted normalized pairs). Keep fallback.
        if lvl is None and engine_row.get("confidence_score") == 100:
            return "EXACT"
        return "FUZZY"
    # Review Required tab: return granular label so the table cell shows the
    # specific reason (L3_AMOUNT_MISMATCH, L2_NORMALIZED, etc.).
    _LEVEL_LABEL = {
        1: "EXACT",
        2: "L2_NORMALIZED",
        3: "L3_AMOUNT_MISMATCH",
        4: "L4_VENDOR_FUZZY",
        5: "L5_TYPO_INVOICE",
    }
    if isinstance(lvl, int) and lvl in _LEVEL_LABEL:
        return _LEVEL_LABEL[lvl]
    # Phase-2 review rows (duplicate ambiguity, GSTIN mismatch, typo/vendor fuzzy,
    # amount mismatch, etc.) never populate an int match_level because they're
    # pushed without a MatchResult (see _push_review_required call-sites in
    # execute_phase2_and_3). Fall back to the actual review reason so the "Match
    # Method" column shows something truthful (e.g. "GSTIN_MISMATCH") instead of
    # a generic "FUZZY" that the frontend used to special-case for a bogus
    # discrepancy recompute.
    reason = str(engine_row.get("reason") or engine_row.get("review_reason") or "").strip()
    return reason or "FUZZY"


def _rule37_urgency_from_status(status: Optional[str]) -> Optional[str]:
    s = str(status or "").upper()
    if s == "OVERDUE_UNPAID":
        return "CRITICAL"
    if "60" in s or s == "WARNING_60_DAYS":
        return "HIGH"
    if "30" in s or s == "WARNING_30_DAYS" or s in ro.RULE37_CONCERNS:
        return "MEDIUM"
    return None


def _build_reconcile_summary(
    sb,
    *,
    run_row: dict[str, Any],
    payload: dict[str, Any],
    current_user_id: str,
    precomputed_outcome_rows: Optional[list[Any]] = None,
) -> dict[str, Any]:
    rid = str(run_row.get("id", "")).strip()
    engine = payload.get("engine") or {}

    # Derive counts from build_outcome_rows so the KPI cards agree with the
    # corrected tab contents.  Raw engine list lengths diverge when ghost rows
    # (gstr_id absent from DB) are present — empirically confirmed as 686-row
    # drift on a 4,886-record run.
    outcome_rows = (
        precomputed_outcome_rows
        if precomputed_outcome_rows is not None
        else ro.build_outcome_rows(sb, rid, payload)[0]
    )
    matched_count = sum(1 for r in outcome_rows if r.category == "matched")
    if matched_count == 0:
        rs = run_row.get("run_summary") if isinstance(run_row.get("run_summary"), dict) else {}
        stored_clean = int(rs.get("clean_matched_count") or 0)
        engine_clean = len(engine.get("matched") or [])
        fallback_matched = stored_clean or engine_clean
        if fallback_matched > 0:
            _log.warning(
                "Summary matched_count recomputed as 0 but stored=%d engine=%d; using fallback for run %s",
                stored_clean,
                engine_clean,
                rid,
            )
            matched_count = fallback_matched

    # GSTR-side KPI only: PR-anchored marker rows (id prefix "dp:") are emitted
    # for duplicate-claim groups so each conflicting PR booking is visible in
    # the Review tab, but they must NOT inflate Review Required past Total GSTR.
    # Matched + Review + Missed ITC must equal total_gstr_records.
    review_required_count = sum(
        1
        for r in outcome_rows
        if r.category == "review_required" and not str(r.id).startswith("dp:")
    )
    total_linked_count = matched_count + review_required_count

    # exact_match_count: count of matched pairs where the match method was L1
    # (identical GSTIN + invoice number + amounts — no normalisation or fuzzy logic).
    # Source of truth is match_level == 1 in the engine payload, which is preserved
    # in _MATCHED_KEYS since this fix.  For runs serialized before this fix (where
    # match_level is absent / None), fall back to confidence_score == 100 which only
    # L1 pairs emit.  Do NOT use financial match_status == "MISMATCHED" — that is a
    # discrepancy flag, not a match-method flag, and produces wildly wrong counts.
    matched_gstr_ids = {
        str(r.id)[3:]
        for r in outcome_rows
        if r.category == "matched" and str(r.id).startswith("pm:")
    }
    matched_engine_rows = engine.get("matched") or []
    exact_match_count = sum(
        1 for m in matched_engine_rows
        if isinstance(m, dict)
        and (str(m.get("gstr_id")) in matched_gstr_ids if matched_gstr_ids else True)
        and (
            m.get("match_level") == 1
            or (m.get("match_level") is None and m.get("confidence_score") == 100)
        )
    )
    exact_match_count = min(exact_match_count, matched_count)

    # Count gstr_records with a single COUNT query instead of fetching all rows.
    _cnt = (
        sb.table("gstr_records")
        .select("id", count="exact")
        .eq("run_id", rid)
        .limit(1)
        .execute()
    )
    n_g = int(_cnt.count if getattr(_cnt, "count", None) is not None else len(_cnt.data or []))
    if n_g == 0:
        rs_cnt = run_row.get("run_summary") if isinstance(run_row.get("run_summary"), dict) else {}
        n_g = int(
            rs_cnt.get("gstr_in_scope")
            or rs_cnt.get("total_gstr")
            or run_row.get("gstr_records_imported")
            or (matched_count + review_required_count + len(engine.get("missed_itc") or []))
            or 0
        )


    missed_list = engine.get("missed_itc") or []
    wr_list = engine.get("wrongful_itc_risk") or []
    matched_engine = engine.get("matched") or []
    # late_match_count reads the engine rows directly: is_late_filing is a stable
    # flag written at reconciliation time and is not subject to reclassification.
    late_match_count = sum(1 for m in matched_engine if m.get("is_late_filing"))
    missed_count = len(missed_list)
    wrongful_count = len(wr_list)

    gstr_db = ro.load_gstr_map(sb, rid)
    missed_total_rupees = _paise_to_rupees(
        ro._sum_itc_paise_with_fallback(missed_list, gstr_db)
    )
    pr_db = ro.load_pr_map(sb, rid)
    wrongful_total_rupees = sum(
        _paise_to_rupees(
            _wrongful_risk_itc_paise(
                w,
                (pr_db.get(str(w.get("id") or "").strip()) or {}).get("matcher")
                or {},
            )
        )
        for w in wr_list
    )
    wrongful_purchase_total_rupees = sum(
        _paise_to_rupees(
            _wrongful_risk_invoice_value_paise(
                w,
                (pr_db.get(str(w.get("id") or "").strip()) or {}).get("matcher")
                or {},
            )
        )
        for w in wr_list
    )
    if n_g > 0:
        match_pct = round(100.0 * matched_count / n_g, 1)
    else:
        match_pct = 0.0

    cgid = str(run_row.get("client_gstin_id") or "").strip()
    cg = (
        sb.table("client_gstins")
        .select("trade_name, gstin, assigned_to")
        .eq("id", cgid)
        .limit(1)
        .execute()
    )

    crow = (cg.data or [{}])[0]
    client_display = crow.get("trade_name") or crow.get("gstin") or ""
    assigned_to_uid = crow.get("assigned_to")
    assigned_to_name = ""
    if assigned_to_uid:
        ap = get_user_profile(str(assigned_to_uid)) or {}
        assigned_to_name = str(ap.get("full_name") or "")

    fin_uid = str(run_row.get("finalized_by") or "").strip()
    finalized_name: Optional[str] = None
    if fin_uid:
        fp = get_user_profile(fin_uid) or {}
        finalized_name = str(fp.get("full_name")) if fp.get("full_name") else None

    prof = get_user_profile(current_user_id) or {}
    user_role_literal = (
        prof.get("role").strip().lower()
        if prof.get("role")
        else "staff"
    )
    role_out: Literal["admin", "staff"] = (
        "admin" if user_role_literal == "admin" else "staff"
    )

    period = str(run_row.get("period") or "")

    client_gstin = str(crow.get("gstin") or "").strip()

    # Paise-denominated amounts for frontend cards
    missed_itc_amount_paise = int(round(missed_total_rupees * 100))
    wrongful_risk_amount_paise = int(round(wrongful_total_rupees * 100))
    purchase_value_at_risk_paise = int(round(wrongful_purchase_total_rupees * 100))

    rs = run_row.get("run_summary") if isinstance(run_row.get("run_summary"), dict) else {}
    skipped_count = int(rs.get("skipped_count") or rs.get("pr_skipped_missing_invoice_count") or 0)
    pr_skipped_detail = rs.get("pr_skipped_detail")
    if skipped_count and not pr_skipped_detail:
        pr_skipped_detail = f"{skipped_count} skipped: missing invoice number"
    status_message = run_row.get("status_message")
    if skipped_count and (
        not status_message
        or str(status_message).strip() in ("Completed", "completed", "")
    ):
        status_message = f"Completed — {pr_skipped_detail}"

    isd_count = int(rs.get("isd_count") or 0)
    impg_count = int(rs.get("impg_count") or 0)
    isd_present = bool(rs.get("isd_present")) or isd_count > 0
    impg_present = bool(rs.get("impg_present")) or impg_count > 0
    isd_impg_warning = rs.get("isd_impg_warning")
    if (isd_count > 0 or impg_count > 0) and not isd_impg_warning:
        from app.parsers.gstr2b_parser import format_isd_impg_warning

        isd_impg_warning = format_isd_impg_warning(isd_count, impg_count)

    decision_statuses = _decision_statuses_for_run(sb, rid) if sb is not None else {}
    decisions_acted_count = sum(1 for s in decision_statuses.values() if s == "acted")
    decisions_ignored_count = sum(1 for s in decision_statuses.values() if s == "ignored")
    action_needed_count = review_required_count + missed_count + wrongful_count
    decisions_pending_count = max(0, action_needed_count - decisions_acted_count - decisions_ignored_count)

    low_priority_review_count = 0
    low_priority_review_itc_paise = 0
    if review_required_count > 0:
        notes = _notes_count_for_run(sb, rid)
        rr_pairs = _cached_matched_pairs(
            sb,
            rid=rid,
            payload=payload,
            note_counts=notes,
            fetch_review_required=True,
        )
        for api_row, _ in rr_pairs:
            prio = str(api_row.get("priority") or "LOW").upper()
            status_val = str(api_row.get("decision_status") or "pending").lower()
            if prio == "LOW" and status_val != "acted":
                low_priority_review_count += 1
                low_priority_review_itc_paise += int(round(float(api_row.get("amount") or 0) * 100))

    itc_on_hold_count = sum(
        1 for r in outcome_rows if r.id.startswith("pm:") and r.category in ("rule37_warnings", "blocked_credit")
    )
    gross_matched_count = matched_count + itc_on_hold_count
    gross_match_pct = round(100.0 * gross_matched_count / n_g, 1) if n_g > 0 else 0.0

    return {
        "run_id": rid,
        "client_name": client_display,
        "client_gstin": client_gstin,
        "client_gstin_id": cgid,
        "period": period,
        "assigned_to_name": assigned_to_name,
        "status": _display_status(run_row.get("status")),
        "status_message": status_message,
        "finalized_by_name": finalized_name,
        "finalized_at": run_row.get("finalized_at"),
        "total_gstr_records": n_g,
        # Stable canonical fields consumed by the results page
        "clean_matched_count": matched_count,
        "gross_matched_count": gross_matched_count,
        "gross_match_rate_pct": gross_match_pct,
        "review_required_count": review_required_count,
        "total_linked_count": total_linked_count,
        # matched_count kept for backward compat (= clean_matched_count)
        "matched_count": matched_count,
        "mismatched_count": 0,  # deprecated: was match_status==MISMATCHED proxy, now unused
        "exact_match_count": exact_match_count,
        "missed_itc_count": missed_count,
        "missed_itc_total_amount": round(missed_total_rupees, 2),
        "wrongful_risk_count": wrongful_count,
        "wrongful_risk_total_amount": round(wrongful_total_rupees, 2),
        "wrongful_risk_purchase_total_amount": round(
            wrongful_purchase_total_rupees, 2
        ),
        # Paise fields for the frontend stat cards
        "missed_itc_amount_paise": missed_itc_amount_paise,
        "wrongful_risk_amount_paise": wrongful_risk_amount_paise,
        "purchase_value_at_risk_paise": purchase_value_at_risk_paise,
        "late_match_count": late_match_count,
        "match_rate_percent": match_pct,
        "match_rate_pct": match_pct,
        "user_role": role_out,
        "pr_skipped_count": skipped_count,
        "pr_skipped_detail": pr_skipped_detail,
        "isd_present": isd_present,
        "isd_count": isd_count,
        "impg_present": impg_present,
        "impg_count": impg_count,
        "isd_impg_warning": isd_impg_warning,
        "duplicate_entry_count": sum(
            1 for r in outcome_rows if r.category == "duplicate_entry"
        ),
        "unmatched_notes_count": sum(
            1 for r in outcome_rows if r.category == "unmatched_notes"
        ),
        "matched_notes_count": sum(
            1 for r in outcome_rows if r.category == "matched" and getattr(r, "is_credit_note", False)
        ),
        "itc_on_hold_count": itc_on_hold_count,
        "rule37a_count": sum(
            1 for r in outcome_rows if r.category == "rule37_warnings"
        ),
        "blocked_credit_count": sum(
            1 for r in outcome_rows if r.id.startswith("pm:") and r.category == "blocked_credit"
        ),
        "itc_on_hold_total_amount": round(
            sum(
                _paise_to_rupees(r.amount or 0)
                for r in outcome_rows
                if r.id.startswith("pm:") and r.category in ("rule37_warnings", "blocked_credit")
            ),
            2,
        ),
        # Statutory 3B Breakdown
        "matched_eligible_itc_amount": round(
            sum(
                _paise_to_rupees(r.amount or 0)
                for r in outcome_rows
                if r.category == "matched"
                and getattr(r, "itc_available", True)
                and not getattr(r, "is_rcm", False)
                and getattr(r, "supply_type", "") not in ("ISD", "IMPORT_GOODS")
                and not getattr(r, "is_credit_note", False)
                and str(getattr(r, "document_type", "")).upper() not in ("CREDIT_NOTE", "CREDIT NOTE", "CRN", "CN")
                and not getattr(r, "blocked_credit_flag", False)
            ),
            2,
        ),
        "isd_count": sum(1 for r in outcome_rows if getattr(r, "supply_type", "") == "ISD"),
        "isd_itc_amount": round(
            sum(
                _paise_to_rupees(r.amount or 0)
                for r in outcome_rows
                if getattr(r, "supply_type", "") == "ISD"
                and r.category == "matched"
                and getattr(r, "itc_available", True)
            ),
            2,
        ),
        "import_goods_count": sum(
            1 for r in outcome_rows
            if getattr(r, "supply_type", "") in ("IMPORT_GOODS", "IMPG", "IMPGSEZ")
            and r.category == "matched"
            and getattr(r, "itc_available", True)
        ),
        "import_goods_itc_amount": round(
            sum(
                _paise_to_rupees(r.amount or 0)
                for r in outcome_rows
                if getattr(r, "supply_type", "") in ("IMPORT_GOODS", "IMPG", "IMPGSEZ")
                and r.category == "matched"
                and getattr(r, "itc_available", True)
            ),
            2,
        ),
        "rcm_count": sum(1 for r in outcome_rows if getattr(r, "is_rcm", False)),
        "rcm_itc_amount": round(
            sum(_paise_to_rupees(r.amount or 0) for r in outcome_rows if getattr(r, "is_rcm", False) and r.category == "matched" and getattr(r, "itc_available", True)),
            2,
        ),
        "rcm_liability_amount": round(
            sum(_paise_to_rupees(r.amount or 0) for r in outcome_rows if getattr(r, "is_rcm", False)),
            2,
        ),
        "time_barred_count": sum(1 for r in outcome_rows if r.category == "time_barred_itc"),
        "time_barred_itc_amount": round(
            sum(_paise_to_rupees(r.amount or 0) for r in outcome_rows if r.category == "time_barred_itc"),
            2,
        ),
        "ineligible_itc_count": len({
            (str(r.supplier_gstin or "").strip().upper(), str(r.invoice_number or "").strip().upper())
            for r in outcome_rows
            if r.category == "blocked_credit"
            or getattr(r, "blocked_credit_flag", False)
            or getattr(r, "itc_available", True) is False
        }),
        "ineligible_itc_amount": round(
            sum(
                _paise_to_rupees(r.amount or 0)
                for r in {
                    (str(r.supplier_gstin or "").strip().upper(), str(r.invoice_number or "").strip().upper()): r
                    for r in outcome_rows
                    if r.category == "blocked_credit"
                    or getattr(r, "blocked_credit_flag", False)
                    or getattr(r, "itc_available", True) is False
                }.values()
            ),
            2,
        ),
        "decisions_acted_count": decisions_acted_count,
        "decisions_ignored_count": decisions_ignored_count,
        "decisions_pending_count": decisions_pending_count,
        # Low-priority review counts — power the Bulk Accept banner
        "low_priority_review_count": low_priority_review_count,
        "low_priority_review_itc_paise": low_priority_review_itc_paise,
    }


def _build_missed_itc_records(
    sb,
    *,
    rid: str,
    payload: dict[str, Any],
    note_counts: Counter[str],
    source_software: str,
) -> list[dict[str, Any]]:
    engine = payload.get("engine") or {}
    gstr_db = ro.load_gstr_map(sb, rid)
    decision_statuses = _decision_statuses_for_run(sb, rid)
    out = []
    for mi in engine.get("missed_itc") or []:
        gid = str(mi.get("gstr_id", "")).strip()
        cell = gstr_db.get(gid) or {}
        mt = cell.get("matcher") or {}
        rd = cell.get("record_data") if isinstance(cell.get("record_data"), dict) else {}
        amt_paise = int(mi.get("total_tax_paise") or mt.get("total_tax_paise") or 0)
        amt = _paise_to_rupees(amt_paise)
        mf_miss: list[str] = []
        sg_mi = str(mi.get("supplier_gstin") or mt.get("supplier_gstin") or "").strip()
        if sg_mi:
            mf_miss.append("gstin")
        inv_mi = str(
            mi.get("invoice_number_normalized") or mt.get("invoice_number_normalized") or ""
        ).strip()
        if inv_mi:
            mf_miss.append("invoice_number")
        id_mi = mi.get("invoice_date") or mt.get("invoice_date")
        if id_mi not in (None, ""):
            mf_miss.append("invoice_date")
        if mi.get("total_tax_paise") is not None or mt.get("total_tax_paise") is not None:
            mf_miss.append("total_tax")
        dout = generate_decision(
            "MISSED_ITC",
            confidence="MEDIUM",
            matched_fields=mf_miss,
            differed_fields=[],
            normalized_pairs=[],
            source_software=source_software,
            itc_amount=f"₹{amt:,.2f}",
        )
        row_id = f"mi:{gid}"
        gd2 = _merged_record_data(rd, mt)
        trade_name = ""
        for key in ("trade_name", "Trade Name", "supplier_name", "Supplier Name"):
            v = gd2.get(key)
            if v:
                trade_name = str(v).strip()[:200]
                break
        decision_status = _lookup_by_record_id(
            decision_statuses, row_id, "pending"
        )
        out.append(
            {
                "id": row_id,
                "supplier_gstin": str(mi.get("supplier_gstin") or mt.get("supplier_gstin") or ""),
                "trade_name": trade_name or None,
                "invoice_number": str(
                    mi.get("invoice_number_normalized")
                    or mt.get("invoice_number_normalized")
                    or ""
                ),
                "invoice_date": str(mi.get("invoice_date") or mt.get("invoice_date") or "")[:40],
                "amount": amt,
                "match_level": "UNMATCHED",
                "confidence_score": 0.0,
                "discrepancy_note": mi.get("mismatch_reason") if isinstance(mi, dict) else None,
                "decision_what": dout.what,
                "decision_why": dout.why,
                "decision_next": dout.next,
                "decision_rule": dout.rule,
                "decision_confidence": dout.confidence,
                "decision_matched_fields": list(dout.matched_fields),
                "decision_differed_fields": list(dout.differed_fields),
                "decision_normalized_pairs": [list(p) for p in dout.normalized_pairs],
                "decision_status": decision_status,
                "decision_type": None,
                "notes_count": int(_lookup_by_record_id(note_counts, row_id, 0)),
                "gstr2b_data": gd2,
                "purchase_register_data": {},
                "ims_status": str(
                    mi.get("ims_status")
                    or mt.get("ims_status")
                    or (rd.get("ims_status") if isinstance(rd, dict) else None)
                    or "no_action_taken"
                ),
            }
        )
    return out


def _build_wrongful_risk_records(
    sb,
    *,
    rid: str,
    payload: dict[str, Any],
    note_counts: Counter[str],
) -> list[dict[str, Any]]:
    engine = payload.get("engine") or {}
    pr_db = ro.load_pr_map(sb, rid)
    decision_statuses = _decision_statuses_for_run(sb, rid)
    out = []
    for w in engine.get("wrongful_itc_risk") or []:
        pid = str(w.get("id", "")).strip()
        row_id = f"wr:{pid}"
        cell = pr_db.get(pid) or {}
        mt = cell.get("matcher") or {}
        rd = cell.get("record_data") if isinstance(cell.get("record_data"), dict) else {}
        amt = _paise_to_rupees(_wrongful_risk_itc_paise(w, mt))
        mf_wr: list[str] = []
        sg_wr = str(w.get("supplier_gstin") or mt.get("supplier_gstin") or "").strip()
        if sg_wr:
            mf_wr.append("gstin")
        inv_wr = str(
            w.get("invoice_number_normalized") or mt.get("invoice_number_normalized") or ""
        ).strip()
        if inv_wr:
            mf_wr.append("invoice_number")
        id_wr = w.get("invoice_date") or mt.get("invoice_date")
        if id_wr not in (None, ""):
            mf_wr.append("invoice_date")
        tap_wr = w.get("taxable_amount_paise")
        if tap_wr is None:
            tap_wr = mt.get("taxable_amount_paise")
        if tap_wr is not None:
            mf_wr.append("taxable_amount")
        dout = generate_decision(
            "WRONGFUL_ITC",
            confidence="MEDIUM",
            matched_fields=mf_wr,
            differed_fields=[],
            normalized_pairs=[],
            supplier_gstin=str(w.get("supplier_gstin") or mt.get("supplier_gstin") or "?"),
            itc_amount=f"₹{amt:,.2f}",
        )
        gd2 = _merged_record_data(rd, mt)
        trade_name = ""
        for key in ("trade_name", "Trade Name", "supplier_name", "Supplier Name"):
            v = gd2.get(key)
            if v:
                trade_name = str(v).strip()[:200]
                break
        decision_status = _lookup_by_record_id(
            decision_statuses, row_id, "pending"
        )
        out.append(
            {
                "id": row_id,
                "supplier_gstin": str(w.get("supplier_gstin") or mt.get("supplier_gstin") or ""),
                "trade_name": trade_name or None,
                "invoice_number": str(
                    w.get("invoice_number_normalized") or mt.get("invoice_number_normalized") or ""
                ),
                "invoice_date": str(w.get("invoice_date") or mt.get("invoice_date") or "")[:40],
                "amount": amt,
                "match_level": "UNMATCHED",
                "confidence_score": 0.0,
                "discrepancy_note": None,
                "decision_what": dout.what,
                "decision_why": dout.why,
                "decision_next": dout.next,
                "decision_rule": dout.rule,
                "decision_confidence": dout.confidence,
                "decision_matched_fields": list(dout.matched_fields),
                "decision_differed_fields": list(dout.differed_fields),
                "decision_normalized_pairs": [list(p) for p in dout.normalized_pairs],
                "decision_status": decision_status,
                "decision_type": None,
                "notes_count": int(_lookup_by_record_id(note_counts, row_id, 0)),
                "gstr2b_data": {},
                "purchase_register_data": gd2,
            }
        )
    return out


def _pair_tax_diff_paise(
    gm: dict[str, Any],
    pm: dict[str, Any],
    en_row: dict[str, Any],
) -> int:
    """Return the ₹ discrepancy (paise) for a paired row's Discrepancy column.

    Used by BOTH the Review Required tab and the Matched tab so the "Discrepancy"
    figure is computed one way everywhere.

    This is always recomputed from live gm/pm matcher rows rather than trusting any
    stored value, because:
      - Stored ``taxable_diff_paise`` was absent (pre-fix runs) or 0 for Phase-2
        DUPLICATE/GSTIN_MISMATCH call-sites that didn't pass gstr_rec/pr_rec to
        ``_push_review_required``.
      - gm/pm come directly from the DB matcher projection, so taxable_amount_paise
        is always present and authoritative for both sides.

    Bug fix (Review Required): only compute an actual amount diff when BOTH sides
    are genuinely present (a real pair). One-sided review rows (e.g.
    DUPLICATE_AMBIGUITY, where a GSTR or PR record has no confirmed counterpart)
    previously fell through with the missing side treated as 0, so
    ``abs(gstr_taxable - 0)`` silently displayed the *entire* one-sided taxable
    value as a fabricated "discrepancy" for a record that has nothing to compare
    against — and for non-financial mismatches (GSTIN typo, date shift) where both
    sides exist and the amounts are actually identical, the correct answer is
    genuinely ₹0, not a raw invoice/taxable value.

    Bug fix (Matched tab): the matched path previously derived the discrepancy from
    ``orow.total_tax_diff_paise`` (a total_tax_paise-based delta). When a PR row's
    total_tax_paise projected as 0 (see pr_db_row_to_matcher_row), that delta became
    ``gstr_tax - 0`` = the full invoice tax, i.e. a fake discrepancy exactly equal
    to the row's Amount even though the pair is a clean match. Routing the Matched
    tab through this same both-sides-present computation yields ₹0 for genuine
    matches (identical taxable+tax on both sides) with no exceptions.

    Bug fix (false-negative regression): an earlier version of this function only
    diffed ``taxable_amount_paise``, falling back to ``total_tax_paise`` ONLY when
    BOTH sides' taxable values were exactly zero. That silently hid real, deliberate
    mismatches whose amount gap lives in the tax component rather than the taxable
    value (e.g. a wrong GST rate applied, or a total-amount typo that only shows up
    in total_tax_paise) — taxable_amount_paise matched on both sides, so the diff
    always resolved to ₹0 even though a genuine financial discrepancy existed. The
    discrepancy is therefore always computed against the *total invoice value*
    (taxable + total tax) on each side, which catches a real gap regardless of
    which component it lives in, while still correctly collapsing to ₹0 whenever
    both components genuinely match (byte-identical pairs, GSTIN-only or
    date-only mismatches).

    Callers on the Matched tab must pass a ``pm`` that already reflects any
    multi-line PR split (see ``_matched_pr_matcher_for_diff``). This helper
    itself stays level-agnostic and never special-cases multiline logic.
    """
    if gm and pm:
        gstr_taxable = int(gm.get("taxable_amount_paise") or 0)
        pr_taxable = int(pm.get("taxable_amount_paise") or 0)
        gstr_tax = int(gm.get("total_tax_paise") or 0)
        pr_tax = int(pm.get("total_tax_paise") or 0)
        gstr_total = gstr_taxable + gstr_tax
        pr_total = pr_taxable + pr_tax
        return abs(gstr_total - pr_total)

    if gm or pm:
        # Only one side resolved — there is no counterpart to diff against, so the
        # discrepancy is not a financial amount gap.
        return 0

    # Last resort: gm and pm are both empty (data-integrity gap). Try stored keys
    # as a best-effort fallback rather than showing nothing at all.
    raw_tdiff = (
        en_row.get("taxable_diff_paise")
        or en_row.get("tax_difference_paise")
        or en_row.get("total_tax_diff_paise")
    )
    if raw_tdiff:
        try:
            return abs(int(raw_tdiff))
        except (TypeError, ValueError):
            pass
    return 0


def _build_pr_ids_by_dup_key(
    pr_db: dict[str, Any],
) -> dict[tuple[str, str], list[str]]:
    """Index PR matcher rows by (GSTIN, normalized invoice) for multiline rediscovery."""
    from app.services.reconciliation import _dup_group_key

    out: dict[tuple[str, str], list[str]] = {}
    for pid, cell in pr_db.items():
        matcher = (cell or {}).get("matcher") or {}
        key = _dup_group_key(
            matcher.get("supplier_gstin"),
            matcher.get("invoice_number_normalized"),
        )
        if key:
            out.setdefault(key, []).append(str(pid))
    return out


def _matched_pr_matcher_for_diff(
    gm: dict[str, Any],
    pm: dict[str, Any],
    en_row: dict[str, Any],
    pr_db: dict[str, Any],
    *,
    pr_ids_by_dup_key: dict[tuple[str, str], list[str]] | None = None,
) -> dict[str, Any]:
    """Return the PR-side amounts to use for Matched-tab discrepancy.

    Clean 1:1 matches are unchanged (``pm`` as-is).

    Multi-line PR splits (one GSTR invoice booked as N tax-rate / HSN rows) are
    clean matches at the *group* level, but the persisted matched row only stores
    the primary ``pr_id``. Diffing GSTR against that one line fabricates a fake
    discrepancy equal to the sibling line(s). When — and only when —
    ``_is_multiline_pr_split`` confirms the candidate PR rows partition this
    GSTR invoice, return a synthetic matcher whose taxable/tax are the sum of
    those lines (→ ₹0).

    Safety gates (do not remove):
      * Review Required must NOT call this — a real amount mismatch must stay
        visible even if other PR rows share the invoice number.
      * True data-entry duplicates (every PR is a full-value copy) fail
        ``_is_multiline_pr_split`` (a single PR already equals GSTR), so we
        keep the primary row and correctly show ₹0 — we never sum 2× GSTR.
      * Arbitrary same-invoice siblings that do not sum to GSTR also fail the
        gate; the primary-only diff is preserved (no silent zeroing).
    """
    if not gm or not pm:
        return pm

    from app.services.reconciliation import _dup_group_key, _is_multiline_pr_split

    candidate_ids: list[str] = []
    raw_ids = en_row.get("pr_ids") if isinstance(en_row, dict) else None
    if isinstance(raw_ids, list):
        candidate_ids = [str(x) for x in raw_ids if x]

    if len(candidate_ids) < 2:
        key = _dup_group_key(
            gm.get("supplier_gstin"),
            gm.get("invoice_number_normalized"),
        )
        if key:
            if pr_ids_by_dup_key is not None:
                candidate_ids = list(pr_ids_by_dup_key.get(key) or [])
            else:
                candidate_ids = [
                    pid
                    for pid, cell in pr_db.items()
                    if _dup_group_key(
                        ((cell or {}).get("matcher") or {}).get("supplier_gstin"),
                        ((cell or {}).get("matcher") or {}).get(
                            "invoice_number_normalized"
                        ),
                    )
                    == key
                ]

    if len(candidate_ids) < 2:
        return pm

    pr_by_id: dict[str, dict[str, Any]] = {}
    for pid in candidate_ids:
        matcher = ((pr_db.get(pid) or {}).get("matcher")) or {}
        if matcher:
            pr_by_id[pid] = matcher
    if len(pr_by_id) < 2:
        return pm

    if not _is_multiline_pr_split(gm, list(pr_by_id.keys()), pr_by_id):
        return pm

    out = dict(pm)
    out["taxable_amount_paise"] = sum(
        int(m.get("taxable_amount_paise") or 0) for m in pr_by_id.values()
    )
    out["total_tax_paise"] = sum(
        int(m.get("total_tax_paise") or 0) for m in pr_by_id.values()
    )
    return out


def _classify_review_prio_fallback(en_row: Any, discrepancy_reason: str, tax_diff_paise: Optional[int]) -> str:
    from app.services.review_priority import classify_review_priority
    rec = dict(en_row) if isinstance(en_row, dict) else {}
    if discrepancy_reason:
        rec.setdefault("reason", discrepancy_reason)
    if tax_diff_paise is not None:
        rec.setdefault("taxable_diff_paise", tax_diff_paise)
    return classify_review_priority(rec)


def _build_matched_pair_records(
    sb,
    *,
    rid: str,
    payload: dict[str, Any],
    note_counts: Counter[str],
    fetch_review_required: bool = False,
    precomputed_outcome_rows: Optional[list[Any]] = None,
    decision_statuses: Optional[dict[str, str]] = None,
    include_ineligible: bool = False,
) -> list[tuple[dict[str, Any], Any]]:
    """Return list of ({api_row}, outcome_row) for pagination / filters."""
    gstr_db = ro.load_gstr_map(sb, rid)
    pr_db = ro.load_pr_map(sb, rid)
    if decision_statuses is None:
        decision_statuses = _decision_statuses_for_run(sb, rid) if sb is not None else {}

    all_outcome_rows = (
        precomputed_outcome_rows
        if precomputed_outcome_rows is not None
        else ro.build_outcome_rows(sb, rid, payload)[0]
    )

    if fetch_review_required:
        engine_matched = (
            (payload.get("engine", {}).get("duplicates") or [])
            + (payload.get("engine", {}).get("review_required") or [])
            + (payload.get("engine", {}).get("review_required_typo") or [])
        )
        oc_matched_in_order = [r for r in all_outcome_rows if r.category == "review_required"]
        if len(oc_matched_in_order) != len(engine_matched):
            _log.warning(
                "review_required outcome vs engine mismatch run=%s oc=%s engine=%s",
                rid,
                len(oc_matched_in_order),
                len(engine_matched),
            )
        oc_matched_by_gid: dict[str, Any] = {}  # unused in review_required branch
    else:
        engine_matched = payload.get("engine", {}).get("matched") or []
        # Build a gstr_id-keyed dict instead of a positional list.
        # engine["matched"] can contain ghost rows (gstr_id not in DB) that
        # build_outcome_rows silently skips, causing oc_matched_in_order[idx]
        # to return the WRONG orow for every row after the gap.
        if include_ineligible:
            oc_matched_by_gid = {
                r.id.removeprefix("pm:"): r
                for r in all_outcome_rows
                if r.id.startswith("pm:")
                and (
                    r.category in ("matched", "blocked_credit")
                    or getattr(r, "itc_available", True) is False
                    or getattr(r, "blocked_credit_flag", False)
                )
            }
        else:
            oc_matched_by_gid = {
                r.id.removeprefix("pm:"): r
                for r in all_outcome_rows
                if r.category == "matched" and r.id.startswith("pm:")
            }
        oc_matched_in_order = []  # unused in matched branch (kept for type consistency)

    # Bug-1b fix: Build a dict of decisions keyed by gstr_id.
    # The previous code used a positional index (decisions_rows[idx]) which drifts
    # out of sync whenever engine["matched"] contains ghost rows (since the engine
    # list includes them but the outcomes build process correctly skips them).
    decisions_rows = ((payload.get("decisions") or {}).get("rows")) or []
    decisions_by_gid = {
        str(dr.get("gstr_id", "")): dr
        for dr in decisions_rows if isinstance(dr, dict) and dr.get("gstr_id")
    }

    out_pairs: list[tuple[dict[str, Any], Any]] = []

    # Matched tab only: index PR rows by (GSTIN, invoice) so multi-line splits
    # can be rediscovered on already-persisted runs that stripped pr_ids.
    pr_ids_by_dup_key: dict[tuple[str, str], list[str]] | None = None
    if not fetch_review_required:
        pr_ids_by_dup_key = _build_pr_ids_by_dup_key(pr_db)

    for idx, en_row in enumerate(engine_matched):
        try:
            gid = ""
            pid = ""
            if fetch_review_required:
                if "side" in en_row:
                    side = en_row.get("side")
                    if side == "GSTR":
                        gid = str(en_row.get("gstr_id", "")).strip()
                    else:
                        pid = str(en_row.get("id", "")).strip()
                    if not gid and not pid:
                        _log.warning("Skipping REVIEW_REQUIRED pair with missing both IDs")
                        continue
                    if not en_row.get("reason"):
                        _log.warning(f"Skipping REVIEW_REQUIRED pair with missing reason: {en_row}")
                        continue
                else:
                    gid = str(en_row.get("gstr_id", "")).strip()
                    # Paired records store the PR id under "id" (set by reconciliation_task.py).
                    # Fall back to "id" when the canonical "pr_id" key is absent.
                    pid = str(en_row.get("pr_id") or en_row.get("id", "")).strip()
                    if not gid and not pid:
                        _log.warning("Skipping REVIEW_REQUIRED pair with missing both IDs")
                        continue
                rid_str = f"rr:{gid or pid}"
            else:
                gid = str(en_row.get("gstr_id", "")).strip()
                pid = str(en_row.get("pr_id", "")).strip()
                if not gid or not pid:
                    _log.warning("Skipping MATCHED pair with missing gstr_id or pr_id")
                    continue
                rid_str = f"pm:{gid}"

            gm = ((gstr_db.get(gid) or {}).get("matcher")) or {}
            grd_raw = (
                (gstr_db.get(gid) or {}).get("record_data")
                if isinstance((gstr_db.get(gid) or {}).get("record_data"), dict)
                else {}
            )
            pm = ((pr_db.get(pid) or {}).get("matcher")) or {}
            prd_raw = (
                (pr_db.get(pid) or {}).get("record_data")
                if isinstance((pr_db.get(pid) or {}).get("record_data"), dict)
                else {}
            )

            # Ensure that if the join resulted in nothing (both gm and pm are empty), we skip it
            if not gm and not pm:
                continue

            orow = (
                oc_matched_by_gid.get(gid)
                if not fetch_review_required
                else (oc_matched_in_order[idx] if idx < len(oc_matched_in_order) else None)
            )
            if not fetch_review_required and all_outcome_rows and orow is None:
                continue
            mst_disp = getattr(orow, "match_status", None)
            lvl = _matched_ui_match_level(
                dict(en_row),
                mst_disp,
                for_matched_tab=not fetch_review_required,
            )

            if fetch_review_required:
                # Prefer DB matcher tax so Amount never shows ₹0 when only the
                # slim engine row omitted total_tax_paise.
                amt_paise = int(
                    gm.get("total_tax_paise")
                    or en_row.get("total_tax_paise")
                    or pm.get("total_tax_paise")
                    or 0
                )
                amt = _paise_to_rupees(amt_paise)
            else:
                amt = _paise_to_rupees(int(gm.get("total_tax_paise") or 0))

            # Both tabs compute the Discrepancy column via _pair_tax_diff_paise.
            # Matched tab: for multi-line PR splits, pass a pm whose amounts are
            # the sum of every split line (gated by _is_multiline_pr_split) so
            # clean group-level matches show ₹0 instead of a fake sibling-sized
            # gap. Review Required never aggregates siblings — real mismatches
            # must stay visible.
            pm_for_diff = pm
            if not fetch_review_required:
                pm_for_diff = _matched_pr_matcher_for_diff(
                    gm,
                    pm,
                    en_row if isinstance(en_row, dict) else {},
                    pr_db,
                    pr_ids_by_dup_key=pr_ids_by_dup_key,
                )
            tax_diff_paise: Optional[int] = _pair_tax_diff_paise(gm, pm_for_diff, en_row)

            review_reason = str(
                (en_row.get("review_reason") if isinstance(en_row, dict) else None)
                or (en_row.get("reason") if isinstance(en_row, dict) else None)
                or ""
            ).strip()
            discrepancy_reason = str(
                (en_row.get("reason") if isinstance(en_row, dict) else None)
                or review_reason
                or ""
            ).strip()
            # GSTIN_MISMATCH with equal amounts has tax_diff=0 — surface the
            # reason so the UI shows "Gstin mismatch" instead of ₹0.00.
            if (
                fetch_review_required
                and review_reason == "GSTIN_MISMATCH"
                and not (tax_diff_paise or 0)
            ):
                discrepancy_reason = "GSTIN_MISMATCH"

            # Decision data: for matched rows, look up from the decisions_by_gid
            # map (keyed by gstr_id).  For review-required rows, the decision
            # fields are stored directly on en_row (populated by
            # populate_review_decisions in the worker).
            dm: dict[str, Any] = {}
            if fetch_review_required:
                # en_row *is* the slim_duplicates dict — decision_* keys live on it.
                dm = en_row if isinstance(en_row, dict) else {}
            else:
                dm = decisions_by_gid.get(gid) or {}


            d_what = dm.get("decision_what")
            d_why = dm.get("decision_why")
            d_next = dm.get("decision_next")

            gd2 = _merged_record_data(grd_raw, gm)
            pd2 = _merged_record_data(prd_raw, pm)

            if orow is not None:
                itc_avl = getattr(orow, "itc_available", True)
                itc_rsn_val = getattr(orow, "itc_reason", None)
            else:
                itc_avl = resolve_itc_available(gm, grd_raw)
                itc_rsn_val = resolve_itc_reason(gm, grd_raw)

            is_ineligible_row = (
                itc_avl is False
                or getattr(orow, "itc_available", True) is False
                or getattr(orow, "category", "") == "blocked_credit"
                or getattr(orow, "blocked_credit_flag", False)
                or str(pd2.get("itc_eligibility") or "").strip().upper() in ("N", "NO", "INELIGIBLE")
            )
            if is_ineligible_row and orow and getattr(orow, "decision_next", None) and "can be claimed" not in str(getattr(orow, "decision_next", "")).lower():
                final_d_what = str(getattr(orow, "decision_what", ""))
                final_d_why = str(getattr(orow, "decision_why", ""))
                final_d_next = str(getattr(orow, "decision_next", ""))
            elif is_ineligible_row:
                final_d_what = "Matched invoice, but ITC is marked ineligible/blocked"
                final_d_why = str(itc_rsn_val or getattr(orow, "itc_reason", None) or "Invoice matches in books, but is blocked under Section 17(5) or marked ineligible in GSTR-2B")
                final_d_next = "Ineligible for ITC u/s 17(5) / marked ineligible. Do not claim in Table 4(A)(5); report under Table 4(D)(2)."
            else:
                final_d_what = d_what if d_what else (str(getattr(orow, "decision_what", "")) if orow else None)
                final_d_why = d_why if d_why else (str(getattr(orow, "decision_why", "")) if orow else None)
                final_d_next = d_next if d_next else (str(getattr(orow, "decision_next", "")) if orow else None)

            api_row = {
                "id": rid_str,
                "supplier_gstin": str(en_row.get("supplier_gstin") or gm.get("supplier_gstin") or pm.get("supplier_gstin") or ""),
                "invoice_number": str(
                    en_row.get("invoice_number_normalized")
                    or gm.get("invoice_number_normalized")
                    or pm.get("invoice_number_normalized")
                    or ""
                ),
                "invoice_date": str(
                    en_row.get("invoice_date") or gm.get("invoice_date") or pm.get("invoice_date") or ""
                )[:40],
                "amount": amt,
                "match_level": lvl,
                "confidence_score": float(en_row.get("confidence_score") or 0.0),
                "discrepancy_note": en_row.get("note") if isinstance(en_row, dict) else None,
                "discrepancy_reason": discrepancy_reason,
                "tax_difference_paise": tax_diff_paise or 0,
                "supply_type": (
                    getattr(orow, "supply_type", None)
                    or en_row.get("supply_type")
                    or gm.get("supply_type")
                    or pm.get("supply_type")
                    or "REGULAR"
                ),
                "itc_available": not is_ineligible_row,
                "itc_reason": itc_rsn_val or getattr(orow, "itc_reason", None),
                "decision_what": final_d_what,
                "decision_why": final_d_why,
                "decision_next": final_d_next,
                "decision_status": _lookup_by_record_id(decision_statuses, rid_str, "pending"),
                "decision_type": None,
                "notes_count": int(_lookup_by_record_id(note_counts, rid_str, 0)),
                "gstr2b_data": gd2,
                "purchase_register_data": pd2,
                "match_confidence": en_row.get("match_confidence") if isinstance(en_row, dict) else None,
                "compared_fields": en_row.get("compared_fields") if isinstance(en_row, dict) else None,
                "decision_rule": dm.get("decision_rule"),
                "decision_confidence": dm.get("decision_confidence"),
                "decision_matched_fields": dm.get("decision_matched_fields"),
                "decision_differed_fields": dm.get("decision_differed_fields"),
                "decision_normalized_pairs": dm.get("decision_normalized_pairs"),
                "ims_status": str(
                    (en_row.get("ims_status") if isinstance(en_row, dict) else None)
                    or gm.get("ims_status")
                    or (grd_raw.get("ims_status") if isinstance(grd_raw, dict) else None)
                    or "no_action_taken"
                ),
                "auto_approved": bool(
                    isinstance(en_row, dict) and en_row.get("auto_approved")
                ),
                "itc_available": itc_avl,
                "itc_reason": itc_rsn_val,
                "priority": str(
                    en_row.get("priority")
                    or (
                        _classify_review_prio_fallback(en_row, discrepancy_reason, tax_diff_paise)
                        if fetch_review_required
                        else "LOW"
                    )
                ),
            }
            out_pairs.append((api_row, orow))
        except Exception as e:
            _log.error(f"Error building matched pair record (idx={idx}): {e}")
            continue
    if fetch_review_required:
        from app.services.review_priority import review_priority_sort_key
        out_pairs.sort(key=lambda t: review_priority_sort_key(t[0]))
    else:
        out_pairs.sort(key=lambda t: (-t[0]["amount"], t[0]["id"]))
    return out_pairs


def _filter_matched(
    pairs: list[tuple[dict[str, Any], Any]],
    *,
    search_q: Optional[str],
    match_level_filter: Optional[str],
    amount_min_val: Optional[float],
    amount_max_val: Optional[float],
    require_notes: bool,
    review_required: bool,
    section174: bool,
    ims_status_filter: Optional[str] = None,
    discrepancy_reason_filter: Optional[str] = None,
) -> list[tuple[dict[str, Any], Any]]:
    out_f: list[tuple[dict[str, Any], Any]] = []
    for api_row, orow in pairs:
        amt = float(api_row["amount"]) if api_row.get("amount") is not None else 0.0
        gstin = str(api_row.get("supplier_gstin") or "").lower()
        invn = str(api_row.get("invoice_number") or "").lower()
        lvl = str(api_row.get("match_level") or "").upper()

        if search_q:
            q = search_q.strip().lower()
            if q not in gstin and q not in invn:
                continue

        if match_level_filter:
            if lvl != match_level_filter.strip().upper():
                continue

        if amount_min_val is not None and amt < amount_min_val - 1e-9:
            continue
        if amount_max_val is not None and amt > amount_max_val + 1e-9:
            continue

        if require_notes and int(api_row.get("notes_count") or 0) < 1:
            continue

        if review_required:
            ms = (
                getattr(orow, "match_status", "")
                if orow is not None
                else str(api_row.get("_ms") or "")
            )
            if str(ms).upper() == "MATCHED":
                continue

        if section174:
            blk = (
                bool(getattr(orow, "blocked_credit_flag", False))
                if orow is not None
                else bool(api_row.get("_bc"))
            )
            if not blk:
                continue

        if ims_status_filter:
            want = ims_status_filter.strip().lower()
            got = str(api_row.get("ims_status") or "no_action_taken").strip().lower()
            if got != want:
                continue

        if discrepancy_reason_filter:
            dr = str(api_row.get("discrepancy_reason") or "").strip().upper()
            if dr != discrepancy_reason_filter.strip().upper():
                continue

        out_f.append((api_row, orow))
    return out_f


def _parse_money_query(s: Optional[str]) -> Optional[float]:
    if s is None or not str(s).strip():
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def _parse_iso_date_query(s: Optional[str]) -> Optional[date]:
    if s is None or not str(s).strip():
        return None
    raw = str(s).strip()[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _row_invoice_date_value(row: dict[str, Any]) -> Optional[date]:
    inv = row.get("invoice_date")
    if inv is None or inv == "":
        return None
    if isinstance(inv, date):
        return inv
    try:
        return date.fromisoformat(str(inv).strip()[:10])
    except ValueError:
        return None


def _filter_bucket_amount_gstin(
    rows: list[dict[str, Any]],
    *,
    amount_min_val: Optional[float],
    amount_max_val: Optional[float],
    supplier_gstin_q: Optional[str],
) -> list[dict[str, Any]]:
    gq = (supplier_gstin_q or "").strip().lower()
    out: list[dict[str, Any]] = []
    for r in rows:
        amt = float(r.get("amount") or 0)
        if amount_min_val is not None and amt < amount_min_val - 1e-9:
            continue
        if amount_max_val is not None and amt > amount_max_val + 1e-9:
            continue
        if gq:
            gstin = str(r.get("supplier_gstin") or "").lower()
            if gq not in gstin:
                continue
        out.append(r)
    return out


def _filter_itc_date_range(
    rows: list[dict[str, Any]],
    *,
    date_from: Optional[date],
    date_to: Optional[date],
) -> list[dict[str, Any]]:
    if date_from is None and date_to is None:
        return list(rows)
    out: list[dict[str, Any]] = []
    for r in rows:
        id_val = _row_invoice_date_value(r)
        if date_from is not None:
            if id_val is None or id_val < date_from:
                continue
        if date_to is not None:
            if id_val is None or id_val > date_to:
                continue
        out.append(r)
    return out


def _risk_impact_level(amount: float, max_amount: float) -> str:
    if max_amount <= 0:
        return "low"
    if amount >= max_amount * 0.5 - 1e-9:
        return "high"
    if amount >= max_amount * 0.1 - 1e-9:
        return "medium"
    return "low"


def _filter_risk_by_level(
    rows: list[dict[str, Any]],
    risk_level: Optional[str],
) -> list[dict[str, Any]]:
    lvl = (risk_level or "").strip().lower()
    if not lvl or lvl not in ("high", "medium", "low"):
        return list(rows)
    mx = max((float(r.get("amount") or 0) for r in rows), default=0.0)
    return [
        r
        for r in rows
        if _risk_impact_level(float(r.get("amount") or 0), mx) == lvl
    ]


_DEFAULT_SOURCE_SOFTWARE = "your accounting software"


def _source_software_for_run(sb, run_id: str) -> str:
    """Return detected PR source software (Tally/Busy/Excel) for a run.

    Reads ``pr_records.source_software`` when populated; otherwise falls back to
    the same default used by ITC bucket endpoints.
    """
    try:
        r = (
            sb.table("pr_records")
            .select("source_software")
            .eq("run_id", run_id)
            .limit(20)
            .execute()
        )
    except Exception:
        _log.warning(
            "source_software lookup failed reconciliation_run=%s",
            run_id,
            exc_info=True,
        )
        return _DEFAULT_SOURCE_SOFTWARE
    for row in r.data or []:
        val = str(row.get("source_software") or "").strip()
        if val:
            return val
    return _DEFAULT_SOURCE_SOFTWARE


def _assert_record_ids_in_run(sb, rid: str, record_ids: list[str]) -> None:
    wanted = {str(x).strip() for x in record_ids if str(x).strip()}
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="record_ids cannot be empty",
        )

    p = _payload_or_404(sb, rid)
    notes = _notes_count_for_run(sb, rid)
    source_software = _source_software_for_run(sb, rid)
    valid: set[str] = set()
    if any(x.startswith("mi:") for x in wanted):
        valid.update(
            str(row.get("id") or "")
            for row in _build_missed_itc_records(
                sb,
                rid=rid,
                payload=p,
                note_counts=notes,
                source_software=source_software,
            )
        )
    if any(x.startswith("wr:") for x in wanted):
        valid.update(
            str(row.get("id") or "")
            for row in _build_wrongful_risk_records(
                sb,
                rid=rid,
                payload=p,
                note_counts=notes,
            )
        )
    if any(x.startswith("pm:") for x in wanted):
        valid.update(
            str(row.get("id") or "")
            for row, _ in _build_matched_pair_records(
                sb,
                rid=rid,
                payload=p,
                note_counts=notes,
                decision_statuses={},
            )
        )
    if any(x.startswith("rr:") or x.startswith("rrp:") or x.startswith("rrg:") or x.startswith("dp:") for x in wanted):
        for row, orow in _build_matched_pair_records(
            sb,
            rid=rid,
            payload=p,
            note_counts=notes,
            fetch_review_required=True,
            decision_statuses={},
        ):
            if row.get("id"):
                valid.add(str(row.get("id")))
            if orow and getattr(orow, "id", None):
                valid.add(str(orow.id))
    if any(x.startswith("r37:") for x in wanted):
        valid.update(
            str(row.get("id") or "")
            for row in _build_rule37_rows(sb, rid, p, notes)
        )
    if any(x.startswith("s175:") or x.startswith("s175-db:") for x in wanted):
        valid.update(
            str(row.get("id") or "")
            for row in _build_section175_rows(sb, rid, p, notes)
        )

    missing = sorted(x for x in wanted if x not in valid)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"record not found in this run: {missing[0]}",
        )


def _row_supplier_name_sort_key(row: dict[str, Any]) -> str:
    """Best-effort supplier display name for A–Z sorting."""
    for key in ("trade_name", "supplier_name"):
        v = row.get(key)
        if v:
            return str(v).strip().lower()
    for blob_key in ("gstr2b_data", "purchase_register_data", "pr_data"):
        blob = row.get(blob_key)
        if not isinstance(blob, dict):
            continue
        for key in ("trade_name", "Trade Name", "supplier_name", "Supplier Name"):
            v = blob.get(key)
            if v:
                return str(v).strip().lower()
    return str(row.get("supplier_gstin") or "").lower()


def _row_confidence_sort_value(row: dict[str, Any]) -> float:
    """Lower values surface first for review (confidence_asc)."""
    cs = row.get("confidence_score")
    if cs is not None and cs != "":
        try:
            return float(cs)
        except (TypeError, ValueError):
            pass
    mc = row.get("match_confidence")
    if mc is not None and mc != "":
        try:
            v = float(mc)
            # match_confidence is often 0–1; confidence_score is typically 0–100
            return v * 100.0 if v <= 1.0 else v
        except (TypeError, ValueError):
            pass
    return 0.0


def _sort_reconcile_bucket_rows(rows: list[dict[str, Any]], sort: str) -> None:
    s = (sort or "amount_desc").strip().lower()
    if s == "priority":
        from app.services.review_priority import review_priority_sort_key

        rows.sort(key=review_priority_sort_key)
    elif s == "amount_asc":
        rows.sort(key=lambda x: (float(x.get("amount") or 0), str(x.get("id"))))
    elif s == "amount_desc":
        rows.sort(key=lambda x: (-float(x.get("amount") or 0), str(x.get("id"))))
    elif s == "supplier_name":
        rows.sort(
            key=lambda x: (_row_supplier_name_sort_key(x), str(x.get("id")))
        )
    elif s in ("invoice_date", "invoice_date_desc"):
        rows.sort(
            key=lambda x: (
                _row_invoice_date_value(x) or date.min,
                str(x.get("id")),
            ),
            reverse=True,
        )
    elif s == "invoice_date_asc":
        rows.sort(
            key=lambda x: (
                _row_invoice_date_value(x) or date.max,
                str(x.get("id")),
            )
        )
    elif s == "confidence_asc":
        rows.sort(
            key=lambda x: (_row_confidence_sort_value(x), str(x.get("id")))
        )
    elif s == "confidence_desc":
        rows.sort(
            key=lambda x: (-_row_confidence_sort_value(x), str(x.get("id")))
        )
    else:
        rows.sort(key=lambda x: (-float(x.get("amount") or 0), str(x.get("id"))))


def _build_late_match_rows(
    sb,
    *,
    rid: str,
    payload: dict[str, Any],
    gstr2b_period_label: str,
) -> list[dict[str, Any]]:
    gstr_db = ro.load_gstr_map(sb, rid)
    pr_db = ro.load_pr_map(sb, rid)
    engine_matched = payload.get("engine", {}).get("matched") or []
    out: list[dict[str, Any]] = []
    for en_row in engine_matched:
        if not en_row.get("is_late_filing"):
            continue
        gid = str(en_row.get("gstr_id", "")).strip()
        pid = str(en_row.get("pr_id", "")).strip()
        gm = ((gstr_db.get(gid) or {}).get("matcher")) or {}
        pm = ((pr_db.get(pid) or {}).get("matcher")) or {}
        orig = en_row.get("original_period")
        orig_label = ""
        if isinstance(orig, date):
            orig_label = orig.isoformat()[:7]
        elif orig is not None:
            orig_label = str(orig)[:40]
        late_m = int(en_row.get("late_months") or 0)
        supplier = str(gm.get("supplier_gstin") or pm.get("supplier_gstin") or "")
        inv = str(
            gm.get("invoice_number_normalized")
            or pm.get("invoice_number_normalized")
            or ""
        )
        out.append(
            {
                "supplier_gstin": supplier,
                "invoice_number": inv,
                "original_period": orig_label,
                "gstr2b_period": gstr2b_period_label,
                "months_late": late_m,
            }
        )
    out.sort(
        key=lambda x: (-int(x.get("months_late") or 0), x["supplier_gstin"], x["invoice_number"])
    )
    return out


def _total_pages(total: int, limit: int) -> int:
    if total <= 0 or limit <= 0:
        return 0 if total <= 0 else 1
    return math.ceil(total / limit)


def _pagination_chunk(seq: list[TSeq], page: int, limit: int) -> list[TSeq]:
    if limit <= 0:
        return []
    start = max(0, (page - 1) * limit)
    return seq[start : start + limit]


def _paginated_body(rows: list[dict[str, Any]], page: int, limit: int) -> dict[str, Any]:
    total = len(rows)
    page_items = _pagination_chunk(rows, page, limit)
    for item in page_items:
        if isinstance(item, dict):
            item.pop("_ms", None)
            item.pop("_bc", None)
    return {
        "data": page_items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": _total_pages(total, limit),
    }


def _cached_bucket_dict_rows(
    rid: str,
    bucket: str,
    builder,
) -> list[dict[str, Any]]:
    """Redis-memoize full unfiltered bucket lists (TTL); rebuild on miss.

    Uses a per-key lock so concurrent cold requests for the same bucket
    (e.g. duplicate SWR/tab fetches) share one rebuild instead of N.
    """
    key = bucket_cache_key(rid, bucket)
    cached = cache_get(key)
    if isinstance(cached, list):
        return cached
    with _bucket_build_lock(key):
        cached = cache_get(key)
        if isinstance(cached, list):
            return cached
        rows = builder()
        if isinstance(rows, list):
            cache_set(key, rows, ttl_seconds=BUCKET_CACHE_TTL_SECONDS)
        return rows


def _cached_reconcile_summary(
    sb,
    *,
    rid: str,
    run_row: dict[str, Any],
    payload: dict[str, Any],
    current_user_id: str,
) -> dict[str, Any]:
    """Redis-memoize the summary JSON so parallel tab loads share one rebuild."""
    key = bucket_cache_key(rid, "summary_v1")
    cached = cache_get(key)
    if isinstance(cached, dict) and cached.get("run_id") == rid:
        return cached
    with _bucket_build_lock(key):
        cached = cache_get(key)
        if isinstance(cached, dict) and cached.get("run_id") == rid:
            return cached
        out = _build_reconcile_summary(
            sb,
            run_row=run_row,
            payload=payload,
            current_user_id=current_user_id,
        )
        if isinstance(out, dict):
            cache_set(key, out, ttl_seconds=BUCKET_CACHE_TTL_SECONDS)
        return out


def _cached_matched_pairs(
    sb,
    *,
    rid: str,
    payload: dict[str, Any],
    note_counts: Counter[str],
    fetch_review_required: bool,
) -> list[tuple[dict[str, Any], Any]]:
    bucket = "review_required" if fetch_review_required else "matched"

    def _build() -> list[dict[str, Any]]:
        pairs = _build_matched_pair_records(
            sb,
            rid=rid,
            payload=payload,
            note_counts=note_counts,
            fetch_review_required=fetch_review_required,
        )
        rows: list[dict[str, Any]] = []
        for api_row, orow in pairs:
            row = dict(api_row)
            if orow is not None:
                row["_ms"] = getattr(orow, "match_status", None)
                row["_bc"] = bool(getattr(orow, "blocked_credit_flag", False))
            rows.append(row)
        return rows

    rows = _cached_bucket_dict_rows(rid, bucket, _build)
    return [(r, None) for r in rows]


async def _reconcile_finalize_core(
    request: Request,
    sb,
    *,
    rid: str,
    current_user: dict,
    checklist_snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    uid = str(current_user.get("id", ""))
    res = await execute_canonical_finalization(
        request,
        sb,
        rid=rid,
        current_user=current_user,
        checklist_snapshot=checklist_snapshot,
        allow_idempotent_return=True,
        required_role="admin",
    )
    return _build_reconcile_summary(
        sb, run_row=res.run_row, payload=res.payload, current_user_id=uid
    )





def _rule37_stable_id(item: dict[str, Any]) -> str:
    """Return a stable r37:<id> for a rule37 payload entry.

    Uses ``pr_id`` when present; otherwise hashes the invoice identifiers so
    the same entry produces the same id across requests. ``id(item)`` (the
    Python object memory address) is NOT stable and must not be used.
    """
    pid = str(item.get("pr_id") or "").strip()
    if pid:
        return f"r37:{pid}"
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


def _build_rule37_rows(sb, rid: str, payload: dict[str, Any], note_counts: Counter[str]) -> list[dict[str, Any]]:
    actions = _rule37_actions_for_run(sb, rid)
    dec = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    lst = []
    lst.extend(list(dec.get("rule37") or []))
    lst.extend(list(comp.get("rule37") or []))
    uniq: dict[str, dict[str, Any]] = {}
    for item in lst:
        if not isinstance(item, dict):
            continue
        stable = _rule37_stable_id(item)
        if stable in uniq:
            continue
        uniq[stable] = item

    # Also include rule37_warnings from outcome rows (e.g. Rule 37A non-filers)
    outcome_rows, _cc, _st = ro.build_outcome_rows(sb, rid, payload)
    for oc in outcome_rows:
        if oc.category == "rule37_warnings":
            row_id = oc.id
            if row_id in uniq:
                continue
            uniq[row_id] = {
                "id": row_id,
                "supplier_gstin": oc.supplier_gstin,
                "invoice_number": oc.invoice_number,
                "invoice_date": oc.invoice_date,
                "itc_at_risk_paise": oc.amount,
                "decision_what": oc.decision_what,
                "decision_why": oc.decision_why,
                "decision_next": oc.decision_next,
                "status": oc.match_status or "RULE37A",
                "rule37a_flag": oc.rule37a_flag,
            }

    out: list[dict[str, Any]] = []
    action_details = _rule37_action_details_for_run(sb, rid)
    for row_id, ru in uniq.items():
        amt = _paise_to_rupees(int(ru.get("itc_at_risk_paise") or 0))
        invoice_amt = _rule37_invoice_amount_from_item(ru)
        st = ru.get("status")
        ur = (
            "HIGH"
            if (ru.get("rule37a_flag") or st == "RULE37A")
            else _rule37_urgency_from_status(st)
        )
        action_status = actions.get(row_id)
        detail = action_details.get(row_id, {})
        coverage = str(detail.get("payment_coverage") or "").strip().lower()
        out.append(
            {
                "id": row_id,
                "supplier_gstin": str(ru.get("supplier_gstin") or ""),
                "invoice_number": str(ru.get("invoice_number") or ""),
                "invoice_date": str(ru.get("invoice_date") or "")[:40],
                "amount": amt,
                "invoice_amount": invoice_amt,
                "rule37_action_status": action_status,
                "rule37_action_id": detail.get("id"),
                "rule37_review_metadata": detail.get("review_metadata"),
                "rule37_payment_coverage": (
                    coverage if coverage in {"full", "partial", "pending_review"} else None
                ),
                "match_level": "UNMATCHED",
                "confidence_score": 0.0,
                "discrepancy_note": None,
                "decision_what": ru.get("decision_what"),
                "decision_why": ru.get("decision_why"),
                "decision_next": ru.get("decision_next"),
                "decision_status": "pending",
                "decision_type": None,
                "notes_count": int(_lookup_by_record_id(note_counts, row_id, 0)),
                "gstr2b_data": {},
                "purchase_register_data": {},
                "rule37_urgency": ur,
                "rule37a_flag": bool(ru.get("rule37a_flag") or st == "RULE37A"),
            }
        )
    out.sort(key=lambda x: (-x["amount"], x["id"]))
    return out


def _try_rule37_via_table(sb, rid: str, page: int, limit: int) -> Optional[dict[str, Any]]:
    actions = _rule37_actions_for_run(sb, rid)
    for col in ("reconciliation_run_id", "run_id"):
        try:
            off = max(0, (page - 1) * limit)
            qr = sb.table("rule37_warnings").select("*", count="exact").eq(col, rid)  # type: ignore[arg-type]
            qr = qr.range(off, off + limit - 1)
            exe = qr.execute()
            total = exe.count if getattr(exe, "count", None) is not None else len(exe.data or [])
            chunk = exe.data or []
            action_details = _rule37_action_details_for_run(sb, rid)
            body = [_db_rule37_warning_to_frontend(row) for row in chunk]
            for row in body:
                record_id = str(row.get("id") or "")
                if record_id in actions:
                    row["rule37_action_status"] = actions[record_id]
                detail = action_details.get(record_id, {})
                coverage = str(detail.get("payment_coverage") or "").strip().lower()
                row["rule37_payment_coverage"] = (
                    coverage if coverage in {"full", "partial"} else None
                )
            return {
                "data": body,
                "total": int(total),
                "page": page,
                "limit": limit,
                "total_pages": _total_pages(int(total), limit),
            }
        except Exception:
            continue
    return None


def _db_rule37_warning_to_frontend(row: dict[str, Any]) -> dict[str, Any]:
    pr_id = row.get("pr_id") or row.get("id")
    amt = row.get("itc_amount_rupees")
    try:
        ar = (
            float(amt)
            if amt is not None
            else _paise_to_rupees(int(row.get("itc_at_risk_paise") or 0))
        )
    except (TypeError, ValueError):
        ar = _paise_to_rupees(int(row.get("itc_at_risk_paise") or 0))
    rid_str = f"r37:{pr_id}"
    action_status = str(row.get("action_status") or "").strip().lower()
    if action_status not in {"resolved", "acknowledged"}:
        action_status = None
    inv_paise = int(row.get("total_invoice_value_paise") or 0)
    invoice_amt = (
        _paise_to_rupees(inv_paise) if inv_paise > 0 else round(ar, 2)
    )
    return {
        "id": rid_str,
        "supplier_gstin": str(row.get("supplier_gstin") or ""),
        "invoice_number": str(row.get("invoice_number") or ""),
        "invoice_date": str(row.get("invoice_date") or ""),
        "amount": round(ar, 2),
        "invoice_amount": invoice_amt,
        "match_level": "UNMATCHED",
        "confidence_score": 0.0,
        "discrepancy_note": None,
        "decision_what": row.get("decision_what"),
        "decision_why": row.get("decision_why"),
        "decision_next": row.get("decision_next"),
        "decision_status": "pending",
        "decision_type": None,
        "notes_count": 0,
        "gstr2b_data": {},
        "purchase_register_data": {},
        "rule37_urgency": _rule37_urgency_from_status(row.get("status")),
        "rule37_action_status": action_status,
    }


def _build_section175_rows(sb, rid: str, payload: dict[str, Any], note_counts: Counter[str]) -> list[dict[str, Any]]:
    """Build Section 17(5) export/API rows from decisions + compliance payloads.

    Decisions carry rendered WHAT/WHY/NEXT; compliance carries identity fields from
    ``check_blocked_credits``. Merge by (GSTIN, invoice) so we never emit:
      - literal ``?`` placeholders (fixed upstream in the checker/decision layer)
      - blank ``—`` decision columns from compliance-only shells
      - orphan decision rows that lost invoice_number during payload slim
    Rows that still lack both identity and decision text are excluded.
    """
    dec = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    dec_list = list(dec.get("section_17_5") or dec.get("section_175") or [])
    comp_list = list(comp.get("section_17_5") or comp.get("section_175") or [])

    def _key(item: dict[str, Any]) -> str:
        inv = str(item.get("invoice_number") or item.get("invoice_no") or "").strip()
        gst = str(item.get("supplier_gstin") or "").strip()
        return f"{gst}|{inv}"

    merged: dict[str, dict[str, Any]] = {}

    # Start with compliance (identity + hsn/category/amount), then overlay decisions.
    for item in comp_list:
        if not isinstance(item, dict):
            continue
        k = _key(item)
        if not k.strip("|"):
            continue
        merged[k] = dict(item)

    for item in dec_list:
        if not isinstance(item, dict):
            continue
        k = _key(item)
        if not k.strip("|"):
            # Decision row lost invoice_number during an older slim — try to
            # attach onto a single compliance row with the same GSTIN.
            gst = str(item.get("supplier_gstin") or "").strip()
            if gst:
                candidates = [mk for mk in merged if mk.startswith(f"{gst}|")]
                if len(candidates) == 1:
                    k = candidates[0]
                else:
                    continue
            else:
                continue
        base = merged.get(k, {})
        combined = {**base, **{kk: vv for kk, vv in item.items() if vv not in (None, "")}}
        # Prefer decision_* from the decisions payload when present.
        for dk in ("decision_what", "decision_why", "decision_next", "decision_rule"):
            if item.get(dk):
                combined[dk] = item[dk]
        merged[k] = combined

    out: list[dict[str, Any]] = []
    for k, bn in merged.items():
        gst = str(bn.get("supplier_gstin") or "").strip()
        inv = str(bn.get("invoice_number") or bn.get("invoice_no") or "").strip()
        d_what = bn.get("decision_what")
        d_why = bn.get("decision_why")
        d_next = bn.get("decision_next")
        # Exclude shells with no identity and no decision text (would render as
        # Type=Section 17(5) with "—" in every text column).
        has_identity = bool(gst or inv)
        has_decision = bool(
            (isinstance(d_what, str) and d_what.strip())
            or (isinstance(d_why, str) and d_why.strip())
            or (isinstance(d_next, str) and d_next.strip())
            or (isinstance(bn.get("reason"), str) and str(bn.get("reason")).strip())
        )
        if not has_identity or not has_decision:
            continue
        # Skip still-broken placeholder text from pre-fix payloads.
        text_blob = " ".join(str(x or "") for x in (d_what, d_why, d_next))
        if "HSN ?" in text_blob or "blocked credit: ?" in text_blob:
            # Re-render from stored hsn/category when available.
            hsn = str(bn.get("hsn_code") or "").strip()
            cat = str(bn.get("category") or bn.get("reason") or "").strip()
            if hsn and cat:
                from app.services.decision_templates import generate_decision
                dout = generate_decision("BLOCKED_CREDIT", category=cat, hsn_code=hsn)
                d_what, d_why, d_next = dout.what, dout.why, dout.next
            elif cat:
                from app.services.decision_templates import generate_decision
                dout = generate_decision("BLOCKED_CREDIT_NO_HSN", category=cat)
                d_what, d_why, d_next = dout.what, dout.why, dout.next
            else:
                continue

        row_id = f"s175:{k.replace('|', '-')[:240]}"
        cat = bn.get("category")
        raw_am = bn.get("estimated_itc_amount") if "estimated_itc_amount" in bn else bn.get("amount")
        try:
            amt = round(float(raw_am if raw_am is not None else 0.0), 2)
        except (TypeError, ValueError):
            amt = 0.0
        inv_date = bn.get("invoice_date")
        inv_date_str = ""
        if inv_date not in (None, ""):
            inv_date_str = str(inv_date)[:40]

        out.append(
            {
                "id": row_id,
                "supplier_gstin": gst,
                "invoice_number": inv,
                "invoice_date": inv_date_str,
                "amount": amt,
                "match_level": bn.get("match_status") or bn.get("match_level") or "MATCHED",
                "confidence_score": 0.0,
                "discrepancy_note": bn.get("hsn_code"),
                "decision_what": d_what,
                "decision_why": d_why,
                "decision_next": d_next,
                "decision_status": "pending",
                "decision_type": None,
                "notes_count": int(_lookup_by_record_id(note_counts, row_id, 0)),
                "gstr2b_data": {},
                "purchase_register_data": {},
                "section_17_5_category": str(cat) if cat else None,
            }
        )
    out.sort(key=lambda x: (-x["amount"], x["id"]))
    return out


def _build_itc_on_hold_records(
    sb,
    *,
    rid: str,
    payload: dict[str, Any],
    note_counts: Counter[str],
    precomputed_outcome_rows: Optional[list[Any]] = None,
) -> list[dict[str, Any]]:
    """Build list of matched pairs that are on hold (Rule 37A non-filers or Section 17(5) blocked credits)."""
    all_outcome_rows = (
        precomputed_outcome_rows
        if precomputed_outcome_rows is not None
        else ro.build_outcome_rows(sb, rid, payload)[0]
    )
    gstr_db = ro.load_gstr_map(sb, rid)
    pr_db = ro.load_pr_map(sb, rid)

    rows: list[dict[str, Any]] = []
    for r in all_outcome_rows:
        if not r.id.startswith("pm:"):
            continue
        if r.category not in ("rule37_warnings", "blocked_credit"):
            continue

        gid = r.id.removeprefix("pm:")
        gm = ((gstr_db.get(gid) or {}).get("matcher")) or {}
        grd_raw = (
            (gstr_db.get(gid) or {}).get("record_data")
            if isinstance((gstr_db.get(gid) or {}).get("record_data"), dict)
            else {}
        )
        pid = r.matched_pr_id or ""
        pm = ((pr_db.get(pid) or {}).get("matcher")) if pid else {}
        prd_raw = (
            (pr_db.get(pid) or {}).get("record_data")
            if isinstance((pr_db.get(pid) or {}).get("record_data"), dict)
            else {}
        )

        is_r37a = (
            r.category == "rule37_warnings"
            or bool(r.rule37a_flag)
            or str(r.match_status).upper() == "RULE37A"
        )
        hold_type = "RULE37A" if is_r37a else "BLOCKED_CREDIT"
        hold_reason = (
            "Supplier GSTR-3B Non-Filer (Rule 37A)"
            if is_r37a
            else (r.itc_reason or "Ineligible Credit under Section 17(5)")
        )

        gd2 = _merged_record_data(grd_raw, gm)
        pd2 = _merged_record_data(prd_raw, pm)

        amt = _paise_to_rupees(int(r.amount or 0))

        rows.append(
            {
                "id": r.id,
                "supplier_gstin": r.supplier_gstin,
                "supplier_name": r.supplier_name,
                "invoice_number": r.invoice_number,
                "invoice_date": str(r.invoice_date or "")[:40],
                "amount": amt,
                "match_level": "MATCHED",
                "confidence_score": float(r.match_confidence or 100.0),
                "discrepancy_note": None,
                "discrepancy_reason": None,
                "tax_difference_paise": r.total_tax_diff_paise or 0,
                "decision_what": r.decision_what,
                "decision_why": r.decision_why,
                "decision_next": r.decision_next,
                "decision_status": "pending",
                "decision_type": None,
                "notes_count": int(_lookup_by_record_id(note_counts, r.id, 0)),
                "gstr2b_data": gd2,
                "purchase_register_data": pd2,
                "compared_fields": r.compared_fields,
                "rule37a_flag": is_r37a,
                "blocked_credit_flag": not is_r37a,
                "itc_available": False,
                "itc_reason": r.itc_reason,
                "hold_type": hold_type,
                "hold_reason": hold_reason,
            }
        )

    rows.sort(key=lambda t: (-t["amount"], t["id"]))
    return rows


def _try_section175_via_table(sb, rid: str, page: int, limit: int) -> Optional[dict[str, Any]]:
    for tbl in ("section_17_5_flags", "section_175_warnings"):
        for col in ("reconciliation_run_id", "run_id"):
            try:
                off = max(0, (page - 1) * limit)
                qr = sb.table(tbl).select("*", count="exact").eq(col, rid)  # type: ignore[arg-type]
                exe = qr.range(off, off + limit - 1).execute()
                total = exe.count if getattr(exe, "count", None) is not None else len(exe.data or [])
                chunk = exe.data or []
                body = []
                for i, rw in enumerate(chunk):
                    gid = rw.get("gstr_record_id") or rw.get("id") or i
                    body.append(_db_section17_to_frontend(str(gid), rw))
                return {
                    "data": body,
                    "total": int(total),
                    "page": page,
                    "limit": limit,
                    "total_pages": _total_pages(int(total), limit),
                }
            except Exception:
                continue
    return None


def _db_section17_to_frontend(syn_id: str, row: dict[str, Any]) -> dict[str, Any]:
    row_id = f"s175-db:{syn_id}"
    amt = row.get("amount_rupees", 0.0)
    try:
        ar = float(amt)
    except (TypeError, ValueError):
        ar = 0.0
    return {
        "id": row_id,
        "supplier_gstin": str(row.get("supplier_gstin") or ""),
        "invoice_number": str(row.get("invoice_number") or ""),
        "invoice_date": str(row.get("invoice_date") or ""),
        "amount": round(ar, 2),
        "match_level": str(row.get("match_status") or row.get("match_level") or "UNMATCHED"),
        "confidence_score": 0.0,
        "discrepancy_note": None,
        "decision_what": row.get("decision_what"),
        "decision_why": row.get("decision_why"),
        "decision_next": row.get("decision_next"),
        "decision_status": "pending",
        "decision_type": None,
        "notes_count": 0,
        "gstr2b_data": {},
        "purchase_register_data": {},
        "section_17_5_category": str(row.get("category") or "") or None,
    }


def _excel_quote_text(val: Any) -> str:
    """Format string for CSV export so Excel treats it strictly as text.

    Prevents Excel from dropping leading zeros (e.g. '00123' -> 123) or
    converting long numbers (e.g. '2024092300012') to scientific notation (2.02E+12).
    """
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    escaped = s.replace('"', '""')
    return f'="{escaped}"'


def _csv_bytes(headers: tuple[str, ...], data_rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for ln in data_rows:
        writer.writerow(ln)
    return buf.getvalue().encode("utf-8")


_CHUNK_CLIENT_IDS = 120
# Cap payload backfills per list request so a large portfolio stays snappy.
_MATCHED_ITC_BACKFILL_CAP = 5


def _hydrate_run_list_money_fields(row_out: dict[str, Any]) -> None:
    """Prefer top-level money columns; fall back to run_summary scalars."""
    rs = row_out.get("run_summary")
    if not isinstance(rs, dict):
        return
    top_risk = row_out.get("itc_at_risk")
    if top_risk in (None, 0):
        for k in ("itc_at_risk", "missed_itc_paise"):
            v = rs.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                row_out["itc_at_risk"] = int(v)
                break
    top_wrong = row_out.get("wrongful_itc")
    if top_wrong in (None, 0):
        v = rs.get("wrongful_itc")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            row_out["wrongful_itc"] = int(v)


def _backfill_matched_itc_paise(
    sb, row_out: dict[str, Any], *, persist: bool = True
) -> None:
    """Ensure FINAL/COMPLETED runs expose matched_itc_paise for dashboard ITC Protected."""
    st = str(row_out.get("status") or "").strip().upper()
    if st not in (RunStatus.FINAL, RunStatus.COMPLETED):
        return
    rs_raw = row_out.get("run_summary")
    rs: dict[str, Any] = dict(rs_raw) if isinstance(rs_raw, dict) else {}
    existing = rs.get("matched_itc_paise")
    if isinstance(existing, (int, float)) and not isinstance(existing, bool):
        row_out["run_summary"] = rs
        return
    rid = str(row_out.get("id") or "").strip()
    if not rid:
        return
    try:
        payload = ro.load_payload(sb, rid)
        if not payload:
            return
        paise = ro.matched_itc_paise_from_payload(sb, rid, payload)
        rs["matched_itc_paise"] = int(paise)
        row_out["run_summary"] = rs
        if persist:
            sb.table("reconciliation_run").update({"run_summary": rs}).eq(
                "id", rid
            ).execute()
    except Exception:
        _log.exception("matched_itc_paise backfill failed for run %s", rid)


def _list_reconciliation_run_rows_for_clients(
    sb,
    client_ids: list[str],
    *,
    status_filter: Optional[str],
    per_chunk_cap: int,
) -> list[dict[str, Any]]:
    """Merge runs across client id chunks (PostgREST ``in`` size limits)."""
    rows_out: list[dict[str, Any]] = []
    for i in range(0, len(client_ids), _CHUNK_CLIENT_IDS):
        chunk = client_ids[i : i + _CHUNK_CLIENT_IDS]
        q = (
            sb.table("reconciliation_run")
            .select(
                "id, client_gstin_id, period, status, progress_percent, status_message, "
                "gstr_records_imported, pr_records_imported, matched_count, unmatched_count, "
                "itc_at_risk, wrongful_itc, late_itc, created_at, updated_at, "
                "processing_started_at, completed_at, run_summary, is_locked, "
                "finalized_at, finalized_by"
            )
            .in_("client_gstin_id", chunk)
        )
        raw_sf = (status_filter or "").strip()
        if raw_sf:
            norm = raw_sf.upper()
            if norm == "FAILED":
                q = q.in_("status", ["FAILED", "failed"])
            elif norm == RunStatus.PENDING:
                q = q.eq("status", RunStatus.PENDING)
            elif norm == RunStatus.PROCESSING:
                q = q.eq("status", RunStatus.PROCESSING)
            elif norm == RunStatus.COMPLETED:
                q = q.eq("status", RunStatus.COMPLETED)
            elif norm == RunStatus.FINAL:
                q = q.eq("status", RunStatus.FINAL)
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid status filter",
                )
        try:
            res = q.order("created_at", desc=True).limit(per_chunk_cap).execute()
        except Exception:
            _log.exception("list_reconciliation_run_rows chunk failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="could not load reconciliation runs",
            ) from None
        rows_out.extend(list(res.data or []))
    rows_out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows_out


@reconcile_runs_router.get("/runs")
async def list_reconcile_runs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    client_gstin_id: Optional[str] = Query(None),
    light: bool = Query(
        False,
        description="Skip matched_itc payload backfill (faster list for shells/tables).",
    ),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user.get("id", "")).strip()
    # v4: list rows hydrate money + computed display_type; light skips payload backfill
    cache_key = (
        f"cache:runs:v4:{user_id}:{status or ''}:{limit}:{client_gstin_id or ''}:"
        f"{'1' if light else '0'}"
    )
    cached_val = cache_get(cache_key)
    if cached_val is not None:
        return cached_val

    sb = get_supabase()
    accessible = list_accessible_client_gstin_ids(sb, current_user)
    if not accessible:
        return []

    per_chunk_cap = max(limit, limit * 3 // max(1, (len(accessible) + _CHUNK_CLIENT_IDS - 1) // _CHUNK_CLIENT_IDS))
    per_chunk_cap = min(1000, per_chunk_cap)

    if client_gstin_id:
        cid = _parse_uuid(client_gstin_id, "client_gstin_id")
        if cid not in accessible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not allowed for this client",
            )
        rows = _list_reconciliation_run_rows_for_clients(
            sb,
            [cid],
            status_filter=status,
            per_chunk_cap=limit,
        )[:limit]
    else:
        aid = sorted(accessible)
        rows = _list_reconciliation_run_rows_for_clients(
            sb,
            aid,
            status_filter=status,
            per_chunk_cap=per_chunk_cap,
        )[:limit]

    cids = list({str(r.get("client_gstin_id") or "") for r in rows if r.get("client_gstin_id")})
    trade_by_id: dict[str, dict[str, Any]] = {}
    if cids:
        cr = (
            sb.table("client_gstins")
            .select("id, trade_name, gstin")
            .in_("id", cids)
            .execute()
        )
        for row in cr.data or []:
            trade_by_id[str(row["id"])] = row

    finalized_ids = list(
        {
            str(r.get("finalized_by"))
            for r in rows
            if r.get("finalized_by") not in (None, "")
        }
    )
    name_by_uid: dict[str, str] = {}
    if finalized_ids:
        try:
            res_profiles = (
                sb.table("user_profiles")
                .select("id, full_name")
                .in_("id", finalized_ids)
                .execute()
            )
            for row in res_profiles.data or []:
                uid = str(row.get("id") or "").strip()
                fn = (row.get("full_name") or "").strip()
                if uid and fn:
                    name_by_uid[uid] = fn
        except Exception:
            _log.exception("Failed to batch query user profiles in list_reconcile_runs")

    out: list[dict[str, Any]] = []
    backfills = 0
    for r in rows:
        cg = str(r.get("client_gstin_id") or "")
        tn = trade_by_id.get(cg, {})
        fb = str(r.get("finalized_by") or "").strip()
        finalized_name = name_by_uid.get(fb) if fb else None
        row_out = dict(r)
        row_out["trade_name"] = tn.get("trade_name")
        row_out["client_gstin"] = tn.get("gstin")
        row_out["finalized_by_name"] = finalized_name
        row_out["display_type"] = get_display_type(row_out)
        _hydrate_run_list_money_fields(row_out)
        if not light:
            rs = row_out.get("run_summary")
            needs_matched = (
                not isinstance(rs, dict)
                or rs.get("matched_itc_paise") is None
            )
            st = str(row_out.get("status") or "").strip().upper()
            if (
                needs_matched
                and st in (RunStatus.FINAL, RunStatus.COMPLETED)
                and backfills < _MATCHED_ITC_BACKFILL_CAP
            ):
                _backfill_matched_itc_paise(sb, row_out, persist=True)
                backfills += 1
        out.append(row_out)
    cache_set(cache_key, out, ttl_seconds=30)
    return out


@reconcile_runs_router.post("/runs/{run_id}/retry")
async def retry_failed_reconcile_run(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    full = (
        sb.table("reconciliation_run")
        .select(
            "id, status, client_gstin_id, is_locked, gstr_records_imported, "
            "pr_records_imported"
        )
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not full.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    r = full.data[0]
    if bool(r.get("is_locked")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This reconciliation run is locked; matching cannot be re-run.",
        )
    st_raw = str(r.get("status") or "").strip().upper()
    st_lower = str(r.get("status") or "").strip().lower()
    if st_raw != "FAILED" and st_lower != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run is not failed (status={r.get('status')})",
        )
    gi = int(r.get("gstr_records_imported") or 0)
    pi = int(r.get("pr_records_imported") or 0)
    if gi <= 0 or pi <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot retry without imported GSTR and purchase register data",
        )
    now = datetime.now(timezone.utc).isoformat()
    upd = (
        sb.table("reconciliation_run")
        .update(
            {
                "status": "MATCHING",
                "progress_percent": 0.0,
                "status_message": "Queued for retry",
                "updated_at": now,
                "processing_started_at": None,
                "completed_at": None,
            }
        )
        .eq("id", rid)
        .in_("status", ["FAILED", "failed"])
        .execute()
    )
    if not upd.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="could not reset failed run; refresh and retry",
        )
    try:
        execute_reconciliation.delay(rid)
    except Exception as exc:
        _log.exception("Celery enqueue failed retry run_id=%s", rid)
        sb.table("reconciliation_run").update(
            {
                "status": "FAILED",
                "status_message": f"Queue rejected: {exc!s}"[:2000],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", rid).execute()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reconciliation task queue is unavailable. Try again later.",
        ) from exc
    invalidate_user_dashboard(current_user.get("id"))
    invalidate_run_bucket_cache(rid)
    return {"run_id": rid, "status": "MATCHING"}


def _safe_delete_by_eq(sb, table: str, column: str, value: str) -> None:
    """Delete rows matching column=value; ignore missing tables."""
    try:
        sb.table(table).delete().eq(column, value).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if any(
            token in msg
            for token in (
                "does not exist",
                "42p01",
                "pgrst205",
                "could not find the table",
                "relation",
            )
        ):
            _log.warning(
                "skip delete from %s (%s=%s): table unavailable: %s",
                table,
                column,
                value,
                exc,
            )
            return
        raise


def _clear_invoice_tracking_for_run(sb, rid: str) -> None:
    """Remove or re-point invoice_tracking FKs that block reconciliation_run deletes.

    ``invoice_tracking.first_seen_run_id`` / ``last_seen_run_id`` reference
    ``reconciliation_run(id)`` without ON DELETE CASCADE, so a bare parent
    delete raises PostgreSQL 23503 and surfaces as a generic 500.
    """
    rows: list[dict] = []
    try:
        for column in ("first_seen_run_id", "last_seen_run_id"):
            res = (
                sb.table("invoice_tracking")
                .select("id, first_seen_run_id, last_seen_run_id")
                .eq(column, rid)
                .execute()
            )
            rows.extend(res.data or [])
    except Exception as exc:
        msg = str(exc).lower()
        if any(
            token in msg
            for token in (
                "does not exist",
                "42p01",
                "pgrst205",
                "could not find the table",
                "relation",
            )
        ):
            _log.warning(
                "skip invoice_tracking cleanup for run %s: table unavailable: %s",
                rid,
                exc,
            )
            return
        raise

    seen_ids: set[str] = set()
    for trow in rows:
        tid = str(trow.get("id") or "")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        first = str(trow.get("first_seen_run_id") or "")
        last = str(trow.get("last_seen_run_id") or "")
        if first == rid:
            sb.table("invoice_tracking").delete().eq("id", tid).execute()
            continue
        if last == rid and first and first != rid:
            sb.table("invoice_tracking").update(
                {"last_seen_run_id": first}
            ).eq("id", tid).execute()

    # Final sweep in case any last_seen refs remain.
    _safe_delete_by_eq(sb, "invoice_tracking", "last_seen_run_id", rid)
    _safe_delete_by_eq(sb, "invoice_tracking", "first_seen_run_id", rid)


def _clear_table4_and_ledger_for_run(sb, rid: str) -> None:
    """Remove dependent GSTR-3B Table 4 snapshots, reclaim events, and reversal ledger rows.

    These tables have ON DELETE RESTRICT foreign keys referencing reconciliation_run(id)
    to protect historical finalized data, and must be cleaned up before the parent run is deleted.
    """
    # 1. Clear circular FK reconciliation_run(table4_summary_id)
    try:
        sb.table("reconciliation_run").update({"table4_summary_id": None}).eq("id", rid).execute()
    except Exception as exc:
        _log.warning("could not clear table4_summary_id on run %s: %s", rid, exc)

    # 2. Clear reclaim events referencing this run or this run's reversal ledger
    try:
        ledger_res = (
            sb.table("gstr3b_reversal_ledger")
            .select("id")
            .eq("source_run_id", rid)
            .execute()
        )
        ledger_ids = [str(r.get("id")) for r in (ledger_res.data or []) if r.get("id")]
        if ledger_ids:
            for lid in ledger_ids:
                _safe_delete_by_eq(sb, "gstr3b_reclaim_events", "ledger_id", lid)
        _safe_delete_by_eq(sb, "gstr3b_reclaim_events", "reclaim_run_id", rid)
    except Exception as exc:
        _log.warning("could not clear gstr3b_reclaim_events for run %s: %s", rid, exc)

    # 3. Clear reversal ledger entries originated by this run
    _safe_delete_by_eq(sb, "gstr3b_reversal_ledger", "source_run_id", rid)

    # 4. Clear Table 4 summaries for this run
    _safe_delete_by_eq(sb, "gstr3b_table4_summaries", "run_id", rid)


@reconcile_runs_router.delete("/runs/{run_id}")
async def delete_reconcile_run(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    uid = str(current_user.get("id", ""))
    role = await get_user_role(uid)
    if (role or "").strip().lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete reconciliation runs",
        )

    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

    try:
        full = (
            sb.table("reconciliation_run")
            .select("id, r2_key, client_gstin_id")
            .eq("id", rid)
            .limit(1)
            .execute()
        )
        if not full.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="run not found",
            )
        row = full.data[0]

        r2_keys: list[str] = []
        stored_key = row.get("r2_key")
        if stored_key:
            r2_keys.append(str(stored_key))
        client_gstin_id = str(row.get("client_gstin_id") or "").strip()
        if client_gstin_id:
            for ext in (".xlsx", ".xls", ".csv"):
                r2_keys.append(
                    f"uploads/{client_gstin_id}/{rid}/purchase_register{ext}"
                )

        # Import-wizard uploads share the same run UUID but live in a separate table.
        try:
            import_res = (
                sb.table("reconciliation_import_runs")
                .select("id, gstr2b_r2_key, pr_r2_key")
                .eq("id", rid)
                .limit(1)
                .execute()
            )
            import_row = (import_res.data or [None])[0]
            if import_row:
                for key_name in ("gstr2b_r2_key", "pr_r2_key"):
                    key_val = import_row.get(key_name)
                    if key_val:
                        r2_keys.append(str(key_val))
        except Exception as exc:
            _log.warning(
                "could not load reconciliation_import_runs for run %s: %s",
                rid,
                exc,
            )
            import_row = None

        # Prefer a single DB transaction via RPC when the migration is applied.
        used_rpc = False
        try:
            sb.rpc("delete_reconciliation_run_cascade", {"p_run_id": rid}).execute()
            used_rpc = True
            _log.info("delete_reconcile_run used RPC cascade for run_id=%s", rid)
        except Exception as rpc_exc:
            rpc_msg = str(rpc_exc).lower()
            rpc_missing = any(
                token in rpc_msg
                for token in (
                    "could not find the function",
                    "pgrst202",
                    "does not exist",
                    "42883",
                    "23503",
                    "foreign key",
                )
            )
            if not rpc_missing:
                raise
            _log.warning(
                "delete_reconciliation_run_cascade RPC unavailable or failed for run_id=%s "
                "(%s); falling back to ordered deletes",
                rid,
                rpc_exc,
            )
            # 1) Non-cascading FK blockers (Table 4 summaries, reversal ledger, reclaim events)
            _clear_table4_and_ledger_for_run(sb, rid)
            # 2) Non-cascading FK blockers (invoice_tracking)
            _clear_invoice_tracking_for_run(sb, rid)
            # 3) Tables without FK to reconciliation_run
            _safe_delete_by_eq(sb, "rule37_actions", "run_id", rid)
            if import_row:
                _safe_delete_by_eq(sb, "reconciliation_import_runs", "id", rid)
            # 4) Parent — remaining children cascade via ON DELETE CASCADE
            sb.table("reconciliation_run").delete().eq("id", rid).execute()

        # R2 cleanup is best-effort and must not roll back a successful DB delete.
        seen: set[str] = set()
        for key in r2_keys:
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                await delete_file(key)
            except Exception as exc:
                _log.warning("R2 delete failed for key %s: %s", key, exc)

        still = (
            sb.table("reconciliation_run")
            .select("id")
            .eq("id", rid)
            .limit(1)
            .execute()
        )
        if still.data:
            raise RuntimeError(
                "reconciliation_run row still present after delete "
                f"(rpc={used_rpc})"
            )

        await log_action(
            uid,
            "delete_run",
            "reconciliation_run",
            rid,
            {},
            ip_address=(request.client.host if request.client else None),
        )
        invalidate_user_dashboard(uid)
        invalidate_run_bucket_cache(rid)
        return {"message": "Run deleted successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception(
            "delete_reconcile_run failed run_id=%s user=%s: %s",
            rid,
            uid,
            exc,
        )
        print(
            f"[delete_reconcile_run] FAILED run_id={rid} user={uid}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        detail = supabase_error_message(
            exc, context="Failed to delete reconciliation run"
        )
        low = str(exc).lower()
        if "23503" in low or "foreign key" in low:
            detail = (
                "Cannot delete run: related records still reference it. "
                f"{detail}"
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


@reconcile_runs_router.get("/runs/{run_id}/summary")
async def reconcile_run_summary(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    import traceback

    rid = _parse_uuid(run_id, "run_id")
    uid = str(current_user.get("id", ""))

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        run_row = assert_run_accessible(sb, rid, current_user)
        p = ro.load_payload(sb, rid)
        if not p:
            alt = _summary_without_payload(sb, run_row, rid=rid)
            if alt is not None:
                return alt
            raw_res = (
                sb.table("reconciliation_results")
                .select("record_data, payload")
                .eq("run_id", rid)
                .limit(1)
                .execute()
            )
            _log.error(
                "RAW DB PAYLOAD CHECK for run %s: has_row=%s type(payload)=%s",
                rid,
                bool(raw_res.data),
                type(raw_res.data[0].get("payload")) if raw_res.data else "N/A",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no reconciliation payload for this run",
            )
        return _cached_reconcile_summary(
            sb,
            rid=rid,
            run_row=run_row,
            payload=p,
            current_user_id=uid,
        )

    try:
        return await _run_sync(_work)
    except HTTPException:
        raise
    except Exception as e:
        _log.error(f"Error in reconcile_run_summary: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@reconcile_runs_router.get(
    "/runs/{run_id}/confidence-summary",
    response_model=ConfidenceSummaryResponse,
)
async def reconcile_run_confidence_summary(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Aggregate high/medium/low/unmatched confidence counts for a run.

    Read-only: buckets already-stored ``match_confidence`` on outcome rows using
    the same thresholds as the per-invoice confidence badge (≥90% / ≥75%).
    """
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> ConfidenceSummaryResponse:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        # build_outcome_rows returns (rows, category_counts, money_stats)
        outcome_rows, _cc, _stats = ro.build_outcome_rows(sb, rid, p)
        return ConfidenceSummaryResponse(
            **ro.build_confidence_summary(rid, outcome_rows)
        )

    return await _run_sync(_work)


def _payload_or_404(sb, rid: str) -> dict[str, Any]:
    p = ro.load_payload(sb, rid)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no reconciliation payload for this run",
        )
    return p


_IN_PROGRESS_RUN_STATUSES = frozenset(
    {
        "MATCHING",
        "PROCESSING",
        "PENDING",
        "RUNNING",
        "IMPORTING",
        "UPLOADING",
        "READY",
        "GSTR_IMPORT_COMPLETE",
        "PURCHASE_IMPORT_COMPLETE",
    }
)


def _status_message_for_run(sb, rid: str, run_row: dict[str, Any]) -> str:
    msg = run_row.get("status_message")
    if msg is not None and str(msg).strip():
        return str(msg).strip()
    res = (
        sb.table("reconciliation_run")
        .select("status_message")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if res.data:
        return str(res.data[0].get("status_message") or "").strip()
    return ""


def _summary_without_payload(
    sb, run_row: dict[str, Any], *, rid: str
) -> Optional[dict[str, Any]]:
    """When results payload is missing, surface FAILED / in-progress instead of 404.

    Returns a summary-shaped dict the frontend can render, or None to keep the
    existing 404 for truly unknown / empty completed runs.
    """
    st = str(run_row.get("status") or "").strip().upper()
    msg = _status_message_for_run(sb, rid, run_row)
    period = str(run_row.get("period") or "")

    def _shell(*, status: str, status_message: str) -> dict[str, Any]:
        return {
            "run_id": rid,
            "client_name": "",
            "client_gstin": "",
            "client_gstin_id": str(run_row.get("client_gstin_id") or "").strip(),
            "period": period,
            "assigned_to_name": "",
            "status": status,
            "status_message": status_message,
            "finalized_by_name": None,
            "finalized_at": None,
            "total_gstr_records": 0,
            "clean_matched_count": 0,
            "review_required_count": 0,
            "total_linked_count": 0,
            "matched_count": 0,
            "mismatched_count": 0,
            "exact_match_count": 0,
            "missed_itc_count": 0,
            "missed_itc_total_amount": 0.0,
            "wrongful_risk_count": 0,
            "wrongful_risk_total_amount": 0.0,
            "wrongful_risk_purchase_total_amount": 0.0,
            "missed_itc_amount_paise": 0,
            "wrongful_risk_amount_paise": 0,
            "purchase_value_at_risk_paise": 0,
            "late_match_count": 0,
            "match_rate_percent": 0.0,
            "match_rate_pct": 0.0,
            "user_role": "staff",
        }

    if st == "FAILED":
        return _shell(
            status="FAILED",
            status_message=msg or "Reconciliation failed",
        )
    if st in _IN_PROGRESS_RUN_STATUSES:
        return _shell(
            status=st,
            status_message=msg or "Processing…",
        )
    return None


class BulkAcceptLowPriorityBody(BaseModel):
    run_id: str
    dry_run: bool = False
    """When True, only returns the count and ITC amount — no DB writes."""


class BulkAcceptLowPriorityResponse(BaseModel):
    low_priority_count: int
    low_priority_itc_paise: int
    accepted_count: int
    dry_run: bool


@reconcile_runs_router.post(
    "/records/bulk-accept-low-priority",
    response_model=BulkAcceptLowPriorityResponse,
)
async def bulk_accept_low_priority_review(
    body: BulkAcceptLowPriorityBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Accept all LOW-priority Review Required records in one click.

    LOW-priority records are minor rounding / freight / TCS amount variances
    (< ₹100 diff) that are safe for CA bulk-approval.  URGENT, HIGH, and MEDIUM
    records are never touched by this endpoint.

    Pass dry_run=True to get the count and ITC amount without committing.
    """
    rid = _parse_uuid(body.run_id, "run_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)
    if bool(run_row.get("is_locked")) or str(run_row.get("status") or "").upper() == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="locked or final runs cannot be modified",
        )
    uid = str(current_user.get("id") or "").strip()
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing user id")

    payload = _payload_or_404(sb, rid)
    notes = _notes_count_for_run(sb, rid)
    pairs = _cached_matched_pairs(
        sb,
        rid=rid,
        payload=payload,
        note_counts=notes,
        fetch_review_required=True,
    )

    # Collect all unresolved LOW-priority review_required record IDs and their ITC paise
    low_ids: list[str] = []
    low_itc_paise: int = 0
    for api_row, _ in pairs:
        prio = str(api_row.get("priority") or "LOW").upper()
        status_val = str(api_row.get("decision_status") or "pending").lower()
        if prio != "LOW":
            continue
        if status_val == "acted":
            continue
        rec_id = str(api_row.get("id") or "").strip()
        if not rec_id:
            continue
        low_ids.append(rec_id)
        low_itc_paise += int(round(float(api_row.get("amount") or 0) * 100))

    if body.dry_run or not low_ids:
        return BulkAcceptLowPriorityResponse(
            low_priority_count=len(low_ids),
            low_priority_itc_paise=low_itc_paise,
            accepted_count=0,
            dry_run=True,
        )

    # Confirm IDs actually belong to this run then bulk-mark as acted
    _assert_record_ids_in_run(sb, rid, low_ids)
    for record_id in low_ids:
        _upsert_decision_status(
            sb,
            run_id=rid,
            record_id=record_id,
            status_value="acted",
            user_id=uid,
        )

    return BulkAcceptLowPriorityResponse(
        low_priority_count=len(low_ids),
        low_priority_itc_paise=low_itc_paise,
        accepted_count=len(low_ids),
        dry_run=False,
    )


@reconcile_runs_router.patch(
    "/records/bulk-update",
    response_model=DecisionBulkUpdateResponse,
)
async def reconcile_records_bulk_update(
    body: DecisionBulkUpdateBody,
    current_user: dict = Depends(get_current_active_user),
):
    if not body.run_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="run_id is required",
        )
    rid = _parse_uuid(body.run_id, "run_id")
    ids = [str(x).strip() for x in body.record_ids if str(x).strip()]
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="record_ids cannot be empty",
        )
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)
    if bool(run_row.get("is_locked")) or str(run_row.get("status") or "").upper() == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="locked or final runs cannot be modified",
        )
    uid = str(current_user.get("id") or "").strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )
    _assert_record_ids_in_run(sb, rid, ids)
    for record_id in ids:
        _upsert_decision_status(
            sb,
            run_id=rid,
            record_id=record_id,
            status_value=body.decision_status,
            user_id=uid,
        )
    return DecisionBulkUpdateResponse(updated_count=len(ids))


@reconcile_runs_router.get("/runs/{run_id}/itc")
async def reconcile_run_itc_bucket(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    sort: str = Query("amount_desc"),
    amount_min: Optional[str] = None,
    amount_max: Optional[str] = None,
    supplier_gstin: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    ims_status: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)
        rows = _cached_bucket_dict_rows(
            rid,
            "itc",
            lambda: _build_missed_itc_records(
                sb,
                rid=rid,
                payload=p,
                note_counts=notes,
                source_software="your accounting software",
            ),
        )
        amin = _parse_money_query(amount_min)
        amax = _parse_money_query(amount_max)
        dfrom = _parse_iso_date_query(date_from)
        dto = _parse_iso_date_query(date_to)
        rows = _filter_bucket_amount_gstin(
            rows,
            amount_min_val=amin,
            amount_max_val=amax,
            supplier_gstin_q=supplier_gstin,
        )
        rows = _filter_itc_date_range(rows, date_from=dfrom, date_to=dto)
        if ims_status and str(ims_status).strip():
            want = str(ims_status).strip().lower()
            rows = [
                r
                for r in rows
                if str(r.get("ims_status") or "no_action_taken").strip().lower() == want
            ]
        _sort_reconcile_bucket_rows(rows, sort)
        return _paginated_body(rows, page, limit)

    return await _run_sync(_work)


@reconcile_runs_router.get("/runs/{run_id}/risk")
async def reconcile_run_risk_bucket(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    sort: str = Query("amount_desc"),
    amount_min: Optional[str] = None,
    amount_max: Optional[str] = None,
    supplier_gstin: Optional[str] = None,
    risk_level: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)
        rows = _cached_bucket_dict_rows(
            rid,
            "risk",
            lambda: _build_wrongful_risk_records(
                sb, rid=rid, payload=p, note_counts=notes
            ),
        )
        amin = _parse_money_query(amount_min)
        amax = _parse_money_query(amount_max)
        rows = _filter_bucket_amount_gstin(
            rows,
            amount_min_val=amin,
            amount_max_val=amax,
            supplier_gstin_q=supplier_gstin,
        )
        rows = _filter_risk_by_level(rows, risk_level)
        _sort_reconcile_bucket_rows(rows, sort)
        return _paginated_body(rows, page, limit)

    return await _run_sync(_work)


@reconcile_runs_router.post(
    "/runs/{run_id}/supplier-followup/audit",
    response_model=SupplierFollowupAuditResponse,
    status_code=status.HTTP_201_CREATED,
)
async def log_supplier_followup_audit(
    run_id: str,
    body: SupplierFollowupAuditBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Persist supplier follow-up letter audit (snapshot from client at action time)."""
    try:
        return _log_supplier_followup_audit_impl(
            run_id, body, current_user=current_user
        )
    except HTTPException:
        raise
    except Exception as exc:
        detail = supabase_error_message(
            exc, context="supplier_followup_audit failed"
        )
        _log.exception(
            "supplier_followup_audit unhandled run_id=%s detail=%s",
            run_id,
            detail,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc


def _log_supplier_followup_audit_impl(
    run_id: str,
    body: SupplierFollowupAuditBody,
    *,
    current_user: dict,
) -> SupplierFollowupAuditResponse:
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)
    uid = str(current_user.get("id") or "").strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )

    run_period = str(run_row.get("period") or "").strip()
    if body.tax_period.strip() != run_period:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tax_period does not match run",
        )

    record_ids = [str(x).strip() for x in body.record_ids if str(x).strip()]
    if not record_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="record_ids cannot be empty",
        )
    if not all(rid_item.startswith("wr:") for rid_item in record_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="follow-up audit only supports wrongful ITC (wr:) records",
        )
    _assert_wr_record_ids_in_run(sb, rid, record_ids)

    sg = body.supplier_gstin.strip().upper()
    if not sg:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="supplier_gstin is required",
        )

    snap_ids = {str(item.record_id).strip() for item in body.invoice_snapshot}
    if snap_ids != set(record_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invoice_snapshot record_ids must match record_ids",
        )
    for item in body.invoice_snapshot:
        if str(item.supplier_gstin or "").strip().upper() != sg:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invoice_snapshot supplier_gstin must match request",
            )

    template_type = body.template_type
    if len(record_ids) == 1:
        template_type = "wrongful_itc_single"
    elif len(record_ids) >= 2:
        template_type = "wrongful_itc_bulk"

    snapshot_json = [
        {
            "record_id": item.record_id,
            "supplier_gstin": item.supplier_gstin,
            "invoice_number": item.invoice_number,
            "invoice_date": item.invoice_date,
            "amount": item.amount,
            "decision_what": item.decision_what,
            "decision_why": item.decision_why,
            "decision_next": item.decision_next,
            "trade_name": item.trade_name,
        }
        for item in body.invoice_snapshot
    ]

    letter_body = (body.letter_body or "").strip()
    if not letter_body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="letter_body is required",
        )

    now = datetime.now(timezone.utc).isoformat()
    row_ins: dict[str, Any] = {
        "run_id": rid,
        "tax_period": body.tax_period.strip(),
        "supplier_gstin": sg,
        "record_ids": record_ids,
        "invoice_snapshot": snapshot_json,
        "template_type": template_type,
        "generated_by": uid,
        "status": body.status,
        "supplier_name_display": (body.supplier_name_display or "").strip() or None,
        "letter_body": letter_body,
    }
    try:
        ins = sb.table("supplier_followup_audit").insert(row_ins).execute()
    except HTTPException:
        raise
    except Exception as exc:
        detail = supabase_error_message(
            exc, context="supplier_followup_audit insert failed"
        )
        _log.exception(
            "supplier_followup_audit insert failed run_id=%s detail=%s",
            rid,
            detail,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc
    if not ins.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to record follow-up audit",
        )
    out = ins.data[0]
    return SupplierFollowupAuditResponse(
        id=str(out.get("id") or ""),
        status=str(out.get("status") or body.status),
        generated_at=str(out.get("generated_at") or now),
    )


@reconcile_runs_router.get(
    "/runs/{run_id}/supplier-followup/audit",
    response_model=list[SupplierFollowupAuditListItem],
)
async def list_run_supplier_followup_audit(
    run_id: str,
    status: Optional[str] = Query(None),
    supplier_gstin: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    st = _parse_followup_audit_status_filter(status)
    sg = (supplier_gstin or "").strip().upper() or None
    rows = _followup_audit_query(
        sb, run_id=rid, status=st, supplier_gstin=sg
    )
    return _followup_audit_list_response(rows)


@reconcile_runs_router.get(
    "/clients/{client_gstin_id}/supplier-followup/audit",
    response_model=list[SupplierFollowupAuditListItem],
)
async def list_client_supplier_followup_audit(
    client_gstin_id: str,
    status: Optional[str] = Query(None),
    tax_period: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_gstin_id, "client_gstin_id")
    sb = get_supabase()
    accessible = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )
    st = _parse_followup_audit_status_filter(status)
    tp = (tax_period or "").strip() or None
    runs_res = (
        sb.table("reconciliation_run")
        .select("id")
        .eq("client_gstin_id", cid)
        .execute()
    )
    run_ids = [str(r.get("id") or "") for r in (runs_res.data or []) if r.get("id")]
    rows = _followup_audit_query(
        sb, run_ids=run_ids, status=st, tax_period=tp
    )
    return _followup_audit_list_response(rows)


@reconcile_runs_router.get(
    "/clients/{client_gstin_id}/supplier-followup/audit/export",
)
async def export_client_supplier_followup_audit(
    client_gstin_id: str,
    status: Optional[str] = Query(None),
    tax_period: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_active_user),
):
    cid = _parse_uuid(client_gstin_id, "client_gstin_id")
    sb = get_supabase()
    accessible = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )
    st = _parse_followup_audit_status_filter(status)
    tp = (tax_period or "").strip() or None
    cg_res = (
        sb.table("client_gstins")
        .select("gstin")
        .eq("id", cid)
        .limit(1)
        .execute()
    )
    if not cg_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client not found",
        )
    client_gstin = str(cg_res.data[0].get("gstin") or "").strip()
    runs_res = (
        sb.table("reconciliation_run")
        .select("id")
        .eq("client_gstin_id", cid)
        .execute()
    )
    run_ids = [str(r.get("id") or "") for r in (runs_res.data or []) if r.get("id")]
    rows = _followup_audit_query(
        sb, run_ids=run_ids, status=st, tax_period=tp
    )
    items = _followup_audit_list_response(rows)
    blob, fn = build_followup_history_xlsx_bytes(
        [x.model_dump() for x in items],
        client_gstin=client_gstin,
        include_tax_period=True,
    )
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@reconcile_runs_router.get("/clients/{client_gstin_id}/gstr9c-itc-fy")
async def get_gstr9c_itc_fy_rollup(
    client_gstin_id: str,
    fy: Optional[str] = Query(
        None,
        description="Indian financial year as YYYY-YY (e.g. 2025-26). Defaults to current FY.",
    ),
    current_user: dict = Depends(get_current_active_user),
):
    """Annual ITC rollup for GSTR-9C (practical internal view, not official Table 8)."""
    cid = _parse_uuid(client_gstin_id, "client_gstin_id")
    sb = get_supabase()
    accessible = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )
    fy_raw = (fy or "").strip() or default_fy_label()
    try:
        parse_fy_label(fy_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    try:
        return build_gstr9c_itc_fy_rollup(sb, client_gstin_id=cid, fy=fy_raw)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        _log.exception("GSTR-9C FY rollup failed for client=%s fy=%s", cid, fy_raw)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to generate GSTR-9C FY rollup: {str(exc)}",
        ) from exc


@reconcile_runs_router.patch(
    "/runs/{run_id}/risk/{record_id}",
    response_model=DecisionStatusResponse,
)
async def reconcile_run_risk_status(
    run_id: str,
    record_id: str,
    body: DecisionStatusPatch,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    rec_id = str(record_id).strip()
    new_status = body.status or body.decision_status
    if new_status is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status is required",
        )
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)
    if bool(run_row.get("is_locked")) or str(run_row.get("status") or "").upper() == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="locked or final runs cannot be modified",
        )
    uid = str(current_user.get("id") or "").strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )
    _assert_record_ids_in_run(sb, rid, [rec_id])
    _upsert_decision_status(
        sb,
        run_id=rid,
        record_id=rec_id,
        status_value=new_status,
        user_id=uid,
    )
    return DecisionStatusResponse(id=rec_id, status=new_status)


@reconcile_runs_router.get("/runs/{run_id}/late-matches")
async def reconcile_run_late_matches(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        period_res = (
            sb.table("reconciliation_run")
            .select("period")
            .eq("id", rid)
            .limit(1)
            .execute()
        )
        period_label = ""
        if period_res.data:
            period_label = str((period_res.data[0] or {}).get("period") or "")
        rows = _build_late_match_rows(
            sb, rid=rid, payload=p, gstr2b_period_label=period_label
        )
        return {"data": rows, "total": len(rows)}

    return await _run_sync(_work)


@reconcile_runs_router.get("/runs/{run_id}/matched")
async def reconcile_run_matched_bucket(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    sort: str = Query("amount_desc"),
    search: Optional[str] = None,
    match_level: Optional[str] = None,
    has_notes: Optional[str] = None,
    review_required: Optional[str] = None,
    section_17_5: Optional[str] = None,
    amount_min: Optional[str] = None,
    amount_max: Optional[str] = None,
    ims_status: Optional[str] = None,
    reason: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)

        def _parse_money(s: Optional[str]) -> Optional[float]:
            if s is None or not str(s).strip():
                return None
            try:
                return float(str(s).replace(",", "").strip())
            except ValueError:
                return None

        rr_req = bool(
            review_required
            and review_required.strip().lower() in ("true", "1", "yes", "review_required")
        )
        pairs = _cached_matched_pairs(
            sb,
            rid=rid,
            payload=p,
            note_counts=notes,
            fetch_review_required=rr_req,
        )
        hn = bool(has_notes and has_notes.strip().lower() in ("true", "1", "yes"))
        s174 = bool(
            section_17_5 and section_17_5.strip().lower() in ("true", "1", "yes")
        )
        filtered_pairs = _filter_matched(
            pairs,
            search_q=search,
            match_level_filter=match_level,
            amount_min_val=_parse_money(amount_min),
            amount_max_val=_parse_money(amount_max),
            require_notes=hn,
            review_required=rr_req,
            section174=s174,
            ims_status_filter=ims_status,
            discrepancy_reason_filter=reason,
        )
        extracted = [pair[0] for pair in filtered_pairs]
        _sort_reconcile_bucket_rows(extracted, sort)
        return _paginated_body(extracted, page, limit)

    return await _run_sync(_work)


@reconcile_runs_router.get(
    "/runs/{run_id}/rule37/summary",
    response_model=Rule37SummaryResponse,
)
async def reconcile_run_rule37_summary(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> Rule37SummaryResponse:
        sb = get_supabase()
        run_row = assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)
        rs = run_row.get("run_summary") if isinstance(run_row, dict) else None
        if not isinstance(rs, dict):
            rs = None
        body = _build_rule37_summary_payload(sb, rid, p, notes, run_summary=rs)
        return Rule37SummaryResponse(**body)

    return await _run_sync(_work)


@reconcile_runs_router.get("/runs/{run_id}/rule37")
async def reconcile_run_rule37(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        via = _try_rule37_via_table(sb, rid, page, limit)
        if via is not None:
            return via
        notes = _notes_count_for_run(sb, rid)
        rows = _cached_bucket_dict_rows(
            rid,
            "rule37",
            lambda: _build_rule37_rows(sb, rid, p, notes),
        )
        return _paginated_body(rows, page, limit)

    return await _run_sync(_work)


@reconcile_runs_router.patch(
    "/runs/{run_id}/rule37/{record_id}",
    response_model=Rule37ActionResponse,
)
async def reconcile_run_rule37_action(
    run_id: str,
    record_id: str,
    body: Rule37ActionPatch,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    rec_id = _normalize_record_id(record_id)
    if not rec_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing record_id",
        )
    try:
        sb = get_supabase()
        run_row = assert_run_accessible(sb, rid, current_user)
        if bool(run_row.get("is_locked")) or str(run_row.get("status") or "").upper() == RunStatus.FINAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="locked or final runs cannot be modified",
            )

        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)

        if not _rule37_record_exists_in_run(sb, rid, rec_id, p, notes):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="rule37 record not found",
            )

        uid = str(current_user.get("id") or "").strip()
        if not uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing user id",
            )

        amount_paid: Optional[float] = None
        tds_deducted = 0.0
        tds_confirmed = False
        total_settled: Optional[float] = None
        remaining_unpaid_amount: Optional[float] = None
        payment_coverage: Optional[str] = None

        if body.status == "resolved":
            if body.amount_paid is None or float(body.amount_paid) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="amount_paid is required for mark as settled",
                )
            tds_deducted = round(float(body.tds_deducted or 0), 2)
            if tds_deducted < 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="tds_deducted cannot be negative",
                )
            if not body.tds_confirmed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="settlement confirmation is required",
                )
            amount_paid = round(float(body.amount_paid), 2)
            computed_total_settled = round(amount_paid + tds_deducted, 2)
            if body.total_settled is not None:
                total_settled = round(float(body.total_settled), 2)
                if abs(total_settled - computed_total_settled) > 0.005:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            "total_settled must equal net paid plus statutory deduction"
                        ),
                    )
            else:
                total_settled = computed_total_settled
            invoice_amount = 0.0
            for row in _build_rule37_rows(sb, rid, p, notes):
                if _normalize_record_id(str(row.get("id") or "")) == rec_id:
                    invoice_amount = float(row.get("invoice_amount") or 0)
                    break
            if invoice_amount > 0 and total_settled > invoice_amount + 0.005:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "settlement exceeds invoice amount; check whether net paid "
                        "is net of TDS/statutory deduction"
                    ),
                )
            remaining_unpaid_amount = round(
                max(invoice_amount - total_settled, 0.0), 2
            )
            payment_coverage = _rule37_payment_coverage(total_settled, invoice_amount)
            tds_confirmed = bool(body.tds_confirmed)

        _upsert_rule37_action(
            sb,
            run_id=rid,
            record_id=rec_id,
            status_value=body.status,
            user_id=uid,
            amount_paid=amount_paid,
            tds_deducted=tds_deducted,
            tds_confirmed=tds_confirmed,
            total_settled=total_settled,
            remaining_unpaid_amount=remaining_unpaid_amount,
            payment_coverage=payment_coverage,
        )
        now = datetime.now(timezone.utc).isoformat()
        cov_out: Optional[Literal["full", "partial"]] = None
        if payment_coverage in {"full", "partial"}:
            cov_out = payment_coverage  # type: ignore[assignment]
        invalidate_run_bucket_cache(rid)
        return Rule37ActionResponse(
            id=rec_id,
            status=body.status,
            acted_by=uid,
            acted_at=now,
            amount_paid=amount_paid,
            tds_deducted=tds_deducted,
            tds_confirmed=tds_confirmed,
            total_settled=total_settled,
            remaining_unpaid_amount=remaining_unpaid_amount,
            payment_coverage=cov_out,
        )
    except HTTPException:
        raise
    except Exception as exc:
        import traceback

        print("rule37 PATCH error:", str(exc))
        traceback.print_exc()
        _log.exception(
            "rule37 PATCH failed run_id=%s record_id=%s raw_record_id=%s status=%s "
            "amount_paid=%s tds_deducted=%s tds_confirmed=%s total_settled=%s",
            run_id,
            rec_id,
            record_id,
            body.status,
            body.amount_paid,
            body.tds_deducted,
            body.tds_confirmed,
            body.total_settled,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=supabase_error_message(
                exc, context="failed to update rule37 status"
            ),
        ) from exc


@reconcile_runs_router.get("/runs/{run_id}/section17")
async def reconcile_run_section175(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        via = _try_section175_via_table(sb, rid, page, limit)
        if via is not None:
            return via
        notes = _notes_count_for_run(sb, rid)
        rows = _cached_bucket_dict_rows(
            rid,
            "section17",
            lambda: _build_section175_rows(sb, rid, p, notes),
        )
        return _paginated_body(rows, page, limit)

    return await _run_sync(_work)


@reconcile_runs_router.get("/runs/{run_id}/itc-on-hold")
async def reconcile_run_itc_on_hold(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    sort: str = Query("amount_desc"),
    search: Optional[str] = None,
    hold_type: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)
        rows = _cached_bucket_dict_rows(
            rid,
            "itc_on_hold",
            lambda: _build_itc_on_hold_records(sb, rid=rid, payload=p, note_counts=notes),
        )
        filtered = []
        for row in rows:
            if hold_type and str(row.get("hold_type") or "").upper() != hold_type.strip().upper():
                continue
            if search:
                q = search.strip().lower()
                inv = str(row.get("invoice_number") or "").lower()
                gst = str(row.get("supplier_gstin") or "").lower()
                name = str(row.get("supplier_name") or "").lower()
                if q not in inv and q not in gst and q not in name:
                    continue
            filtered.append(row)
        _sort_reconcile_bucket_rows(filtered, sort)
        return _paginated_body(filtered, page, limit)

    return await _run_sync(_work)


@reconcile_runs_router.get("/runs/{run_id}/rcm-tie-out")
async def reconcile_run_rcm_tie_out(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Return RCM three-way tie-out reconciliation result for a run."""
    from app.filing.gstr3b_rcm_extractor import extract_gstr3b_rcm_data
    from app.reconciliation.rcm_reconciliation import reconcile_rcm_three_way

    rid = _parse_uuid(run_id, "run_id")

    def _work() -> dict[str, Any]:
        sb = get_supabase()
        run_row = assert_run_accessible(sb, rid, current_user)

        # Load PR records and unwrap outcome dicts
        pr_map = ro.load_pr_map(sb, rid)
        pr_records = []
        if pr_map:
            for item in pr_map.values():
                if isinstance(item, dict):
                    rec = dict(item.get("record_data") or {})
                    rec.update(item.get("matcher") or {})
                    for k, v in item.items():
                        if k not in ("matcher", "record_data") and k not in rec:
                            rec[k] = v
                    pr_records.append(rec)
                else:
                    pr_records.append(item)

        # Resolve client GSTIN
        client_gstin = str(run_row.get("client_gstin") or "")
        if not client_gstin and run_row.get("client_id"):
            try:
                c_res = sb.table("clients").select("gstin").eq("id", run_row["client_id"]).limit(1).execute()
                if c_res.data:
                    client_gstin = str(c_res.data[0].get("gstin") or "")
            except Exception as exc:
                _log.debug("Could not fetch client GSTIN for RCM tie-out: %s", exc)

        # Load GSTR-3B data (from gstr3b_reconciliation or payload)
        g3b_raw = None
        try:
            res = (
                sb.table("gstr3b_reconciliation")
                .select("raw_gstr3b")
                .eq("run_id", rid)
                .order("uploaded_at", desc=True)
                .limit(1)
                .execute()
            )
            if res.data and res.data[0].get("raw_gstr3b"):
                g3b_raw = res.data[0]["raw_gstr3b"]
        except Exception as exc:
            _log.debug("No gstr3b_reconciliation entry for run %s: %s", rid, exc)

        if not g3b_raw:
            p = ro.load_payload(sb, rid)
            g3b_raw = p.get("gstr3b") or p.get("raw_gstr3b") or {
                "gstin": client_gstin or str(p.get("gstin") or ""),
                "ret_period": str(run_row.get("period") or p.get("period") or ""),
            }

        g3b_extracted = extract_gstr3b_rcm_data(g3b_raw)
        tie_out = reconcile_rcm_three_way(
            pr_records=pr_records,
            gstr3b_rcm_data=g3b_extracted,
        )
        return tie_out.summary_dict()

    return await _run_sync(_work)


class ReconcileFinalizeBody(BaseModel):
    checklist_snapshot: Optional[dict[str, Any]] = None


@reconcile_runs_router.post("/runs/{run_id}/finalize")
async def reconcile_finalize_run_api(
    request: Request,
    run_id: str,
    body: ReconcileFinalizeBody = Body(default_factory=ReconcileFinalizeBody),
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    res = await _reconcile_finalize_core(
        request,
        sb,
        rid=rid,
        current_user=current_user,
        checklist_snapshot=body.checklist_snapshot,
    )
    invalidate_user_dashboard(current_user.get("id"))
    return res


def _csv_missed_bytes(rows: list[dict[str, Any]], rid: str) -> tuple[bytes, str]:
    hdr = (
        "Supplier GSTIN",
        "Invoice Number",
        "Invoice Date",
        "ITC Amount",
        "WHAT",
        "WHY",
        "NEXT ACTION",
    )
    lines: list[list[Any]] = []
    for rw in rows:
        lines.append(
            [
                rw.get("supplier_gstin", ""),
                _excel_quote_text(rw.get("invoice_number", "")),
                rw.get("invoice_date", ""),
                rw.get("amount", ""),
                (rw.get("decision_what") or ""),
                (rw.get("decision_why") or ""),
                (rw.get("decision_next") or ""),
            ]
        )
    return _csv_bytes(hdr, lines), f"missed_itc_export_{rid[:8]}.csv"


def _csv_risk_bytes(rows: list[dict[str, Any]], rid: str) -> tuple[bytes, str]:
    hdr = (
        "Supplier GSTIN",
        "Invoice Number",
        "Invoice Date",
        "ITC Amount",
        "WHAT",
        "WHY",
        "NEXT ACTION",
    )
    lines: list[list[Any]] = []
    for rw in rows:
        lines.append(
            [
                rw.get("supplier_gstin", ""),
                _excel_quote_text(rw.get("invoice_number", "")),
                rw.get("invoice_date", ""),
                rw.get("amount", ""),
                (rw.get("decision_what") or ""),
                (rw.get("decision_why") or ""),
                (rw.get("decision_next") or ""),
            ]
        )
    return _csv_bytes(hdr, lines), f"risk_export_{rid[:8]}.csv"


@reconcile_runs_router.get("/runs/{run_id}/export/itc")
async def reconcile_export_itc(
    run_id: str,
    sort: str = Query("amount_desc"),
    amount_min: Optional[str] = None,
    amount_max: Optional[str] = None,
    supplier_gstin: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> tuple[bytes, str, dict[str, Any]]:
        sb = get_supabase()
        run_row = assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)
        rows = _build_missed_itc_records(
            sb,
            rid=rid,
            payload=p,
            note_counts=notes,
            source_software="your accounting software",
        )
        amin = _parse_money_query(amount_min)
        amax = _parse_money_query(amount_max)
        dfrom = _parse_iso_date_query(date_from)
        dto = _parse_iso_date_query(date_to)
        rows = _filter_bucket_amount_gstin(
            rows,
            amount_min_val=amin,
            amount_max_val=amax,
            supplier_gstin_q=supplier_gstin,
        )
        rows = _filter_itc_date_range(rows, date_from=dfrom, date_to=dto)
        _sort_reconcile_bucket_rows(rows, sort)
        blob, fn = _csv_missed_bytes(rows, rid)
        return blob, fn, run_row

    blob, fn, run_row = await _run_sync(_work)
    await _log_result_export(get_supabase(), current_user, run_row, rid, "itc_csv")
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(io.BytesIO(blob), media_type="text/csv", headers=headers)


@reconcile_runs_router.get("/runs/{run_id}/export/risk")
async def reconcile_export_risk(
    run_id: str,
    sort: str = Query("amount_desc"),
    amount_min: Optional[str] = None,
    amount_max: Optional[str] = None,
    supplier_gstin: Optional[str] = None,
    risk_level: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")

    def _work() -> tuple[bytes, str, dict[str, Any]]:
        sb = get_supabase()
        run_row = assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        notes = _notes_count_for_run(sb, rid)
        rows = _build_wrongful_risk_records(sb, rid=rid, payload=p, note_counts=notes)
        amin = _parse_money_query(amount_min)
        amax = _parse_money_query(amount_max)
        rows = _filter_bucket_amount_gstin(
            rows,
            amount_min_val=amin,
            amount_max_val=amax,
            supplier_gstin_q=supplier_gstin,
        )
        rows = _filter_risk_by_level(rows, risk_level)
        _sort_reconcile_bucket_rows(rows, sort)
        blob, fn = _csv_risk_bytes(rows, rid)
        return blob, fn, run_row

    blob, fn, run_row = await _run_sync(_work)
    await _log_result_export(get_supabase(), current_user, run_row, rid, "risk_csv")
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(io.BytesIO(blob), media_type="text/csv", headers=headers)


def _sort_matched_pair_records(
    pairs: list[tuple[dict[str, Any], Any]],
    sort: str,
) -> list[tuple[dict[str, Any], Any]]:
    """Sort matched (api_row, outcome) pairs using the shared bucket sorter."""
    if not pairs:
        return []
    api_rows = [p[0] for p in pairs]
    orow_by_id = {id(p[0]): p[1] for p in pairs}
    _sort_reconcile_bucket_rows(api_rows, sort)
    return [(row, orow_by_id[id(row)]) for row in api_rows]


@reconcile_runs_router.get("/runs/{run_id}/export/excel")
async def reconcile_export_excel_workbook(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Always return the full multi-sheet reconciliation workbook.

    Tab/filter query params are intentionally ignored — every Excel download
    includes all sections for the run, independent of the active UI tab.
    Per-bucket CSV downloads remain available for filtered single-section exports.
    """
    rid = _parse_uuid(run_id, "run_id")
    uid = str(current_user.get("id", ""))

    def _work() -> tuple[bytes, str, dict[str, Any]]:
        sb = get_supabase()
        assert_run_accessible(sb, rid, current_user)
        p = _payload_or_404(sb, rid)
        run_ex = (
            sb.table("reconciliation_run")
            .select("id, period, status, client_gstin_id, finalized_at, finalized_by")
            .eq("id", rid)
            .limit(1)
            .execute()
        )
        run_row = (run_ex.data or [{}])[0]
        summ_outcome_rows = ro.build_outcome_rows(sb, rid, p)[0]
        summ = _build_reconcile_summary(
            sb,
            run_row=run_row,
            payload=p,
            current_user_id=uid,
            precomputed_outcome_rows=summ_outcome_rows,
        )
        prof = get_user_profile(uid) or {}
        firm_name = str(prof.get("firm_name") or "")
        gen_name = str(prof.get("full_name") or "")
        notes = _notes_count_for_run(sb, rid)

        # Each section is loaded independently for the full run — never gated by UI tab.
        matched_pairs = _build_matched_pair_records(
            sb,
            rid=rid,
            payload=p,
            note_counts=notes,
            precomputed_outcome_rows=summ_outcome_rows,
            include_ineligible=True,
        )
        review_pairs = _build_matched_pair_records(
            sb,
            rid=rid,
            payload=p,
            note_counts=notes,
            fetch_review_required=True,
            precomputed_outcome_rows=summ_outcome_rows,
        )
        review_rows = [pair[0] for pair in review_pairs]
        missed = _build_missed_itc_records(
            sb,
            rid=rid,
            payload=p,
            note_counts=notes,
            source_software="your accounting software",
        )
        risk = _build_wrongful_risk_records(sb, rid=rid, payload=p, note_counts=notes)
        time_barred_ids = {x.id for x in summ_outcome_rows if x.category == "time_barred_itc"}
        recoverable_risk = [
            r for r in risk
            if r.get("id") not in time_barred_ids
            and f"pr:{r.get('id')}" not in time_barred_ids
            and f"wr:{r.get('id')}" not in time_barred_ids
            and str(r.get("section_16_4_status") or "").upper() != "ITC_TIME_BARRED"
        ]
        time_barred_rows = [
            r for r in risk
            if (
                r.get("id") in time_barred_ids
                or f"pr:{r.get('id')}" in time_barred_ids
                or f"wr:{r.get('id')}" in time_barred_ids
                or str(r.get("section_16_4_status") or "").upper() == "ITC_TIME_BARRED"
            )
        ] or [x.as_dict() for x in summ_outcome_rows if x.category == "time_barred_itc"]
        r37 = _build_rule37_rows(sb, rid, p, notes)
        s17 = _build_section175_rows(sb, rid, p, notes)
        duplicate_rows = [
            x.as_dict() for x in summ_outcome_rows if x.category == "duplicate_entry"
        ]
        unmatched_note_rows = [
            x.as_dict() for x in summ_outcome_rows if x.category == "unmatched_notes"
        ]

        gstr3b_result: Optional[dict[str, Any]] = None
        try:
            g3b_ex = (
                sb.table("gstr3b_reconciliation")
                .select(
                    "id, run_id, client_gstin, tax_period, overall_status, "
                    "gstr3b_igst_claimed, gstr3b_cgst_claimed, gstr3b_sgst_claimed, "
                    "gstr2b_igst_available, gstr2b_cgst_available, gstr2b_sgst_available, "
                    "igst_difference, cgst_difference, sgst_difference, "
                    "igst_status, cgst_status, sgst_status, "
                    "outward_supply_total, uploaded_at"
                )
                .eq("run_id", rid)
                .order("uploaded_at", desc=True)
                .limit(1)
                .execute()
            )
            if g3b_ex.data:
                gstr3b_result = dict(g3b_ex.data[0])
        except Exception:
            _log.exception("excel export: gstr3b fetch failed run=%s", rid)

        followup_rows: list[dict[str, Any]] = []
        try:
            followup_raw = _followup_audit_query(sb, run_id=rid)
            followup_rows = [
                x.model_dump() for x in _followup_audit_list_response(followup_raw)
            ]
        except Exception:
            _log.exception("excel export: followup fetch failed run=%s", rid)

        blob, fn = build_excel_workbook_bytes(
            run_id=rid,
            firm_name=firm_name,
            client_trade_name=str(summ.get("client_name") or ""),
            period_raw=str(run_row.get("period") or ""),
            summary=summ,
            matched_pairs=matched_pairs,
            missed_rows=missed,
            risk_rows=recoverable_risk,
            time_barred_rows=time_barred_rows,
            rule37_rows=r37,
            section17_rows=s17,
            review_required_rows=review_rows,
            duplicate_rows=duplicate_rows,
            unmatched_note_rows=unmatched_note_rows,
            gstr3b_result=gstr3b_result,
            followup_rows=followup_rows,
            generated_at=datetime.now(timezone.utc),
            generated_by_name=gen_name,
        )
        return blob, fn, run_row

    blob, fn, run_row = await _run_sync(_work)
    await _log_result_export(get_supabase(), current_user, run_row, rid, "excel")
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GSTR-3B Reconciliation endpoints
# ─────────────────────────────────────────────────────────────────────────────

_MAX_GSTR3B_BYTES = 20 * 1024 * 1024  # 20 MB


class Gstr3bHeadResult(BaseModel):
    gstr2b: float
    gstr3b: float
    difference: float
    status: str


class Gstr3bOutwardSupply(BaseModel):
    taxable_value: float
    igst: float
    total: float
    cgst: float = 0.0
    sgst: float = 0.0
    cess: float = 0.0


class Gstr3bDrc01cResult(BaseModel):
    """Additive Rule 88D / DRC-01C dual-threshold check (does not alter overall_status)."""
    threshold_status: str
    excess_amount: float
    excess_pct: float | None = None
    pct_threshold: float
    amount_threshold: float
    triggers_drc01c: bool


class Gstr3bTaxHeads(BaseModel):
    igst: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    cess: float = 0.0


class Gstr3bSupplyRow(BaseModel):
    taxable_value: float = 0.0
    igst: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    cess: float = 0.0


class Gstr3bInwardSupRow(BaseModel):
    ty: str = "GST"
    inter: float = 0.0
    intra: float = 0.0


class Gstr3bFiledSummary(BaseModel):
    """Full filed GSTR-3B as parsed — additive; independent of ITC check heads."""
    outward_supply: Gstr3bOutwardSupply
    osup_zero: Gstr3bSupplyRow
    osup_nil_exmp: Gstr3bSupplyRow
    isup_rev: Gstr3bSupplyRow
    osup_nongst: Gstr3bSupplyRow
    itc_avl: Gstr3bTaxHeads
    itc_rev: Gstr3bTaxHeads
    itc_net: Gstr3bTaxHeads
    itc_inelg: Gstr3bTaxHeads
    itc_avl_by_source: dict[str, Gstr3bTaxHeads]
    inward_sup: list[Gstr3bInwardSupRow]
    interest_late_fee: Gstr3bTaxHeads
    late_fee: Gstr3bTaxHeads


class Gstr3bReconciliationResult(BaseModel):
    id: str
    run_id: str
    client_gstin: str
    tax_period: str
    overall_status: str
    igst: Gstr3bHeadResult
    cgst: Gstr3bHeadResult
    sgst: Gstr3bHeadResult
    total: Gstr3bHeadResult
    outward_supply: Gstr3bOutwardSupply
    uploaded_at: str
    drc01c: Gstr3bDrc01cResult | None = None
    filed: Gstr3bFiledSummary | None = None
    client_gstin_id: str | None = None


@reconcile_runs_router.post(
    "/runs/{run_id}/gstr3b",
    response_model=Gstr3bReconciliationResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_and_reconcile_gstr3b(
    run_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Accept a GSTR-3B JSON file, parse it, run reconciliation, and persist the result."""
    from app.parsers.gstr3b_parser import ParseError, parse_gstr3b
    from app.services.gstr3b_reconciliation import reconcile_gstr3b

    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)

    uid = str(current_user.get("id") or "").strip()
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing user id")

    fname = (file.filename or "").lower()
    if not fname.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only .json files are accepted for GSTR-3B upload",
        )

    raw_bytes = await file.read()
    if len(raw_bytes) > _MAX_GSTR3B_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="GSTR-3B file exceeds 20 MB limit",
        )

    try:
        raw_json = _json.loads(raw_bytes)
    except _json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid JSON: {exc}",
        ) from exc

    try:
        parsed = parse_gstr3b(raw_json)
    except ParseError as exc:
        _log.warning(
            "GSTR-3B parse failed: run_id=%s, top_keys=%s, gstin_found=%s, period_found=%s",
            rid,
            list(raw_json.keys()) if isinstance(raw_json, dict) else type(raw_json).__name__,
            raw_json.get("gstin") if isinstance(raw_json, dict) else None,
            raw_json.get("ret_period") if isinstance(raw_json, dict) else None,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    client_gstin_id = str(run_row.get("client_gstin_id") or "").strip()
    # Fetch the actual GSTIN string from the database using the ID
    client_gstin_res = sb.table("client_gstins").select("gstin").eq("id", client_gstin_id).single().execute()
    actual_client_gstin = str((client_gstin_res.data or {}).get("gstin") or "").strip().upper()

    if parsed.get("gstin") != actual_client_gstin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"GSTIN mismatch: file is for {parsed.get('gstin')}, but run is for {actual_client_gstin}",
        )

    expected_period = str(run_row.get("period") or "").strip()
    file_period = str(parsed.get("ret_period") or "").strip()
    # Runs are often stored as YYYY-MM-DD (wizard); portal 3B is YYYY-MM / MMYYYY.
    if file_period and not periods_match_yyyy_mm(file_period, expected_period):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Period mismatch: file is for {file_period}, "
                f"but run is for {expected_period}"
            ),
        )

    try:
        result = reconcile_gstr3b(rid, parsed, actual_client_gstin, sb=sb)
    except Exception as exc:
        _log.exception("gstr3b_reconciliation failed run_id=%s", rid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reconciliation failed: {exc}",
        ) from exc

    now_iso = datetime.now(timezone.utc).isoformat()
    igst_r = result["igst"]
    cgst_r = result["cgst"]
    sgst_r = result["sgst"]
    osup   = result["outward_supply"]

    row_data: dict[str, Any] = {
        "run_id":                run_id,
        "client_gstin":          actual_client_gstin,
        "tax_period":            result["tax_period"],
        "gstr3b_igst_claimed":   igst_r["gstr3b"],
        "gstr3b_cgst_claimed":   cgst_r["gstr3b"],
        "gstr3b_sgst_claimed":   sgst_r["gstr3b"],
        "gstr2b_igst_available": igst_r["gstr2b"],
        "gstr2b_cgst_available": cgst_r["gstr2b"],
        "gstr2b_sgst_available": sgst_r["gstr2b"],
        "igst_difference":       igst_r["difference"],
        "cgst_difference":       cgst_r["difference"],
        "sgst_difference":       sgst_r["difference"],
        "igst_status":           igst_r["status"],
        "cgst_status":           cgst_r["status"],
        "sgst_status":           sgst_r["status"],
        "overall_status":        result["overall_status"],
        "outward_supply_total":  osup["total"],
        "raw_gstr3b":            raw_json,
        "uploaded_by":           uid,
        "uploaded_at":           now_iso,
    }

    # Upsert: one record per run (overwrite if re-uploaded)
    try:
        existing = (
            sb.table("gstr3b_reconciliation")
            .select("id")
            .eq("run_id", rid)
            .execute()
        )
        if existing.data:
            existing_id = existing.data[0]["id"]
            ins = (
                sb.table("gstr3b_reconciliation")
                .update(row_data)
                .eq("id", existing_id)
                .execute()
            )
        else:
            ins = sb.table("gstr3b_reconciliation").insert(row_data).execute()
    except Exception as exc:
        detail = supabase_error_message(exc, context="gstr3b_reconciliation upsert")
        _log.exception("gstr3b upsert failed run_id=%s detail=%s", rid, detail)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from exc

    if not ins.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist GSTR-3B reconciliation result",
        )
    return _gstr3b_row_to_response(
        ins.data[0],
        filed_parsed=parsed,
        client_gstin_id=client_gstin_id or None,
    )


@reconcile_runs_router.get(
    "/runs/{run_id}/gstr3b",
    response_model=Gstr3bReconciliationResult,
)
async def get_gstr3b_reconciliation(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Return stored GSTR-3B reconciliation result for a run."""
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)

    try:
        res = (
            sb.table("gstr3b_reconciliation")
            .select(
                "id, run_id, client_gstin, tax_period, overall_status, "
                "gstr3b_igst_claimed, gstr3b_cgst_claimed, gstr3b_sgst_claimed, "
                "gstr2b_igst_available, gstr2b_cgst_available, gstr2b_sgst_available, "
                "igst_difference, cgst_difference, sgst_difference, "
                "igst_status, cgst_status, sgst_status, "
                "outward_supply_total, uploaded_at, raw_gstr3b"
            )
            .eq("run_id", rid)
            .order("uploaded_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        detail = supabase_error_message(exc, context="gstr3b_reconciliation fetch")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from exc

    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GSTR-3B reconciliation found for this run",
        )
    return _gstr3b_row_to_response(
        res.data[0],
        client_gstin_id=str(run_row.get("client_gstin_id") or "") or None,
    )


def _gstr3b_tax_heads(d: Any) -> Gstr3bTaxHeads:
    if not isinstance(d, dict):
        return Gstr3bTaxHeads()
    def _n(k: str) -> float:
        try:
            return round(float(d.get(k) or 0), 2)
        except (TypeError, ValueError):
            return 0.0
    return Gstr3bTaxHeads(igst=_n("igst"), cgst=_n("cgst"), sgst=_n("sgst"), cess=_n("cess"))


def _gstr3b_supply_row(d: Any) -> Gstr3bSupplyRow:
    if not isinstance(d, dict):
        return Gstr3bSupplyRow()
    def _n(k: str) -> float:
        try:
            return round(float(d.get(k) or 0), 2)
        except (TypeError, ValueError):
            return 0.0
    return Gstr3bSupplyRow(
        taxable_value=_n("taxable_value"),
        igst=_n("igst"),
        cgst=_n("cgst"),
        sgst=_n("sgst"),
        cess=_n("cess"),
    )


def _filed_from_parsed(parsed: Mapping[str, Any] | None) -> Gstr3bFiledSummary | None:
    if not isinstance(parsed, dict):
        return None
    osup = parsed.get("outward_supply") if isinstance(parsed.get("outward_supply"), dict) else {}
    by_src_raw = parsed.get("itc_avl_by_source")
    by_src: dict[str, Gstr3bTaxHeads] = {}
    if isinstance(by_src_raw, dict):
        for ty, heads in by_src_raw.items():
            by_src[str(ty)] = _gstr3b_tax_heads(heads)
    for ty in ("IMPG", "IMPS", "ISRC", "ISD", "OTH"):
        by_src.setdefault(ty, Gstr3bTaxHeads())

    inward_rows: list[Gstr3bInwardSupRow] = []
    for row in parsed.get("inward_sup") or []:
        if not isinstance(row, dict):
            continue
        try:
            inter = round(float(row.get("inter") or 0), 2)
            intra = round(float(row.get("intra") or 0), 2)
        except (TypeError, ValueError):
            inter, intra = 0.0, 0.0
        inward_rows.append(
            Gstr3bInwardSupRow(
                ty=str(row.get("ty") or "GST"),
                inter=inter,
                intra=intra,
            )
        )

    try:
        txval = round(float(osup.get("taxable_value") or 0), 2)
        oigst = round(float(osup.get("igst") or 0), 2)
        ocgst = round(float(osup.get("cgst") or 0), 2)
        osgst = round(float(osup.get("sgst") or 0), 2)
        ocess = round(float(osup.get("cess") or 0), 2)
        total = round(float(osup.get("total") or (txval + oigst)), 2)
    except (TypeError, ValueError):
        txval = oigst = ocgst = osgst = ocess = total = 0.0

    return Gstr3bFiledSummary(
        outward_supply=Gstr3bOutwardSupply(
            taxable_value=txval,
            igst=oigst,
            cgst=ocgst,
            sgst=osgst,
            cess=ocess,
            total=total,
        ),
        osup_zero=_gstr3b_supply_row(parsed.get("osup_zero")),
        osup_nil_exmp=_gstr3b_supply_row(parsed.get("osup_nil_exmp")),
        isup_rev=_gstr3b_supply_row(parsed.get("isup_rev")),
        osup_nongst=_gstr3b_supply_row(parsed.get("osup_nongst")),
        itc_avl=_gstr3b_tax_heads(parsed.get("itc_avl")),
        itc_rev=_gstr3b_tax_heads(parsed.get("itc_rev")),
        itc_net=_gstr3b_tax_heads(parsed.get("itc_net")),
        itc_inelg=_gstr3b_tax_heads(parsed.get("itc_inelg")),
        itc_avl_by_source=by_src,
        inward_sup=inward_rows,
        interest_late_fee=_gstr3b_tax_heads(parsed.get("interest_late_fee")),
        late_fee=_gstr3b_tax_heads(parsed.get("late_fee")),
    )


def _parse_filed_from_raw(raw: Any) -> Gstr3bFiledSummary | None:
    """Re-parse stored raw_gstr3b. Cheap (~sub-ms); no cache needed."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except _json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    try:
        from app.parsers.gstr3b_parser import ParseError, parse_gstr3b
        return _filed_from_parsed(parse_gstr3b(raw))
    except (ParseError, TypeError, ValueError):
        _log.warning("gstr3b filed re-parse failed", exc_info=True)
        return None


def _gstr3b_row_to_response(
    row: dict,
    *,
    filed_parsed: Mapping[str, Any] | None = None,
    client_gstin_id: str | None = None,
) -> Gstr3bReconciliationResult:
    from app.services.gstr3b_reconciliation import (
        _head_status,
        _overall_status,
        compute_drc01c_threshold,
    )

    def _f(key: str) -> float:
        try:
            return round(float(row.get(key) or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    igst_diff = _f("igst_difference")
    cgst_diff = _f("cgst_difference")
    sgst_diff = _f("sgst_difference")
    g3b_igst  = _f("gstr3b_igst_claimed")
    g3b_cgst  = _f("gstr3b_cgst_claimed")
    g3b_sgst  = _f("gstr3b_sgst_claimed")
    g2b_igst  = _f("gstr2b_igst_available")
    g2b_cgst  = _f("gstr2b_cgst_available")
    g2b_sgst  = _f("gstr2b_sgst_available")

    g2b_total = round(g2b_igst + g2b_cgst + g2b_sgst, 2)
    g3b_total = round(g3b_igst + g3b_cgst + g3b_sgst, 2)
    drc = compute_drc01c_threshold(g3b_total, g2b_total)

    igst_status = str(row.get("igst_status") or _head_status(g2b_igst, g3b_igst))
    cgst_status = str(row.get("cgst_status") or _head_status(g2b_cgst, g3b_cgst))
    sgst_status = str(row.get("sgst_status") or _head_status(g2b_sgst, g3b_sgst))
    # Recompute so older rows (any-overclaim badge) and Total-row status stay honest.
    overall = _overall_status(igst_status, cgst_status, sgst_status)
    total_status = _head_status(g2b_total, g3b_total)

    filed: Gstr3bFiledSummary | None
    if filed_parsed is not None:
        filed = _filed_from_parsed(filed_parsed)
    else:
        filed = _parse_filed_from_raw(row.get("raw_gstr3b"))

    # Prefer full 3.1(a) from filed when available; else stored total only
    if filed is not None:
        osup_out = filed.outward_supply
    else:
        osup_out = Gstr3bOutwardSupply(
            taxable_value=0.0, igst=0.0, total=_f("outward_supply_total"),
        )

    return Gstr3bReconciliationResult(
        id=str(row.get("id") or ""),
        run_id=str(row.get("run_id") or ""),
        client_gstin=str(row.get("client_gstin") or ""),
        tax_period=str(row.get("tax_period") or ""),
        overall_status=overall,
        igst=Gstr3bHeadResult(
            gstr2b=g2b_igst, gstr3b=g3b_igst, difference=igst_diff,
            status=igst_status,
        ),
        cgst=Gstr3bHeadResult(
            gstr2b=g2b_cgst, gstr3b=g3b_cgst, difference=cgst_diff,
            status=cgst_status,
        ),
        sgst=Gstr3bHeadResult(
            gstr2b=g2b_sgst, gstr3b=g3b_sgst, difference=sgst_diff,
            status=sgst_status,
        ),
        total=Gstr3bHeadResult(
            gstr2b=g2b_total,
            gstr3b=g3b_total,
            difference=round(igst_diff + cgst_diff + sgst_diff, 2),
            status=total_status,
        ),
        outward_supply=osup_out,
        uploaded_at=str(row.get("uploaded_at") or ""),
        drc01c=Gstr3bDrc01cResult(**drc),
        filed=filed,
        client_gstin_id=client_gstin_id,
    )


# ---------------------------------------------------------------------------
# GSTR-3B Table 4 Workpaper Models & Endpoints
# ---------------------------------------------------------------------------

class Table4AdjustmentInput(BaseModel):
    row_id: str
    adjustment_type: str = "ADDITION"  # ADDITION | REDUCTION
    statutory_category: str
    igst: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    cess: float = 0.0
    reason: str
    reference_doc: Optional[str] = None
    turnover_ratio_data: Optional[dict[str, Any]] = None
    expected_digest: Optional[str] = None


class ExceptionDispositionInput(BaseModel):
    record_id: str
    exception_type: str  # SEC_17_5 | RULE_37 | TWO_B_ONLY | GOODS_RECEIPT | RULE_37A
    disposition: str
    reason: str
    reference_doc: Optional[str] = None
    statutory_reference: Optional[str] = None


@reconcile_runs_router.get("/runs/{run_id}/gstr3b/table4")
async def get_gstr3b_table4_workpaper(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve compiled GSTR-3B Table 4 Workpaper (Provisional or Finalized)."""
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

    def _work():
        return compile_gstr3b_table4(sb, rid)

    return await _run_sync(_work)


@reconcile_runs_router.get("/runs/{run_id}/gstr3b/table4/drilldown")
async def get_gstr3b_table4_drilldown(
    run_id: str,
    row_id: str = Query(..., description="Table 4 row code (e.g. 4A1, 4A5, 4B1, 4B2)"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch paginated, verifiable invoice-level ledger for any Table 4 cell."""
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

    def _work():
        return get_table4_drilldown(sb, rid, row_id=row_id, page=page, limit=limit, search=search)

    return await _run_sync(_work)


@reconcile_runs_router.post("/runs/{run_id}/gstr3b/table4/adjust")
async def add_gstr3b_table4_adjustment(
    run_id: str,
    body: Table4AdjustmentInput,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: dict = Depends(get_current_active_user),
):
    """Add a verified external adjustment (Rules 42/43/38/RCM) to a provisional run.

    Enforces optimistic concurrency control (OCC) if expected_digest or If-Match header is provided.
    """
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

    run_row = (
        sb.table("reconciliation_run")
        .select("id, status, is_locked, client_gstin_id, period")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not run_row.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    r0 = run_row.data[0]
    if bool(r0.get("is_locked")) or str(r0.get("status", "")).upper() == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finalized reconciliation runs are immutable; adjustments cannot be modified.",
        )

    if not body.reason or len(body.reason.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reason must be at least 10 characters explaining the statutory basis.",
        )

    # Optimistic Concurrency Control (OCC) Check
    raw_expected = body.expected_digest or (if_match.strip('"') if if_match else None)
    current_adjs = load_table4_adjustments(sb, rid)
    current_adj_digest = compute_table4_adjustments_digest(current_adjs, run_id=rid)

    if raw_expected:
        expected_clean = raw_expected.strip()
        matches = (expected_clean == current_adj_digest)
        if not matches:
            # Also accept the full workpaper audit_hash so clients can provide either token
            try:
                wp = compile_gstr3b_table4(sb, rid)
                matches = (expected_clean == (wp.get("audit_hash") or wp.get("source_state_digest")))
            except Exception:
                pass

        if not matches:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Table 4 workpaper adjustments have changed since last retrieved "
                    f"(expected '{expected_clean}', current '{current_adj_digest}'). "
                    f"Please refresh the workpaper before saving adjustments."
                ),
            )

    uid = current_user.get("id")
    insert_data = {
        "run_id": rid,
        "client_gstin_id": r0.get("client_gstin_id"),
        "tax_period": r0.get("period") or "",
        "row_id": body.row_id.upper().strip(),
        "igst_paise": rupees_to_paise(body.igst),
        "cgst_paise": rupees_to_paise(body.cgst),
        "sgst_paise": rupees_to_paise(body.sgst),
        "cess_paise": rupees_to_paise(body.cess),
        "adjustment_type": body.adjustment_type.upper().strip(),
        "statutory_category": body.statutory_category.upper().strip(),
        "reason": body.reason.strip(),
        "reference_doc": (body.reference_doc or "").strip() or None,
        "turnover_ratio_data": body.turnover_ratio_data,
        "created_by": uid,
        "is_deleted": False,
    }

    res = sb.table("gstr3b_table4_adjustments").insert(insert_data).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save adjustment")

    saved_row = dict(res.data[0])
    updated_adjs = [*current_adjs, saved_row]
    saved_row["new_adjustments_digest"] = compute_table4_adjustments_digest(updated_adjs, run_id=rid)
    return saved_row


@reconcile_runs_router.delete("/runs/{run_id}/gstr3b/table4/adjust/{adj_id}")
async def delete_gstr3b_table4_adjustment(
    run_id: str,
    adj_id: str,
    expected_digest: Optional[str] = Query(None, description="Optional expected concurrency token"),
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: dict = Depends(get_current_active_user),
):
    """Soft delete an adjustment from a provisional run.

    Enforces optimistic concurrency control (OCC) if expected_digest or If-Match header is provided.
    """
    rid = _parse_uuid(run_id, "run_id")
    aid = _parse_uuid(adj_id, "adj_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

    run_row = (
        sb.table("reconciliation_run")
        .select("id, status, is_locked")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not run_row.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    r0 = run_row.data[0]
    if bool(r0.get("is_locked")) or str(r0.get("status", "")).upper() == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finalized reconciliation runs are immutable; adjustments cannot be deleted.",
        )

    # Fetch target adjustment
    adj_row = (
        sb.table("gstr3b_table4_adjustments")
        .select("*")
        .eq("id", aid)
        .eq("run_id", rid)
        .limit(1)
        .execute()
    )
    if not adj_row.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Adjustment not found")
    target_adj = adj_row.data[0]
    if bool(target_adj.get("is_deleted")):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Adjustment has already been deleted.")

    # Concurrency verification if expected token supplied
    raw_expected = expected_digest or (if_match.strip('"') if if_match else None)
    current_adjs = load_table4_adjustments(sb, rid)
    current_adj_digest = compute_table4_adjustments_digest(current_adjs, run_id=rid)

    if raw_expected:
        expected_clean = raw_expected.strip()
        matches = (expected_clean == current_adj_digest)
        if not matches:
            try:
                wp = compile_gstr3b_table4(sb, rid)
                matches = (expected_clean == (wp.get("audit_hash") or wp.get("source_state_digest")))
            except Exception:
                pass
        if not matches:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Table 4 workpaper adjustments have changed since last retrieved "
                    f"(expected '{expected_clean}', current '{current_adj_digest}'). "
                    f"Please refresh the workpaper before deleting adjustments."
                ),
            )

    sb.table("gstr3b_table4_adjustments").update({"is_deleted": True}).eq("id", aid).eq("run_id", rid).execute()
    remaining_adjs = [a for a in current_adjs if str(a.get("id")) != str(aid)]
    new_digest = compute_table4_adjustments_digest(remaining_adjs, run_id=rid)
    return {"deleted": True, "id": aid, "new_adjustments_digest": new_digest}


@reconcile_runs_router.post("/runs/{run_id}/dispositions")
async def record_exception_disposition(
    run_id: str,
    body: ExceptionDispositionInput,
    current_user: dict = Depends(get_current_active_user),
):
    """Record an audit disposition on an ITC-affecting exception."""
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

    run_row = (
        sb.table("reconciliation_run")
        .select("id, status, is_locked")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not run_row.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    r0 = run_row.data[0]
    if bool(r0.get("is_locked")) or str(r0.get("status", "")).upper() == RunStatus.FINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finalized reconciliation runs are immutable; dispositions cannot be modified.",
        )

    # Derive eligibility and table4 effect
    disp_clean = body.disposition.upper().strip()
    ex_type = body.exception_type.upper().strip()

    elig_effect = "ELIGIBLE"
    t4_effect = "4A5"

    if disp_clean in ("CONFIRMED_BLOCKED", "INELIGIBLE"):
        elig_effect = "INELIGIBLE"
        t4_effect = "4B1"
    elif disp_clean in ("REVERSED", "REVERSAL_CONFIRMED"):
        elig_effect = "REVERSED"
        t4_effect = "4B2"
    elif disp_clean in ("HELD_GOODS_NOT_RECEIVED", "HOLD", "REJECTED_WRONG_GSTIN", "NOT_RECEIVED"):
        elig_effect = "HELD"
        t4_effect = "EXCLUDED"
    elif disp_clean in ("STATUTORY_EXCEPTION", "PAID_ELIGIBLE", "BOOKED_AND_VERIFIED", "RECEIPT_VERIFIED"):
        elig_effect = "ELIGIBLE"
        t4_effect = "4A5"

    uid = current_user.get("id")
    record_data = {
        "run_id": rid,
        "record_id": body.record_id.strip(),
        "exception_type": ex_type,
        "disposition": disp_clean,
        "eligibility_effect": elig_effect,
        "table4_effect": t4_effect,
        "reason": body.reason.strip(),
        "reference_doc": (body.reference_doc or "").strip() or None,
        "statutory_reference": (body.statutory_reference or "").strip() or None,
        "created_by": uid,
    }

    res = (
        sb.table("reconciliation_exception_dispositions")
        .upsert(record_data, on_conflict="run_id,record_id,exception_type")
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save disposition")
    return res.data[0]


@reconcile_runs_router.get("/runs/{run_id}/gstr3b/table4/export")
async def export_gstr3b_table4_workpaper(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Download the 5-sheet GSTR-3B Table 4 Workpaper Excel workbook."""
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

    def _work():
        return generate_table4_excel_workpaper(sb, rid)

    excel_bytes = await _run_sync(_work)
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="GSTR3B_Table4_Workpaper_{rid[:8]}.xlsx"',
            "Cache-Control": "no-cache",
        },
    )

