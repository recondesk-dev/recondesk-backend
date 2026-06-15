from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from supabase import Client

from app.auth import get_current_active_user
from app.config import settings
from app.database import supabase_client
from app.models.billing import CreateOrderRequest, OrderResponse
from app.services.billing_service import create_order
from app.services.payment_idempotency import (
    lookup_idempotent_response,
    store_idempotent_response,
)
from app.utils.audit import log_action
from app.utils.rate_limit import limiter

router = APIRouter()
_log = logging.getLogger(__name__)


@router.post("/order", response_model=OrderResponse)
@limiter.limit("10/hour")
async def create_payment_order(
    request: Request,
    payload: CreateOrderRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),  # noqa: ARG001
):
    """Create a Razorpay order to initiate a subscription payment."""
    uid = str(current_user.get("id", ""))
    if not (idempotency_key or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    cached = lookup_idempotent_response(idempotency_key.strip(), uid)
    if cached:
        return OrderResponse(
            order_id=cached.get("order_id", ""),
            amount=int(cached.get("amount", 0)),
            currency=str(cached.get("currency", "INR")),
            razorpay_key=cached.get("razorpay_key", settings.RAZORPAY_KEY_ID),
        )
    if payload.plan.value == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create order for the free plan",
        )
    try:
        order = create_order(payload.plan.value, payload.billing_period)
    except Exception as exc:  # noqa: BLE001
        _log.error("Razorpay create_order: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service temporarily unavailable",
        ) from exc

    out = {
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "razorpay_key": settings.RAZORPAY_KEY_ID,
    }
    store_idempotent_response(idempotency_key.strip(), uid, out)
    await log_action(
        uid,
        "PAYMENT_CREATED",
        "order",
        str(order.get("id")),
        {"amount": order.get("amount"), "plan": payload.plan.value},
        ip_address=(request.client.host if request.client else None),
    )
    return OrderResponse(
        order_id=out["order_id"],
        amount=out["amount"],
        currency=out["currency"],
        razorpay_key=out["razorpay_key"],
    )


@router.get("/plans")
@limiter.limit("200/minute")
async def list_plans(request: Request):  # noqa: ARG001
    """Return available subscription plans with pricing."""
    # TODO: update Razorpay plan IDs — legacy subscription-style plan listing, update when new plans are created
    return {
        "plans": [
            {"id": "free", "name": "Free", "monthly": 0, "yearly": 0, "row_limit": 500},
            {
                "id": "starter",
                "name": "Starter",
                "monthly": 999,
                "yearly": 9999,
                "row_limit": 10000,
            },
            {
                "id": "growth",
                "name": "Growth",
                "monthly": 2999,
                "yearly": 29999,
                "row_limit": 100000,
            },
            {
                "id": "enterprise",
                "name": "Enterprise",
                "monthly": 9999,
                "yearly": 99999,
                "row_limit": None,
            },
        ]
    }
