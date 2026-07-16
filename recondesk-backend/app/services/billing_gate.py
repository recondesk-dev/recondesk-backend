"""Run access, free runs, GSTIN subscriptions, and legacy FIFO run credits."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client

from app.database import get_supabase, get_user_profile
from app.utils.audit import log_action

_log = logging.getLogger(__name__)


def _with_gst(base_paise: int) -> dict[str, int]:
    gst_paise = round(base_paise * 0.18)
    return {
        "base_paise": base_paise,
        "gst_paise": gst_paise,
        "total_paise": base_paise + gst_paise,
    }


# GSTIN-based plans. Paid subscription = unlimited runs until subscription_ends_at.
PLAN_CONFIG: dict[str, dict[str, int | str]] = {
    "starter": {
        **_with_gst(99_900),
        "gstin_limit": 25,
        "period_days": 30,
        "billing_period": "monthly",
    },
    "growth": {
        **_with_gst(799_900),
        "gstin_limit": 50,
        "period_days": 365,
        "billing_period": "yearly",
    },
    "pro": {
        **_with_gst(1_199_900),
        "gstin_limit": 75,
        "period_days": 365,
        "billing_period": "yearly",
    },
}

FREE_GSTIN_LIMIT = 2
BATCH_VALID_DAYS = 30  # legacy run-credit batches
FREE_RUNS_ALLOCATION = 2
_SUCCESSFUL_RUN_STATUSES = frozenset(
    {"COMPLETED", "FINAL", "COMPLETE", "FINALIZED"}
)


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


def _is_successful_run_status(status: Any) -> bool:
    return str(status or "").strip().upper() in _SUCCESSFUL_RUN_STATUSES


def _client_gstin_ids_for_firm(sb: Client, firm_owner_id: str) -> list[str]:
    res = (
        sb.table("client_gstins")
        .select("id")
        .eq("firm_owner_id", firm_owner_id)
        .execute()
    )
    return [str(row["id"]) for row in (res.data or []) if row.get("id")]


def count_successful_reconciliation_runs(sb: Client, firm_owner_id: str) -> int:
    """Count reconciliation runs with status COMPLETED or FINAL for the firm."""
    client_ids = _client_gstin_ids_for_firm(sb, firm_owner_id)
    if not client_ids:
        return 0
    total = 0
    status_values = ["COMPLETED", "FINAL", "complete", "final", "finalized"]
    for i in range(0, len(client_ids), 100):
        chunk = client_ids[i : i + 100]
        res = (
            sb.table("reconciliation_run")
            .select("id", count="exact")
            .in_("client_gstin_id", chunk)
            .in_("status", status_values)
            .limit(0)
            .execute()
        )
        total += int(res.count or 0)
    return total


def _decrement_oldest_credit_batch(sb: Client, firm_owner_id: str) -> bool:
    batches = (
        sb.table("run_credits")
        .select("id, runs_remaining, expires_at")
        .eq("firm_owner_id", firm_owner_id)
        .gt("runs_remaining", 0)
        .order("expires_at", desc=False)
        .execute()
    )
    now = _utcnow()
    for batch in batches.data or []:
        exp = _parse_ts(batch.get("expires_at"))
        if exp is None or exp <= now:
            continue
        cid = str(batch["id"])
        rem = int(batch.get("runs_remaining") or 0) - 1
        sb.table("run_credits").update({"runs_remaining": max(0, rem)}).eq("id", cid).execute()
        return True
    return False


def has_active_subscription(sb: Client, firm_owner_id: str) -> bool:
    """True when subscription_ends_at is in the future."""
    res = (
        sb.table("user_profiles")
        .select("subscription_ends_at")
        .eq("id", firm_owner_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return False
    ends = _parse_ts(res.data[0].get("subscription_ends_at"))
    return ends is not None and ends > _utcnow()


async def sync_billing_credits(firm_owner_id: str) -> dict[str, int]:
    """Backfill billing for completed runs and align free-run counters."""
    sb = get_supabase()
    forfeit_expired_credit_batches(sb, firm_owner_id)

    client_ids = _client_gstin_ids_for_firm(sb, firm_owner_id)
    orphans: list[dict[str, Any]] = []
    if client_ids:
        status_values = ["COMPLETED", "FINAL", "complete", "final", "finalized"]
        for i in range(0, len(client_ids), 100):
            chunk = client_ids[i : i + 100]
            res = (
                sb.table("reconciliation_run")
                .select("id, status, created_at, paid_at")
                .in_("client_gstin_id", chunk)
                .in_("status", status_values)
                .is_("paid_at", "null")
                .order("created_at", desc=False)
                .execute()
            )
            for row in res.data or []:
                if _is_successful_run_status(row.get("status")):
                    orphans.append(row)

    free_n = _profile_int(sb, firm_owner_id, "free_runs_remaining")
    balance = _profile_int(sb, firm_owner_id, "runs_balance")
    sub_active = has_active_subscription(sb, firm_owner_id)
    now = _utcnow().isoformat()
    credits_touched = False

    for orphan in orphans:
        rid = str(orphan["id"])
        if free_n > 0:
            free_n -= 1
        elif sub_active:
            pass  # subscription covers the run — no credit decrement
        elif balance > 0 and _decrement_oldest_credit_batch(sb, firm_owner_id):
            balance -= 1
            credits_touched = True
        sb.table("reconciliation_run").update({"paid_at": now}).eq("id", rid).execute()

    successful = count_successful_reconciliation_runs(sb, firm_owner_id)
    expected_free = max(
        0,
        FREE_RUNS_ALLOCATION - min(successful, FREE_RUNS_ALLOCATION),
    )
    free_n = min(free_n, expected_free)

    if orphans or free_n != _profile_int(sb, firm_owner_id, "free_runs_remaining"):
        sb.table("user_profiles").update({"free_runs_remaining": free_n}).eq(
            "id", firm_owner_id
        ).execute()

    if credits_touched:
        forfeit_expired_credit_batches(sb, firm_owner_id)
        balance = _profile_int(sb, firm_owner_id, "runs_balance")
    elif orphans:
        sb.table("user_profiles").update({"runs_balance": balance}).eq(
            "id", firm_owner_id
        ).execute()

    return {
        "free_runs_remaining": free_n,
        "runs_balance": balance,
        "successful_runs": successful,
    }


def count_active_gstins(sb: Client, firm_owner_id: str) -> int:
    res = (
        sb.table("client_gstins")
        .select("id", count="exact")
        .eq("firm_owner_id", firm_owner_id)
        .eq("is_active", True)
        .limit(0)
        .execute()
    )
    return int(res.count or 0)


def get_gstin_limit(sb: Client, firm_owner_id: str) -> int:
    res = (
        sb.table("user_profiles")
        .select("gstin_limit, plan, subscription_ends_at")
        .eq("id", firm_owner_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return FREE_GSTIN_LIMIT
    row = res.data[0]
    ends = _parse_ts(row.get("subscription_ends_at"))
    if ends is None or ends <= _utcnow():
        # Expired / unpaid: enforce free cap even if stale gstin_limit remains.
        return FREE_GSTIN_LIMIT
    return max(int(row.get("gstin_limit") or FREE_GSTIN_LIMIT), FREE_GSTIN_LIMIT)


def assert_gstin_capacity(sb: Client, firm_owner_id: str) -> dict[str, int]:
    """Raise ValueError when firm is at GSTIN capacity."""
    used = count_active_gstins(sb, firm_owner_id)
    limit = get_gstin_limit(sb, firm_owner_id)
    if used >= limit:
        raise ValueError(
            f"GSTIN limit reached ({used}/{limit}). Upgrade your plan to add more clients."
        )
    return {"gstins_used": used, "gstin_limit": limit}


async def activate_subscription(
    user_id: str,
    plan: str,
    payment_id: str | None,
    *,
    log_ip: str | None = None,
) -> dict[str, Any]:
    """Activate or extend a GSTIN subscription for the firm owner."""
    if plan not in PLAN_CONFIG:
        raise ValueError("invalid plan")
    cfg = PLAN_CONFIG[plan]
    sb = get_supabase()
    period_days = int(cfg["period_days"])
    gstin_limit = int(cfg["gstin_limit"])

    prof = (
        sb.table("user_profiles")
        .select("subscription_ends_at, plan")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    now = _utcnow()
    base = now
    if prof.data:
        existing_end = _parse_ts(prof.data[0].get("subscription_ends_at"))
        if existing_end is not None and existing_end > now:
            base = existing_end

    ends_at = base + timedelta(days=period_days)
    ends_iso = ends_at.isoformat()

    sb.table("user_profiles").update(
        {
            "plan": plan,
            "gstin_limit": gstin_limit,
            "subscription_ends_at": ends_iso,
        }
    ).eq("id", user_id).execute()

    await log_action(
        user_id,
        "SUBSCRIPTION_ACTIVATED",
        "user_profile",
        payment_id or user_id,
        {
            "plan": plan,
            "gstin_limit": gstin_limit,
            "period_days": period_days,
            "subscription_ends_at": ends_iso,
            "payment_id": payment_id,
        },
        ip_address=log_ip,
    )
    return {
        "plan": plan,
        "gstin_limit": gstin_limit,
        "subscription_ends_at": ends_iso,
        "period_days": period_days,
    }


async def check_run_access(user_id: str) -> dict[str, Any]:
    """user_id = firm_owner_id for credits / subscription."""
    synced = await sync_billing_credits(user_id)
    free_n = synced["free_runs_remaining"]
    if free_n > 0:
        return {
            "allowed": True,
            "reason": "free",
            "free_runs_remaining": free_n,
        }

    sb = get_supabase()
    if has_active_subscription(sb, user_id):
        return {
            "allowed": True,
            "reason": "subscription",
        }

    balance = synced["runs_balance"]
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
    """Consume free run, subscription entitlement, or legacy credit batch."""
    sb = get_supabase()
    forfeit_expired_credit_batches(sb, user_id)

    prof = (
        sb.table("user_profiles")
        .select("free_runs_remaining, runs_balance, subscription_ends_at")
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

    ends = _parse_ts(row0.get("subscription_ends_at"))
    if ends is not None and ends > _utcnow():
        await log_action(
            user_id,
            "SUBSCRIPTION_RUN_USED",
            "user_profile",
            user_id,
            {"subscription_ends_at": ends.isoformat()},
        )
        return {"consumed": "subscription"}

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
    """Legacy helper kept for old packs; new purchases should use activate_subscription."""
    if plan not in PLAN_CONFIG:
        raise ValueError("invalid plan")
    # New model does not sell run packs — activate subscription instead.
    return await activate_subscription(
        user_id, plan, payment_id, log_ip=log_ip
    )
