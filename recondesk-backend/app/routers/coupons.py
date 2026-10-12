"""Customer endpoints for Coupon validation prior to Razorpay checkout."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status
from supabase import Client

from app.auth import get_current_active_user
from app.database import supabase_client
from app.models.coupon import (
    CouponValidationRequest,
    CouponValidationResponse,
)
from app.services.billing_gate import resolve_firm_owner_for_billing
from app.services.coupon_service import validate_coupon_for_checkout
from app.utils.rate_limit import limiter

_log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/validate", response_model=CouponValidationResponse)
@limiter.limit("30/minute")
async def validate_coupon_endpoint(
    request: Request,
    payload: CouponValidationRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    """Validate a coupon code and calculate authoritative server-side price breakdown.

    Must be called before Razorpay order creation.
    """
    firm_owner = resolve_firm_owner_for_billing(db, current_user)
    user_email = current_user.get("email")

    breakdown = validate_coupon_for_checkout(
        db,
        code=payload.code,
        plan=payload.plan,
        billing_cycle=payload.billing_cycle,
        firm_owner_id=firm_owner,
        user_email=user_email,
    )

    return CouponValidationResponse(
        valid=True,
        code=breakdown["code"],
        coupon_id=breakdown["coupon_id"],
        discount_percentage=breakdown["discount_percentage"],
        original_base_paise=breakdown["original_base_paise"],
        discount_amount_paise=breakdown["discount_amount_paise"],
        discounted_base_paise=breakdown["discounted_base_paise"],
        gst_paise=breakdown["gst_paise"],
        total_paise=breakdown["total_paise"],
        plan=breakdown["plan"],
        billing_cycle=breakdown["billing_cycle"],
        message=f"{breakdown['discount_percentage']}% discount applied successfully",
    )
