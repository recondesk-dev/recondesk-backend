"""Supplier intelligence — `/api/intelligence`."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.auth import get_current_active_user
from app.constants import RunStatus
from app.database import get_supabase
from app.services import reconciliation_record_adapter as rec_adapt
from app.services.firm_access import (
    get_firm_owner_for_client,
    list_accessible_client_gstin_ids,
)
from app.services.vendor_intelligence import (
    calculate_supplier_score,
    score_to_api_dict,
    supplier_gstins_from_runs_history,
)

_log = logging.getLogger(__name__)
router = APIRouter()

RISK_ORDER = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _runs_history_grouped(flat_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape expected by vendor intelligence: one entry per run with nested *records*."""
    order: list[str] = []
    by_rid: dict[str, dict[str, Any]] = {}
    for rec in flat_records:
        rid = str(rec.get("reconciliation_run_id") or "").strip()
        if not rid:
            continue
        if rid not in by_rid:
            by_rid[rid] = {
                "run_id": rid,
                "period_end_date": rec.get("period_end_date"),
                "records": [],
            }
            order.append(rid)
        by_rid[rid]["records"].append(dict(rec))
    return [by_rid[k] for k in order]


def _normalize_intel_row(g: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    m = rec_adapt.gstr_db_row_to_matcher_row(g)
    rd = g.get("record_data") if isinstance(g.get("record_data"), dict) else {}
    adp = g.get("amount_difference_paise")
    if adp is None:
        adp = rd.get("amount_difference_paise")
    ref = g.get("gstr2b_reflection_date")
    if ref is None:
        ref = rd.get("gstr2b_reflection_date")
    pend = run.get("gstr_period_end") or run.get("period_end_date")
    run_id = str(g.get("run_id") or run.get("id") or "").strip()
    return {
        "supplier_gstin": str(m.get("supplier_gstin") or "").strip().upper(),
        "invoice_number": str(m.get("invoice_number_normalized") or "").strip(),
        "invoice_date": m.get("invoice_date"),
        "reconciliation_run_id": run_id,
        "amount_difference_paise": adp,
        "gstr2b_reflection_date": ref,
        "period_end_date": pend,
        "created_at": g.get("created_at"),
    }


@router.get("/suppliers/{client_gstin_id}")
async def get_supplier_intelligence(
    client_gstin_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    cg = str(client_gstin_id).strip()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cg not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )

    batch_size = 2000
    offset = 0
    raw_joined: list[dict[str, Any]] = []
    while True:
        q = (
            sb.table("gstr_records")
            .select(
                "id, run_id, client_gstin_id, period, record_data, created_at, "
                "amount_difference_paise, gstr2b_reflection_date, "
                "reconciliation_run!inner(id, status, gstr_period_end, client_gstin_id)"
            )
            .eq("client_gstin_id", cg)
            .eq("reconciliation_run.status", RunStatus.COMPLETED)
            .range(offset, offset + batch_size - 1)
        )
        r = q.execute()
        rows = r.data or []
        for g in rows:
            run = g.get("reconciliation_run") or {}
            if str(run.get("client_gstin_id") or "").strip() != cg:
                continue
            raw_joined.append(_normalize_intel_row(g, run))
        if len(rows) < batch_size:
            break
        offset += batch_size

    runs_history = _runs_history_grouped(raw_joined)

    pair_keys: set[tuple[str, str]] = set()
    for rec in raw_joined:
        sg = str(rec.get("supplier_gstin") or "").strip().upper()
        rid = str(rec.get("reconciliation_run_id") or "").strip()
        if sg and rid:
            pair_keys.add((sg, rid))
    if len(pair_keys) > 500:
        _log.warning(
            "vendor intelligence: %s supplier-run pairs (>500) for client_gstin_id=%s",
            len(pair_keys),
            cg,
        )

    suppliers_set = supplier_gstins_from_runs_history(runs_history)
    if not suppliers_set:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "insufficient_data",
                "min_appearances_required": 2,
                "message": "No suppliers found in 2+ completed runs.",
            },
        )

    firm_owner = get_firm_owner_for_client(sb, cg)
    supplier_list = sorted(suppliers_set)
    name_by_gstin: dict[str, str] = {}
    for i in range(0, len(supplier_list), 500):
        chunk = supplier_list[i : i + 500]
        res = (
            sb.table("client_gstins")
            .select("gstin, trade_name")
            .eq("firm_owner_id", firm_owner)
            .in_("gstin", chunk)
            .execute()
        )
        for row in res.data or []:
            gsn = str(row.get("gstin") or "").strip().upper()
            if gsn:
                name_by_gstin[gsn] = str(row.get("trade_name") or "").strip()

    suppliers: list[dict[str, Any]] = []
    excluded_low_data_suppliers = 0
    for sg in supplier_list:
        tn = name_by_gstin.get(sg, "")
        score = calculate_supplier_score(sg, tn, runs_history)
        if score is None:
            excluded_low_data_suppliers += 1
            continue
        suppliers.append(score_to_api_dict(sg, tn, score))

    if not suppliers:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "insufficient_data",
                "min_appearances_required": 2,
                "message": "No suppliers found in 2+ completed runs.",
            },
        )

    suppliers.sort(
        key=lambda x: (
            RISK_ORDER.get(str(x.get("risk_level") or ""), 99),
            str(x.get("supplier_gstin") or ""),
        )
    )

    return {
        "suppliers": suppliers,
        "excluded_low_data_suppliers": excluded_low_data_suppliers,
        "total_eligible_suppliers": len(suppliers),
    }
