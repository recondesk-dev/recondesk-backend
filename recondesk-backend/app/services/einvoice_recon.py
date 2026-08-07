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

        # Search candidate pool in e-invoices
        for idx, e in enumerate(norm_einv):
            if idx in consumed_einv_indices:
                continue

            e_inv_norm = e["invoice_number_normalized"]
            e_gstin = e["gstin"]

            # Key comparison: invoice number + gstin (or PAN)
            inv_match = False
            if inv_norm and e_inv_norm and inv_norm == e_inv_norm:
                inv_match = True
            elif inv_norm and e_inv_norm and is_invoice_format_variant(inv_norm, e_inv_norm):
                inv_match = True

            gstin_match = False
            if not gstin or not e_gstin or gstin == e_gstin or same_pan(gstin, e_gstin):
                gstin_match = True

            if inv_match and gstin_match:
                matched_candidate = e
                matched_einv_idx = idx
                break

        if matched_candidate is not None and matched_einv_idx is not None:
            consumed_einv_indices.add(matched_einv_idx)
            e_val = matched_candidate["value_paise"]
            val_diff = abs(b_val - e_val)
            irn_status = matched_candidate["irn_status"]

            if irn_status.lower() == "cancelled":
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
                category = "MATCHED"
                dec = generate_decision(
                    "L1_EXACT",
                    matched_fields=("invoice_number", "gstin", "amount"),
                )
                # Customize what for e-invoice matched
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

            results.append(
                {
                    "invoice_number": b["invoice_number"],
                    "invoice_number_normalized": b["invoice_number_normalized"],
                    "gstin": b["gstin"],
                    "invoice_date": b["invoice_date"],
                    "category": category,
                    "book_value": round(b_val / 100.0, 2),
                    "einvoice_value": round(e_val / 100.0, 2),
                    "value_difference": round(val_diff / 100.0, 2),
                    "irn": matched_candidate["irn"],
                    "irn_status": matched_candidate["irn_status"],
                    "ack_number": matched_candidate["ack_number"],
                    "ack_date": matched_candidate["ack_date"],
                    "decision_what": dec.what,
                    "decision_why": dec.why,
                    "decision_next": dec.next,
                    "decision_rule": dec.rule,
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

            results.append(
                {
                    "invoice_number": b["invoice_number"],
                    "invoice_number_normalized": b["invoice_number_normalized"],
                    "gstin": b["gstin"],
                    "invoice_date": b["invoice_date"],
                    "category": category,
                    "book_value": round(b_val / 100.0, 2),
                    "einvoice_value": 0.0,
                    "value_difference": round(b_val / 100.0, 2),
                    "irn": None,
                    "irn_status": None,
                    "ack_number": None,
                    "ack_date": None,
                    "decision_what": dec.what,
                    "decision_why": dec.why,
                    "decision_next": dec.next,
                    "decision_rule": dec.rule,
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
