"""Admin endpoints for Annual Subscription Coupon Management.

Exclusively accessible to verified internal platform administrators.
Tenant admins and CA practice users are blocked with 403 Forbidden.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from supabase import Client

from app.auth import require_internal_coupon_staff, require_platform_admin
from app.database import supabase_client
from app.models.coupon import (
    CouponCreateRequest,
    CouponResponse,
    CouponUpdateRequest,
    PrivateCouponAssignRequest,
    PrivateCouponRevokeRequest,
    RedemptionRecord,
    TenantSearchResult,
)
from app.services.coupon_service import (
    activate_private_ca_coupon,
    assign_private_ca_coupon,
    create_admin_coupon,
    find_coupon_by_code,
    get_coupon_analytics,
    list_admin_coupons,
    list_redemption_history,
    revoke_private_ca_coupon,
    search_tenants_for_assignment,
    toggle_coupon_status,
)
from app.utils.audit import log_action

_log = logging.getLogger(__name__)

router = APIRouter()


class ToggleStatusPayload(BaseModel):
    is_active: bool


@router.post("", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_coupon_endpoint(
    payload: CouponCreateRequest,
    request: Request,
    current_admin: dict = Depends(require_platform_admin),
    db: Client = Depends(supabase_client),
):
    """Create a new promotional coupon (20%, 25%, or 30% with founder approval)."""
    admin_id = str(current_admin.get("id") or "")
    created = create_admin_coupon(db, payload, current_admin)

    await log_action(
        admin_id,
        "COUPON_CREATED",
        "coupon",
        str(created.get("id")),
        {
            "code": created.get("code"),
            "discount_percentage": created.get("discount_percentage"),
            "eligible_plans": created.get("eligible_plans"),
            "founder_approved": created.get("founder_approved"),
        },
        ip_address=(request.client.host if request.client else None),
    )

    return created


@router.get("", response_model=List[dict[str, Any]])
async def list_coupons_endpoint(
    current_admin: dict = Depends(require_platform_admin),
    db: Client = Depends(supabase_client),
):
    """List all coupons with redemption totals and configuration."""
    return list_admin_coupons(db)


@router.get("/analytics", response_model=dict[str, Any])
async def get_analytics_endpoint(
    current_admin: dict = Depends(require_platform_admin),
    db: Client = Depends(supabase_client),
):
    """Get coupon analytics, aggregate redemption counts, and total discounts."""
    return get_coupon_analytics(db)


@router.get("/redemptions", response_model=List[dict[str, Any]])
async def list_redemptions_endpoint(
    coupon_id: Optional[str] = None,
    current_admin: dict = Depends(require_platform_admin),
    db: Client = Depends(supabase_client),
):
    """View redemption history across customers and subscriptions."""
    return list_redemption_history(db, coupon_id=coupon_id)


@router.get("/{coupon_id}", response_model=dict[str, Any])
async def get_coupon_endpoint(
    coupon_id: str,
    current_admin: dict = Depends(require_platform_admin),
    db: Client = Depends(supabase_client),
):
    """Get coupon details by ID."""
    res = db.table("coupons").select("*").eq("id", coupon_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    return res.data[0]


@router.patch("/{coupon_id}/status", response_model=dict[str, Any])
async def update_coupon_status_endpoint(
    coupon_id: str,
    payload: ToggleStatusPayload,
    request: Request,
    current_admin: dict = Depends(require_platform_admin),
    db: Client = Depends(supabase_client),
):
    """Activate or deactivate a coupon."""
    admin_id = str(current_admin.get("id") or "")
    updated = toggle_coupon_status(db, coupon_id, payload.is_active)

    await log_action(
        admin_id,
        "COUPON_STATUS_UPDATED",
        "coupon",
        coupon_id,
        {"is_active": payload.is_active, "code": updated.get("code")},
        ip_address=(request.client.host if request.client else None),
    )

    return updated


@router.get("/tenants", response_model=List[TenantSearchResult])
async def search_tenants_endpoint(
    query: str = "",
    current_staff: dict = Depends(require_internal_coupon_staff),
    db: Client = Depends(supabase_client),
):
    """Search authoritative CA customer accounts for negotiated offer assignment."""
    return search_tenants_for_assignment(db, query=query)


@router.post("/assign", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
async def assign_private_offer_endpoint(
    payload: PrivateCouponAssignRequest,
    request: Request,
    current_staff: dict = Depends(require_internal_coupon_staff),
    db: Client = Depends(supabase_client),
):
    """Assign and optionally activate a negotiated private discount offer to an existing CA customer."""
    staff_id = str(current_staff.get("id") or "")
    assigned = assign_private_ca_coupon(db, payload, current_staff)

    await log_action(
        staff_id,
        "PRIVATE_COUPON_ASSIGNED",
        "coupon",
        str(assigned.get("id")),
        {
            "code": assigned.get("code"),
            "tenant_id": payload.tenant_id,
            "plan": payload.plan,
            "discount_percentage": payload.discount_percentage,
            "is_active": assigned.get("is_active"),
            "offer_status": assigned.get("offer_status"),
        },
        ip_address=(request.client.host if request.client else None),
    )

    return assigned


@router.patch("/{coupon_id}/activate", response_model=dict[str, Any])
async def activate_offer_endpoint(
    coupon_id: str,
    request: Request,
    current_staff: dict = Depends(require_internal_coupon_staff),
    db: Client = Depends(supabase_client),
):
    """Activate a draft or inactive private offer."""
    staff_id = str(current_staff.get("id") or "")
    updated = activate_private_ca_coupon(db, coupon_id, current_staff)

    await log_action(
        staff_id,
        "PRIVATE_COUPON_ACTIVATED",
        "coupon",
        coupon_id,
        {"code": updated.get("code"), "status": "active"},
        ip_address=(request.client.host if request.client else None),
    )

    return updated


@router.patch("/{coupon_id}/revoke", response_model=dict[str, Any])
async def revoke_offer_endpoint(
    coupon_id: str,
    request: Request,
    payload: Optional[PrivateCouponRevokeRequest] = None,
    current_staff: dict = Depends(require_internal_coupon_staff),
    db: Client = Depends(supabase_client),
):
    """Revoke an unredeemed private offer."""
    staff_id = str(current_staff.get("id") or "")
    reason = payload.reason if payload else None
    revoked = revoke_private_ca_coupon(db, coupon_id, current_staff, reason=reason)

    await log_action(
        staff_id,
        "PRIVATE_COUPON_REVOKED",
        "coupon",
        coupon_id,
        {"code": revoked.get("code"), "reason": reason},
        ip_address=(request.client.host if request.client else None),
    )

    return revoked
