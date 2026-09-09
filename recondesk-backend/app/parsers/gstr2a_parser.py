"""GSTR-2A JSON Parser.

Parses raw GSTR-2A JSON (from Sandbox GSP API or manual export) into normalized
record dicts compatible with GSTR-2B parser output and the delta reconciliation engine.

Supported sections:
- b2b: B2B invoices from registered suppliers
- cdna: Credit/debit notes (credit notes inverted to negative values)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Mapping

from app.services.matcher import normalize_invoice
from app.services.normalizer import (
    NormalizationError,
    normalize_amount,
    normalize_date,
    normalize_gstin,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "gstr2a_v1"


class ParseError(Exception):
    """Raised when GSTR-2A payload cannot be parsed."""
    pass


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Return the first key present in mapping with a non-None value."""
    for k in keys:
        if k in mapping and mapping[k] is not None:
            return mapping[k]
    return None


def _parse_iso_date(raw: Any) -> str | None:
    """Normalize date string to YYYY-MM-DD."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    s = str(raw).strip()
    if not s or s.lower() in ("null", "none", "nan"):
        return None
    try:
        norm = normalize_date(s)
        return norm.value.isoformat()
    except Exception:
        pass

    # Fallback date parsing
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    return s[:10] if len(s) >= 10 else s


def _amount_to_paise(val: Any) -> int:
    """Convert amount (rupees float/int/str) to integer paise."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(round(float(val) * 100))
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "nan"):
        return 0
    try:
        norm = normalize_amount(s)
        return int(norm.value)
    except Exception:
        try:
            clean = re.sub(r"[^\d.-]", "", s)
            return int(round(float(clean) * 100))
        except Exception:
            return 0


def _extract_items_tax(inv_or_note: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """Sum (taxable, igst, cgst, sgst, cess) in paise from line items or root fields."""
    items = inv_or_note.get("itms") or inv_or_note.get("items")
    if isinstance(items, list) and items:
        txval = 0
        igst = 0
        cgst = 0
        sgst = 0
        cess = 0
        for itm in items:
            if not isinstance(itm, dict):
                continue
            itm_det = itm.get("itm_det") if isinstance(itm.get("itm_det"), dict) else itm
            txval += _amount_to_paise(_first_present(itm_det, "txval", "taxable_value", "taxable_amount"))
            igst += _amount_to_paise(_first_present(itm_det, "iamt", "igst", "igst_amount"))
            cgst += _amount_to_paise(_first_present(itm_det, "camt", "cgst", "cgst_amount"))
            sgst += _amount_to_paise(_first_present(itm_det, "samt", "sgst", "sgst_amount"))
            cess += _amount_to_paise(_first_present(itm_det, "csamt", "cess", "cess_amount"))
        return txval, igst, cgst, sgst, cess

    # Root level fields fallback
    txval = _amount_to_paise(_first_present(inv_or_note, "txval", "taxable_value", "taxable_amount", "val"))
    igst = _amount_to_paise(_first_present(inv_or_note, "iamt", "igst", "igst_amount"))
    cgst = _amount_to_paise(_first_present(inv_or_note, "camt", "cgst", "cgst_amount"))
    sgst = _amount_to_paise(_first_present(inv_or_note, "samt", "sgst", "sgst_amount"))
    cess = _amount_to_paise(_first_present(inv_or_note, "csamt", "cess", "cess_amount"))
    return txval, igst, cgst, sgst, cess


def _unwrap_payload(raw_data: Any) -> dict[str, Any]:
    """Unwrap JSON string, bytes, or dictionary into standard root dictionary."""
    if isinstance(raw_data, (bytes, bytearray)):
        raw_data = raw_data.decode("utf-8", errors="replace")
    if isinstance(raw_data, str):
        try:
            parsed = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise ParseError(f"Invalid GSTR-2A JSON: {exc.msg}") from exc
    elif isinstance(raw_data, dict):
        parsed = raw_data
    else:
        raise ParseError(f"Expected dict, str, or bytes, got {type(raw_data).__name__}")

    if not isinstance(parsed, dict):
        raise ParseError("GSTR-2A root JSON must be an object")

    # If data is under a 'data' envelope key, unwrap it
    if "data" in parsed and isinstance(parsed["data"], dict):
        data_block = parsed["data"]
        # Merge top-level metadata if present
        for k, v in parsed.items():
            if k != "data" and k not in data_block:
                data_block[k] = v
        return data_block

    return parsed


def _extract_section_suppliers(root: dict[str, Any], section_key: str) -> list[dict[str, Any]]:
    """Extract list of supplier blocks for a section (e.g. 'b2b', 'cdna')."""
    sec_data = root.get(section_key)
    if isinstance(sec_data, dict):
        if "data" in sec_data and isinstance(sec_data["data"], dict):
            sec_data = sec_data["data"].get(section_key) or sec_data["data"]
        elif section_key in sec_data and isinstance(sec_data[section_key], list):
            sec_data = sec_data[section_key]
        elif "value" in sec_data and isinstance(sec_data["value"], list):
            sec_data = sec_data["value"]

    if isinstance(sec_data, list):
        return [s for s in sec_data if isinstance(s, dict)]
    return []


def parse_gstr2a(raw_data: Any) -> list[dict[str, Any]]:
    """Parse raw GSTR-2A JSON into normalized record dictionaries.

    Parameters
    ----------
    raw_data : dict | str | bytes
        Raw GSTR-2A JSON from Sandbox GSP or portal export.

    Returns
    -------
    list[dict[str, Any]]
        List of normalized invoice/note records matching GSTR-2B field semantics.
    """
    root = _unwrap_payload(raw_data)
    records: list[dict[str, Any]] = []

    # 1. Parse B2B Section
    b2b_suppliers = _extract_section_suppliers(root, "b2b")
    for sup in b2b_suppliers:
        ctin_raw = _first_present(sup, "ctin", "supplier_gstin", "gstin") or ""
        supplier_name = str(_first_present(sup, "cname", "supplier_name", "trade_name") or "").strip()
        try:
            supplier_gstin = normalize_gstin(str(ctin_raw).strip()) if ctin_raw else ""
        except NormalizationError:
            supplier_gstin = str(ctin_raw).strip().upper()

        invoices = sup.get("inv") or sup.get("invoices") or []
        if not isinstance(invoices, list):
            continue

        for inv in invoices:
            if not isinstance(inv, dict):
                continue

            inv_raw = str(_first_present(inv, "inum", "invoice_number", "inv_no") or "").strip()
            if not inv_raw:
                continue

            inv_norm = normalize_invoice(inv_raw)
            inv_date = _parse_iso_date(_first_present(inv, "idt", "invoice_date", "dt"))
            filing_date = _parse_iso_date(_first_present(inv, "fldtr1", "fldt", "supfildt", "filing_date", "fld_dt"))
            gstr1_period = str(_first_present(inv, "supprd", "gstr1_period", "rtnprd", "fp", "period") or "").strip()
            pos = str(_first_present(inv, "pos", "place_of_supply") or "").strip()
            rchrg = str(_first_present(inv, "rchrg", "reverse_charge") or "N").strip().upper() == "Y"
            inv_typ = str(_first_present(inv, "inv_typ", "invoice_type") or "R").strip().upper()

            txval_paise, igst_paise, cgst_paise, sgst_paise, cess_paise = _extract_items_tax(inv)
            total_tax_paise = igst_paise + cgst_paise + sgst_paise + cess_paise
            inv_val_paise = _amount_to_paise(_first_present(inv, "val", "total_amount", "invoice_value")) or (txval_paise + total_tax_paise)

            records.append({
                "supplier_gstin": supplier_gstin,
                "supplier_gstin_raw": str(ctin_raw).strip(),
                "supplier_name": supplier_name,
                "invoice_number": inv_raw,
                "invoice_number_raw": inv_raw,
                "invoice_number_normalized": inv_norm,
                "invoice_date": inv_date,
                "taxable_value": txval_paise,
                "taxable_amount_paise": txval_paise,
                "igst": igst_paise,
                "cgst": cgst_paise,
                "sgst": sgst_paise,
                "cess": cess_paise,
                "igst_paise": igst_paise,
                "cgst_paise": cgst_paise,
                "sgst_paise": sgst_paise,
                "cess_paise": cess_paise,
                "total_tax": total_tax_paise,
                "total_tax_paise": total_tax_paise,
                "invoice_value_paise": inv_val_paise,
                "filing_date": filing_date,
                "gstr1_period": gstr1_period,
                "pos": pos,
                "reverse_charge": rchrg,
                "doc_type": "INVOICE",
                "section": "b2b",
                "invoice_type": inv_typ,
                "raw_data": inv,
            })

    # 2. Parse CDNA Section (Credit/Debit Notes)
    cdna_suppliers = _extract_section_suppliers(root, "cdna")
    if not cdna_suppliers:
        cdna_suppliers = _extract_section_suppliers(root, "cdn") or _extract_section_suppliers(root, "cdnr")

    for sup in cdna_suppliers:
        ctin_raw = _first_present(sup, "ctin", "supplier_gstin", "gstin") or ""
        supplier_name = str(_first_present(sup, "cname", "supplier_name", "trade_name") or "").strip()
        try:
            supplier_gstin = normalize_gstin(str(ctin_raw).strip()) if ctin_raw else ""
        except NormalizationError:
            supplier_gstin = str(ctin_raw).strip().upper()

        notes = sup.get("nt") or sup.get("cdna") or sup.get("cdn") or sup.get("notes") or []
        if not isinstance(notes, list):
            continue

        for note in notes:
            if not isinstance(note, dict):
                continue

            nt_num_raw = str(_first_present(note, "nt_num", "note_number", "inum", "invoice_number") or "").strip()
            if not nt_num_raw:
                continue

            nt_norm = normalize_invoice(nt_num_raw)
            nt_date = _parse_iso_date(_first_present(note, "nt_dt", "note_date", "idt", "invoice_date"))
            filing_date = _parse_iso_date(_first_present(note, "fldtr1", "fldt", "supfildt", "filing_date", "fld_dt"))
            gstr1_period = str(_first_present(note, "supprd", "gstr1_period", "rtnprd", "fp", "period") or "").strip()
            ntty = str(_first_present(note, "ntty", "ntyp", "typ") or "C").strip().upper()
            pos = str(_first_present(note, "pos", "place_of_supply") or "").strip()
            rchrg = str(_first_present(note, "rchrg", "reverse_charge") or "N").strip().upper() == "Y"

            is_credit = ntty in ("C", "CREDIT", "CR", "CREDIT_NOTE")
            doc_type = "CREDIT_NOTE" if is_credit else "DEBIT_NOTE"

            txval_paise, igst_paise, cgst_paise, sgst_paise, cess_paise = _extract_items_tax(note)
            total_tax_paise = igst_paise + cgst_paise + sgst_paise + cess_paise
            note_val_paise = _amount_to_paise(_first_present(note, "val", "total_amount", "invoice_value")) or (txval_paise + total_tax_paise)

            # Credit notes have negative values per GSTR reconciliation standard
            sign = -1 if is_credit else 1

            signed_txval = sign * abs(txval_paise)
            signed_igst = sign * abs(igst_paise)
            signed_cgst = sign * abs(cgst_paise)
            signed_sgst = sign * abs(sgst_paise)
            signed_cess = sign * abs(cess_paise)
            signed_total_tax = sign * abs(total_tax_paise)
            signed_val = sign * abs(note_val_paise)

            records.append({
                "supplier_gstin": supplier_gstin,
                "supplier_gstin_raw": str(ctin_raw).strip(),
                "supplier_name": supplier_name,
                "invoice_number": nt_num_raw,
                "invoice_number_raw": nt_num_raw,
                "invoice_number_normalized": nt_norm,
                "invoice_date": nt_date,
                "taxable_value": signed_txval,
                "taxable_amount_paise": signed_txval,
                "igst": signed_igst,
                "cgst": signed_cgst,
                "sgst": signed_sgst,
                "cess": signed_cess,
                "igst_paise": signed_igst,
                "cgst_paise": signed_cgst,
                "sgst_paise": signed_sgst,
                "cess_paise": signed_cess,
                "total_tax": signed_total_tax,
                "total_tax_paise": signed_total_tax,
                "invoice_value_paise": signed_val,
                "filing_date": filing_date,
                "gstr1_period": gstr1_period,
                "pos": pos,
                "reverse_charge": rchrg,
                "doc_type": doc_type,
                "section": "cdna",
                "invoice_type": ntty,
                "raw_data": note,
            })

    return records
