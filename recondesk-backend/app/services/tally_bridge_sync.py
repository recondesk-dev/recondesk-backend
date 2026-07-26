"""Match Tally bill refs to open Rule 37 invoices and settle via existing upsert."""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timezone
from typing import Any, Optional

from supabase import Client

from app.services.matcher import (
    INVOICE_SIMILARITY_L5_MIN,
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
# Soft party-name boost; never settles on party alone.
_PARTY_BOOST_MIN = 0.82
# Require a clear winner when multiple candidates score above the floor.
_UNIQUE_GAP_MIN = 0.05

API_KEY_PREFIX = "rdb_"


def generate_tally_bridge_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def score_bill_ref_against_invoice(
    bill_ref: str,
    invoice_number: str,
    *,
    party: str = "",
    supplier_name: str = "",
) -> float:
    """Reuse GSTR↔PR invoice identity helpers; optional rapidfuzz party boost."""
    if not bill_ref or not invoice_number:
        return 0.0

    if invoices_effectively_match(bill_ref, invoice_number):
        base = 1.0
    elif is_invoice_format_variant(bill_ref, invoice_number, bill_ref, invoice_number):
        base = 0.95
    else:
        base = float(invoice_similarity(bill_ref, invoice_number))

    if party and supplier_name:
        party_sim = vendor_name_similarity(party, supplier_name)
        if party_sim >= _PARTY_BOOST_MIN and base >= INVOICE_SIMILARITY_L5_MIN:
            base = min(1.0, base + 0.05)

    return base


def is_confident_bill_match(score: float, second_best: float = 0.0) -> bool:
    if score < _CONFIDENT_SIM_MIN:
        return False
    if second_best > 0 and (score - second_best) < _UNIQUE_GAP_MIN and score < 0.999:
        return False
    return True


def _paise_to_rupees(paise: int) -> float:
    return round(int(paise or 0) / 100.0, 2)


def _actions_resolved_hashes(sb: Client, run_id: str) -> set[str]:
    try:
        res = (
            sb.table("rule37_actions")
            .select("record_hash, status")
            .eq("run_id", run_id)
            .execute()
        )
    except Exception:
        _log.exception("tally_bridge: failed reading rule37_actions run_id=%s", run_id)
        return set()
    out: set[str] = set()
    for row in res.data or []:
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
    *,
    party: str = "",
) -> tuple[Optional[dict[str, Any]], float, float]:
    """Return (best_row, best_score, second_best_score)."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in open_rows:
        score = score_bill_ref_against_invoice(
            bill_ref,
            str(row.get("invoice_number") or ""),
            party=party,
            supplier_name=str(row.get("supplier_name") or ""),
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


def apply_tally_outstanding_sync(
    sb: Client,
    *,
    account_id: str,
    records: list[dict[str, Any]],
    company_name: str = "",
    key_id: str | None = None,
) -> dict[str, Any]:
    """Match incoming Tally bill refs to open Rule 37 rows and settle confident hits.

    Uses ``_upsert_rule37_action`` (same path as the dashboard Mark as Settled).
    """
    # Local import avoids circular import at module load (router ↔ reconciliation_api).
    from app.routers.reconciliation_api import (
        _rule37_payment_coverage,
        _upsert_rule37_action,
    )

    open_rows = load_open_rule37_for_account(sb, account_id)
    settled: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    claimed: set[str] = set()  # record_id already settled this sync

    for rec in records:
        if not isinstance(rec, dict):
            continue
        bill_ref = str(rec.get("bill_ref") or "").strip()
        if not bill_ref:
            skipped.append({"reason": "missing_bill_ref", "record": rec})
            continue
        party = str(rec.get("party") or "").strip()
        best, score, second = find_best_open_match(bill_ref, open_rows, party=party)
        if best is None or not is_confident_bill_match(score, second):
            skipped.append(
                {
                    "reason": "weak_or_no_match",
                    "bill_ref": bill_ref,
                    "best_score": round(score, 4),
                    "second_best": round(second, 4),
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

        invoice_amount = float(best.get("invoice_amount") or 0)
        tally_amount = rec.get("amount")
        try:
            amount_paid = (
                round(abs(float(tally_amount)), 2)
                if tally_amount is not None
                else round(invoice_amount, 2)
            )
        except (TypeError, ValueError):
            amount_paid = round(invoice_amount, 2)
        if amount_paid <= 0 and invoice_amount > 0:
            amount_paid = round(invoice_amount, 2)
        if amount_paid <= 0:
            skipped.append(
                {
                    "reason": "non_positive_amount",
                    "bill_ref": bill_ref,
                    "record_id": record_id,
                }
            )
            continue

        total_settled = amount_paid
        remaining = round(max(invoice_amount - total_settled, 0.0), 2)
        coverage = _rule37_payment_coverage(total_settled, invoice_amount)
        settled_date = _parse_settled_date(rec.get("bill_date"))

        _upsert_rule37_action(
            sb,
            run_id=str(best["run_id"]),
            record_id=record_id,
            status_value="resolved",
            user_id=account_id,
            amount_paid=amount_paid,
            tds_deducted=0.0,
            tds_confirmed=True,
            total_settled=total_settled,
            remaining_unpaid_amount=remaining,
            payment_coverage=coverage,
            source="tally_bridge",
            settled_date=settled_date,
        )
        claimed.add(record_id)
        # Remove from open pool so one invoice is not double-matched
        open_rows = [r for r in open_rows if str(r.get("record_id")) != record_id]
        settled.append(
            {
                "bill_ref": bill_ref,
                "invoice_number": best.get("invoice_number"),
                "record_id": record_id,
                "run_id": best.get("run_id"),
                "score": round(score, 4),
                "amount_paid": amount_paid,
                "settled_date": settled_date,
            }
        )

    now_iso = datetime.now(timezone.utc).isoformat()
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
        "received": len(records),
        "settled_count": len(settled),
        "skipped_count": len(skipped),
        "settled": settled,
        "skipped": skipped[:50],
        "last_synced_at": now_iso,
    }
