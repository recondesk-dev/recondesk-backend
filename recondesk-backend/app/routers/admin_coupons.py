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

from app.auth import require_platform_admin
from app.database import supabase_client
from app.models.coupon import (
    CouponCreateRequest,
    CouponResponse,
    CouponUpdateRequest,
    RedemptionRecord,
)
from app.services.coupon_service import (
    create_admin_coupon,
    find_coupon_by_code,
    get_coupon_analytics,
    list_admin_coupons,
    list_redemption_history,
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
