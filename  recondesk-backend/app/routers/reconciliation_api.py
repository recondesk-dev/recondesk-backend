"""Reconciliation results, history, diff, summary, finalize — `/api/reconciliation`."""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import math
import re
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional, TypeVar
from urllib.parse import unquote

TSeq = TypeVar("TSeq")

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from uuid import UUID

from app.auth import get_current_active_user, get_user_role
from app.constants import RunStatus
from app.database import get_supabase, get_user_profile
from app.services.decision_templates import generate_decision
from app.services import reconciliation_outcomes as ro
from app.services.firm_access import (
    assert_run_accessible,
    list_accessible_client_gstin_ids,
)
from app.services.followup_audit_export import build_followup_history_xlsx_bytes
from app.services.reconcile_export_workbook import build_excel_workbook_bytes
from app.utils.audit import log_action
from app.utils.supabase_errors import supabase_error_message
from app.utils.storage import delete_file
from app.worker.reconciliation_task import execute_reconciliation
from app.services.invoice_results_sync import (
    count_unresolved_rule37,
    find_invoice_result_id_for_pr,
    sync_rule37_invoice_results,
)

_log = logging.getLogger(__name__)
router = APIRouter()


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
        "rule37_warnings",
        "blocked_credit",
        "credit_notes",
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


@router.post("/finalize/{run_id}", response_model=FinalizeResponse)
async def finalize_reconciliation(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    uid = str(current_user.get("id", ""))
    role = await get_user_role(uid)
    if (role or "").strip().lower() == "staff":
        await log_action(
            uid,
            "FINALIZATION_BLOCKED",
            "reconciliation_run",
            run_id,
            {"role": role},
            ip_address=(request.client.host if request.client else None),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    row = assert_run_accessible(sb, rid, current_user)
    st = str(row.get("status") or "").strip().upper()
    if st == RunStatus.FINAL or bool(row.get("is_locked")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="run is already final",
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
    need, have, unresolved = count_unresolved_rule37(sb, rid)
    if unresolved > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{unresolved} Rule 37 invoice(s) are unresolved. "
                "Resolve all before finalizing."
            ),
        )
    now = datetime.now(timezone.utc).isoformat()
    by = uid
    prof = get_user_profile(uid)
    name = (prof or {}).get("full_name")
    ex = (
        sb.table("reconciliation_run")
        .update(
            {
                "status": RunStatus.FINAL,
                "finalized_at": now,
                "finalized_by": by,
                "is_locked": True,
                "updated_at": now,
            }
        )
        .eq("id", rid)
        .eq("status", RunStatus.COMPLETED)
        .execute()
    )
    if not ex.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="could not finalize run; refresh and retry",
        )
    await log_action(
        uid,
        "RUN_FINALIZED",
        "reconciliation_run",
        rid,
        {},
        ip_address=(request.client.host if request.client else None),
    )
    return FinalizeResponse(
        run_id=rid,
        status=RunStatus.FINAL,
        finalized_at=now,
        finalized_by=by,
        finalized_by_name=name,
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
                "template_type, status, generated_by, generated_at, invoice_snapshot"
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
    if paise is None:
        return 0.0
    try:
        return round(float(paise) / 100.0, 2)
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


def _normalize_record_id(record_id: str) -> str:
    """URL-decode a path ``record_id`` (handles single and double encoding)."""
    decoded = str(record_id or "").strip()
    for _ in range(3):
        next_val = unquote(decoded)
        if next_val == decoded:
            break
        decoded = next_val
    return decoded


def _rule37_db_record_key(record_id: str) -> str:
    """``mismatch_notes.record_id`` is a UUID column — strip the ``r37:`` API prefix."""
    rid = _normalize_record_id(record_id)
    if rid.startswith("r37:"):
        return rid[4:]
    return rid


def _rule37_api_record_id(db_record_id: str) -> str:
    """Map a DB ``record_id`` back to the frontend ``r37:…`` identifier."""
    rid = str(db_record_id or "").strip()
    if not rid:
        return rid
    if rid.startswith("r37:"):
        return rid
    return f"r37:{rid}"


def _rule37_db_record_lookup_keys(record_id: str) -> list[str]:
    """Candidate keys for lookup (stripped UUID plus legacy full ``r37:`` value)."""
    full = _normalize_record_id(record_id)
    bare = _rule37_db_record_key(full)
    keys: list[str] = []
    for key in (bare, full):
        if key and key not in keys:
            keys.append(key)
    return keys


def _is_schema_compat_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "pgrst204",
            "42703",
            "column",
            "note_type",
            "firm_owner_id",
            "severity",
            "status",
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
) -> None:
    """Persist a Rule 37 action in the dedicated ``rule37_actions`` table.

    Uses an upsert keyed on (run_id, record_hash) so clicking the same button
    twice is idempotent.  ``record_hash`` is the bare string after stripping
    the ``r37:`` prefix — it is plain TEXT, never treated as UUID by PostgREST.
    """
    record_hash = _rule37_record_hash(record_id)
    _log.debug(
        "rule37 action upsert run_id=%s record_id=%s hash=%s status=%s",
        run_id, record_id, record_hash, status_value,
    )
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
            }
        )
    else:
        payload.update(
            {
                "amount_paid": None,
                "tds_deducted": 0,
                "tds_confirmed": False,
                "total_settled": None,
                "remaining_unpaid_amount": None,
                "payment_coverage": None,
            }
        )
    _log.info("rule37 payload: %s", payload)
    try:
        sb.table("rule37_actions").upsert(
            payload,
            on_conflict="run_id,record_hash",
        ).execute()
    except Exception as e:
        _log.exception("rule37 update failed: %s", e)
        raise


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
                "record_hash, status, amount_paid, tds_deducted, tds_confirmed, "
                "total_settled, remaining_unpaid_amount, payment_coverage"
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
        if not record_hash or status not in {"resolved", "acknowledged"}:
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
    for col in ("reconciliation_run_id", "run_id"):
        try:
            qr = sb.table("rule37_warnings").select("*").eq(col, rid)  # type: ignore[arg-type]
            exe = qr.execute()
            chunk = exe.data or []
            if chunk:
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
                return body
        except Exception:
            continue
    return _build_rule37_rows(sb, rid, payload, notes)


def _build_rule37_summary_payload(
    sb,
    rid: str,
    payload: dict[str, Any],
    notes: Counter[str],
) -> dict[str, Any]:
    rows = _all_rule37_rows_for_run(sb, rid, payload, notes)
    row_by_id = {str(r.get("id") or ""): r for r in rows}

    total = 0.0
    saved = 0.0
    reversed_amt = 0.0
    pending = 0.0
    action_details = _rule37_action_details_for_run(sb, rid)

    for row in rows:
        amt = float(row.get("amount") or 0)
        total += amt
        row_id = str(row.get("id") or "")
        status = str(row.get("rule37_action_status") or "").strip().lower()
        detail = action_details.get(row_id, {})
        coverage = str(detail.get("payment_coverage") or "").strip().lower()
        if status == "resolved":
            if coverage == "partial":
                pending += amt
            else:
                saved += amt
        elif status == "acknowledged":
            reversed_amt += amt
        else:
            pending += amt

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
            "total_itc_at_risk": round(total, 2),
            "itc_saved": round(saved, 2),
            "itc_reversed": round(reversed_amt, 2),
            "pending_action": round(pending, 2),
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
        if record_hash and status in {"resolved", "acknowledged"}:
            api_id = record_hash if record_hash.startswith("r37:") else f"r37:{record_hash}"
            out[api_id] = status
    return out


def _decision_statuses_for_run(sb, run_id: str) -> dict[str, str]:
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
    """
    now = datetime.now(timezone.utc).isoformat()

    # ── Step 1: remove any prior status row for this (run, record) pair ──
    try:
        sb.table("mismatch_notes").delete().eq("run_id", run_id).eq(
            "record_id", record_id
        ).execute()
    except Exception:
        _log.warning(
            "decision_status delete failed (non-fatal) run_id=%s record_id=%s",
            run_id,
            record_id,
        )

    # ── Step 2: insert the fresh status row ───────────────────────────────
    ins: dict[str, Any] = {
        "record_id": record_id,
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


def _matched_ui_match_level(engine_row: dict[str, Any], match_status_display: Optional[str]) -> str:
    st = str(match_status_display or "").strip().upper()
    if engine_row.get("is_late_filing"):
        return "MANUAL"
    if st == "MATCHED":
        return "EXACT"
    return "FUZZY"


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
) -> dict[str, Any]:
    rid = str(run_row.get("id", "")).strip()
    engine = payload.get("engine") or {}
    matched_n = len(engine.get("matched") or [])
    # Count gstr_records with a single COUNT query instead of fetching all rows.
    _cnt = (
        sb.table("gstr_records")
        .select("id", count="exact")
        .eq("run_id", rid)
        .limit(1)
        .execute()
    )
    n_g = int(_cnt.count if getattr(_cnt, "count", None) is not None else len(_cnt.data or []))

    matched_count = matched_n
    missed_list = engine.get("missed_itc") or []
    wr_list = engine.get("wrongful_itc_risk") or []
    matched_engine = engine.get("matched") or []
    late_match_count = sum(1 for m in matched_engine if m.get("is_late_filing"))
    missed_count = len(missed_list)
    wrongful_count = len(wr_list)

    missed_total_rupees = sum(
        _paise_to_rupees(int(m.get("total_tax_paise") or 0)) for m in missed_list
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
            _wrongful_risk_taxable_paise(
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

    return {
        "run_id": rid,
        "client_name": client_display,
        "client_gstin": client_gstin,
        "period": period,
        "assigned_to_name": assigned_to_name,
        "status": _display_status(run_row.get("status")),
        "finalized_by_name": finalized_name,
        "finalized_at": run_row.get("finalized_at"),
        "total_gstr_records": n_g,
        "matched_count": matched_count,
        "missed_itc_count": missed_count,
        "missed_itc_total_amount": round(missed_total_rupees, 2),
        "wrongful_risk_count": wrongful_count,
        "wrongful_risk_total_amount": round(wrongful_total_rupees, 2),
        "wrongful_risk_purchase_total_amount": round(
            wrongful_purchase_total_rupees, 2
        ),
        "late_match_count": late_match_count,
        "match_rate_percent": match_pct,
        "user_role": role_out,
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
        decision_status = decision_statuses.get(row_id, "pending")
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
                "notes_count": int(note_counts.get(row_id, 0)),
                "gstr2b_data": gd2,
                "purchase_register_data": {},
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
        decision_status = decision_statuses.get(row_id, "pending")
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
                "notes_count": int(note_counts.get(row_id, 0)),
                "gstr2b_data": {},
                "purchase_register_data": gd2,
            }
        )
    return out


def _build_matched_pair_records(
    sb,
    *,
    rid: str,
    payload: dict[str, Any],
    note_counts: Counter[str],
) -> list[tuple[dict[str, Any], Any]]:
    """Return list of ({api_row}, outcome_row) for pagination / filters."""
    gstr_db = ro.load_gstr_map(sb, rid)
    pr_db = ro.load_pr_map(sb, rid)
    engine_matched = payload.get("engine", {}).get("matched") or []
    decisions_rows = (
        ((payload.get("decisions") or {}).get("rows")) or []
    )

    oc_rows = ro.build_outcome_rows(sb, rid, payload)[0]
    oc_matched_in_order = [r for r in oc_rows if r.category == "matched"]

    if len(oc_matched_in_order) != len(engine_matched):
        _log.warning(
            "matched outcome vs engine mismatch run=%s %s vs %s",
            rid,
            len(oc_matched_in_order),
            len(engine_matched),
        )

    out_pairs: list[tuple[dict[str, Any], Any]] = []

    for idx, en_row in enumerate(engine_matched):
        gid = str(en_row.get("gstr_id", "")).strip()
        pid = str(en_row.get("pr_id", "")).strip()
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

        orow = oc_matched_in_order[idx] if idx < len(oc_matched_in_order) else None
        mst_disp = getattr(orow, "match_status", None)
        lvl = _matched_ui_match_level(dict(en_row), mst_disp)
        amt = _paise_to_rupees(int(gm.get("total_tax_paise") or 0))

        tax_diff_paise: Optional[int] = None
        if getattr(orow, "match_status", "") == "MISMATCHED" and orow is not None:
            tax_diff_paise = int(orow.total_tax_diff_paise)

        dm: dict[str, Any] = (
            decisions_rows[idx] if idx < len(decisions_rows) and isinstance(decisions_rows[idx], dict) else {}
        )
        d_what = dm.get("decision_what")
        d_why = dm.get("decision_why")
        d_next = dm.get("decision_next")

        gd2 = _merged_record_data(grd_raw, gm)
        pd2 = _merged_record_data(prd_raw, pm)

        rid_str = f"pm:{gid}"
        api_row = {
            "id": rid_str,
            "supplier_gstin": str(gm.get("supplier_gstin") or pm.get("supplier_gstin") or ""),
            "invoice_number": str(
                gm.get("invoice_number_normalized")
                or pm.get("invoice_number_normalized")
                or ""
            ),
            "invoice_date": str(
                gm.get("invoice_date") or pm.get("invoice_date") or ""
            )[:40],
            "amount": amt,
            "match_level": lvl,
            "confidence_score": float(en_row.get("confidence_score") or 0.0),
            "discrepancy_note": None,
            "tax_difference_paise": tax_diff_paise,
            "decision_what": d_what
            if d_what
            else (str(getattr(orow, "decision_what", "")) if orow else None),
            "decision_why": d_why
            if d_why
            else (str(getattr(orow, "decision_why", "")) if orow else None),
            "decision_next": d_next
            if d_next
            else (str(getattr(orow, "decision_next", "")) if orow else None),
            "decision_status": "pending",
            "decision_type": None,
            "notes_count": int(note_counts.get(rid_str, 0)),
            "gstr2b_data": gd2,
            "purchase_register_data": pd2,
        }
        out_pairs.append((api_row, orow))
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

        if review_required and orow is not None:
            if getattr(orow, "match_status", "").upper() == "MATCHED":
                continue

        if section174:
            blk = bool(getattr(orow, "blocked_credit_flag", False)) if orow else False
            if not blk:
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
            )
        )
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


def _sort_reconcile_bucket_rows(rows: list[dict[str, Any]], sort: str) -> None:
    s = (sort or "amount_desc").strip().lower()
    if s == "amount_asc":
        rows.sort(key=lambda x: (float(x.get("amount") or 0), str(x.get("id"))))
    elif s == "amount_desc":
        rows.sort(key=lambda x: (-float(x.get("amount") or 0), str(x.get("id"))))
    elif s == "supplier_name":
        rows.sort(
            key=lambda x: (str(x.get("supplier_gstin") or "").lower(), str(x.get("id")))
        )
    elif s == "invoice_date":
        rows.sort(
            key=lambda x: (
                _row_invoice_date_value(x) or date.min,
                str(x.get("id")),
            ),
            reverse=True,
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
    return {
        "data": page_items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": _total_pages(total, limit),
    }


async def _reconcile_finalize_core(
    request: Request,
    sb,
    *,
    rid: str,
    current_user: dict,
    checklist_snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    uid = str(current_user.get("id", ""))
    run_row = assert_run_accessible(sb, rid, current_user)
    role = await get_user_role(uid)
    if (role or "").strip().lower() != "admin":
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
    raw_status = str(run_row.get("status") or "").strip()
    st = raw_status.upper()
    if st == RunStatus.FINAL or raw_status.lower() == "final":
        p = ro.load_payload(sb, rid) or {}
        return _build_reconcile_summary(
            sb, run_row=run_row, payload=p, current_user_id=uid
        )
    if st != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="run must be complete before finalization",
        )
    if not ro.load_payload(sb, rid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no reconciliation payload for this run",
        )
    need, have, unresolved = count_unresolved_rule37(sb, rid)
    if unresolved > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{unresolved} Rule 37 invoice(s) are unresolved. "
                "Resolve all before finalizing."
            ),
        )
    now = datetime.utcnow().isoformat()
    update_fields: dict[str, Any] = {
        "status": RunStatus.FINAL,
        "finalized_at": now,
        "finalized_by": uid,
        "is_locked": True,
        "updated_at": now,
    }
    if checklist_snapshot is not None:
        update_fields["checklist_snapshot"] = checklist_snapshot

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
    await log_action(
        uid,
        "RUN_FINALIZED",
        "reconciliation_run",
        rid,
        {},
        ip_address=(request.client.host if request.client else None),
    )
    refreshed = (
        sb.table("reconciliation_run")
        .select("*")
        .eq("id", rid)
        .limit(1)
        .execute()
    ).data or []
    refreshed_row = refreshed[0] if refreshed else {}
    p = ro.load_payload(sb, rid) or {}
    return _build_reconcile_summary(
        sb, run_row={**run_row, **refreshed_row}, payload=p, current_user_id=uid
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
    out: list[dict[str, Any]] = []
    action_details = _rule37_action_details_for_run(sb, rid)
    for row_id, ru in uniq.items():
        amt = _paise_to_rupees(int(ru.get("itc_at_risk_paise") or 0))
        invoice_amt = _rule37_invoice_amount_from_item(ru)
        ur = _rule37_urgency_from_status(ru.get("status"))
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
                "rule37_payment_coverage": (
                    coverage if coverage in {"full", "partial"} else None
                ),
                "match_level": "UNMATCHED",
                "confidence_score": 0.0,
                "discrepancy_note": None,
                "decision_what": ru.get("decision_what"),
                "decision_why": ru.get("decision_why"),
                "decision_next": ru.get("decision_next"),
                "decision_status": "pending",
                "decision_type": None,
                "notes_count": int(note_counts.get(row_id, 0)),
                "gstr2b_data": {},
                "purchase_register_data": {},
                "rule37_urgency": ur,
                "rule37_action_status": action_status,
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
    dec = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    lst: list = []
    lst.extend(list(dec.get("section_17_5") or dec.get("section_175") or []))
    lst.extend(list(comp.get("section_17_5") or comp.get("section_175") or []))

    uniq: dict[str, dict[str, Any]] = {}
    for item in lst:
        if not isinstance(item, dict):
            continue
        inv = str(item.get("invoice_number") or item.get("invoice_no") or "")
        gst = str(item.get("supplier_gstin") or "")
        k = f"{gst}|{inv}"
        uniq[k] = item

    out: list[dict[str, Any]] = []
    for k, bn in uniq.items():
        row_id = f"s175:{k.replace('|', '-')[:240]}"
        cat = bn.get("category")
        raw_am = bn.get("estimated_itc_amount") if "estimated_itc_amount" in bn else bn.get("amount")
        try:
            amt = round(float(raw_am if raw_am is not None else 0.0), 2)
        except (TypeError, ValueError):
            amt = 0.0
        out.append(
            {
                "id": row_id,
                "supplier_gstin": str(bn.get("supplier_gstin") or ""),
                "invoice_number": str(bn.get("invoice_number") or ""),
                "invoice_date": str(bn.get("invoice_date") or "")[:40],
                "amount": amt,
                "match_level": "UNMATCHED",
                "confidence_score": 0.0,
                "discrepancy_note": bn.get("hsn_code"),
                "decision_what": bn.get("decision_what"),
                "decision_why": bn.get("decision_why"),
                "decision_next": bn.get("decision_next"),
                "decision_status": "pending",
                "decision_type": None,
                "notes_count": int(note_counts.get(row_id, 0)),
                "gstr2b_data": {},
                "purchase_register_data": {},
                "section_17_5_category": str(cat) if cat else None,
            }
        )
    out.sort(key=lambda x: (-x["amount"], x["id"]))
    return out


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
        "section_17_5_category": str(row.get("category") or "") or None,
    }


def _csv_bytes(headers: tuple[str, ...], data_rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for ln in data_rows:
        writer.writerow(ln)
    return buf.getvalue().encode("utf-8")


_CHUNK_CLIENT_IDS = 120


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
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    accessible = list_accessible_client_gstin_ids(sb, current_user)
    if not accessible:
        return []

    per_chunk_cap = max(limit, limit * 3 // max(1, (len(accessible) + _CHUNK_CLIENT_IDS - 1) // _CHUNK_CLIENT_IDS))

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
    for u in finalized_ids:
        p = get_user_profile(u) or {}
        fn = (p.get("full_name") or "").strip()
        if fn:
            name_by_uid[u] = fn

    out: list[dict[str, Any]] = []
    for r in rows:
        cg = str(r.get("client_gstin_id") or "")
        tn = trade_by_id.get(cg, {})
        fb = str(r.get("finalized_by") or "").strip()
        finalized_name = name_by_uid.get(fb) if fb else None
        row_out = dict(r)
        row_out["trade_name"] = tn.get("trade_name")
        row_out["client_gstin"] = tn.get("gstin")
        row_out["finalized_by_name"] = finalized_name
        out.append(row_out)
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
    return {"run_id": rid, "status": "MATCHING"}


@reconcile_runs_router.delete("/runs/{run_id}")
async def delete_reconcile_run(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)

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

    seen: set[str] = set()
    for key in r2_keys:
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            await delete_file(key)
        except Exception as exc:
            _log.warning("R2 delete failed for key %s: %s", key, exc)

    del_res = sb.table("reconciliation_run").delete().eq("id", rid).execute()
    if not del_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )

    uid = str(current_user.get("id", ""))
    await log_action(
        uid,
        "delete_run",
        "reconciliation_run",
        rid,
        {},
        ip_address=(request.client.host if request.client else None),
    )
    return {"message": "Run deleted successfully"}


@reconcile_runs_router.get("/runs/{run_id}/summary")
async def reconcile_run_summary(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    run_row = assert_run_accessible(sb, rid, current_user)
    p = ro.load_payload(sb, rid)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no reconciliation payload for this run",
        )
    uid = str(current_user.get("id", ""))
    return _build_reconcile_summary(
        sb, run_row=run_row, payload=p, current_user_id=uid
    )


def _payload_or_404(sb, rid: str) -> dict[str, Any]:
    p = ro.load_payload(sb, rid)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no reconciliation payload for this run",
        )
    return p


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
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
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
    return _paginated_body(rows, page, limit)


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
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
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
    return _paginated_body(rows, page, limit)


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
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    p = _payload_or_404(sb, rid)
    run_row = (
        sb.table("reconciliation_run")
        .select("period")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    period_label = ""
    if run_row.data:
        period_label = str((run_row.data[0] or {}).get("period") or "")
    rows = _build_late_match_rows(sb, rid=rid, payload=p, gstr2b_period_label=period_label)
    return {"data": rows, "total": len(rows)}


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
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
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

    pairs = _build_matched_pair_records(sb, rid=rid, payload=p, note_counts=notes)
    hn = bool(has_notes and has_notes.strip().lower() in ("true", "1", "yes"))
    rr_req = bool(review_required and review_required.strip().lower() in ("true", "1", "yes"))
    s174 = bool(section_17_5 and section_17_5.strip().lower() in ("true", "1", "yes"))
    filtered_pairs = _filter_matched(
        pairs,
        search_q=search,
        match_level_filter=match_level,
        amount_min_val=_parse_money(amount_min),
        amount_max_val=_parse_money(amount_max),
        require_notes=hn,
        review_required=rr_req,
        section174=s174,
    )
    extracted = [pair[0] for pair in filtered_pairs]
    if sort.endswith("desc"):
        extracted.sort(key=lambda x: (-x["amount"], x["id"]))
    else:
        extracted.sort(key=lambda x: (x["amount"], x["id"]))
    return _paginated_body(extracted, page, limit)


@reconcile_runs_router.get(
    "/runs/{run_id}/rule37/summary",
    response_model=Rule37SummaryResponse,
)
async def reconcile_run_rule37_summary(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    p = _payload_or_404(sb, rid)
    notes = _notes_count_for_run(sb, rid)
    body = _build_rule37_summary_payload(sb, rid, p, notes)
    return Rule37SummaryResponse(**body)


@reconcile_runs_router.get("/runs/{run_id}/rule37")
async def reconcile_run_rule37(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    p = _payload_or_404(sb, rid)
    via = _try_rule37_via_table(sb, rid, page, limit)
    if via is not None:
        return via
    notes = _notes_count_for_run(sb, rid)
    rows = _build_rule37_rows(sb, rid, p, notes)
    return _paginated_body(rows, page, limit)


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
    except Exception:
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
            detail="failed to update rule37 status",
        )


@reconcile_runs_router.get("/runs/{run_id}/section17")
async def reconcile_run_section175(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=250),
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    p = _payload_or_404(sb, rid)
    via = _try_section175_via_table(sb, rid, page, limit)
    if via is not None:
        return via
    notes = _notes_count_for_run(sb, rid)
    rows = _build_section175_rows(sb, rid, p, notes)
    return _paginated_body(rows, page, limit)


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
    return await _reconcile_finalize_core(
        request,
        sb,
        rid=rid,
        current_user=current_user,
        checklist_snapshot=body.checklist_snapshot,
    )


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
                rw.get("invoice_number", ""),
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
                rw.get("invoice_number", ""),
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
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
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
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
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
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(io.BytesIO(blob), media_type="text/csv", headers=headers)


@reconcile_runs_router.get("/runs/{run_id}/export/excel")
async def reconcile_export_excel_workbook(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    assert_run_accessible(sb, rid, current_user)
    p = _payload_or_404(sb, rid)
    uid = str(current_user.get("id", ""))
    run_ex = (
        sb.table("reconciliation_run")
        .select("id, period, status, client_gstin_id, finalized_at, finalized_by")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    run_row = (run_ex.data or [{}])[0]
    summ = _build_reconcile_summary(sb, run_row=run_row, payload=p, current_user_id=uid)
    prof = get_user_profile(uid) or {}
    firm_name = str(prof.get("firm_name") or "")
    gen_name = str(prof.get("full_name") or "")
    notes = _notes_count_for_run(sb, rid)
    matched_pairs = _build_matched_pair_records(sb, rid=rid, payload=p, note_counts=notes)
    missed = _build_missed_itc_records(
        sb,
        rid=rid,
        payload=p,
        note_counts=notes,
        source_software="your accounting software",
    )
    risk = _build_wrongful_risk_records(sb, rid=rid, payload=p, note_counts=notes)
    r37 = _build_rule37_rows(sb, rid, p, notes)
    s17 = _build_section175_rows(sb, rid, p, notes)
    blob, fn = build_excel_workbook_bytes(
        run_id=rid,
        firm_name=firm_name,
        client_trade_name=str(summ.get("client_name") or ""),
        period_raw=str(run_row.get("period") or ""),
        summary=summ,
        matched_pairs=matched_pairs,
        missed_rows=missed,
        risk_rows=risk,
        rule37_rows=r37,
        section17_rows=s17,
        generated_at=datetime.now(timezone.utc),
        generated_by_name=gen_name,
    )
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )

