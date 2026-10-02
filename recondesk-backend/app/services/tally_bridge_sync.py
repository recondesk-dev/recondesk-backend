"""Match Tally Payment Agst Ref lines to open Rule 37 invoices and settle.

Outstandings (Bills Payable) are unpaid truth only — never a settle trigger.
Auto-settle requires both a confident bill-ref match and a hard party-name gate.
"""

from __future__ import annotations

import logging
import secrets
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Optional

from supabase import Client

from app.services.matcher import (
    invoice_similarity,
    invoices_effectively_match,
    is_invoice_format_variant,
    normalize_invoice,
)
from app.services.rule37_alert_scan import (
    _build_pr_for_rule37,
    _load_completed_runs_for_client,
    _load_pr_bundle,
    _run_has_pr_records,
    select_alert_run_ids_by_period,
)
from app.services.rule37_tracker import check_rule_37_compliance
from app.services.vendor_name_matcher import vendor_name_similarity

_log = logging.getLogger(__name__)

# Auto-settle only on strong invoice identity — stricter than L5 review floor.
_CONFIDENT_SIM_MIN = 0.85
# Hard party-name gate for auto-settle (not a soft score boost).
_PARTY_AUTO_SETTLE_MIN = 0.82
# Require a clear winner when multiple candidates score above the floor.
_UNIQUE_GAP_MIN = 0.05
# Wider uniqueness gap when party is missing/unclear (cheap anti-collision).
_UNIQUE_GAP_UNCLEAR_PARTY = 0.15
# Outstanding pending above this keeps coverage partial.
_OUTSTANDING_PENDING_EPS = 0.01

API_KEY_PREFIX = "rdb_"


def generate_tally_bridge_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def score_bill_ref_against_invoice(bill_ref: str, invoice_number: str) -> float:
    """Reuse GSTR↔PR invoice identity helpers. Party is gated separately."""
    if not bill_ref or not invoice_number:
        return 0.0

    if invoices_effectively_match(bill_ref, invoice_number):
        return 1.0
    if is_invoice_format_variant(bill_ref, invoice_number, bill_ref, invoice_number):
        return 0.95
    return float(invoice_similarity(bill_ref, invoice_number))


def party_similarity(party: str, supplier_name: str) -> float:
    return float(vendor_name_similarity(party or "", supplier_name or ""))


def party_clears_autosettle_gate(
    party: str,
    supplier_name: str,
    *,
    tally_gstin: str = "",
    supplier_gstin: str = "",
) -> tuple[bool, float]:
    """Hard gate: clears if GSTINs match exactly, OR if names clear _PARTY_AUTO_SETTLE_MIN."""
    p = (party or "").strip()
    s = (supplier_name or "").strip()
    tgst = (tally_gstin or "").strip().upper()
    sgst = (supplier_gstin or "").strip().upper()

    if tgst and sgst and tgst == sgst:
        return True, 1.0

    if not p or not s:
        return False, 0.0
    sim = party_similarity(p, s)
    return sim >= _PARTY_AUTO_SETTLE_MIN, sim


def _load_tally_ledger_gstin_map(sb: Client, account_id: str) -> dict[str, str]:
    try:
        res = (
            sb.table("tally_ledger_masters")
            .select("name, gstin")
            .eq("account_id", account_id)
            .execute()
        )
        return {
            str(r["name"]).strip(): str(r.get("gstin") or "").strip().upper()
            for r in (res.data or [])
            if r.get("name")
        }
    except Exception:
        return {}


def is_confident_bill_match(
    score: float,
    second_best: float = 0.0,
    *,
    unique_gap: float = _UNIQUE_GAP_MIN,
) -> bool:
    if score < _CONFIDENT_SIM_MIN:
        return False
    gap = max(float(unique_gap), 0.0)
    if second_best > 0 and (score - second_best) < gap and score < 0.999:
        return False
    return True


def _paise_to_rupees(paise: int) -> float:
    return round(int(paise or 0) / 100.0, 2)


def _get_compliance_repo():
    """Return Aurora compliance repo or None."""
    try:
        from app.repositories.compliance import get_compliance_repository
        return get_compliance_repository()
    except Exception:
        return None


def _actions_resolved_hashes(sb: Client, run_id: str) -> set[str]:
    """Return resolved rule37_action record_hashes for a run.

    Aurora is PRIMARY; Supabase is fallback.
    """
    rows: list[dict] = []
    repo = _get_compliance_repo()
    if repo is not None:
        try:
            rows = repo.get_rule37_actions_for_run(run_id)
        except Exception:
            rows = []

    if not rows:
        try:
            res = (
                sb.table("rule37_actions")
                .select("record_hash, status")
                .eq("run_id", run_id)
                .execute()
            )
            rows = list(res.data or [])
        except Exception:
            _log.exception("tally_bridge: failed reading rule37_actions run_id=%s", run_id)
            return set()

    out: set[str] = set()
    for row in rows:
        if str(row.get("status") or "").strip().lower() == "resolved":
            h = str(row.get("record_hash") or "").strip()
            if h:
                out.add(h)
    return out


def load_open_rule37_for_account(sb: Client, account_id: str) -> list[dict[str, Any]]:
    """Open Rule 37 invoices for a firm (account_id = firm owner user_profiles.id)."""
    clients_res = (
        sb.table("client_gstins")
        .select("id, firm_owner_id, trade_name, legal_name, gstin")
        .eq("firm_owner_id", account_id)
        .eq("is_active", True)
        .limit(2000)
        .execute()
    )
    open_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for cg in clients_res.data or []:
        client_id = str(cg.get("id") or "").strip()
        if not client_id:
            continue
        try:
            completed = _load_completed_runs_for_client(sb, client_id)
            run_ids = select_alert_run_ids_by_period(
                completed,
                has_pr_records=lambda rid: _run_has_pr_records(sb, rid),
            )
        except Exception:
            _log.exception(
                "tally_bridge: run selection failed client=%s", client_id
            )
            continue

        for run_id in run_ids:
            try:
                matcher_rows, raw_by_id = _load_pr_bundle(sb, run_id)
                pr_for_r37 = _build_pr_for_rule37(matcher_rows, raw_by_id)
                if not pr_for_r37:
                    continue
                results = check_rule_37_compliance(pr_for_r37, [])
                resolved = _actions_resolved_hashes(sb, run_id)
            except Exception:
                _log.exception(
                    "tally_bridge: rule37 build failed run_id=%s", run_id
                )
                continue

            for item in results:
                pr_id = str(item.get("pr_id") or "").strip()
                if not pr_id or pr_id in resolved:
                    continue
                inv = str(item.get("invoice_number") or "").strip()
                gst = str(item.get("supplier_gstin") or "").strip().upper()
                idt = str(item.get("invoice_date") or "").strip()[:10]
                dedupe = f"{gst}|{normalize_invoice(inv)}|{idt}"
                if dedupe in seen_keys:
                    continue
                seen_keys.add(dedupe)

                raw = raw_by_id.get(pr_id) or {}
                supplier_name = str(
                    raw.get("supplier_name")
                    or raw.get("vendor_name")
                    or raw.get("party_name")
                    or ""
                ).strip()
                invoice_amount = _paise_to_rupees(
                    int(item.get("total_invoice_value_paise") or 0)
                )
                open_rows.append(
                    {
                        "run_id": run_id,
                        "record_id": f"r37:{pr_id}",
                        "pr_id": pr_id,
                        "invoice_number": inv,
                        "invoice_date": idt,
                        "supplier_gstin": gst,
                        "supplier_name": supplier_name,
                        "invoice_amount": invoice_amount,
                        "client_gstin_id": client_id,
                    }
                )
    return open_rows


def find_best_open_match(
    bill_ref: str,
    open_rows: list[dict[str, Any]],
) -> tuple[Optional[dict[str, Any]], float, float]:
    """Return (best_row, best_score, second_best_score) on bill-ref identity only."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in open_rows:
        score = score_bill_ref_against_invoice(
            bill_ref,
            str(row.get("invoice_number") or ""),
        )
        if score > 0:
            scored.append((score, row))
    if not scored:
        return None, 0.0, 0.0
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_row = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    return best_row, best_score, second


def _parse_settled_date(raw: object) -> Optional[str]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw.isoformat()
    s = str(raw).strip()
    if not s:
        return None
    if len(s) >= 10 and s[4] == "-":
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except ValueError:
            return None
    return None


def _parse_positive_amount(raw: object) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        val = round(abs(float(raw)), 2)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    return val


def _index_outstanding_pending(
    outstanding: list[dict[str, Any]],
) -> dict[str, float]:
    """Map bill_ref → remaining-due amount (pending). Never treated as amount paid."""
    pending: dict[str, float] = {}
    for rec in outstanding:
        if not isinstance(rec, dict):
            continue
        bill_ref = str(rec.get("bill_ref") or "").strip()
        if not bill_ref:
            continue
        amt = _parse_positive_amount(rec.get("amount"))
        if amt is None:
            continue
        # Keep the larger pending if duplicates appear.
        prev = pending.get(bill_ref)
        pending[bill_ref] = amt if prev is None else max(prev, amt)
    return pending


def _aggregate_payments(
    payments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse Agst Ref lines sharing (party, bill_ref) into one settle candidate."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in payments:
        if not isinstance(rec, dict):
            continue
        bill_ref = str(rec.get("bill_ref") or "").strip()
        if not bill_ref:
            continue
        party = str(rec.get("party") or "").strip()
        groups[(party, bill_ref)].append(rec)

    aggregated: list[dict[str, Any]] = []
    for (party, bill_ref), lines in groups.items():
        paid = 0.0
        dates: list[str] = []
        voucher_numbers: list[str] = []
        for line in lines:
            amt = _parse_positive_amount(line.get("amount"))
            if amt is not None:
                paid += amt
            d = _parse_settled_date(line.get("payment_date") or line.get("bill_date"))
            if d:
                dates.append(d)
            vn = str(line.get("voucher_number") or "").strip()
            if vn:
                voucher_numbers.append(vn)
        aggregated.append(
            {
                "party": party,
                "bill_ref": bill_ref,
                "amount_paid": round(paid, 2) if paid > 0 else None,
                "payment_date": max(dates) if dates else None,
                "voucher_numbers": voucher_numbers,
                "line_count": len(lines),
            }
        )
    return aggregated


def _sync_tally_ledgers(
    sb: Client,
    account_id: str,
    company_name: str,
    ledgers: list[dict[str, Any]],
) -> int:
    if not ledgers:
        return 0
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = []
    for leg in ledgers:
        if not isinstance(leg, dict):
            continue
        name = str(leg.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "account_id": account_id,
                "company_name": company_name,
                "name": name,
                "parent_group": str(leg.get("parent_group") or ""),
                "gstin": str(leg.get("gstin") or "").strip().upper(),
                "state": str(leg.get("state") or ""),
                "opening_balance": leg.get("opening_balance"),
                "closing_balance": leg.get("closing_balance"),
                "synced_at": now_iso,
            }
        )
    if not rows:
        return 0
    try:
        sb.table("tally_ledger_masters").upsert(
            rows, on_conflict="account_id,company_name,name"
        ).execute()
        return len(rows)
    except Exception:
        _log.warning(
            "tally_bridge: failed upserting tally_ledger_masters for account_id=%s",
            account_id,
            exc_info=True,
        )
        return 0


def apply_tally_bridge_sync(
    sb: Client,
    *,
    account_id: str,
    outstanding: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    ledgers: list[dict[str, Any]] | None = None,
    company_name: str = "",
    key_id: str | None = None,
) -> dict[str, Any]:
    """Apply Tally Bridge sync: payments settle; outstandings mark still unpaid.

    Party-name gate is enforced immediately before ``_upsert_rule37_action`` —
    confident bill-ref alone never settles.
    """
    # Local import avoids circular import at module load (router ↔ reconciliation_api).
    from app.routers.reconciliation_api import (
        _rule37_payment_coverage,
        _upsert_rule37_action,
    )

    open_rows = load_open_rule37_for_account(sb, account_id)
    outstanding_pending = _index_outstanding_pending(outstanding)
    payment_groups = _aggregate_payments(payments)
    ledgers_synced = _sync_tally_ledgers(sb, account_id, company_name, ledgers or [])
    tally_gstin_map = _load_tally_ledger_gstin_map(sb, account_id)

    settled: list[dict[str, Any]] = []
    still_outstanding: list[dict[str, Any]] = []
    needs_manual_confirmation: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    claimed: set[str] = set()

    # --- Payments: only settle path ---
    for group in payment_groups:
        bill_ref = str(group["bill_ref"])
        party = str(group.get("party") or "")
        amount_paid = group.get("amount_paid")
        if amount_paid is None:
            skipped.append(
                {
                    "reason": "missing_or_non_positive_payment_amount",
                    "bill_ref": bill_ref,
                    "party": party,
                }
            )
            continue

        best, score, second = find_best_open_match(bill_ref, open_rows)
        if best is None:
            skipped.append(
                {
                    "reason": "weak_or_no_match",
                    "bill_ref": bill_ref,
                    "party": party,
                    "best_score": 0.0,
                    "second_best": 0.0,
                }
            )
            continue

        supplier_name = str(best.get("supplier_name") or "")
        supplier_gstin = str(best.get("supplier_gstin") or "")
        tally_gstin = tally_gstin_map.get(party, "")

        party_ok, party_sim = party_clears_autosettle_gate(
            party,
            supplier_name,
            tally_gstin=tally_gstin,
            supplier_gstin=supplier_gstin,
        )
        unique_gap = (
            _UNIQUE_GAP_MIN if party_ok else _UNIQUE_GAP_UNCLEAR_PARTY
        )

        if not is_confident_bill_match(score, second, unique_gap=unique_gap):
            skipped.append(
                {
                    "reason": "weak_or_no_match",
                    "bill_ref": bill_ref,
                    "party": party,
                    "best_score": round(score, 4),
                    "second_best": round(second, 4),
                    "party_sim": round(party_sim, 4),
                    "unique_gap_required": unique_gap,
                }
            )
            continue

        record_id = str(best["record_id"])
        if record_id in claimed:
            skipped.append(
                {
                    "reason": "already_settled_this_sync",
                    "bill_ref": bill_ref,
                    "record_id": record_id,
                }
            )
            continue

        # Hard party gate at the settle call site — do not upsert without it.
        if not party_ok:
            item = {
                "reason": "party_confidence_below_gate",
                "bill_ref": bill_ref,
                "party": party,
                "supplier_name": supplier_name,
                "invoice_number": best.get("invoice_number"),
                "record_id": record_id,
                "run_id": best.get("run_id"),
                "bill_ref_score": round(score, 4),
                "party_sim": round(party_sim, 4),
                "party_gate_min": _PARTY_AUTO_SETTLE_MIN,
                "amount_paid": amount_paid,
                "payment_date": group.get("payment_date"),
            }
            needs_manual_confirmation.append(item)

            best_run_id = str(best["run_id"])
            try:
                from app.routers.reconciliation_api import (
                    _rule37_record_hash,
                )

                rec_hash = _rule37_record_hash(record_id)
                # Aurora primary read
                repo = _get_compliance_repo()
                existing_row = None
                if repo is not None:
                    existing_row = repo.get_rule37_action_by_hash(best_run_id, rec_hash)
                if existing_row is None:
                    # Supabase fallback
                    existing = (
                        sb.table("rule37_actions")
                        .select("status")
                        .eq("run_id", best_run_id)
                        .eq("record_hash", rec_hash)
                        .execute()
                    )
                    existing_statuses = {
                        str(r.get("status") or "").lower() for r in (existing.data or [])
                    }
                else:
                    existing_statuses = {str(existing_row.get("status") or "").lower()}
            except Exception:
                existing_statuses = set()

            # Skip if already resolved or rejected by CA
            if not (existing_statuses & {"resolved", "rejected"}):
                settled_date = _parse_settled_date(group.get("payment_date"))
                _upsert_rule37_action(
                    sb,
                    run_id=best_run_id,
                    record_id=record_id,
                    status_value="pending_review",
                    user_id=account_id,
                    amount_paid=float(amount_paid),
                    tds_deducted=0.0,
                    tds_confirmed=False,
                    total_settled=None,
                    remaining_unpaid_amount=None,
                    payment_coverage="pending_review",
                    source="tally_bridge",
                    settled_date=settled_date,
                    review_metadata=item,
                )
            continue

        invoice_amount = float(best.get("invoice_amount") or 0)
        pending = outstanding_pending.get(bill_ref)
        if pending is not None and pending > _OUTSTANDING_PENDING_EPS:
            remaining = round(pending, 2)
            coverage = "partial"
        else:
            remaining = round(max(invoice_amount - float(amount_paid), 0.0), 2)
            coverage = _rule37_payment_coverage(float(amount_paid), invoice_amount)

        settled_date = _parse_settled_date(group.get("payment_date"))

        # Party gate already passed — this is the only path to upsert.
        _upsert_rule37_action(
            sb,
            run_id=str(best["run_id"]),
            record_id=record_id,
            status_value="resolved",
            user_id=account_id,
            amount_paid=float(amount_paid),
            tds_deducted=0.0,
            tds_confirmed=False,
            total_settled=float(amount_paid),
            remaining_unpaid_amount=remaining,
            payment_coverage=coverage,
            source="tally_bridge",
            settled_date=settled_date,
        )
        claimed.add(record_id)
        open_rows = [r for r in open_rows if str(r.get("record_id")) != record_id]
        settled.append(
            {
                "bill_ref": bill_ref,
                "party": party,
                "invoice_number": best.get("invoice_number"),
                "record_id": record_id,
                "run_id": best.get("run_id"),
                "score": round(score, 4),
                "party_sim": round(party_sim, 4),
                "amount_paid": amount_paid,
                "remaining_unpaid_amount": remaining,
                "payment_coverage": coverage,
                "settled_date": settled_date,
                "tds_confirmed": False,
            }
        )

    # --- Outstandings: unpaid truth only (never settle) ---
    for rec in outstanding:
        if not isinstance(rec, dict):
            continue
        bill_ref = str(rec.get("bill_ref") or "").strip()
        if not bill_ref:
            skipped.append({"reason": "missing_bill_ref", "record": rec})
            continue
        party = str(rec.get("party") or "").strip()
        best, score, second = find_best_open_match(bill_ref, open_rows)
        if best is None or not is_confident_bill_match(
            score, second, unique_gap=_UNIQUE_GAP_UNCLEAR_PARTY
        ):
            skipped.append(
                {
                    "reason": "outstanding_unmatched",
                    "bill_ref": bill_ref,
                    "party": party,
                    "best_score": round(score, 4),
                }
            )
            continue
        record_id = str(best["record_id"])
        if record_id in claimed:
            continue
        pending = _parse_positive_amount(rec.get("amount"))
        still_outstanding.append(
            {
                "bill_ref": bill_ref,
                "party": party,
                "invoice_number": best.get("invoice_number"),
                "record_id": record_id,
                "run_id": best.get("run_id"),
                "pending_due": pending,
                "bill_date": rec.get("bill_date"),
                "score": round(score, 4),
            }
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    rows_imported = (
        len(settled) > 0
        or len(still_outstanding) > 0
        or len(needs_manual_confirmation) > 0
    )
    if rows_imported:
        try:
            q = sb.table("tally_bridge_keys").update({"last_synced_at": now_iso})
            if key_id:
                q = q.eq("id", key_id)
            else:
                q = q.eq("account_id", account_id)
                if company_name:
                    q = q.eq("company_name", company_name)
            q.execute()
        except Exception:
            _log.exception(
                "tally_bridge: failed updating last_synced_at account_id=%s", account_id
            )

    return {
        "open_candidates": len(open_rows) + len(claimed),
        "outstanding_received": len(outstanding),
        "payments_received": len(payments),
        "ledgers_received": len(ledgers) if ledgers else 0,
        "ledgers_synced_count": ledgers_synced,
        "settled_count": len(settled),
        "still_outstanding_count": len(still_outstanding),
        "needs_manual_confirmation_count": len(needs_manual_confirmation),
        "skipped_count": len(skipped),
        "settled": settled,
        "still_outstanding": still_outstanding[:50],
        "needs_manual_confirmation": needs_manual_confirmation[:50],
        "skipped": skipped[:50],
        "last_synced_at": now_iso if rows_imported else None,
        "sync_status": "ok" if rows_imported else "no_rows_imported",
    }

