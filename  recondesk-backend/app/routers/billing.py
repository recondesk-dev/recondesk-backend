from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth import get_current_active_user
from app.database import supabase_client
from app.models.billing import CreateOrderRequest, OrderResponse
from app.services.billing_service import create_order
from app.config import settings

router = APIRouter()


@router.post("/order", response_model=OrderResponse)
async def create_payment_order(
    payload: CreateOrderRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Create a Razorpay order to initiate a subscription payment."""
    if payload.plan.value == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create order for the free plan",
        )

    try:
        order = create_order(payload.plan.value, payload.billing_period)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Payment gateway error: {exc}",
        ) from exc

    return OrderResponse(
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        razorpay_key=settings.RAZORPAY_KEY_ID,
    )


@router.get("/plans")
async def list_plans():
    """Return available subscription plans with pricing."""
    return {
        "plans": [
            {"id": "free",       "name": "Free",       "monthly": 0,      "yearly": 0,       "row_limit": 500},
            {"id": "starter",    "name": "Starter",    "monthly": 999,    "yearly": 9999,    "row_limit": 10000},
            {"id": "growth",     "name": "Growth",     "monthly": 2999,   "yearly": 29999,   "row_limit": 100000},
            {"id": "enterprise", "name": "Enterprise", "monthly": 9999,   "yearly": 99999,   "row_limit": None},
        ]
    }
