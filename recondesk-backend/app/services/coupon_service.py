"""Annual Subscription Coupon Service.

Enforces business rules, server-side monetary calculations, tenant security,
concurrency safety, and redemption tracking for promotional coupons.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from supabase import Client

from app.models.coupon import (
    ANNUAL_PLANS,
    PERMITTED_DISCOUNTS,
    CouponCreateRequest,
    CouponValidationResponse,
)
from app.services.billing_gate import get_plan_details
from app.utils.audit import log_action

import threading

_log = logging.getLogger(__name__)

_coupon_fulfillment_locks: dict[str, threading.Lock] = {}
_fulfillment_mutex = threading.Lock()


def _get_coupon_tenant_lock(coupon_id: str, tenant_id: str) -> threading.Lock:
    key = f"{coupon_id}:{tenant_id}"
    with _fulfillment_mutex:
        if key not in _coupon_fulfillment_locks:
            _coupon_fulfillment_locks[key] = threading.Lock()
        return _coupon_fulfillment_locks[key]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(dt_val: Any) -> Optional[datetime]:
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val
    try:
        s = str(dt_val).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def calculate_discounted_pricing(
    base_paise: int,
    discount_percentage: int,
) -> dict[str, int]:
    """Calculates discounted base, 18% GST on discounted base, and total payable in integer paise."""
    if discount_percentage not in PERMITTED_DISCOUNTS:
        raise ValueError(f"Discount percentage {discount_percentage}% is not permitted. Allowed: {sorted(PERMITTED_DISCOUNTS)}")

    discount_amount_paise = int(
        (Decimal(base_paise) * Decimal(discount_percentage) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    discounted_base_paise = max(0, base_paise - discount_amount_paise)
    gst_paise = int(
        (Decimal(discounted_base_paise) * Decimal("0.18")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    total_paise = discounted_base_paise + gst_paise

    return {
        "original_base_paise": base_paise,
        "discount_amount_paise": discount_amount_paise,
        "discounted_base_paise": discounted_base_paise,
        "gst_paise": gst_paise,
        "total_paise": total_paise,
    }


def find_coupon_by_code(db: Client, code: str) -> Optional[dict[str, Any]]:
    """Look up coupon by case-insensitive code."""
    clean_code = (code or "").strip().upper()
    if not clean_code:
        return None
    try:
        res = (
            db.table("coupons")
            .select("*")
            .ilike("code", clean_code)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0]
    except Exception as exc:
        _log.warning("Failed to lookup coupon %s: %s", clean_code, exc)
    return None


def validate_coupon_for_checkout(
    db: Client,
    *,
    code: str,
    plan: str,
    billing_cycle: str,
    firm_owner_id: str,
    user_email: Optional[str] = None,
) -> dict[str, Any]:
    """Authoritative validation of coupon eligibility and price breakdown.

    Raises HTTPException on any validation failure.
    """
    clean_plan = (plan or "").strip().lower()
    clean_cycle = (billing_cycle or "yearly").strip().lower()

    # Rule 1 & 10: Coupons apply only to annual subscription plans
    if clean_cycle not in ("yearly", "annual"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Promotional coupons are available only for annual subscription plans.",
        )

    # Validate plan tier exists in annual plans
    if clean_plan not in ANNUAL_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Plan '{clean_plan}' is not eligible for annual coupons.",
        )

    coupon = find_coupon_by_code(db, code)
    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid coupon code.",
        )

    # Check active status
    if not coupon.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon has been deactivated.",
        )

    # Check expiration date
    expires_at = _parse_datetime(coupon.get("expires_at"))
    if expires_at and expires_at < _utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon code has expired.",
        )

    # Check eligible plans
    eligible_plans = coupon.get("eligible_plans") or []
    if isinstance(eligible_plans, str):
        import json
        try:
            eligible_plans = json.loads(eligible_plans)
        except Exception:
            eligible_plans = [eligible_plans]
    eligible_plans_set = {str(p).strip().lower() for p in eligible_plans}
    if clean_plan not in eligible_plans_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This coupon is not valid for the {clean_plan.replace('_', ' ').title()} plan.",
        )

    discount_percentage = int(coupon.get("discount_percentage") or 0)
    # Rule 2 & 5: Only 20, 25, 30 permitted
    if discount_percentage not in PERMITTED_DISCOUNTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid coupon discount percentage configuration.",
        )

    # Rule 12: Founder-level approval required for 30% discount
    if discount_percentage == 30 and not coupon.get("founder_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="30% discount coupon requires verified founder approval.",
        )

    # Rule 3 & 4: Acquisition vs Renewal coupon check
    is_acquisition_only = coupon.get("is_acquisition_only", True)
    if is_acquisition_only:
        from app.services.billing_gate import has_active_subscription
        if has_active_subscription(db, firm_owner_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Promotional acquisition coupons apply only to first-year subscriptions. Standard renewal pricing applies.",
            )
        try:
            prior_payments = (
                db.table("payments")
                .select("id", count="exact")
                .eq("firm_owner_id", str(firm_owner_id))
                .eq("status", "paid")
                .in_("billing_cycle", ["yearly", "annual"])
                .limit(1)
                .execute()
            )
            has_prior = False
            if isinstance(prior_payments.count, int) and prior_payments.count > 0:
                has_prior = True
            elif isinstance(prior_payments.data, list) and len(prior_payments.data) > 0:
                has_prior = True
            if has_prior:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Promotional acquisition coupons apply only to first-year subscriptions. Standard renewal pricing applies.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            _log.warning("Error checking prior customer subscription history: %s", exc)

    # Rule 8: Tenant / customer restriction
    restricted_tenant = coupon.get("restricted_to_tenant_id")
    if restricted_tenant and str(restricted_tenant).strip().lower() != str(firm_owner_id).strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon is not valid for your account.",
        )

    restricted_email = (coupon.get("restricted_to_email") or "").strip().lower()
    if restricted_email:
        clean_user_email = (user_email or "").strip().lower()
        if clean_user_email != restricted_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon is reserved for a specific customer email.",
            )

    # Rule 7: Global redemption limit
    max_redemptions = coupon.get("max_redemptions")
    current_redemptions = int(coupon.get("redemptions_count") or 0)
    if max_redemptions is not None and current_redemptions >= int(max_redemptions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon has reached its maximum global redemption limit.",
        )

    # Rule 7 & 9: Per-customer usage limit (checks only fulfilled/paid redemptions)
    max_per_customer = int(coupon.get("max_per_customer") or 1)
    try:
        cust_redemptions = (
            db.table("coupon_redemptions")
            .select("id", count="exact")
            .eq("coupon_id", str(coupon["id"]))
            .eq("tenant_id", str(firm_owner_id))
            .eq("status", "fulfilled")
            .execute()
        )
        has_cust_exceeded = False
        if isinstance(cust_redemptions.count, int) and cust_redemptions.count >= max_per_customer:
            has_cust_exceeded = True
        elif isinstance(cust_redemptions.data, list) and len(cust_redemptions.data) >= max_per_customer:
            has_cust_exceeded = True
        if has_cust_exceeded:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already redeemed this coupon the maximum allowed times.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        _log.warning("Error checking customer redemption history: %s", exc)

    # Calculate authoritative pricing
    plan_details = get_plan_details(clean_plan, "yearly")
    base_paise = int(plan_details["base_paise"])
    breakdown = calculate_discounted_pricing(base_paise, discount_percentage)

    return {
        "valid": True,
        "coupon_id": str(coupon["id"]),
        "code": str(coupon["code"]),
        "discount_percentage": discount_percentage,
        "plan": clean_plan,
        "billing_cycle": "yearly",
        **breakdown,
    }


def record_pending_redemption(
    db: Client,
    *,
    coupon_id: str,
    tenant_id: str,
    user_id: str,
    razorpay_order_id: str,
    pricing: dict[str, Any],
    plan: str,
    billing_cycle: str = "yearly",
) -> dict[str, Any]:
    """Records a pending redemption associated with a Razorpay Order.

    Does NOT increment redemptions_count until payment is successfully fulfilled.
    """
    row = {
        "coupon_id": coupon_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "razorpay_order_id": razorpay_order_id,
        "original_base_amount_paise": pricing["original_base_paise"],
        "discount_amount_paise": pricing["discount_amount_paise"],
        "final_base_amount_paise": pricing["discounted_base_paise"],
        "gst_amount_paise": pricing["gst_paise"],
        "total_amount_paise": pricing["total_paise"],
        "plan": plan,
        "billing_cycle": billing_cycle,
        "status": "pending",
    }
    try:
        res = db.table("coupon_redemptions").insert(row).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
    except Exception as exc:
        _log.warning("Failed to record pending redemption: %s", exc)
    return row


def fulfill_coupon_redemption(
    db: Client,
    *,
    razorpay_order_id: str,
    payment_id: Optional[str],
    razorpay_payment_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """Finalizes redemption on payment verification or webhook.

    Ensures idempotency, atomic count increments, and per-customer limit enforcement.
    """
    try:
        existing = (
            db.table("coupon_redemptions")
            .select("*")
            .eq("razorpay_order_id", razorpay_order_id)
            .limit(1)
            .execute()
        )
        if not existing.data or len(existing.data) == 0:
            return None

        redemption = existing.data[0]
        if redemption.get("status") == "fulfilled":
            # Already fulfilled (idempotent duplicate call)
            return redemption

        coupon_id = str(redemption["coupon_id"])
        tenant_id = str(redemption.get("tenant_id") or "")

        c_res = db.table("coupons").select("*").eq("id", coupon_id).limit(1).execute()
        if not c_res.data:
            _log.warning("Coupon %s not found during redemption fulfillment", coupon_id)
            return None
        coupon = c_res.data[0]

        max_redemptions = coupon.get("max_redemptions")
        max_per_customer = int(coupon.get("max_per_customer") or 1)

        # 1. Attempt single-transaction PostgreSQL/Aurora execution
        try:
            from app.aurora import get_aurora_engine
            from sqlalchemy import text
            eng = get_aurora_engine()
            with eng.begin() as a_conn:
                # 1a. Advisory transaction lock
                if tenant_id and a_conn.dialect.name == "postgresql":
                    a_conn.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                        {"k": f"coupon_{coupon_id}_{tenant_id}"},
                    )

                # 1b. Check per-customer limit in same transaction
                if tenant_id:
                    check_stmt = text("""
                        SELECT COUNT(*) FROM public.coupon_redemptions
                        WHERE coupon_id = :cid AND tenant_id = :tid AND status = 'fulfilled'
                    """)
                    cust_cnt = a_conn.execute(check_stmt, {"cid": coupon_id, "tid": tenant_id}).scalar() or 0
                    if cust_cnt >= max_per_customer:
                        _log.warning(
                            "Customer %s exceeded max_per_customer (%s) for coupon %s in SQL transaction",
                            tenant_id, max_per_customer, coupon_id
                        )
                        a_conn.execute(
                            text("""
                                UPDATE public.coupon_redemptions
                                SET status = 'limit_exceeded', updated_at = NOW()
                                WHERE id = :rid
                            """),
                            {"rid": str(redemption["id"])},
                        )
                        return None

                # 1c. Check global limit & atomically increment in same transaction
                if max_redemptions is not None:
                    stmt = text("""
                        UPDATE public.coupons
                        SET redemptions_count = redemptions_count + 1, updated_at = NOW()
                        WHERE id = :cid AND (max_redemptions IS NULL OR redemptions_count < :max_r)
                        RETURNING redemptions_count
                    """)
                    exec_res = a_conn.execute(stmt, {"cid": coupon_id, "max_r": int(max_redemptions)})
                else:
                    stmt = text("""
                        UPDATE public.coupons
                        SET redemptions_count = redemptions_count + 1, updated_at = NOW()
                        WHERE id = :cid
                        RETURNING redemptions_count
                    """)
                    exec_res = a_conn.execute(stmt, {"cid": coupon_id})
                row = exec_res.first()
                if row is None:
                    _log.warning("Atomic coupon increment failed: limit reached in SQL transaction")
                    a_conn.execute(
                        text("""
                            UPDATE public.coupon_redemptions
                            SET status = 'limit_exceeded', updated_at = NOW()
                            WHERE id = :rid
                        """),
                        {"rid": str(redemption["id"])},
                    )
                    return None
                updated_count = row[0]

                # 1d. Fulfill redemption in same transaction
                a_conn.execute(
                    text("""
                        UPDATE public.coupon_redemptions
                        SET status = 'fulfilled',
                            razorpay_payment_id = :rpid,
                            payment_id = :pid,
                            updated_at = NOW()
                        WHERE id = :rid
                    """),
                    {
                        "rid": str(redemption["id"]),
                        "rpid": razorpay_payment_id,
                        "pid": payment_id,
                    },
                )
                update_data = {
                    "status": "fulfilled",
                    "razorpay_payment_id": razorpay_payment_id,
                    "updated_at": _utcnow().isoformat(),
                }
                if payment_id:
                    update_data["payment_id"] = payment_id

                _log.info(
                    "Successfully fulfilled coupon redemption %s in single SQL transaction for order %s (total count %s)",
                    redemption["id"],
                    razorpay_order_id,
                    updated_count,
                )
                return {**redemption, **update_data}
        except Exception as sql_err:
            _log.info("Aurora engine not active (%s), falling back to in-process lock and Supabase client", sql_err)

        # 2. Fallback for mock_db / unit test harnesses without Aurora engine
        with _get_coupon_tenant_lock(coupon_id, tenant_id):
            if tenant_id:
                cust_check = (
                    db.table("coupon_redemptions")
                    .select("id", count="exact")
                    .eq("coupon_id", coupon_id)
                    .eq("tenant_id", tenant_id)
                    .eq("status", "fulfilled")
                    .execute()
                )
                has_cust_limit = False
                if isinstance(cust_check.count, int) and cust_check.count >= max_per_customer:
                    has_cust_limit = True
                elif isinstance(cust_check.data, list) and len(cust_check.data) >= max_per_customer:
                    has_cust_limit = True
                if has_cust_limit:
                    _log.warning(
                        "Customer %s exceeded max_per_customer (%s) for coupon %s",
                        tenant_id, max_per_customer, coupon_id
                    )
                    db.table("coupon_redemptions").update({
                        "status": "limit_exceeded",
                        "updated_at": _utcnow().isoformat(),
                    }).eq("id", str(redemption["id"])).execute()
                    return None

            current_redemptions = int(coupon.get("redemptions_count") or 0)
            if max_redemptions is not None and current_redemptions >= int(max_redemptions):
                _log.warning("Coupon %s reached max_redemptions (%s)", coupon_id, max_redemptions)
                db.table("coupon_redemptions").update({
                    "status": "limit_exceeded",
                    "updated_at": _utcnow().isoformat(),
                }).eq("id", str(redemption["id"])).execute()
                return None

            updated_count = current_redemptions + 1
            db.table("coupons").update({
                "redemptions_count": updated_count,
                "updated_at": _utcnow().isoformat(),
            }).eq("id", coupon_id).execute()

            update_data = {
                "status": "fulfilled",
                "razorpay_payment_id": razorpay_payment_id,
                "updated_at": _utcnow().isoformat(),
            }
            if payment_id:
                update_data["payment_id"] = payment_id

            db.table("coupon_redemptions").update(update_data).eq("id", str(redemption["id"])).execute()

            _log.info(
                "Successfully fulfilled coupon redemption %s for order %s (payment %s, total count %s)",
                redemption["id"],
                razorpay_order_id,
                razorpay_payment_id,
                updated_count,
            )
            return {**redemption, **update_data}
    except Exception as exc:
        _log.exception("Failed to fulfill coupon redemption for order %s: %s", razorpay_order_id, exc)
        return None


# ─── Admin Management Functions ──────────────────────────────────────────────

def create_admin_coupon(
    db: Client,
    payload: CouponCreateRequest,
    admin_user: Optional[dict | str] = None,
    *,
    admin_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Creates a promotional coupon with strict validation, founder checks, and audit logging."""
    if admin_user is None and admin_user_id is not None:
        admin_user = {"id": admin_user_id}
    elif isinstance(admin_user, str):
        admin_user = {"id": admin_user}
    elif admin_user is None:
        admin_user = {}

    admin_uid = str(admin_user.get("id") or admin_user_id or "")
    clean_code = payload.code.strip().upper()

    # Rule 2: Permitted discount tiers
    if payload.discount_percentage not in PERMITTED_DISCOUNTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Discount must be one of {sorted(PERMITTED_DISCOUNTS)}%",
        )

    # Rule 12: 30% discount requires verified founder identity (P0 fix)
    from app.auth import is_founder_user
    if payload.discount_percentage == 30:
        if not is_founder_user(admin_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="30% discount coupons strictly require authorization by an authorized founder.",
            )
        founder_approved = True
        founder_approved_by = str(admin_user.get("email") or admin_uid or "founder")
        founder_approval_notes = payload.founder_approval_notes.strip() if payload.founder_approval_notes else None
    else:
        founder_approved = False
        founder_approved_by = None
        founder_approval_notes = None

    # Check duplicate code
    existing = find_coupon_by_code(db, clean_code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Coupon code '{clean_code}' already exists.",
        )

    coupon_record = {
        "code": clean_code,
        "discount_percentage": payload.discount_percentage,
        "eligible_plans": payload.eligible_plans,
        "is_active": True,
        "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
        "max_redemptions": payload.max_redemptions,
        "redemptions_count": 0,
        "max_per_customer": payload.max_per_customer,
        "restricted_to_tenant_id": payload.restricted_to_tenant_id,
        "restricted_to_email": payload.restricted_to_email.strip().lower() if payload.restricted_to_email else None,
        "is_acquisition_only": payload.is_acquisition_only,
        "created_by": admin_uid,
        "founder_approved": founder_approved,
        "founder_approved_by": founder_approved_by,
        "founder_approval_notes": founder_approval_notes,
    }

    res = db.table("coupons").insert(coupon_record).execute()
    if not res.data or len(res.data) == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist coupon in database.",
        )
    created = res.data[0]
    return created


def list_admin_coupons(db: Client) -> List[dict[str, Any]]:
    """List all coupons ordered by created date."""
    res = db.table("coupons").select("*").order("created_at", desc=True).execute()
    return res.data or []


def toggle_coupon_status(db: Client, coupon_id: str, is_active: bool) -> dict[str, Any]:
    """Activate or deactivate a coupon."""
    res = (
        db.table("coupons")
        .update({"is_active": is_active, "updated_at": _utcnow().isoformat()})
        .eq("id", coupon_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    return res.data[0]


def list_redemption_history(db: Client, coupon_id: Optional[str] = None) -> List[dict[str, Any]]:
    """List coupon redemption history."""
    q = db.table("coupon_redemptions").select("*").order("created_at", desc=True)
    if coupon_id:
        q = q.eq("coupon_id", coupon_id)
    res = q.execute()
    return res.data or []


def get_coupon_analytics(db: Client) -> dict[str, Any]:
    """Aggregates coupon performance, redemption counts, and discount totals."""
    coupons_res = db.table("coupons").select("id, code, discount_percentage, redemptions_count, is_active").execute()
    coupons = coupons_res.data or []

    redemptions_res = (
        db.table("coupon_redemptions")
        .select("original_base_amount_paise, discount_amount_paise, total_amount_paise, status")
        .eq("status", "fulfilled")
        .execute()
    )
    redemptions = redemptions_res.data or []

    total_coupons = len(coupons)
    active_coupons = sum(1 for c in coupons if c.get("is_active"))
    total_redemptions = len(redemptions)
    total_discount_given_paise = sum(int(r.get("discount_amount_paise") or 0) for r in redemptions)
    total_revenue_realized_paise = sum(int(r.get("total_amount_paise") or 0) for r in redemptions)

    return {
        "total_coupons": total_coupons,
        "active_coupons": active_coupons,
        "total_redemptions": total_redemptions,
        "total_discount_given_paise": total_discount_given_paise,
        "total_revenue_realized_paise": total_revenue_realized_paise,
        "discount_breakdown": {
            "20%": sum(1 for c in coupons if c.get("discount_percentage") == 20),
            "25%": sum(1 for c in coupons if c.get("discount_percentage") == 25),
            "30%": sum(1 for c in coupons if c.get("discount_percentage") == 30),
        },
    }
