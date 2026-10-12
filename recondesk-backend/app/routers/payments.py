"""GSTIN subscription billing: Razorpay orders, verify, webhooks, receipts, status."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from supabase import Client

from app.auth import get_current_active_user
from app.utils.redis_cache import cache_get, cache_set, invalidate_user_dashboard
from app.config import settings
from app.database import get_user_profile, supabase_client
from app.services.billing_gate import (
    PLAN_CONFIG,
    activate_subscription,
    consume_run_credit,
    count_gstins_toward_limit,
    forfeit_expired_credit_batches,
    get_gstin_limit,
    get_plan_details,
    has_active_subscription,
    resolve_firm_owner_for_billing,
    sync_billing_credits,
)
from app.services.billing_service import verify_payment_signature
from app.services.firm_access import assert_run_accessible, user_can_access_firm
from app.services.receipt_pdf import (
    GST_STATE_MAP,
    build_tax_invoice_pdf,
    invoice_filename_and_number,
)
from app.utils.audit import log_action
from app.utils.rate_limit import limiter
from app.services.payment_webhook_service import (
    fulfill_razorpay_payment_captured,
    handle_razorpay_refund_failed,
    handle_razorpay_refund_processed,
    mark_webhook_status,
    record_webhook_event,
)

_log = logging.getLogger(__name__)

payments_router = APIRouter()
billing_status_router = APIRouter()

_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def _verify_webhook(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


class CreateOrderBody(BaseModel):
    plan: str | None = None
    plan_name: str | None = None
    run_id: str | None = None
    billing_period: str = Field(default="yearly")
    billing_cycle: str | None = None
    custom_gstin_limit: int | None = None
    customer_gstin: str | None = None
    customer_trade_name: str | None = None
    customer_city: str | None = None
    customer_state_code: str | None = None
    coupon_code: str | None = None


class VerifyBody(BaseModel):
    order_id: str | None = None
    razorpay_order_id: str | None = None
    payment_id: str | None = None
    razorpay_payment_id: str | None = None
    signature: str | None = None
    razorpay_signature: str | None = None
    run_id: str | None = None
    plan: str | None = None
    plan_name: str | None = None
    billing_period: str = Field(default="yearly")
    billing_cycle: str | None = None
    custom_gstin_limit: int | None = None
    customer_gstin: str | None = None
    customer_trade_name: str | None = None
    customer_city: str | None = None
    customer_state_code: str | None = None
    coupon_code: str | None = None


def _parse_uuid(run_id: str, field: str = "run_id") -> str:
    try:
        return str(UUID(str(run_id).strip()))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid {field}",
        ) from exc


@payments_router.post("/create-order")
@limiter.limit("30/hour")
async def payments_create_order(
    request: Request,
    payload: CreateOrderBody,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    plan = (payload.plan or payload.plan_name or "starter").strip().lower()
    billing_period = (payload.billing_cycle or payload.billing_period or "yearly").strip().lower()

    run_id = None
    if payload.run_id and payload.run_id.strip():
        run_id = _parse_uuid(payload.run_id)
        row = assert_run_accessible(db, run_id, current_user)
        if row.get("paid_at"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="run already paid",
            )
        from app.services.firm_access import get_firm_owner_for_client
        firm_owner = get_firm_owner_for_client(db, str(row["client_gstin_id"]))
        receipt = run_id.replace("-", "")[:8]
    else:
        firm_owner = resolve_firm_owner_for_billing(db, current_user)
        receipt = f"SUB{int(datetime.now(timezone.utc).timestamp())}"[:8]

    forfeit_expired_credit_batches(db, firm_owner)
    if run_id:
        prof = get_user_profile(firm_owner) or {}
        free_left = int(prof.get("free_runs_remaining") or 0)
        if free_left > 0:
            return {
                "free": True,
                "run_unlocked": True,
                "free_runs_remaining": free_left,
            }

    details = get_plan_details(plan, billing_period, payload.custom_gstin_limit)

    coupon_breakdown = None
    if payload.coupon_code and payload.coupon_code.strip():
        from app.services.coupon_service import validate_coupon_for_checkout
        coupon_breakdown = validate_coupon_for_checkout(
            db,
            code=payload.coupon_code.strip(),
            plan=plan,
            billing_cycle=billing_period,
            firm_owner_id=firm_owner,
            user_email=current_user.get("email"),
        )

    base_paise = coupon_breakdown["discounted_base_paise"] if coupon_breakdown else int(details["base_paise"])
    gst_paise = coupon_breakdown["gst_paise"] if coupon_breakdown else int(details["gst_paise"])
    total_paise = coupon_breakdown["total_paise"] if coupon_breakdown else int(details["total_paise"])

    try:
        notes: dict[str, str] = {
            "user_id": firm_owner,
            "plan": details["plan"],
            "plan_version": "2",
            "billing_period": details["billing_period"],
            "gstin_limit": str(details["gstin_limit"]),
            "period_days": str(details["period_days"]),
            "overage_gstins": str(details["overage_gstins"]),
            "customer_gstin": (payload.customer_gstin or "").strip().upper()[:15],
            "customer_trade_name": (payload.customer_trade_name or "").strip()[:255],
            "customer_city": (payload.customer_city or "").strip()[:128],
            "customer_state_code": (payload.customer_state_code or "").strip()[:2],
        }
        if run_id:
            notes["run_id"] = run_id
        if coupon_breakdown:
            notes["coupon_id"] = str(coupon_breakdown["coupon_id"])
            notes["coupon_code"] = str(coupon_breakdown["code"])
            notes["discount_percentage"] = str(coupon_breakdown["discount_percentage"])
            notes["discount_amount_paise"] = str(coupon_breakdown["discount_amount_paise"])
            notes["original_base_paise"] = str(coupon_breakdown["original_base_paise"])

        order = _client.order.create(
            {
                "amount": total_paise,
                "currency": "INR",
                "payment_capture": 1,
                "receipt": receipt[:8],
                "notes": notes,
            }
        )
    except Exception as exc:  # noqa: BLE001
        _log.exception("Razorpay create_order failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service temporarily unavailable",
        ) from exc

    # Pre-record pending order row in Aurora payments table
    try:
        pending_payment = {
            "firm_owner_id": firm_owner,
            "razorpay_order_id": order["id"],
            "amount_paise": total_paise,
            "status": "created",
            "plan": details["plan"],
            "plan_version": 2,
            "billing_cycle": details["billing_period"],
            "gstin_limit": int(details["gstin_limit"]),
            "runs_purchased": 0,
            "base_amount_paise": base_paise,
            "gst_paise": gst_paise,
            "total_amount_paise": total_paise,
        }
        if coupon_breakdown:
            pending_payment["coupon_id"] = coupon_breakdown["coupon_id"]
            pending_payment["coupon_code"] = coupon_breakdown["code"]
            pending_payment["discount_percentage"] = coupon_breakdown["discount_percentage"]
            pending_payment["discount_amount_paise"] = coupon_breakdown["discount_amount_paise"]
        if run_id:
            pending_payment["run_id"] = run_id
        db.table("payments").insert(pending_payment).execute()
    except Exception as exc:
        _log.warning("Could not pre-insert pending payment: %s", exc)

    if coupon_breakdown:
        try:
            from app.services.coupon_service import record_pending_redemption
            record_pending_redemption(
                db,
                coupon_id=coupon_breakdown["coupon_id"],
                tenant_id=firm_owner,
                user_id=str(current_user.get("id")),
                razorpay_order_id=order["id"],
                pricing=coupon_breakdown,
                plan=details["plan"],
                billing_cycle=details["billing_period"],
            )
        except Exception as exc:
            _log.warning("Could not record pending coupon redemption: %s", exc)

    await log_action(
        str(current_user.get("id")),
        "PAYMENT_ORDER_CREATED",
        "razorpay_order",
        str(order.get("id")),
        {
            "plan": details["plan"],
            "amount": total_paise,
            "run_id": run_id,
            "coupon_code": coupon_breakdown["code"] if coupon_breakdown else None,
        },
        ip_address=(request.client.host if request.client else None),
    )

    resp_payload = {
        "order_id": order["id"],
        "amount": total_paise,
        "currency": order.get("currency", "INR"),
        "key": settings.RAZORPAY_KEY_ID,
        "plan": details["plan"],
        "billing_period": details["billing_period"],
        "gstin_limit": int(details["gstin_limit"]),
        "period_days": int(details["period_days"]),
        "base": base_paise,
        "gst": gst_paise,
        "overage_gstins": int(details["overage_gstins"]),
    }
    if coupon_breakdown:
        resp_payload["coupon_code"] = coupon_breakdown["code"]
        resp_payload["discount_percentage"] = coupon_breakdown["discount_percentage"]
        resp_payload["discount_amount_paise"] = coupon_breakdown["discount_amount_paise"]
        resp_payload["original_base_paise"] = coupon_breakdown["original_base_paise"]

    return resp_payload


@payments_router.post("/verify")
@limiter.limit("60/hour")
async def payments_verify(
    request: Request,
    payload: VerifyBody,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    order_id = (payload.order_id or payload.razorpay_order_id or "").strip()
    payment_id = (payload.payment_id or payload.razorpay_payment_id or "").strip()
    signature = (payload.signature or payload.razorpay_signature or "").strip()

    if not order_id or not payment_id or not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required payment verification fields (order_id, payment_id, signature)",
        )

    if not verify_payment_signature(order_id, payment_id, signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment signature",
        )

    pay_id = payment_id
    existing = (
        db.table("payments")
        .select(
            "id, run_id, firm_owner_id, plan, runs_purchased, total_amount_paise, amount_paise, status"
        )
        .eq("razorpay_payment_id", pay_id)
        .limit(1)
        .execute()
    )
    if existing.data and existing.data[0].get("status") in ("refunded", "refund_pending", "refund_failed"):
        st = existing.data[0].get("status")
        msg = "Coupon usage limit was reached during checkout. Your payment has been automatically refunded in full. Please try again."
        if st == "refund_pending":
            msg = "Coupon usage limit was reached during checkout. Your payment refund has been initiated and is pending gateway processing."
        elif st == "refund_failed":
            msg = "Coupon usage limit was reached during checkout. Automatic refund encountered an error and has been queued for reconciliation."
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
    if existing.data and existing.data[0].get("status") == "paid":
        owner_for_bal = str(existing.data[0].get("firm_owner_id") or "").strip()
        if owner_for_bal and not user_can_access_firm(db, current_user, owner_for_bal):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        prof = get_user_profile(owner_for_bal or resolve_firm_owner_for_billing(db, current_user)) or {}
        return {
            "success": True,
            "plan": existing.data[0].get("plan") or (payload.plan or payload.plan_name),
            "gstin_limit": int(prof.get("gstin_limit") or 0),
            "subscription_ends_at": prof.get("subscription_ends_at"),
            "idempotent": True,
        }

    run_id = None
    if payload.run_id and payload.run_id.strip():
        run_id = _parse_uuid(payload.run_id)
        row = assert_run_accessible(db, run_id, current_user)
        if row.get("paid_at"):
            raise HTTPException(status_code=400, detail="run already paid")
        from app.services.firm_access import get_firm_owner_for_client
        firm_owner = get_firm_owner_for_client(db, str(row["client_gstin_id"]))
    else:
        firm_owner = resolve_firm_owner_for_billing(db, current_user)

    plan = (payload.plan or payload.plan_name or "").strip().lower()
    billing_period = (payload.billing_cycle or payload.billing_period or "yearly").strip().lower()

    pending_row = None
    try:
        pending_res = (
            db.table("payments")
            .select("*")
            .eq("razorpay_order_id", order_id)
            .limit(1)
            .execute()
        )
        if pending_res.data:
            pending_row = pending_res.data[0]
            st = pending_row.get("status")
            if st in ("refunded", "refund_pending", "refund_failed"):
                msg = "Coupon usage limit was reached during checkout. Your payment has been automatically refunded in full. Please try again."
                if st == "refund_pending":
                    msg = "Coupon usage limit was reached during checkout. Your payment refund has been initiated and is pending gateway processing."
                elif st == "refund_failed":
                    msg = "Coupon usage limit was reached during checkout. Automatic refund encountered an error and has been queued for reconciliation."
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            if not plan:
                plan = (pending_row.get("plan") or "firm").lower()
                billing_period = (pending_row.get("billing_cycle") or billing_period).lower()
    except Exception as exc:
        _log.warning("Could not read pending payment for order %s: %s", order_id, exc)

    if not plan:
        plan = "firm"

    details = get_plan_details(plan, billing_period, payload.custom_gstin_limit)

    coupon_id = None
    coupon_code = None
    discount_percentage = None
    discount_amount_paise = 0

    if pending_row and pending_row.get("coupon_code"):
        coupon_id = pending_row.get("coupon_id")
        coupon_code = pending_row.get("coupon_code")
        discount_percentage = pending_row.get("discount_percentage")
        discount_amount_paise = int(pending_row.get("discount_amount_paise") or 0)
        base_amount_paise = int(pending_row.get("base_amount_paise") or details["base_paise"])
        gst_val = int(pending_row.get("gst_paise") or details["gst_paise"])
        total_amount_paise = int(pending_row.get("total_amount_paise") or details["total_paise"])
    else:
        # Check coupon_redemptions table for pending redemption by razorpay_order_id
        redemption_res = None
        try:
            redemption_res = (
                db.table("coupon_redemptions")
                .select("*")
                .eq("razorpay_order_id", order_id)
                .limit(1)
                .execute()
            )
        except Exception:
            pass

        if redemption_res and redemption_res.data:
            rdata = redemption_res.data[0]
            coupon_id = rdata.get("coupon_id")
            coupon_code = rdata.get("coupon_code")
            discount_amount_paise = int(rdata.get("discount_amount_paise") or 0)
            base_amount_paise = int(rdata.get("final_base_amount_paise") or details["base_paise"])
            gst_val = int(rdata.get("gst_amount_paise") or details["gst_paise"])
            total_amount_paise = int(rdata.get("total_amount_paise") or details["total_paise"])
        else:
            base_amount_paise = int(details["base_paise"])
            gst_val = int(details["gst_paise"])
            total_amount_paise = int(details["total_paise"])

    seller_state_code = (getattr(settings, "SELLER_STATE_CODE", "") or "27").strip()
    cust_gstin = (payload.customer_gstin or "").strip().upper() or None
    cust_name = (payload.customer_trade_name or "").strip() or None
    cust_city = (payload.customer_city or "").strip() or None
    cust_state_code = (payload.customer_state_code or "").strip() or None
    if not cust_state_code and cust_gstin and len(cust_gstin) >= 2 and cust_gstin[:2].isdigit():
        cust_state_code = cust_gstin[:2]
    if not cust_state_code:
        cust_state_code = seller_state_code

    is_inter = cust_state_code != seller_state_code
    tax_type = "inter" if is_inter else "intra"
    if is_inter:
        igst_paise = gst_val
        cgst_paise = 0
        sgst_paise = 0
    else:
        igst_paise = 0
        cgst_paise = gst_val // 2
        sgst_paise = gst_val - cgst_paise

    pay_row = {
        "firm_owner_id": firm_owner,
        "razorpay_order_id": order_id,
        "razorpay_payment_id": pay_id,
        "amount_paise": total_amount_paise,
        "status": "paid",
        "plan": details["plan"],
        "plan_version": 2,
        "billing_cycle": details["billing_period"],
        "gstin_limit": int(details["gstin_limit"]),
        "overage_gstins": int(details["overage_gstins"]),
        "overage_rate_paise": int(details["overage_rate_paise"]),
        "runs_purchased": 0,
        "base_amount_paise": base_amount_paise,
        "gst_paise": gst_val,
        "total_amount_paise": total_amount_paise,
        "coupon_id": coupon_id,
        "coupon_code": coupon_code,
        "discount_percentage": discount_percentage,
        "discount_amount_paise": discount_amount_paise,
        "customer_gstin": cust_gstin,
        "customer_trade_name": cust_name,
        "customer_city": cust_city,
        "customer_state_code": cust_state_code,
        "tax_type": tax_type,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "igst_paise": igst_paise,
    }
    if run_id:
        pay_row["run_id"] = run_id

    payment_rec = None
    if pending_row and pending_row.get("id"):
        try:
            up = db.table("payments").update(pay_row).eq("id", str(pending_row["id"])).execute()
            if up.data and len(up.data) > 0:
                payment_rec = up.data[0]
        except Exception as exc:
            _log.warning("payments update with v2 fields failed, falling back: %s", exc)
            try:
                up = db.table("payments").update({
                    "razorpay_payment_id": pay_id,
                    "status": "paid",
                    "amount_paise": total_amount_paise,
                    "total_amount_paise": total_amount_paise,
                }).eq("id", str(pending_row["id"])).execute()
                if up.data and len(up.data) > 0:
                    payment_rec = up.data[0]
            except Exception as exc2:
                _log.warning("payments fallback update failed: %s", exc2)

    if not payment_rec:
        try:
            check_exist = db.table("payments").select("*").eq("razorpay_order_id", order_id).limit(1).execute()
            if check_exist.data and len(check_exist.data) > 0:
                up = db.table("payments").update(pay_row).eq("id", str(check_exist.data[0]["id"])).execute()
                payment_rec = (up.data or [check_exist.data[0]])[0]
            else:
                ins = db.table("payments").insert(pay_row).execute()
                payment_rec = (ins.data or [{}])[0]
        except Exception as exc:
            _log.warning("payments insert with v2 fields failed, falling back: %s", exc)
            fallback_row = {
                "firm_owner_id": firm_owner,
                "razorpay_order_id": order_id,
                "razorpay_payment_id": pay_id,
                "amount_paise": total_amount_paise,
                "status": "paid",
                "plan": details["plan"],
                "runs_purchased": 0,
                "base_amount_paise": base_amount_paise,
                "gst_paise": gst_val,
                "total_amount_paise": total_amount_paise,
            }
            if run_id:
                fallback_row["run_id"] = run_id
            ins = db.table("payments").insert(fallback_row).execute()
            payment_rec = (ins.data or [{}])[0]

    payment_uuid = str(payment_rec.get("id", ""))

    fulfilled_red = None
    try:
        from app.services.coupon_service import fulfill_coupon_redemption
        fulfilled_red = fulfill_coupon_redemption(
            db,
            razorpay_order_id=order_id,
            payment_id=payment_uuid if payment_uuid else None,
            razorpay_payment_id=pay_id,
        )
    except Exception as exc:
        _log.warning("Exception during coupon fulfillment: %s", exc)

    if fulfilled_red is None:
        # Check if this order actually had a coupon redemption record that exceeded limits
        red_chk = None
        try:
            red_chk = (
                db.table("coupon_redemptions")
                .select("status")
                .eq("razorpay_order_id", order_id)
                .limit(1)
                .execute()
            )
        except Exception:
            pass

        if red_chk and red_chk.data and red_chk.data[0].get("status") == "limit_exceeded":
            _log.warning(
                "Coupon quota exceeded during checkout for order %s (payment %s). Triggering automatic refund.",
                order_id, pay_id,
            )
            rfnd = None
            ref_err = None
            try:
                rfnd = _client.payment.refund(
                    pay_id,
                    {
                        "amount": total_amount_paise,
                        "notes": {
                            "reason": "coupon_quota_exceeded",
                            "order_id": order_id,
                        },
                    },
                )
                _log.info("Automatic refund request dispatched for payment %s on order %s", pay_id, order_id)
            except Exception as exc:
                ref_err = exc
                _log.error("Automatic refund call failed for payment %s: %s", pay_id, exc)

            if ref_err:
                payment_status = "refund_failed"
                refund_status = "failed"
                refund_id = None
                detail_msg = "Coupon usage limit was reached during checkout. Automatic refund encountered an error and has been queued for reconciliation. Please contact support."
            else:
                rfnd_status = str(rfnd.get("status") or "").lower() if isinstance(rfnd, dict) else "pending"
                refund_id = str(rfnd.get("id") or "") if isinstance(rfnd, dict) else None
                if rfnd_status == "processed":
                    payment_status = "refunded"
                    refund_status = "processed"
                    detail_msg = "Coupon usage limit was reached during checkout. Your payment has been automatically refunded in full. Please try again."
                else:
                    payment_status = "refund_pending"
                    refund_status = "pending"
                    detail_msg = "Coupon usage limit was reached during checkout. Your payment refund has been initiated and is pending gateway processing."

            up_pay = {
                "status": payment_status,
                "refund_status": refund_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if refund_id:
                up_pay["refund_id"] = refund_id
            if ref_err:
                up_pay["refund_error"] = str(ref_err)

            if payment_uuid:
                try:
                    db.table("payments").update(up_pay).eq("id", payment_uuid).execute()
                except Exception as up_err:
                    _log.warning("Failed updating payment status in DB: %s", up_err)
            try:
                db.table("payments").update(up_pay).eq("razorpay_order_id", order_id).execute()
            except Exception:
                pass

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=detail_msg,
            )

    try:
        prof_updates: dict[str, Any] = {}
        if cust_gstin:
            prof_updates["firm_gstin"] = cust_gstin
        if cust_name:
            prof_updates["firm_name"] = cust_name
        if cust_city:
            prof_updates["firm_city"] = cust_city
        if prof_updates:
            db.table("user_profiles").update(prof_updates).eq("id", firm_owner).execute()
    except Exception as exc:
        _log.warning("Failed to auto-update profile from checkout: %s", exc)

    sub = await activate_subscription(
        firm_owner,
        details["plan"],
        payment_uuid if payment_uuid else None,
        billing_cycle=details["billing_period"],
        plan_version=2,
        custom_gstin_limit=details["gstin_limit"],
        log_ip=(request.client.host if request.client else None),
    )
    if run_id:
        await consume_run_credit(firm_owner)
        now = datetime.now(timezone.utc).isoformat()
        db.table("reconciliation_run").update({"paid_at": now}).eq("id", run_id).execute()

    # Send payment receipt email per preference
    try:
        from app.utils.notification_prefs import should_send_notification
        if should_send_notification(firm_owner, "payment_receipts"):
            from app.utils.email import send_payment_receipt_email
            owner_profile = get_user_profile(firm_owner) or {}
            owner_email = owner_profile.get("email")
            owner_name = owner_profile.get("full_name") or "there"
            if owner_email:
                import asyncio
                asyncio.create_task(
                    send_payment_receipt_email(
                        owner_email,
                        owner_name,
                        details["plan"],
                        int(details["total_paise"]),
                        payment_uuid,
                    )
                )
    except Exception as exc:
        _log.warning("Failed to trigger payment receipt email in backend: %s", exc)

    await log_action(
        str(current_user.get("id")),
        "PAYMENT_VERIFIED",
        "payment",
        payment_uuid,
        {"razorpay_payment_id": pay_id, "plan": details["plan"], "run_id": run_id},
        ip_address=(request.client.host if request.client else None),
    )

    invalidate_user_dashboard(str(current_user.get("id")))
    if firm_owner != str(current_user.get("id")):
        invalidate_user_dashboard(firm_owner)
    return {
        "success": True,
        "plan": sub["plan"],
        "gstin_limit": sub["gstin_limit"],
        "subscription_ends_at": sub["subscription_ends_at"],
    }


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@payments_router.post("/webhook")
async def payments_webhook(
    request: Request,
    db: Client = Depends(supabase_client),
):
    raw = await request.body()
    sig = (request.headers.get("X-Razorpay-Signature") or "").strip()
    if not sig or not _verify_webhook(raw, sig):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None

    event = payload.get("event") or "unknown"
    ent = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    ) or {}
    refund_ent = (
        payload.get("payload", {})
        .get("refund", {})
        .get("entity", {})
    ) or {}
    event_id = str(payload.get("id") or refund_ent.get("id") or ent.get("id") or "").strip()

    # Deduplicate event
    is_new, event_status = record_webhook_event(
        db,
        provider="razorpay",
        event_id=event_id,
        event_type=event,
        payload=payload,
    )
    if not is_new and event_status == "already_processed":
        _log.info("Ignoring duplicate Razorpay webhook event %s in payments webhook", event_id)
        return {"received": True, "duplicate": True}

    await log_action(
        None,
        "RAZORPAY_WEBHOOK",
        "webhook",
        str(event or ""),
        {"event": event, "id": refund_ent.get("id") or ent.get("id")},
    )

    try:
        if event == "payment.captured":
            await fulfill_razorpay_payment_captured(db, payload)
            await log_action(
                None,
                "PAYMENT_CAPTURED_WEBHOOK",
                "payment",
                str(ent.get("id") or ""),
                {"order_id": ent.get("order_id"), "amount": ent.get("amount"), "notes": ent.get("notes")},
            )
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
        elif event == "payment.failed":
            await log_action(
                None,
                "PAYMENT_FAILED",
                "payment",
                str(ent.get("id") or ""),
                {"order_id": ent.get("order_id"), "error": ent.get("error_description")},
            )
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
        elif event == "refund.processed":
            handle_razorpay_refund_processed(db, payload)
            await log_action(
                None,
                "REFUND_PROCESSED_WEBHOOK",
                "payment",
                str(refund_ent.get("payment_id") or ent.get("id") or ""),
                {"refund_id": refund_ent.get("id"), "payment_id": refund_ent.get("payment_id")},
            )
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
        elif event == "refund.failed":
            handle_razorpay_refund_failed(db, payload)
            await log_action(
                None,
                "REFUND_FAILED_WEBHOOK",
                "payment",
                str(refund_ent.get("payment_id") or ent.get("id") or ""),
                {
                    "refund_id": refund_ent.get("id"),
                    "payment_id": refund_ent.get("payment_id"),
                    "error": refund_ent.get("error_description"),
                },
            )
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
        else:
            mark_webhook_status(db, provider="razorpay", event_id=event_id, status="processed")
    except Exception as exc:  # noqa: BLE001
        _log.exception("webhook side-effect: %s", exc)
        mark_webhook_status(db, provider="razorpay", event_id=event_id, status="failed", error_message=str(exc))

    return {"received": True}


@payments_router.get("/history")
@limiter.limit("120/minute")
async def payments_history(
    request: Request,  # noqa: ARG001
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    firm_owner = resolve_firm_owner_for_billing(db, current_user)
    if not user_can_access_firm(db, current_user, firm_owner):
        raise HTTPException(status_code=403, detail="Access denied")

    res = (
        db.table("payments")
        .select(
            "id, created_at, plan, runs_purchased, base_amount_paise, gst_paise, "
            "total_amount_paise, amount_paise, status, razorpay_payment_id, run_id"
        )
        .eq("firm_owner_id", firm_owner)
        .order("created_at", desc=True)
        .execute()
    )
    rows_out: list[dict[str, Any]] = []
    for p in res.data or []:
        rid = p.get("run_id")
        trade_name: str | None = None
        period: str | None = None
        if rid:
            rres = (
                db.table("reconciliation_run")
                .select("client_gstin_id, period")
                .eq("id", str(rid))
                .limit(1)
                .execute()
            )
            if rres.data:
                cg_id = str(rres.data[0].get("client_gstin_id", ""))
                period = str(rres.data[0].get("period") or "")
                cg = (
                    db.table("client_gstins")
                    .select("trade_name")
                    .eq("id", cg_id)
                    .limit(1)
                    .execute()
                )
                if cg.data:
                    trade_name = str(cg.data[0].get("trade_name") or "")
        st = (p.get("status") or "").strip().lower()
        display = "PAID" if st == "paid" else "FAILED" if st == "failed" else st.upper() or "UNKNOWN"
        rows_out.append(
            {
                "payment_id": str(p.get("id")),
                "created_at": p.get("created_at"),
                "trade_name": trade_name,
                "period": period,
                "plan": p.get("plan"),
                "runs_purchased": p.get("runs_purchased"),
                "base_amount_paise": p.get("base_amount_paise"),
                "gst_paise": p.get("gst_paise"),
                "total_amount_paise": p.get("total_amount_paise") or p.get("amount_paise"),
                "status": display,
                "razorpay_payment_id": p.get("razorpay_payment_id"),
            }
        )
    return rows_out


@payments_router.get("/receipt/{payment_id}")
@limiter.limit("60/minute")
async def payments_receipt(
    request: Request,  # noqa: ARG001
    payment_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    try:
        UUID(payment_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid payment_id") from exc

    pres = (
        db.table("payments")
        .select("*")
        .eq("id", payment_id.strip())
        .limit(1)
        .execute()
    )
    if not pres.data:
        raise HTTPException(status_code=404, detail="payment not found")
    pay = pres.data[0]
    owner = str(pay.get("firm_owner_id", "")).strip()
    if not owner or not user_can_access_firm(db, current_user, owner):
        raise HTTPException(status_code=403, detail="Access denied")

    prof = get_user_profile(owner) or {}
    bill_to = {
        "firm_name": str(pay.get("customer_trade_name") or prof.get("firm_name") or ""),
        "firm_city": str(pay.get("customer_city") or prof.get("firm_city") or "—"),
        "firm_gstin": str(pay.get("customer_gstin") or prof.get("firm_gstin") or ""),
        "customer_state_code": str(pay.get("customer_state_code") or ""),
    }
    pdf = build_tax_invoice_pdf(pay, bill_to)
    fname, _ = invoice_filename_and_number(pay)
    bio = io.BytesIO(pdf)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@payments_router.get("/export-gstr1")
@limiter.limit("30/minute")
async def payments_export_gstr1(
    request: Request,  # noqa: ARG001
    year: int | None = None,
    month: int | None = None,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    """Export B2B & B2C sales register formatted for GSTR-1 filing."""
    firm_owner = resolve_firm_owner_for_billing(db, current_user)
    if not user_can_access_firm(db, current_user, firm_owner):
        raise HTTPException(status_code=403, detail="Access denied")

    query = (
        db.table("payments")
        .select("*")
        .eq("status", "paid")
        .order("created_at", desc=True)
    )
    if current_user.get("role") != "admin":
        query = query.eq("firm_owner_id", firm_owner)

    res = query.execute()
    payments_data = res.data or []

    if year or month:
        filtered = []
        for p in payments_data:
            dt = _parse_ts(p.get("created_at"))
            if not dt:
                continue
            if year and dt.year != year:
                continue
            if month and dt.month != month:
                continue
            filtered.append(p)
        payments_data = filtered

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "GSTIN/UIN of Recipient",
        "Receiver Name",
        "Invoice Number",
        "Invoice Date",
        "Invoice Value",
        "Place Of Supply",
        "Reverse Charge",
        "Applicable % of Tax Rate",
        "Invoice Type",
        "E-Commerce GSTIN",
        "Rate",
        "Taxable Value",
        "Cess Amount",
    ])

    seller_state_code = (getattr(settings, "SELLER_STATE_CODE", "") or "27").strip()
    for p in payments_data:
        _, inv_no = invoice_filename_and_number(p)
        inv_dt = _format_invoice_date(p.get("created_at"))
        base_val = round((p.get("base_amount_paise") or p.get("amount_paise") or 0) / 100, 2)
        tot_val = round((p.get("total_amount_paise") or p.get("amount_paise") or 0) / 100, 2)
        cust_gstin = str(p.get("customer_gstin") or "").strip().upper()
        cust_name = str(p.get("customer_trade_name") or "Customer").strip()
        state_code = str(
            p.get("customer_state_code")
            or (cust_gstin[:2] if len(cust_gstin) >= 2 and cust_gstin[:2].isdigit() else seller_state_code)
        ).strip()
        state_name = GST_STATE_MAP.get(state_code, "Other")
        pos = f"{state_code}-{state_name}"
        inv_type = "Regular" if cust_gstin else "B2C"

        writer.writerow([
            cust_gstin or "URP",
            cust_name,
            inv_no,
            inv_dt,
            f"{tot_val:.2f}",
            pos,
            "N",
            "",
            inv_type,
            "",
            "18.0",
            f"{base_val:.2f}",
            "0.00",
        ])

    csv_data = output.getvalue()
    filename = f"GSTR1_Sales_Register_{year or 'all'}_{month or 'all'}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@billing_status_router.get("/status")
@limiter.limit("120/minute")
async def billing_status(
    request: Request,  # noqa: ARG001
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    user_id = str(current_user.get("id", "")).strip()
    cache_key = f"cache:billing_status:{user_id}"
    cached_val = cache_get(cache_key)
    if cached_val is not None:
        return cached_val

    firm_owner = resolve_firm_owner_for_billing(db, current_user)
    synced = await sync_billing_credits(firm_owner)
    prof = get_user_profile(firm_owner) or {}
    plan_name = (prof.get("plan") or "free").strip() or "free"
    free_runs = synced["free_runs_remaining"]
    runs_balance = synced["runs_balance"]
    sub_active = has_active_subscription(db, firm_owner)
    gstin_limit = get_gstin_limit(db, firm_owner)
    gstins_used = count_gstins_toward_limit(db, firm_owner)
    subscription_ends_at = prof.get("subscription_ends_at")

    batches_res = (
        db.table("run_credits")
        .select(
            "plan, runs_purchased, runs_remaining, expires_at, purchased_at"
        )
        .eq("firm_owner_id", firm_owner)
        .order("expires_at", desc=False)
        .execute()
    )
    now = datetime.now(timezone.utc)
    soon = now + timedelta(days=7)
    credit_batches: list[dict[str, Any]] = []
    expiring_soon: list[dict[str, Any]] = []
    for b in batches_res.data or []:
        exp = _parse_ts(b.get("expires_at"))
        rem = int(b.get("runs_remaining") or 0)
        batch = {
            "plan": b.get("plan"),
            "runs_purchased": b.get("runs_purchased"),
            "runs_remaining": rem,
            "expires_at": b.get("expires_at"),
            "purchased_at": b.get("purchased_at"),
        }
        if exp is None:
            batch["status"] = "Active"
        elif exp <= now:
            batch["status"] = "Expired"
        elif exp <= soon and rem > 0:
            batch["status"] = "Use soon"
            expiring_soon.append(batch.copy())
        else:
            batch["status"] = "Active"
        credit_batches.append(batch)

    paid = (
        db.table("payments")
        .select("total_amount_paise, amount_paise, status")
        .eq("firm_owner_id", firm_owner)
        .execute()
    )
    total_spent = 0
    for row in paid.data or []:
        if str(row.get("status") or "").lower() != "paid":
            continue
        total_spent += int(
            row.get("total_amount_paise") if row.get("total_amount_paise") is not None else row.get("amount_paise") or 0
        )

    out = {
        "plan": plan_name,
        "free_runs_remaining": free_runs,
        "runs_balance": runs_balance,
        "gstin_limit": gstin_limit,
        "gstins_used": gstins_used,
        "subscription_ends_at": subscription_ends_at,
        "subscription_active": sub_active,
        "credit_batches": credit_batches,
        "expiring_soon": expiring_soon,
        "total_spent_paise": total_spent,
        "suggested_upgrade": free_runs == 0 and runs_balance == 0 and not sub_active,
    }
    cache_set(cache_key, out, ttl_seconds=30)
    return out


class SendReceiptBody(BaseModel):
    payment_id: str


@payments_router.post("/send-receipt")
async def payments_send_receipt(
    payload: SendReceiptBody,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    """Trigger a payment receipt email for a specific payment ID, if preferences allow."""
    payment_id = _parse_uuid(payload.payment_id, "payment_id")
    try:
        res = db.table("payments").select("*").eq("id", payment_id).limit(1).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Payment not found")

        payment = res.data[0]
        firm_owner = payment.get("firm_owner_id")

        if firm_owner and not user_can_access_firm(db, current_user, firm_owner):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        # Check notification preferences
        from app.utils.notification_prefs import should_send_notification
        if firm_owner and should_send_notification(firm_owner, "payment_receipts"):
            from app.utils.email import send_payment_receipt_email
            owner_profile = get_user_profile(firm_owner) or {}
            owner_email = owner_profile.get("email")
            owner_name = owner_profile.get("full_name") or "there"
            if owner_email:
                import asyncio
                asyncio.create_task(
                    send_payment_receipt_email(
                        owner_email,
                        owner_name,
                        payment.get("plan", "starter"),
                        int(payment.get("total_amount_paise") or payment.get("amount_paise") or 0),
                        str(payment.get("id")),
                    )
                )
                return {"success": True, "message": "Receipt email triggered"}

        return {"success": True, "message": "Receipt email skipped per preference"}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("Failed to send receipt email for payment %s", payment_id)
        raise HTTPException(status_code=500, detail=str(exc))

