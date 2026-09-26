"""Bidirectional GSTR ↔ PR reconciliation orchestration."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from app.services.matching_core import THRESHOLD, choose_best_candidate, compute_match_score
from supabase import Client

from app.services.matcher import (
    INVOICE_SIMILARITY_L5_MIN,
    TOTAL_TOLERANCE_PAISE,
    MatchResult,
    are_document_types_compatible,
    build_compared_fields,
    invoice_similarity,
    is_invoice_format_variant,
    is_sequential_series_mismatch,
    match_gstr_to_pr,
    normalize_invoice,
    same_pan,
    supplier_identity_compatible,
    _parse_invoice_date,
    _RE_NOTE_IDENTIFIER,
)
from app.services.vendor_name_matcher import find_best_vendor_match, vendor_name_similarity
from app.services.gstr3b_reconciliation import _paise_to_rupees

logger = logging.getLogger(__name__)

# Exact same (GSTIN, normalized invoice) double-bookings may still drift a few
# percent in taxable/tax or by several days between the two PR entries. Keep
# these gates ONLY for exact invoice equality — never for fuzzy invoice pairs —
# so unrelated same-vendor rows cannot collapse into Duplicate Entry.
EXACT_INVOICE_DUP_TAXABLE_PCT = 0.05  # 5%
EXACT_INVOICE_DUP_TAX_PCT = 0.05  # 5%
EXACT_INVOICE_DUP_DATE_DAYS = 60
# Fuzzy invoice clones (sim ≥ 0.85): both taxable AND total tax must stay within
# this band. Never waive the tax gate on similarity alone — that mis-labeled
# distinct PR-only invoices (e.g. May INV53169 vs linked INV53161) as Duplicate
# instead of ITC at Risk when taxable happened to land within ~2%.
FUZZY_INVOICE_DUP_AMOUNT_PCT = 0.02  # 2%


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


def _taxable_paise(rec: Mapping[str, Any] | None) -> int:
    if not rec or not isinstance(rec, Mapping):
        return 0
    for k in ("taxable_amount_paise", "taxable_value_paise", "taxable_paise"):
        if k in rec and rec[k] is not None:
            return int(rec[k])
    for k in ("taxable_amount", "taxable_value", "txval", "taxable_amt"):
        if k in rec and rec[k] is not None:
            try:
                return int(round(float(rec[k]) * 100))
            except (ValueError, TypeError):
                pass
    inv_val = int(rec.get("invoice_value_paise") or rec.get("total_amount_paise") or 0)
    tot_tax = int(rec.get("total_tax_paise") or 0)
    if tot_tax == 0:
        tot_tax = (
            int(rec.get("igst_paise") or 0)
            + int(rec.get("cgst_paise") or 0)
            + int(rec.get("sgst_paise") or 0)
            + int(rec.get("cess_paise") or 0)
        )
    if inv_val > 0 and tot_tax >= 0 and inv_val >= tot_tax:
        return inv_val - tot_tax
    return 0


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
    return int(round(abs(amount_paise) / 10000.0))

@dataclass
class PRCandidateIndices:
    by_taxable: dict[str, dict[int, list[dict]]] = field(default_factory=dict)
    by_tax: dict[str, dict[int, list[dict]]] = field(default_factory=dict)
    by_invoice_norm_global: dict[str, list[dict]] = field(default_factory=dict)
    # Full PR list per GSTIN — used for format-variant scans that cross bucket boundaries
    by_gstin: dict[str, list[dict]] = field(default_factory=dict)

def build_pr_candidate_indices(pr_index: dict[str, list[dict]]) -> PRCandidateIndices:
    indices = PRCandidateIndices()
    for gstin, prs in pr_index.items():
        taxable_dict = defaultdict(list)
        tax_dict = defaultdict(list)
        for pr in prs:
            tb = _get_tax_bucket(_taxable_paise(pr))
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
        indices.by_gstin[gstin] = list(prs)
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

    g_taxable = _taxable_paise(gstr_record)
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
    # Extra PR bookings of an already-matched invoice (identical full-value
    # duplicates). Separate from review_required and wrongful_itc_risk.
    duplicate_entries: list[dict] = field(default_factory=list)
    # PR credit/debit note rows quarantined from invoice matching (no CDN↔2B
    # note matching yet). Kept visible but out of ITC at Risk / Matched.
    unmatched_notes: list[dict] = field(default_factory=list)

    consumed_pr_ids: set[str] = field(default_factory=set)
    consumed_gstr_ids: set[str] = field(default_factory=set)
    # PR rows consumed as pure data-entry duplicates of an already-matched invoice
    # (not a review item, not ITC-at-risk — just a repeat booking of one real invoice).
    duplicate_pr_ids: set[str] = field(default_factory=set)

    metrics: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def is_pr_note_quarantine(pr_rec: dict) -> bool:
    """True when a PR row was tagged as a credit/debit note during import."""
    if pr_rec.get("pr_note_quarantine"):
        return True
    # Adapter / matcher rows may only carry note_number + doc_type.
    note_no = str(pr_rec.get("note_number") or "").strip()
    if not note_no:
        return False
    doc = str(
        pr_rec.get("doc_type")
        or pr_rec.get("document_type")
        or pr_rec.get("invoice_type")
        or ""
    ).strip().upper()
    return doc in {"CREDIT_NOTE", "DEBIT_NOTE"}


def _is_note_document(rec: Mapping[str, Any] | None) -> bool:
    """True if record represents a credit or debit note."""
    if not rec:
        return False

    doc = str(
        rec.get("doc_type")
        or rec.get("document_type")
        or rec.get("invoice_type")
        or ""
    ).strip().upper()

    # Explicitly return False for ordinary invoice document types unless explicitly
    # flagged as a note (e.g. pr_note_quarantine)
    if doc in {"INVOICE", "TAX_INVOICE", "INV"}:
        if not (rec.get("is_credit_note") or rec.get("is_debit_note") or rec.get("pr_note_quarantine")):
            return False

    if doc in {"CREDIT_NOTE", "DEBIT_NOTE", "CRN", "DBN", "CN", "DN", "CREDIT", "DEBIT"}:
        return True

    sec = str(rec.get("section") or "").strip().lower()
    if sec in {"cdnr", "cdnra", "cdnur", "cdnura"}:
        return True

    if rec.get("is_credit_note") or rec.get("is_debit_note") or rec.get("pr_note_quarantine"):
        return True

    inv_raw = str(rec.get("invoice_number_raw") or rec.get("invoice_number") or "").strip()
    if inv_raw and _RE_NOTE_IDENTIFIER.search(inv_raw):
        return True

    return False


def quarantine_pr_notes(state: ReconState, pr_records: list[dict]) -> list[dict]:
    """Move unconsumed note rows out of the invoice matching pool into unmatched_notes.

    Consumes their PR ids so they never appear in ITC at Risk. Returns the
    remaining invoice PR records for matching. Safe to call more than once.
    """
    already_noted = {str(n.get("id") or "") for n in state.unmatched_notes}
    invoice_prs: list[dict] = []
    for p in pr_records:
        if not is_pr_note_quarantine(p):
            invoice_prs.append(p)
            continue
        pid = str(p.get("id") or "")
        if not pid:
            continue
        if pid in state.consumed_pr_ids:
            # Already consumed by a successful match or duplicate booking — do not quarantine
            continue
        state.consumed_pr_ids.add(pid)
        if pid in already_noted:
            continue
        doc = str(
            p.get("doc_type")
            or p.get("document_type")
            or p.get("invoice_type")
            or "DEBIT_NOTE"
        ).strip().upper()
        if doc not in {"CREDIT_NOTE", "DEBIT_NOTE"}:
            doc = "DEBIT_NOTE"
        note_no = str(p.get("note_number") or p.get("invoice_number") or "").strip()
        note_amt = p.get("note_amount_paise")
        if note_amt is None:
            note_amt = _taxable_paise(p)
        try:
            note_amt_i = int(note_amt) if note_amt is not None else None
        except (TypeError, ValueError):
            note_amt_i = None
        note_reason = (
            "PR_CREDIT_NOTE_UNMATCHED_IN_2B"
            if doc == "CREDIT_NOTE"
            else "PR_DEBIT_NOTE_PENDING_2B"
        )
        state.unmatched_notes.append(
            {
                "id": pid,
                "side": "PR",
                "reason": note_reason,
                "classification": "Notes — Not Matched",
                "document_type": doc,
                "note_number": note_no,
                "note_amount_paise": note_amt_i,
                "supplier_gstin": str(p.get("supplier_gstin") or ""),
                "supplier_name": p.get("vendor_name") or p.get("supplier_name"),
                "invoice_date": p.get("invoice_date"),
                "match_status": "NOTE_NOT_MATCHED",
            }
        )
        already_noted.add(pid)
    if state.unmatched_notes:
        logger.info(
            "[PR_NOTES] Quarantined %d credit/debit note row(s) from invoice matching",
            len(state.unmatched_notes),
        )
    return invoice_prs



def _push_clean_matched(
    state,
    gstr_id,
    pr_id,
    score,
    best_result,
    is_late_filing=False,
    original_period=None,
    late_months=0,
    match_confidence=None,
    gstr_rec: "dict | None" = None,
    pr_rec: "dict | None" = None,
):
    # Persist abs(GSTR taxable − PR taxable) so the decision layer can render
    # L2/L3 ``{diff}`` correctly. Without this, populate_decisions defaulted
    # missing amount_difference_paise to 0 and every FUZZY Matched export row
    # showed "amount differs by ₹0.00".
    taxable_diff: int = 0
    g_taxable: int | None = None
    p_taxable: int | None = None
    if gstr_rec is not None and pr_rec is not None:
        g_taxable = _taxable_paise(gstr_rec)
        p_taxable = _taxable_paise(pr_rec)
        taxable_diff = abs(abs(g_taxable) - abs(p_taxable))

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
        "match_confidence": match_confidence,  # invoice_similarity score for L5/fuzzy matches
        "compared_fields": list(getattr(best_result, "compared_fields", None) or []),
        "taxable_diff_paise": taxable_diff,
        "amount_difference_paise": taxable_diff,
    }
    g_doc = str((gstr_rec or {}).get("doc_type") or "").strip().upper()
    p_doc = str((pr_rec or {}).get("doc_type") or (pr_rec or {}).get("document_type") or "").strip().upper()
    if g_doc in ("CREDIT_NOTE", "DEBIT_NOTE") or p_doc in ("CREDIT_NOTE", "DEBIT_NOTE"):
        match_dict["doc_type"] = g_doc or p_doc
        match_dict["is_credit_note"] = (g_doc == "CREDIT_NOTE" or p_doc == "CREDIT_NOTE")
    if g_taxable is not None:
        match_dict["gstr_taxable_amount_paise"] = g_taxable
    if p_taxable is not None:
        match_dict["pr_taxable_amount_paise"] = p_taxable
    if gstr_rec is not None:
        g_inv = str(gstr_rec.get("invoice_number") or "").strip()
        if g_inv:
            match_dict["gstr_invoice_number"] = g_inv
            match_dict["invoice_number"] = g_inv
    if pr_rec is not None:
        p_inv = str(pr_rec.get("invoice_number") or "").strip()
        if p_inv:
            match_dict["pr_invoice_number"] = p_inv
    state.clean_matched.append(match_dict)
    state.consumed_pr_ids.add(str(pr_id))
    state.consumed_gstr_ids.add(str(gstr_id))

def _push_review_required(
    state,
    gstr_id,
    pr_id,
    score,
    review_type,
    best_result=None,
    gstr_rec: "dict | None" = None,
    pr_rec: "dict | None" = None,
    note: str | None = None,
    match_confidence: float | None = None,
):
    # Compute the absolute invoice-value diff (paise) so it can be stored and
    # later shown in the Review Required → Discrepancy / Reason column.
    # Previously this was never stored, causing the column to always display ₹0.
    #
    # This must be based on the TOTAL invoice value (taxable + total tax) on each
    # side, not taxable_amount_paise alone: a real, deliberate mismatch can live
    # entirely in the tax component (e.g. a wrong GST rate) while the taxable value
    # matches on both sides. Diffing taxable alone made such genuine discrepancies
    # silently report ₹0 (a false negative) even though this API-level value is
    # only a last-resort fallback (see _pair_tax_diff_paise in reconciliation_api.py,
    # which recomputes live from the DB and is what the UI actually reads).
    taxable_diff: int = 0
    if gstr_rec is not None and pr_rec is not None:
        g_taxable = _taxable_paise(gstr_rec)
        p_taxable = _taxable_paise(pr_rec)
        g_tt = int(gstr_rec.get("total_tax_paise") or 0)
        p_tt = int(pr_rec.get("total_tax_paise") or 0)
        g_tot = int(gstr_rec.get("invoice_value_paise") or gstr_rec.get("total_amount_paise") or (g_taxable + g_tt))
        p_tot = int(pr_rec.get("total_amount_paise") or pr_rec.get("invoice_value_paise") or (p_taxable + p_tt))
        taxable_diff = abs(g_tot - p_tot)

    compared_fields = list(getattr(best_result, "compared_fields", None) or [])
    if not compared_fields and gstr_rec is not None and pr_rec is not None:
        compared_fields = build_compared_fields(
            gstr_rec,
            pr_rec,
            invoice_sim_override=match_confidence,
        )

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
        "taxable_diff_paise": taxable_diff,
        "note": note,
        "match_confidence": match_confidence,  # invoice_similarity score for L5/fuzzy matches
        "compared_fields": compared_fields or None,
    }
    g_doc = str((gstr_rec or {}).get("doc_type") or "").strip().upper()
    p_doc = str((pr_rec or {}).get("doc_type") or (pr_rec or {}).get("document_type") or "").strip().upper()
    if g_doc in ("CREDIT_NOTE", "DEBIT_NOTE") or p_doc in ("CREDIT_NOTE", "DEBIT_NOTE"):
        match_dict["doc_type"] = g_doc or p_doc
        match_dict["is_credit_note"] = (g_doc == "CREDIT_NOTE" or p_doc == "CREDIT_NOTE")
    if gstr_rec is not None:
        match_dict["gstr_invoice_date"] = gstr_rec.get("invoice_date")
    if pr_rec is not None:
        match_dict["pr_invoice_date"] = pr_rec.get("invoice_date")
    if gstr_rec is not None and gstr_rec.get("gstin_format_invalid"):
        match_dict["gstin_format_invalid"] = True
    if best_result is not None:
        if getattr(best_result, "decision_why", None):
            match_dict["decision_why"] = best_result.decision_why
        if getattr(best_result, "decision_what", None):
            match_dict["decision_what"] = best_result.decision_what
        if getattr(best_result, "decision_next", None):
            match_dict["decision_next"] = best_result.decision_next
    state.review_required.append(match_dict)
    if pr_id:
        state.consumed_pr_ids.add(str(pr_id))
    state.consumed_gstr_ids.add(str(gstr_id))


def _is_note_prefix_variant(a_norm: str | None, b_norm: str | None) -> bool:
    """True when two note numbers differ only by note prefix (CN, CRN, DN, DBN) and/or leading zeros."""
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm:
        return True

    def _strip_prefix(s: str) -> str:
        s = str(s).upper()
        for pfx in ("CRN", "CDN", "DBN", "CN", "DN"):
            if s.startswith(pfx):
                s = s[len(pfx):]
                break
        return s.lstrip("0")

    sa = _strip_prefix(a_norm)
    sb = _strip_prefix(b_norm)
    if sa and sb and sa == sb:
        return True
    return False


def execute_credit_note_reconciliation(
    gstr_records: list[dict],
    pr_records: list[dict],
    state: ReconState,
    amount_tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
) -> None:
    """Dedicated bilateral Credit Note (CDNR) & Debit Note reconciliation phase.

    Executes after Phase 1 and before Phase 2/3 / residual quarantine.
    Reconciles GSTR-2B CDNR notes with PR credit/debit notes across four pathways:
      - Pathway A: Exact Note Number match (GSTR nt_num == PR note_number).
      - Pathway B: GSTR Note Number matches PR Invoice Number.
      - Pathway C: Cross-reference original invoice (GSTR oinum == PR invoice_number or PR original_invoice).
      - Pathway D: Format-variant / Prefix-stripped note match.
    Enforces semantic direction (are_document_types_compatible) and statutory ₹1 tolerance.
    Clean matches are added to state.clean_matched with is_credit_note=True and consumed.
    Matches with exact note number but amount mismatch exceeding ₹1 are routed to
    state.review_required so they do not falsely drop into unmatched notes or missed ITC.
    """
    unconsumed_gstr = [
        g for g in gstr_records
        if str(g.get("id") or "") not in state.consumed_gstr_ids
        and _is_note_document(g)
    ]
    if not unconsumed_gstr:
        return

    unconsumed_pr = [
        p for p in pr_records
        if str(p.get("id") or "") not in state.consumed_pr_ids
        and (is_pr_note_quarantine(p) or _is_note_document(p))
    ]
    if not unconsumed_pr:
        return

    pr_by_gstin: dict[str, list[dict]] = defaultdict(list)
    for p in unconsumed_pr:
        gst = str(p.get("supplier_gstin") or p.get("gstin") or "").strip().upper()
        if gst:
            pr_by_gstin[gst].append(p)

    for g in unconsumed_gstr:
        gid = str(g.get("id") or "")
        if gid in state.consumed_gstr_ids:
            continue

        g_gst = str(g.get("supplier_gstin") or g.get("gstin") or "").strip().upper()
        if not g_gst:
            continue

        candidates = pr_by_gstin.get(g_gst, [])
        if not candidates:
            candidates = [
                p for p in unconsumed_pr
                if str(p.get("id") or "") not in state.consumed_pr_ids
                and supplier_identity_compatible(g, p)[0]
            ]

        if not candidates:
            continue

        g_inv_raw = str(g.get("invoice_number_raw") or g.get("invoice_number") or "").strip()
        g_note_norm = normalize_invoice(g.get("invoice_number_normalized") or g_inv_raw)
        g_orig_raw = str(
            g.get("original_invoice_number_raw")
            or g.get("original_invoice_number")
            or g.get("oinum")
            or g.get("ont_num")
            or ""
        ).strip()
        g_orig_norm = (
            normalize_invoice(g.get("original_invoice_number_normalized") or g_orig_raw)
            if (g.get("original_invoice_number_normalized") or g_orig_raw)
            else None
        )

        g_tax = int(g.get("total_tax_paise") or 0)
        g_taxable = _taxable_paise(g)

        best_match = None
        best_priority = 999
        best_diff = float("inf")

        for p in candidates:
            pid = str(p.get("id") or "")
            if not pid or pid in state.consumed_pr_ids:
                continue

            # 1. Semantic Direction Gate
            compat, _ = are_document_types_compatible(g, p)
            if not compat:
                continue

            # 2. Supplier Identity Gate
            id_compat, _, _ = supplier_identity_compatible(g, p)
            if not id_compat:
                continue

            p_note_raw = str(p.get("note_number") or "").strip()
            p_note_norm = normalize_invoice(p_note_raw) if p_note_raw else None

            p_inv_raw = str(p.get("invoice_number_raw") or p.get("invoice_number") or "").strip()
            p_inv_norm = (
                normalize_invoice(p.get("invoice_number_normalized") or p_inv_raw)
                if (p.get("invoice_number_normalized") or p_inv_raw)
                else None
            )

            p_orig_raw = str(
                p.get("original_invoice_number_raw")
                or p.get("original_invoice_number")
                or p.get("original_invoice")
                or p.get("orig_inv_num")
                or p.get("against_invoice_number")
                or ""
            ).strip()
            p_orig_norm = (
                normalize_invoice(p.get("original_invoice_number_normalized") or p_orig_raw)
                if (p.get("original_invoice_number_normalized") or p_orig_raw)
                else None
            )

            pathway = None
            priority = 999
            pathway_desc = ""

            # Pathway A: Exact Note Number Match
            if g_note_norm and p_note_norm and g_note_norm == p_note_norm:
                pathway = "PATHWAY_A_EXACT_NOTE_NUMBER"
                priority = 1
                pathway_desc = f"Exact note number {g_inv_raw}"
            # Pathway B: GSTR Note Number matches PR Invoice Number
            elif g_note_norm and p_inv_norm and g_note_norm == p_inv_norm:
                pathway = "PATHWAY_B_NOTE_TO_INVOICE"
                priority = 2
                pathway_desc = f"Note number {g_inv_raw} matches PR invoice number"
            # Pathway C: Cross-reference original invoice
            elif (
                (g_orig_norm and p_inv_norm and g_orig_norm == p_inv_norm)
                or (g_orig_norm and p_orig_norm and g_orig_norm == p_orig_norm)
                or (p_orig_norm and g_note_norm and p_orig_norm == g_note_norm)
            ):
                pathway = "PATHWAY_C_ORIGINAL_INVOICE_CROSS_REF"
                priority = 3
                pathway_desc = f"Original invoice cross-reference ({g_orig_raw or p_orig_raw})"
            # Pathway D: Format-variant / prefix-stripped note match
            elif (
                is_invoice_format_variant(g_inv_raw, p_note_raw or p_inv_raw)
                or _is_note_prefix_variant(g_note_norm, p_note_norm or p_inv_norm)
            ):
                pathway = "PATHWAY_D_FORMAT_VARIANT_NOTE"
                priority = 4
                pathway_desc = f"Format-variant note {g_inv_raw} ~ {p_note_raw or p_inv_raw}"

            if not pathway:
                continue

            p_tax = int(p.get("total_tax_paise") or 0)
            p_taxable = _taxable_paise(p)
            tax_diff = abs(abs(g_tax) - abs(p_tax))
            taxable_diff = abs(abs(g_taxable) - abs(p_taxable))

            if g_tax != 0 or p_tax != 0:
                is_tolerance_match = (tax_diff <= amount_tolerance_paise)
                primary_diff = tax_diff
            else:
                is_tolerance_match = (taxable_diff <= amount_tolerance_paise)
                primary_diff = taxable_diff

            if priority < best_priority or (priority == best_priority and primary_diff < best_diff):
                best_match = (p, pathway, priority, pathway_desc, is_tolerance_match, tax_diff, taxable_diff)
                best_priority = priority
                best_diff = primary_diff

        if best_match:
            p_best, pathway, priority, pathway_desc, is_tol_match, tax_diff, taxable_diff = best_match
            pid = str(p_best["id"])

            if is_tol_match:
                m_level = 1 if priority in (1, 2) else 2
                score = 100 if m_level == 1 else 90
                mr = MatchResult(
                    level=m_level,
                    matched=True,
                    confidence=score,
                    requires_human_review=False,
                    decision_what="Matched Credit/Debit Note",
                    decision_why=f"Bilateral note reconciliation: {pathway_desc}",
                    decision_next="Auto-accepted",
                    identity_confidence="High",
                    financial_status="Exact" if (tax_diff == 0 and taxable_diff == 0) else "Tolerance",
                    compared_fields=build_compared_fields(g, p_best),
                )
                _push_clean_matched(
                    state=state,
                    gstr_id=gid,
                    pr_id=pid,
                    score=score,
                    best_result=mr,
                    gstr_rec=g,
                    pr_rec=p_best,
                )
            elif priority in (1, 2):
                mr = MatchResult(
                    level=4,
                    matched=False,
                    confidence=70,
                    requires_human_review=True,
                    decision_what="Review Credit/Debit Note Amount",
                    decision_why=f"Note numbers match ({pathway_desc}) but tax differs by ₹{tax_diff/100:.2f}",
                    decision_next="CA review required for note value discrepancy",
                    review_reason="AMOUNT_MISMATCH",
                    compared_fields=build_compared_fields(g, p_best),
                )
                _push_review_required(
                    state=state,
                    gstr_id=gid,
                    pr_id=pid,
                    score=70,
                    review_type="AMOUNT_MISMATCH",
                    best_result=mr,
                    gstr_rec=g,
                    pr_rec=p_best,
                )


def _dup_group_key(gstin: str | None, inv_norm: str | None) -> tuple[str, str] | None:
    gst = str(gstin or "").strip()
    inv = str(inv_norm or "")
    if gst and len(gst) == 15 and inv:
        return (gst, inv)
    return None


def _duplicate_pair_cost(g: dict, p: dict) -> tuple[int, int]:
    """(amount_diff_paise, date_diff_days) — lower is a better candidate pairing."""
    g_amt = int(g.get("total_tax_paise") or _taxable_paise(g) or 0)
    p_amt = int(p.get("total_tax_paise") or _taxable_paise(p) or 0)
    gd = _parse_invoice_date_safe(g)
    pd = _parse_invoice_date_safe(p)
    date_diff = abs((gd - pd).days) if gd and pd else 0
    return (abs(g_amt - p_amt), date_diff)


def _parse_invoice_date_safe(rec: dict) -> date | None:
    from app.services.matcher import _parse_invoice_date
    return _parse_invoice_date(rec)


def _is_deterministic_duplicate_group(g_ids: list[str], p_ids: list[str], gstr_by_id: dict, pr_by_id: dict) -> bool:
    """True when every GSTR row in an ambiguous-key group has one unambiguous best PR
    partner (no ties) and no two GSTR rows share the same best partner. In that case
    the group is NOT a genuine duplicate conflict — amount/date alone disambiguate the
    pairing, so Phase 1's normal greedy matching is left to resolve it record-by-record.
    """
    if len(g_ids) <= 1 or not p_ids:
        return True
    best_for_g: dict[str, str] = {}
    for gid in g_ids:
        g = gstr_by_id[gid]
        ranked = sorted(p_ids, key=lambda pid: _duplicate_pair_cost(g, pr_by_id[pid]))
        best_cost = _duplicate_pair_cost(g, pr_by_id[ranked[0]])
        tied = [pid for pid in p_ids if _duplicate_pair_cost(g, pr_by_id[pid]) == best_cost]
        if len(tied) > 1:
            return False
        best_for_g[gid] = ranked[0]
    return len(set(best_for_g.values())) == len(best_for_g)


def _is_multiline_pr_split(
    g: dict,
    p_ids: list[str],
    pr_by_id: dict[str, dict],
    *,
    tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
) -> bool:
    """True when multiple PR rows are a tax-rate / HSN line split of one GSTR invoice.

    Purchase registers often book one invoice as several spreadsheet rows (one per
    tax rate). GSTR-2B keeps a single ``inum`` with summed ``itms``. When the PR
    rows' taxable + tax amounts sum to the GSTR invoice totals (within rounding)
    and no single PR row already equals the full GSTR invoice, treat the group as
    one multi-line booking — not a duplicate data-entry conflict.
    """
    if len(p_ids) < 2:
        return False
    g_taxable = _taxable_paise(g)
    g_tax = int(g.get("total_tax_paise") or 0)
    if g_tax == 0:
        g_tax = (
            int(g.get("igst_paise") or 0)
            + int(g.get("cgst_paise") or 0)
            + int(g.get("sgst_paise") or 0)
            + int(g.get("cess_paise") or 0)
        )
    prs = [pr_by_id[pid] for pid in p_ids]
    sum_taxable = sum(_taxable_paise(p) for p in prs)
    sum_tax = sum(int(p.get("total_tax_paise") or 0) for p in prs)
    if abs(sum_taxable - g_taxable) > tolerance_paise:
        return False
    if abs(sum_tax - g_tax) > tolerance_paise:
        return False
    # Pure duplicates: at least one PR row already equals the full invoice.
    for p in prs:
        p_taxable = _taxable_paise(p)
        p_tax = int(p.get("total_tax_paise") or 0)
        if (
            abs(p_taxable - g_taxable) <= tolerance_paise
            and abs(p_tax - g_tax) <= tolerance_paise
        ):
            return False
    return True


def _exact_invoice_amounts_near(
    a_taxable: int,
    a_tax: int,
    b_taxable: int,
    b_tax: int,
    *,
    tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
    taxable_pct: float = EXACT_INVOICE_DUP_TAXABLE_PCT,
    tax_pct: float = EXACT_INVOICE_DUP_TAX_PCT,
) -> bool:
    """Amount proximity for exact-(GSTIN, invoice) double-bookings only."""
    if (
        abs(a_taxable - b_taxable) <= tolerance_paise
        and abs(a_tax - b_tax) <= tolerance_paise
    ):
        return True
    return _pct_within(a_taxable, b_taxable, taxable_pct) and (
        abs(a_tax - b_tax) <= tolerance_paise or _pct_within(a_tax, b_tax, tax_pct)
    )


def _is_true_duplicate_pr_group(
    g: dict,
    p_ids: list[str],
    pr_by_id: dict[str, dict],
    *,
    tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
) -> bool:
    """True when every PR row is a full-value copy of the GSTR invoice.

    Distinguishes true data-entry duplicates from mixed groups (e.g. one full
    booking plus an unrelated partial row sharing the same invoice number).
    Uses magnitude compare so credit-note / CDNR sign differences still count.
    Allows small %-drift so double-bookings with rounding typos still count.
    """
    if len(p_ids) < 2:
        return False
    g_taxable = abs(_taxable_paise(g))
    g_tax = abs(int(g.get("total_tax_paise") or 0))
    for pid in p_ids:
        p = pr_by_id[pid]
        p_taxable = abs(_taxable_paise(p))
        p_tax = abs(int(p.get("total_tax_paise") or 0))
        if not _exact_invoice_amounts_near(
            g_taxable, g_tax, p_taxable, p_tax, tolerance_paise=tolerance_paise
        ):
            return False
    return True


def _flag_pr_to_pr_clone_duplicates(
    state: ReconState,
    *,
    gstr_id: str,
    g: dict,
    p_ids: list[str],
    pr_by_id: dict[str, dict],
    tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
) -> int:
    """Flag identical PR↔PR clones as Duplicate Entry even when they differ from GSTR.

    Extreme / messy books often book the same invoice twice with identical PR
    amounts that still drift from GSTR-2B (→ Review Required on the survivor).
    ``_is_true_duplicate_pr_group`` misses those because it requires every PR to
    match the GSTR full value — the extras then leaked into ITC at Risk.

    Clusters remaining PRs by absolute (taxable, total_tax) within tolerance
    or a small %, keeps one canonical per cluster (closest to GSTR), flags the
    rest. Caller already grouped by exact (GSTIN, invoice) key.
    Returns how many extras were flagged.
    """
    remaining = [pid for pid in p_ids if str(pid) not in state.consumed_pr_ids]
    if len(remaining) < 2:
        return 0

    # Greedy clusters: each PR joins the first cluster whose representative is
    # within exact-invoice amount proximity (₹1 or small %).
    clusters: list[list[str]] = []
    for pid in remaining:
        p = pr_by_id[pid]
        p_taxable = abs(_taxable_paise(p))
        p_tax = abs(int(p.get("total_tax_paise") or 0))
        placed = False
        for cluster in clusters:
            rep = pr_by_id[cluster[0]]
            r_taxable = abs(_taxable_paise(rep))
            r_tax = abs(int(rep.get("total_tax_paise") or 0))
            if _exact_invoice_amounts_near(
                p_taxable,
                p_tax,
                r_taxable,
                r_tax,
                tolerance_paise=tolerance_paise,
            ):
                cluster.append(pid)
                placed = True
                break
        if not placed:
            clusters.append([pid])

    flagged = 0
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        canonical = _select_canonical_pr_id(g, cluster, pr_by_id)
        for pid in cluster:
            if pid == canonical:
                continue
            _push_duplicate_entry(
                state,
                extra_pr_id=pid,
                matched_pr_id=canonical,
                gstr_id=gstr_id,
                pr_rec=pr_by_id[pid],
            )
            flagged += 1
    return flagged


def _invoice_digit_core(s: str | None) -> str:
    """Digits-only spine of an invoice number (for mangled-prefix twin checks)."""
    return re.sub(r"[^0-9]", "", str(s or ""))


def flag_fuzzy_duplicates_of_linked_prs(
    state: ReconState,
    pr_records: list[dict],
    *,
    invoice_sim_min: float = 0.75,
    amount_tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
    date_tolerance_days: int = 30,
) -> int:
    """Post-match sweep: flag unconsumed PRs that clone an already-linked PR.

    Covers two gaps the exact-key prepass cannot see:

    1. **Same invoice, no GSTR on that key** — the canonical PR matched a GSTR
       via format-variant / typo / strong-twin, so prepass never grouped the
       extra with a GSTR and left it to become ITC at Risk.
    2. **Mangled invoice extras** — e.g. ``NIV455325`` vs linked ``INV455325``
       with identical GSTIN + taxable + total tax + date.

    Requires same GSTIN, invoice similarity ≥ ``invoice_sim_min`` (or exact
    norm), date within ``date_tolerance_days``, and amount proximity:
    exact-invoice pairs use the wider exact-invoice gates; fuzzy pairs need
    taxable *and* total tax within ₹1 or ``FUZZY_INVOICE_DUP_AMOUNT_PCT``
    (high-sim alone must not waive the tax check).
    Routes to Duplicate Entry (never ITC at Risk). Returns extras flagged.
    """
    from app.services.matcher import _parse_invoice_date, is_invoice_format_variant

    linked_meta: dict[str, str] = {}  # pr_id -> gstr_id (may be "")
    for row in list(state.clean_matched) + list(state.review_required):
        pid = str(row.get("pr_id") or row.get("matched_pr_id") or "").strip()
        if not pid or pid == "None":
            continue
        gid = str(row.get("gstr_id") or "").strip()
        if gid == "None":
            gid = ""
        # Prefer a row that carries a real gstr_id when the same PR appears twice.
        if pid not in linked_meta or (gid and not linked_meta[pid]):
            linked_meta[pid] = gid

    if not linked_meta:
        return 0

    pr_by_id = {str(p["id"]): p for p in pr_records}
    by_gstin_taxable: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for pid in linked_meta:
        p = pr_by_id.get(pid)
        if not p:
            continue
        gst = str(p.get("supplier_gstin") or "").strip().upper()
        if not gst:
            continue
        by_gstin_taxable[(gst, _taxable_paise(p))].append(p)

    # Also index all linked PRs by GSTIN for the high-sim / 2% taxable path
    # (when total_tax drifts beyond paise tolerance on messy clones).
    linked_by_gstin: dict[str, list[dict]] = defaultdict(list)
    for pid in linked_meta:
        p = pr_by_id.get(pid)
        if not p:
            continue
        gst_l = str(p.get("supplier_gstin") or "").strip().upper()
        if gst_l:
            linked_by_gstin[gst_l].append(p)

    flagged = 0
    # Deterministic order so ties are stable across runs.
    for p in sorted(pr_records, key=lambda r: str(r.get("id") or "")):
        pid = str(p["id"])
        if pid in state.consumed_pr_ids:
            continue
        gst = str(p.get("supplier_gstin") or "").strip().upper()
        if not gst:
            continue
        tax = _taxable_paise(p)
        tot = abs(int(p.get("total_tax_paise") or 0))
        inv = str(p.get("invoice_number_normalized") or "")
        if not inv:
            continue
        p_date = _parse_invoice_date(p)

        best = None
        candidates = list(by_gstin_taxable.get((gst, tax), []))
        for tkey in (tax - 100, tax + 100):
            if tkey >= 0:
                candidates.extend(by_gstin_taxable.get((gst, tkey), []))
        # High-sim path: scan all linked same-GSTIN rows (taxable within 2%).
        seen_cids = {str(c["id"]) for c in candidates}
        for cp in linked_by_gstin.get(gst, []):
            cid = str(cp["id"])
            if cid not in seen_cids:
                candidates.append(cp)
                seen_cids.add(cid)

        for cp in candidates:
            cid = str(cp["id"])
            if cid == pid:
                continue
            c_tax = abs(_taxable_paise(cp))
            c_tot = abs(int(cp.get("total_tax_paise") or 0))
            c_inv = str(cp.get("invoice_number_normalized") or "")
            if not c_inv:
                continue
            exact_inv = c_inv == inv
            sim = 1.0 if exact_inv else invoice_similarity(inv, c_inv)
            if not exact_inv and sim < invoice_sim_min:
                ok_digit, _ = _invoice_twin_similarity_ok(
                    inv, c_inv, sim_min=invoice_sim_min, digit_dist_max=2
                )
                if not ok_digit:
                    continue
            # Exact invoice: allow wider amount/date drift (double-booking
            # typos). Fuzzy invoice: keep the stricter 2%/₹1 + 30d gates on
            # *both* taxable and total tax (do not waive tax on sim alone).
            if exact_inv:
                if not _exact_invoice_amounts_near(
                    c_tax,
                    c_tot,
                    abs(tax),
                    tot,
                    tolerance_paise=amount_tolerance_paise,
                ):
                    continue
                max_date_days = EXACT_INVOICE_DUP_DATE_DAYS
            else:
                taxable_ok = abs(c_tax - abs(tax)) <= amount_tolerance_paise or (
                    sim >= 0.85
                    and _pct_within(c_tax, abs(tax), FUZZY_INVOICE_DUP_AMOUNT_PCT)
                )
                if not taxable_ok:
                    continue
                tax_ok = abs(c_tot - tot) <= amount_tolerance_paise or (
                    sim >= 0.85
                    and _pct_within(c_tot, tot, FUZZY_INVOICE_DUP_AMOUNT_PCT)
                )
                if not tax_ok:
                    continue
                max_date_days = date_tolerance_days
            c_date = _parse_invoice_date(cp)
            if p_date and c_date and abs((p_date - c_date).days) > max_date_days:
                continue
            if best is None or sim > best[0] or (sim == best[0] and cid < str(best[1]["id"])):
                best = (sim, cp)

        if best is None:
            continue
        _sim, cp = best
        _push_duplicate_entry(
            state,
            extra_pr_id=pid,
            matched_pr_id=str(cp["id"]),
            gstr_id=linked_meta.get(str(cp["id"]), ""),
            pr_rec=p,
        )
        flagged += 1

    if flagged:
        logger.info(
            "[FUZZY_DUPLICATE] Flagged %d unconsumed PR clone(s) of linked invoices "
            "as Duplicate Entry (not ITC at Risk)",
            flagged,
        )
    return flagged


def flag_fuzzy_pr_peer_duplicates(
    state: ReconState,
    pr_records: list[dict],
    *,
    invoice_sim_min: float = 0.75,
    taxable_pct: float = 0.02,
    date_tolerance_days: int = 45,
) -> int:
    """Flag PR↔PR clones among unconsumed rows (neither side linked to GSTR).

    When both bookings of a fuzzed duplicate sit outside GSTR linking, the
    linked-only sweep cannot see them and both would become ITC at Risk.
    Keep one canonical survivor (earliest date, then lowest id); extras →
    Duplicate Entry.

    Exact same invoice number uses the wider exact-invoice amount/date gates;
    fuzzy peers keep the stricter digit-spine + 2% path.
    """
    from app.services.matcher import _parse_invoice_date

    by_gstin: dict[str, list[dict]] = defaultdict(list)
    for p in pr_records:
        pid = str(p["id"])
        if pid in state.consumed_pr_ids:
            continue
        gst = str(p.get("supplier_gstin") or "").strip().upper()
        inv = str(p.get("invoice_number_normalized") or "")
        if not gst or not inv:
            continue
        by_gstin[gst].append(p)

    flagged = 0
    for gst, plist in by_gstin.items():
        if len(plist) < 2:
            continue
        # Deterministic order for greedy clustering.
        ordered = sorted(
            plist,
            key=lambda r: (
                str(_parse_invoice_date(r) or date.max),
                str(r.get("id") or ""),
            ),
        )
        claimed: set[str] = set()
        for i, canon in enumerate(ordered):
            cid = str(canon["id"])
            if cid in state.consumed_pr_ids or cid in claimed:
                continue
            c_inv = str(canon.get("invoice_number_normalized") or "")
            c_tax = abs(_taxable_paise(canon))
            c_tot = abs(int(canon.get("total_tax_paise") or 0))
            c_date = _parse_invoice_date(canon)
            for extra in ordered[i + 1 :]:
                eid = str(extra["id"])
                if eid in state.consumed_pr_ids or eid in claimed:
                    continue
                e_inv = str(extra.get("invoice_number_normalized") or "")
                if not e_inv:
                    continue
                ok, sim = _peer_pr_invoice_clone_ok(c_inv, e_inv)
                if not ok:
                    continue
                e_tax = abs(_taxable_paise(extra))
                e_tot = abs(int(extra.get("total_tax_paise") or 0))
                exact_inv = c_inv == e_inv
                if exact_inv:
                    if not _exact_invoice_amounts_near(c_tax, c_tot, e_tax, e_tot):
                        continue
                    max_date_days = EXACT_INVOICE_DUP_DATE_DAYS
                else:
                    if not (
                        abs(c_tax - e_tax) <= TOTAL_TOLERANCE_PAISE
                        or _pct_within(c_tax, e_tax, taxable_pct)
                    ):
                        continue
                    # Mirror linked-fuzzy: total tax must also be near, or
                    # distinct invoices with coincidental taxable collapse.
                    if not (
                        abs(c_tot - e_tot) <= TOTAL_TOLERANCE_PAISE
                        or _pct_within(c_tot, e_tot, taxable_pct)
                    ):
                        continue
                    max_date_days = date_tolerance_days
                e_date = _parse_invoice_date(extra)
                if c_date and e_date and abs((c_date - e_date).days) > max_date_days:
                    continue
                _push_duplicate_entry(
                    state,
                    extra_pr_id=eid,
                    matched_pr_id=cid,
                    gstr_id="",
                    pr_rec=extra,
                )
                claimed.add(eid)
                flagged += 1
                logger.debug(
                    "[FUZZY_PEER_DUPLICATE] PR %s clone of unlinked PR %s "
                    "(sim=%.3f) → Duplicate Entry",
                    eid,
                    cid,
                    sim,
                )

    if flagged:
        logger.info(
            "[FUZZY_PEER_DUPLICATE] Flagged %d unconsumed PR↔PR clone(s) as "
            "Duplicate Entry",
            flagged,
        )
    return flagged


def _push_duplicate_entry(
    state: ReconState,
    *,
    extra_pr_id: str,
    matched_pr_id: str,
    gstr_id: str,
    pr_rec: dict,
) -> None:
    """Flag an extra identical PR booking as Duplicate Entry (not ITC at Risk)."""
    state.consumed_pr_ids.add(str(extra_pr_id))
    state.duplicate_pr_ids.add(str(extra_pr_id))
    state.duplicate_entries.append(
        {
            "id": str(extra_pr_id),
            "side": "PR",
            "reason": "DUPLICATE_ENTRY",
            "classification": "Duplicate Entry",
            "matched_pr_id": str(matched_pr_id),
            "gstr_id": str(gstr_id),
            "supplier_gstin": str(pr_rec.get("supplier_gstin") or ""),
            "invoice_number_normalized": str(
                pr_rec.get("invoice_number_normalized") or ""
            ),
            "invoice_date": pr_rec.get("invoice_date"),
            "taxable_amount_paise": int(pr_rec.get("taxable_amount_paise") or 0),
            "total_tax_paise": int(pr_rec.get("total_tax_paise") or 0),
        }
    )


def _select_canonical_pr_id(
    g: dict,
    p_ids: list[str],
    pr_by_id: dict[str, dict],
) -> str:
    """Deterministically pick the canonical PR for a true-duplicate group.

    Primary key: lowest ``_duplicate_pair_cost`` (amount then date closeness).
    Tie-break: lexicographically lowest ``pr_id`` so the choice is stable
    regardless of input order.
    """
    ranked = sorted(
        p_ids,
        key=lambda pid: (_duplicate_pair_cost(g, pr_by_id[pid]), str(pid)),
    )
    return ranked[0]


def _push_multiline_clean_match(
    state: ReconState,
    gid: str,
    p_ids: list[str],
    gstr_by_id: dict[str, dict],
    pr_by_id: dict[str, dict],
) -> None:
    """Record one clean match for a multi-line PR split and consume every PR row.

    Primary PR is chosen with the same deterministic canonical rule as true
    duplicates. ``match_level`` follows Issue 3 (L1 only when raw invoice
    strings match the GSTR row; otherwise L2) without calling the full matcher
    on a single partial PR line — amounts only reconcile at the group level.
    """
    g = gstr_by_id[gid]
    primary_pr_id = _select_canonical_pr_id(g, p_ids, pr_by_id)
    pr_primary = pr_by_id[primary_pr_id]
    g_raw = str(g.get("invoice_number") or "").strip()
    p_raw = str(pr_primary.get("invoice_number") or "").strip()
    raw_identical = bool(g_raw and p_raw and g_raw == p_raw)
    level = 1 if raw_identical else 2
    ml_result = MatchResult(
        level=level,
        matched=True,
        confidence=100 if raw_identical else 95,
        requires_human_review=False,
        decision_what="Matched",
        decision_why="Multi-line purchase register booking sums to GSTR-2B invoice",
        decision_next="",
        identity_confidence="High",
        financial_status="Exact",
    )
    score = compute_match_score(ml_result)
    _push_clean_matched(
        state, gid, primary_pr_id, score, ml_result,
        gstr_rec=g, pr_rec=pr_primary,
    )
    for pid in p_ids:
        if pid != primary_pr_id:
            state.consumed_pr_ids.add(pid)
    match_dict = state.clean_matched[-1]
    match_dict["pr_ids"] = list(p_ids)
    match_dict["multiline_pr_split"] = True
    match_dict["match_reasons"] = [
        "Multi-line purchase register rows sum to GSTR-2B invoice"
    ]
    if not raw_identical:
        match_dict["match_reasons"].append(
            "Invoice numbers match after normalization or format variant"
        )
    # Group-level taxable delta (primary line alone is a partial booking).
    g_taxable = _taxable_paise(g)
    p_taxable_sum = sum(
        _taxable_paise(pr_by_id[pid]) for pid in p_ids
    )
    taxable_diff = abs(g_taxable - p_taxable_sum)
    match_dict["taxable_diff_paise"] = taxable_diff
    match_dict["amount_difference_paise"] = taxable_diff
    match_dict["gstr_taxable_amount_paise"] = g_taxable
    match_dict["pr_taxable_amount_paise"] = p_taxable_sum


def prepass_duplicate_ambiguity(
    gstr_records: list[dict],
    pr_records: list[dict],
    state: ReconState,
) -> None:
    """Detect duplicate/ambiguous (GSTIN, normalized invoice) groups BEFORE Phase 1
    greedy matching runs, so that:

      * Genuinely ambiguous groups (e.g. 2 GSTR rows and 1 PR row all sharing an
        identical invoice number, amount and date) are routed straight to Review
        Required — Phase 1's greedy "first candidate wins" matching must never be
        allowed to silently auto-pick one of several equally-plausible pairings.
      * Groups that share only the invoice+GSTIN key but are deterministically
        distinguishable by amount/date (e.g. two genuinely different invoices that
        happen to reuse the same invoice number) are left untouched so Phase 1's
        per-record matching — which already ranks candidates by amount/date
        closeness — resolves them correctly.
      * Multi-line PR bookings (one GSTR invoice, N PR rows whose amounts sum to
        the GSTR totals — typical tax-rate / HSN splits) are auto-matched as a
        single clean pair. Counting each PR row separately was the source of
        Matched+Review+Missed exceeding Total GSTR on multi-item invoices.
      * Pure data-entry duplicates (one real GSTR invoice booked twice in the
        Purchase Register with identical full-invoice values) leave the
        deterministically chosen canonical PR free for Phase 1 to match, and
        flag every extra PR row as Duplicate Entry (not Review Required, not
        ITC at Risk). Each duplicate_entry records matched_pr_id so a CA can
        see which row was treated as the real booking.

    This must run before ``process_gstr_records_chunk`` (Phase 1); running it
    afterwards (as a Phase 2 step) is too late because Phase 1 will already have
    greedily consumed one arbitrary member of the ambiguous group.
    """
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    gstr_by_id: dict[str, dict] = {}
    pr_by_id: dict[str, dict] = {}

    for g in gstr_records:
        gid = str(g.get("id"))
        gstr_by_id[gid] = g
        key = _dup_group_key(g.get("supplier_gstin"), g.get("invoice_number_normalized"))
        if key:
            groups[key].append("G_" + gid)
    for p in pr_records:
        pid = str(p.get("id"))
        pr_by_id[pid] = p
        key = _dup_group_key(p.get("supplier_gstin"), p.get("invoice_number_normalized"))
        if key:
            groups[key].append("P_" + pid)

    for _key, items in groups.items():
        g_ids = [x[2:] for x in items if x.startswith("G_")]
        p_ids = [x[2:] for x in items if x.startswith("P_")]

        if len(g_ids) <= 1 and len(p_ids) <= 1:
            continue  # nothing ambiguous about a single GSTR / single PR pairing

        if len(g_ids) == 1 and len(p_ids) > 1:
            gid = g_ids[0]
            g = gstr_by_id[gid]
            # Tax-rate / HSN line split: PR rows partition one invoice → 1 match.
            if _is_multiline_pr_split(g, p_ids, pr_by_id):
                _push_multiline_clean_match(state, gid, p_ids, gstr_by_id, pr_by_id)
                continue
            # True duplicate booking: every PR is a full-value copy of the GSTR
            # invoice. Pick a deterministic canonical PR for Phase 1; flag every
            # other PR as Duplicate Entry. Mixed groups (full + partial) are
            # left for Phase 1 — do not mislabel partials as duplicates.
            if _is_true_duplicate_pr_group(g, p_ids, pr_by_id):
                canonical_pr_id = _select_canonical_pr_id(g, p_ids, pr_by_id)
                for pid in p_ids:
                    if pid == canonical_pr_id:
                        continue
                    _push_duplicate_entry(
                        state,
                        extra_pr_id=pid,
                        matched_pr_id=canonical_pr_id,
                        gstr_id=gid,
                        pr_rec=pr_by_id[pid],
                    )
                continue
            # PR↔PR clones that share amounts with each other but drift from
            # GSTR (common in stress / messy books). Flag extras as Duplicate
            # Entry so they never become ITC at Risk; leave one survivor for
            # Phase 1/2 (typically Review Required for the amount gap).
            _flag_pr_to_pr_clone_duplicates(
                state, gstr_id=gid, g=g, p_ids=p_ids, pr_by_id=pr_by_id
            )
            continue

        if len(g_ids) > 1 and _is_deterministic_duplicate_group(g_ids, p_ids, gstr_by_id, pr_by_id):
            # Amount/date make the pairing unambiguous even though several rows
            # share the same invoice number — let Phase 1 match them normally.
            continue

        if len(g_ids) <= 1:
            continue

        # Genuine ambiguity: cannot safely auto-pair. Route every row on both
        # sides to Review Required so a human resolves it — one row per GSTR
        # id and one row per PR id.
        #
        # Each GSTR row's pr_id must NOT be filled in with an arbitrary PR id
        # (e.g. always "the first PR in the group") — a previous version of
        # this code did that, which caused that one PR id to be double
        # (triple, ...) counted across every GSTR row on top of its own
        # dedicated PR-anchored row, breaking bucket-exclusivity. Since the
        # whole point of this branch is "we cannot safely say which GSTR
        # pairs with which PR", a GSTR-anchored row must leave pr_id blank
        # (and a PR-anchored row must leave gstr_id blank) so every id is
        # attributable to exactly one row.
        for gid in g_ids:
            state.consumed_gstr_ids.add(gid)
        for pid in p_ids:
            state.consumed_pr_ids.add(pid)
        for gid in g_ids:
            _push_review_required(
                state, gid, "", 50, "DUPLICATE_AMBIGUITY",
            )
        for pid in p_ids:
            _push_review_required(
                state, "", pid, 50, "DUPLICATE_AMBIGUITY_PR",
            )


def resolve_orphans(
    matched: list[dict],
    missed_itc: list[dict],
    wrongful_itc_risk: list[dict],
    gstr_by_id: dict[str, dict],
    pr_by_id: dict[str, dict],
    *,
    amount_tolerance_paise: int = TOTAL_TOLERANCE_PAISE,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Standalone orphan-pool reclassifier (bipartite/union-find), kept as a
    reusable utility and safety net independent of the inline Phase 1/2/3 engine.

    Given already-classified ``matched`` / ``missed_itc`` / ``wrongful_itc_risk``
    pools, re-groups every record (matched + orphans) by shared normalized
    invoice number and re-derives bucket-exclusive outcomes so no invoice can
    ever appear twice (e.g. as both ``missed_itc`` and ``wrongful_itc_risk``).

    Lifecycle (in order):
      1. **Build bipartite candidate graph** — connect ALL records (matched + orphans)
         by shared normalized invoice number.
      2. **Classify connected components**:
         - 1 GSTR + 1 PR: if already matched, keep matched. If orphans with
           different GSTIN, ``gstin_mismatch``. Else genuine orphans.
         - 1 GSTR + N PRs (N > 1): if the GSTR is already matched to one PR,
           keep that match and flag extra PRs as ``duplicate_pr_rows``.
         - N GSTR + N PRs → deterministic pairing if amount/date uniquely
           disambiguate; otherwise ``review_required``.
         - 1 GSTR + 0 PRs → genuine ``missed_itc``
         - 0 GSTRs + 1 PR → genuine ``wrongful_itc_risk``
      3. **Bucket exclusivity** is guaranteed: each GSTR/PR id appears in exactly
         one output list.

    Returns ``(matched_final, missed_final, wrongful_final, gstin_mismatch, review_required, duplicate_pr_rows)``.
    """
    inv_to_gstr: dict[str, list[str]] = defaultdict(list)
    inv_to_pr: dict[str, list[str]] = defaultdict(list)

    gstr_by_id_local: dict[str, dict] = {}
    pr_by_id_local: dict[str, dict] = {}

    matched_pairs_by_ids: dict[tuple[str, str], dict] = {}

    def _add_gstr(g: dict):
        gid = str(g.get("gstr_id") or g.get("id") or "")
        if not gid:
            return
        gstr_by_id_local[gid] = g
        inv_key = normalize_invoice(g.get("invoice_number_normalized") or "").upper()
        if inv_key:
            inv_to_gstr[inv_key].append(gid)

    def _add_pr(p: dict):
        pid = str(p.get("pr_id") or p.get("id") or "")
        if not pid:
            return
        pr_by_id_local[pid] = p
        inv_key = normalize_invoice(p.get("invoice_number_normalized") or "").upper()
        if inv_key:
            inv_to_pr[inv_key].append(pid)

    for m in matched:
        gid = str(m.get("gstr_id"))
        pid = str(m.get("pr_id"))
        matched_pairs_by_ids[(gid, pid)] = m
        if gid in gstr_by_id:
            _add_gstr({"gstr_id": gid, **gstr_by_id[gid]})
        if pid in pr_by_id:
            _add_pr({"id": pid, **pr_by_id[pid]})

    for mi in missed_itc:
        _add_gstr(mi)
    for w in wrongful_itc_risk:
        _add_pr(w)

    all_inv_keys = set(inv_to_gstr) | set(inv_to_pr)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
            x = parent.get(x, x)
        return x

    def union(a: str, b: str):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for gid in gstr_by_id_local:
        parent[f"G:{gid}"] = f"G:{gid}"
    for pid in pr_by_id_local:
        parent[f"P:{pid}"] = f"P:{pid}"
    for inv_key in all_inv_keys:
        parent[f"I:{inv_key}"] = f"I:{inv_key}"
        for gid in inv_to_gstr.get(inv_key, []):
            union(f"I:{inv_key}", f"G:{gid}")
        for pid in inv_to_pr.get(inv_key, []):
            union(f"I:{inv_key}", f"P:{pid}")

    for gid, pid in matched_pairs_by_ids:
        union(f"G:{gid}", f"P:{pid}")

    comp_gstr: dict[str, list[str]] = defaultdict(list)
    comp_pr: dict[str, list[str]] = defaultdict(list)
    for gid in gstr_by_id_local:
        comp_gstr[find(f"G:{gid}")].append(gid)
    for pid in pr_by_id_local:
        comp_pr[find(f"P:{pid}")].append(pid)

    all_roots = set(comp_gstr) | set(comp_pr)

    matched_final: list[dict] = []
    missed_final: list[dict] = []
    wrongful_final: list[dict] = []
    gstin_mismatch: list[dict] = []
    review_required: list[dict] = []
    duplicate_pr_rows: list[dict] = []

    for root in all_roots:
        g_ids = comp_gstr.get(root, [])
        p_ids = comp_pr.get(root, [])

        if len(g_ids) == 1 and len(p_ids) == 1:
            gid = g_ids[0]
            pid = p_ids[0]
            if (gid, pid) in matched_pairs_by_ids:
                matched_final.append(matched_pairs_by_ids[(gid, pid)])
                continue
            mi = gstr_by_id_local[gid]
            w = pr_by_id_local[pid]
            g_gstin = str(mi.get("supplier_gstin") or "")
            w_gstin = str(w.get("supplier_gstin") or "")
            g_taxable = _taxable_paise(mi)
            w_taxable = _taxable_paise(w)

            if g_gstin != w_gstin and abs(w_taxable - g_taxable) <= amount_tolerance_paise:
                gstin_mismatch.append({
                    "gstr_id": str(mi.get("gstr_id") or ""),
                    "pr_id": str(w.get("id") or ""),
                    "gstr_supplier_gstin": g_gstin,
                    "pr_supplier_gstin": w_gstin,
                    "invoice_number_normalized": mi.get("invoice_number_normalized"),
                    "invoice_date": mi.get("invoice_date"),
                    "taxable_amount_paise": w_taxable,
                    "total_tax_paise": int(mi.get("total_tax_paise") or 0),
                    "reason": "GSTIN_MISMATCH",
                })
            else:
                missed_final.append(mi)
                wrongful_final.append(w)
            continue

        if len(g_ids) == 1 and len(p_ids) == 0:
            missed_final.append(gstr_by_id_local[g_ids[0]])
            continue

        if len(g_ids) == 0 and len(p_ids) == 1:
            wrongful_final.append(pr_by_id_local[p_ids[0]])
            continue

        if len(g_ids) == 1 and len(p_ids) > 1:
            gid = g_ids[0]
            matched_pid = None
            for pid in p_ids:
                if (gid, pid) in matched_pairs_by_ids:
                    matched_pid = pid
                    break
            if matched_pid is not None:
                matched_final.append(matched_pairs_by_ids[(gid, matched_pid)])
                for pid in p_ids:
                    if pid != matched_pid:
                        w = pr_by_id_local[pid]
                        duplicate_pr_rows.append({
                            **w,
                            "is_duplicate_pr_row": True,
                            "matched_to_gstr_id": gid,
                            "matched_pr_id": matched_pid,
                            "reason": "DUPLICATE_PR_DATA_ENTRY",
                        })
                continue

        if len(g_ids) == len(p_ids) and len(g_ids) > 1:
            g_sigs = [
                (_taxable_paise(gstr_by_id_local[gid]), str(gstr_by_id_local[gid].get("invoice_date") or ""))
                for gid in g_ids
            ]
            p_sigs = [
                (_taxable_paise(pr_by_id_local[pid]), str(pr_by_id_local[pid].get("invoice_date") or ""))
                for pid in p_ids
            ]
            if len(set(g_sigs)) == len(g_ids) and sorted(g_sigs) == sorted(p_sigs):
                for gid, pid in zip(
                    sorted(g_ids, key=lambda x: (_taxable_paise(gstr_by_id_local[x]), str(gstr_by_id_local[x].get("invoice_date") or ""))),
                    sorted(p_ids, key=lambda x: (_taxable_paise(pr_by_id_local[x]), str(pr_by_id_local[x].get("invoice_date") or ""))),
                ):
                    if (gid, pid) in matched_pairs_by_ids:
                        matched_final.append(matched_pairs_by_ids[(gid, pid)])
                    else:
                        g_gstin = str(gstr_by_id_local[gid].get("supplier_gstin") or "")
                        p_gstin = str(pr_by_id_local[pid].get("supplier_gstin") or "")
                        if g_gstin != p_gstin:
                            gstin_mismatch.append({
                                "gstr_id": gid,
                                "pr_id": pid,
                                "gstr_supplier_gstin": g_gstin,
                                "pr_supplier_gstin": p_gstin,
                                "invoice_number_normalized": gstr_by_id_local[gid].get("invoice_number_normalized"),
                                "invoice_date": gstr_by_id_local[gid].get("invoice_date"),
                                "taxable_amount_paise": _taxable_paise(pr_by_id_local[pid]),
                                "total_tax_paise": int(gstr_by_id_local[gid].get("total_tax_paise") or 0),
                                "reason": "GSTIN_MISMATCH",
                            })
                        else:
                            matched_final.append({
                                "gstr_id": gid, "pr_id": pid,
                                "match_status_text": "Matched (deterministic duplicate pair)",
                                "match_level": 1, "confidence_score": 95,
                            })
                continue

        # Truly ambiguous → review_required
        for gid in g_ids:
            mi = gstr_by_id_local[gid]
            review_required.append({**mi, "side": "GSTR", "reason": "DUPLICATE_CONFLICT"})
        for pid in p_ids:
            w = pr_by_id_local[pid]
            review_required.append({**w, "side": "PR", "reason": "DUPLICATE_CONFLICT"})

    return matched_final, missed_final, wrongful_final, gstin_mismatch, review_required, duplicate_pr_rows


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
    run_skipped_count = 0  # batched across entire chunk — logged once at end

    # Process GSTR rows that have an exact same-GSTIN + normalized-invoice PR
    # hit first. Phase 1 is greedy (consumes the PR on first acceptable link);
    # without this ordering a near-invoice GSTR processed earlier can steal the
    # PR via a weaker path and orphan the exact counterpart into Missed ITC.
    def _exact_pr_hit_first(rec: dict) -> tuple[int, str]:
        gst = str(rec.get("supplier_gstin") or "").strip()
        inv = str(rec.get("invoice_number_normalized") or "")
        has_exact = bool(
            pr_by_invoice
            and gst
            and inv
            and pr_by_invoice.get(gst, {}).get(inv) is not None
        )
        return (0 if has_exact else 1, str(rec.get("id") or ""))

    ordered_gstr = (
        sorted(gstr_records, key=_exact_pr_hit_first)
        if pr_by_invoice
        else gstr_records
    )

    for gstr_record in ordered_gstr:
        gstr_id = str(gstr_record["id"])
        if gstr_id in state.consumed_gstr_ids:
            continue
            
        gstin = str(gstr_record.get("supplier_gstin") or "").strip()
        
        # A.2 Pre-Phase 1 routing for missing/invalid GSTIN (URP/unregistered is valid)
        if not gstin or (len(gstin) != 15 and gstin != "URP" and gstin not in pr_index):
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
            pr_id = str(pr_rec.get("id") or "")
            if not pr_id:
                run_skipped_count += 1
                continue
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
            if best_result.requires_human_review:
                _push_review_required(
                    state, gstr_record["id"], best_pr["id"], score,
                    best_result.review_reason or "Amount/Date mismatch", best_result,
                    gstr_rec=gstr_record, pr_rec=best_pr,
                )
            else:
                _push_clean_matched(
                    state, gstr_record["id"], best_pr["id"], score, best_result,
                    gstr_rec=gstr_record, pr_rec=best_pr,
                )
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
                if not p.get("id"):
                    run_skipped_count += 1
                    continue
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
                if best_r.requires_human_review:
                    _push_review_required(
                        state, gstr_record["id"], best_p["id"], score,
                        best_r.review_reason or "Amount/Date mismatch", best_r,
                        gstr_rec=gstr_record, pr_rec=best_p,
                    )
                else:
                    _push_clean_matched(
                        state, gstr_record["id"], best_p["id"], score, best_r,
                        is_late_filing=True, original_period=period, late_months=late_months,
                        gstr_rec=gstr_record, pr_rec=best_p,
                    )
                break

    if run_skipped_count > 0:
        logger.warning(
            "[MATCH] Skipped %d PR candidate(s) with missing id during chunk matching "
            "(chunk size=%d). These are likely index entries missing 'id' — investigate "
            "PR record import if count is high.",
            run_skipped_count, len(gstr_records),
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
        tap = _taxable_paise(pr_rec)
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


RISKY_GSTR_FILING_STATUSES = frozenset({"Q"})


def build_filing_status_itc_risk(gstr_records: list[dict]) -> list[dict]:
    """GSTR invoices flagged as risky by supplier filing pattern (e.g. quarterly filer)."""
    out: list[dict] = []
    for g in gstr_records:
        filing_status = str(g.get("filing_status") or "").strip().upper()
        if filing_status not in RISKY_GSTR_FILING_STATUSES:
            continue
        gid = str(g.get("id") or "")
        ttp = int(g.get("total_tax_paise") or 0)
        tap = _taxable_paise(g)
        out.append(
            {
                "gstr_id": gid,
                "id": gid,
                "supplier_gstin": str(g.get("supplier_gstin") or ""),
                "invoice_number_normalized": str(
                    g.get("invoice_number_normalized") or ""
                ),
                "invoice_date": g.get("invoice_date"),
                "taxable_amount_paise": tap,
                "total_tax_paise": ttp,
                "risk_reason": "QUARTERLY_FILER",
                "risk_category": "filing_status",
                "filing_status": filing_status,
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


def _invoice_digit_core(s: str | None) -> str:
    """Digits-only spine of an invoice number (for mangled-prefix twin checks)."""
    return re.sub(r"[^0-9]", "", str(s or ""))


def _pct_within(a: int, b: int, pct: float) -> bool:
    if a == b:
        return True
    base = max(abs(a), abs(b), 1)
    return abs(a - b) / base <= pct


def _invoice_twin_similarity_ok(
    g_inv: str,
    p_inv: str,
    *,
    sim_min: float,
    digit_dist_max: int | None = 2,
    min_digit_len: int = 4,
) -> tuple[bool, float]:
    """True when invoice sim ≥ ``sim_min`` or digit-core edit distance ≤ max.

    Digit-core fallback requires both spines to be at least ``min_digit_len``
    digits so letter-only / empty cores (e.g. synthetic ``PRBOOKA`` fixtures)
    cannot collide via distance 0 on ``\"\"``.
    """
    sim = invoice_similarity(g_inv, p_inv)
    if sim >= sim_min:
        return True, sim
    if digit_dist_max is not None:
        gc = _invoice_digit_core(g_inv)
        pc = _invoice_digit_core(p_inv)
        if (
            len(gc) >= min_digit_len
            and len(pc) >= min_digit_len
            and _levenshtein_distance(gc, pc) <= digit_dist_max
        ):
            return True, sim
    return False, sim


def _peer_pr_invoice_clone_ok(a_inv: str, b_inv: str) -> tuple[bool, float]:
    """Stricter identity for unlinked PR↔PR clones.

    Unlinked rows have no GSTR anchor to corroborate identity. To prevent
    sequential invoices in the same series (e.g. '00242' vs '00272') from
    collapsing into Duplicate Entry, unlinked peer clones require:
    1. Exact normalized equality (a_inv == b_inv), OR
    2. True invoice format variant (is_invoice_format_variant), OR
    3. Mangled prefix typo with identical numeric core (ga == gb, len >= 4).
    """
    if a_inv == b_inv:
        return True, 1.0
    from app.services.matcher import is_invoice_format_variant
    if is_invoice_format_variant(a_inv, b_inv):
        return True, 1.0
    sim = invoice_similarity(a_inv, b_inv)
    if sim >= 0.75:
        ga, gb = _invoice_digit_core(a_inv), _invoice_digit_core(b_inv)
        if len(ga) >= 4 and len(gb) >= 4 and ga == gb:
            return True, sim
    return False, sim


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
    # NOTE: duplicate/ambiguous (GSTIN, normalized invoice) groups are now detected
    # and resolved by ``prepass_duplicate_ambiguity`` BEFORE Phase 1 runs (see
    # ``run_bidirectional_reconciliation`` / the worker task). Running this check
    # here — after Phase 1's greedy matching has already consumed one arbitrary
    # member of the ambiguous group — was too late and let Phase 1 silently
    # auto-pick a pairing out of several equally-plausible candidates. Nothing
    # left to do here; kept as a no-op for readability of the phase numbering.

    # Refresh unconsumed
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]
    pr_by_id_local = {str(p["id"]): p for p in unconsumed_pr}
    
    # Pre-index remaining PRs for fast lookup in Phase 2
    rem_pr_by_inv_norm = defaultdict(list)
    for p in unconsumed_pr:
        inv = str(p.get("invoice_number_normalized") or "")
        if inv: rem_pr_by_inv_norm[inv].append(p)

    # Snapshot of all unconsumed PRs for the fuzzy-GSTIN fallback scan.
    # This list is intentionally built once here; the per-iteration consumed-id
    # guard inside the loop keeps it correct without rebuilding.
    _all_unconsumed_pr_snapshot = list(unconsumed_pr)

    from app.services.matcher import (
        invoice_similarity,
        _parse_invoice_date,
        are_document_types_compatible,
    )

    # 1b. GSTIN_FORMAT_INVALID fallback — GSTR records whose ``ctin`` failed
    # strict GSTIN format validation at parse time (see gstr2b_parser.py) but
    # were kept in the pipeline instead of being dropped. ``supplier_gstin`` on
    # these records is a best-effort cleaned string, not a trustworthy key, so
    # every other Phase 1/2 step (which all compare GSTINs) will correctly find
    # nothing for them. Search for a PR counterpart using invoice_number +
    # amount + trade name only, deliberately ignoring GSTIN entirely.
    for g in list(unconsumed_gstr):
        gid = str(g["id"])
        if gid in state.consumed_gstr_ids:
            continue
        if not g.get("gstin_format_invalid"):
            continue

        g_inv_norm = str(g.get("invoice_number_normalized") or "")
        g_inv_raw = str(g.get("invoice_number") or "")
        g_amt = g.get("total_tax_paise") or 0
        g_date = _parse_invoice_date(g)
        g_name = str(g.get("supplier_name") or "")

        best_candidate: dict | None = None
        best_sort_key: tuple | None = None
        for p in unconsumed_pr:
            pid = str(p["id"])
            if pid in state.consumed_pr_ids:
                continue
            compat, _ = are_document_types_compatible(g, p)
            if not compat:
                continue

            # Supplier identity gate: Corrupted GSTIN must still have compatible supplier identity
            # (e.g. near-match GSTIN or non-conflicting PAN/state/vendor)
            compat_id, id_reason, id_type = supplier_identity_compatible(g, p)
            if not compat_id or id_type == "IDENTITY_CONFLICT":
                continue

            p_inv_norm = str(p.get("invoice_number_normalized") or "")
            if not g_inv_norm or not p_inv_norm:
                continue
            p_inv_raw = str(p.get("invoice_number") or "")
            inv_sim = (
                invoice_similarity(g_inv_norm, p_inv_norm)
                if g_inv_norm and p_inv_norm
                else 0.0
            )

            # Sequential series mismatch (e.g. INV1900 vs INV1920) must NEVER match as fuzzy invoice.
            is_seq_mismatch = is_sequential_series_mismatch(
                g_inv_norm,
                p_inv_norm,
                g_inv_raw,
                p_inv_raw,
                is_note=_is_note_document(g) or _is_note_document(p),
            )
            if is_seq_mismatch:
                continue

            # Equal-length digit mangling (e.g. INV650125 ↔ INV605125, sim≈0.78)
            # is not a format variant by design — still a credible twin when
            # amount/date corroborate. Align floor with fuzzy-GSTIN / TYPO (0.75).
            same_invoice = (
                g_inv_norm == p_inv_norm
                or is_invoice_format_variant(
                    g_inv_norm, p_inv_norm, g_inv_raw, p_inv_raw
                )
                or inv_sim >= 0.75
            )
            if not same_invoice:
                continue

            p_amt = p.get("total_tax_paise") or 0
            if g_amt == 0 and p_amt == 0:
                diff_pct = 0.0
            elif p_amt == 0:
                diff_pct = 1.0
            else:
                diff_pct = abs(g_amt - p_amt) / float(p_amt)
            if diff_pct > 0.05:
                continue

            p_date = _parse_invoice_date(p)
            date_diff = abs((g_date - p_date).days) if g_date and p_date else 0
            if g_date and p_date and date_diff > 30:
                continue

            # Trade name is a confirming signal, not a hard gate: a corrupted
            # GSTIN means the whole supplier identity on the GSTR side is
            # unreliable, and legitimate names can legally differ slightly
            # (abbreviations, branch suffixes) between filings.
            p_name = str(p.get("supplier_name") or "")
            name_sim = vendor_name_similarity(g_name, p_name) if g_name and p_name else 0.0

            sort_key = (diff_pct, -inv_sim, -name_sim, date_diff)
            if best_candidate is None or sort_key < best_sort_key:
                best_candidate = p
                best_sort_key = sort_key

        if best_candidate is not None:
            _push_review_required(
                state, gid, best_candidate["id"], 35, "GSTIN_MISMATCH",
                gstr_rec=g, pr_rec=best_candidate,
                note="Supplier GSTIN has invalid format — verify manually",
            )
            state.metrics["invalid_gstin_matched_count"] += 1
            continue
        # No credible PR candidate found even ignoring GSTIN — leave unconsumed.
        # Phase 3 will pick this up and tag it distinctly (see below) instead of
        # silently reporting it as ordinary, fully-verified Missed ITC.

    # Refresh unconsumed + dependent indices after the GSTIN_FORMAT_INVALID pass
    # may have consumed some GSTR/PR ids above.
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]
    pr_by_id_local = {str(p["id"]): p for p in unconsumed_pr}
    rem_pr_by_inv_norm = defaultdict(list)
    for p in unconsumed_pr:
        inv = str(p.get("invoice_number_normalized") or "")
        if inv: rem_pr_by_inv_norm[inv].append(p)
    _all_unconsumed_pr_snapshot = list(unconsumed_pr)
    unconsumed_gstr_by_gstin = defaultdict(list)
    for g_rec in unconsumed_gstr:
        g_gst = str(g_rec.get("supplier_gstin") or "").strip()
        if g_gst:
            unconsumed_gstr_by_gstin[g_gst].append(g_rec)

    # 2. GSTIN_MISMATCH & 3. TYPO_MISMATCH
    for g in unconsumed_gstr:
        gid = str(g["id"])
        gst = str(g.get("supplier_gstin") or "").strip()
        if not gst or (len(gst) != 15 and gst != "URP"):
            continue
            
        inv = str(g.get("invoice_number_normalized") or "")
        g_amt = g.get("total_tax_paise") or 0
        g_date = _parse_invoice_date(g)
        
        # Look for GSTIN_MISMATCH (same inv norm, amt within 2%)
        candidates_gstin_mismatch = []
        for p in rem_pr_by_inv_norm.get(inv, []):
            if str(p["id"]) in state.consumed_pr_ids: continue
            compat, _ = are_document_types_compatible(g, p)
            if not compat:
                continue
            p_gst = str(p.get("supplier_gstin") or "").strip()
            if gst != p_gst:
                if _pr_has_stronger_same_gstin_gstr_candidate(
                    p, unconsumed_gstr_by_gstin, state.consumed_gstr_ids
                ):
                    continue
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
                _push_review_required(
                    state, gid, candidates_gstin_mismatch[0]["id"], 50, "MULTIPLE_CANDIDATES",
                    gstr_rec=g, pr_rec=candidates_gstin_mismatch[0],
                )
            else:
                _push_review_required(
                    state, gid, candidates_gstin_mismatch[0]["id"], 50, "GSTIN_MISMATCH",
                    gstr_rec=g, pr_rec=candidates_gstin_mismatch[0],
                )
            continue

        # ── FUZZY-GSTIN FALLBACK ────────────────────────────────────────────────────
        # The exact-invoice GSTIN_MISMATCH check above found nothing, which means
        # either the invoice number also differs slightly OR the PR was indexed under
        # a different GSTIN key.  Do a broader scan across all remaining PRs:
        #   • GSTIN is a near-match  (Levenshtein ≤ 2  OR  same PAN)
        #   • Invoice similarity ≥ 0.75
        #   • Amount within 2 %
        #   • Date within 30 days
        # If found → Review Required (GSTIN_MISMATCH), NOT missed_itc.
        # This path is ONLY reached when no exact-GSTIN match was found in Phase 1
        # and the exact-invoice GSTIN_MISMATCH check above also failed.
        candidates_fuzzy_gstin: list[tuple[dict, float]] = []
        for p in _all_unconsumed_pr_snapshot:
            pid = str(p["id"])
            if pid in state.consumed_pr_ids:
                continue
            compat, _ = are_document_types_compatible(g, p)
            if not compat:
                continue
            p_gst = str(p.get("supplier_gstin") or "").strip()
            # Must be a near-match GSTIN (not exact — exact case already handled above)
            if not _gstin_is_fuzzy_match(gst, p_gst):
                continue
            if _pr_has_stronger_same_gstin_gstr_candidate(
                p, unconsumed_gstr_by_gstin, state.consumed_gstr_ids
            ):
                continue
            # Invoice must be plausibly the same.
            # Accept if similarity >= 0.75 OR if the two invoice numbers are recognised
            # format variants (e.g. "DS/26/78" ↔ "DS-2026-00078").  Format variants can
            # score low on raw Levenshtein even though they are clearly the same invoice.
            p_inv_norm = str(p.get("invoice_number_normalized") or "")
            inv_sim = invoice_similarity(inv, p_inv_norm) if inv and p_inv_norm else 0.0
            g_inv_raw_fuzzy = str(g.get("invoice_number") or "")
            p_inv_raw_fuzzy = str(p.get("invoice_number") or "")
            _is_fv = is_invoice_format_variant(inv, p_inv_norm, g_inv_raw_fuzzy, p_inv_raw_fuzzy) if inv and p_inv_norm else False
            if inv_sim < 0.75 and not _is_fv:
                continue
            if is_sequential_series_mismatch(
                inv,
                p_inv_norm,
                g_inv_raw_fuzzy,
                p_inv_raw_fuzzy,
                is_note=_is_note_document(g) or _is_note_document(p),
            ):
                continue
            # Amount within 5 % (relaxed from 2 % because we already require a
            # near-match GSTIN *and* a plausible invoice — the extra amount slack
            # only adds a human-review flag, never a clean match).
            p_amt = p.get("total_tax_paise") or 0
            if g_amt == 0 and p_amt == 0:
                diff_pct = 0.0
            elif p_amt == 0:
                diff_pct = 1.0
            else:
                diff_pct = abs(g_amt - p_amt) / float(p_amt)
            if diff_pct > 0.05:
                continue
            # Date within 30 days (skip check when either side has no date)
            p_date = _parse_invoice_date(p)
            date_diff = abs((g_date - p_date).days) if g_date and p_date else 0
            if g_date and p_date and date_diff > 30:
                continue
            candidates_fuzzy_gstin.append((p, inv_sim))

        if candidates_fuzzy_gstin:
            # Pick best by invoice similarity, then lowest amount diff as tiebreaker
            candidates_fuzzy_gstin.sort(
                key=lambda x: (
                    -x[1],
                    abs((x[0].get("total_tax_paise") or 0) - g_amt),
                )
            )
            best_p, _best_sim = candidates_fuzzy_gstin[0]
            if len(candidates_fuzzy_gstin) > 1:
                _push_review_required(
                    state, gid, best_p["id"], 45, "MULTIPLE_CANDIDATES",
                    gstr_rec=g, pr_rec=best_p,
                    match_confidence=_best_sim,
                )
            else:
                _push_review_required(
                    state, gid, best_p["id"], 45, "GSTIN_MISMATCH",
                    gstr_rec=g, pr_rec=best_p,
                    match_confidence=_best_sim,
                )
            continue
            
        # 3. TYPO_MISMATCH
        # same GSTIN + amount within 5% + date within 45 days + invoice similarity ≥ 75%.
        # Floor was historically strict ``> 0.80``; equal-length digit transposition
        # (INV650125 ↔ INV605125 ≈ 0.78) and single-char OCR (BILL952425 ↔ BLIL952425
        # = 0.80) then fell through to Missed ITC despite an exact taxable twin in
        # the books. 0.75 matches the fuzzy-GSTIN invoice floor above.
        candidates_typo = []
        for prs_in_bucket in candidate_indices.by_taxable.get(gst, {}).values():
            for p in prs_in_bucket:
                if str(p["id"]) in state.consumed_pr_ids: continue
                compat, _ = are_document_types_compatible(g, p)
                if not compat: continue
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
                        if sim >= 0.75 and g_inv_norm != p_inv_norm:
                            g_inv_raw_typo = str(g.get("invoice_number") or "")
                            p_inv_raw_typo = str(p.get("invoice_number") or "")
                            if is_sequential_series_mismatch(
                                g_inv_norm,
                                p_inv_norm,
                                g_inv_raw_typo,
                                p_inv_raw_typo,
                                is_note=_is_note_document(g) or _is_note_document(p),
                            ):
                                continue
                            candidates_typo.append((p, sim))
                            
        if candidates_typo:
            candidates_typo.sort(key=lambda x: x[1], reverse=True)
            if len(candidates_typo) > 1 and candidates_typo[0][1] == candidates_typo[1][1]:
                _push_review_required(
                    state, gid, candidates_typo[0][0]["id"], 60, "MULTIPLE_CANDIDATES",
                    gstr_rec=g, pr_rec=candidates_typo[0][0],
                    match_confidence=candidates_typo[0][1],
                )
            else:
                _push_review_required(
                    state, gid, candidates_typo[0][0]["id"], 60, "TYPO_MISMATCH",
                    gstr_rec=g, pr_rec=candidates_typo[0][0],
                    match_confidence=candidates_typo[0][1],
                )
            continue

        # ── INVOICE_MATCH_AMOUNT_REVIEW ──────────────────────────────────────────
        # Catches: same GSTIN + same (or format-variant) invoice + amount diff too
        # large for L2/L3 or the TYPO/VENDOR threshold.  Invoice identity is certain
        # so this must NEVER go to missed_itc — always Review Required.
        # Triggered ONLY when all earlier Phase 2 checks (including TYPO_MISMATCH)
        # have produced no candidate, meaning the amount gap is the
        # sole remaining issue.
        g_inv_norm = str(g.get("invoice_number_normalized") or "")
        candidates_inv_match: list[dict] = []

        # Pass 1: exact same-GSTIN + exact normalized-invoice match — NO amount cap.
        # When invoice identity is unambiguous (same GSTIN, same normalized form), the
        # pair MUST be linked as Review Required even if the amount differs by >50%.
        # The by_taxable bucket scan (Pass 2) cannot find this PR when the amount diff
        # pushes the PR outside the ±30-bucket window, so we check the global index first.
        if g_inv_norm:
            for p in candidate_indices.by_invoice_norm_global.get(g_inv_norm, []):
                pid = str(p["id"])
                if pid in state.consumed_pr_ids:
                    continue
                compat, _ = are_document_types_compatible(g, p)
                if not compat:
                    continue
                p_gst = str(p.get("supplier_gstin") or "").strip()
                if p_gst == gst:
                    # Exact GSTIN + exact normalized invoice: no amount cap.
                    candidates_inv_match.append(p)

        # Pass 2: format-variant or near-GSTIN scan via taxable-bucket index (50% cap).
        # Only run when Pass 1 found nothing, to avoid double-counting.
        if not candidates_inv_match:
            g_inv_raw = str(g.get("invoice_number") or "")
            for prs_in_bucket in candidate_indices.by_taxable.get(gst, {}).values():
                for p in prs_in_bucket:
                    pid = str(p["id"])
                    if pid in state.consumed_pr_ids:
                        continue
                    compat, _ = are_document_types_compatible(g, p)
                    if not compat:
                        continue
                    p_inv_norm = str(p.get("invoice_number_normalized") or "")
                    # Accept exact normalized match OR a recognised format variant
                    # Pass raw invoice strings so Check 2 can tokenise on separators
                    # (e.g. 'FZ/2026/03763' → {2026, 3763} which intersects 'F3763' → {3763})
                    p_inv_raw = str(p.get("invoice_number") or "")
                    if g_inv_norm and p_inv_norm and (
                        g_inv_norm == p_inv_norm
                        or is_invoice_format_variant(g_inv_norm, p_inv_norm, g_inv_raw, p_inv_raw)
                    ):
                        p_amt = p.get("total_tax_paise") or 0
                        if g_amt == 0 and p_amt == 0: diff_pct = 0.0
                        elif p_amt == 0: diff_pct = 1.0
                        else: diff_pct = abs(g_amt - p_amt) / float(p_amt)
                        if diff_pct <= 0.50:
                            candidates_inv_match.append(p)
            # Global index fallback for near-GSTIN + large-amount-diff edge cases
            if not candidates_inv_match and g_inv_norm:
                for p in candidate_indices.by_invoice_norm_global.get(g_inv_norm, []):
                    pid = str(p["id"])
                    if pid in state.consumed_pr_ids:
                        continue
                    compat, _ = are_document_types_compatible(g, p)
                    if not compat:
                        continue
                    p_gst = str(p.get("supplier_gstin") or "").strip()
                    if p_gst != gst and _gstin_is_fuzzy_match(gst, p_gst):
                        p_amt = p.get("total_tax_paise") or 0
                        if g_amt == 0 and p_amt == 0: diff_pct = 0.0
                        elif p_amt == 0: diff_pct = 1.0
                        else: diff_pct = abs(g_amt - p_amt) / float(p_amt)
                        if diff_pct <= 0.50:
                            candidates_inv_match.append(p)

        # Pass 3: format-variant full-GSTIN scan — NO amount cap.
        # Pass 2 scans the taxable-bucket index; if the PR's taxable amount is far
        # outside the bucket window (large amount diff), the PR is never found.
        # When is_invoice_format_variant=True AND same GSTIN, identity is still
        # unambiguous (e.g. GSTR 'FY202600328' ↔ PR 'FY2600328' — year prefix dropped).
        # Such pairs must always be Review Required, not Missed ITC.
        if not candidates_inv_match and g_inv_norm:
            g_inv_raw = str(g.get("invoice_number") or "")
            for p in candidate_indices.by_gstin.get(gst, []):
                pid = str(p["id"])
                if pid in state.consumed_pr_ids:
                    continue
                compat, _ = are_document_types_compatible(g, p)
                if not compat:
                    continue
                p_inv_norm = str(p.get("invoice_number_normalized") or "")
                p_inv_raw = str(p.get("invoice_number") or "")
                if (g_inv_norm != p_inv_norm  # not an exact norm match (already handled above)
                        and is_invoice_format_variant(g_inv_norm, p_inv_norm, g_inv_raw, p_inv_raw)):
                    candidates_inv_match.append(p)

        if candidates_inv_match:
            if len(candidates_inv_match) > 1:
                _push_review_required(
                    state, gid, candidates_inv_match[0]["id"], 55, "MULTIPLE_CANDIDATES",
                    gstr_rec=g, pr_rec=candidates_inv_match[0],
                )
            else:
                _push_review_required(
                    state, gid, candidates_inv_match[0]["id"], 55, "AMOUNT_MISMATCH",
                    gstr_rec=g, pr_rec=candidates_inv_match[0],
                )
            continue

    # 5. CREDIBLE_CANDIDATE_FALLBACK
    # Find unconsumed GSTR/PR records that still have a credible candidate
    # Those should become review_required, not final financial risk.
    #
    # IMPORTANT — deterministic, order-independent assignment:
    # This runs as a two-pass global assignment instead of a single greedy pass
    # over ``unconsumed_gstr`` in list order. The previous implementation picked
    # ``credible_candidates[0]`` for whichever GSTR record happened to be
    # processed first, and immediately consumed that PR row — so when several
    # GSTR invoices from the same supplier had near-identical/sequential invoice
    # numbers (a common real-world pattern), the *input row order* silently
    # decided which invoice got the (correct) Review Required match and which
    # one fell through to Missed ITC / ITC at Risk. Re-uploading the exact same
    # two files with rows in a different order (e.g. after a DB re-read) could
    # then change the classification of a handful of genuinely ambiguous
    # invoices with no underlying data change.
    #
    # Fix: (1) discover every credible (GSTR, PR) candidate pair up front,
    # without consuming anything: (2) rank all pairs globally by match quality
    # (identity strength, then amount closeness, then date closeness, then a
    # stable id-based tiebreak) so the *best* pairs are locked in first,
    # regardless of which order the records arrived in; (3) walk that globally
    # sorted list once, skipping any pair whose GSTR or PR side was already
    # claimed by a better-ranked pair.
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr_fallback = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]

    # identity_tier: lower = stronger evidence the two records are the same invoice.
    #   0 = normalized invoice number matches exactly (criteria 2/3)
    #   1 = (retired) amount/date proximity with NO invoice-number check — removed
    #       because at multi-thousand invoice scale, same-GSTIN + similar tax is a
    #       coincidental collision, not identity evidence. Those GSTR rows must
    #       fall through to Missed ITC.
    #   2 = invoice number is a recognised format variant (criteria 4)
    candidates_by_gid: dict[str, list[tuple]] = defaultdict(list)
    all_candidate_pairs: list[tuple] = []

    for g in unconsumed_gstr:
        gid = str(g["id"])
        gst = str(g.get("supplier_gstin") or "").strip()
        g_amt = g.get("total_tax_paise") or 0
        g_date = _parse_invoice_date(g)
        g_inv_norm = str(g.get("invoice_number_normalized") or "")

        for p in unconsumed_pr_fallback:
            pid = str(p["id"])
            compat, _ = are_document_types_compatible(g, p)
            if not compat:
                continue

            p_gst = str(p.get("supplier_gstin") or "").strip()
            p_amt = p.get("total_tax_paise") or 0
            p_date = _parse_invoice_date(p)
            p_inv_norm = str(p.get("invoice_number_normalized") or "")

            if g_amt == 0 and p_amt == 0: diff_pct = 0.0
            elif p_amt == 0: diff_pct = 1.0
            else: diff_pct = abs(abs(g_amt) - abs(p_amt)) / float(abs(p_amt))

            date_diff = abs((g_date - p_date).days) if g_date and p_date else 0

            found: tuple[int, str] | None = None  # (identity_tier, reason)

            # criteria 2: same normalized invoice + amount within 2% + date within 30 days
            if g_inv_norm and g_inv_norm == p_inv_norm and diff_pct <= 0.02 and (not g_date or not p_date or date_diff <= 30):
                if gst and p_gst and gst != p_gst:
                    if _pr_has_stronger_same_gstin_gstr_candidate(
                        p, unconsumed_gstr_by_gstin, state.consumed_gstr_ids
                    ):
                        continue
                    g_vend = str(g.get("supplier_name") or "")
                    p_vend = str(p.get("supplier_name") or "")
                    supp_ok, _, _ = supplier_identity_compatible(g, p, g_vend, p_vend)
                    if not supp_ok:
                        continue
                found = (0, "POSSIBLE_MATCH")

            # criteria 3: same GSTIN + same normalized invoice → date/amount are secondary
            # (late_date_shift: date diff > 45 days but invoice identity is unambiguous).
            # Any amount diff is tolerated here — INVOICE_MATCH_AMOUNT_REVIEW handles
            # the precise amount-mismatch path; this is the fallback for cases that
            # slipped through (e.g. PR GSTIN slightly different but still exact inv).
            # CAP: amount diff <= 50% and date shift <= 365 days
            elif (gst and gst == p_gst and g_inv_norm and g_inv_norm == p_inv_norm
                    and diff_pct <= 0.50 and (not g_date or not p_date or date_diff <= 365)):
                reason = "TIME_BARRED_RISK" if (g_date and p_date and date_diff > 180) else "POSSIBLE_MATCH"
                found = (0, reason)

            # criteria 4: same GSTIN + format-variant invoice + amount diff <= 50%
            # Catches the pattern where the PR uses a stripped/abbreviated invoice number
            # (e.g. GSTR "FZ202603763" ↔ PR "F3763") AND the amount also differs.
            # These pairs fell through INVOICE_MATCH_AMOUNT_REVIEW (which uses the
            # by_taxable bucket scan and is fine for exact invoices with big amounts)
            # but were missed because the format variant + amount mismatch combo
            # exhausted all earlier sequential checks.  They must never go to missed_itc.
            # CAP: amount diff <= 50% and date within 365 days (same safety rails as C3).
            elif gst and gst == p_gst and g_inv_norm and p_inv_norm:
                # Pass raw invoice strings so Check 2's numeric-intersection can work
                g_inv_raw_fb = str(g.get("invoice_number") or "")
                p_inv_raw_fb = str(p.get("invoice_number") or "")
                _is_fmt_variant = is_invoice_format_variant(g_inv_norm, p_inv_norm, g_inv_raw_fb, p_inv_raw_fb)
                if _is_fmt_variant and diff_pct <= 0.50 and (not g_date or not p_date or date_diff <= 365):
                    reason = "TIME_BARRED_RISK" if (g_date and p_date and date_diff > 180) else "FORMAT_VARIANT_AMOUNT_REVIEW"
                    found = (2, reason)

            if found is not None:
                tier, reason = found
                pair = (tier, diff_pct, date_diff, gid, pid, reason, g, p)
                candidates_by_gid[gid].append(pair)
                all_candidate_pairs.append(pair)

    # Rank globally: strongest identity evidence first, then closest amount,
    # then closest date, then a stable id-based tiebreak so the outcome never
    # depends on the order records were read from the DB or the source file.
    all_candidate_pairs.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4]))

    # Group by PR id so we can tell, after assignment, which GSTR invoices
    # were credible claimants of a PR row that ultimately went to a
    # better-ranked competitor (see CREDIBLE_CANDIDATE_CONTENTION below).
    candidates_by_pid: dict[str, list[tuple]] = defaultdict(list)
    for pair in all_candidate_pairs:
        candidates_by_pid[pair[4]].append(pair)  # pair[4] == pid

    pid_winner_gid: dict[str, str] = {}

    for tier, diff_pct, date_diff, gid, pid, reason, g, p in all_candidate_pairs:
        if gid in state.consumed_gstr_ids or pid in state.consumed_pr_ids:
            continue
        review_reason = "MULTIPLE_CANDIDATES" if len(candidates_by_gid[gid]) > 1 else reason
        _push_review_required(
            state, gid, pid, 40, review_reason,
            gstr_rec=g, pr_rec=p,
        )
        pid_winner_gid[pid] = gid
        if len(candidates_by_pid[pid]) > 1:
            logger.info(
                "[CREDIBLE_CANDIDATE_CONTENTION] PR %s had %d credible GSTR claimant(s); "
                "winner=GSTR %s (tier=%d, diff_pct=%.4f, date_diff=%dd, reason=%s)",
                pid, len(candidates_by_pid[pid]), gid, tier, diff_pct, date_diff, reason,
            )

    # CREDIBLE_CANDIDATE_CONTENTION — losers.
    # A GSTR row that had at least one credible candidate (it's a key in
    # ``candidates_by_gid``) but is still unconsumed here lost EVERY one of
    # its candidate PR rows to a better-ranked claimant (lower identity tier,
    # then closer amount, then closer date — see the sort key above). Without
    # this pass such a row would silently fall through to PHASE 3 and be
    # reported as Missed ITC, indistinguishable from a genuinely orphaned
    # invoice with zero PR evidence. Route it to Review Required instead,
    # with a note identifying the invoice that won the contended PR, so a
    # human can see there WAS a plausible match, it just lost to a closer one.
    for gid, pairs in candidates_by_gid.items():
        if gid in state.consumed_gstr_ids:
            continue  # won its own assignment above, or consumed earlier in the pipeline
        tier, diff_pct, date_diff, _gid, pid, reason, g, p = min(
            pairs, key=lambda t: (t[0], t[1], t[2])
        )
        winner_gid = pid_winner_gid.get(pid)
        note = (
            f"credible PR match existed but was claimed by a closer match: {winner_gid}"
            if winner_gid
            else "credible PR match existed but was claimed by a closer match"
        )
        _push_review_required(
            state, gid, "", 35, "PR_CLAIMED_BY_BETTER_MATCH",
            gstr_rec=g, pr_rec=p, note=note,
        )
        logger.info(
            "[CREDIBLE_CANDIDATE_CONTENTION] GSTR %s lost PR %s to GSTR %s "
            "(loser diff_pct=%.4f, date_diff=%dd) -> routed to Review Required "
            "(PR_CLAIMED_BY_BETTER_MATCH) instead of Missed ITC",
            gid, pid, winner_gid, diff_pct, date_diff,
        )

    # 5b. STRONG_TAXABLE_TWIN rescue (before Phase 3 Missed ITC)
    # Tier 1: same GSTIN + exact taxable (±₹1) + invoice sim ≥ 0.75 + date ≤ 30d.
    # Tier 2: same GSTIN + taxable within 2% (+ total_tax within 5% when not
    # exact) + (sim ≥ 0.70 OR digit-core edit ≤ 2) + date ≤ 45d.
    # Complements TYPO_MISMATCH (which keys off total_tax within 5%): tax-head
    # swaps or cess drift can push total_tax outside that band while taxable
    # still matches exactly — those twins must not become Missed ITC.
    # Global assignment (same pattern as credible-candidate) so row order cannot
    # decide which of two near-ties gets the PR.
    def _assign_twin_pairs(
        pairs: list[tuple],
        by_gid: dict[str, list[tuple]],
        *,
        note: str,
        confidence: int = 55,
    ) -> None:
        pairs.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4]))
        for neg_sim, _taxable_diff, _date_diff, gid, pid, g, p in pairs:
            if gid in state.consumed_gstr_ids or pid in state.consumed_pr_ids:
                continue
            reason = (
                "MULTIPLE_CANDIDATES" if len(by_gid[gid]) > 1 else "TYPO_MISMATCH"
            )
            _push_review_required(
                state,
                gid,
                pid,
                confidence,
                reason,
                gstr_rec=g,
                pr_rec=p,
                match_confidence=-neg_sim,
                note=note,
            )

    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr_twin = [p for p in pr_records if str(p["id"]) not in state.consumed_pr_ids]
    pr_by_gstin_taxable: dict[tuple[str, int], list[dict]] = defaultdict(list)
    pr_by_gstin_all: dict[str, list[dict]] = defaultdict(list)
    for p in unconsumed_pr_twin:
        p_gst = str(p.get("supplier_gstin") or "").strip()
        if not p_gst:
            continue
        pr_by_gstin_taxable[(p_gst, _taxable_paise(p))].append(p)
        pr_by_gstin_all[p_gst].append(p)

    twin_pairs: list[tuple] = []
    twins_by_gid: dict[str, list[tuple]] = defaultdict(list)
    for g in unconsumed_gstr:
        gid = str(g["id"])
        gst = str(g.get("supplier_gstin") or "").strip()
        if not gst:
            continue
        g_taxable = _taxable_paise(g)
        g_inv_norm = str(g.get("invoice_number_normalized") or "")
        if not g_inv_norm:
            continue
        g_date = _parse_invoice_date(g)
        # Exact taxable ± ₹1 (100 paise)
        for tax_key in (g_taxable, g_taxable - 100, g_taxable + 100):
            if tax_key < 0:
                continue
            for p in pr_by_gstin_taxable.get((gst, tax_key), []):
                pid = str(p["id"])
                p_inv_norm = str(p.get("invoice_number_normalized") or "")
                if not p_inv_norm or p_inv_norm == g_inv_norm:
                    continue  # exact norm already handled earlier in Phase 2
                ok, sim = _invoice_twin_similarity_ok(
                    g_inv_norm, p_inv_norm, sim_min=0.75, digit_dist_max=None
                )
                if not ok:
                    continue
                g_inv_raw_twin = str(g.get("invoice_number") or "")
                p_inv_raw_twin = str(p.get("invoice_number") or "")
                if is_sequential_series_mismatch(
                    g_inv_norm,
                    p_inv_norm,
                    g_inv_raw_twin,
                    p_inv_raw_twin,
                    is_note=_is_note_document(g) or _is_note_document(p),
                ):
                    continue
                p_date = _parse_invoice_date(p)
                date_diff = abs((g_date - p_date).days) if g_date and p_date else 0
                if g_date and p_date and date_diff > 30:
                    continue
                taxable_diff = abs(g_taxable - _taxable_paise(p))
                pair = (-sim, taxable_diff, date_diff, gid, pid, g, p)
                twin_pairs.append(pair)
                twins_by_gid[gid].append(pair)

    _assign_twin_pairs(
        twin_pairs,
        twins_by_gid,
        note="Exact taxable twin with fuzzy invoice — verify before treating as Missed ITC",
    )

    # Tier 2 — looser amount/date/sim for extreme multi-mutation fuzz packs.
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    unconsumed_pr_ids_tier2 = {
        str(p["id"]) for p in pr_records if str(p["id"]) not in state.consumed_pr_ids
    }
    twin_pairs_t2: list[tuple] = []
    twins_by_gid_t2: dict[str, list[tuple]] = defaultdict(list)
    for g in unconsumed_gstr:
        gid = str(g["id"])
        gst = str(g.get("supplier_gstin") or "").strip()
        if not gst:
            continue
        g_taxable = _taxable_paise(g)
        g_tax = int(g.get("total_tax_paise") or 0)
        g_inv_norm = str(g.get("invoice_number_normalized") or "")
        if not g_inv_norm:
            continue
        g_date = _parse_invoice_date(g)
        for p in pr_by_gstin_all.get(gst, []):
            pid = str(p["id"])
            if pid not in unconsumed_pr_ids_tier2:
                continue
            p_inv_norm = str(p.get("invoice_number_normalized") or "")
            if not p_inv_norm or p_inv_norm == g_inv_norm:
                continue
            p_taxable = _taxable_paise(p)
            p_tax = int(p.get("total_tax_paise") or 0)
            taxable_diff = abs(g_taxable - p_taxable)
            exact_taxable = taxable_diff <= 100
            if not exact_taxable and not _pct_within(g_taxable, p_taxable, 0.02):
                continue
            if not exact_taxable and not _pct_within(g_tax, p_tax, 0.05):
                continue
            ok, sim = _invoice_twin_similarity_ok(
                g_inv_norm, p_inv_norm, sim_min=0.70, digit_dist_max=2
            )
            if not ok:
                continue
            g_inv_raw_twin2 = str(g.get("invoice_number") or "")
            p_inv_raw_twin2 = str(p.get("invoice_number") or "")
            if is_sequential_series_mismatch(
                g_inv_norm,
                p_inv_norm,
                g_inv_raw_twin2,
                p_inv_raw_twin2,
                is_note=_is_note_document(g) or _is_note_document(p),
            ):
                continue
            p_date = _parse_invoice_date(p)
            date_diff = abs((g_date - p_date).days) if g_date and p_date else 0
            if g_date and p_date and date_diff > 45:
                continue
            pair = (-sim, taxable_diff, date_diff, gid, pid, g, p)
            twin_pairs_t2.append(pair)
            twins_by_gid_t2[gid].append(pair)

    _assign_twin_pairs(
        twin_pairs_t2,
        twins_by_gid_t2,
        note="Near-amount twin with fuzzy invoice — verify before treating as Missed ITC",
        confidence=50,
    )

    # PHASE 3: True Financial Buckets
    unconsumed_gstr = [g for g in gstr_records if str(g["id"]) not in state.consumed_gstr_ids]
    for g in unconsumed_gstr:
        ttp = g.get("total_tax_paise")
        tap = _taxable_paise(g)
        entry = {
            "gstr_id": str(g["id"]),
            "supplier_gstin": str(g.get("supplier_gstin") or ""),
            "invoice_number_normalized": str(g.get("invoice_number_normalized") or ""),
            "invoice_date": g.get("invoice_date"),
            "taxable_amount_paise": int(tap) if tap is not None else 0,
            "total_tax_paise": int(ttp) if ttp is not None else 0,
        }
        g_doc = str(g.get("doc_type") or "").strip().upper()
        if g_doc == "CREDIT_NOTE":
            entry["doc_type"] = "CREDIT_NOTE"
            entry["is_credit_note"] = True
            entry["note_kind"] = "CREDIT_NOTE"
            entry["mismatch_reason"] = "UNBOOKED_CREDIT_NOTE_ITC_REDUCTION_PENDING"
            entry["requires_reversal"] = True
        elif g_doc == "DEBIT_NOTE":
            entry["doc_type"] = "DEBIT_NOTE"
            entry["is_debit_note"] = True
            entry["note_kind"] = "DEBIT_NOTE"
            entry["mismatch_reason"] = "UNCLAIMED_DEBIT_NOTE_ITC"
        elif g.get("gstin_format_invalid"):
            # The GSTIN_FORMAT_INVALID fallback pass above already tried and
            # failed to find a PR counterpart by invoice_number + amount +
            # trade name. This is still a genuine GSTR-2B invoice — do not
            # report it as ordinary, fully-verified Missed ITC (which implies
            # "supplier definitely filed, you just haven't booked it yet").
            # Flag it so downstream consumers can distinguish it.
            entry["gstin_format_invalid"] = True
            entry["mismatch_reason"] = "GSTIN format invalid — could not verify against PR"
        state.missed_itc.append(entry)

    # 5c. FUZZY / late duplicate sweep — after all GSTR↔PR linking.
    # Extras that share amounts with an already-linked PR but were not in the
    # same exact-key prepass group (canonical matched via typo/format-variant,
    # or invoice number itself was mangled) must become Duplicate Entry, not
    # ITC at Risk. Peer sweep catches clones when neither PR was linked.
    flag_fuzzy_duplicates_of_linked_prs(state, pr_records)
    flag_fuzzy_pr_peer_duplicates(state, pr_records)

    # Overwrite reason code for losing PR rows claimed by better-matched PR rows
    claimed_inv_norms = set()
    matched_pr_amounts: dict[str, tuple[int, int]] = {}
    pr_by_id = {str(p["id"]): p for p in pr_records}
    for m in state.clean_matched:
        inv_n = str(m.get("invoice_number_normalized") or "")
        if inv_n:
            claimed_inv_norms.add(inv_n)
        pid = str(m.get("pr_id") or "")
        if pid and pid in pr_by_id:
            matched_pr_amounts[pid] = (
                _taxable_paise(pr_by_id[pid]),
                int(pr_by_id[pid].get("total_tax_paise") or 0),
            )
    for r in state.review_required:
        if r.get("gstr_id") and r.get("pr_id"):
            inv_n = str(r.get("invoice_number_normalized") or "")
            if inv_n:
                claimed_inv_norms.add(inv_n)
            pid = str(r.get("pr_id") or "")
            if pid and pid in pr_by_id:
                matched_pr_amounts[pid] = (
                    _taxable_paise(pr_by_id[pid]),
                    int(pr_by_id[pid].get("total_tax_paise") or 0),
                )

    for d in state.duplicate_entries:
        if d.get("side") == "PR":
            d_inv = str(d.get("invoice_number_normalized") or "")
            matched_pid = str(d.get("matched_pr_id") or "")
            if (d_inv and d_inv in claimed_inv_norms) or d.get("gstr_id"):
                m_amt = matched_pr_amounts.get(matched_pid)
                d_taxable = _taxable_paise(d)
                d_tax = int(d.get("total_tax_paise") or 0)
                if m_amt and abs(m_amt[0] - d_taxable) <= 100 and abs(m_amt[1] - d_tax) <= 100:
                    d["reason"] = "DUPLICATE_ENTRY"
                else:
                    d["reason"] = "PR_CLAIMED_BY_BETTER_MATCH"


def _gstin_pan(gstin: str | None) -> str:
    g = (gstin or "").strip().upper()
    return g[2:12] if len(g) >= 12 else ""


def _gstin_is_fuzzy_match(gst_a: str, gst_b: str) -> bool:
    """Return True when two GSTINs are near-matches but NOT identical.

    Criteria (either is sufficient):
    * Levenshtein distance ≤ 2  (handles state-code swap, checksum typo, extra space)
    * Identical PAN (positions 3-12) — catches valid GSTIN variants for the same entity

    Identical GSTINs return False intentionally so callers can distinguish the
    fuzzy-mismatch path from the exact-match path.
    """
    a = gst_a.strip().upper()
    b = gst_b.strip().upper()
    if not a or not b or a == b:
        return False
    # Same PAN ⇒ almost certainly the same supplier filed under a different state/branch
    pan_a = a[2:12] if len(a) >= 12 else ""
    pan_b = b[2:12] if len(b) >= 12 else ""
    if pan_a and pan_b and pan_a == pan_b:
        return True
    # Levenshtein ≤ 2 handles one-off typos, case issues, single-digit checksum errors
    return _levenshtein_distance(a, b) <= 2


def _pr_has_stronger_same_gstin_gstr_candidate(
    p: dict,
    unconsumed_gstr_by_gstin: dict[str, list[dict]],
    consumed_gstr_ids: set[str],
) -> bool:
    """Return True if PR record `p` has an unconsumed same-GSTIN GSTR counterpart.

    Candidate Priority Hierarchy:
      Same-GSTIN candidates (exact normalized invoice, format variant, or typo match)
      represent claims under the true supplier and must not be stolen by cross-GSTIN
      matching (GSTIN_MISMATCH) from an unrelated supplier.
    """
    p_gst = str(p.get("supplier_gstin") or "").strip()
    if not p_gst:
        return False
    same_gst_gstrs = unconsumed_gstr_by_gstin.get(p_gst, [])
    if not same_gst_gstrs:
        return False

    p_inv_norm = str(p.get("invoice_number_normalized") or "")
    p_inv_raw = str(p.get("invoice_number") or "")
    p_amt = p.get("total_tax_paise") or 0
    p_date = _parse_invoice_date(p)

    for g_cand in same_gst_gstrs:
        if str(g_cand.get("id")) in consumed_gstr_ids:
            continue
        g_cand_norm = str(g_cand.get("invoice_number_normalized") or "")
        g_cand_raw = str(g_cand.get("invoice_number") or "")

        # 1. Exact invoice number match
        if p_inv_norm and g_cand_norm and p_inv_norm == g_cand_norm:
            return True

        # 2. Format variant match
        if p_inv_norm and g_cand_norm and is_invoice_format_variant(g_cand_norm, p_inv_norm, g_cand_raw, p_inv_raw):
            return True

        # 3. Typo match (amount within 5%, date within 45 days, invoice similarity >= 0.75)
        g_cand_amt = g_cand.get("total_tax_paise") or 0
        if p_amt == 0 and g_cand_amt == 0:
            diff_pct = 0.0
        elif p_amt == 0:
            diff_pct = 1.0
        else:
            diff_pct = abs(g_cand_amt - p_amt) / float(p_amt)

        if diff_pct <= 0.05:
            g_cand_date = _parse_invoice_date(g_cand)
            date_diff = abs((g_cand_date - p_date).days) if g_cand_date and p_date else 0
            if not g_cand_date or not p_date or date_diff <= 45:
                if p_inv_norm and g_cand_norm:
                    sim = invoice_similarity(g_cand_norm, p_inv_norm)
                    if sim >= 0.75:
                        return True

    return False


def _finalize_reconciliation_result(
    state: ReconState,
    total_gstr: int,
    total_pr: int,
    pr_records: list[dict],
    gstr_records: list[dict] = None,
) -> dict:
    matched_count = len(state.clean_matched)
    # review_gstr_count: count only rows anchored to a real GSTR record. Genuine
    # duplicate-ambiguity groups also emit PR-only marker rows (gstr_id="") so the
    # raw review_required list reflects every record in conflict — those marker
    # rows must NOT inflate the GSTR-side bucket-exclusivity invariant below.
    review_gstr_count = sum(1 for r in state.review_required if r.get("gstr_id"))
    
    missed_itc_count = len(state.missed_itc)
    missed_itc_amount_paise = sum(
        int(x.get("total_tax_paise") or 0) for x in state.missed_itc
    )
    
    # ITC at risk = unconsumed PR ghosts + GSTR-side risky-filer flags
    pr_wrongful_itc_risk = [
        {
            "id": str(p["id"]),
            "supplier_gstin": str(p.get("supplier_gstin") or ""),
            "invoice_number_normalized": str(
                p.get("invoice_number_normalized") or ""
            ),
            "invoice_date": p.get("invoice_date"),
            "taxable_amount_paise": _taxable_paise(p),
            "total_tax_paise": int(p.get("total_tax_paise") or 0),
            "risk_reason": "PR_ONLY",
            "risk_category": "pr_ghost",
        }
        for p in pr_records
        if str(p["id"]) not in state.consumed_pr_ids
    ]
    filing_status_risk = build_filing_status_itc_risk(gstr_records or [])
    wrongful_itc_risk = pr_wrongful_itc_risk + filing_status_risk
    wrongful_risk_count = len(wrongful_itc_risk)
    wrongful_risk_amount_paise = sum(
        int(x.get("total_tax_paise") or 0) for x in wrongful_itc_risk
    )
    
    # duplicate_pr_count: pure PR-side data-entry duplicates (one real invoice,
    # booked more than once) — these are consumed silently, never routed to
    # review, so they live in state.duplicate_pr_ids, not state.review_required.
    duplicate_pr_count = len(state.duplicate_pr_ids)
    gstin_mismatch_count = sum(1 for r in state.review_required if r.get("review_reason") == "GSTIN_MISMATCH")

    # Records whose GSTR-2B ``ctin`` failed strict format validation but were
    # retained (not dropped) by the parser — see gstr2b_parser.py. Surfaced so
    # the dashboard can show "N invoices need GSTIN verification" instead of
    # these silently vanishing from Total GSTR or being miscounted elsewhere.
    invalid_gstin_records = [g for g in (gstr_records or []) if g.get("gstin_format_invalid")]
    invalid_gstin_count = len(invalid_gstin_records)
    invalid_gstin_amount_paise = sum(int(g.get("total_tax_paise") or 0) for g in invalid_gstin_records)
    invalid_g_ids = {str(g["id"]) for g in invalid_gstin_records}
    invalid_gstin_matched_count = sum(
        1 for m in state.clean_matched if str(m.get("gstr_id")) in invalid_g_ids
    ) + sum(
        1 for r in state.review_required if str(r.get("gstr_id")) in invalid_g_ids
    )
    invalid_gstin_unresolved_count = invalid_gstin_count - invalid_gstin_matched_count

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
    
    # ── INJECT IMS STATUS (Stage 3 Integration) ──
    for m in state.clean_matched:
        gid = m.get("gstr_id")
        if gid and gid in gstr_by_id:
            m["ims_status"] = gstr_by_id[gid].get("ims_status", "no_action_taken")
            
    for m in state.review_required:
        gid = m.get("gstr_id")
        if gid and gid in gstr_by_id:
            m["ims_status"] = gstr_by_id[gid].get("ims_status", "no_action_taken")
            
    for m in state.missed_itc:
        gid = m.get("gstr_id")
        if gid and gid in gstr_by_id:
            m["ims_status"] = gstr_by_id[gid].get("ims_status", "no_action_taken")

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
        "duplicate_entries": list(state.duplicate_entries),
        "unmatched_notes": list(state.unmatched_notes),
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
            "duplicate_entry_count": len(state.duplicate_entries),
            "unmatched_notes_count": len(state.unmatched_notes),
            
            # Legacy stats (optional, but keep for now if UI needs it)
            "gstin_mismatch_count": gstin_mismatch_count,
            "gstin_mismatch_amount_paise": 0,

            # GSTR-2B records kept despite a structurally malformed ctin (see
            # gstr2b_parser.py). invalid_gstin_matched_count of these were
            # resolved via the invoice+amount+trade-name fallback and appear in
            # review_required (GSTIN_MISMATCH); the remainder appear in
            # missed_itc flagged with gstin_format_invalid=True.
            "invalid_gstin_count": invalid_gstin_count,
            "invalid_gstin_amount_paise": invalid_gstin_amount_paise,
            "invalid_gstin_matched_count": invalid_gstin_matched_count,
            "invalid_gstin_unresolved_count": invalid_gstin_unresolved_count,
            "duplicate_count": 0,
            "duplicate_pr_count": duplicate_pr_count,
            "duplicate_conflict_count": review_dup,
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
