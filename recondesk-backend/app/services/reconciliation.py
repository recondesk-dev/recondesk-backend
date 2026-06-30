"""Bidirectional GSTR ↔ PR reconciliation orchestration."""

from __future__ import annotations

import asyncio
import logging
import re
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
from app.services.gstr3b_reconciliation import _paise_to_rupees

logger = logging.getLogger(__name__)


def normalize_invoice_number(s: str | None) -> str:
    """Uppercase the string, strip all non-alphanumeric characters. Do NOT strip leading zeros."""
    if not s:
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(s).upper())



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
    for b in range(tb - 30, tb + 31):
        for pr in taxable_buckets.get(b, []):
            candidates_set[str(pr["id"])] = pr

    # Candidates by exact GSTIN and nearby tax bucket
    tax_buckets = candidate_indices.by_tax.get(gstin, {})
    for b in range(txb - 30, txb + 31):
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

    clean_matched: list[dict] = field(default_factory=list)
    review_required: list[dict] = field(default_factory=list)
    missed_itc: list[dict] = field(default_factory=list)
    
    consumed_pr_ids: set[str] = field(default_factory=set)
    consumed_gstr_ids: set[str] = field(default_factory=set)
    
    metrics: dict[str, int] = field(default_factory=lambda: defaultdict(int))



def _push_clean_matched(state, gstr_id, pr_id, score, best_result, is_late_filing=False, original_period=None, late_months=0):
    match_dict = {
        "gstr_id": str(gstr_id),
        "pr_id": str(pr_id),
        "confidence_score": score,
        "match_reasons": _match_reasons_from_result(best_result),
        "is_late_filing": is_late_filing,
        "original_period": original_period,
        "late_months": late_months,
        "match_status": "matched",
        "match_status_text": "Matched",
        "vendor_similarity_score": best_result.vendor_similarity_score,
        "identity_confidence": getattr(best_result, "identity_confidence", "High"),
        "financial_status": getattr(best_result, "financial_status", "Exact"),
        "review_reason": best_result.review_reason,
        "match_level": getattr(best_result, "level", 0),
    }
    state.clean_matched.append(match_dict)
    state.consumed_pr_ids.add(str(pr_id))
    state.consumed_gstr_ids.add(str(gstr_id))

def _push_review_required(state, gstr_id, pr_id, score, review_type, best_result=None):
    match_dict = {
        "gstr_id": str(gstr_id),
        "pr_id": str(pr_id),
        "confidence_score": score,
        "match_reasons": _match_reasons_from_result(best_result) if best_result else [],
        "match_status": "review_required",
        "match_status_text": "Review Required",
        "review_reason": review_type,
        "reason": review_type,
        "match_level": getattr(best_result, "level", 0) if best_result else 0,
        "vendor_similarity_score": getattr(best_result, "vendor_similarity_score", None) if best_result else None,
    }
    state.review_required.append(match_dict)
    if pr_id:
        state.consumed_pr_ids.add(str(pr_id))
    state.consumed_gstr_ids.add(str(gstr_id))

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
    """PHASE 1: Strict Clean Matching (L1, L2, L3)."""
    gstr_period = date(effective_gstr_period.year, effective_gstr_period.month, 1)
    for gstr_record in gstr_records:
        gstr_id = str(gstr_record["id"])
        if gstr_id in state.consumed_gstr_ids:
            continue
            
        gstin = str(gstr_record.get("supplier_gstin") or "").strip()
        
        # A.2 Pre-Phase 1 routing for missing/invalid GSTIN
        if not gstin or len(gstin) != 15:
            continue # Leave for Phase 2
            
        inv_norm = str(gstr_record.get("invoice_number_normalized") or "")
        candidates = pr_index.get(gstin, [])
        ordered_candidates = _get_narrowed_candidates(
            gstr_record,
            gstin=gstin,
            inv_norm=inv_norm,
            pr_by_invoice=pr_by_invoice,
            candidate_indices=candidate_indices,
            pr_index_candidates=candidates,
        )

        best_result: MatchResult | None = None
        best_pr: dict | None = None
        best_key: tuple[int, int, int] | None = None

        for pr_rec in ordered_candidates:
            pr_id = str(pr_rec["id"])
            if pr_id in state.consumed_pr_ids:
                continue
                
            result = match_gstr_to_pr(gstr_record, [pr_rec], gstr_by_invoice=gstr_by_invoice)
            if result is None or result.level not in (1, 2, 3) or not _accept_reconciliation_pair(gstr_record, pr_rec, result):
                continue
                
            key = _tie_key(result, gstr_record, pr_rec)
            if best_key is None or key < best_key:
                best_key = key
                best_result = result
                best_pr = pr_rec
                
            if result.level == 1:
                break # Exact match, greedily pick

        if best_result is not None and best_pr is not None:
            score = compute_match_score(best_result)
            if best_result.requires_human_review or best_result.level > 1:
                _push_review_required(state, gstr_record["id"], best_pr["id"], score, best_result.review_reason or "Amount/Date mismatch", best_result)
            else:
                _push_clean_matched(state, gstr_record["id"], best_pr["id"], score, best_result)
            continue
            
        # Cross-period check for clean match (late filing)
        inv_raw = gstr_record.get("invoice_date")
        inv_d: date | None = None
        if isinstance(inv_raw, date): inv_d = inv_raw
        elif inv_raw:
            try: inv_d = date.fromisoformat(str(inv_raw))
            except: pass
            
        periods = get_search_periods(inv_d, gstr_period)
        other_periods = sorted(periods[1:], key=lambda d: abs((gstr_period.year - d.year) * 12 + (gstr_period.month - d.month)))
        
        for period in other_periods:
            raw_candidates = pr_index_by_period.get(period, {}).get(gstin, {}).get(inv_norm, [])
            acceptable = []
            for p in raw_candidates:
                if str(p["id"]) in state.consumed_pr_ids: continue
                r = match_gstr_to_pr(gstr_record, [p], gstr_by_invoice=gstr_by_invoice)
                if r and r.level in (1, 2, 3) and _accept_reconciliation_pair(gstr_record, p, r):
                    acceptable.append((r, p))
            
            if acceptable:
                # Pick the best one
                acceptable.sort(key=lambda x: _tie_key(x[0], gstr_record, x[1]))
                best_r, best_p = acceptable[0]
                score = compute_match_score(best_r)
                late_months = (gstr_period.year - period.year) * 12 + (gstr_period.month - period.month)
                if best_r.requires_human_review or best_r.level > 1:
                    _push_review_required(state, gstr_record["id"], best_p["id"], score, best_r.review_reason or "Amount/Date mismatch", best_r)
                else:
                    _push_clean_matched(state, gstr_record["id"], best_p["id"], score, best_r, is_late_filing=True, original_period=period, late_months=late_months)
                break


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


def execute_phase2_and_3(
    gstr_records: list[dict],
    pr_records: list[dict],
    state: ReconState,
    candidate_indices: PRCandidateIndices,
    amount_tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
) -> None:
    """PHASE 2: Review Resolution & PHASE 3: True Financial Buckets."""
    
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]
    
    gstr_by_id_local = {str(g["id"]): g for g in unconsumed_gstr}
    pr_by_id_local = {str(p["id"]): p for p in unconsumed_pr}
    
    # 1. DUPLICATE_AMBIGUITY
    # Same GSTIN + same normalized invoice appears in multiple GSTR or PR rows
    dup_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for g in unconsumed_gstr:
        gst = str(g.get("supplier_gstin") or "").strip()
        inv = str(g.get("invoice_number_normalized") or "")
        if gst and len(gst) == 15 and inv:
            dup_groups[(gst, inv)].append("G_" + str(g["id"]))
    for p in unconsumed_pr:
        gst = str(p.get("supplier_gstin") or "").strip()
        inv = str(p.get("invoice_number_normalized") or "")
        if gst and len(gst) == 15 and inv:
            dup_groups[(gst, inv)].append("P_" + str(p["id"]))
            
    for (gst, inv), items in dup_groups.items():
        g_ids = [x[2:] for x in items if x.startswith("G_")]
        p_ids = [x[2:] for x in items if x.startswith("P_")]
        if (len(g_ids) > 1 and len(p_ids) > 0) or (len(g_ids) > 0 and len(p_ids) > 1):
            # It's a duplicate ambiguity!
            for gid in g_ids:
                if gid not in state.consumed_gstr_ids:
                    _push_review_required(state, gid, p_ids[0] if p_ids else "", 50, "DUPLICATE_AMBIGUITY")
            for pid in p_ids:
                state.consumed_pr_ids.add(pid)
    
    # Refresh unconsumed
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]
    pr_by_id_local = {str(p["id"]): p for p in unconsumed_pr}
    
    # Pre-index remaining PRs for fast lookup in Phase 2
    rem_pr_by_inv_norm = defaultdict(list)
    for p in unconsumed_pr:
        inv = str(p.get("invoice_number_normalized") or "")
        if inv: rem_pr_by_inv_norm[inv].append(p)
    
    from app.services.matcher import invoice_similarity, _parse_invoice_date
    # 2. GSTIN_MISMATCH & 3. TYPO_MISMATCH
    for g in unconsumed_gstr:
        gid = str(g["id"])
        gst = str(g.get("supplier_gstin") or "").strip()
        if not gst or len(gst) != 15:
            continue
            
        inv = str(g.get("invoice_number_normalized") or "")
        g_amt = g.get("total_tax_paise") or 0
        g_date = _parse_invoice_date(g)
        
        # Look for GSTIN_MISMATCH (same inv norm, amt within 2%)
        candidates_gstin_mismatch = []
        for p in rem_pr_by_inv_norm.get(inv, []):
            if str(p["id"]) in state.consumed_pr_ids: continue
            p_gst = str(p.get("supplier_gstin") or "").strip()
            if gst != p_gst:
                p_amt = p.get("total_tax_paise") or 0
                if g_amt == 0 and p_amt == 0:
                    diff_pct = 0
                elif p_amt == 0:
                    diff_pct = 1.0
                else:
                    diff_pct = abs(g_amt - p_amt) / float(p_amt)
                
                if diff_pct <= 0.02:
                    p_date = _parse_invoice_date(p)
                    date_diff = abs((g_date - p_date).days) if g_date and p_date else 0
                    if not g_date or not p_date or date_diff <= 30:
                        candidates_gstin_mismatch.append(p)
        
        if candidates_gstin_mismatch:
            if len(candidates_gstin_mismatch) > 1:
                _push_review_required(state, gid, candidates_gstin_mismatch[0]["id"], 50, "MULTIPLE_CANDIDATES")
            else:
                _push_review_required(state, gid, candidates_gstin_mismatch[0]["id"], 50, "GSTIN_MISMATCH")
            continue
            
        # 3. TYPO_MISMATCH
        # same GSTIN + amount within 5% + date within 45 days + invoice similarity > 80%
        candidates_typo = []
        for prs_in_bucket in candidate_indices.by_taxable.get(gst, {}).values():
            for p in prs_in_bucket:
                if str(p["id"]) in state.consumed_pr_ids: continue
                p_amt = p.get("total_tax_paise") or 0
                if g_amt == 0 and p_amt == 0: diff_pct = 0
                elif p_amt == 0: diff_pct = 1.0
                else: diff_pct = abs(g_amt - p_amt) / float(p_amt)
                
                if diff_pct <= 0.05:
                    p_date = _parse_invoice_date(p)
                    date_diff = abs((g_date - p_date).days) if g_date and p_date else 0
                    if not g_date or not p_date or date_diff <= 45:
                        g_inv_norm = str(g.get("invoice_number_normalized") or "")
                        p_inv_norm = str(p.get("invoice_number_normalized") or "")
                        sim = invoice_similarity(g_inv_norm, p_inv_norm)
                        if sim > 0.80 and g_inv_norm != p_inv_norm:
                            candidates_typo.append((p, sim))
                            
        if candidates_typo:
            candidates_typo.sort(key=lambda x: x[1], reverse=True)
            if len(candidates_typo) > 1 and candidates_typo[0][1] == candidates_typo[1][1]:
                _push_review_required(state, gid, candidates_typo[0][0]["id"], 60, "MULTIPLE_CANDIDATES")
            else:
                _push_review_required(state, gid, candidates_typo[0][0]["id"], 60, "TYPO_MISMATCH")
            continue

        # 4. MULTIPLE_CANDIDATES / VENDOR_FUZZY
        # same GSTIN + exact amount.
        candidates_vendor = []
        for prs_in_bucket in candidate_indices.by_taxable.get(gst, {}).values():
            for p in prs_in_bucket:
                pid = str(p["id"])
                if pid in state.consumed_pr_ids: continue
                p_amt = p.get("total_tax_paise") or 0
                if abs(g_amt - p_amt) <= TOTAL_TOLERANCE_PAISE:
                    candidates_vendor.append(p)
                    
        if candidates_vendor:
            if len(candidates_vendor) > 1:
                _push_review_required(state, gid, candidates_vendor[0]["id"], 50, "MULTIPLE_CANDIDATES")
            else:
                _push_review_required(state, gid, candidates_vendor[0]["id"], 50, "VENDOR_FUZZY")
            continue

    # 5. CREDIBLE_CANDIDATE_FALLBACK
    # Find unconsumed GSTR/PR records that still have a credible candidate
    # Those should become review_required, not final financial risk.
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr_fallback = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]
    
    for g in unconsumed_gstr:
        gid = str(g["id"])
        if gid in state.consumed_gstr_ids: continue
        
        gst = str(g.get("supplier_gstin") or "").strip()
        g_amt = g.get("total_tax_paise") or 0
        g_date = _parse_invoice_date(g)
        g_inv_norm = str(g.get("invoice_number_normalized") or "")
        
        credible_candidates = []
        for p in unconsumed_pr_fallback:
            pid = str(p["id"])
            if pid in state.consumed_pr_ids: continue
            
            p_gst = str(p.get("supplier_gstin") or "").strip()
            p_amt = p.get("total_tax_paise") or 0
            p_date = _parse_invoice_date(p)
            p_inv_norm = str(p.get("invoice_number_normalized") or "")
            
            if g_amt == 0 and p_amt == 0: diff_pct = 0
            elif p_amt == 0: diff_pct = 1.0
            else: diff_pct = abs(g_amt - p_amt) / float(p_amt)
            
            date_diff = abs((g_date - p_date).days) if g_date and p_date else 0
            
            # criteria 1: same GSTIN + amount within 5% + date within 45 days
            if gst and gst == p_gst and diff_pct <= 0.05 and (not g_date or not p_date or date_diff <= 45):
                credible_candidates.append((p, "POSSIBLE_MATCH"))
                continue
                
            # criteria 2: same normalized invoice + amount within 2% + date within 30 days
            if g_inv_norm and g_inv_norm == p_inv_norm and diff_pct <= 0.02 and (not g_date or not p_date or date_diff <= 30):
                credible_candidates.append((p, "POSSIBLE_MATCH"))
                continue
                
        if credible_candidates:
            if len(credible_candidates) > 1:
                _push_review_required(state, gid, credible_candidates[0][0]["id"], 40, "MULTIPLE_CANDIDATES")
            else:
                _push_review_required(state, gid, credible_candidates[0][0]["id"], 40, credible_candidates[0][1])
            continue

    # PHASE 3: True Financial Buckets
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    for g in unconsumed_gstr:
        ttp = g.get("total_tax_paise")
        tap = g.get("taxable_amount_paise")
        state.missed_itc.append(
            {
                "gstr_id": str(g["id"]),
                "supplier_gstin": str(g.get("supplier_gstin") or ""),
                "invoice_number_normalized": str(g.get("invoice_number_normalized") or ""),
                "invoice_date": g.get("invoice_date"),
                "taxable_amount_paise": int(tap) if tap is not None else 0,
                "total_tax_paise": int(ttp) if ttp is not None else 0,
            }
        )


def _gstin_pan(gstin: str | None) -> str:
    g = (gstin or "").strip().upper()
    return g[2:12] if len(g) >= 12 else ""


def _finalize_reconciliation_result(
    state: ReconState,
    total_gstr: int,
    total_pr: int,
    pr_records: list[dict],
    gstr_records: list[dict] = None,
) -> dict:
    matched_count = len(state.clean_matched)
    review_gstr_count = len(state.review_required)
    
    missed_itc_count = len(state.missed_itc)
    missed_itc_amount_paise = sum(
        int(x.get("total_tax_paise") or 0) for x in state.missed_itc
    )
    
    # ITC at risk = PR records not consumed
    wrongful_itc_risk = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]
    wrongful_risk_count = len(wrongful_itc_risk)
    wrongful_risk_amount_paise = sum(
        int(x.get("total_tax_paise") or 0) for x in wrongful_itc_risk
    )
    
    duplicate_pr_count = sum(1 for r in state.review_required if r.get("review_reason") == "DUPLICATE_AMBIGUITY")
    gstin_mismatch_count = sum(1 for r in state.review_required if r.get("review_reason") == "GSTIN_MISMATCH")

    sanity_passed = (
        matched_count + missed_itc_count + review_gstr_count == total_gstr
    )

    if total_gstr > 0:
        match_rate_pct = round(matched_count / total_gstr * 100, 2)
    else:
        match_rate_pct = 0.0

    l1 = sum(1 for m in state.clean_matched if m.get("match_level") == 1)
    l2 = sum(1 for m in state.clean_matched if m.get("match_level") == 2)
    l3 = sum(1 for m in state.clean_matched if m.get("match_level") == 3)
    
    gstr_by_id = {str(g["id"]): g for g in (gstr_records or [])}
    def _review_metrics(reason_match: str) -> tuple[int, float]:
        count = 0
        amt_paise = 0
        for m in state.review_required:
            if reason_match == m.get("review_reason") or (reason_match == "POSSIBLE_MATCH" and m.get("review_reason") == "POSSIBLE_MATCH"):
                count += 1
                gid = m.get("gstr_id")
                if gid and gid in gstr_by_id:
                    amt_paise += int(gstr_by_id[gid].get("total_tax_paise") or 0)
        return count, amt_paise

    review_dup, review_dup_amt = _review_metrics("DUPLICATE_AMBIGUITY")
    review_gstin, review_gstin_amt = _review_metrics("GSTIN_MISMATCH")
    review_typo, review_typo_amt = _review_metrics("TYPO_MISMATCH")
    review_vendor, review_vendor_amt = _review_metrics("VENDOR_FUZZY")
    review_mult, review_mult_amt = _review_metrics("MULTIPLE_CANDIDATES")
    review_possible, review_possible_amt = _review_metrics("POSSIBLE_MATCH")

    logger.info(f"[MATCH SUMMARY] L1: {l1}, L2: {l2}, L3: {l3}, Review_Duplicate: {review_dup}, Review_GSTIN: {review_gstin}, Review_Typo: {review_typo}, Review_Vendor: {review_vendor}, Review_Multiple: {review_mult}, Review_Possible: {review_possible}, Missed_ITC: {missed_itc_count}, ITC_at_Risk: {wrongful_risk_count}")
    logger.info(f"[MATCH AMOUNTS] Missed_ITC: {_paise_to_rupees(missed_itc_amount_paise)}, ITC_at_Risk: {_paise_to_rupees(wrongful_risk_amount_paise)}, Review_Duplicate: {_paise_to_rupees(review_dup_amt)}, Review_GSTIN: {_paise_to_rupees(review_gstin_amt)}, Review_Typo: {_paise_to_rupees(review_typo_amt)}, Review_Vendor: {_paise_to_rupees(review_vendor_amt)}, Review_Multiple: {_paise_to_rupees(review_mult_amt)}, Review_Possible: {_paise_to_rupees(review_possible_amt)}")

    return {
        "matched": state.clean_matched,
        "review_required": state.review_required,
        "missed_itc": state.missed_itc,
        "wrongful_itc_risk": wrongful_itc_risk,
        "gstin_mismatch": [], # deprecated
        "duplicates": [], # deprecated
        "stats": {
            "total_gstr": total_gstr,
            "total_pr": total_pr,
            "matched_count": matched_count,
            "clean_matched_count": matched_count,
            "review_required_count": review_gstr_count,
            "total_linked_count": matched_count + review_gstr_count,
            "missed_itc_count": missed_itc_count,
            "missed_itc_amount_paise": missed_itc_amount_paise,
            "wrongful_risk_count": wrongful_risk_count,
            "wrongful_risk_amount_paise": wrongful_risk_amount_paise,
            "itc_at_risk_count": wrongful_risk_count,
            "itc_at_risk_total": wrongful_risk_amount_paise,
            "purchase_value_at_risk_paise": 0, # Placeholder, depends on line item calculation
            
            # Legacy stats (optional, but keep for now if UI needs it)
            "gstin_mismatch_count": gstin_mismatch_count,
            "gstin_mismatch_amount_paise": 0,
            "duplicate_count": 0,
            "duplicate_pr_count": duplicate_pr_count,
            "duplicate_conflict_count": review_gstr_count,
            "genuine_gstr_only_count": missed_itc_count,
            "genuine_pr_only_count": wrongful_risk_count,
            
            "missed_itc_total": missed_itc_amount_paise,
            "match_rate_pct": match_rate_pct,
            "sanity_passed": sanity_passed,
        },
    }


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
