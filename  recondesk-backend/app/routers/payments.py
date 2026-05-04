"""Run-based billing: Razorpay orders, verify, webhooks, receipts, billing status."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from supabase import Client

from app.auth import get_current_active_user
from app.config import settings
from app.database import get_user_profile, supabase_client
from app.services.billing_gate import (
    PLAN_CONFIG,
    add_run_credits,
    consume_run_credit,
    forfeit_expired_credit_batches,
    resolve_firm_owner_for_billing,
)
from app.services.billing_service import verify_payment_signature
from app.services.firm_access import assert_run_accessible, user_can_access_firm
from app.services.receipt_pdf import build_tax_invoice_pdf, invoice_filename_and_number
from app.utils.audit import log_action
from app.utils.rate_limit import limiter

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


class VerifyBody(BaseModel):
    order_id: str = Field(..., min_length=1)
    payment_id: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    plan: str = Field(..., min_length=1)


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
    if plan not in PLAN_CONFIG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid plan",
        )
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

    cfg = PLAN_CONFIG[plan]
    receipt = run_id.replace("-", "")[:8]
    try:
        order = _client.order.create(
            {
                "amount": cfg["total_paise"],
                "currency": "INR",
                "payment_capture": 1,
                "receipt": receipt[:8],
                "notes": {
                    "user_id": firm_owner,
                    "run_id": run_id,
                    "plan": plan,
                    "runs": str(cfg["runs"]),
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
        {"plan": plan, "amount": cfg["total_paise"], "run_id": run_id},
        ip_address=(request.client.host if request.client else None),
    )

    return {
        "order_id": order["id"],
        "amount": cfg["total_paise"],
        "currency": order.get("currency", "INR"),
        "key": settings.RAZORPAY_KEY_ID,
        "plan": plan,
        "runs": cfg["runs"],
        "base": cfg["base_paise"],
        "gst": cfg["gst_paise"],
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
    if plan not in PLAN_CONFIG:
        raise HTTPException(status_code=400, detail="invalid plan")
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
            "runs_added": int(existing.data[0].get("runs_purchased") or 0),
            "runs_balance": int(prof.get("runs_balance") or 0),
            "idempotent": True,
        }

    row = assert_run_accessible(db, run_id, current_user)
    if row.get("paid_at"):
        raise HTTPException(status_code=400, detail="run already paid")

    from app.services.firm_access import get_firm_owner_for_client

    firm_owner = get_firm_owner_for_client(db, str(row["client_gstin_id"]))
    cfg = PLAN_CONFIG[plan]

    pay_row = {
        "firm_owner_id": firm_owner,
        "run_id": run_id,
        "razorpay_order_id": payload.order_id.strip(),
        "razorpay_payment_id": pay_id,
        "amount_paise": cfg["total_paise"],
        "status": "paid",
        "plan": plan,
        "runs_purchased": cfg["runs"],
        "base_amount_paise": cfg["base_paise"],
        "gst_paise": cfg["gst_paise"],
        "total_amount_paise": cfg["total_paise"],
    }
    ins = db.table("payments").insert(pay_row).execute()
    payment_rec = (ins.data or [{}])[0]
    payment_uuid = str(payment_rec.get("id", ""))

    await add_run_credits(
        firm_owner,
        plan,
        payment_uuid if payment_uuid else None,
        log_ip=(request.client.host if request.client else None),
    )
    await consume_run_credit(firm_owner)
    now = datetime.now(timezone.utc).isoformat()
    db.table("reconciliation_run").update({"paid_at": now}).eq("id", run_id).execute()

    prof2 = get_user_profile(firm_owner) or {}
    await log_action(
        str(current_user.get("id")),
        "PAYMENT_VERIFIED",
        "payment",
        payment_uuid,
        {"razorpay_payment_id": pay_id, "plan": plan, "run_id": run_id},
        ip_address=(request.client.host if request.client else None),
    )

    return {
        "success": True,
        "runs_added": cfg["runs"],
        "runs_balance": int(prof2.get("runs_balance") or 0),
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

    event = payload.get("event")
    await log_action(
        None,
        "RAZORPAY_WEBHOOK",
        "webhook",
        str(event or ""),
        {"event": event, "id": payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id")},
    )

    try:
        if event == "payment.captured":
            ent = payload.get("payload", {}).get("payment", {}).get("entity", {}) or {}
            await log_action(
                None,
                "PAYMENT_CAPTURED_WEBHOOK",
                "payment",
                str(ent.get("id") or ""),
                {"order_id": ent.get("order_id"), "amount": ent.get("amount"), "notes": ent.get("notes")},
            )
        elif event == "payment.failed":
            ent = payload.get("payload", {}).get("payment", {}).get("entity", {}) or {}
            await log_action(
                None,
                "PAYMENT_FAILED",
                "payment",
                str(ent.get("id") or ""),
                {"order_id": ent.get("order_id"), "error": ent.get("error_description")},
            )
    except Exception as exc:  # noqa: BLE001
        _log.exception("webhook side-effect: %s", exc)

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
        "firm_name": str(prof.get("firm_name") or ""),
        "firm_city": str(prof.get("firm_city") or "—"),
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


@billing_status_router.get("/status")
@limiter.limit("120/minute")
async def billing_status(
    request: Request,  # noqa: ARG001
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    firm_owner = resolve_firm_owner_for_billing(db, current_user)
    forfeit_expired_credit_batches(db, firm_owner)
    prof = get_user_profile(firm_owner) or {}
    plan_name = (prof.get("plan") or "free").strip() or "free"
    free_runs = int(prof.get("free_runs_remaining") or 0)
    runs_balance = int(prof.get("runs_balance") or 0)

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
    soon = now + timedelta(days=30)
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
            batch["status"] = "Expiring Soon"
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

    return {
        "plan": plan_name,
        "free_runs_remaining": free_runs,
        "runs_balance": runs_balance,
        "credit_batches": credit_batches,
        "expiring_soon": expiring_soon,
        "total_spent_paise": total_spent,
        "suggested_upgrade": free_runs == 0 and runs_balance == 0,
    }
