"""Advanced Export API — ``POST /api/export/advanced``."""

from __future__ import annotations

import io
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase, get_user_profile
from app.services.advanced_export_pdf import build_advanced_export_pdf_bytes
from app.services.advanced_export_service import (
    ALL_EXPORT_STATUSES,
    apply_filters,
    available_itc_categories,
    collect_export_rows,
    summarize_rows,
)
from app.services.advanced_export_workbook import build_advanced_export_xlsx_bytes
from app.services.firm_access import assert_run_accessible
from app.services import reconciliation_outcomes as ro
from app.utils.audit import client_display_label, log_audit

_log = logging.getLogger(__name__)

router = APIRouter()


class AdvancedExportFilters(BaseModel):
    status: list[str] = Field(default_factory=list)
    client_id: list[str] = Field(default_factory=list)
    period: Optional[str] = None
    itc_category: list[str] = Field(default_factory=list)


class AdvancedExportRequest(BaseModel):
    reconciliation_id: Optional[str] = None
    run_id: Optional[str] = None
    filters: AdvancedExportFilters = Field(default_factory=AdvancedExportFilters)
    format: Literal["xlsx", "pdf", "preview"] = "xlsx"


def _resolve_run_id(body: AdvancedExportRequest) -> str:
    rid = (body.run_id or body.reconciliation_id or "").strip()
    if not rid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_id or reconciliation_id is required",
        )
    return rid


def _load_run_context(sb, rid: str, current_user: dict) -> tuple[dict[str, Any], dict[str, Any], str]:
    run_row = assert_run_accessible(sb, rid, current_user)
    payload = ro.load_payload(sb, rid)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no reconciliation payload for this run",
        )
    # Prefer a fresh select for period / client fields used in export metadata.
    run_ex = (
        sb.table("reconciliation_run")
        .select("id, period, status, client_gstin_id")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    fresh = (run_ex.data or [None])[0] or run_row
    cg_id = str(fresh.get("client_gstin_id") or "")
    client_name = client_display_label(sb, cg_id) if cg_id else ""
    return fresh, payload, client_name


async def _log_advanced_export(
    sb,
    current_user: dict,
    run_row: dict,
    run_id: str,
    export_type: str,
) -> None:
    cg_id = str(run_row.get("client_gstin_id") or "")
    period = str(run_row.get("period") or "")
    client_name = client_display_label(sb, cg_id) if cg_id else "Client"
    label = f"{client_name} ({period})" if period else client_name
    await log_audit(
        sb,
        current_user,
        "RESULT_EXPORTED",
        "reconciliation",
        run_id,
        label,
        {"export_type": export_type},
    )


@router.post("/advanced")
async def advanced_export(
    body: AdvancedExportRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Filtered reconciliation export as xlsx/pdf, or JSON preview with row count."""
    rid = _resolve_run_id(body)
    sb = get_supabase()
    run_row, payload, client_name = _load_run_context(sb, rid, current_user)

    uid = str(current_user.get("id", ""))
    prof = get_user_profile(uid) or {}
    firm_name = str(prof.get("firm_name") or "")
    gen_name = str(prof.get("full_name") or "")

    try:
        bundle = collect_export_rows(
            sb=sb,
            run_id=rid,
            payload=payload,
            run_row=run_row,
            client_name=client_name,
            firm_name=firm_name,
            generated_by=gen_name,
        )
    except Exception:
        _log.exception("advanced_export collect failed run=%s", rid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to collect reconciliation rows for export",
        )

    # Validate status filter values (ignore unknown quietly after normalize).
    raw_statuses = body.filters.status or []
    statuses = [s.strip().upper() for s in raw_statuses if s and str(s).strip()]
    unknown = [s for s in statuses if s not in ALL_EXPORT_STATUSES]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown status filter value(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(ALL_EXPORT_STATUSES)}",
        )

    filtered = apply_filters(
        bundle,
        statuses=statuses or None,
        client_ids=body.filters.client_id or None,
        period=body.filters.period,
        itc_categories=body.filters.itc_category or None,
    )
    summary = summarize_rows(filtered)

    if body.format == "preview":
        return JSONResponse(
            {
                "matched_row_count": summary["total_rows"],
                "count_by_status": summary["count_by_status"],
                "count_by_itc_category": summary["count_by_itc_category"],
                "total_itc_at_risk": summary["total_itc_at_risk"],
                "available_statuses": list(ALL_EXPORT_STATUSES),
                "available_itc_categories": available_itc_categories(bundle),
                "client_id": bundle.client_id,
                "client_name": bundle.client_name,
                "period": bundle.period,
            }
        )

    if body.format == "xlsx":
        blob, fn = build_advanced_export_xlsx_bytes(bundle, filtered)
        await _log_advanced_export(sb, current_user, run_row, rid, "advanced_excel")
        return StreamingResponse(
            io.BytesIO(blob),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'},
        )

    # pdf
    blob, fn = build_advanced_export_pdf_bytes(bundle, filtered)
    await _log_advanced_export(sb, current_user, run_row, rid, "advanced_pdf")
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )
