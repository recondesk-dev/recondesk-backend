"""Run access, free runs, and FIFO purchased credits (6-month expiry per batch)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client

from app.database import get_supabase, get_user_profile
from app.utils.audit import log_action

_log = logging.getLogger(__name__)

PLAN_CONFIG: dict[str, dict[str, int]] = {
    "starter": {
        "base_paise": 29_900,
        "runs": 1,
        "gst_paise": 5_382,
        "total_paise": 35_282,
    },
    "growth": {
        "base_paise": 119_900,
        "runs": 5,
        "gst_paise": 21_582,
        "total_paise": 141_482,
    },
    "pro": {
        "base_paise": 269_900,
        "runs": 12,
        "gst_paise": 48_582,
        "total_paise": 318_482,
    },
}

BATCH_VALID_DAYS = 183  # ~6 months


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        # ISO from Supabase
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def resolve_firm_owner_for_billing(sb: Client, current_user: dict) -> str:
    """CA principal user_profiles.id for billing credits (owner or staff firm)."""
    uid = str(current_user.get("id", "")).strip()
    profile = get_user_profile(uid) or {}
    role = (profile.get("role") or "staff").strip().lower()
    if role == "admin":
        return uid
    r = (
        sb.table("client_gstins")
        .select("firm_owner_id")
        .eq("assigned_to", uid)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if r.data:
        return str(r.data[0].get("firm_owner_id", "")).strip()
    return uid


def forfeit_expired_credit_batches(sb: Client, firm_owner_id: str) -> None:
    """Zero remaining runs on expired batches and realign runs_balance."""
    now = _utcnow()
    res = (
        sb.table("run_credits")
        .select("id, runs_remaining, expires_at")
        .eq("firm_owner_id", firm_owner_id)
        .gt("runs_remaining", 0)
        .execute()
    )
    for row in res.data or []:
        exp = _parse_ts(row.get("expires_at"))
        if exp is None or exp > now:
            continue
        rid = str(row.get("id", "")).strip()
        if not rid:
            continue
        try:
            sb.table("run_credits").update({"runs_remaining": 0}).eq("id", rid).execute()
        except Exception as exc:  # noqa: BLE001
            _log.warning("forfeit batch %s: %s", rid, exc)

    active = (
        sb.table("run_credits")
        .select("runs_remaining, expires_at")
        .eq("firm_owner_id", firm_owner_id)
        .gt("runs_remaining", 0)
        .execute()
    )
    total = 0
    for row in active.data or []:
        exp = _parse_ts(row.get("expires_at"))
        if exp is None or exp <= now:
            continue
        total += int(row.get("runs_remaining") or 0)
    try:
        sb.table("user_profiles").update({"runs_balance": total}).eq("id", firm_owner_id).execute()
    except Exception as exc:  # noqa: BLE001
        _log.warning("runs_balance sync: %s", exc)


def _profile_int(sb: Client, firm_owner_id: str, key: str) -> int:
    res = (
        sb.table("user_profiles")
        .select(key)
        .eq("id", firm_owner_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return 0
    return int(res.data[0].get(key) or 0)


async def check_run_access(user_id: str) -> dict[str, Any]:
    """user_id = firm_owner_id for credits."""
    sb = get_supabase()
    forfeit_expired_credit_batches(sb, user_id)

    free_n = _profile_int(sb, user_id, "free_runs_remaining")
    if free_n > 0:
        return {
            "allowed": True,
            "reason": "free",
            "free_runs_remaining": free_n,
        }

    balance = _profile_int(sb, user_id, "runs_balance")
    if balance > 0:
        return {
            "allowed": True,
            "reason": "credits",
            "runs_balance": balance,
        }

    return {
        "allowed": False,
        "reason": "payment_required",
        "suggested_plan": "growth",
    }


async def consume_run_credit(user_id: str) -> dict[str, Any]:
    """Decrement one free run or oldest-expiring credit batch (FIFO). user_id = firm_owner."""
    sb = get_supabase()
    forfeit_expired_credit_batches(sb, user_id)

    prof = (
        sb.table("user_profiles")
        .select("free_runs_remaining, runs_balance")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not prof.data:
        raise RuntimeError("user profile missing for billing")
    row0 = prof.data[0]
    free_n = int(row0.get("free_runs_remaining") or 0)
    balance = int(row0.get("runs_balance") or 0)

    if free_n > 0:
        new_free = free_n - 1
        sb.table("user_profiles").update({"free_runs_remaining": new_free}).eq(
            "id", user_id
        ).execute()
        await log_action(
            user_id,
            "FREE_RUN_USED",
            "user_profile",
            user_id,
            {"free_runs_remaining_after": new_free},
        )
        return {"consumed": "free"}

    if balance <= 0:
        raise RuntimeError("no credits available")

    batches = (
        sb.table("run_credits")
        .select("id, runs_remaining, expires_at")
        .eq("firm_owner_id", user_id)
        .gt("runs_remaining", 0)
        .order("expires_at", desc=False)
        .execute()
    )
    now = _utcnow()
    chosen: dict[str, Any] | None = None
    for b in batches.data or []:
        exp = _parse_ts(b.get("expires_at"))
        if exp is None or exp <= now:
            continue
        chosen = b
        break
    if not chosen:
        raise RuntimeError("no valid credit batch")

    cid = str(chosen["id"])
    rem = int(chosen.get("runs_remaining") or 0) - 1
    sb.table("run_credits").update({"runs_remaining": max(0, rem)}).eq("id", cid).execute()
    new_bal = max(0, balance - 1)
    sb.table("user_profiles").update({"runs_balance": new_bal}).eq("id", user_id).execute()
    await log_action(
        user_id,
        "CREDIT_RUN_USED",
        "run_credit",
        cid,
        {"credit_batch_id": cid, "runs_remaining_after": rem, "runs_balance_after": new_bal},
    )
    return {"consumed": "credit", "credit_id": cid}


async def add_run_credits(
    user_id: str, plan: str, payment_id: str | None, *, log_ip: str | None = None
) -> dict[str, Any]:
    if plan not in PLAN_CONFIG:
        raise ValueError("invalid plan")
    cfg = PLAN_CONFIG[plan]
    sb = get_supabase()
    expires_at = _utcnow() + timedelta(days=BATCH_VALID_DAYS)
    expires_iso = expires_at.isoformat()

    ins = {
        "firm_owner_id": user_id,
        "payment_id": payment_id,
        "plan": plan,
        "runs_purchased": cfg["runs"],
        "runs_remaining": cfg["runs"],
        "expires_at": expires_iso,
    }
    ins_res = sb.table("run_credits").insert(ins).execute()
    credit_row = (ins_res.data or [{}])[0]
    credit_id = str(credit_row.get("id", ""))

    bal = _profile_int(sb, user_id, "runs_balance")
    new_bal = bal + cfg["runs"]
    sb.table("user_profiles").update({"runs_balance": new_bal}).eq("id", user_id).execute()

    await log_action(
        user_id,
        "CREDITS_ADDED",
        "run_credit",
        credit_id or payment_id,
        {
            "plan": plan,
            "runs": cfg["runs"],
            "expires_at": expires_iso,
            "payment_id": payment_id,
        },
        ip_address=log_ip,
    )
    return {"runs_added": cfg["runs"], "runs_balance": new_bal, "credit_id": credit_id}
