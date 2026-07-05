"""Map ``gstr_records`` / ``pr_records`` table rows to matcher record dicts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.services.matcher import normalize_invoice


def _iso_date(val: Any) -> str | None:
    if val is None or val == "":
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, datetime):
        return val.date().isoformat()
    s = str(val).strip()
    if not s:
        return None
    if "T" in s:
        s = s[:10]
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except (ValueError, TypeError):
        return s


def _gstr_taxable_paise_from_record(rd: dict[str, Any]) -> int:
    items = rd.get("items") or []
    if items:
        return sum(int(i.get("taxable_value_paise") or 0) for i in items)
    return int(rd.get("invoice_value_paise") or 0)


def _gstr_tax_paise_from_record(rd: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """Return (cgst, sgst, igst, cess, total) from GSTR record_data.

    Strategy:
    1. If ``items`` array is present and non-empty, sum component paise from items.
    2. Otherwise fall back to top-level ``*_paise`` fields on the record itself
       (some normalised / synthetic records carry tax directly at root level).
    3. Always include cess in the total so Missed ITC is never understated.
    """
    items = rd.get("items") or []
    cgst, sgst, igst, cess = 0, 0, 0, 0
    if items:
        cgst = sum(int(i.get("cgst_paise") or 0) for i in items)
        sgst = sum(int(i.get("sgst_paise") or 0) for i in items)
        igst = sum(int(i.get("igst_paise") or 0) for i in items)
        cess = sum(int(i.get("cess_paise") or 0) for i in items)
    
    total = cgst + sgst + igst + cess
    if total == 0:
        # Fallback: top-level tax fields (e.g. pre-computed or synthetic records)
        cgst = int(rd.get("cgst_paise") or rd.get("cgst_amount") or 0)
        sgst = int(rd.get("sgst_paise") or rd.get("sgst_amount") or 0)
        igst = int(rd.get("igst_paise") or rd.get("igst_amount") or 0)
        cess = int(rd.get("cess_paise") or rd.get("cess_amount") or 0)
        total = cgst + sgst + igst + cess

    if total == 0:
        total = int(rd.get("total_tax_paise") or 0)
        if total == 0:
            inv_val = int(rd.get("invoice_value_paise") or 0)
            tax_val = int(rd.get("taxable_value_paise") or _gstr_taxable_paise_from_record(rd) or 0)
            if inv_val > tax_val and tax_val > 0:
                total = inv_val - tax_val

    return (cgst, sgst, igst, cess, total)


def gstr_db_row_to_matcher_row(row: dict[str, Any]) -> dict[str, Any]:
    """``row`` = ``{id, record_data}`` from ``gstr_records``."""
    rid = row["id"]
    rd: dict[str, Any] = row.get("record_data") or {}
    if not isinstance(rd, dict):
        rd = {}
    sup = (rd.get("supplier_gstin_norm") or rd.get("supplier_gstin") or "").strip()
    supplier_name = str(rd.get("supplier_name") or "").strip()
    inv_true_raw = rd.get("invoice_number_raw") or rd.get("invoice_number") or ""
    inv_raw_for_norm = rd.get("invoice_number_norm") or inv_true_raw or ""
    inv = normalize_invoice(str(inv_raw_for_norm).strip() if inv_raw_for_norm else None)
    cg, sg, ig, cs, ttp = _gstr_tax_paise_from_record(rd)
    taxable = _gstr_taxable_paise_from_record(rd)
    inv_d = _iso_date(rd.get("invoice_date_norm") or rd.get("invoice_date"))
    return {
        "id": str(rid),
        "supplier_gstin": sup,
        "supplier_name": supplier_name,
        "invoice_number": str(inv_true_raw).strip() if inv_true_raw else "",
        "invoice_number_normalized": inv,
        "invoice_date": inv_d,
        "taxable_amount_paise": int(taxable),
        "cgst_paise": int(cg),
        "sgst_paise": int(sg),
        "igst_paise": int(ig),
        "cess_paise": int(cs),
        "total_tax_paise": int(ttp if ttp else 0),
    }


def _pr_stored_paise(x: object) -> int:
    """PR parser stores true paise in ``*_paise`` fields."""
    if x is None:
        return 0
    return int(x)


def pr_db_row_to_matcher_row(row: dict[str, Any]) -> dict[str, Any]:
    """``row`` = ``{id, record_data}`` from ``pr_records``."""
    rid = row["id"]
    rd: dict[str, Any] = row.get("record_data") or {}
    if not isinstance(rd, dict):
        rd = {}
    gstin = (rd.get("gstin") or rd.get("supplier_gstin") or "").strip()
    vendor_name = str(rd.get("supplier_name") or "").strip()
    inv_true_raw = rd.get("invoice_number") or ""
    inv_raw_for_norm = rd.get("invoice_number_normalized") or inv_true_raw or ""
    invn = normalize_invoice(
        str(inv_raw_for_norm).strip() if inv_raw_for_norm else None
    )
    inv_d = _iso_date(rd.get("invoice_date"))
    cgst = _pr_stored_paise(rd.get("cgst_paise"))
    sgst = _pr_stored_paise(rd.get("sgst_paise"))
    igst = _pr_stored_paise(rd.get("igst_paise"))
    cess = _pr_stored_paise(rd.get("cess_paise"))
    # total_tax_paise must be derived symmetrically with the GSTR adapter:
    # prefer the stored value, but fall back to summing components when the PR
    # record_data has no top-level total_tax_paise (e.g. uploads that only carry
    # separate IGST/CGST/SGST columns). Without this fallback the PR side of a
    # genuine match projects total_tax_paise=0 on the read path, so the matched
    # decision computes ttd = gstr_tax - 0 = the full invoice tax, surfacing a
    # fabricated "discrepancy" equal to the row's own Amount on the Matched tab.
    total_tax = _pr_stored_paise(rd.get("total_tax_paise"))
    if total_tax == 0:
        total_tax = cgst + sgst + igst + cess
    return {
        "id": str(rid),
        "supplier_gstin": gstin,
        "vendor_name": vendor_name,
        "invoice_number": str(inv_true_raw).strip() if inv_true_raw else "",
        "invoice_number_normalized": invn,
        "invoice_date": inv_d,
        "taxable_amount_paise": _pr_stored_paise(rd.get("taxable_amount_paise")),
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": igst,
        "cess_paise": cess,
        "total_tax_paise": total_tax,
    }
