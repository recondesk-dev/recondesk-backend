"""Periodic Rule 37 pre-deadline / overdue email alerts.

Scans latest completed purchase runs **per tax period** per client (wall-clock
``date.today()``), respects ``notification_preferences.rule37_alerts``, and
dedups via ``rule37_alert_dedup`` so the same invoice+tier is not re-mailed
every cycle.

When the newest completed run for a period has no ``pr_records`` (thin re-run),
falls back to an older completed run for that same period — same class of fix
as the GSTR-9C FY rollup claimed-ITC period fallback.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from supabase import Client

from app.database import get_supabase, get_user_profile
from app.services.gstr9c_itc_fy_rollup import normalize_period_yyyy_mm
from app.services.rule37_tracker import (
    OVERDUE_UNPAID,
    WARNING_30_DAYS,
    WARNING_60_DAYS,
    _is_itc_claimed,
    build_payment_records_from_pr,
    check_rule_37_compliance,
)
from app.utils.email import send_rule37_alert_email
from app.utils.notification_prefs import should_send_notification

_log = logging.getLogger(__name__)

ALERT_TIERS = frozenset({WARNING_60_DAYS, WARNING_30_DAYS, OVERDUE_UNPAID})

# Tier rank for escalation (higher = more urgent).
_TIER_RANK = {
    WARNING_60_DAYS: 1,
    WARNING_30_DAYS: 2,
    OVERDUE_UNPAID: 3,
}

# Re-send same tier only after this cooldown.
_SAME_TIER_COOLDOWN = timedelta(days=7)

# Do not run a full scan more often than this (stuck_job loop is every 5 min).
_SCAN_MIN_INTERVAL = timedelta(hours=6)

_COMPLETED_STATUSES = ("COMPLETED", "COMPLETE", "FINALIZED")

_last_scan_at: datetime | None = None


def _invoice_key(row: dict[str, Any]) -> str:
    gst = str(row.get("supplier_gstin") or "").strip().upper()
    inv = str(row.get("invoice_number") or "").strip().upper()
    idt = str(row.get("invoice_date") or "").strip()[:10]
    return f"{gst}|{inv}|{idt}"


def _should_send_for_dedup(
    prior: dict[str, Any] | None,
    tier: str,
    *,
    now: datetime,
) -> bool:
    if prior is None:
        return True
    prev_tier = str(prior.get("last_alert_tier") or "")
    if _TIER_RANK.get(tier, 0) > _TIER_RANK.get(prev_tier, 0):
        return True  # escalated
    if prev_tier != tier:
        # Downgrade / different non-escalation — still allow after cooldown
        pass
    sent_raw = prior.get("last_sent_at")
    if not sent_raw:
        return True
    try:
        sent = datetime.fromisoformat(str(sent_raw).replace("Z", "+00:00"))
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return (now - sent) >= _SAME_TIER_COOLDOWN


def select_alert_run_ids_by_period(
    runs: list[dict[str, Any]],
    *,
    has_pr_records: Callable[[str], bool],
) -> list[str]:
    """Pick one completed run_id per tax period for Rule 37 alert scanning.

    *runs* must already be completed-status rows. Within each period, prefer the
    newest run that has ``pr_records``; if the newest is empty (thin re-run),
    fall back to older completed runs for that same period. Periods with no
    PR-bearing run are skipped.

    Returns run_ids ordered by period descending (newest period first) so
    within-scan invoice-key collisions prefer the newer period.
    """
    by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in runs:
        rid = str(row.get("id") or "").strip()
        if not rid:
            continue
        period = normalize_period_yyyy_mm(row.get("period")) or "_none_"
        by_period[period].append(row)

    for period_rows in by_period.values():
        period_rows.sort(
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )

    selected: list[tuple[str, str]] = []  # (period, run_id)
    for period, period_rows in by_period.items():
        chosen: str | None = None
        for row in period_rows:
            rid = str(row.get("id") or "").strip()
            if not rid:
                continue
            if has_pr_records(rid):
                chosen = rid
                break
        if chosen:
            selected.append((period, chosen))

    selected.sort(key=lambda t: t[0], reverse=True)
    return [rid for _period, rid in selected]


def _load_completed_runs_for_client(
    sb: Client, client_gstin_id: str
) -> list[dict[str, Any]]:
    """All completed purchase runs for a client (newest first, capped)."""
    res = (
        sb.table("reconciliation_run")
        .select("id, period, status, created_at")
        .eq("client_gstin_id", client_gstin_id)
        .in_("status", list(_COMPLETED_STATUSES))
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    return list(res.data or [])


def _run_has_pr_records(sb: Client, run_id: str) -> bool:
    """True when at least one ``pr_records`` row exists for *run_id*."""
    res = (
        sb.table("pr_records")
        .select("id")
        .eq("run_id", run_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def _load_pr_bundle(sb: Client, run_id: str) -> tuple[list[dict], dict[str, dict]]:
    """Return (matcher-shaped PR rows, raw record_data by id) for a run."""
    page_size = 1000
    offset = 0
    matcher_rows: list[dict] = []
    raw_by_id: dict[str, dict] = {}
    while True:
        res = (
            sb.table("pr_records")
            .select("id, record_data")
            .eq("run_id", run_id)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        chunk = res.data or []
        if not chunk:
            break
        for row in chunk:
            rid = str(row.get("id") or "")
            if not rid:
                continue
            raw = row.get("record_data") if isinstance(row.get("record_data"), dict) else {}
            raw_by_id[rid] = raw
            matcher_rows.append(
                {
                    "id": rid,
                    "supplier_gstin": raw.get("supplier_gstin")
                    or raw.get("supplier_gstin_norm")
                    or "",
                    "invoice_number_normalized": raw.get("invoice_number_normalized")
                    or raw.get("invoice_number")
                    or "",
                    "invoice_date": raw.get("invoice_date") or raw.get("invoice_date_norm"),
                    "taxable_amount_paise": raw.get("taxable_amount_paise") or 0,
                    "total_tax_paise": raw.get("total_tax_paise") or 0,
                    "invoice_value_paise": raw.get("invoice_value_paise") or 0,
                    "igst_paise": raw.get("igst_paise"),
                    "cgst_paise": raw.get("cgst_paise"),
                    "sgst_paise": raw.get("sgst_paise"),
                }
            )
        if len(chunk) < page_size:
            break
        offset += page_size
    return matcher_rows, raw_by_id


def _build_pr_for_rule37(
    matcher_rows: list[dict],
    raw_by_id: dict[str, dict],
) -> list[dict]:
    out: list[dict] = []
    for p in matcher_rows:
        pr_id = str(p.get("id") or "")
        raw = raw_by_id.get(pr_id) or {}
        if not _is_itc_claimed(raw):
            continue
        status_str = raw.get("payment_status")
        if isinstance(status_str, str):
            status_str = status_str.strip().lower()
        else:
            status_str = None
        if status_str is not None and status_str not in (
            "unpaid",
            "partially paid",
            "partial",
        ):
            continue
        inv_date = p.get("invoice_date")
        if not inv_date:
            continue
        out.append(
            {
                **p,
                "id": pr_id,
                "invoice_date": str(inv_date)[:10],
                "payment_status": status_str,
                "payment_date": raw.get("payment_date"),
                "itc_claimed": True,
            }
        )
    return out


def _upsert_dedup(
    sb: Client,
    *,
    firm_owner_id: str,
    client_gstin_id: str,
    invoice_key: str,
    tier: str,
    now: datetime,
) -> None:
    payload = {
        "firm_owner_id": firm_owner_id,
        "client_gstin_id": client_gstin_id,
        "invoice_key": invoice_key,
        "last_alert_tier": tier,
        "last_sent_at": now.isoformat(),
    }
    sb.table("rule37_alert_dedup").upsert(
        payload, on_conflict="client_gstin_id,invoice_key"
    ).execute()


def _load_dedup_map(sb: Client, client_gstin_id: str) -> dict[str, dict[str, Any]]:
    res = (
        sb.table("rule37_alert_dedup")
        .select("invoice_key, last_alert_tier, last_sent_at")
        .eq("client_gstin_id", client_gstin_id)
        .execute()
    )
    out: dict[str, dict[str, Any]] = {}
    for row in res.data or []:
        key = str(row.get("invoice_key") or "")
        if key:
            out[key] = row
    return out


async def run_rule37_alert_scan(
    *,
    sb: Client | None = None,
    today: date | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Scan clients for Rule 37 warning/overdue invoices and email firm owners.

    Throttled to once per ``_SCAN_MIN_INTERVAL`` unless ``force=True``.
    Returns a small stats dict for logging/tests.
    """
    global _last_scan_at
    now = datetime.now(timezone.utc)
    if not force and _last_scan_at is not None:
        if now - _last_scan_at < _SCAN_MIN_INTERVAL:
            return {"skipped": True, "reason": "throttled"}

    client = sb if sb is not None else get_supabase()
    eval_day = today or date.today()
    stats = {
        "skipped": False,
        "clients_scanned": 0,
        "invoices_flagged": 0,
        "emails_sent": 0,
        "emails_skipped_prefs": 0,
        "emails_skipped_dedup": 0,
    }

    try:
        clients_res = (
            client.table("client_gstins")
            .select("id, firm_owner_id, trade_name, legal_name, gstin")
            .eq("is_active", True)
            .limit(2000)
            .execute()
        )
    except Exception:
        _log.exception("rule37_alert_scan: failed to list clients")
        raise

    clients = clients_res.data or []
    # Group invoices to email: (firm_owner_id, client_id) -> list
    pending_emails: dict[tuple[str, str], dict[str, Any]] = {}

    for cg in clients:
        client_id = str(cg.get("id") or "").strip()
        firm_owner_id = str(cg.get("firm_owner_id") or "").strip()
        if not client_id or not firm_owner_id:
            continue

        try:
            completed_runs = _load_completed_runs_for_client(client, client_id)
            run_ids = select_alert_run_ids_by_period(
                completed_runs,
                has_pr_records=lambda rid: _run_has_pr_records(client, rid),
            )
        except Exception:
            _log.exception(
                "rule37_alert_scan: client=%s run selection failed", client_id
            )
            continue

        if not run_ids:
            continue

        stats["clients_scanned"] += 1
        try:
            dedup_map = _load_dedup_map(client, client_id)
            client_name = (
                str(cg.get("trade_name") or cg.get("legal_name") or cg.get("gstin") or "")
                .strip()
                or "Client"
            )
            # invoice_key -> best row when the same invoice appears across periods
            seen_keys: dict[str, dict[str, Any]] = {}

            for run_id in run_ids:
                matcher_rows, raw_by_id = _load_pr_bundle(client, run_id)
                if not matcher_rows:
                    continue
                pr_for_r37 = _build_pr_for_rule37(matcher_rows, raw_by_id)
                payments = build_payment_records_from_pr(matcher_rows, raw_by_id)
                flagged = check_rule_37_compliance(
                    pr_for_r37, payments, today=eval_day
                )
                for row in flagged:
                    if str(row.get("status") or "") not in ALERT_TIERS:
                        continue
                    key = _invoice_key(row)
                    if not key or key.startswith("||"):
                        continue
                    # Prefer first occurrence (newer period — run_ids are period-desc).
                    if key not in seen_keys:
                        seen_keys[key] = row

            if not seen_keys:
                continue

            for key, row in seen_keys.items():
                stats["invoices_flagged"] += 1
                tier = str(row.get("status") or "")
                prior = dedup_map.get(key)
                if not _should_send_for_dedup(prior, tier, now=now):
                    stats["emails_skipped_dedup"] += 1
                    continue

                bucket_key = (firm_owner_id, client_id)
                bucket = pending_emails.get(bucket_key)
                if bucket is None:
                    bucket = {
                        "firm_owner_id": firm_owner_id,
                        "client_gstin_id": client_id,
                        "client_name": client_name,
                        "invoices": [],
                        "dedup_keys": [],
                    }
                    pending_emails[bucket_key] = bucket
                amount = int(
                    row.get("potential_itc_paise")
                    or row.get("itc_at_risk_paise")
                    or 0
                )
                bucket["invoices"].append(
                    {
                        "supplier_gstin": row.get("supplier_gstin") or "",
                        "invoice_number": row.get("invoice_number") or "",
                        "amount_paise": amount,
                        "deadline_date": row.get("deadline") or "",
                        "status": tier,
                        "days_remaining": row.get("days_remaining"),
                        "decision_rule": row.get("decision_rule") or "ITC_014",
                    }
                )
                bucket["dedup_keys"].append((key, tier))
        except Exception:
            _log.exception(
                "rule37_alert_scan: client=%s run scan failed", client_id
            )
            continue

    # Send one email per (owner, client) with invoices that passed dedup.
    for (_owner, _cid), bucket in pending_emails.items():
        firm_owner_id = bucket["firm_owner_id"]
        if not should_send_notification(firm_owner_id, "rule37_alerts"):
            stats["emails_skipped_prefs"] += 1
            continue

        profile = get_user_profile(firm_owner_id) or {}
        to_email = str(profile.get("email") or "").strip()
        if not to_email:
            _log.warning(
                "rule37_alert_scan: no email for firm_owner=%s", firm_owner_id
            )
            continue

        full_name = str(profile.get("full_name") or "").strip()
        invoices = bucket["invoices"]
        if not invoices:
            continue

        try:
            ok = await send_rule37_alert_email(
                to_email,
                full_name,
                bucket["client_name"],
                invoices,
            )
        except Exception:
            _log.exception(
                "rule37_alert_scan: send failed owner=%s client=%s",
                firm_owner_id,
                bucket["client_gstin_id"],
            )
            continue

        if not ok:
            continue

        stats["emails_sent"] += 1
        for key, tier in bucket["dedup_keys"]:
            try:
                _upsert_dedup(
                    client,
                    firm_owner_id=firm_owner_id,
                    client_gstin_id=bucket["client_gstin_id"],
                    invoice_key=key,
                    tier=tier,
                    now=now,
                )
            except Exception:
                _log.exception(
                    "rule37_alert_scan: dedup upsert failed key=%s", key
                )

    _last_scan_at = now
    _log.info("rule37_alert_scan complete: %s", stats)
    return stats


def reset_scan_throttle_for_tests() -> None:
    """Clear the in-process throttle (unit tests only)."""
    global _last_scan_at
    _last_scan_at = None
