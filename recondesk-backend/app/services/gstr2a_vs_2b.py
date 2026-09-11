"""GSTR-2A vs GSTR-2B Delta Reconciliation Engine.

Compares real-time supplier filings in GSTR-2A against the locked monthly GSTR-2B statement.
Identifies late filings beyond the 13th cutoff date, explains deferred ITC,
flags portal lags, and detects post-generation invoice value amendments.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from app.services.matcher import normalize_invoice

logger = logging.getLogger(__name__)

# Amount tolerance: ±1% (consistent with L2 matching) and ₹1 (100 paise) rounding
AMOUNT_TOLERANCE_PCT = 0.01
AMOUNT_TOLERANCE_PAISE = 100

# Category Constants
IN_BOTH = "IN_BOTH"
LATE_FILED = "LATE_FILED"
FILED_NOT_REFLECTED = "FILED_NOT_REFLECTED"
IN_2B_NOT_2A = "IN_2B_NOT_2A"
VALUE_MISMATCH = "VALUE_MISMATCH"

ALL_CATEGORIES = (
    IN_BOTH,
    LATE_FILED,
    FILED_NOT_REFLECTED,
    IN_2B_NOT_2A,
    VALUE_MISMATCH,
)


def _parse_period_year_month(period: str) -> tuple[int, int]:
    """Extract (year, month) from period string ('YYYY-MM' or 'MMYYYY')."""
    s = str(period).strip().replace("-", "").replace("/", "")
    if len(s) == 6 and s.isdigit():
        if s.startswith(("20", "19")):
            # YYYYMM
            return int(s[:4]), int(s[4:6])
        else:
            # MMYYYY
            return int(s[2:6]), int(s[:2])
    if len(period) >= 7 and period[4] == "-":
        parts = period.split("-")
        return int(parts[0]), int(parts[1])
    today = date.today()
    return today.year, today.month


def get_default_cutoff_date(period: str) -> date:
    """Default cutoff date is the 13th of the period month."""
    year, month = _parse_period_year_month(period)
    return date(year, month, 13)


def get_next_month_period(period: str) -> str:
    """Calculate the subsequent tax period (YYYY-MM)."""
    year, month = _parse_period_year_month(period)
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def _parse_date(val: Any) -> date | None:
    """Safely parse date or string into datetime.date."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "nan"):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _extract_amount_paise(rec: Mapping[str, Any], *keys: str) -> int:
    """Extract integer paise amount from record dict."""
    # Check if record has nested items list (e.g. from parse_gstr2b)
    if "items" in rec and isinstance(rec["items"], list) and len(rec["items"]) > 0:
        if any(k in ("taxable_amount_paise", "taxable_value_paise", "taxable_value") for k in keys):
            item_taxable = sum(int(it.get("taxable_value_paise") or 0) for it in rec["items"] if isinstance(it, dict))
            if item_taxable != 0:
                return item_taxable

    for k in keys:
        if k in rec and rec[k] is not None:
            v = rec[k]
            try:
                if isinstance(v, (int, float)):
                    # If field name already ends with _paise, assume it is in paise
                    if k.endswith("_paise") or k in ("total_tax_paise", "taxable_amount_paise", "taxable_value_paise"):
                        return int(v)
                    return int(round(float(v) * 100))
                s = str(v).strip()
                if s and s.lower() not in ("null", "none", "nan"):
                    if k.endswith("_paise"):
                        return int(float(s))
                    return int(round(float(s) * 100))
            except (ValueError, TypeError):
                continue
    return 0


def _extract_total_tax(rec: Mapping[str, Any]) -> int:
    """Extract total tax in paise from record."""
    if "items" in rec and isinstance(rec["items"], list) and len(rec["items"]) > 0:
        tax_sum = sum(
            int(it.get("igst_paise") or 0)
            + int(it.get("cgst_paise") or 0)
            + int(it.get("sgst_paise") or 0)
            + int(it.get("cess_paise") or 0)
            for it in rec["items"]
            if isinstance(it, dict)
        )
        if tax_sum != 0:
            return tax_sum

    tot = _extract_amount_paise(rec, "total_tax", "total_tax_paise")
    if tot != 0:
        return tot
    igst = _extract_amount_paise(rec, "igst", "igst_paise")
    cgst = _extract_amount_paise(rec, "cgst", "cgst_paise")
    sgst = _extract_amount_paise(rec, "sgst", "sgst_paise")
    cess = _extract_amount_paise(rec, "cess", "cess_paise")
    return igst + cgst + sgst + cess


def _extract_record_identifiers(rec: Mapping[str, Any]) -> tuple[str, str, str]:
    """Extract (supplier_gstin, invoice_number_raw, invoice_number_normalized)."""
    rd = rec.get("record_data") if isinstance(rec.get("record_data"), dict) else rec

    gstin = str(
        rd.get("supplier_gstin")
        or rd.get("gstin")
        or rd.get("supplier_gstin_raw")
        or rd.get("ctin")
        or ""
    ).strip().upper()

    inv_raw = str(
        rd.get("invoice_number_raw")
        or rd.get("invoice_number")
        or rd.get("inum")
        or rd.get("nt_num")
        or rd.get("inv_no")
        or ""
    ).strip()

    inv_norm = rd.get("invoice_number_normalized") or normalize_invoice(inv_raw)

    return gstin, inv_raw, inv_norm


def _amounts_match(val_a: int, val_b: int) -> bool:
    """Return True if amounts match within ±1% or Rs 1 rounding tolerance."""
    diff = abs(abs(val_a) - abs(val_b))
    base = max(abs(val_a), abs(val_b))
    tolerance = max(AMOUNT_TOLERANCE_PAISE, int(round(base * AMOUNT_TOLERANCE_PCT)))
    return diff <= tolerance


def reconcile_2a_vs_2b(
    gstr2a_records: Sequence[Mapping[str, Any]],
    gstr2b_records: Sequence[Mapping[str, Any]],
    period: str,
    cutoff_date: date | str | None = None,
) -> dict[str, Any]:
    """Reconcile GSTR-2A records against GSTR-2B records for a tax period.

    Parameters
    ----------
    gstr2a_records : Sequence[Mapping]
        Parsed GSTR-2A invoice/note records (from parse_gstr2a).
    gstr2b_records : Sequence[Mapping]
        GSTR-2B records (from parse_gstr2b or DB rows).
    period : str
        Tax period ('YYYY-MM' or 'MMYYYY').
    cutoff_date : date | str | None
        Statutory cutoff date for GSTR-1 filing (defaults to 13th of period month).

    Returns
    -------
    dict with:
      - 'results': list of categorized delta records
      - 'summary': dictionary of counts and aggregated deferred/unresolved ITC totals
    """
    period_norm = period.strip()
    if len(period_norm) == 6 and period_norm.isdigit() and not period_norm.startswith(("20", "19")):
        # MMYYYY -> YYYY-MM
        period_norm = f"{period_norm[2:]}-{period_norm[:2]}"

    if cutoff_date is not None:
        parsed_cutoff = _parse_date(cutoff_date)
        effective_cutoff = parsed_cutoff if parsed_cutoff else get_default_cutoff_date(period_norm)
    else:
        effective_cutoff = get_default_cutoff_date(period_norm)

    next_month_2b_str = get_next_month_period(period_norm)

    # 1. Index GSTR-2B records by (gstin, normalized_invoice)
    gstr2b_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in gstr2b_records:
        gstin, inv_raw, inv_norm = _extract_record_identifiers(r)
        if not gstin or not inv_norm:
            continue
        rd = r.get("record_data") if isinstance(r.get("record_data"), dict) else r
        doc_type_2b = str(
            rd.get("doc_type")
            or rd.get("document_type")
            or ("CREDIT_NOTE" if rd.get("section") == "cdnr" else "INVOICE")
        ).strip().upper()
        section_2b = str(rd.get("section") or "b2b").strip().lower()
        is_amendment_2b = bool(rd.get("is_amendment", False))

        key = (gstin, inv_norm)
        if key not in gstr2b_index:
            gstr2b_index[key] = []
        gstr2b_index[key].append({
            "record": r,
            "record_data": rd,
            "gstin": gstin,
            "invoice_number": inv_raw,
            "invoice_number_normalized": inv_norm,
            "invoice_date": _parse_date(rd.get("invoice_date") or rd.get("idt")),
            "taxable_value": _extract_amount_paise(rd, "taxable_amount_paise", "taxable_value_paise", "taxable_value"),
            "total_tax": _extract_total_tax(rd),
            "doc_type": doc_type_2b,
            "section": section_2b,
            "is_amendment": is_amendment_2b,
        })

    results: list[dict[str, Any]] = []
    matched_2b_keys: set[tuple[str, str]] = set()

    total_2a = len(gstr2a_records)
    total_2b = len(gstr2b_records)

    # 2. Iterate through GSTR-2A records
    for r2a in gstr2a_records:
        gstin_2a, inv_raw_2a, inv_norm_2a = _extract_record_identifiers(r2a)
        rd_2a = r2a.get("record_data") if isinstance(r2a.get("record_data"), dict) else r2a

        doc_type_2a = str(
            rd_2a.get("doc_type")
            or rd_2a.get("document_type")
            or ("CREDIT_NOTE" if rd_2a.get("section") == "cdnr" else "INVOICE")
        ).strip().upper()
        section_2a = str(rd_2a.get("section") or "b2b").strip().lower()
        is_amendment_2a = bool(rd_2a.get("is_amendment", False))

        inv_date_2a = _parse_date(rd_2a.get("invoice_date") or rd_2a.get("idt"))
        filing_date = _parse_date(
            rd_2a.get("filing_date")
            or rd_2a.get("fldtr1")
            or rd_2a.get("supfildt")
            or rd_2a.get("fldt")
        )
        taxable_2a = _extract_amount_paise(rd_2a, "taxable_amount_paise", "taxable_value_paise", "taxable_value")
        tax_2a = _extract_total_tax(rd_2a)

        key = (gstin_2a, inv_norm_2a)
        candidates_2b = gstr2b_index.get(key, [])

        if candidates_2b:
            matched_2b_keys.add(key)
            # Pick best candidate if multiple
            cand_2b = candidates_2b[0]
            taxable_2b = cand_2b["taxable_value"]
            tax_2b = cand_2b["total_tax"]
            raw_2b_rec = cand_2b["record"]

            effective_doc_type = cand_2b.get("doc_type") or doc_type_2a
            effective_section = cand_2b.get("section") or section_2a
            effective_amendment = cand_2b.get("is_amendment") or is_amendment_2a

            val_2a_rupees = round(taxable_2a / 100.0, 2)
            val_2b_rupees = round(taxable_2b / 100.0, 2)
            tax_2a_rupees = round(tax_2a / 100.0, 2)
            tax_2b_rupees = round(tax_2b / 100.0, 2)
            f_date_str = filing_date.isoformat() if filing_date else "on time"
            c_date_str = effective_cutoff.isoformat()

            if _amounts_match(taxable_2a, taxable_2b):
                # Category: IN_BOTH
                results.append({
                    "category": IN_BOTH,
                    "supplier_gstin": gstin_2a,
                    "invoice_number": inv_raw_2a,
                    "invoice_date": inv_date_2a.isoformat() if inv_date_2a else None,
                    "filing_date": filing_date.isoformat() if filing_date else None,
                    "cutoff_date": c_date_str,
                    "days_late": 0,
                    "taxable_value_2a": val_2a_rupees,
                    "taxable_value_2b": val_2b_rupees,
                    "tax_value_2a": tax_2a_rupees,
                    "tax_value_2b": tax_2b_rupees,
                    "itc_at_risk_paise": 0,
                    "next_month_2b": None,
                    "doc_type": effective_doc_type,
                    "section": effective_section,
                    "is_amendment": effective_amendment,
                    "decision_what": "Invoice present in both 2A and 2B. ITC eligible this month.",
                    "decision_why": f"Supplier filed on time ({f_date_str}) and invoice reflected in locked 2B.",
                    "decision_next": "Claim ITC in GSTR-3B for this period.",
                    "raw_2a_record": dict(r2a),
                    "raw_2b_record": dict(raw_2b_rec),
                })
            else:
                # Category: VALUE_MISMATCH
                diff_paise = abs(taxable_2a - taxable_2b)
                tax_diff_paise = abs(tax_2a - tax_2b)
                at_risk = tax_diff_paise if tax_diff_paise > 0 else diff_paise
                results.append({
                    "category": VALUE_MISMATCH,
                    "supplier_gstin": gstin_2a,
                    "invoice_number": inv_raw_2a,
                    "invoice_date": inv_date_2a.isoformat() if inv_date_2a else None,
                    "filing_date": filing_date.isoformat() if filing_date else None,
                    "cutoff_date": c_date_str,
                    "days_late": 0,
                    "taxable_value_2a": val_2a_rupees,
                    "taxable_value_2b": val_2b_rupees,
                    "tax_value_2a": tax_2a_rupees,
                    "tax_value_2b": tax_2b_rupees,
                    "itc_at_risk_paise": at_risk,
                    "next_month_2b": None,
                    "doc_type": effective_doc_type,
                    "section": effective_section,
                    "is_amendment": effective_amendment,
                    "decision_what": f"Taxable value mismatch: 2A has ₹{val_2a_rupees:,.2f} vs 2B has ₹{val_2b_rupees:,.2f}.",
                    "decision_why": "Supplier likely amended invoice value in a subsequent return or amendment table.",
                    "decision_next": "Claim ITC based on 2B value. Reconcile difference with supplier.",
                    "raw_2a_record": dict(r2a),
                    "raw_2b_record": dict(raw_2b_rec),
                })
        else:
            # Invoice in 2A but NOT in 2B
            val_2a_rupees = round(taxable_2a / 100.0, 2)
            tax_2a_rupees = round(tax_2a / 100.0, 2)
            is_late = bool(filing_date and filing_date > effective_cutoff)
            c_date_str = effective_cutoff.isoformat()

            if is_late:
                days_late = (filing_date - effective_cutoff).days
                f_date_str = filing_date.isoformat()
                results.append({
                    "category": LATE_FILED,
                    "supplier_gstin": gstin_2a,
                    "invoice_number": inv_raw_2a,
                    "invoice_date": inv_date_2a.isoformat() if inv_date_2a else None,
                    "filing_date": f_date_str,
                    "cutoff_date": c_date_str,
                    "days_late": days_late,
                    "taxable_value_2a": val_2a_rupees,
                    "taxable_value_2b": None,
                    "tax_value_2a": tax_2a_rupees,
                    "tax_value_2b": None,
                    "itc_at_risk_paise": tax_2a,
                    "next_month_2b": next_month_2b_str,
                    "doc_type": doc_type_2a,
                    "section": section_2a,
                    "is_amendment": is_amendment_2a,
                    "decision_what": f"Supplier filed GSTR-1 on {f_date_str} — {days_late} days after cutoff ({c_date_str}). ITC deferred to {next_month_2b_str}.",
                    "decision_why": "GSTR-2B was locked on the 14th with invoices filed up to the 13th. Invoices filed after the 13th are excluded from this month's 2B.",
                    "decision_next": f"Do NOT claim ITC this month — Rule 88D will flag mismatch. Claim in {next_month_2b_str} GSTR-3B once 2B updates.",
                    "raw_2a_record": dict(r2a),
                    "raw_2b_record": None,
                })
            else:
                f_desc = f"on {filing_date.isoformat()}" if filing_date else "on time"
                results.append({
                    "category": FILED_NOT_REFLECTED,
                    "supplier_gstin": gstin_2a,
                    "invoice_number": inv_raw_2a,
                    "invoice_date": inv_date_2a.isoformat() if inv_date_2a else None,
                    "filing_date": filing_date.isoformat() if filing_date else None,
                    "cutoff_date": c_date_str,
                    "days_late": 0,
                    "taxable_value_2a": val_2a_rupees,
                    "taxable_value_2b": None,
                    "tax_value_2a": tax_2a_rupees,
                    "tax_value_2b": None,
                    "itc_at_risk_paise": tax_2a,
                    "next_month_2b": None,
                    "doc_type": doc_type_2a,
                    "section": section_2a,
                    "is_amendment": is_amendment_2a,
                    "decision_what": f"Invoice filed {f_desc} (within cutoff {c_date_str}) but missing from GSTR-2B.",
                    "decision_why": "Possible GST portal processing delay, supplier cancelled invoice before 2B generation, or technical lag.",
                    "decision_next": "Raise grievance on GST portal or wait for next 2B re-generation. Do not claim until reflected.",
                    "raw_2a_record": dict(r2a),
                    "raw_2b_record": None,
                })

    # 3. Invoices in 2B but NOT in 2A (IN_2B_NOT_2A)
    for key, cands in gstr2b_index.items():
        if key in matched_2b_keys:
            continue
        for cand in cands:
            taxable_2b = cand["taxable_value"]
            tax_2b = cand["total_tax"]
            val_2b_rupees = round(taxable_2b / 100.0, 2)
            tax_2b_rupees = round(tax_2b / 100.0, 2)
            raw_2b_rec = cand["record"]
            results.append({
                "category": IN_2B_NOT_2A,
                "supplier_gstin": cand["gstin"],
                "invoice_number": cand["invoice_number"],
                "invoice_date": cand["invoice_date"].isoformat() if cand["invoice_date"] else None,
                "filing_date": None,
                "cutoff_date": effective_cutoff.isoformat(),
                "days_late": 0,
                "taxable_value_2a": None,
                "taxable_value_2b": val_2b_rupees,
                "tax_value_2a": None,
                "tax_value_2b": tax_2b_rupees,
                "itc_at_risk_paise": tax_2b,
                "next_month_2b": None,
                "doc_type": cand.get("doc_type") or "INVOICE",
                "section": cand.get("section") or "b2b",
                "is_amendment": cand.get("is_amendment", False),
                "decision_what": "Invoice present in 2B but absent from 2A.",
                "decision_why": "Supplier may have amended or cancelled invoice after 2B was generated, or 2A fetch is incomplete.",
                "decision_next": "Verify invoice status with supplier before claiming ITC.",
                "raw_2a_record": None,
                "raw_2b_record": dict(raw_2b_rec),
            })

    # 4. Compute summary metrics
    in_both_count = sum(1 for r in results if r["category"] == IN_BOTH)
    late_filed_count = sum(1 for r in results if r["category"] == LATE_FILED)
    filed_not_reflected_count = sum(1 for r in results if r["category"] == FILED_NOT_REFLECTED)
    in_2b_not_2a_count = sum(1 for r in results if r["category"] == IN_2B_NOT_2A)
    value_mismatch_count = sum(1 for r in results if r["category"] == VALUE_MISMATCH)

    total_itc_deferred = sum(
        int(r.get("itc_at_risk_paise") or 0)
        for r in results
        if r["category"] == LATE_FILED
    )
    total_itc_unresolved = sum(
        int(r.get("itc_at_risk_paise") or 0)
        for r in results
        if r["category"] in (FILED_NOT_REFLECTED, IN_2B_NOT_2A, VALUE_MISMATCH)
    )

    doc_type_breakdown: dict[str, int] = {}
    for r in results:
        dt = r.get("doc_type") or "INVOICE"
        doc_type_breakdown[dt] = doc_type_breakdown.get(dt, 0) + 1

    summary = {
        "total_records": len(results),
        "unique_union_count": len(results),
        "total_2a": total_2a,
        "total_2b": total_2b,
        "in_both": in_both_count,
        "in_both_count": in_both_count,
        "late_filed": late_filed_count,
        "late_filed_count": late_filed_count,
        "filed_not_reflected": filed_not_reflected_count,
        "filed_not_reflected_count": filed_not_reflected_count,
        "in_2b_not_2a": in_2b_not_2a_count,
        "in_2b_not_2a_count": in_2b_not_2a_count,
        "value_mismatch": value_mismatch_count,
        "value_mismatch_count": value_mismatch_count,
        "value_mismatch_is_subset": True,
        "subset_note": f"{value_mismatch_count} of the {in_both_count} invoices present in both have value differences.",
        "total_itc_deferred_paise": total_itc_deferred,
        "deferred_itc_paise": total_itc_deferred,
        "deferred_itc_rupees": round(total_itc_deferred / 100.0, 2),
        "total_itc_unresolved_paise": total_itc_unresolved,
        "unresolved_itc_paise": total_itc_unresolved,
        "unresolved_itc_rupees": round(total_itc_unresolved / 100.0, 2),
        "doc_type_breakdown": doc_type_breakdown,
    }

    return results, summary
