"""E-Invoice Reconciliation Service — matches accounting books (Purchase/Sales Register)
against E-Invoice Report data.

Classifies results into 5 canonical categories:
- MATCHED
- IRN_MISSING
- IRN_CANCELLED
- EXTRA_IRN
- VALUE_MISMATCH
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Mapping

import pandas as pd

from app.decisions.layer import _decision_for_row
from app.services.decision_templates import generate_decision
from app.services.matcher import (
    AMOUNT_TOLERANCE_L1_PAISE,
    is_invoice_format_variant,
    normalize_invoice,
    same_pan,
)

logger = logging.getLogger(__name__)


def _extract_paise_value(rec: Mapping[str, Any]) -> int:
    """Extract total invoice value in paise from record dict."""
    if "value_paise" in rec and rec["value_paise"] is not None:
        try:
            return int(rec["value_paise"])
        except (ValueError, TypeError):
            pass
    for k in ("total_amount_paise", "total_value_paise", "invoice_value_paise", "amount_paise"):
        if rec.get(k) is not None:
            try:
                return int(rec[k])
            except (ValueError, TypeError):
                pass
    # Fallback to float rupees
    for k in ("total_value", "total_amount", "value", "amount", "invoice_value"):
        if rec.get(k) is not None:
            try:
                return int(round(float(rec[k]) * 100.0))
            except (ValueError, TypeError):
                pass
    return 0


def _extract_invoice_date(rec: Mapping[str, Any]) -> str:
    """Extract ISO date string (YYYY-MM-DD) from record dict."""
    d = rec.get("invoice_date") or rec.get("doc_date") or rec.get("date") or ""
    s = str(d).strip()
    if "T" in s:
        s = s[:10]
    return s[:10] if len(s) >= 10 else s


def reconcile_books_vs_einvoice(
    books_records: list[dict[str, Any]] | pd.DataFrame,
    einvoice_records: list[dict[str, Any]] | pd.DataFrame,
    e_invoice_applicable: bool = True,
) -> dict[str, Any]:
    """Reconcile Books (Purchase/Sales Register) against E-Invoice Report.

    Returns dict containing:
    - results: list of categorized result dicts
    - summary: counts and value totals by category
    """
    if isinstance(books_records, pd.DataFrame):
        books_list = books_records.to_dict(orient="records")
    else:
        books_list = list(books_records)

    if isinstance(einvoice_records, pd.DataFrame):
        einv_list = einvoice_records.to_dict(orient="records")
    else:
        einv_list = list(einvoice_records)

    # Pre-process books records
    norm_books: list[dict[str, Any]] = []
    for idx, b in enumerate(books_list):
        inv_raw = str(b.get("invoice_number") or b.get("invoice_no") or "").strip()
        inv_norm = b.get("invoice_number_normalized") or normalize_invoice(inv_raw)
        gstin = str(b.get("gstin") or b.get("supplier_gstin") or b.get("buyer_gstin") or "").strip().upper()
        paise = _extract_paise_value(b)
        inv_date = _extract_invoice_date(b)

        norm_books.append(
            {
                "_index": idx,
                "raw_record": b,
                "invoice_number": inv_raw,
                "invoice_number_normalized": inv_norm,
                "gstin": gstin,
                "value_paise": paise,
                "invoice_date": inv_date,
            }
        )

    # Pre-process e-invoice records
    norm_einv: list[dict[str, Any]] = []
    for idx, e in enumerate(einv_list):
        inv_raw = str(e.get("invoice_number") or e.get("invoice_no") or "").strip()
        inv_norm = e.get("invoice_number_normalized") or normalize_invoice(inv_raw)
        gstin = str(e.get("gstin") or e.get("supplier_gstin") or e.get("buyer_gstin") or "").strip().upper()
        paise = _extract_paise_value(e)
        inv_date = _extract_invoice_date(e)
        irn = str(e.get("irn") or "").strip()
        irn_status = str(e.get("irn_status") or "Active").strip()

        norm_einv.append(
            {
                "_index": idx,
                "raw_record": e,
                "invoice_number": inv_raw,
                "invoice_number_normalized": inv_norm,
                "gstin": gstin,
                "value_paise": paise,
                "invoice_date": inv_date,
                "irn": irn,
                "irn_status": irn_status,
                "ack_number": str(e.get("ack_number") or "").strip(),
                "ack_date": e.get("ack_date"),
            }
        )

    consumed_einv_indices: set[int] = set()
    results: list[dict[str, Any]] = []

    # 1. Primary match pass over Books rows
    for b in norm_books:
        inv_norm = b["invoice_number_normalized"]
        gstin = b["gstin"]
        b_val = b["value_paise"]

        matched_candidate: dict[str, Any] | None = None
        matched_einv_idx: int | None = None
        match_confidence: str = "HIGH"
        custom_unmatched_why: str | None = None

        # 1a. Collect all unconsumed candidates satisfying strict GSTIN match
        strict_candidates: list[tuple[int, dict[str, Any]]] = []
        for idx, e in enumerate(norm_einv):
            if idx in consumed_einv_indices:
                continue

            e_inv_norm = e["invoice_number_normalized"]
            e_gstin = e["gstin"]

            inv_match = (
                bool(inv_norm and e_inv_norm)
                and (inv_norm == e_inv_norm or is_invoice_format_variant(inv_norm, e_inv_norm))
            )
            strict_gstin_match = (
                bool(gstin)
                and bool(e_gstin)
                and (gstin == e_gstin or same_pan(gstin, e_gstin))
            )

            if inv_match and strict_gstin_match:
                strict_candidates.append((idx, e))

        if strict_candidates:
            # 1b. Rank multiple candidates: exact value diff == 0 first, then Active over Cancelled, then closest ack_date
            def _candidate_rank_key(item: tuple[int, dict[str, Any]]) -> tuple[bool, bool, int, int, int]:
                c_idx, e = item
                v_diff = abs(b_val - e["value_paise"])
                is_exact_val = (v_diff == 0)
                is_active = (str(e.get("irn_status") or "").strip().lower() not in ("cancelled", "unknown"))

                ack_diff_days = 999999
                b_date_str = b.get("invoice_date")
                e_date_str = e.get("ack_date") or e.get("invoice_date")
                if b_date_str and e_date_str:
                    try:
                        bd = date.fromisoformat(str(b_date_str)[:10])
                        ed = date.fromisoformat(str(e_date_str)[:10])
                        ack_diff_days = abs((ed - bd).days)
                    except Exception:
                        ack_diff_days = 999999

                return (is_exact_val, is_active, -v_diff, -ack_diff_days, -c_idx)

            best_tuple = max(strict_candidates, key=_candidate_rank_key)
            matched_einv_idx, matched_candidate = best_tuple
            match_confidence = "HIGH"

        elif not gstin:
            # 1c. Zero candidates found under strict GSTIN matching & books GSTIN is blank
            blank_gstin_candidates: list[tuple[int, dict[str, Any]]] = []
            for idx, e in enumerate(norm_einv):
                if idx in consumed_einv_indices:
                    continue
                e_inv_norm = e["invoice_number_normalized"]
                inv_match = (
                    bool(inv_norm and e_inv_norm)
                    and (inv_norm == e_inv_norm or is_invoice_format_variant(inv_norm, e_inv_norm))
                )
                if inv_match:
                    blank_gstin_candidates.append((idx, e))

            if len(blank_gstin_candidates) == 1:
                matched_einv_idx, matched_candidate = blank_gstin_candidates[0]
                match_confidence = "LOW_GSTIN_BLANK"
            elif len(blank_gstin_candidates) > 1:
                custom_unmatched_why = (
                    "Multiple e-invoice candidates share this invoice number; "
                    "GSTIN missing in books prevents disambiguation. Add GSTIN to books entry and re-run."
                )
                match_confidence = "LOW_GSTIN_BLANK"

        if matched_candidate is not None and matched_einv_idx is not None:
            consumed_einv_indices.add(matched_einv_idx)
            e_val = matched_candidate["value_paise"]
            val_diff = abs(b_val - e_val)
            irn_status = matched_candidate["irn_status"]

            if irn_status.lower() in ("cancelled", "unknown"):
                category = "IRN_CANCELLED"
                dec = generate_decision("EINVOICE_CANCELLED_MISMATCH")
            elif val_diff > AMOUNT_TOLERANCE_L1_PAISE:
                category = "VALUE_MISMATCH"
                diff_formatted = f"₹{val_diff / 100:,.2f}"
                book_val_fmt = f"₹{b_val / 100:,.2f}"
                einv_val_fmt = f"₹{e_val / 100:,.2f}"
                dec = generate_decision(
                    "EINVOICE_VALUE_MISMATCH",
                    diff=diff_formatted,
                    book_val=book_val_fmt,
                    einvoice_val=einv_val_fmt,
                )
            else:
                books_row = b.get("raw_record") or b
                irp_record = matched_candidate
                books_irn = books_row.get("irn")
                irp_irn = irp_record.get("irn")
                has_books_irn_field = ("irn" in books_row)
                if has_books_irn_field and not books_irn:
                    category = "IRN_MISSING"
                    dec = generate_decision("EINVOICE_IRN_MISSING")
                elif books_irn and irp_irn and books_irn != irp_irn:
                    category = "IRN_MISMATCH"
                    dec = generate_decision("EINVOICE_IRN_MISSING")
                else:
                    category = "MATCHED"
                    dec = generate_decision(
                        "L1_EXACT",
                        confidence="HIGH",
                        matched_fields=("invoice_number", "gstin", "amount"),
                    )
                    dec = type(dec)(
                        what="Exact match found — Active IRN verified",
                        why=f"Invoice {b['invoice_number']} in books has corresponding Active IRN on portal",
                        next="No action required. E-Invoice registration confirmed.",
                        rule="EINVOICE_MATCHED",
                        confidence="HIGH",
                        matched_fields=("invoice_number", "gstin", "amount"),
                        differed_fields=(),
                        normalized_pairs=((b["invoice_number"], matched_candidate["invoice_number"]),),
                    )

            why_text = dec.why
            if match_confidence == "LOW_GSTIN_BLANK":
                note = " (Note: GSTIN was missing in books; matched on single e-invoice candidate for this invoice number. Please verify manually.)"
                if note not in why_text:
                    why_text = f"{why_text}{note}"

            results.append(
                {
                    "invoice_number": b["invoice_number"],
                    "invoice_number_normalized": b["invoice_number_normalized"],
                    "gstin": b["gstin"],
                    "invoice_date": b["invoice_date"],
                    "doc_type": b.get("doc_type") or b.get("document_type") or b.get("invoice_type"),
                    "category": category,
                    "book_value": round(b_val / 100.0, 2),
                    "einvoice_value": round(e_val / 100.0, 2),
                    "value_difference": round(val_diff / 100.0, 2),
                    "irn": matched_candidate["irn"],
                    "irn_status": matched_candidate["irn_status"],
                    "ack_number": matched_candidate["ack_number"],
                    "ack_date": matched_candidate["ack_date"],
                    "decision_what": dec.what,
                    "decision_why": why_text,
                    "decision_next": dec.next,
                    "decision_rule": dec.rule,
                    "match_confidence": match_confidence,
                }
            )
        else:
            # Unmatched books row
            if e_invoice_applicable:
                category = "IRN_MISSING"
                dec = generate_decision("EINVOICE_IRN_MISSING")
            else:
                category = "NOT_APPLICABLE"
                dec = generate_decision(
                    "L1_EXACT",
                    confidence="MEDIUM",
                )
                dec = type(dec)(
                    what="E-Invoice not applicable for entity threshold",
                    why="Turnover threshold or entity classification does not mandate e-invoicing",
                    next="No action required.",
                    rule="EINVOICE_NOT_APPLICABLE",
                    confidence="HIGH",
                    matched_fields=(),
                    differed_fields=(),
                    normalized_pairs=(),
                )

            why_text = custom_unmatched_why if custom_unmatched_why is not None else dec.why

            results.append(
                {
                    "invoice_number": b["invoice_number"],
                    "invoice_number_normalized": b["invoice_number_normalized"],
                    "gstin": b["gstin"],
                    "invoice_date": b["invoice_date"],
                    "doc_type": b.get("doc_type") or b.get("document_type") or b.get("invoice_type"),
                    "category": category,
                    "book_value": round(b_val / 100.0, 2),
                    "einvoice_value": 0.0,
                    "value_difference": round(b_val / 100.0, 2),
                    "irn": None,
                    "irn_status": None,
                    "ack_number": None,
                    "ack_date": None,
                    "decision_what": dec.what,
                    "decision_why": why_text,
                    "decision_next": dec.next,
                    "decision_rule": dec.rule,
                    "match_confidence": match_confidence,
                }
            )

    # 2. Unconsumed E-Invoice rows -> EXTRA_IRN
    for idx, e in enumerate(norm_einv):
        if idx in consumed_einv_indices:
            continue
        e_val = e["value_paise"]
        dec = generate_decision(
            "L1_EXACT",
            confidence="MEDIUM",
        )
        dec = type(dec)(
            what="Extra IRN found on portal — missing in books",
            why=f"IRN {e['irn'][:12]}... registered on IRP but no matching entry exists in accounting software",
            next="Verify physical invoice. Record in books or check for duplicate IRN generation on portal.",
            rule="EINVOICE_EXTRA_IRN",
            confidence="HIGH",
            matched_fields=(),
            differed_fields=("books_entry",),
            normalized_pairs=(),
        )

        results.append(
            {
                "invoice_number": e["invoice_number"],
                "invoice_number_normalized": e["invoice_number_normalized"],
                "gstin": e["gstin"],
                "invoice_date": e["invoice_date"],
                "category": "EXTRA_IRN",
                "book_value": 0.0,
                "einvoice_value": round(e_val / 100.0, 2),
                "value_difference": round(e_val / 100.0, 2),
                "irn": e["irn"],
                "irn_status": e["irn_status"],
                "ack_number": e["ack_number"],
                "ack_date": e["ack_date"],
                "decision_what": dec.what,
                "decision_why": dec.why,
                "decision_next": dec.next,
                "decision_rule": dec.rule,
                "match_confidence": "HIGH",
            }
        )

    # Compute summary metrics
    summary: dict[str, Any] = {
        "total_records": len(results),
        "matched_count": sum(1 for r in results if r["category"] == "MATCHED"),
        "irn_missing_count": sum(1 for r in results if r["category"] == "IRN_MISSING"),
        "irn_cancelled_count": sum(1 for r in results if r["category"] == "IRN_CANCELLED"),
        "extra_irn_count": sum(1 for r in results if r["category"] == "EXTRA_IRN"),
        "value_mismatch_count": sum(1 for r in results if r["category"] == "VALUE_MISMATCH"),
        "matched_value": sum(r["book_value"] for r in results if r["category"] == "MATCHED"),
        "irn_missing_value": sum(r["book_value"] for r in results if r["category"] == "IRN_MISSING"),
        "irn_cancelled_value": sum(r["book_value"] for r in results if r["category"] == "IRN_CANCELLED"),
        "extra_irn_value": sum(r["einvoice_value"] for r in results if r["category"] == "EXTRA_IRN"),
        "value_mismatch_difference": sum(r["value_difference"] for r in results if r["category"] == "VALUE_MISMATCH"),
    }

    return {
        "results": results,
        "summary": summary,
    }
