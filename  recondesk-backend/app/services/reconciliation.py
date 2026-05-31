"""Bidirectional GSTR ↔ PR reconciliation orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date

from app.services.matching_core import THRESHOLD, choose_best_candidate, compute_match_score
from supabase import Client

from app.services.matcher import (
    INVOICE_SIMILARITY_L5_MIN,
    MatchResult,
    invoice_similarity,
    match_gstr_to_pr,
)
from app.services.vendor_name_matcher import find_best_vendor_match

logger = logging.getLogger(__name__)


def get_search_periods(
    invoice_date: date | None,
    gstr_period: date,
    lookback_months: int = 6,
) -> list[date]:
    """First day of month dates: ``gstr_period`` first, then oldest→newest for search windows."""
    gstr_period = date(gstr_period.year, gstr_period.month, 1)

    if invoice_date is None:
        return [gstr_period]

    inv_month = date(invoice_date.year, invoice_date.month, 1)

    if inv_month.year == gstr_period.year and inv_month.month == gstr_period.month:
        return [gstr_period]

    months_before = (gstr_period.year - inv_month.year) * 12 + (
        gstr_period.month - inv_month.month
    )
    if months_before > lookback_months:
        return [gstr_period]

    months_set: set[date] = {inv_month}
    cur = inv_month
    while True:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        if nxt >= gstr_period:
            break
        months_set.add(nxt)
        cur = nxt

    def months_before_gstr(p: date) -> int:
        return (gstr_period.year - p.year) * 12 + (gstr_period.month - p.month)

    filtered = [p for p in months_set if months_before_gstr(p) <= lookback_months]
    rest = sorted(filtered)
    return [gstr_period] + rest


def _taxable_paise(rec: dict) -> int:
    v = rec.get("taxable_amount_paise")
    if v is None:
        return 0
    return int(v)


def _tie_key(
    result: MatchResult,
    gstr_rec: dict,
    pr_rec: dict,
) -> tuple[int, int, int]:
    """Sort key: lower level first, higher confidence, smaller taxable gap."""
    return (
        result.level,
        -result.confidence,
        abs(_taxable_paise(gstr_rec) - _taxable_paise(pr_rec)),
    )


def _accept_reconciliation_pair(
    gstr_rec: dict, pr_rec: dict, result: MatchResult
) -> bool:
    """Gate matcher output for 1:1 reconciliation: same GSTIN, no L4/L6, min invoice sim."""
    if result.level == 6 or result.level > 5:
        return False
    g_gst = str(gstr_rec.get("supplier_gstin") or "").strip()
    p_gst = str(pr_rec.get("supplier_gstin") or "").strip()
    if not g_gst or g_gst != p_gst:
        return False
    # L4 links different invoice numbers with similar amounts — too weak for strict pairing
    # (e.g. INV099 vs INV999 at the same taxable totals).
    if result.level == 4:
        return False
    g_inv = str(gstr_rec.get("invoice_number_normalized") or "")
    p_inv = str(pr_rec.get("invoice_number_normalized") or "")
    return invoice_similarity(g_inv, p_inv) >= INVOICE_SIMILARITY_L5_MIN


def _match_reasons_from_result(result: MatchResult) -> list[str]:
    out = [result.decision_why]
    if result.discrepancies:
        out.extend(result.discrepancies)
    return out


def _infer_gstr_period(gstr_records: list[dict]) -> date:
    for rec in gstr_records:
        v = rec.get("invoice_date")
        if v is None or v == "":
            continue
        if isinstance(v, date):
            return date(v.year, v.month, 1)
        try:
            d = date.fromisoformat(str(v))
            return date(d.year, d.month, 1)
        except (ValueError, TypeError):
            continue
    return date.today().replace(day=1)


def _build_pr_index_by_period(
    pr_records_by_period: dict[date, list[dict]],
) -> dict[date, dict[str, dict[str, list[dict]]]]:
    """Index PR rows by period → GSTIN → normalized invoice number."""
    triple_to_periods: dict[tuple[str, str, str], set[date]] = defaultdict(set)
    pr_index_by_period: dict[date, dict[str, dict[str, list[dict]]]] = {}

    for period, prs in pr_records_by_period.items():
        period_key = date(period.year, period.month, 1)
        inner: dict[str, dict[str, list[dict]]] = defaultdict(dict)
        for p in prs:
            gstin = str(p.get("supplier_gstin") or "")
            inv = str(p.get("invoice_number_normalized") or "")
            pid = str(p["id"])
            triple_to_periods[(gstin, inv, pid)].add(period_key)
            if inv not in inner[gstin]:
                inner[gstin][inv] = []
            inner[gstin][inv].append(p)
        pr_index_by_period[period_key] = {
            g: dict(inv_map) for g, inv_map in inner.items()
        }

    for (_gst, _inv, pid), periods in triple_to_periods.items():
        if len(periods) > 1:
            logger.warning("Duplicate PR record %s found in multiple periods", pid)

    return pr_index_by_period


def build_gstr_by_invoice(gstr_records: list[dict]) -> dict[str, dict]:
    """Normalized invoice number → GSTR matcher row (built once per run)."""
    gstr_by_invoice: dict[str, dict] = {}
    for rec in gstr_records:
        inv = str(rec.get("invoice_number_normalized") or rec.get("invoice_number") or "")
        if inv:
            gstr_by_invoice[inv] = rec
    return gstr_by_invoice


def build_pr_by_invoice(
    pr_index: dict[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """GSTIN → normalized invoice number → PR matcher row."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for gstin, prs in pr_index.items():
        for pr in prs:
            inv = str(pr.get("invoice_number_normalized") or "")
            if inv:
                out[gstin][inv] = pr
    return {g: dict(inv_map) for g, inv_map in out.items()}


def _order_pr_candidates(
    candidates: list[dict],
    *,
    gstin: str,
    inv_norm: str,
    pr_by_invoice: dict[str, dict[str, dict]] | None,
) -> list[dict]:
    """Put hash-index hit first so L1 pairs resolve without scanning the full GSTIN bucket."""
    if not pr_by_invoice or not inv_norm:
        return candidates
    direct = pr_by_invoice.get(gstin, {}).get(inv_norm)
    if direct is None:
        return candidates
    direct_id = str(direct["id"])
    return [direct] + [p for p in candidates if str(p["id"]) != direct_id]


@dataclass
class ReconState:
    """Mutable state for multi-chunk GSTR↔PR matching (avoids re-processing or duplicate PR use)."""

    matched: list[dict] = field(default_factory=list)
    matched_pr_ids: set[str] = field(default_factory=set)
    matched_gstr_ids: set[str] = field(default_factory=set)
    missed_itc: list[dict] = field(default_factory=list)


def process_gstr_records_chunk(
    gstr_records: list[dict],
    effective_gstr_period: date,
    pr_index: dict[str, list[dict]],
    pr_index_by_period: dict[date, dict[str, dict[str, list[dict]]]],
    state: ReconState,
    *,
    gstr_by_invoice: dict[str, dict] | None = None,
    pr_by_invoice: dict[str, dict[str, dict]] | None = None,
) -> None:
    """Match a chunk of GSTR rows using shared *state* (same invariants as full run)."""
    gstr_period = date(effective_gstr_period.year, effective_gstr_period.month, 1)
    for gstr_record in gstr_records:
        gstr_id = str(gstr_record["id"])
        gstin = gstr_record.get("supplier_gstin") or ""
        gstin_str = str(gstin)
        candidates = pr_index.get(gstin_str, [])
        inv_norm = str(gstr_record.get("invoice_number_normalized") or "")
        ordered_candidates = _order_pr_candidates(
            candidates,
            gstin=gstin_str,
            inv_norm=inv_norm,
            pr_by_invoice=pr_by_invoice,
        )

        best_result: MatchResult | None = None
        best_pr: dict | None = None
        best_key: tuple[int, int, int] | None = None
        tied_at_best: list[tuple[MatchResult, dict]] = []

        for pr_rec in ordered_candidates:
            pr_id = str(pr_rec["id"])
            if pr_id in state.matched_pr_ids:
                continue
            result = match_gstr_to_pr(
                gstr_record, [pr_rec], gstr_by_invoice=gstr_by_invoice
            )
            if result is None or not _accept_reconciliation_pair(
                gstr_record, pr_rec, result
            ):
                continue
            key = _tie_key(result, gstr_record, pr_rec)
            if best_key is None or key < best_key:
                best_key = key
                tied_at_best = [(result, pr_rec)]
            elif key == best_key:
                tied_at_best.append((result, pr_rec))

        if tied_at_best:
            if len(tied_at_best) > 1 and tied_at_best[0][0].level == 5:
                vendor_pick = find_best_vendor_match(
                    gstr_record.get("supplier_name", ""),
                    [
                        {
                            "vendor_name": pr.get("vendor_name", ""),
                            "record": pr,
                        }
                        for _, pr in tied_at_best
                    ],
                    threshold=0.82,
                )
                if vendor_pick is not None:
                    picked_pr = vendor_pick["record"]
                    for result, pr_rec in tied_at_best:
                        if pr_rec is picked_pr:
                            best_result = replace(
                                result,
                                vendor_similarity_score=vendor_pick[
                                    "vendor_similarity_score"
                                ],
                            )
                            best_pr = pr_rec
                            break
                else:
                    best_result, best_pr = tied_at_best[0]
            else:
                best_result, best_pr = tied_at_best[0]

        if best_result is not None and best_pr is not None:
            score = compute_match_score(best_result)
            state.matched.append(
                {
                    "gstr_id": str(gstr_record["id"]),
                    "pr_id": str(best_pr["id"]),
                    "confidence_score": score,
                    "match_reasons": _match_reasons_from_result(best_result),
                    "is_late_filing": False,
                    "original_period": None,
                    "late_months": 0,
                    "match_status_text": "Matched",
                    "vendor_similarity_score": best_result.vendor_similarity_score,
                }
            )
            state.matched_pr_ids.add(str(best_pr["id"]))
            state.matched_gstr_ids.add(gstr_id)
            continue

        inv_raw = gstr_record.get("invoice_date")
        inv_d: date | None
        if inv_raw is None or inv_raw == "":
            inv_d = None
        elif isinstance(inv_raw, date):
            inv_d = inv_raw
        else:
            try:
                inv_d = date.fromisoformat(str(inv_raw))
            except (ValueError, TypeError):
                inv_d = None

        periods = get_search_periods(inv_d, gstr_period)
        other_periods = sorted(
            periods[1:],
            key=lambda d: abs(
                (gstr_period.year - d.year) * 12
                + (gstr_period.month - d.month)
            ),
        )

        cross_matched = False
        for period in other_periods:
            inv_norm = str(gstr_record.get("invoice_number_normalized") or "")
            raw_candidates = (
                pr_index_by_period.get(period, {})
                .get(str(gstin), {})
                .get(inv_norm, [])
            )
            raw_candidates = [
                p for p in raw_candidates if str(p["id"]) not in state.matched_pr_ids
            ]
            candidates_cp = sorted(raw_candidates, key=lambda x: x["id"])
            acceptable: list[dict] = []
            for p in candidates_cp:
                r = match_gstr_to_pr(
                    gstr_record, [p], gstr_by_invoice=gstr_by_invoice
                )
                if r is None or not _accept_reconciliation_pair(gstr_record, p, r):
                    continue
                acceptable.append(p)
            if not acceptable:
                continue

            best_p, score, _ = choose_best_candidate(
                gstr_record, acceptable, gstr_by_invoice=gstr_by_invoice
            )
            if best_p is None or score < THRESHOLD:
                continue

            final_mr = match_gstr_to_pr(
                gstr_record, [best_p], gstr_by_invoice=gstr_by_invoice
            )
            if final_mr is None:
                continue

            late_months = (gstr_period.year - period.year) * 12 + (
                gstr_period.month - period.month
            )
            state.matched.append(
                {
                    "gstr_id": str(gstr_record["id"]),
                    "pr_id": str(best_p["id"]),
                    "confidence_score": score,
                    "match_reasons": _match_reasons_from_result(final_mr),
                    "is_late_filing": True,
                    "original_period": period,
                    "late_months": late_months,
                    "match_status_text": (
                        f"Matched -- Late Supplier Filing ({late_months} months late)"
                    ),
                    "vendor_similarity_score": final_mr.vendor_similarity_score,
                }
            )
            state.matched_pr_ids.add(str(best_p["id"]))
            state.matched_gstr_ids.add(gstr_id)
            cross_matched = True
            break

        if cross_matched:
            continue

        ttp = gstr_record.get("total_tax_paise")
        state.missed_itc.append(
            {
                "gstr_id": gstr_id,
                "supplier_gstin": str(gstin),
                "invoice_number_normalized": str(
                    gstr_record.get("invoice_number_normalized") or ""
                ),
                "invoice_date": gstr_record.get("invoice_date"),
                "total_tax_paise": int(ttp) if ttp is not None else 0,
            }
        )


def build_wrongful_itc_risk(
    pr_records: list[dict],
    matched_pr_ids: set[str],
) -> list[dict]:
    """PR rows in the current run that had no GSTR match."""
    out: list[dict] = []
    for pr_rec in pr_records:
        pr_id = str(pr_rec["id"])
        if pr_id in matched_pr_ids:
            continue
        ttp = pr_rec.get("total_tax_paise")
        tap = pr_rec.get("taxable_amount_paise")
        out.append(
            {
                "id": pr_id,
                "supplier_gstin": str(pr_rec.get("supplier_gstin") or ""),
                "invoice_number_normalized": str(
                    pr_rec.get("invoice_number_normalized") or ""
                ),
                "invoice_date": pr_rec.get("invoice_date"),
                "taxable_amount_paise": int(tap) if tap is not None else 0,
                "total_tax_paise": int(ttp) if ttp is not None else 0,
            }
        )
    return out


def _finalize_reconciliation_result(
    state: ReconState,
    wrongful_itc_risk: list[dict],
    total_gstr: int,
    total_pr: int,
) -> dict:
    """Shared stats and sanity payload (same as :func:`run_bidirectional_reconciliation` output)."""
    matched_count = len(state.matched)
    missed_itc_count = len(state.missed_itc)
    missed_itc_amount_paise = sum(
        int(m["total_tax_paise"]) for m in state.missed_itc
    )
    wrongful_risk_count = len(wrongful_itc_risk)
    wrongful_risk_amount_paise = sum(
        int(w["total_tax_paise"]) for w in wrongful_itc_risk
    )

    missed_gstr_ids = {str(m["gstr_id"]) for m in state.missed_itc}
    sanity_passed = (
        matched_count + missed_itc_count == total_gstr
        and matched_count + wrongful_risk_count == total_pr
        and not (state.matched_gstr_ids & missed_gstr_ids)
        and len(state.matched_pr_ids) == matched_count
    )

    if total_gstr > 0:
        match_rate_pct = round(matched_count / total_gstr * 100, 2)
    else:
        match_rate_pct = 0.0

    return {
        "matched": state.matched,
        "missed_itc": state.missed_itc,
        "wrongful_itc_risk": wrongful_itc_risk,
        "stats": {
            "total_gstr": total_gstr,
            "total_pr": total_pr,
            "matched_count": matched_count,
            "missed_itc_count": missed_itc_count,
            "missed_itc_amount_paise": missed_itc_amount_paise,
            "wrongful_risk_count": wrongful_risk_count,
            "wrongful_risk_amount_paise": wrongful_risk_amount_paise,
            "match_rate_pct": match_rate_pct,
            "sanity_passed": sanity_passed,
        },
    }


def run_bidirectional_reconciliation(
    gstr_records: list[dict],
    pr_records: list[dict],
    gstr_period: date | None = None,
    pr_records_by_period: dict[date, list[dict]] | None = None,
) -> dict:
    total_gstr = len(gstr_records)
    total_pr = len(pr_records)

    effective_gstr_period = gstr_period
    if effective_gstr_period is None and gstr_records:
        effective_gstr_period = _infer_gstr_period(gstr_records)
    elif effective_gstr_period is None:
        effective_gstr_period = date.today().replace(day=1)

    effective_pr_by_period: dict[date, list[dict]]
    if pr_records_by_period is None:
        effective_pr_by_period = {effective_gstr_period: pr_records}
    else:
        effective_pr_by_period = {
            date(k.year, k.month, 1): v for k, v in pr_records_by_period.items()
        }

    pr_index_by_period = _build_pr_index_by_period(effective_pr_by_period)

    if total_gstr == 0:
        return {
            "matched": [],
            "missed_itc": [],
            "wrongful_itc_risk": [],
            "stats": {
                "total_gstr": 0,
                "total_pr": total_pr,
                "matched_count": 0,
                "missed_itc_count": 0,
                "missed_itc_amount_paise": 0,
                "wrongful_risk_count": 0,
                "wrongful_risk_amount_paise": 0,
                "match_rate_pct": 0.0,
                "sanity_passed": True,
            },
        }

    gstr_p = date(effective_gstr_period.year, effective_gstr_period.month, 1)
    pr_records_current = effective_pr_by_period.get(effective_gstr_period, [])
    pr_index: dict[str, list[dict]] = defaultdict(list)
    for pr_rec in pr_records_current:
        gstin = pr_rec.get("supplier_gstin") or ""
        pr_index[str(gstin)].append(pr_rec)

    gstr_by_invoice = build_gstr_by_invoice(gstr_records)
    pr_by_invoice = build_pr_by_invoice(pr_index)

    state = ReconState()
    process_gstr_records_chunk(
        gstr_records,
        gstr_p,
        pr_index,
        pr_index_by_period,
        state,
        gstr_by_invoice=gstr_by_invoice,
        pr_by_invoice=pr_by_invoice,
    )
    wrongful_itc_risk = build_wrongful_itc_risk(pr_records, state.matched_pr_ids)
    return _finalize_reconciliation_result(
        state, wrongful_itc_risk, total_gstr, total_pr
    )


def notify_reconciliation_run_completed_email_maybe(
    client: Client,
    *,
    run_id: str,
    actor_user_id: str | None,
    to_email: str,
    full_name: str,
    client_name: str,
    period: str,
    matched_count: int,
    missed_itc_amount_paise: int,
    wrongful_risk_amount_paise: int,
    match_rate_percent: float,
) -> None:
    """If no prior EMAIL_SENT for this run, send completion email and record EMAIL_SENT.

    Swallows failures from :func:`asyncio.run` so Celery / callers are never blocked.
    """
    from app.utils.audit import log_action_sync
    from app.utils.email import send_reconciliation_complete_email

    to_clean = (to_email or "").strip()
    if not to_clean:
        return

    try:
        already = (
            client.table("audit_logs")
            .select("id")
            .eq("action", "EMAIL_SENT")
            .eq("entity_id", run_id)
            .limit(1)
            .execute()
        )
        if (already.data or []):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_logs idempotency check failed run_id=%s: %s", run_id, exc)
        return

    try:
        ok = asyncio.run(
            send_reconciliation_complete_email(
                to_clean,
                (full_name or "").strip() or "there",
                (client_name or "").strip() or "Client",
                (period or "").strip(),
                matched_count,
                int(missed_itc_amount_paise),
                int(wrongful_risk_amount_paise),
                float(match_rate_percent),
                run_id,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("reconciliation complete email failed run_id=%s: %s", run_id, exc)
        return

    if not ok:
        return

    log_action_sync(
        actor_user_id,
        "EMAIL_SENT",
        "reconciliation_run",
        run_id,
        {"kind": "reconciliation_complete"},
    )
