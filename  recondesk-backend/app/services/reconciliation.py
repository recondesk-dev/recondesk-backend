"""Bidirectional GSTR ↔ PR reconciliation orchestration."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from app.services.matching_core import THRESHOLD, choose_best_candidate, compute_match_score
from app.services.matcher import (
    INVOICE_SIMILARITY_L5_MIN,
    MatchResult,
    invoice_similarity,
    match_gstr_to_pr,
)

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

    pr_records_current = effective_pr_by_period.get(effective_gstr_period, [])
    pr_index: dict[str, list[dict]] = defaultdict(list)
    for pr_rec in pr_records_current:
        gstin = pr_rec.get("supplier_gstin") or ""
        pr_index[str(gstin)].append(pr_rec)

    matched: list[dict] = []
    matched_pr_ids: set[str] = set()
    matched_gstr_ids: set[str] = set()
    missed_itc: list[dict] = []

    for gstr_record in gstr_records:
        gstr_id = str(gstr_record["id"])
        gstin = gstr_record.get("supplier_gstin") or ""
        candidates = pr_index.get(str(gstin), [])

        best_result: MatchResult | None = None
        best_pr: dict | None = None
        best_key: tuple[int, int, int] | None = None

        for pr_rec in candidates:
            pr_id = str(pr_rec["id"])
            if pr_id in matched_pr_ids:
                continue
            result = match_gstr_to_pr(gstr_record, [pr_rec])
            if result is None or not _accept_reconciliation_pair(
                gstr_record, pr_rec, result
            ):
                continue
            key = _tie_key(result, gstr_record, pr_rec)
            if best_key is None or key < best_key:
                best_key = key
                best_result = result
                best_pr = pr_rec

        if best_result is not None and best_pr is not None:
            score = compute_match_score(best_result)
            matched.append(
                {
                    "gstr_id": str(gstr_record["id"]),
                    "pr_id": str(best_pr["id"]),
                    "confidence_score": score,
                    "match_reasons": _match_reasons_from_result(best_result),
                    "is_late_filing": False,
                    "original_period": None,
                    "late_months": 0,
                    "match_status_text": "Matched",
                }
            )
            matched_pr_ids.add(str(best_pr["id"]))
            matched_gstr_ids.add(gstr_id)
            continue

        # Cross-period late filing search
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

        periods = get_search_periods(inv_d, effective_gstr_period)
        other_periods = sorted(
            periods[1:],
            key=lambda d: abs(
                (effective_gstr_period.year - d.year) * 12
                + (effective_gstr_period.month - d.month)
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
                p for p in raw_candidates if str(p["id"]) not in matched_pr_ids
            ]
            candidates_cp = sorted(raw_candidates, key=lambda x: x["id"])
            acceptable: list[dict] = []
            for p in candidates_cp:
                r = match_gstr_to_pr(gstr_record, [p])
                if r is None or not _accept_reconciliation_pair(gstr_record, p, r):
                    continue
                acceptable.append(p)
            if not acceptable:
                continue

            best_p, score, _ = choose_best_candidate(gstr_record, acceptable)
            if best_p is None or score < THRESHOLD:
                continue

            final_mr = match_gstr_to_pr(gstr_record, [best_p])
            if final_mr is None:
                continue

            late_months = (effective_gstr_period.year - period.year) * 12 + (
                effective_gstr_period.month - period.month
            )
            matched.append(
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
                }
            )
            matched_pr_ids.add(str(best_p["id"]))
            matched_gstr_ids.add(gstr_id)
            cross_matched = True
            break

        if cross_matched:
            continue

        ttp = gstr_record.get("total_tax_paise")
        missed_itc.append(
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

    wrongful_itc_risk: list[dict] = []
    for pr_rec in pr_records:
        pr_id = str(pr_rec["id"])
        if pr_id in matched_pr_ids:
            continue
        ttp = pr_rec.get("total_tax_paise")
        tap = pr_rec.get("taxable_amount_paise")
        wrongful_itc_risk.append(
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

    matched_count = len(matched)
    missed_itc_count = len(missed_itc)
    missed_itc_amount_paise = sum(
        int(m["total_tax_paise"]) for m in missed_itc
    )
    wrongful_risk_count = len(wrongful_itc_risk)
    wrongful_risk_amount_paise = sum(
        int(w["total_tax_paise"]) for w in wrongful_itc_risk
    )

    missed_gstr_ids = {str(m["gstr_id"]) for m in missed_itc}
    sanity_passed = (
        matched_count + missed_itc_count == total_gstr
        and matched_count + wrongful_risk_count == total_pr
        and not (matched_gstr_ids & missed_gstr_ids)
        and len(matched_pr_ids) == matched_count
    )

    if total_gstr > 0:
        match_rate_pct = round(matched_count / total_gstr * 100, 2)
    else:
        match_rate_pct = 0.0

    return {
        "matched": matched,
        "missed_itc": missed_itc,
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
