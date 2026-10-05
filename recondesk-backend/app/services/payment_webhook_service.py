"""Razorpay webhook processing, deduplication, and asynchronous fulfillment service."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client

from app.config import settings
from app.services.billing_gate import (
    activate_subscription,
    get_plan_details,
    resolve_firm_owner_for_billing,
)
from app.utils.redis_cache import invalidate_user_dashboard

_log = logging.getLogger(__name__)


def verify_razorpay_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify Razorpay HMAC-SHA256 signature against settings.RAZORPAY_KEY_SECRET."""
    secret = (getattr(settings, "RAZORPAY_KEY_SECRET", "") or "").strip()
    if not secret or not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def record_webhook_event(
    sb: Client,
    provider: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    """Record webhook receipt for deduplication.
    
    Returns:
        (is_new, status)
        If event was already processed, returns (False, 'already_processed').
        If event is brand new or previously failed, returns (True, status).
    """
    clean_event_id = str(event_id or "").strip()
    if not clean_event_id:
        return True, "missing_event_id"

    try:
        # Check existing event
        res = (
            sb.table("webhook_events")
            .select("id, status")
            .eq("provider", provider)
            .eq("event_id", clean_event_id)
            .limit(1)
            .execute()
        )
        if res.data:
            existing = res.data[0]
            existing_status = existing.get("status")
            if existing_status == "processed":
                _log.info("Webhook event already processed provider=%s event_id=%s", provider, clean_event_id)
                return False, "already_processed"
            # If received but not processed, or failed, allow retry
            return True, str(existing_status or "received")

        # Insert new record
        sb.table("webhook_events").insert(
            {
                "provider": provider,
                "event_id": clean_event_id,
                "event_type": event_type,
                "status": "received",
                "payload": payload,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        return True, "received"
    except Exception as exc:
        _log.warning("webhook_events table operation failed (non-blocking fallback): %s", exc)
        return True, "fallback"


def mark_webhook_status(
    sb: Client,
    provider: str,
    event_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Update webhook event status in webhook_events."""
    clean_event_id = str(event_id or "").strip()
    if not clean_event_id:
        return
    try:
        updates: dict[str, Any] = {
            "status": status,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        if error_message is not None:
            updates["error_message"] = error_message
        sb.table("webhook_events").update(updates).eq("provider", provider).eq("event_id", clean_event_id).execute()
    except Exception as exc:
        _log.warning("Failed to update webhook_events status: %s", exc)


async def fulfill_razorpay_payment_captured(sb: Client, payload: dict[str, Any]) -> dict[str, Any]:
    """Fulfill subscription and run unlock asynchronously on payment.captured."""
    payment = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    ) or {}
    payment_id = str(payment.get("id") or "").strip()
    order_id = str(payment.get("order_id") or "").strip()
    notes = payment.get("notes") or {}

    if not payment_id:
        return {"status": "skipped", "reason": "missing_payment_id"}

    # 1. Idempotency check: has this payment already been recorded as paid?
    try:
        existing_pay = (
            sb.table("payments")
            .select("id, status, firm_owner_id, plan")
            .eq("razorpay_payment_id", payment_id)
            .limit(1)
            .execute()
        )
        if existing_pay.data and existing_pay.data[0].get("status") == "paid":
            _log.info("Payment %s already fulfilled in payments table", payment_id)
            return {"status": "already_fulfilled", "payment_id": payment_id}
    except Exception as exc:
        _log.warning("Failed checking existing payment: %s", exc)

    # 2. Extract billing details
    plan = str(notes.get("plan") or "starter").strip().lower()
    billing_period = str(notes.get("billing_period") or "yearly").strip().lower()
    custom_gstin_limit = None
    if notes.get("gstin_limit"):
        try:
            custom_gstin_limit = int(notes["gstin_limit"])
        except (ValueError, TypeError):
            pass

    run_id = str(notes.get("run_id") or "").strip() or None
    firm_owner_id = str(notes.get("user_id") or "").strip()

    # If firm_owner_id missing from notes, attempt resolution from run
    if not firm_owner_id and run_id:
        try:
            rres = sb.table("reconciliation_run").select("client_gstin_id").eq("id", run_id).limit(1).execute()
            if rres.data:
                cg_id = str(rres.data[0].get("client_gstin_id") or "").strip()
                cgres = sb.table("client_gstins").select("firm_owner_id").eq("id", cg_id).limit(1).execute()
                if cgres.data:
                    firm_owner_id = str(cgres.data[0].get("firm_owner_id") or "").strip()
        except Exception as exc:
            _log.warning("Failed to resolve firm_owner_id from run: %s", exc)

    if not firm_owner_id:
        _log.warning("Could not determine firm_owner_id for captured payment %s", payment_id)
        return {"status": "failed", "reason": "missing_firm_owner_id"}

    details = get_plan_details(plan, billing_period, custom_gstin_limit)
    amount_paise = int(payment.get("amount") or details["total_paise"])

    # 3. Insert or update payments record
    pay_row = {
        "firm_owner_id": firm_owner_id,
        "run_id": run_id,
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "amount_paise": amount_paise,
        "status": "paid",
        "plan": details["plan"],
        "plan_version": 2,
        "billing_cycle": details["billing_period"],
        "gstin_limit": int(details["gstin_limit"]),
        "overage_gstins": int(details["overage_gstins"]),
        "overage_rate_paise": int(details["overage_rate_paise"]),
        "runs_purchased": 0,
        "base_amount_paise": int(details["base_paise"]),
        "gst_paise": int(details["gst_paise"]),
        "total_amount_paise": amount_paise,
    }

    payment_uuid: Optional[str] = None
    try:
        ins = sb.table("payments").insert(pay_row).execute()
        if ins.data:
            payment_uuid = str(ins.data[0].get("id") or "")
    except Exception as exc:
        _log.warning("Failed inserting payment record, attempting update: %s", exc)
        try:
            up = sb.table("payments").update({"status": "paid"}).eq("razorpay_payment_id", payment_id).execute()
            if up.data:
                payment_uuid = str(up.data[0].get("id") or "")
        except Exception:
            pass

    # 4. Activate subscription
    try:
        await activate_subscription(
            firm_owner_id,
            details["plan"],
            payment_uuid,
            billing_period=details["billing_period"],
            custom_gstin_limit=custom_gstin_limit,
            sb=sb,
        )
    except Exception as exc:
        _log.error("Failed to activate subscription for owner %s: %s", firm_owner_id, exc)

    # 5. Mark reconciliation run paid if applicable
    if run_id:
        try:
            sb.table("reconciliation_run").update(
                {"paid_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", run_id).execute()
        except Exception as exc:
            _log.warning("Failed to mark run %s as paid: %s", run_id, exc)

    # 6. Invalidate dashboard cache
    invalidate_user_dashboard(firm_owner_id)

    return {"status": "fulfilled", "payment_id": payment_id, "firm_owner_id": firm_owner_id}
