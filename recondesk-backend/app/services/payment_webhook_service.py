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
        if existing_pay.data and existing_pay.data[0].get("status") in ("paid", "refunded", "refund_pending", "refund_failed"):
            st = existing_pay.data[0].get("status")
            _log.info("Payment %s already handled in payments table (status: %s)", payment_id, st)
            return {"status": f"already_{st}", "payment_id": payment_id}
        if order_id:
            ord_chk = sb.table("payments").select("id, status").eq("razorpay_order_id", order_id).limit(1).execute()
            if ord_chk.data and ord_chk.data[0].get("status") in ("refunded", "refund_pending", "refund_failed"):
                st = ord_chk.data[0].get("status")
                _log.info("Order %s already marked %s, skipping fulfillment", order_id, st)
                return {"status": f"already_{st}", "order_id": order_id}
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
    firm_owner_id = str(notes.get("user_id") or notes.get("firm_owner_id") or "").strip()

    # If firm_owner_id missing from notes, check existing payment record for this order
    if not firm_owner_id and order_id:
        try:
            pres = sb.table("payments").select("firm_owner_id").eq("razorpay_order_id", order_id).limit(1).execute()
            if pres.data and pres.data[0].get("firm_owner_id"):
                firm_owner_id = str(pres.data[0]["firm_owner_id"]).strip()
        except Exception:
            pass

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

    # Check for coupon applied to this order
    coupon_id = None
    coupon_code = None
    discount_percentage = None
    discount_amount_paise = 0
    base_amount_paise = int(details["base_paise"])
    gst_paise = int(details["gst_paise"])

    if order_id:
        try:
            pres = sb.table("payments").select("*").eq("razorpay_order_id", order_id).limit(1).execute()
            if pres.data and pres.data[0].get("coupon_code"):
                p_item = pres.data[0]
                coupon_id = p_item.get("coupon_id")
                coupon_code = p_item.get("coupon_code")
                discount_percentage = p_item.get("discount_percentage")
                discount_amount_paise = int(p_item.get("discount_amount_paise") or 0)
                base_amount_paise = int(p_item.get("base_amount_paise") or details["base_paise"])
                gst_paise = int(p_item.get("gst_paise") or details["gst_paise"])
            else:
                rres = sb.table("coupon_redemptions").select("*").eq("razorpay_order_id", order_id).limit(1).execute()
                if rres.data:
                    ritem = rres.data[0]
                    coupon_id = ritem.get("coupon_id")
                    coupon_code = ritem.get("coupon_code")
                    discount_amount_paise = int(ritem.get("discount_amount_paise") or 0)
                    base_amount_paise = int(ritem.get("final_base_amount_paise") or details["base_paise"])
                    gst_paise = int(ritem.get("gst_amount_paise") or details["gst_paise"])
        except Exception as exc:
            _log.warning("Webhook could not query pending coupon details for order %s: %s", order_id, exc)

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
        "base_amount_paise": base_amount_paise,
        "gst_paise": gst_paise,
        "total_amount_paise": amount_paise,
        "coupon_id": coupon_id,
        "coupon_code": coupon_code,
        "discount_percentage": discount_percentage,
        "discount_amount_paise": discount_amount_paise,
    }

    payment_uuid: Optional[str] = None
    updated = False
    if order_id:
        try:
            up = sb.table("payments").update(pay_row).eq("razorpay_order_id", order_id).execute()
            if up.data and len(up.data) > 0:
                payment_uuid = str(up.data[0].get("id") or "")
                updated = True
        except Exception as exc:
            _log.warning("Failed updating existing order payment record in webhook: %s", exc)

    if not updated:
        try:
            ins = sb.table("payments").insert(pay_row).execute()
            if ins.data:
                payment_uuid = str(ins.data[0].get("id") or "")
        except Exception as exc:
            _log.warning("Failed inserting payment record, attempting update: %s", exc)
            try:
                up = sb.table("payments").update({"status": "paid", "razorpay_payment_id": payment_id}).eq("razorpay_payment_id", payment_id).execute()
                if up.data:
                    payment_uuid = str(up.data[0].get("id") or "")
            except Exception:
                pass

    # 4. Fulfill coupon redemption BEFORE subscription activation
    if coupon_id or coupon_code or order_id:
        from app.services.coupon_service import fulfill_coupon_redemption
        fulfilled_red = None
        try:
            fulfilled_red = fulfill_coupon_redemption(
                sb,
                razorpay_order_id=order_id,
                payment_id=payment_uuid,
                razorpay_payment_id=payment_id,
            )
        except Exception as exc:
            _log.warning("Webhook failed to fulfill coupon redemption: %s", exc)

        if fulfilled_red is None:
            # Check if this order actually had a coupon redemption reservation
            red_chk = sb.table("coupon_redemptions").select("status").eq("razorpay_order_id", order_id).limit(1).execute()
            if red_chk.data and red_chk.data[0].get("status") == "limit_exceeded":
                _log.warning(
                    "Webhook: Coupon limit exceeded for order %s (payment %s). Initiating automatic refund.",
                    order_id, payment_id
                )
                rfnd = None
                ref_err = None
                try:
                    from app.routers.payments import _client as rzp_client
                    rfnd = rzp_client.payment.refund(
                        payment_id,
                        {
                            "amount": amount_paise,
                            "notes": {
                                "reason": "coupon_quota_exceeded",
                                "order_id": order_id,
                            },
                        },
                    )
                    _log.info("Webhook automatic refund request dispatched for payment %s", payment_id)
                except Exception as exc:
                    ref_err = exc
                    _log.error("Webhook automatic refund call failed for payment %s: %s", payment_id, exc)

                if ref_err:
                    payment_status = "refund_failed"
                    refund_status = "failed"
                    refund_id = None
                    refund_error = str(ref_err)
                else:
                    rfnd_status = str(rfnd.get("status") or "").lower() if isinstance(rfnd, dict) else "pending"
                    refund_id = str(rfnd.get("id") or "") if isinstance(rfnd, dict) else None
                    if rfnd_status == "processed":
                        payment_status = "refunded"
                        refund_status = "processed"
                    else:
                        payment_status = "refund_pending"
                        refund_status = "pending"
                    refund_error = None

                up_pay = {
                    "status": payment_status,
                    "refund_status": refund_status,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                if refund_id:
                    up_pay["refund_id"] = refund_id
                if refund_error:
                    up_pay["refund_error"] = refund_error

                try:
                    if payment_uuid:
                        sb.table("payments").update(up_pay).eq("id", payment_uuid).execute()
                    sb.table("payments").update(up_pay).eq("razorpay_order_id", order_id).execute()
                except Exception as up_err:
                    _log.warning("Failed marking payment refund status in webhook: %s", up_err)

                return {
                    "status": payment_status,
                    "reason": "coupon_quota_exceeded",
                    "refund_id": refund_id,
                    "refund_status": refund_status,
                }

    # 5. Activate subscription
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


def handle_razorpay_refund_processed(sb: Client, payload: dict[str, Any]) -> dict[str, Any]:
    """Handles refund.processed webhook event from Razorpay."""
    refund_ent = (
        payload.get("payload", {})
        .get("refund", {})
        .get("entity", {})
    ) or {}
    refund_id = str(refund_ent.get("id") or "").strip()
    payment_id = str(refund_ent.get("payment_id") or "").strip()

    if not payment_id and not refund_id:
        return {"status": "skipped", "reason": "missing_identifiers"}

    updates: dict[str, Any] = {
        "status": "refunded",
        "refund_status": "processed",
        "refund_id": refund_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if payment_id:
        sb.table("payments").update(updates).eq("razorpay_payment_id", payment_id).execute()
    elif refund_id:
        sb.table("payments").update(updates).eq("refund_id", refund_id).execute()

    _log.info("Successfully recorded refund.processed for payment %s (refund %s)", payment_id, refund_id)
    return {"status": "processed", "refund_id": refund_id}


def handle_razorpay_refund_failed(sb: Client, payload: dict[str, Any]) -> dict[str, Any]:
    """Handles refund.failed webhook event from Razorpay."""
    refund_ent = (
        payload.get("payload", {})
        .get("refund", {})
        .get("entity", {})
    ) or {}
    refund_id = str(refund_ent.get("id") or "").strip()
    payment_id = str(refund_ent.get("payment_id") or "").strip()
    err_desc = str(refund_ent.get("error_description") or "Refund failed on gateway").strip()

    if not payment_id and not refund_id:
        return {"status": "skipped", "reason": "missing_identifiers"}

    updates: dict[str, Any] = {
        "status": "refund_failed",
        "refund_status": "failed",
        "refund_error": err_desc,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if refund_id:
        updates["refund_id"] = refund_id
    if payment_id:
        sb.table("payments").update(updates).eq("razorpay_payment_id", payment_id).execute()
    elif refund_id:
        sb.table("payments").update(updates).eq("refund_id", refund_id).execute()

    _log.warning("Recorded refund.failed for payment %s (refund %s): %s", payment_id, refund_id, err_desc)
    return {"status": "failed", "refund_id": refund_id, "error": err_desc}


def reconcile_or_retry_refund(
    db: Client,
    razorpay_order_id: str,
    razorpay_payment_id: Optional[str] = None,
) -> dict[str, Any]:
    """Reconciles pending or failed refunds with Razorpay gateway, retrying if necessary.

    Ensures idempotency: if already marked 'refunded', does nothing.
    """
    from app.routers.payments import _client as rzp_client

    q = db.table("payments").select("*")
    if razorpay_payment_id:
        q = q.eq("razorpay_payment_id", razorpay_payment_id)
    else:
        q = q.eq("razorpay_order_id", razorpay_order_id)
    res = q.limit(1).execute()
    if not res.data:
        return {"status": "not_found"}

    pay = res.data[0]
    current_status = pay.get("status")
    existing_refund_id = pay.get("refund_id")
    pay_id = pay.get("razorpay_payment_id") or razorpay_payment_id
    amount_paise = int(pay.get("total_amount_paise") or pay.get("amount_paise") or 0)

    # 1. Idempotency: already processed
    if current_status == "refunded":
        return {
            "status": "already_refunded",
            "refund_id": existing_refund_id,
            "refund_status": "processed",
        }

    # 2. Check gateway if refund_id exists
    if existing_refund_id:
        try:
            rfnd = rzp_client.refund.fetch(existing_refund_id)
            gate_status = str(rfnd.get("status") or "").lower()
            if gate_status == "processed":
                db.table("payments").update({
                    "status": "refunded",
                    "refund_status": "processed",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", pay["id"]).execute()
                return {"status": "refunded", "refund_id": existing_refund_id, "reconciled": True}
            elif gate_status == "failed":
                db.table("payments").update({
                    "status": "refund_failed",
                    "refund_status": "failed",
                    "refund_error": str(rfnd.get("error_description") or "Gateway refund failed"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", pay["id"]).execute()
            else:
                return {"status": "refund_pending", "refund_id": existing_refund_id, "gateway_status": gate_status}
        except Exception as f_err:
            _log.warning("Failed fetching refund %s from Razorpay: %s", existing_refund_id, f_err)

    # 3. Retry initiating refund
    if pay_id:
        try:
            rfnd = rzp_client.payment.refund(
                pay_id,
                {
                    "amount": amount_paise,
                    "notes": {"reason": "coupon_quota_exceeded_retry", "order_id": razorpay_order_id},
                },
            )
            rfnd_status = str(rfnd.get("status") or "").lower() if isinstance(rfnd, dict) else "pending"
            rfnd_id = str(rfnd.get("id") or "") if isinstance(rfnd, dict) else None
            p_st = "refunded" if rfnd_status == "processed" else "refund_pending"
            r_st = "processed" if rfnd_status == "processed" else "pending"
            db.table("payments").update({
                "status": p_st,
                "refund_status": r_st,
                "refund_id": rfnd_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", pay["id"]).execute()
            return {"status": p_st, "refund_status": r_st, "refund_id": rfnd_id}
        except Exception as r_err:
            db.table("payments").update({
                "status": "refund_failed",
                "refund_status": "failed",
                "refund_error": str(r_err),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", pay["id"]).execute()
            return {"status": "refund_failed", "error": str(r_err)}

    return {"status": "cannot_retry", "reason": "missing_payment_id"}
