from __future__ import annotations

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response
from supabase import Client

from app.auth import get_current_user
from app.database import supabase_client
from app.models.billing import (
    CdnCreateInput,
    CdnDetailResponse,
    CdnResponse,
    CdnUpdateInput,
)
from app.services.billing import cdn_service
from app.services.billing.invoice_pdf_service import build_gst_invoice_pdf

router = APIRouter()
_log = logging.getLogger(__name__)


@router.post("", response_model=CdnDetailResponse)
@router.post("/", response_model=CdnDetailResponse)
async def create_credit_debit_note(
    payload: CdnCreateInput,
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Create a draft Credit Note or Debit Note linked to an original e-invoice."""
    return cdn_service.create_credit_debit_note(db, payload, user_or_id=user)


@router.get("", response_model=List[CdnResponse])
@router.get("/", response_model=List[CdnResponse])
async def list_credit_debit_notes(
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    original_invoice_id: Optional[str] = Query(None, description="Filter by original invoice ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """List Credit Notes / Debit Notes for a client GSTIN."""
    return cdn_service.list_cdns(
        db, client_gstin_id=client_gstin_id, original_invoice_id=original_invoice_id, user_or_id=user
    )


@router.get("/{id}", response_model=CdnDetailResponse)
async def get_cdn_detail(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Get full CDN details including line items, original invoice, seller, and buyer."""
    return cdn_service.get_cdn_detail(db, id, client_gstin_id, user_or_id=user)


@router.patch("/{id}", response_model=CdnDetailResponse)
async def update_cdn(
    id: str,
    payload: CdnUpdateInput,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Edit draft CDN."""
    return cdn_service.update_cdn(db, id, client_gstin_id, payload, user_or_id=user)


@router.post("/{id}/finalize", response_model=CdnDetailResponse)
async def finalize_cdn(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Finalize CDN (locks editing)."""
    return cdn_service.finalize_cdn(db, id, client_gstin_id, user_or_id=user)


@router.post("/{id}/submit-to-irp", response_model=CdnDetailResponse)
async def submit_cdn_to_irp(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Submit finalized Credit/Debit Note to Government IRP for IRN generation."""
    return cdn_service.submit_cdn_to_irp(db, id, client_gstin_id, user_or_id=user)


@router.get("/{id}/pdf")
async def download_cdn_pdf(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Generate and return official GST Credit/Debit Note PDF."""
    detail = cdn_service.get_cdn_detail(db, id, client_gstin_id, user_or_id=user)
    pdf_bytes = build_gst_invoice_pdf(detail)
    note_num = (detail.get("note_number") or id).replace("/", "_")
    filename = f"Credit_Note_{note_num}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )
