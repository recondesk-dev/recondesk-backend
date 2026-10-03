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
from app.integrations.gstr2b_autofetch import get_gstr2b
from app.parsers.gstr2a_parser import parse_gstr2a
from app.parsers.gstr2b_parser import parse_gstr2b
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
    gstr2b_raw: Optional[dict[str, Any]] = Field(
        None, description="Raw GSTR-2B JSON payload if provided"
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


def _resolve_latest_2b_run(
    sb,
    client_gstin_id: str,
    period: str,
    expected_gstin: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Locate the latest valid, non-deleted GSTR-2B reconciliation run for a client and period.

    Returns dict containing run metadata + provenance, or None if no valid run exists.
    """
    year, month = _split_period_year_month(period)
    p_iso = f"{year}-{month}"
    p_mmyyyy = f"{month}{year}"
    periods_to_check = list({period, p_iso, p_mmyyyy, f"{p_iso}-01"})

    try:
        # 1. Query reconciliation_run for completed / active runs with GSTR records
        run_res = (
            sb.table("reconciliation_run")
            .select("id, client_gstin_id, period, status, gstr_records_imported, created_at, updated_at")
            .eq("client_gstin_id", client_gstin_id)
            .in_("period", periods_to_check)
            .gt("gstr_records_imported", 0)
            .not_.in_("status", ["failed", "FAILED", "cancelled", "CANCELLED"])
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        candidates = run_res.data or []
        if not candidates:
            return None

        candidate_ids = [str(c["id"]) for c in candidates]

        # 2. Check reconciliation_import_runs for soft-delete or richer file metadata
        import_map: dict[str, dict[str, Any]] = {}
        from app.repositories.wizard import get_wizard_repository
        w_repo = get_wizard_repository()
        if w_repo is not None:
            try:
                for row in w_repo.get_runs_by_ids(candidate_ids):
                    import_map[str(row["id"])] = row
            except Exception as exc:
                logger.debug("Aurora candidate runs lookup failed: %s", exc)

        if not import_map:
            try:
                imp_res = (
                    sb.table("reconciliation_import_runs")
                    .select("id, gstr2b_file_name, gstr2b_file_size, gstr2b_uploaded_at, gstr2b_deleted_at, gstr2b_record_count")
                    .in_("id", candidate_ids)
                    .execute()
                )
                for row in (imp_res.data or []):
                    import_map[str(row["id"])] = row
            except Exception as exc:
                logger.debug("reconciliation_import_runs lookup failed: %s", exc)

        # 3. Pick latest run that was not soft-deleted
        for run in candidates:
            rid = str(run["id"])
            imp = import_map.get(rid)
            if imp and imp.get("gstr2b_deleted_at"):
                # GSTR-2B file was deleted in Manage Data
                continue

            file_name = imp.get("gstr2b_file_name") if imp else None
            source_type = "reconciliation_import"
            if file_name:
                fn_lower = file_name.lower().strip()
                if fn_lower.endswith(".json"):
                    source_type = "portal_json"
                elif fn_lower.endswith((".xlsx", ".xls")):
                    source_type = "excel_recon"

            imported_count = (
                imp.get("gstr2b_record_count")
                if imp and imp.get("gstr2b_record_count") is not None
                else run.get("gstr_records_imported") or 0
            )

            uploaded_at = (
                imp.get("gstr2b_uploaded_at")
                if imp and imp.get("gstr2b_uploaded_at")
                else run.get("created_at")
            )

            return {
                "run_id": rid,
                "client_gstin_id": client_gstin_id,
                "period": run.get("period"),
                "status": run.get("status"),
                "source_type": source_type,
                "file_name": file_name,
                "file_size": imp.get("gstr2b_file_size") if imp else None,
                "uploaded_at": uploaded_at,
                "record_count": int(imported_count or 0),
            }

        return None
    except Exception as exc:
        logger.warning("_resolve_latest_2b_run failed for client %s period %s: %s", client_gstin_id, period, exc)
        return None


def _fetch_2b_records_for_run(
    sb,
    run_id: str,
    expected_gstin: Optional[str] = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Paginate and fetch all GSTR-2B records strictly for a single reconciliation run_id.

    Bypasses the Supabase PostgREST default 1,000-row limit using chunked range queries.
    Preserves document types and validates buyer_gstin if provided.
    Returns (records_2b, doc_type_counts).
    """
    records_2b: list[dict[str, Any]] = []
    doc_type_counts: dict[str, int] = {}
    page_size = 1000
    offset = 0

    exp_gstin_clean = expected_gstin.strip().upper() if expected_gstin else None

    while True:
        try:
            res = (
                sb.table("gstr_records")
                .select("id, record_data")
                .eq("run_id", run_id)
                .order("id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                break

            for r in rows:
                rd = r.get("record_data")
                if not isinstance(rd, dict):
                    continue

                # Buyer GSTIN validation (if present and expected_gstin provided)
                buyer = str(rd.get("buyer_gstin") or "").strip().upper()
                if buyer and exp_gstin_clean and buyer != exp_gstin_clean:
                    logger.debug(
                        "Skipping record %s: buyer_gstin %s does not match client GSTIN %s",
                        r.get("id"), buyer, exp_gstin_clean
                    )
                    continue

                # Document type tracking
                raw_dt = str(
                    rd.get("doc_type")
                    or rd.get("document_type")
                    or ("CREDIT_NOTE" if rd.get("section") == "cdnr" else "INVOICE")
                ).strip().upper()
                doc_type_counts[raw_dt] = doc_type_counts.get(raw_dt, 0) + 1

                matcher_row = gstr_db_row_to_matcher_row(r)
                records_2b.append(matcher_row)

            offset += len(rows)
            if len(rows) < page_size:
                break
        except Exception as exc:
            logger.warning("_fetch_2b_records_for_run failed at offset %d: %s", offset, exc)
            break

    return records_2b, doc_type_counts


def _fetch_2b_records_from_db(
    sb,
    client_gstin_id: str,
    period: str,
    expected_gstin: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Query 2B records strictly from the latest valid reconciliation run for client and period."""
    run_meta = _resolve_latest_2b_run(sb, client_gstin_id, period, expected_gstin)
    if not run_meta:
        return []
    records, _ = _fetch_2b_records_for_run(sb, run_meta["run_id"], expected_gstin)
    return records


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
    live_gstn_token: Optional[str] = None
    gstin_val: Optional[str] = None
    year_val: Optional[str] = None
    month_val: Optional[str] = None

    try:
        client_row_init = load_client_gstin(sb, body.client_gstin_id)
        gstin_val = client_row_init.get("gstin")
    except Exception:
        pass

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
            live_gstn_token = token
            gstin_val = gstin
            year_val, month_val = year, month
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
    if body.gstr2b_raw:
        try:
            raw_2b_payload = body.gstr2b_raw
            if "data" not in raw_2b_payload and isinstance(raw_2b_payload, dict):
                raw_2b_payload = {"data": raw_2b_payload}
            parsed_2b = parse_gstr2b(raw_2b_payload)
            records_2b = parsed_2b.get("records", [])
        except Exception as exc:
            logger.exception("Failed to parse provided gstr2b_raw")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to parse GSTR-2B JSON: {exc}",
            ) from exc
    elif body.gstr2b_records is not None:
        records_2b = body.gstr2b_records
    else:
        # First check DB (existing reconciliation or gstr_records)
        records_2b = _fetch_2b_records_from_db(sb, body.client_gstin_id, body.period, gstin_val)
        # If no 2B records in DB and live GSTN session is active, attempt live auto-fetch
        if not records_2b and live_gstn_token and gstin_val and year_val and month_val:
            try:
                raw_2b = await asyncio.to_thread(
                    get_gstr2b,
                    access_token=live_gstn_token,
                    gstin=gstin_val,
                    year=year_val,
                    month=month_val,
                )
                if "data" not in raw_2b and isinstance(raw_2b, dict):
                    raw_2b = {"data": raw_2b}
                parsed_2b = parse_gstr2b(raw_2b)
                records_2b = parsed_2b.get("records", [])
            except Exception as exc:
                logger.warning("GSTR-2B live auto-fetch fallback failed: %s", exc)

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

    # 5. Persist results in Aurora (Primary) with Supabase Fallback
    save_payload = {
        "client_gstin_id": body.client_gstin_id,
        "period": body.period,
        "cutoff_date": cutoff_date_str,
        "reconciled_at": now_iso,
        "summary": summary,
        "results": results,
        "updated_at": now_iso,
    }
    saved_to_aurora = False
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        repo.save_gstr2a_delta(
            client_gstin_id=body.client_gstin_id,
            period=body.period,
            summary=summary,
            results=results,
            reconciled_at=now_iso,
            cutoff_date=cutoff_date_str,
        )
        saved_to_aurora = True
    except Exception as exc:
        logger.warning("Aurora save_gstr2a_delta failed, falling back to Supabase: %s", exc)

    if not saved_to_aurora:
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

    # ── Aurora Primary ────────────────────────────────────────────────────────
    row = None
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        row = repo.get_gstr2a_delta(client_gstin_id=client_gstin_id, period=period)
    except Exception as exc:
        logger.warning("Aurora get_gstr2a_delta failed, falling back to Supabase: %s", exc)

    if not row:
        # Query saved delta results from Supabase fallback
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
        if res.data:
            row = res.data[0]

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GSTR-2A delta results found for client {client_gstin_id} and period {period}",
        )

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

    # ── Aurora Primary ────────────────────────────────────────────────────────
    row = None
    try:
        from app.repositories.return_reconciliation import get_return_reconciliation_repository
        repo = get_return_reconciliation_repository()
        row = repo.get_gstr2a_delta(client_gstin_id=client_gstin_id, period=period)
    except Exception as exc:
        logger.warning("Aurora get_gstr2a_delta_summary failed, falling back to Supabase: %s", exc)

    if not row:
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
        if res.data:
            row = res.data[0]

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GSTR-2A delta summary found for client {client_gstin_id} and period {period}",
        )

    return {
        "client_gstin_id": client_gstin_id,
        "period": row.get("period"),
        "cutoff_date": row.get("cutoff_date"),
        "reconciled_at": row.get("reconciled_at"),
        "summary": row.get("summary") or {},
    }


@router.get("/{client_gstin_id}/{period}/sources")
async def get_gstr2a_delta_sources(
    client_gstin_id: str,
    period: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Check availability of GSTR-2B records in DB for the given client and period."""
    sb = get_supabase()
    _assert_client_access(sb, current_user, client_gstin_id)

    client_row = None
    try:
        client_row = load_client_gstin(sb, client_gstin_id)
    except Exception:
        pass
    expected_gstin = client_row.get("gstin") if client_row else None

    run_meta = _resolve_latest_2b_run(sb, client_gstin_id, period, expected_gstin)
    records_2b = _fetch_2b_records_from_db(sb, client_gstin_id, period, expected_gstin)

    doc_type_counts: dict[str, int] = {}
    for r in records_2b:
        rd = r.get("record_data") if isinstance(r.get("record_data"), dict) else r
        dt = str(
            rd.get("doc_type")
            or rd.get("document_type")
            or r.get("doc_type")
            or ("CREDIT_NOTE" if rd.get("section") == "cdnr" else "INVOICE")
        ).strip().upper()
        doc_type_counts[dt] = doc_type_counts.get(dt, 0) + 1

    return {
        "client_gstin_id": client_gstin_id,
        "period": period,
        "has_2b_in_db": len(records_2b) > 0,
        "records_2b_count": len(records_2b),
        "source_type": run_meta.get("source_type") if run_meta else None,
        "run_id": run_meta.get("run_id") if run_meta else None,
        "file_name": run_meta.get("file_name") if run_meta else None,
        "uploaded_at": run_meta.get("uploaded_at") if run_meta else None,
        "doc_type_counts": doc_type_counts,
    }

