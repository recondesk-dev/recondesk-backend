"""GSTR-2A vs GSTR-2B Delta Reconciliation API Router — /api/gstr2a-delta/*."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase
from app.parsers.gstr2a_parser import parse_gstr2a
from app.services.firm_access import list_accessible_client_gstin_ids
from app.services.gst_fetch import gstr2a as gstr2a_fetch
from app.services.gst_fetch.token import ensure_fresh_gstn_token, load_client_gstin
from app.services.gstr2a_vs_2b import (
    ALL_CATEGORIES,
    get_default_cutoff_date,
    reconcile_2a_vs_2b,
)
from app.services.reconciliation_record_adapter import gstr_db_row_to_matcher_row

logger = logging.getLogger(__name__)

router = APIRouter()


class RunDeltaReconciliationRequest(BaseModel):
    client_gstin_id: str = Field(..., description="Client GSTIN ID (UUID)")
    period: str = Field(..., description="Tax period (YYYY-MM or MMYYYY)")
    cutoff_date: Optional[str] = Field(None, description="Optional custom cutoff date YYYY-MM-DD")
    gstr2a_records: Optional[list[dict[str, Any]]] = Field(
        None, description="Pre-parsed 2A records or raw 2A payload items"
    )
    gstr2a_raw: Optional[dict[str, Any]] = Field(
        None, description="Raw GSTR-2A JSON payload if provided"
    )
    gstr2b_records: Optional[list[dict[str, Any]]] = Field(
        None, description="Pre-parsed 2B records if provided"
    )


def _assert_client_access(sb, current_user: dict, client_id: str) -> None:
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if client_id not in allowed:
        logger.warning("Access denied for client_id=%s, user=%s", client_id, current_user.get("id"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this client GSTIN",
        )


def _split_period_year_month(period: str) -> tuple[str, str]:
    """Return (YYYY, MM) strings from period."""
    s = period.strip().replace("-", "").replace("/", "")
    if len(s) == 6 and s.isdigit():
        if s.startswith(("20", "19")):
            return s[:4], s[4:6]
        else:
            return s[2:6], s[:2]
    if len(period) >= 7 and period[4] == "-":
        parts = period.split("-")
        return parts[0], f"{int(parts[1]):02d}"
    today = date.today()
    return f"{today.year:04d}", f"{today.month:02d}"


def _fetch_2b_records_from_db(sb, client_gstin_id: str, period: str) -> list[dict[str, Any]]:
    """Query 2B records from gstr_records table for client and period."""
    records_2b: list[dict[str, Any]] = []

    # Format variations (e.g. 2026-06 and 062026)
    year, month = _split_period_year_month(period)
    p_iso = f"{year}-{month}"
    p_mmyyyy = f"{month}{year}"
    periods_to_check = list({period, p_iso, p_mmyyyy})

    # 1. Direct query by client_gstin_id and period
    try:
        res = (
            sb.table("gstr_records")
            .select("id, record_data")
            .eq("client_gstin_id", client_gstin_id)
            .in_("period", periods_to_check)
            .limit(5000)
            .execute()
        )
        if res.data:
            for r in res.data:
                records_2b.append(gstr_db_row_to_matcher_row(r))
            return records_2b
    except Exception as exc:
        logger.debug("Direct gstr_records query by client_gstin_id failed: %s", exc)

    # 2. Lookup via latest reconciliation_run
    try:
        run_res = (
            sb.table("reconciliation_run")
            .select("id")
            .eq("client_gstin_id", client_gstin_id)
            .in_("period", periods_to_check)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if run_res.data:
            run_id = run_res.data[0]["id"]
            rec_res = (
                sb.table("gstr_records")
                .select("id, record_data")
                .eq("run_id", run_id)
                .limit(5000)
                .execute()
            )
            if rec_res.data:
                for r in rec_res.data:
                    records_2b.append(gstr_db_row_to_matcher_row(r))
                return records_2b
    except Exception as exc:
        logger.debug("reconciliation_run lookup for gstr_records failed: %s", exc)

    return records_2b


@router.post("/run")
async def run_gstr2a_delta(
    body: RunDeltaReconciliationRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Run GSTR-2A vs GSTR-2B Delta Reconciliation.

    Categorizes invoices into:
    - IN_BOTH: Matched in both 2A and 2B
    - LATE_FILED: Filed after the 13th cutoff (ITC deferred to next month)
    - FILED_NOT_REFLECTED: Filed on time but missing from 2B
    - IN_2B_NOT_2A: Present in 2B but missing from 2A
    - VALUE_MISMATCH: Present in both but differing amounts (> 1% tolerance)
    """
    sb = get_supabase()
    _assert_client_access(sb, current_user, body.client_gstin_id)

    # 1. Resolve 2A records
    records_2a: list[dict[str, Any]] = []
    if body.gstr2a_raw:
        try:
            records_2a = parse_gstr2a(body.gstr2a_raw)
        except Exception as exc:
            logger.exception("Failed to parse provided gstr2a_raw")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to parse GSTR-2A JSON: {exc}",
            ) from exc
    elif body.gstr2a_records is not None:
        # If passed records look like raw payload items or already normalized
        records_2a = body.gstr2a_records
    else:
        # Attempt auto-fetch from GSP API
        try:
            client_row = load_client_gstin(sb, body.client_gstin_id)
            gstin = client_row.get("gstin")
            if not gstin:
                raise ValueError("Client GSTIN is missing")
            token = await asyncio.to_thread(ensure_fresh_gstn_token, sb, client_row)
            year, month = _split_period_year_month(body.period)
            raw_payload = await asyncio.to_thread(
                gstr2a_fetch.fetch, gstin=gstin, year=year, month=month, token=token
            )
            records_2a = parse_gstr2a(raw_payload)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("GSTR-2A auto-fetch failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"GSTR-2A records not provided and live GSTN fetch failed: {exc}. "
                    "Please provide gstr2a_raw or gstr2a_records."
                ),
            ) from exc

    # 2. Resolve 2B records
    records_2b: list[dict[str, Any]] = []
    if body.gstr2b_records is not None:
        records_2b = body.gstr2b_records
    else:
        records_2b = _fetch_2b_records_from_db(sb, body.client_gstin_id, body.period)

    # 3. Reconcile
    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period=body.period,
        cutoff_date=body.cutoff_date,
    )

    # 4. Determine cutoff date string
    cutoff_date_str = (
        body.cutoff_date
        if body.cutoff_date
        else get_default_cutoff_date(body.period).isoformat()
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    # 5. Persist results in Supabase
    save_payload = {
        "client_gstin_id": body.client_gstin_id,
        "period": body.period,
        "cutoff_date": cutoff_date_str,
        "reconciled_at": now_iso,
        "summary": summary,
        "results": results,
        "updated_at": now_iso,
    }
    try:
        sb.table("gstr2a_delta_results").upsert(
            save_payload,
            on_conflict="client_gstin_id,period",
        ).execute()
    except Exception as exc:
        logger.exception("Failed to save gstr2a_delta_results to database: %s", exc)

    return {
        "client_gstin_id": body.client_gstin_id,
        "period": body.period,
        "cutoff_date": cutoff_date_str,
        "reconciled_at": now_iso,
        "summary": summary,
        "results": results,
    }


@router.get("/{client_gstin_id}/{period}")
async def get_gstr2a_delta_results(
    client_gstin_id: str,
    period: str,
    category: Optional[str] = Query(None, description="Filter by category: IN_BOTH, LATE_FILED, etc."),
    search: Optional[str] = Query(None, description="Search by supplier GSTIN or invoice number"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve saved GSTR-2A vs GSTR-2B delta results with filtering and pagination."""
    sb = get_supabase()
    _assert_client_access(sb, current_user, client_gstin_id)

    # Query saved delta results
    year, month = _split_period_year_month(period)
    p_iso = f"{year}-{month}"
    p_mmyyyy = f"{month}{year}"
    periods_to_check = list({period, p_iso, p_mmyyyy})

    res = (
        sb.table("gstr2a_delta_results")
        .select("*")
        .eq("client_gstin_id", client_gstin_id)
        .in_("period", periods_to_check)
        .limit(1)
        .execute()
    )

    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GSTR-2A delta results found for client {client_gstin_id} and period {period}",
        )

    row = res.data[0]
    all_results: list[dict[str, Any]] = row.get("results") or []

    # Category filter
    filtered = all_results
    if category:
        cat_clean = category.strip().upper()
        filtered = [r for r in filtered if str(r.get("category", "")).upper() == cat_clean]

    # Search filter
    if search:
        s_clean = search.strip().lower()
        filtered = [
            r
            for r in filtered
            if s_clean in str(r.get("supplier_gstin", "")).lower()
            or s_clean in str(r.get("invoice_number", "")).lower()
            or s_clean in str(r.get("supplier_name", "")).lower()
        ]

    total_records = len(filtered)
    start_idx = (page - 1) * page_size
    paged_results = filtered[start_idx : start_idx + page_size]

    return {
        "client_gstin_id": client_gstin_id,
        "period": row.get("period"),
        "cutoff_date": row.get("cutoff_date"),
        "reconciled_at": row.get("reconciled_at"),
        "summary": row.get("summary") or {},
        "total_records": total_records,
        "page": page,
        "page_size": page_size,
        "results": paged_results,
    }


@router.get("/{client_gstin_id}/{period}/summary")
async def get_gstr2a_delta_summary(
    client_gstin_id: str,
    period: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve summary metrics for GSTR-2A vs GSTR-2B delta reconciliation."""
    sb = get_supabase()
    _assert_client_access(sb, current_user, client_gstin_id)

    year, month = _split_period_year_month(period)
    p_iso = f"{year}-{month}"
    p_mmyyyy = f"{month}{year}"
    periods_to_check = list({period, p_iso, p_mmyyyy})

    res = (
        sb.table("gstr2a_delta_results")
        .select("id, client_gstin_id, period, cutoff_date, reconciled_at, summary")
        .eq("client_gstin_id", client_gstin_id)
        .in_("period", periods_to_check)
        .limit(1)
        .execute()
    )

    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GSTR-2A delta summary found for client {client_gstin_id} and period {period}",
        )

    row = res.data[0]
    return {
        "client_gstin_id": client_gstin_id,
        "period": row.get("period"),
        "cutoff_date": row.get("cutoff_date"),
        "reconciled_at": row.get("reconciled_at"),
        "summary": row.get("summary") or {},
    }
