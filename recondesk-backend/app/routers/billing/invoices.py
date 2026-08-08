from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.auth import get_current_user
from app.database import supabase_client
from app.models.billing import (
    InvoiceCreateInput,
    InvoiceDetailResponse,
    InvoiceResponse,
    InvoiceUpdateInput,
)
from app.services.billing import invoice_service

router = APIRouter()
_log = logging.getLogger(__name__)


@router.post("", response_model=InvoiceDetailResponse)
@router.post("/", response_model=InvoiceDetailResponse)
async def create_invoice(
    payload: InvoiceCreateInput,
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Create a draft invoice."""
    return invoice_service.create_invoice(db, payload)


@router.get("", response_model=List[InvoiceResponse])
@router.get("/", response_model=List[InvoiceResponse])
async def list_invoices(
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    status: Optional[str] = Query(None, description="Draft, finalized, or cancelled"),
    start_date: Optional[date] = Query(None, description="Filter start date"),
    end_date: Optional[date] = Query(None, description="Filter end date"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """List invoices with optional status and date filters."""
    return invoice_service.list_invoices(
        db, client_gstin_id=client_gstin_id, status=status, start_date=start_date, end_date=end_date
    )


@router.get("/{id}", response_model=InvoiceDetailResponse)
async def get_invoice_detail(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Get full invoice details including company profile, customer, and line items."""
    return invoice_service.get_invoice_detail(db, id, client_gstin_id)


@router.patch("/{id}", response_model=InvoiceDetailResponse)
async def update_invoice(
    id: str,
    payload: InvoiceUpdateInput,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Edit draft invoice. Rejects edits if status is not draft."""
    return invoice_service.update_invoice(db, id, client_gstin_id, payload)


@router.post("/{id}/finalize", response_model=InvoiceDetailResponse)
async def finalize_invoice(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Finalize invoice (locks editing)."""
    return invoice_service.finalize_invoice(db, id, client_gstin_id)
