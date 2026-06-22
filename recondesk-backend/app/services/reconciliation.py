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
    TOTAL_TOLERANCE_PAISE,
    MatchResult,
    invoice_similarity,
    is_invoice_format_variant,
    match_gstr_to_pr,
    normalize_invoice,
    same_pan,
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
    """Gate matcher output for 1:1 reconciliation."""
    if result.level == 6 or result.level > 5:
        return False
    g_gst = str(gstr_rec.get("supplier_gstin") or "").strip()
    p_gst = str(pr_rec.get("supplier_gstin") or "").strip()
    
    if not g_gst or not p_gst:
        return False
        
    if g_gst != p_gst:
        # Only allow GSTIN mismatch if explicitly marked as Review Required (Tier 4)
        if result.requires_human_review and result.review_reason == "GSTIN_MISMATCH":
            return True
        return False

    return True


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


def _get_tax_bucket(amount_paise: int | None) -> int:
    if amount_paise is None:
        return 0
    return int(round(amount_paise / 10000.0))

@dataclass
class PRCandidateIndices:
    by_taxable: dict[str, dict[int, list[dict]]] = field(default_factory=dict)
    by_tax: dict[str, dict[int, list[dict]]] = field(default_factory=dict)
    by_invoice_norm_global: dict[str, list[dict]] = field(default_factory=dict)

def build_pr_candidate_indices(pr_index: dict[str, list[dict]]) -> PRCandidateIndices:
    indices = PRCandidateIndices()
    for gstin, prs in pr_index.items():
        taxable_dict = defaultdict(list)
        tax_dict = defaultdict(list)
        for pr in prs:
            tb = _get_tax_bucket(pr.get("taxable_amount_paise"))
            txb = _get_tax_bucket(pr.get("total_tax_paise"))
            taxable_dict[tb].append(pr)
            tax_dict[txb].append(pr)
            
            # Global invoice norm index
            inv_norm = str(pr.get("invoice_number_normalized") or "")
            if inv_norm:
                if inv_norm not in indices.by_invoice_norm_global:
                    indices.by_invoice_norm_global[inv_norm] = []
                indices.by_invoice_norm_global[inv_norm].append(pr)
                
        indices.by_taxable[gstin] = dict(taxable_dict)
        indices.by_tax[gstin] = dict(tax_dict)
    return indices

def _get_narrowed_candidates(
    gstr_record: dict,
    gstin: str,
    inv_norm: str,
    pr_by_invoice: dict[str, dict[str, dict]] | None,
    candidate_indices: PRCandidateIndices | None,
    pr_index_candidates: list[dict],
) -> list[dict]:
    """Narrow candidates using exact match and tax amount buckets to avoid O(N*M) fuzzy comparisons."""
    direct = pr_by_invoice.get(gstin, {}).get(inv_norm) if pr_by_invoice and inv_norm else None

    if not candidate_indices:
        candidates = pr_index_candidates
        if direct:
            direct_id = str(direct["id"])
            return [direct] + [p for p in candidates if str(p["id"]) != direct_id]
        return candidates

    candidates_set = {}
    if direct:
        candidates_set[str(direct["id"])] = direct

    g_taxable = gstr_record.get("taxable_amount_paise")
    g_tax = gstr_record.get("total_tax_paise")

    tb = _get_tax_bucket(g_taxable)
    txb = _get_tax_bucket(g_tax)

    # Candidates by exact GSTIN and nearby taxable bucket
    taxable_buckets = candidate_indices.by_taxable.get(gstin, {})
    for b in (tb - 1, tb, tb + 1):
        for pr in taxable_buckets.get(b, []):
            candidates_set[str(pr["id"])] = pr

    # Candidates by exact GSTIN and nearby tax bucket
    tax_buckets = candidate_indices.by_tax.get(gstin, {})
    for b in (txb - 1, txb, txb + 1):
        for pr in tax_buckets.get(b, []):
            candidates_set[str(pr["id"])] = pr

    # Candidates by exact normalized invoice number globally (handles GSTIN typos)
    if inv_norm:
        for pr in candidate_indices.by_invoice_norm_global.get(inv_norm, []):
            candidates_set[str(pr["id"])] = pr

    ordered = []
    if direct:
        ordered.append(direct)
        candidates_set.pop(str(direct["id"]), None)

    ordered.extend(candidates_set.values())
    return ordered


@dataclass
class ReconState:
    """Mutable state for multi-chunk GSTR↔PR matching (avoids re-processing or duplicate PR use)."""

    matched: list[dict] = field(default_factory=list)
    review_required: list[dict] = field(default_factory=list)
    matched_pr_ids: set[str] = field(default_factory=set)
    matched_gstr_ids: set[str] = field(default_factory=set)
    missed_itc: list[dict] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=lambda: defaultdict(int))



def _push_matched(state, gstr_id, pr_id, score, best_result, is_late_filing=False, original_period=None, late_months=0):
    match_dict = {
        "gstr_id": str(gstr_id),
        "pr_id": str(pr_id),
        "confidence_score": score,
        "match_reasons": _match_reasons_from_result(best_result),
        "is_late_filing": is_late_filing,
        "original_period": original_period,
        "late_months": late_months,
        "match_status_text": "Review Required" if best_result.requires_human_review else "Matched",
        "vendor_similarity_score": best_result.vendor_similarity_score,
        "identity_confidence": getattr(best_result, "identity_confidence", "High"),
        "financial_status": getattr(best_result, "financial_status", "Exact"),
        "review_reason": best_result.review_reason,
    }
    state.matched.append(match_dict)
    
    state.matched_pr_ids.add(str(pr_id))
    state.matched_gstr_ids.add(str(gstr_id))

def process_gstr_records_chunk(
    gstr_records: list[dict],
    effective_gstr_period: date,
    pr_index: dict[str, list[dict]],
    pr_index_by_period: dict[date, dict[str, dict[str, list[dict]]]],
    state: ReconState,
    *,
    gstr_by_invoice: dict[str, dict] | None = None,
    pr_by_invoice: dict[str, dict[str, dict]] | None = None,
    candidate_indices: PRCandidateIndices | None = None,
    audit_mode: bool = False,
) -> None:
    """Match a chunk of GSTR rows using shared *state* (same invariants as full run)."""
    gstr_period = date(effective_gstr_period.year, effective_gstr_period.month, 1)
    for gstr_record in gstr_records:
        gstr_id = str(gstr_record["id"])
        gstin = gstr_record.get("supplier_gstin") or ""
        gstin_str = str(gstin)
        candidates = pr_index.get(gstin_str, [])
        inv_norm = str(gstr_record.get("invoice_number_normalized") or "")
        ordered_candidates = _get_narrowed_candidates(
            gstr_record,
            gstin=gstin_str,
            inv_norm=inv_norm,
            pr_by_invoice=pr_by_invoice,
            candidate_indices=candidate_indices,
            pr_index_candidates=candidates,
        )

        best_result: MatchResult | None = None
        best_pr: dict | None = None
        best_key: tuple[int, int, int] | None = None
        tied_at_best: list[tuple[MatchResult, dict]] = []

        for idx, pr_rec in enumerate(ordered_candidates):
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
            if idx == 0 and result.level == 1:
                break

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
            _push_matched(state, gstr_record["id"], best_pr["id"], score, best_result)
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
        tap = gstr_record.get("taxable_amount_paise")
        state.missed_itc.append(
            {
                "gstr_id": gstr_id,
                "supplier_gstin": str(gstin),
                "invoice_number_normalized": str(
                    gstr_record.get("invoice_number_normalized") or ""
                ),
                "invoice_date": gstr_record.get("invoice_date"),
                "taxable_amount_paise": int(tap) if tap is not None else 0,
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


def _identity_key(gstin: str | None, invoice: str | None) -> tuple[str, str]:
    return (
        str(gstin or "").strip().upper(),
        normalize_invoice(invoice or ""),
    )


def _levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def resolve_orphans(
    matched: list[dict],
    missed_itc: list[dict],
    wrongful_itc_risk: list[dict],
    gstr_by_id: dict[str, dict],
    pr_by_id: dict[str, dict],
    *,
    amount_tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Reclassify orphan pools so no invoice is double-counted.

    0. **Duplicate Conflicts** — Any identity (GSTIN, inv_norm) with multiple GSTRs or PRs
       that cannot be unambiguously paired is pulled into ``review_required``.
    1. **GSTIN mismatch** — a GSTR-only (missed) row and a PR-only (risk) row that
       share the same normalized invoice number + ITC (within tolerance) but
       have different GSTINs (edit distance <= 2) are a likely typo: paired into
       ``gstin_mismatch`` and removed from both orphan pools.

    Returns ``(matched_final, missed_final, wrongful_final, gstin_mismatch, review_required)``.
    """
    review_required: list[dict] = []
    
    # --- 0. Duplicate / Conflict detection ---
    groups = defaultdict(lambda: {"gstr": [], "pr": []})
    
    for m in matched:
        gid = str(m.get("gstr_id"))
        g = gstr_by_id.get(gid)
        if g:
            groups[_identity_key(g.get("supplier_gstin"), g.get("invoice_number_normalized"))]["gstr"].append({
                "gstr_id": gid,
                "supplier_gstin": str(g.get("supplier_gstin") or ""),
                "invoice_number_normalized": str(g.get("invoice_number_normalized") or ""),
                "invoice_date": g.get("invoice_date"),
                "taxable_amount_paise": int(g.get("taxable_amount_paise") or 0),
                "total_tax_paise": int(g.get("total_tax_paise") or 0),
            })
            
        pid = str(m.get("pr_id"))
        p = pr_by_id.get(pid)
        if p:
            groups[_identity_key(p.get("supplier_gstin"), p.get("invoice_number_normalized"))]["pr"].append({
                "id": pid,
                "supplier_gstin": str(p.get("supplier_gstin") or ""),
                "invoice_number_normalized": str(p.get("invoice_number_normalized") or ""),
                "invoice_date": p.get("invoice_date"),
                "taxable_amount_paise": int(p.get("taxable_amount_paise") or 0),
                "total_tax_paise": int(p.get("total_tax_paise") or 0),
            })

    for mi in missed_itc:
        groups[_identity_key(mi.get("supplier_gstin"), mi.get("invoice_number_normalized"))]["gstr"].append(mi)
        
    for w in wrongful_itc_risk:
        groups[_identity_key(w.get("supplier_gstin"), w.get("invoice_number_normalized"))]["pr"].append(w)

    conflicted_gstr_ids = set()
    conflicted_pr_ids = set()

    for key, group in groups.items():
        g_list = group["gstr"]
        p_list = group["pr"]
        
        if len(g_list) <= 1 and len(p_list) <= 1:
            continue
            
        is_unambiguous = False
        if len(g_list) == len(p_list):
            g_sigs = [(int(g.get("taxable_amount_paise") or 0), str(g.get("invoice_date") or "")) for g in g_list]
            p_sigs = [(int(p.get("taxable_amount_paise") or 0), str(p.get("invoice_date") or "")) for p in p_list]
            if len(set(g_sigs)) == len(g_list) and sorted(g_sigs) == sorted(p_sigs):
                is_unambiguous = True

        if not is_unambiguous:
            for g in g_list:
                gid = str(g.get("gstr_id") or g.get("id"))
                if gid not in conflicted_gstr_ids:
                    conflicted_gstr_ids.add(gid)
                    review_required.append({**g, "side": "GSTR", "reason": "DUPLICATE_CONFLICT"})
            for p in p_list:
                pid = str(p.get("id") or p.get("pr_id"))
                if pid not in conflicted_pr_ids:
                    conflicted_pr_ids.add(pid)
                    review_required.append({**p, "side": "PR", "reason": "DUPLICATE_CONFLICT"})

    # Ensure if one half of a matched pair is conflicted, the other half is too
    for m in matched:
        gid = str(m.get("gstr_id"))
        pid = str(m.get("pr_id"))
        if gid in conflicted_gstr_ids or pid in conflicted_pr_ids:
            if gid not in conflicted_gstr_ids:
                g = gstr_by_id.get(gid)
                if g:
                    review_required.append({
                        "side": "GSTR", "reason": "DUPLICATE_CONFLICT", "gstr_id": gid,
                        "supplier_gstin": str(g.get("supplier_gstin") or ""),
                        "invoice_number_normalized": str(g.get("invoice_number_normalized") or ""),
                        "invoice_date": g.get("invoice_date"),
                        "taxable_amount_paise": int(g.get("taxable_amount_paise") or 0),
                        "total_tax_paise": int(g.get("total_tax_paise") or 0),
                    })
                    conflicted_gstr_ids.add(gid)
            if pid not in conflicted_pr_ids:
                p = pr_by_id.get(pid)
                if p:
                    review_required.append({
                        "side": "PR", "reason": "DUPLICATE_CONFLICT", "id": pid,
                        "supplier_gstin": str(p.get("supplier_gstin") or ""),
                        "invoice_number_normalized": str(p.get("invoice_number_normalized") or ""),
                        "invoice_date": p.get("invoice_date"),
                        "taxable_amount_paise": int(p.get("taxable_amount_paise") or 0),
                        "total_tax_paise": int(p.get("total_tax_paise") or 0),
                    })
                    conflicted_pr_ids.add(pid)

    matched_final = [m for m in matched if str(m.get("gstr_id")) not in conflicted_gstr_ids and str(m.get("pr_id")) not in conflicted_pr_ids]
    missed_after_conflict = [mi for mi in missed_itc if str(mi.get("gstr_id")) not in conflicted_gstr_ids]
    wrongful_after_conflict = [w for w in wrongful_itc_risk if str(w.get("id")) not in conflicted_pr_ids]

    gstin_mismatch: list[dict] = []

    # --- 1. GSTIN-mismatch pairing (different GSTIN edit distance <= 2, same invoice + ITC) ---
    wrongful_by_inv: dict[str, list[dict]] = defaultdict(list)
    for w in wrongful_after_conflict:
        inv = normalize_invoice(w.get("invoice_number_normalized") or "")
        wrongful_by_inv[inv].append(w)

    consumed_wrongful: set[int] = set()
    missed_final: list[dict] = []
    for mi in missed_after_conflict:
        g_gstin = str(mi.get("supplier_gstin") or "")
        inv = normalize_invoice(mi.get("invoice_number_normalized") or "")
        g_tax = int(mi.get("total_tax_paise") or 0)
        g_taxable = int(mi.get("taxable_amount_paise") or 0)
        partner = None
        if inv:
            for w in wrongful_by_inv.get(inv, []):
                if id(w) in consumed_wrongful:
                    continue
                w_gstin = str(w.get("supplier_gstin") or "")
                if w_gstin == g_gstin:
                    continue  # same GSTIN handled by the matcher, not here
                if _levenshtein_distance(g_gstin, w_gstin) > 2:
                    continue
                w_taxable = int(w.get("taxable_amount_paise") or 0)
                if abs(w_taxable - g_taxable) <= amount_tolerance_paise:
                    partner = w
                    break
        if partner is not None:
            consumed_wrongful.add(id(partner))
            gstin_mismatch.append(
                {
                    "gstr_id": str(mi.get("gstr_id") or ""),
                    "pr_id": str(partner.get("id") or ""),
                    "gstr_supplier_gstin": g_gstin,
                    "pr_supplier_gstin": str(partner.get("supplier_gstin") or ""),
                    "invoice_number_normalized": mi.get("invoice_number_normalized"),
                    "invoice_date": mi.get("invoice_date"),
                    "taxable_amount_paise": int(partner.get("taxable_amount_paise") or 0),
                    "total_tax_paise": g_tax,
                    "reason": "GSTIN_MISMATCH",
                }
            )
        else:
            missed_final.append(mi)

    wrongful_final = [
        w for w in wrongful_after_conflict if id(w) not in consumed_wrongful
    ]

    return matched_final, missed_final, wrongful_final, gstin_mismatch, review_required


def _gstin_pan(gstin: str | None) -> str:
    g = (gstin or "").strip().upper()
    return g[2:12] if len(g) >= 12 else ""


def _finalize_reconciliation_result(
    state: ReconState,
    wrongful_itc_risk: list[dict],
    total_gstr: int,
    total_pr: int,
    gstin_mismatch: list[dict] | None = None,
    duplicates: list[dict] | None = None,
) -> dict:
    """Shared stats and sanity payload (same as :func:`run_bidirectional_reconciliation` output)."""
    gstin_mismatch = gstin_mismatch or []
    duplicates = duplicates or []
    matched_count = len(state.matched)
    missed_itc_count = len(state.missed_itc)
    missed_itc_amount_paise = sum(
        int(m["total_tax_paise"]) for m in state.missed_itc
    )
    wrongful_risk_count = len(wrongful_itc_risk)
    wrongful_risk_amount_paise = sum(
        int(w["total_tax_paise"]) for w in wrongful_itc_risk
    )
    gstin_mismatch_count = len(gstin_mismatch)
    gstin_mismatch_amount_paise = sum(
        int(g.get("total_tax_paise") or 0) for g in gstin_mismatch
    )
    dup_gstr = [d for d in duplicates if d.get("side") == "GSTR"]
    dup_pr = [d for d in duplicates if d.get("side") == "PR"]

    review_gstr_count = sum(1 for r in state.review_required if r.get("side") == "GSTR")
    review_pr_count = sum(1 for r in state.review_required if r.get("side") == "PR")

    missed_gstr_ids = {str(m["gstr_id"]) for m in state.missed_itc}
    state.matched_gstr_ids = {str(m["gstr_id"]) for m in state.matched}
    state.matched_pr_ids = {str(m["pr_id"]) for m in state.matched}

    sanity_passed = (
        matched_count + missed_itc_count + gstin_mismatch_count + review_gstr_count
        == total_gstr
        and matched_count + wrongful_risk_count + gstin_mismatch_count + review_pr_count
        == total_pr
        and not (state.matched_gstr_ids & missed_gstr_ids)
        and len(state.matched_pr_ids) == matched_count
    )

    if total_gstr > 0:
        match_rate_pct = round(matched_count / total_gstr * 100, 2)
    else:
        match_rate_pct = 0.0

    return {
        "matched": state.matched,
        "review_required": state.review_required,
        "missed_itc": state.missed_itc,
        "wrongful_itc_risk": wrongful_itc_risk,
        "gstin_mismatch": gstin_mismatch,
        "duplicates": duplicates,
        "stats": {
            "total_gstr": total_gstr,
            "total_pr": total_pr,
            "matched_count": matched_count,
            "review_required_count": review_gstr_count,
            "missed_itc_count": missed_itc_count,
            "missed_itc_amount_paise": missed_itc_amount_paise,
            "wrongful_risk_count": wrongful_risk_count,
            "wrongful_risk_amount_paise": wrongful_risk_amount_paise,
            "gstin_mismatch_count": gstin_mismatch_count,
            "gstin_mismatch_amount_paise": gstin_mismatch_amount_paise,
            "duplicate_count": len(duplicates),
            "duplicate_conflict_count": review_gstr_count,
            "genuine_gstr_only_count": missed_itc_count,
            "genuine_pr_only_count": wrongful_risk_count,
            "clean_matched_count": matched_count,
            "itc_at_risk_total": wrongful_risk_amount_paise,
            "missed_itc_total": missed_itc_amount_paise,
            "match_rate_pct": match_rate_pct,
            "sanity_passed": sanity_passed,
        },
    }


def run_bidirectional_reconciliation(
    gstr_records: list[dict],
    pr_records: list[dict],
    gstr_period: date | None = None,
    pr_records_by_period: dict[date, list[dict]] | None = None,
    audit_mode: bool = False,
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
            "gstin_mismatch": [],
            "duplicates": [],
            "stats": {
                "total_gstr": 0,
                "total_pr": total_pr,
                "matched_count": 0,
                "missed_itc_count": 0,
                "missed_itc_amount_paise": 0,
                "wrongful_risk_count": 0,
                "wrongful_risk_amount_paise": 0,
                "gstin_mismatch_count": 0,
                "gstin_mismatch_amount_paise": 0,
                "duplicate_count": 0,
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
    candidate_indices = build_pr_candidate_indices(pr_index)

    state = ReconState()
    process_gstr_records_chunk(
        gstr_records,
        gstr_p,
        pr_index,
        pr_index_by_period,
        state,
        gstr_by_invoice=gstr_by_invoice,
        pr_by_invoice=pr_by_invoice,
        candidate_indices=candidate_indices,
        audit_mode=audit_mode,
    )
    wrongful_itc_risk = build_wrongful_itc_risk(pr_records, state.matched_pr_ids)

    gstr_by_id = {str(g.get("id")): g for g in gstr_records}
    pr_by_id = {str(p.get("id")): p for p in pr_records}

    state.matched, state.missed_itc, wrongful_itc_risk, gstin_mismatch, review_required = resolve_orphans(
        state.matched, state.missed_itc, wrongful_itc_risk, gstr_by_id, pr_by_id
    )

    state.review_required.extend(review_required)

    return _finalize_reconciliation_result(
        state,
        wrongful_itc_risk,
        total_gstr,
        total_pr,
        gstin_mismatch=gstin_mismatch,
        duplicates=[],
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

    # Check notification preferences
    if actor_user_id:
        from app.utils.notification_prefs import should_send_notification
        if not should_send_notification(actor_user_id, "run_completed"):
            logger.info("Skipping run completed email for user %s per preferences", actor_user_id)
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
