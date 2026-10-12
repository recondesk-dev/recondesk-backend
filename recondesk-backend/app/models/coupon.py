"""Models, validation schemas, and types for Annual Subscription Coupons."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


PermittedDiscount = Literal[20, 25, 30]
PERMITTED_DISCOUNTS: frozenset[int] = frozenset({20, 25, 30})
ANNUAL_PLANS: frozenset[str] = frozenset({"solo", "firm", "large_firm"})


class CouponCreateRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=50, description="Unique coupon code")
    discount_percentage: int = Field(..., description="Discount tier (20, 25, or 30)")
    eligible_plans: List[str] = Field(
        default=["solo", "firm", "large_firm"],
        description="List of eligible annual plans",
    )
    expires_at: Optional[datetime] = Field(None, description="Expiration date/time (UTC)")
    max_redemptions: Optional[int] = Field(None, ge=1, description="Global maximum redemption limit")
    max_per_customer: int = Field(1, ge=1, description="Per-customer maximum redemption limit")
    restricted_to_tenant_id: Optional[str] = Field(None, description="Optional restricted tenant/firm owner ID")
    restricted_to_email: Optional[str] = Field(None, description="Optional restricted customer email")
    is_acquisition_only: bool = Field(True, description="Whether coupon is limited to first-year new annual subscribers")
    founder_approved: bool = Field(False, description="Server-verified founder approval")
    founder_approved_by: Optional[str] = Field(None, description="Server-derived identifier of founder who approved")
    founder_approval_notes: Optional[str] = Field(None, description="Notes/justification for 30% discount")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        code = v.strip().upper()
        if not code:
            raise ValueError("Coupon code cannot be empty")
        if not code.isalnum() and not all(c.isalnum() or c in "-_" for c in code):
            raise ValueError("Coupon code must contain only alphanumeric characters, dashes, or underscores")
        return code

    @field_validator("discount_percentage")
    @classmethod
    def validate_discount(cls, v: int) -> int:
        if v not in PERMITTED_DISCOUNTS:
            raise ValueError(f"Discount percentage must be one of {sorted(PERMITTED_DISCOUNTS)}%")
        return v

    @field_validator("eligible_plans")
    @classmethod
    def validate_plans(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("At least one eligible annual plan must be specified")
        normalized = [p.strip().lower() for p in v]
        for p in normalized:
            if p not in ANNUAL_PLANS:
                raise ValueError(f"Invalid annual plan '{p}'. Must be one of {sorted(ANNUAL_PLANS)}")
        return normalized


class CouponUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    max_redemptions: Optional[int] = Field(None, ge=1)
    max_per_customer: Optional[int] = Field(None, ge=1)
    is_acquisition_only: Optional[bool] = None


class CouponValidationRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    plan: str = Field(..., description="Selected plan (solo, firm, large_firm)")
    billing_cycle: str = Field(default="yearly", description="Billing cycle (must be yearly)")
    customer_gstin: Optional[str] = None


class CouponValidationResponse(BaseModel):
    valid: bool
    code: str
    coupon_id: str
    discount_percentage: int
    original_base_paise: int
    discount_amount_paise: int
    discounted_base_paise: int
    gst_paise: int
    total_paise: int
    plan: str
    billing_cycle: str
    is_acquisition_only: bool = True
    message: str = "Coupon applied successfully"


class CouponResponse(BaseModel):
    id: str
    code: str
    discount_percentage: int
    eligible_plans: List[str]
    is_active: bool
    expires_at: Optional[str] = None
    max_redemptions: Optional[int] = None
    redemptions_count: int
    max_per_customer: int
    restricted_to_tenant_id: Optional[str] = None
    restricted_to_email: Optional[str] = None
    is_acquisition_only: bool = True
    created_by: Optional[str] = None
    founder_approved: bool
    founder_approved_by: Optional[str] = None
    founder_approval_notes: Optional[str] = None
    assigned_to_tenant_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    assigned_to_firm_name: Optional[str] = None
    assigned_to_email: Optional[str] = None
    assigned_by: Optional[str] = None
    assigned_by_name: Optional[str] = None
    assigned_at: Optional[str] = None
    sales_notes: Optional[str] = None
    offer_status: Optional[str] = "active"
    revoked_at: Optional[str] = None
    revoked_by_name: Optional[str] = None
    revoked_reason: Optional[str] = None
    created_at: str
    updated_at: str


class PrivateCouponAssignRequest(BaseModel):
    tenant_id: str = Field(..., description="Target CA user/tenant ID from user_profiles")
    plan: str = Field(..., description="Eligible annual plan (solo, firm, large_firm)")
    discount_percentage: int = Field(..., description="Discount tier (20, 25, or 30)")
    expires_at: Optional[datetime] = Field(None, description="Offer expiration timestamp (UTC)")
    sales_notes: Optional[str] = Field(None, max_length=1000, description="Internal sales/negotiation notes")
    custom_code: Optional[str] = Field(None, max_length=50, description="Optional custom code; auto-generated if omitted")
    activate_now: bool = Field(True, description="True to activate immediately; False to save as draft")
    founder_approval_notes: Optional[str] = Field(None, description="Mandatory notes for 30% discount")

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ANNUAL_PLANS:
            raise ValueError(f"Plan must be one of {sorted(ANNUAL_PLANS)}")
        return clean

    @field_validator("discount_percentage")
    @classmethod
    def validate_discount(cls, v: int) -> int:
        if v not in PERMITTED_DISCOUNTS:
            raise ValueError(f"Discount must be one of {sorted(PERMITTED_DISCOUNTS)}%")
        return v


class PrivateCouponRevokeRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500, description="Reason for revoking offer")


class TenantSearchResult(BaseModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    firm_name: Optional[str] = None
    firm_gstin: Optional[str] = None
    plan: Optional[str] = None
    created_at: Optional[str] = None


class CustomerOfferResponse(BaseModel):
    id: str
    code: str
    discount_percentage: int
    eligible_plan: str
    eligible_plans: List[str]
    expires_at: Optional[str] = None
    original_base_paise: int
    discount_amount_paise: int
    discounted_base_paise: int
    gst_paise: int
    total_paise: int
    sales_notes: Optional[str] = None
    offer_status: str
    created_at: str


class RedemptionRecord(BaseModel):
    id: str
    coupon_id: str
    coupon_code: Optional[str] = None
    tenant_id: str
    user_id: str
    payment_id: Optional[str] = None
    razorpay_order_id: str
    razorpay_payment_id: Optional[str] = None
    original_base_amount_paise: int
    discount_amount_paise: int
    final_base_amount_paise: int
    gst_amount_paise: int
    total_amount_paise: int
    plan: str
    billing_cycle: str
    status: str
    created_at: str
