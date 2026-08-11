"""GSTR-4 Composition Scheme Annual Return FastAPI Router.

Endpoints for GSTR-4 annual return auto-computation, CMP-08 quarterly figures management,
CA audit cell overrides, and official GSTN portal JSON exports.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services import gstr4_computation as g4_svc
from app.services.reconciliation_import_wizard.wizard_service import assert_client_access

logger = logging.getLogger(__name__)

router = APIRouter()


class AuditOverrideItem(BaseModel):
    table_key: str = Field(..., description="Table identifier, e.g. table4, table5, table6, table8")
    cell_key: str = Field(..., description="Cell identifier, e.g. 4A_taxable, outward_turnover")
    system_value: float = Field(0.0, description="System calculated value")
    override_value: float = Field(..., description="CA override value")
    notes: Optional[str] = Field(None, description="Optional audit observation note")


class SaveAuditOverridesRequest(BaseModel):
    financial_year: str = Field(..., description="Financial year in YYYY-YY format, e.g. 2025-26")
    overrides: list[AuditOverrideItem] = Field(..., description="List of CA cell overrides")


class Cmp08QuarterItem(BaseModel):
    quarter: str = Field(..., description="Quarter identifier: Q1, Q2, Q3, or Q4")
    outward_taxable: float = Field(0.0, description="Outward taxable turnover")
    outward_tax: float = Field(0.0, description="Outward tax paid")
    rcm_taxable: float = Field(0.0, description="Inward RCM taxable turnover")
    rcm_tax: float = Field(0.0, description="Inward RCM tax paid")
    igst: float = Field(0.0, description="IGST paid")
    cgst: float = Field(0.0, description="CGST paid")
    sgst: float = Field(0.0, description="SGST paid")
    cess: float = Field(0.0, description="Cess paid")
    interest: float = Field(0.0, description="Interest paid")
    late_fee: float = Field(0.0, description="Late fee paid")


class SaveCmp08Request(BaseModel):
    financial_year: str = Field(..., description="Financial year YYYY-YY, e.g. 2025-26")
    records: list[Cmp08QuarterItem] = Field(..., description="Quarterly CMP-08 records (Q1..Q4)")


def _assert_client(sb: Any, client_id: str, user_id: str) -> None:
    try:
        assert_client_access(sb, client_id, user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this client GSTIN",
        ) from exc


@router.get("/clients/{client_id}/computation")
async def get_gstr4_computation(
    client_id: str,
    fy: str = Query("2025-26", description="Financial year YYYY-YY"),
    category: str = Query("trader", description="Composition category: trader, manufacturer, restaurant, service"),
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch system-computed Form GSTR-4 Figures (Tables 1 to 9) with CA cell overrides."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        comp = g4_svc.compute_gstr4(sb, client_id, fy, category)
        return comp
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to compute GSTR-4: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute GSTR-4: {exc}",
        ) from exc


@router.patch("/clients/{client_id}/overrides")
async def save_gstr4_audit_overrides(
    client_id: str,
    body: SaveAuditOverridesRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Save CA audit cell overrides for Form GSTR-4."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    fy = body.financial_year.strip()
    updater_uuid = user_id if (user_id and len(user_id) == 36) else None

    try:
        overrides_dict_list = [item.model_dump() for item in body.overrides]
        g4_svc.save_gstr4_audit_overrides(sb, client_id, fy, overrides_dict_list, updater_uuid)
        return {"status": "success", "message": f"Saved {len(body.overrides)} audit cell overrides for FY {fy}."}
    except Exception as exc:
        logger.exception("Failed to save GSTR-4 audit overrides: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save overrides: {exc}",
        ) from exc


@router.post("/clients/{client_id}/cmp08")
async def save_cmp08_records(
    client_id: str,
    body: SaveCmp08Request,
    current_user: dict = Depends(get_current_active_user),
):
    """Upsert quarterly CMP-08 summary records for GSTR-4 Table 5."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    fy = body.financial_year.strip()
    updater_uuid = user_id if (user_id and len(user_id) == 36) else None

    try:
        records_dict_list = [item.model_dump() for item in body.records]
        saved = g4_svc.save_cmp08_records(sb, client_id, fy, records_dict_list, updater_uuid)
        return {"status": "success", "message": f"Saved CMP-08 records for FY {fy}.", "records": saved}
    except Exception as exc:
        logger.exception("Failed to save CMP-08 records: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save CMP-08 records: {exc}",
        ) from exc


@router.get("/clients/{client_id}/export-json")
async def export_gstr4_json(
    client_id: str,
    fy: str = Query("2025-26", description="Financial year YYYY-YY"),
    category: str = Query("trader", description="Composition category: trader, manufacturer, restaurant, service"),
    current_user: dict = Depends(get_current_active_user),
):
    """Generate official GSTN portal GSTR-4 JSON payload for upload/filing."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        payload = g4_svc.build_gstr4_gstn_json(sb, client_id, fy, category)
        content = json.dumps(payload, indent=2)
        filename = f"GSTR4_{payload.get('gstin', 'CLIENT')}_{fy.replace('-', '_')}.json"

        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.exception("Failed to export GSTR-4 JSON: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export GSTR-4 JSON: {exc}",
        ) from exc
