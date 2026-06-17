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


def _gstr_tax_paise_from_record(rd: dict[str, Any]) -> tuple[int, int, int, int]:
    items = rd.get("items") or []
    if items:
        cgst = sum(int(i.get("cgst_paise") or 0) for i in items)
        sgst = sum(int(i.get("sgst_paise") or 0) for i in items)
        igst = sum(int(i.get("igst_paise") or 0) for i in items)
    else:
        cgst = sgst = igst = 0
    total = cgst + sgst + igst
    return (cgst, sgst, igst, total)


def gstr_db_row_to_matcher_row(row: dict[str, Any]) -> dict[str, Any]:
    """``row`` = ``{id, record_data}`` from ``gstr_records``."""
    rid = row["id"]
    rd: dict[str, Any] = row.get("record_data") or {}
    if not isinstance(rd, dict):
        rd = {}
    sup = (rd.get("supplier_gstin_norm") or rd.get("supplier_gstin") or "").strip()
    inv_raw = rd.get("invoice_number_norm") or rd.get("invoice_number") or ""
    inv = normalize_invoice(str(inv_raw).strip() if inv_raw is not None else None)
    cg, sg, ig, ttp = _gstr_tax_paise_from_record(rd)
    taxable = _gstr_taxable_paise_from_record(rd)
    inv_d = _iso_date(rd.get("invoice_date_norm") or rd.get("invoice_date"))
    return {
        "id": str(rid),
        "supplier_gstin": sup,
        "invoice_number_normalized": inv,
        "invoice_date": inv_d,
        "taxable_amount_paise": int(taxable),
        "cgst_paise": int(cg),
        "sgst_paise": int(sg),
        "igst_paise": int(ig),
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
    inv_raw = rd.get("invoice_number_normalized") or rd.get("invoice_number") or ""
    invn = normalize_invoice(
        str(inv_raw).strip() if inv_raw is not None else None
    )
    inv_d = _iso_date(rd.get("invoice_date"))
    return {
        "id": str(rid),
        "supplier_gstin": gstin,
        "invoice_number_normalized": invn,
        "invoice_date": inv_d,
        "taxable_amount_paise": _pr_stored_paise(rd.get("taxable_amount_paise")),
        "cgst_paise": _pr_stored_paise(rd.get("cgst_paise")),
        "sgst_paise": _pr_stored_paise(rd.get("sgst_paise")),
        "igst_paise": _pr_stored_paise(rd.get("igst_paise")),
        "total_tax_paise": _pr_stored_paise(rd.get("total_tax_paise")),
    }
