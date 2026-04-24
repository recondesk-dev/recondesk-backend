"""Reconciliation results, history, diff, summary, finalize — `/api/reconciliation`."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from uuid import UUID

from app.auth import get_current_active_user, get_user_role
from app.constants import RunStatus
from app.database import get_supabase, get_user_profile
from app.services import reconciliation_outcomes as ro
from app.services.firm_access import (
    assert_run_accessible,
    list_accessible_client_gstin_ids,
)
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
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    uid = str(current_user.get("id", ""))
    role = await get_user_role(uid)
    if (role or "").strip().lower() == "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only CA principals (admin) can finalize reconciliation runs.",
        )
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    # Debug: 404 "run not found" is raised when *reconciliation_run* has no row for
    # this id. 403 "run not accessible" is when the run exists but client_gstin_id is
    # not in list_accessible (firm_owner_id / assigned_to vs user_profiles.id).
    prof_dbg = get_user_profile(uid) or {}
    role_dbg = (prof_dbg.get("role") or "staff").strip().lower()
    run_dbg = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not (run_dbg.data or []):
        _log.info(
            "finalize access debug: no reconciliation_run row (this yields 404). "
            "user_id=%s run_id=%s role=%s",
            uid,
            rid,
            role_dbg,
        )
    else:
        cgid = str((run_dbg.data[0] or {}).get("client_gstin_id", "") or "").strip()
        cgr = (
            sb.table("client_gstins")
            .select("id, firm_owner_id, assigned_to, gstin, is_active")
            .eq("id", cgid)
            .limit(1)
            .execute()
        )
        cgrow = (cgr.data or [None])[0] or {}
        try:
            allowed = list_accessible_client_gstin_ids(sb, current_user)
        except Exception as exc:
            allowed = set()
            _log.info(
                "finalize access debug: list_accessible_client_gstin_ids failed: %s",
                exc,
            )
        if role_dbg == "admin":
            own = (
                sb.table("client_gstins")
                .select("id, firm_owner_id")
                .eq("firm_owner_id", uid)
                .eq("is_active", True)
                .execute()
            )
            _log.info(
                "finalize access debug: user_id=%s run_id=%s role=admin run.client_gstin_id=%s "
                "client_gstin id=%s firm_owner_id=%s assigned_to=%s is_active=%s "
                "client_in_accessible_set=%s admin_owned_client_rows=%s sample_owned_ids=%s",
                uid,
                rid,
                cgid,
                cgrow.get("id"),
                cgrow.get("firm_owner_id"),
                cgrow.get("assigned_to"),
                cgrow.get("is_active"),
                cgid in allowed,
                len(own.data or []),
                [str(x.get("id")) for x in (own.data or [])[:8]],
            )
        else:
            _log.info(
                "finalize access debug: user_id=%s run_id=%s role=%s run.client_gstin_id=%s "
                "client_gstin firm_owner_id=%s assigned_to=%s is_active=%s "
                "client_in_accessible_set=%s accessible_id_count=%s",
                uid,
                rid,
                role_dbg,
                cgid,
                cgrow.get("firm_owner_id"),
                cgrow.get("assigned_to"),
                cgrow.get("is_active"),
                cgid in allowed,
                len(allowed),
            )
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
