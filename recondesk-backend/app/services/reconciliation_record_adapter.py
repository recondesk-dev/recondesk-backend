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
        total = sum(int(i.get("taxable_value_paise") or i.get("taxable_amount_paise") or 0) for i in items)
        if total != 0:
            return total
    for k in ("taxable_amount_paise", "taxable_value_paise", "taxable_paise"):
        if rd.get(k) is not None:
            return int(rd[k] or 0)
    for k in ("taxable_value", "taxable_amount", "txval"):
        if rd.get(k) is not None:
            try:
                return int(round(float(rd[k]) * 100))
            except (ValueError, TypeError):
                pass
    inv_val = int(rd.get("invoice_value_paise") or rd.get("total_amount_paise") or 0)
    tot_tax = int(rd.get("total_tax_paise") or 0)
    if tot_tax == 0:
        tot_tax = (
            int(rd.get("igst_paise") or 0)
            + int(rd.get("cgst_paise") or 0)
            + int(rd.get("sgst_paise") or 0)
            + int(rd.get("cess_paise") or 0)
        )
    if inv_val > 0 and tot_tax >= 0 and inv_val >= tot_tax:
        return inv_val - tot_tax
    return 0


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
    inv_val = int(rd.get("invoice_value_paise") or rd.get("total_amount_paise") or (taxable + ttp) or 0)
    return {
        "id": str(rid),
        "supplier_gstin": sup,
        "supplier_name": supplier_name,
        "invoice_number": str(inv_true_raw).strip() if inv_true_raw else "",
        "invoice_number_normalized": inv,
        "invoice_date": inv_d,
        "taxable_amount_paise": int(taxable),
        "taxable_value_paise": int(taxable),
        "cgst_paise": int(cg),
        "sgst_paise": int(sg),
        "igst_paise": int(ig),
        "cess_paise": int(cs),
        "total_tax_paise": int(ttp if ttp else 0),
        "invoice_value_paise": inv_val,
        "total_amount_paise": inv_val,
        # Carried from gstr2b_parser.py — True when ``supplier_gstin`` above is
        # a best-effort cleaned value that failed strict GSTIN format
        # validation. Matching code must not trust supplier_gstin equality for
        # these records; see execute_phase2_and_3's GSTIN_FORMAT_INVALID pass.
        "gstin_format_invalid": bool(rd.get("gstin_format_invalid", False)),
        "filing_status": (
            str(rd.get("filing_status") or "").strip().upper() or None
        ),
        "doc_type": (
            str(rd.get("doc_type") or rd.get("document_type") or "").strip().upper()
            or None
        ),
        "section": str(rd.get("section") or "").strip().lower() or None,
        "is_amendment": bool(
            rd.get("is_amendment")
            or (
                str(rd.get("section") or "").strip().lower()
                in ("b2ba", "cdnra", "b2cla", "b2csa", "expa")
            )
        ),
        "original_invoice_number": (
            str(
                rd.get("original_invoice_number")
                or (
                    normalize_invoice(str(rd.get("oinum") or rd.get("ont_num") or rd.get("ointnum")).strip())
                    if (rd.get("oinum") or rd.get("ont_num") or rd.get("ointnum"))
                    else ""
                )
            ).strip()
            or None
        ),
        "original_invoice_number_raw": (
            str(
                rd.get("original_invoice_number_raw")
                or rd.get("oinum")
                or rd.get("ont_num")
                or rd.get("ointnum")
                or ""
            ).strip()
            or None
        ),
        "original_invoice_date": _iso_date(
            rd.get("original_invoice_date_norm")
            or rd.get("original_invoice_date")
            or rd.get("oidt")
            or rd.get("ointdt")
        ),
        "supprd": str(rd.get("supprd") or "").strip() or None,
        "ims_status": (
            str(rd.get("ims_status") or "").strip() or "no_action_taken"
        ),
        "itc_available": (
            rd.get("itc_available")
            if isinstance(rd.get("itc_available"), bool)
            else (
                str(rd.get("itcavl") or "Y").strip().upper()[:1] in ("Y", "T", "1")
                if rd.get("itcavl") is not None
                else True
            )
        ),
        "itc_reason": (
            str(
                rd.get("itc_reason")
                or rd.get("rsn")
                or rd.get("reason")
                or rd.get("ineligibility_reason")
                or ""
            ).strip()
            or None
        ),
        "reverse_charge": (
            rd.get("reverse_charge")
            if rd.get("reverse_charge") is not None
            else (rd.get("rchrg") or rd.get("rev") or rd.get("rev_chg"))
        ),
        "reverse_charge_raw": (
            rd.get("reverse_charge")
            if rd.get("reverse_charge") is not None
            else (rd.get("rchrg") or rd.get("rev") or rd.get("rev_chg"))
        ),
        "supply_type": (
            str(rd.get("supply_type") or rd.get("sply_ty") or rd.get("inv_supply_type") or "").strip().upper() or None
        ),
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
    note_no = str(rd.get("note_number") or "").strip().upper() or None
    if not inv_true_raw and note_no:
        inv_true_raw = note_no
    inv_raw_for_norm = rd.get("invoice_number_normalized") or inv_true_raw or ""
    invn = normalize_invoice(
        str(inv_raw_for_norm).strip() if inv_raw_for_norm else None
    )
    inv_d = _iso_date(rd.get("invoice_date"))
    cgst = _pr_stored_paise(rd.get("cgst_paise"))
    sgst = _pr_stored_paise(rd.get("sgst_paise"))
    igst = _pr_stored_paise(rd.get("igst_paise"))
    cess = _pr_stored_paise(rd.get("cess_paise"))
    total_tax = _pr_stored_paise(rd.get("total_tax_paise"))
    if total_tax == 0:
        total_tax = cgst + sgst + igst + cess

    taxable_paise = _pr_stored_paise(rd.get("taxable_amount_paise") or rd.get("taxable_value_paise"))
    note_amt_paise = (
        _pr_stored_paise(rd.get("note_amount_paise"))
        if rd.get("note_amount_paise") is not None
        else None
    )
    if taxable_paise == 0 and note_amt_paise is not None and note_amt_paise != 0:
        taxable_paise = note_amt_paise

    total_amt_raw = _pr_stored_paise(rd.get("total_amount_paise") or rd.get("invoice_value_paise"))
    if taxable_paise == 0 and total_amt_raw != 0 and total_amt_raw >= total_tax:
        taxable_paise = total_amt_raw - total_tax

    orig_inv_raw = (
        rd.get("original_invoice_number")
        or rd.get("original_invoice")
        or rd.get("orig_inv_num")
        or rd.get("against_invoice_number")
        or rd.get("oinum")
        or rd.get("ont_num")
        or ""
    )
    orig_inv_str = str(orig_inv_raw).strip() if orig_inv_raw else ""
    orig_inv_norm = normalize_invoice(orig_inv_str) if orig_inv_str else None

    res = {
        "id": str(rid),
        "supplier_gstin": gstin,
        "vendor_name": vendor_name,
        "invoice_number": str(inv_true_raw).strip() if inv_true_raw else "",
        "invoice_number_normalized": invn,
        "invoice_date": inv_d,
        "taxable_amount_paise": taxable_paise,
        "taxable_value_paise": taxable_paise,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": igst,
        "cess_paise": cess,
        "total_tax_paise": total_tax,
        "itc_eligibility": rd.get("itc_eligibility"),
        "hsn": rd.get("hsn"),
        "doc_type": (
            str(rd.get("invoice_type") or rd.get("document_type") or "")
            .strip()
            .upper()
            or None
        ),
        "note_number": note_no,
        "note_amount_paise": note_amt_paise,
        "pr_note_quarantine": bool(rd.get("pr_note_quarantine")),
        "original_invoice_number": orig_inv_str or None,
        "original_invoice_number_normalized": orig_inv_norm,
        "reverse_charge": (
            rd.get("reverse_charge")
            if rd.get("reverse_charge") is not None
            else (rd.get("rcm") or rd.get("rchrg") or rd.get("reverse_charge_applicable"))
        ),
        "reverse_charge_raw": (
            rd.get("reverse_charge")
            if rd.get("reverse_charge") is not None
            else (rd.get("rcm") or rd.get("rchrg") or rd.get("reverse_charge_applicable"))
        ),
        "supply_type": (
            str(rd.get("supply_type") or "").strip().upper() or None
        ),
    }
    if total_amt_raw != 0:
        res["total_amount_paise"] = total_amt_raw
        res["invoice_value_paise"] = total_amt_raw
    return res
