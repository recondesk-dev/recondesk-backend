import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from supabase import Client

from app.config import settings
from app.database import supabase_client
from app.services.billing_service import fetch_payment

router = APIRouter()


def _verify_razorpay_webhook(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(...),
    db: Client = Depends(supabase_client),
):
    body = await request.body()

    if not _verify_razorpay_webhook(body, x_razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    payload = await request.json()
    event = payload.get("event")

    if event == "payment.captured":
        payment_id = payload["payload"]["payment"]["entity"]["id"]
        order_id = payload["payload"]["payment"]["entity"]["order_id"]
        notes = payload["payload"]["payment"]["entity"].get("notes", {})
        plan = notes.get("plan", "starter")

        # Update user plan — match by razorpay order stored during order creation
        db.table("users").update({"plan": plan}).eq(
            "pending_order_id", order_id
        ).execute()

    elif event == "payment.failed":
        # Log the failure for support visibility
        order_id = payload["payload"]["payment"]["entity"].get("order_id")
        db.table("payment_failures").insert({"order_id": order_id, "payload": payload}).execute()

    return {"received": True}
