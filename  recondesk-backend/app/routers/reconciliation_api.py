"""Reconciliation results, history, diff, summary, finalize — `/api/reconciliation`."""

from __future__ import annotations

import csv
import io
import logging
import math
import re
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional, TypeVar

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
from app.services.reconcile_export_workbook import (
    build_excel_workbook_bytes,
    build_pdf_summary_bytes,
)
from app.utils.audit import log_action
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
    gstr_m = ro.load_gstr_map(sb, rid)
    matched_n = len(engine.get("matched") or [])
    n_g = len(gstr_m)

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
    wrongful_total_rupees = sum(
        _paise_to_rupees(int(w.get("taxable_amount_paise") or 0)) for w in wr_list
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

    return {
        "run_id": rid,
        "client_name": client_display,
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
    out = []
    for mi in engine.get("missed_itc") or []:
        gid = str(mi.get("gstr_id", "")).strip()
        cell = gstr_db.get(gid) or {}
        mt = cell.get("matcher") or {}
        rd = cell.get("record_data") if isinstance(cell.get("record_data"), dict) else {}
        amt_paise = int(mi.get("total_tax_paise") or mt.get("total_tax_paise") or 0)
        amt = _paise_to_rupees(amt_paise)
        dout = generate_decision(
            "MISSED_ITC",
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
                "decision_status": "pending",
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
    out = []
    for w in engine.get("wrongful_itc_risk") or []:
        pid = str(w.get("id", "")).strip()
        row_id = f"wr:{pid}"
        cell = pr_db.get(pid) or {}
        mt = cell.get("matcher") or {}
        rd = cell.get("record_data") if isinstance(cell.get("record_data"), dict) else {}
        amt = _paise_to_rupees(
            int(w.get("taxable_amount_paise") or mt.get("taxable_amount_paise") or 0)
        )
        dout = generate_decision(
            "WRONGFUL_ITC",
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
                "decision_status": "pending",
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

        discrep: Optional[str] = None
        if getattr(orow, "match_status", "") == "MISMATCHED" and orow is not None:
            discrep = (
                f"GST tax delta (Δpaise): {int(orow.total_tax_diff_paise):,}"
            )

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
            "discrepancy_note": discrep,
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





def _build_rule37_rows(sb, rid: str, payload: dict[str, Any], note_counts: Counter[str]) -> list[dict[str, Any]]:
    dec = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    lst = []
    lst.extend(list(dec.get("rule37") or []))
    lst.extend(list(comp.get("rule37") or []))
    uniq: dict[str, dict[str, Any]] = {}
    for item in lst:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("pr_id") or "").strip()
        key = pid or id(item)
        if key in uniq:
            continue
        uniq[str(key)] = item
    out: list[dict[str, Any]] = []
    for ru in uniq.values():
        pr_id_actual = ru.get("pr_id")
        amt = _paise_to_rupees(int(ru.get("itc_at_risk_paise") or 0))
        row_id = f"r37:{pr_id_actual or id(ru)}"
        ur = _rule37_urgency_from_status(ru.get("status"))
        out.append(
            {
                "id": row_id,
                "supplier_gstin": str(ru.get("supplier_gstin") or ""),
                "invoice_number": str(ru.get("invoice_number") or ""),
                "invoice_date": str(ru.get("invoice_date") or "")[:40],
                "amount": amt,
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
            }
        )
    out.sort(key=lambda x: (-x["amount"], x["id"]))
    return out


def _try_rule37_via_table(sb, rid: str, page: int, limit: int) -> Optional[dict[str, Any]]:
    for col in ("reconciliation_run_id", "run_id"):
        try:
            off = max(0, (page - 1) * limit)
            qr = sb.table("rule37_warnings").select("*", count="exact").eq(col, rid)  # type: ignore[arg-type]
            qr = qr.range(off, off + limit - 1)
            exe = qr.execute()
            total = exe.count if getattr(exe, "count", None) is not None else len(exe.data or [])
            chunk = exe.data or []
            body = [_db_rule37_warning_to_frontend(row) for row in chunk]
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
    return {
        "id": rid_str,
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
        "rule37_urgency": _rule37_urgency_from_status(row.get("status")),
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


@reconcile_runs_router.get("/runs/{run_id}/itc")
async def reconcile_run_itc_bucket(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
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
    limit: int = Query(50, ge=1, le=200),
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
    limit: int = Query(50, ge=1, le=200),
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


@reconcile_runs_router.get("/runs/{run_id}/rule37")
async def reconcile_run_rule37(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
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


@reconcile_runs_router.get("/runs/{run_id}/section17")
async def reconcile_run_section175(
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
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


@reconcile_runs_router.get("/runs/{run_id}/export/pdf")
async def reconcile_export_pdf_summary(
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
    notes = _notes_count_for_run(sb, rid)
    missed = _build_missed_itc_records(
        sb,
        rid=rid,
        payload=p,
        note_counts=notes,
        source_software="your accounting software",
    )
    risk = _build_wrongful_risk_records(sb, rid=rid, payload=p, note_counts=notes)
    r37 = _build_rule37_rows(sb, rid, p, notes)
    missed_sorted = sorted(
        missed,
        key=lambda x: (-float(x.get("amount") or 0), str(x.get("id") or "")),
    )
    risk_sorted = sorted(
        risk,
        key=lambda x: (-float(x.get("amount") or 0), str(x.get("id") or "")),
    )
    blob, fn = build_pdf_summary_bytes(
        firm_name=firm_name,
        client_trade_name=str(summ.get("client_name") or ""),
        period_raw=str(run_row.get("period") or ""),
        run_status=str(summ.get("status") or ""),
        summary=summ,
        top_missed=missed_sorted[:3],
        top_risk=risk_sorted[:3],
        rule37_count=len(r37),
        generated_at=datetime.now(timezone.utc),
        watermark_text=firm_name or "ReconDesk",
    )
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/pdf",
        headers=headers,
    )
