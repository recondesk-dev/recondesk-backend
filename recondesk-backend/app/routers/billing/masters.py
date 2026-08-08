from __future__ import annotations

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.auth import get_current_user
from app.database import supabase_client
from app.models.billing import (
    CompanyProfileCreate,
    CompanyProfileResponse,
    CompanyProfileUpdate,
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
    ItemCreate,
    ItemResponse,
    ItemUpdate,
)
from app.services.billing import invoice_service

router = APIRouter()
_log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Company Profiles
# -----------------------------------------------------------------------------
@router.get("/company-profiles", response_model=List[CompanyProfileResponse])
async def list_company_profiles(
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """List company profiles for a client."""
    return invoice_service.list_company_profiles(db, client_gstin_id)


@router.get("/company-profiles/{id}", response_model=CompanyProfileResponse)
async def get_company_profile(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Get company profile detail by ID."""
    return invoice_service.get_company_profile(db, id, client_gstin_id)


@router.post("/company-profiles", response_model=CompanyProfileResponse)
async def create_company_profile(
    payload: CompanyProfileCreate,
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Create a new company profile for billing."""
    return invoice_service.create_company_profile(db, payload)


@router.put("/company-profiles/{id}", response_model=CompanyProfileResponse)
async def update_company_profile(
    id: str,
    payload: CompanyProfileUpdate,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Update company profile."""
    return invoice_service.update_company_profile(db, id, client_gstin_id, payload)


# -----------------------------------------------------------------------------
# Customers
# -----------------------------------------------------------------------------
@router.get("/customers", response_model=List[CustomerResponse])
async def list_customers(
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """List customers for a client."""
    return invoice_service.list_customers(db, client_gstin_id)


@router.get("/customers/{id}", response_model=CustomerResponse)
async def get_customer(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Get customer detail by ID."""
    return invoice_service.get_customer(db, id, client_gstin_id)


@router.post("/customers", response_model=CustomerResponse)
async def create_customer(
    payload: CustomerCreate,
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Create a customer."""
    return invoice_service.create_customer(db, payload)


@router.put("/customers/{id}", response_model=CustomerResponse)
async def update_customer(
    id: str,
    payload: CustomerUpdate,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Update customer."""
    return invoice_service.update_customer(db, id, client_gstin_id, payload)


@router.delete("/customers/{id}")
async def delete_customer(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Delete customer."""
    invoice_service.delete_customer(db, id, client_gstin_id)
    return {"status": "success", "message": "Customer deleted"}


# -----------------------------------------------------------------------------
# Item Catalog
# -----------------------------------------------------------------------------
@router.get("/items", response_model=List[ItemResponse])
async def list_items(
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """List item catalog for a client."""
    return invoice_service.list_items(db, client_gstin_id)


@router.get("/items/{id}", response_model=ItemResponse)
async def get_item(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Get item detail by ID."""
    return invoice_service.get_item(db, id, client_gstin_id)


@router.post("/items", response_model=ItemResponse)
async def create_item(
    payload: ItemCreate,
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Create an item in catalog."""
    return invoice_service.create_item(db, payload)


@router.put("/items/{id}", response_model=ItemResponse)
async def update_item(
    id: str,
    payload: ItemUpdate,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Update item."""
    return invoice_service.update_item(db, id, client_gstin_id, payload)


@router.delete("/items/{id}")
async def delete_item(
    id: str,
    client_gstin_id: str = Query(..., description="Client GSTIN ID"),
    user: str = Depends(get_current_user),
    db: Client = Depends(supabase_client),
):
    """Delete item."""
    invoice_service.delete_item(db, id, client_gstin_id)
    return {"status": "success", "message": "Item deleted"}
