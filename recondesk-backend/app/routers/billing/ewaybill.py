"""FastAPI Router for E-Way Bill Operations (Standalone, 1-Click from Invoice, Vehicle Update, Cancel, NIC Export)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from supabase import Client

from app.auth import get_current_active_user
from app.database import get_supabase
from app.models.ewaybill import (
    CancelEwayBillInput,
    EwayBillCreateInput,
    EwayBillResponse,
    EwbFromInvoiceInput,
    UpdateVehicleInput,
)
from app.services.billing import ewaybill_service as ewb_svc
from app.services.reconciliation_import_wizard.wizard_service import assert_client_access

logger = logging.getLogger(__name__)

router = APIRouter()


def _assert_client(sb: Any, client_id: str, user_id: str) -> None:
    try:
        assert_client_access(sb, client_id, user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this client GSTIN",
        ) from exc


@router.post("/generate", response_model=Dict[str, Any])
async def create_ewaybill_endpoint(
    body: EwayBillCreateInput,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate standalone E-Way Bill (Part A & Part B)."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, body.client_gstin_id, user_id)

    try:
        return ewb_svc.create_standalone_ewaybill(sb, body, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to generate standalone E-Way Bill: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to generate E-Way Bill: {exc}")


@router.post("/generate-from-invoice", response_model=Dict[str, Any])
async def generate_from_invoice_endpoint(
    body: EwbFromInvoiceInput,
    current_user: dict = Depends(get_current_active_user),
):
    """1-Click generation of E-Way Bill directly from an existing finalized Invoice."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, body.client_gstin_id, user_id)

    try:
        return ewb_svc.generate_ewaybill_from_invoice(sb, body, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to generate E-Way Bill from invoice: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to generate E-Way Bill from invoice: {exc}")


@router.post("/{ewb_id}/update-vehicle")
async def update_vehicle_endpoint(
    ewb_id: str,
    body: UpdateVehicleInput,
    current_user: dict = Depends(get_current_active_user),
):
    """Update Part B Vehicle Details for an active E-Way Bill."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        return ewb_svc.update_vehicle_details(sb, ewb_id, body, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update vehicle for E-Way Bill %s: %s", ewb_id, exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to update vehicle: {exc}")


@router.post("/{ewb_id}/cancel")
async def cancel_ewaybill_endpoint(
    ewb_id: str,
    body: CancelEwayBillInput,
    current_user: dict = Depends(get_current_active_user),
):
    """Cancel E-Way Bill within 24 hours of generation."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        return ewb_svc.cancel_ewaybill(sb, ewb_id, body, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to cancel E-Way Bill %s: %s", ewb_id, exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to cancel E-Way Bill: {exc}")


@router.get("/list")
async def list_ewaybills_endpoint(
    client_gstin_id: str = Query(..., description="Client GSTIN UUID"),
    status: Optional[str] = Query(None, description="Filter by status: ACTIVE, CANCELLED, PART_A_ONLY"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_active_user),
):
    """List generated E-Way Bills for client GSTIN."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_gstin_id, user_id)

    return ewb_svc.list_ewaybills(sb, client_gstin_id, status_filter=status, limit=limit)


@router.get("/export-bulk-json")
async def export_bulk_json_endpoint(
    client_gstin_id: str = Query(..., description="Client GSTIN UUID"),
    status: Optional[str] = Query(None, description="Status filter"),
    current_user: dict = Depends(get_current_active_user),
):
    """Download official Government NIC Bulk JSON export for portal upload."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_gstin_id, user_id)

    records = ewb_svc.list_ewaybills(sb, client_gstin_id, status_filter=status, limit=500)
    payload = ewb_svc.build_nic_bulk_json(records)
    json_bytes = json.dumps(payload, indent=2).encode("utf-8")

    filename = f"EWAYBILL_BULK_{client_gstin_id[:8].upper()}_{len(records)}_RECORDS.json"

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
