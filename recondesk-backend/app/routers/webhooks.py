"""Razorpay external webhook handler with deduplication and async fulfillment."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from supabase import Client

from app.database import supabase_client
from app.services.payment_webhook_service import (
    fulfill_razorpay_payment_captured,
    mark_webhook_status,
    record_webhook_event,
    verify_razorpay_webhook_signature,
)

_log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(...),
    db: Client = Depends(supabase_client),
):
    body = await request.body()

    if not verify_razorpay_webhook_signature(body, x_razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    payload = await request.json()
    event_type = payload.get("event") or "unknown"
    payment_entity = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    ) or {}
    event_id = str(payload.get("id") or payment_entity.get("id") or "").strip()

    # Deduplicate event
    is_new, event_status = record_webhook_event(
        db,
        provider="razorpay",
        event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    if not is_new and event_status == "already_processed":
        _log.info("Ignoring duplicate Razorpay webhook event %s", event_id)
        return {"received": True, "duplicate": True}

    try:
        if event_type == "payment.captured":
            await fulfill_razorpay_payment_captured(db, payload)
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
        elif event_type == "payment.failed":
            order_id = payment_entity.get("order_id")
            try:
                db.table("payment_failures").insert({"order_id": order_id, "payload": payload}).execute()
            except Exception as e:
                _log.warning("Could not insert payment_failures row: %s", e)
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
        else:
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
    except Exception as exc:
        _log.exception("Error processing Razorpay webhook event %s: %s", event_id, exc)
        mark_webhook_status(db, provider="razorpay", event_id=event_id, status="failed", error_message=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook",
        ) from exc

    return {"received": True}
