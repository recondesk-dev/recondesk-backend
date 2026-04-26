from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import StrictModel


class PlanType(str, Enum):
    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    TRIALING = "trialing"


class CreateOrderRequest(StrictModel):
    plan: PlanType
    billing_period: str = Field(
        default="monthly", max_length=32, description="monthly or yearly"
    )


class OrderResponse(StrictModel):
    order_id: str
    amount: int  # paise
    currency: str = "INR"
    razorpay_key: str


class SubscriptionResponse(StrictModel):
    id: UUID
    user_id: UUID
    plan: PlanType
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime
    razorpay_subscription_id: Optional[str] = None

    model_config = {"from_attributes": True}  # type: ignore[assignment]  # noqa: C408
