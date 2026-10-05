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
    plan: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    billing_period: str = Field(default="yearly")
    custom_gstin_limit: int | None = None
    customer_gstin: str | None = None
    customer_trade_name: str | None = None
    customer_city: str | None = None
    customer_state_code: str | None = None


class VerifyBody(BaseModel):
    order_id: str = Field(..., min_length=1)
    payment_id: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    plan: str = Field(..., min_length=1)
    billing_period: str = Field(default="yearly")
    custom_gstin_limit: int | None = None
    customer_gstin: str | None = None
    customer_trade_name: str | None = None
    customer_city: str | None = None
    customer_state_code: str | None = None


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
    plan = payload.plan.strip().lower()
    billing_period = payload.billing_period.strip().lower()
    run_id = _parse_uuid(payload.run_id)
    row = assert_run_accessible(db, run_id, current_user)
    if row.get("paid_at"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run already paid",
        )

    firm_owner = resolve_firm_owner_for_billing(db, current_user)
    # Ensure run belongs to same firm as billing account
    from app.services.firm_access import get_firm_owner_for_client

    run_owner = get_firm_owner_for_client(db, str(row["client_gstin_id"]))
    if run_owner != firm_owner:
        firm_owner = run_owner

    forfeit_expired_credit_batches(db, firm_owner)
    prof = get_user_profile(firm_owner) or {}
    free_left = int(prof.get("free_runs_remaining") or 0)
    if free_left > 0:
        return {
            "free": True,
            "run_unlocked": True,
            "free_runs_remaining": free_left,
        }

    details = get_plan_details(plan, billing_period, payload.custom_gstin_limit)
    receipt = run_id.replace("-", "")[:8]
    try:
        order = _client.order.create(
            {
                "amount": int(details["total_paise"]),
                "currency": "INR",
                "payment_capture": 1,
                "receipt": receipt[:8],
                "notes": {
                    "user_id": firm_owner,
                    "run_id": run_id,
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
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        _log.exception("Razorpay create_order failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service temporarily unavailable",
        ) from exc

    await log_action(
        str(current_user.get("id")),
        "PAYMENT_ORDER_CREATED",
        "razorpay_order",
        str(order.get("id")),
        {"plan": details["plan"], "amount": int(details["total_paise"]), "run_id": run_id},
        ip_address=(request.client.host if request.client else None),
    )

    return {
        "order_id": order["id"],
        "amount": int(details["total_paise"]),
        "currency": order.get("currency", "INR"),
        "key": settings.RAZORPAY_KEY_ID,
        "plan": details["plan"],
        "billing_period": details["billing_period"],
        "gstin_limit": int(details["gstin_limit"]),
        "period_days": int(details["period_days"]),
        "base": int(details["base_paise"]),
        "gst": int(details["gst_paise"]),
        "overage_gstins": int(details["overage_gstins"]),
    }


@payments_router.post("/verify")
@limiter.limit("60/hour")
async def payments_verify(
    request: Request,
    payload: VerifyBody,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    plan = payload.plan.strip().lower()
    billing_period = payload.billing_period.strip().lower()
    run_id = _parse_uuid(payload.run_id)
    if not verify_payment_signature(
        payload.order_id.strip(),
        payload.payment_id.strip(),
        payload.signature.strip(),
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment signature",
        )

    pay_id = payload.payment_id.strip()
    existing = (
        db.table("payments")
        .select(
            "id, run_id, firm_owner_id, plan, runs_purchased, total_amount_paise, amount_paise"
        )
        .eq("razorpay_payment_id", pay_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        owner_for_bal = str(existing.data[0].get("firm_owner_id") or "").strip()
        if owner_for_bal and not user_can_access_firm(db, current_user, owner_for_bal):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        prof = get_user_profile(owner_for_bal or resolve_firm_owner_for_billing(db, current_user)) or {}
        return {
            "success": True,
            "plan": existing.data[0].get("plan") or plan,
            "gstin_limit": int(prof.get("gstin_limit") or 0),
            "subscription_ends_at": prof.get("subscription_ends_at"),
            "idempotent": True,
        }

    row = assert_run_accessible(db, run_id, current_user)
    if row.get("paid_at"):
        raise HTTPException(status_code=400, detail="run already paid")

    from app.services.firm_access import get_firm_owner_for_client

    firm_owner = get_firm_owner_for_client(db, str(row["client_gstin_id"]))
    details = get_plan_details(plan, billing_period, payload.custom_gstin_limit)

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
    gst_val = int(details["gst_paise"])
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
        "run_id": run_id,
        "razorpay_order_id": payload.order_id.strip(),
        "razorpay_payment_id": pay_id,
        "amount_paise": int(details["total_paise"]),
        "status": "paid",
        "plan": details["plan"],
        "plan_version": 2,
        "billing_cycle": details["billing_period"],
        "gstin_limit": int(details["gstin_limit"]),
        "overage_gstins": int(details["overage_gstins"]),
        "overage_rate_paise": int(details["overage_rate_paise"]),
        "runs_purchased": 0,
        "base_amount_paise": int(details["base_paise"]),
        "gst_paise": gst_val,
        "total_amount_paise": int(details["total_paise"]),
        "customer_gstin": cust_gstin,
        "customer_trade_name": cust_name,
        "customer_city": cust_city,
        "customer_state_code": cust_state_code,
        "tax_type": tax_type,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "igst_paise": igst_paise,
    }
    try:
        ins = db.table("payments").insert(pay_row).execute()
    except Exception as exc:
        _log.warning("payments insert with v2 fields failed, falling back: %s", exc)
        fallback_row = {
            "firm_owner_id": firm_owner,
            "run_id": run_id,
            "razorpay_order_id": payload.order_id.strip(),
            "razorpay_payment_id": pay_id,
            "amount_paise": int(details["total_paise"]),
            "status": "paid",
            "plan": details["plan"],
            "runs_purchased": 0,
            "base_amount_paise": int(details["base_paise"]),
            "gst_paise": gst_val,
            "total_amount_paise": int(details["total_paise"]),
        }
        ins = db.table("payments").insert(fallback_row).execute()

    payment_rec = (ins.data or [{}])[0]
    payment_uuid = str(payment_rec.get("id", ""))

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
    event_id = str(payload.get("id") or ent.get("id") or "").strip()

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
        {"event": event, "id": ent.get("id")},
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

