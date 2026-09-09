"""Router for E-Invoice IRP Submission, Cancellation & Status API endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Query, HTTPException, status
from supabase import Client

from app.auth import get_current_user
from app.database import supabase_client
from app.services.billing import irp_submission_service

router = APIRouter()
_log = logging.getLogger(__name__)


class CancelIrnRequest(BaseModel):
    client_gstin_id: str = Field(..., description="Client GSTIN ID")
    reason_code: str = Field(..., description="1: Duplicate, 2: Data Entry Error, 3: Order Cancelled, 4: Other")
    remarks: str = Field(..., min_length=3, description="Cancellation remark string")


class IrpSubmitRequest(BaseModel):
    client_gstin_id: str = Field(..., description="Client GSTIN ID")


@router.post("/{id}/submit-to-irp")
async def submit_invoice_to_irp(
    id: str,
    body: IrpSubmitRequest,
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Validate, format, and submit a finalized invoice to Sandbox e-Invoice Generate API."""
    try:
        return irp_submission_service.submit_to_irp(
            db=db,
            invoice_id=id,
            client_gstin_id=body.client_gstin_id,
            user_id=user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _log.error("Unhandled error submitting invoice %s to IRP: %s", id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error submitting to IRP: {str(exc)}")


@router.post("/{id}/cancel-irn")
async def cancel_invoice_irn(
    id: str,
    body: CancelIrnRequest,
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Cancel an active registered IRN on IRP. Enforces 24-hour window from generation."""
    try:
        return irp_submission_service.cancel_irn(
            db=db,
            invoice_id=id,
            client_gstin_id=body.client_gstin_id,
            reason_code=body.reason_code,
            remarks=body.remarks,
            user_id=user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _log.error("Unhandled error cancelling IRN for invoice %s: %s", id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error cancelling IRN: {str(exc)}")


@router.get("/{id}/irp-status")
async def get_invoice_irp_status(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Fetch current IRP status and submission audit log for an invoice."""
    try:
        return irp_submission_service.get_irp_status_info(
            db=db,
            invoice_id=id,
            client_gstin_id=client_gstin_id,
            user_id=user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _log.error("Unhandled error fetching IRP status for invoice %s: %s", id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error fetching IRP status: {str(exc)}")
