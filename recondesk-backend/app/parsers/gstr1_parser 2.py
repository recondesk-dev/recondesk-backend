"""GSTR-1 JSON parser.

Parses the official GSTN GSTR-1 JSON format (portal download or Sandbox API)
into a flat list of normalised invoice records for GSTR-1 ↔ Sales Register
reconciliation.

Supported sections
==================
- **b2b**   — B2B invoices (to registered recipients)
- **b2ba**  — B2B amendments
- **b2cl**  — B2C Large (inter-state, value > ₹2.5L, unregistered)
- **b2cla** — B2C Large amendments
- **b2cs**  — B2C Small (consolidated, intra-state / inter-state ≤ ₹2.5L)
- **b2csa** — B2C Small amendments
- **cdnr**  — Credit/Debit Notes to registered recipients
- **cdnra** — CDN amendments (registered)
- **cdnur** — Credit/Debit Notes to unregistered recipients
- **cdnura** — CDN amendments (unregistered)
- **exp**   — Exports (with/without payment)
- **expa**  — Export amendments
- **at**    — Advances received (tax liability)
- **ata**   — Advance amendments / adjustments
- **nil**   — Nil-rated / Exempt / Non-GST supplies
- **hsn**   — HSN summary (parsed for completeness; line-item level)
- **doc_issue** — Document issued summary (metadata only, not invoice-level)

Sections ``isd`` and ``supeco`` (SEZ supplies to SEZ developer/unit with
payment of IGST) are silently ignored if present.

Return shape
============
::

    {
        "records": [...],
        "skipped": [...],
        "total_rows": int,
        "section_counts": {"b2b": N, "cdnr": M, ...},
        "sections_present": [...],
        "sections_absent": [...],
        "filing_gstin": str,
        "filing_period": str,   # ISO date (first of month)
        "total_parsed": int,
        "total_skipped": int,
    }
"""

import datetime
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from app.services.normalizer import (
    ALLOWED_NOTES,
    NormalizationError,
    NormalizationResult,
    normalize_amount,
    normalize_date,
    normalize_gstin,
    normalize_invoice_number,
)
from app.services.matcher import normalize_invoice

SCHEMA_VERSION = "gstr1_v1"

# Indian state codes for place-of-supply normalisation
_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (Old)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh",
    "96": "Foreign Country", "97": "Other Territory",
}


# ---------------------------------------------------------------------------
# Skip diagnostics — canonical categories
# ---------------------------------------------------------------------------

SKIP_MISSING_GSTIN = "missing_gstin"
SKIP_INVALID_GSTIN = "invalid_gstin"
SKIP_MISSING_INVOICE_NUMBER = "missing_invoice_number"
SKIP_MISSING_INVOICE_DATE = "missing_invoice_date"
SKIP_INVALID_INVOICE_DATE = "invalid_invoice_date"
SKIP_INVALID_AMOUNT = "invalid_amount"
SKIP_UNSUPPORTED_SCHEMA = "unsupported_schema"
SKIP_MALFORMED_INVOICE = "malformed_invoice"
SKIP_OTHER = "other"

SKIP_CATEGORY_ORDER: tuple[str, ...] = (
    SKIP_MISSING_GSTIN,
    SKIP_INVALID_GSTIN,
    SKIP_MISSING_INVOICE_NUMBER,
    SKIP_MISSING_INVOICE_DATE,
    SKIP_INVALID_INVOICE_DATE,
    SKIP_INVALID_AMOUNT,
    SKIP_UNSUPPORTED_SCHEMA,
    SKIP_MALFORMED_INVOICE,
    SKIP_OTHER,
)

SKIP_CATEGORY_LABELS: dict[str, str] = {
    SKIP_MISSING_GSTIN: "Missing recipient GSTIN",
    SKIP_INVALID_GSTIN: "Invalid recipient GSTIN",
    SKIP_MISSING_INVOICE_NUMBER: "Missing invoice number",
    SKIP_MISSING_INVOICE_DATE: "Missing invoice date",
    SKIP_INVALID_INVOICE_DATE: "Invalid invoice date",
    SKIP_INVALID_AMOUNT: "Invalid amount",
    SKIP_UNSUPPORTED_SCHEMA: "Unsupported schema",
    SKIP_MALFORMED_INVOICE: "Malformed invoice object",
    SKIP_OTHER: "Other",
}

# Internal error message constants
ERR_MISSING_DATE = "missing_field for dt"
ERR_INVALID_AMOUNT = "Invalid value format for invoice amount"
ERR_INVALID_INVOICE_STRUCTURE = "invalid_invoice_structure"
ERR_UNKNOWN_NOTE_TYPE = "unknown_note_type"
ERR_MISSING_RECIPIENT_GSTIN = "missing_recipient_gstin"
ERR_INVALID_CTIN_TYPE = "Invalid type for field: ctin"


# ---------------------------------------------------------------------------
# Skip classification helpers (mirroring gstr2b_parser)
# ---------------------------------------------------------------------------

def _classify_norm_error(field: str, reason: str) -> tuple[str, str]:
    """Map a NormalizationError (field, reason) to (category, reason_code)."""
    reason_code = f"{field}:{reason}"
    if field == "gstin":
        return (
            SKIP_MISSING_GSTIN if reason == "empty" else SKIP_INVALID_GSTIN,
            reason_code,
        )
    if field == "invoice_number":
        return SKIP_MISSING_INVOICE_NUMBER, reason_code
    if field == "date":
        return SKIP_INVALID_INVOICE_DATE, reason_code
    if field == "amount":
        return SKIP_INVALID_AMOUNT, reason_code
    return SKIP_OTHER, reason_code


def _classify_value_error(message: str) -> tuple[str, str]:
    """Map an internal ValueError message to (category, reason_code)."""
    msg = message or ""
    if msg.startswith(ERR_MISSING_DATE):
        return SKIP_MISSING_INVOICE_DATE, "missing_invoice_date"
    if msg == ERR_INVALID_AMOUNT or msg.startswith("invalid amount for"):
        return SKIP_INVALID_AMOUNT, "invalid_amount"
    if msg == ERR_UNKNOWN_NOTE_TYPE:
        return SKIP_UNSUPPORTED_SCHEMA, "unknown_note_type"
    if msg.startswith("invalid_type for itms"):
        return SKIP_MALFORMED_INVOICE, "invalid_items_structure"
    if msg == ERR_INVALID_INVOICE_STRUCTURE:
        return SKIP_MALFORMED_INVOICE, "invalid_invoice_structure"
    if msg.startswith("invalid_item_structure"):
        return SKIP_MALFORMED_INVOICE, "invalid_item_structure"
    if msg.startswith("invalid_type for rt") or msg.startswith("unparseable rt"):
        return SKIP_MALFORMED_INVOICE, "invalid_rate"
    if msg.startswith("invalid_type for"):
        return SKIP_INVALID_AMOUNT, "invalid_amount_type"
    return SKIP_OTHER, "other"


def _classify_skip_exception(exc: BaseException) -> tuple[str, str]:
    """Return (category, reason_code) for any per-invoice parse exception."""
    if isinstance(exc, NormalizationError):
        return _classify_norm_error(exc.field, exc.reason)
    return _classify_value_error(str(exc))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_result(result: Any, field_name: str) -> Any:
    if result is None:
        raise ValueError(f"normalizer returned None for {field_name}")
    if not isinstance(result.notes, list):
        raise ValueError(f"normalizer notes not a list for {field_name}")
    for note in result.notes:
        if note not in ALLOWED_NOTES:
            raise ValueError(f"unknown note '{note}' for {field_name}")
    return result


def _make_skip_entry(
    section: str,
    gstin: str,
    invoice_number: str,
    error_reason: str,
    raw_invoice: Any,
    *,
    category: str = SKIP_OTHER,
    reason_code: str = "other",
) -> dict:
    return {
        "section": section,
        "recipient_gstin": gstin,
        "invoice_number": invoice_number,
        "error_reason": error_reason,
        "category": category,
        "reason_code": reason_code,
        "raw_data": (
            dict(raw_invoice)
            if isinstance(raw_invoice, dict)
            else {"_raw": str(raw_invoice)}
        ),
    }


def _parse_numeric_field(value: Any, field_name: str) -> str:
    """Return str ready for normalize_amount.

    None → "0".
    bool / non-numeric type → ValueError with type info.
    str / int / float → str(value).
    """
    if value is None:
        return "0"
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"invalid_type for {field_name}: {type(value)}")
    return str(value)


def _amount_str_to_paise(raw: str, field_name: str) -> int:
    """Convert a GST monetary string to integer paise via ``normalize_amount``."""
    try:
        r = normalize_amount(raw)
    except NormalizationError as exc:
        raise ValueError(f"invalid amount for {field_name}: {exc.reason}") from exc
    return int(r.value)


def _first_present(mapping: dict, *keys: str) -> Any:
    """Return the first key present with a non-None value."""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _normalize_pos(pos_raw: Any) -> str:
    """Normalise place-of-supply to ``"<code>-<State Name>"`` form."""
    if pos_raw is None:
        return ""
    s = str(pos_raw).strip()
    if not s:
        return ""
    # Extract leading 2-digit code
    m = re.match(r"^(\d{2})", s)
    if m:
        code = m.group(1)
        if code in _STATE_CODES:
            return f"{code}-{_STATE_CODES[code]}"
    return s


def _reverse_charge_value(invoice: dict) -> bool:
    raw = _first_present(invoice, "rchrg", "rev") or "N"
    return str(raw).strip().upper() == "Y"


def _get_inv_num(invoice: Any, is_cdnr: bool) -> str:
    """Extract the invoice/note number string for use in skip entries."""
    if not isinstance(invoice, dict):
        return "unknown"
    if is_cdnr:
        val = invoice.get("nt_num") or invoice.get("ntnum")
    else:
        val = invoice.get("inum")
    return str(val) if val is not None else "unknown"


def _note_type_value(invoice: dict) -> str:
    """Credit/debit note type: ``C`` (credit) or ``D`` (debit)."""
    raw = _first_present(invoice, "ntty", "ntyp", "nttyp", "typ")
    if raw is None:
        return ""
    return str(raw).strip().upper()


# ---------------------------------------------------------------------------
# Item-level parsing
# ---------------------------------------------------------------------------

def _item_tax_value(itm: dict, field: str) -> str:
    aliases = {
        "igst": ("igst", "iamt"),
        "cgst": ("cgst", "camt"),
        "sgst": ("sgst", "samt"),
        "cess": ("cess", "csamt"),
    }
    return _parse_numeric_field(_first_present(itm, *aliases[field]), field)


def _parse_items(items_list: list) -> tuple[list[dict], list[str]]:
    """Parse a list of item dicts.

    Returns (item_records, raw_txvals).

    Raises ValueError or NormalizationError on any item error — the caller
    sends the entire invoice to skipped[].
    """
    item_records: list = []
    raw_txvals: list = []

    for i, item in enumerate(items_list):
        if not isinstance(item, dict):
            raise ValueError(f"invalid_item_structure at index {i}")

        # Support both flat format {"rt", "txval", ...} and the GSTN API
        # nested format {"num": N, "itm_det": {"rt", "txval", ...}}.
        if "itm_det" in item and isinstance(item["itm_det"], dict):
            itm = item["itm_det"]
            raw_rt = itm.get("rt") if itm.get("rt") is not None else item.get("rt")
        else:
            itm = item
            raw_rt = item.get("rt")

        if raw_rt is None:
            tax_rate = 0.0
        elif isinstance(raw_rt, bool) or not isinstance(raw_rt, (int, float, str)):
            raise ValueError(f"invalid_type for rt: {type(raw_rt)}")
        else:
            try:
                tax_rate = float(raw_rt)
            except (ValueError, TypeError):
                raise ValueError(f"unparseable rt value: {raw_rt!r}")

        raw_txval = _parse_numeric_field(itm.get("txval"), "txval")
        raw_igst = _item_tax_value(itm, "igst")
        raw_cgst = _item_tax_value(itm, "cgst")
        raw_sgst = _item_tax_value(itm, "sgst")
        raw_cess = _item_tax_value(itm, "cess")

        raw_txvals.append(raw_txval)

        item_record: dict[str, Any] = {
            "tax_rate": tax_rate,
            "taxable_value_raw": raw_txval,
            "taxable_value_paise": _amount_str_to_paise(raw_txval, "taxable_value"),
            "igst_paise": _amount_str_to_paise(raw_igst, "igst"),
            "cgst_paise": _amount_str_to_paise(raw_cgst, "cgst"),
            "sgst_paise": _amount_str_to_paise(raw_sgst, "sgst"),
            "cess_paise": _amount_str_to_paise(raw_cess, "cess"),
        }
        item_records.append(item_record)

    return item_records, raw_txvals


def _invoice_items_list(invoice: dict) -> list:
    """Return GSTR line items from either official ``itms`` or portal-style ``items``."""
    items_list = invoice.get("itms")
    if items_list is None:
        items_list = invoice.get("items", [])
    if items_list is not None and not isinstance(items_list, list):
        raise ValueError(f"invalid_type for itms: {type(items_list)}")
    return items_list or []


def _invoice_level_amount_paise(invoice: dict) -> dict[str, int] | None:
    """Read invoice-root tax fields when ``itms``/``items`` are absent."""
    if not any(k in invoice for k in ("txval", "cgst", "sgst", "igst", "cess")):
        return None
    return {
        "taxable_value_paise": _amount_str_to_paise(
            _parse_numeric_field(invoice.get("txval"), "txval"), "taxable_value"
        ),
        "cgst_paise": _amount_str_to_paise(
            _parse_numeric_field(invoice.get("cgst"), "cgst"), "cgst"
        ),
        "sgst_paise": _amount_str_to_paise(
            _parse_numeric_field(invoice.get("sgst"), "sgst"), "sgst"
        ),
        "igst_paise": _amount_str_to_paise(
            _parse_numeric_field(invoice.get("igst"), "igst"), "igst"
        ),
        "cess_paise": _amount_str_to_paise(
            _parse_numeric_field(invoice.get("cess"), "cess"), "cess"
        ),
    }


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(
    *,
    section: str,
    invoice_type: str,
    doc_type: str,
    is_amendment: bool,
    recipient_gstin: str | None,
    recipient_name: str,
    invoice_number: str,
    invoice_number_raw: str,
    invoice_date_norm: str,
    invoice_date_raw: str,
    invoice_value_paise: int,
    invoice_value_raw: str,
    pos: str,
    reverse_charge: bool,
    items: list,
    normalization_notes: dict,
    original_invoice_number: str | None = None,
    original_invoice_number_raw: str | None = None,
    original_invoice_date_norm: str | None = None,
    original_invoice_date_raw: str | None = None,
    gstin_format_invalid: bool = False,
    invoice_level_paise: dict[str, int] | None = None,
    export_type: str | None = None,
    shipping_bill_number: str | None = None,
    shipping_bill_date: str | None = None,
    shipping_port_code: str | None = None,
    diff_percent: float | None = None,
    supply_type: str | None = None,
) -> dict:
    """Assemble a flat, normalised record dict."""
    # Compute aggregate tax from items
    total_taxable_paise = 0
    total_igst_paise = 0
    total_cgst_paise = 0
    total_sgst_paise = 0
    total_cess_paise = 0
    tax_rates: list[float] = []

    if items:
        for itm in items:
            total_taxable_paise += itm.get("taxable_value_paise", 0)
            total_igst_paise += itm.get("igst_paise", 0)
            total_cgst_paise += itm.get("cgst_paise", 0)
            total_sgst_paise += itm.get("sgst_paise", 0)
            total_cess_paise += itm.get("cess_paise", 0)
            if itm.get("tax_rate") is not None:
                tax_rates.append(itm["tax_rate"])
    elif invoice_level_paise:
        total_taxable_paise = invoice_level_paise.get("taxable_value_paise", 0)
        total_igst_paise = invoice_level_paise.get("igst_paise", 0)
        total_cgst_paise = invoice_level_paise.get("cgst_paise", 0)
        total_sgst_paise = invoice_level_paise.get("sgst_paise", 0)
        total_cess_paise = invoice_level_paise.get("cess_paise", 0)

    total_tax_paise = (
        total_igst_paise + total_cgst_paise + total_sgst_paise + total_cess_paise
    )

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "section": section,
        "invoice_type": invoice_type,
        "doc_type": doc_type,
        "is_amendment": is_amendment,
        # Recipient
        "recipient_gstin": recipient_gstin,
        "recipient_name": recipient_name,
        "gstin_format_invalid": gstin_format_invalid,
        # Invoice identification
        "invoice_number": invoice_number,
        "invoice_number_raw": invoice_number_raw,
        "invoice_number_normalized": invoice_number,
        "invoice_date": invoice_date_norm,
        "invoice_date_raw": invoice_date_raw,
        # Values (paise)
        "invoice_value_paise": invoice_value_paise,
        "invoice_value_raw": invoice_value_raw,
        "taxable_amount_paise": total_taxable_paise,
        "igst_paise": total_igst_paise,
        "cgst_paise": total_cgst_paise,
        "sgst_paise": total_sgst_paise,
        "cess_paise": total_cess_paise,
        "total_tax_paise": total_tax_paise,
        # Tax rate (first rate if single-rate; None if mixed or absent)
        "rate": tax_rates[0] if len(tax_rates) == 1 else (
            tax_rates[0] if tax_rates and len(set(tax_rates)) == 1 else None
        ),
        # Place of supply
        "place_of_supply": pos,
        "reverse_charge": reverse_charge,
        # Line items
        "items": items,
        # Amendments
        "original_invoice_number": original_invoice_number,
        "original_invoice_number_raw": original_invoice_number_raw,
        "original_invoice_date": original_invoice_date_norm,
        "original_invoice_date_raw": original_invoice_date_raw,
        # Normalisation metadata
        "normalization_notes": normalization_notes,
    }

    # Export-specific fields
    if export_type is not None:
        record["export_type"] = export_type
    if shipping_bill_number is not None:
        record["shipping_bill_number"] = shipping_bill_number
    if shipping_bill_date is not None:
        record["shipping_bill_date"] = shipping_bill_date
    if shipping_port_code is not None:
        record["shipping_port_code"] = shipping_port_code

    # B2CS differential percentage
    if diff_percent is not None:
        record["diff_percent"] = diff_percent
    # Supply type (for B2CS/nil — INTER/INTRA)
    if supply_type is not None:
        record["supply_type"] = supply_type

    return record


# ---------------------------------------------------------------------------
# Section parsers — B2B / B2BA
# ---------------------------------------------------------------------------

def _parse_b2b_invoice(
    invoice: dict,
    recipient_gstin: str,
    recipient_gstin_raw: str,
    section: str,
    is_amendment: bool,
    recipient_name: str = "",
    gstin_format_invalid: bool = False,
) -> dict:
    normalization_notes: dict = {}

    raw_inum_val = invoice.get("inum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = normalize_invoice(result.value)

    raw_dt = _first_present(invoice, "dt", "idt")
    if raw_dt is None:
        raise ValueError(ERR_MISSING_DATE)
    result = _validate_result(normalize_date(raw_dt), "invoice_date")
    if result.notes:
        normalization_notes["invoice_date"] = result.notes
    invoice_date = result.value

    try:
        raw_val = _parse_numeric_field(invoice.get("val"), "val")
    except ValueError:
        raise ValueError(ERR_INVALID_AMOUNT)
    try:
        invoice_value_paise = _amount_str_to_paise(raw_val, "invoice_value")
    except ValueError as e:
        raise ValueError(ERR_INVALID_AMOUNT) from e

    pos = _normalize_pos(invoice.get("pos"))
    reverse_charge = _reverse_charge_value(invoice)

    # Amendment original references
    original_invoice_number = None
    original_invoice_number_raw = None
    original_invoice_date_norm = None
    original_invoice_date_raw = None
    if is_amendment:
        oinum_raw = invoice.get("oinum")
        if oinum_raw is not None:
            original_invoice_number_raw = str(oinum_raw)
            r = _validate_result(
                normalize_invoice_number(original_invoice_number_raw),
                "original_invoice_number",
            )
            if r.notes:
                normalization_notes["original_invoice_number"] = r.notes
            original_invoice_number = normalize_invoice(r.value)
        oidt_raw = invoice.get("oidt")
        if oidt_raw is not None:
            original_invoice_date_raw = str(oidt_raw)
            r = _validate_result(normalize_date(oidt_raw), "original_invoice_date")
            if r.notes:
                normalization_notes["original_invoice_date"] = r.notes
            original_invoice_date_norm = (
                r.value.isoformat() if isinstance(r.value, datetime.date) else str(r.value)
            )

    items_list = _invoice_items_list(invoice)
    item_records, _raw_txvals = _parse_items(items_list)
    invoice_level_paise = (
        None if item_records else _invoice_level_amount_paise(invoice)
    )

    return _build_record(
        section=section,
        invoice_type="B2B",
        doc_type="INVOICE",
        is_amendment=is_amendment,
        recipient_gstin=recipient_gstin,
        recipient_name=recipient_name,
        invoice_number=invoice_number,
        invoice_number_raw=raw_inum,
        invoice_date_norm=(
            invoice_date.isoformat()
            if isinstance(invoice_date, datetime.date) else str(invoice_date)
        ),
        invoice_date_raw=str(raw_dt),
        invoice_value_paise=invoice_value_paise,
        invoice_value_raw=raw_val,
        pos=pos,
        reverse_charge=reverse_charge,
        items=item_records,
        normalization_notes=normalization_notes,
        gstin_format_invalid=gstin_format_invalid,
        original_invoice_number=original_invoice_number,
        original_invoice_number_raw=original_invoice_number_raw,
        original_invoice_date_norm=original_invoice_date_norm,
        original_invoice_date_raw=original_invoice_date_raw,
        invoice_level_paise=invoice_level_paise,
    )


# ---------------------------------------------------------------------------
# Section parsers — B2CL / B2CLA
# ---------------------------------------------------------------------------

def _parse_b2cl_invoice(
    invoice: dict,
    pos: str,
    section: str,
    is_amendment: bool,
) -> dict:
    """Parse a B2C Large invoice (inter-state, > ₹2.5L, unregistered recipient)."""
    normalization_notes: dict = {}

    raw_inum_val = invoice.get("inum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = normalize_invoice(result.value)

    raw_dt = _first_present(invoice, "dt", "idt")
    if raw_dt is None:
        raise ValueError(ERR_MISSING_DATE)
    result = _validate_result(normalize_date(raw_dt), "invoice_date")
    if result.notes:
        normalization_notes["invoice_date"] = result.notes
    invoice_date = result.value

    try:
        raw_val = _parse_numeric_field(invoice.get("val"), "val")
    except ValueError:
        raise ValueError(ERR_INVALID_AMOUNT)
    try:
        invoice_value_paise = _amount_str_to_paise(raw_val, "invoice_value")
    except ValueError as e:
        raise ValueError(ERR_INVALID_AMOUNT) from e

    # Amendment original references
    original_invoice_number = None
    original_invoice_number_raw = None
    original_invoice_date_norm = None
    original_invoice_date_raw = None
    if is_amendment:
        oinum_raw = invoice.get("oinum")
        if oinum_raw is not None:
            original_invoice_number_raw = str(oinum_raw)
            r = _validate_result(
                normalize_invoice_number(original_invoice_number_raw),
                "original_invoice_number",
            )
            if r.notes:
                normalization_notes["original_invoice_number"] = r.notes
            original_invoice_number = normalize_invoice(r.value)
        oidt_raw = invoice.get("oidt")
        if oidt_raw is not None:
            original_invoice_date_raw = str(oidt_raw)
            r = _validate_result(normalize_date(oidt_raw), "original_invoice_date")
            if r.notes:
                normalization_notes["original_invoice_date"] = r.notes
            original_invoice_date_norm = (
                r.value.isoformat() if isinstance(r.value, datetime.date) else str(r.value)
            )

    items_list = _invoice_items_list(invoice)
    item_records, _raw_txvals = _parse_items(items_list)
    invoice_level_paise = (
        None if item_records else _invoice_level_amount_paise(invoice)
    )

    return _build_record(
        section=section,
        invoice_type="B2C_LARGE",
        doc_type="INVOICE",
        is_amendment=is_amendment,
        recipient_gstin=None,
        recipient_name="",
        invoice_number=invoice_number,
        invoice_number_raw=raw_inum,
        invoice_date_norm=(
            invoice_date.isoformat()
            if isinstance(invoice_date, datetime.date) else str(invoice_date)
        ),
        invoice_date_raw=str(raw_dt),
        invoice_value_paise=invoice_value_paise,
        invoice_value_raw=raw_val,
        pos=_normalize_pos(pos),
        reverse_charge=False,
        items=item_records,
        normalization_notes=normalization_notes,
        original_invoice_number=original_invoice_number,
        original_invoice_number_raw=original_invoice_number_raw,
        original_invoice_date_norm=original_invoice_date_norm,
        original_invoice_date_raw=original_invoice_date_raw,
        invoice_level_paise=invoice_level_paise,
    )


# ---------------------------------------------------------------------------
# Section parsers — CDNR / CDNRA
# ---------------------------------------------------------------------------

def _parse_cdnr_invoice(
    invoice: dict,
    recipient_gstin: str,
    recipient_gstin_raw: str,
    section: str,
    is_amendment: bool,
    recipient_name: str = "",
    gstin_format_invalid: bool = False,
) -> dict:
    """Parse a credit/debit note to a registered recipient."""
    normalization_notes: dict = {}

    ntty = _note_type_value(invoice)
    if ntty == "C":
        document_type = "CREDIT_NOTE"
    elif ntty == "D":
        document_type = "DEBIT_NOTE"
    else:
        raise ValueError(ERR_UNKNOWN_NOTE_TYPE)

    raw_inum_val = invoice.get("nt_num") or invoice.get("ntnum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = normalize_invoice(result.value)

    raw_dt = _first_present(invoice, "nt_dt", "dt", "idt")
    if raw_dt is None:
        raise ValueError(ERR_MISSING_DATE)
    result = _validate_result(normalize_date(raw_dt), "invoice_date")
    if result.notes:
        normalization_notes["invoice_date"] = result.notes
    invoice_date = result.value

    try:
        raw_val = _parse_numeric_field(invoice.get("val"), "val")
    except ValueError:
        raise ValueError(ERR_INVALID_AMOUNT)
    try:
        invoice_value_paise = _amount_str_to_paise(raw_val, "invoice_value")
    except ValueError as e:
        raise ValueError(ERR_INVALID_AMOUNT) from e

    pos = _normalize_pos(invoice.get("pos"))
    reverse_charge = _reverse_charge_value(invoice)

    # Amendment original references
    original_invoice_number = None
    original_invoice_number_raw = None
    original_invoice_date_norm = None
    original_invoice_date_raw = None
    if is_amendment:
        ointnum_raw = invoice.get("ont_num") or invoice.get("ontnum")
        if ointnum_raw is not None:
            original_invoice_number_raw = str(ointnum_raw)
            r = _validate_result(
                normalize_invoice_number(original_invoice_number_raw),
                "original_invoice_number",
            )
            if r.notes:
                normalization_notes["original_invoice_number"] = r.notes
            original_invoice_number = normalize_invoice(r.value)
        ointdt_raw = invoice.get("ont_dt") or invoice.get("ontdt")
        if ointdt_raw is not None:
            original_invoice_date_raw = str(ointdt_raw)
            r = _validate_result(normalize_date(ointdt_raw), "original_invoice_date")
            if r.notes:
                normalization_notes["original_invoice_date"] = r.notes
            original_invoice_date_norm = (
                r.value.isoformat() if isinstance(r.value, datetime.date) else str(r.value)
            )

    items_list = _invoice_items_list(invoice)
    item_records, _raw_txvals = _parse_items(items_list)
    invoice_level_paise = (
        None if item_records else _invoice_level_amount_paise(invoice)
    )

    return _build_record(
        section=section,
        invoice_type=document_type,
        doc_type=document_type,
        is_amendment=is_amendment,
        recipient_gstin=recipient_gstin,
        recipient_name=recipient_name,
        invoice_number=invoice_number,
        invoice_number_raw=raw_inum,
        invoice_date_norm=(
            invoice_date.isoformat()
            if isinstance(invoice_date, datetime.date) else str(invoice_date)
        ),
        invoice_date_raw=str(raw_dt),
        invoice_value_paise=invoice_value_paise,
        invoice_value_raw=raw_val,
        pos=pos,
        reverse_charge=reverse_charge,
        items=item_records,
        normalization_notes=normalization_notes,
        gstin_format_invalid=gstin_format_invalid,
        original_invoice_number=original_invoice_number,
        original_invoice_number_raw=original_invoice_number_raw,
        original_invoice_date_norm=original_invoice_date_norm,
        original_invoice_date_raw=original_invoice_date_raw,
        invoice_level_paise=invoice_level_paise,
    )


# ---------------------------------------------------------------------------
# Section parsers — CDNUR / CDNURA
# ---------------------------------------------------------------------------

def _parse_cdnur_invoice(
    invoice: dict,
    section: str,
    is_amendment: bool,
) -> dict:
    """Parse a credit/debit note to an unregistered recipient."""
    normalization_notes: dict = {}

    ntty = _note_type_value(invoice)
    if ntty == "C":
        document_type = "CREDIT_NOTE"
    elif ntty == "D":
        document_type = "DEBIT_NOTE"
    else:
        raise ValueError(ERR_UNKNOWN_NOTE_TYPE)

    raw_inum_val = invoice.get("nt_num") or invoice.get("ntnum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = normalize_invoice(result.value)

    raw_dt = _first_present(invoice, "nt_dt", "dt", "idt")
    if raw_dt is None:
        raise ValueError(ERR_MISSING_DATE)
    result = _validate_result(normalize_date(raw_dt), "invoice_date")
    if result.notes:
        normalization_notes["invoice_date"] = result.notes
    invoice_date = result.value

    try:
        raw_val = _parse_numeric_field(invoice.get("val"), "val")
    except ValueError:
        raise ValueError(ERR_INVALID_AMOUNT)
    try:
        invoice_value_paise = _amount_str_to_paise(raw_val, "invoice_value")
    except ValueError as e:
        raise ValueError(ERR_INVALID_AMOUNT) from e

    pos = _normalize_pos(invoice.get("pos"))

    # cdnur has no amendments currently, but handle defensively
    original_invoice_number = None
    original_invoice_number_raw = None
    original_invoice_date_norm = None
    original_invoice_date_raw = None

    items_list = _invoice_items_list(invoice)
    item_records, _raw_txvals = _parse_items(items_list)
    invoice_level_paise = (
        None if item_records else _invoice_level_amount_paise(invoice)
    )

    return _build_record(
        section=section,
        invoice_type=document_type,
        doc_type=document_type,
        is_amendment=is_amendment,
        recipient_gstin=None,
        recipient_name="",
        invoice_number=invoice_number,
        invoice_number_raw=raw_inum,
        invoice_date_norm=(
            invoice_date.isoformat()
            if isinstance(invoice_date, datetime.date) else str(invoice_date)
        ),
        invoice_date_raw=str(raw_dt),
        invoice_value_paise=invoice_value_paise,
        invoice_value_raw=raw_val,
        pos=pos,
        reverse_charge=False,
        items=item_records,
        normalization_notes=normalization_notes,
        original_invoice_number=original_invoice_number,
        original_invoice_number_raw=original_invoice_number_raw,
        original_invoice_date_norm=original_invoice_date_norm,
        original_invoice_date_raw=original_invoice_date_raw,
        invoice_level_paise=invoice_level_paise,
    )


# ---------------------------------------------------------------------------
# Section parsers — EXP / EXPA
# ---------------------------------------------------------------------------

def _parse_exp_invoice(
    invoice: dict,
    export_type: str,
    section: str,
    is_amendment: bool,
) -> dict:
    """Parse an export invoice."""
    normalization_notes: dict = {}

    raw_inum_val = invoice.get("inum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = normalize_invoice(result.value)

    raw_dt = _first_present(invoice, "dt", "idt")
    if raw_dt is None:
        raise ValueError(ERR_MISSING_DATE)
    result = _validate_result(normalize_date(raw_dt), "invoice_date")
    if result.notes:
        normalization_notes["invoice_date"] = result.notes
    invoice_date = result.value

    try:
        raw_val = _parse_numeric_field(invoice.get("val"), "val")
    except ValueError:
        raise ValueError(ERR_INVALID_AMOUNT)
    try:
        invoice_value_paise = _amount_str_to_paise(raw_val, "invoice_value")
    except ValueError as e:
        raise ValueError(ERR_INVALID_AMOUNT) from e

    # Shipping bill details
    sb_num = invoice.get("sbnum")
    sb_dt_raw = invoice.get("sbdt")
    sb_dt = None
    if sb_dt_raw is not None:
        try:
            r = _validate_result(normalize_date(sb_dt_raw), "shipping_bill_date")
            sb_dt = (
                r.value.isoformat()
                if isinstance(r.value, datetime.date) else str(r.value)
            )
        except (NormalizationError, ValueError):
            sb_dt = str(sb_dt_raw)
    sb_pcode = invoice.get("sbpcode")

    # Amendment original references
    original_invoice_number = None
    original_invoice_number_raw = None
    original_invoice_date_norm = None
    original_invoice_date_raw = None
    if is_amendment:
        oinum_raw = invoice.get("oinum")
        if oinum_raw is not None:
            original_invoice_number_raw = str(oinum_raw)
            r = _validate_result(
                normalize_invoice_number(original_invoice_number_raw),
                "original_invoice_number",
            )
            if r.notes:
                normalization_notes["original_invoice_number"] = r.notes
            original_invoice_number = normalize_invoice(r.value)
        oidt_raw = invoice.get("oidt")
        if oidt_raw is not None:
            original_invoice_date_raw = str(oidt_raw)
            r = _validate_result(normalize_date(oidt_raw), "original_invoice_date")
            if r.notes:
                normalization_notes["original_invoice_date"] = r.notes
            original_invoice_date_norm = (
                r.value.isoformat() if isinstance(r.value, datetime.date) else str(r.value)
            )

    items_list = _invoice_items_list(invoice)
    item_records, _raw_txvals = _parse_items(items_list)
    invoice_level_paise = (
        None if item_records else _invoice_level_amount_paise(invoice)
    )

    return _build_record(
        section=section,
        invoice_type="EXPORT",
        doc_type="INVOICE",
        is_amendment=is_amendment,
        recipient_gstin=None,
        recipient_name="",
        invoice_number=invoice_number,
        invoice_number_raw=raw_inum,
        invoice_date_norm=(
            invoice_date.isoformat()
            if isinstance(invoice_date, datetime.date) else str(invoice_date)
        ),
        invoice_date_raw=str(raw_dt),
        invoice_value_paise=invoice_value_paise,
        invoice_value_raw=raw_val,
        pos=_normalize_pos("96"),  # Foreign country
        reverse_charge=False,
        items=item_records,
        normalization_notes=normalization_notes,
        export_type=export_type,
        shipping_bill_number=str(sb_num) if sb_num is not None else None,
        shipping_bill_date=sb_dt,
        shipping_port_code=str(sb_pcode) if sb_pcode is not None else None,
        original_invoice_number=original_invoice_number,
        original_invoice_number_raw=original_invoice_number_raw,
        original_invoice_date_norm=original_invoice_date_norm,
        original_invoice_date_raw=original_invoice_date_raw,
        invoice_level_paise=invoice_level_paise,
    )


# ---------------------------------------------------------------------------
# Section parsers — B2CS / B2CSA (consolidated, no individual invoice numbers)
# ---------------------------------------------------------------------------

def _parse_b2cs_entry(
    entry: dict,
    section: str,
    is_amendment: bool,
    entry_index: int,
) -> dict:
    """Parse a B2C Small consolidated entry.

    B2CS entries are rate+POS aggregates — no individual invoice number or date.
    We synthesise a pseudo invoice number for downstream tracking.
    """
    normalization_notes: dict = {}

    pos = _normalize_pos(entry.get("pos"))
    supply_type = str(entry.get("sply_ty") or entry.get("typ") or "").strip().upper()

    raw_rt = entry.get("rt")
    if raw_rt is None:
        tax_rate = 0.0
    else:
        try:
            tax_rate = float(raw_rt)
        except (ValueError, TypeError):
            tax_rate = 0.0

    raw_txval = _parse_numeric_field(entry.get("txval"), "txval")
    raw_igst = _parse_numeric_field(entry.get("iamt") or entry.get("igst"), "igst")
    raw_cgst = _parse_numeric_field(entry.get("camt") or entry.get("cgst"), "cgst")
    raw_sgst = _parse_numeric_field(entry.get("samt") or entry.get("sgst"), "sgst")
    raw_cess = _parse_numeric_field(entry.get("csamt") or entry.get("cess"), "cess")

    taxable_paise = _amount_str_to_paise(raw_txval, "taxable_value")
    igst_paise = _amount_str_to_paise(raw_igst, "igst")
    cgst_paise = _amount_str_to_paise(raw_cgst, "cgst")
    sgst_paise = _amount_str_to_paise(raw_sgst, "sgst")
    cess_paise = _amount_str_to_paise(raw_cess, "cess")

    total_paise = taxable_paise + igst_paise + cgst_paise + sgst_paise + cess_paise

    # Differential percentage (0.65 for E-commerce supplies)
    diff_percent_raw = entry.get("diff_percent")
    diff_percent = None
    if diff_percent_raw is not None:
        try:
            diff_percent = float(diff_percent_raw)
        except (ValueError, TypeError):
            pass

    # Synthesise pseudo invoice number
    pseudo_inum = f"B2CS-{pos or 'NOPOS'}-{tax_rate}-{entry_index}"

    item_record: dict[str, Any] = {
        "tax_rate": tax_rate,
        "taxable_value_raw": raw_txval,
        "taxable_value_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": cess_paise,
    }

    return _build_record(
        section=section,
        invoice_type="B2C_SMALL",
        doc_type="INVOICE",
        is_amendment=is_amendment,
        recipient_gstin=None,
        recipient_name="",
        invoice_number=pseudo_inum,
        invoice_number_raw=pseudo_inum,
        invoice_date_norm="",
        invoice_date_raw="",
        invoice_value_paise=total_paise,
        invoice_value_raw=str(total_paise / 100),
        pos=pos,
        reverse_charge=False,
        items=[item_record],
        normalization_notes=normalization_notes,
        diff_percent=diff_percent,
        supply_type=supply_type or None,
    )


# ---------------------------------------------------------------------------
# Section parsers — AT / ATA (Advances)
# ---------------------------------------------------------------------------

def _parse_at_entry(
    entry: dict,
    section: str,
    is_amendment: bool,
    entry_index: int,
) -> dict:
    """Parse an advance-received entry (tax liability on advance)."""
    normalization_notes: dict = {}

    pos = _normalize_pos(entry.get("pos"))
    supply_type = str(entry.get("sply_ty") or "").strip().upper()

    raw_rt = entry.get("rt")
    tax_rate = 0.0
    if raw_rt is not None:
        try:
            tax_rate = float(raw_rt)
        except (ValueError, TypeError):
            pass

    raw_ad = _parse_numeric_field(entry.get("ad_amt") or entry.get("txval"), "ad_amt")
    raw_igst = _parse_numeric_field(entry.get("iamt") or entry.get("igst"), "igst")
    raw_cgst = _parse_numeric_field(entry.get("camt") or entry.get("cgst"), "cgst")
    raw_sgst = _parse_numeric_field(entry.get("samt") or entry.get("sgst"), "sgst")
    raw_cess = _parse_numeric_field(entry.get("csamt") or entry.get("cess"), "cess")

    ad_paise = _amount_str_to_paise(raw_ad, "advance_amount")
    igst_paise = _amount_str_to_paise(raw_igst, "igst")
    cgst_paise = _amount_str_to_paise(raw_cgst, "cgst")
    sgst_paise = _amount_str_to_paise(raw_sgst, "sgst")
    cess_paise = _amount_str_to_paise(raw_cess, "cess")

    pseudo_inum = f"ADV-{pos or 'NOPOS'}-{tax_rate}-{entry_index}"

    item_record: dict[str, Any] = {
        "tax_rate": tax_rate,
        "taxable_value_raw": raw_ad,
        "taxable_value_paise": ad_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": cess_paise,
    }

    return _build_record(
        section=section,
        invoice_type="ADVANCES",
        doc_type="ADVANCE",
        is_amendment=is_amendment,
        recipient_gstin=None,
        recipient_name="",
        invoice_number=pseudo_inum,
        invoice_number_raw=pseudo_inum,
        invoice_date_norm="",
        invoice_date_raw="",
        invoice_value_paise=ad_paise,
        invoice_value_raw=raw_ad,
        pos=pos,
        reverse_charge=False,
        items=[item_record],
        normalization_notes=normalization_notes,
        supply_type=supply_type or None,
    )


# ---------------------------------------------------------------------------
# Section parsers — NIL (Nil-rated / Exempt / Non-GST)
# ---------------------------------------------------------------------------

def _parse_nil_section(
    nil_data: dict,
    records: list,
    skipped: list,
) -> str:
    """Parse the nil-rated/exempt/non-GST section.

    GSTR-1 ``nil`` section structure::

        { "inv": [ {"sply_ty": "INTRB2B", "nil_amt": ..., "expt_amt": ...,
                     "ngsup_amt": ...}, ... ] }

    Each entry is a consolidated row by supply type.
    """
    inv_list = nil_data.get("inv", [])
    if not isinstance(inv_list, list) or not inv_list:
        return "empty"

    parsed = False
    for idx, entry in enumerate(inv_list):
        if not isinstance(entry, dict):
            continue

        supply_type = str(entry.get("sply_ty") or "").strip().upper()

        # Each entry can have nil_amt, expt_amt, ngsup_amt
        for amt_field, sub_type in [
            ("nil_amt", "NIL_RATED"),
            ("expt_amt", "EXEMPT"),
            ("ngsup_amt", "NON_GST"),
        ]:
            raw_val = entry.get(amt_field)
            if raw_val is None:
                continue
            try:
                val_paise = _amount_str_to_paise(
                    _parse_numeric_field(raw_val, amt_field), amt_field
                )
            except (ValueError, NormalizationError):
                continue
            if val_paise == 0:
                continue

            pseudo_inum = f"NIL-{supply_type}-{sub_type}-{idx}"

            record = _build_record(
                section="nil",
                invoice_type=sub_type,
                doc_type="NIL_EXEMPT",
                is_amendment=False,
                recipient_gstin=None,
                recipient_name="",
                invoice_number=pseudo_inum,
                invoice_number_raw=pseudo_inum,
                invoice_date_norm="",
                invoice_date_raw="",
                invoice_value_paise=val_paise,
                invoice_value_raw=str(raw_val),
                pos="",
                reverse_charge=False,
                items=[],
                normalization_notes={},
                supply_type=supply_type or None,
            )
            records.append(record)
            parsed = True

    return "present" if parsed else "empty"


# ---------------------------------------------------------------------------
# Section parsers — HSN Summary
# ---------------------------------------------------------------------------

def _parse_hsn_section(
    hsn_data: dict,
    records: list,
    skipped: list,
) -> str:
    """Parse the HSN summary section.

    Structure::

        { "data": [ {"num": N, "hsn_sc": "...", "desc": "...",
                      "uqc": "...", "qty": ..., "val": ...,
                      "txval": ..., "iamt": ..., "camt": ...,
                      "samt": ..., "csamt": ...}, ... ] }

    These are summary rows by HSN, not individual invoices. Parsed for
    completeness and cross-checking; not used for invoice-level reconciliation.
    """
    data_list = hsn_data.get("data", [])
    if not isinstance(data_list, list) or not data_list:
        return "empty"

    parsed = False
    for idx, entry in enumerate(data_list):
        if not isinstance(entry, dict):
            continue
        hsn_code = str(entry.get("hsn_sc") or "").strip()
        desc = str(entry.get("desc") or "").strip()

        try:
            raw_txval = _parse_numeric_field(entry.get("txval"), "txval")
            raw_igst = _parse_numeric_field(entry.get("iamt") or entry.get("igst"), "igst")
            raw_cgst = _parse_numeric_field(entry.get("camt") or entry.get("cgst"), "cgst")
            raw_sgst = _parse_numeric_field(entry.get("samt") or entry.get("sgst"), "sgst")
            raw_cess = _parse_numeric_field(entry.get("csamt") or entry.get("cess"), "cess")
        except ValueError:
            continue

        try:
            taxable_paise = _amount_str_to_paise(raw_txval, "taxable_value")
            igst_paise = _amount_str_to_paise(raw_igst, "igst")
            cgst_paise = _amount_str_to_paise(raw_cgst, "cgst")
            sgst_paise = _amount_str_to_paise(raw_sgst, "sgst")
            cess_paise = _amount_str_to_paise(raw_cess, "cess")
        except (ValueError, NormalizationError):
            continue

        raw_val = _parse_numeric_field(entry.get("val"), "val")
        try:
            val_paise = _amount_str_to_paise(raw_val, "invoice_value")
        except (ValueError, NormalizationError):
            val_paise = taxable_paise + igst_paise + cgst_paise + sgst_paise + cess_paise

        pseudo_inum = f"HSN-{hsn_code or 'UNKNOWN'}-{idx}"

        item_record: dict[str, Any] = {
            "tax_rate": None,
            "taxable_value_raw": raw_txval,
            "taxable_value_paise": taxable_paise,
            "igst_paise": igst_paise,
            "cgst_paise": cgst_paise,
            "sgst_paise": sgst_paise,
            "cess_paise": cess_paise,
            "hsn": hsn_code,
            "description": desc,
        }

        record = _build_record(
            section="hsn",
            invoice_type="HSN_SUMMARY",
            doc_type="HSN_SUMMARY",
            is_amendment=False,
            recipient_gstin=None,
            recipient_name="",
            invoice_number=pseudo_inum,
            invoice_number_raw=pseudo_inum,
            invoice_date_norm="",
            invoice_date_raw="",
            invoice_value_paise=val_paise,
            invoice_value_raw=raw_val,
            pos="",
            reverse_charge=False,
            items=[item_record],
            normalization_notes={},
        )
        records.append(record)
        parsed = True

    return "present" if parsed else "empty"


# ---------------------------------------------------------------------------
# Section-level processing — GSTIN-grouped sections (b2b, cdnr)
# ---------------------------------------------------------------------------

def _process_gstin_grouped_section(
    root: dict,
    section_name: str,
    records: list,
    skipped: list,
    is_cdnr: bool,
    is_amendment: bool,
) -> str:
    """Process b2b/b2ba/cdnr/cdnra sections (grouped by recipient GSTIN).

    Returns "present", "empty", or "absent".
    """
    raw_section = root.get(section_name)
    if raw_section is None:
        return "absent"
    if not isinstance(raw_section, list) or len(raw_section) == 0:
        return "empty"

    records_before = len(records)

    for recipient in raw_section:
        if not isinstance(recipient, dict):
            continue

        # Invoice/note list key.
        # Portal exports usually nest invoices under {ctin, inv:[...]}.
        # Some test / simplified payloads place a flat invoice object in the
        # section array itself (inum + ctin on the same dict, no inv[]).
        if is_cdnr:
            inv_list = recipient.get("nt") or recipient.get("inv", [])
        else:
            inv_list = recipient.get("inv", [])
        if not isinstance(inv_list, list):
            inv_list = []
        if (
            not inv_list
            and not is_cdnr
            and recipient.get("inum") is not None
            and recipient.get("ctin") is not None
        ):
            inv_list = [recipient]

        raw_ctin = recipient.get("ctin")
        recipient_name = str(recipient.get("trdnm") or "").strip()
        if raw_ctin is None or (isinstance(raw_ctin, str) and not raw_ctin.strip()):
            ctin_error = ERR_MISSING_RECIPIENT_GSTIN
            ctin_category = SKIP_MISSING_GSTIN
            ctin_reason_code = "missing_recipient_gstin"
        elif not isinstance(raw_ctin, str):
            ctin_error = ERR_INVALID_CTIN_TYPE
            ctin_category = SKIP_INVALID_GSTIN
            ctin_reason_code = "ctin_invalid_type"
        else:
            ctin_error = None
            ctin_category = None
            ctin_reason_code = None

        if ctin_error is not None:
            for inv in inv_list:
                inv_num = _get_inv_num(inv, is_cdnr)
                skipped.append(
                    _make_skip_entry(
                        section_name, "unknown", inv_num, ctin_error, inv,
                        category=ctin_category, reason_code=ctin_reason_code,
                    )
                )
            continue

        gstin_format_invalid = False
        try:
            _gstin_out = normalize_gstin(raw_ctin)
            if hasattr(_gstin_out, "value") and hasattr(_gstin_out, "notes"):
                gstin_result = _validate_result(_gstin_out, "recipient_gstin")
            else:
                gstin_result = _validate_result(
                    NormalizationResult(value=_gstin_out, notes=[]),
                    "recipient_gstin",
                )
        except NormalizationError as e:
            if e.reason in ("invalid_checksum", "invalid_format"):
                cleaned = re.sub(r"[^0-9A-Z]", "", raw_ctin.strip().upper())
                gstin_result = _validate_result(
                    NormalizationResult(value=cleaned, notes=[]),
                    "recipient_gstin",
                )
                gstin_format_invalid = e.reason == "invalid_format"
            else:
                gstin_category, gstin_reason_code = _classify_norm_error(
                    e.field, e.reason
                )
                for inv in inv_list:
                    inv_num = _get_inv_num(inv, is_cdnr)
                    skipped.append(
                        _make_skip_entry(
                            section_name, raw_ctin, inv_num, str(e), inv,
                            category=gstin_category, reason_code=gstin_reason_code,
                        )
                    )
                continue

        recipient_gstin = gstin_result.value

        for invoice in inv_list:
            raw_inum = _get_inv_num(invoice, is_cdnr)
            if not isinstance(invoice, dict):
                skipped.append(
                    _make_skip_entry(
                        section_name, recipient_gstin, "unknown",
                        ERR_INVALID_INVOICE_STRUCTURE, invoice,
                        category=SKIP_MALFORMED_INVOICE,
                        reason_code="invalid_invoice_structure",
                    )
                )
                continue

            try:
                if is_cdnr:
                    record = _parse_cdnr_invoice(
                        invoice, recipient_gstin, raw_ctin, section_name,
                        is_amendment, recipient_name=recipient_name,
                        gstin_format_invalid=gstin_format_invalid,
                    )
                else:
                    record = _parse_b2b_invoice(
                        invoice, recipient_gstin, raw_ctin, section_name,
                        is_amendment, recipient_name=recipient_name,
                        gstin_format_invalid=gstin_format_invalid,
                    )
                records.append(record)
            except (NormalizationError, ValueError, KeyError, TypeError) as e:
                category, reason_code = _classify_skip_exception(e)
                skipped.append(
                    _make_skip_entry(
                        section_name, recipient_gstin, raw_inum, str(e), invoice,
                        category=category, reason_code=reason_code,
                    )
                )
            except Exception:
                raise

    return "present" if len(records) > records_before else "empty"


# ---------------------------------------------------------------------------
# Section-level processing — B2CL (grouped by POS)
# ---------------------------------------------------------------------------

def _process_b2cl_section(
    root: dict,
    section_name: str,
    records: list,
    skipped: list,
    is_amendment: bool,
) -> str:
    """Process b2cl/b2cla sections (grouped by place of supply).

    B2CL structure::

        [ {"pos": "27", "inv": [ {invoice}, ... ]}, ... ]
    """
    raw_section = root.get(section_name)
    if raw_section is None:
        return "absent"
    if not isinstance(raw_section, list) or len(raw_section) == 0:
        return "empty"

    records_before = len(records)

    for pos_group in raw_section:
        if not isinstance(pos_group, dict):
            continue

        pos = str(pos_group.get("pos") or "")
        inv_list = pos_group.get("inv", [])
        if not isinstance(inv_list, list):
            inv_list = []

        for invoice in inv_list:
            if not isinstance(invoice, dict):
                skipped.append(
                    _make_skip_entry(
                        section_name, "", "unknown",
                        ERR_INVALID_INVOICE_STRUCTURE, invoice,
                        category=SKIP_MALFORMED_INVOICE,
                        reason_code="invalid_invoice_structure",
                    )
                )
                continue

            raw_inum = _get_inv_num(invoice, is_cdnr=False)
            try:
                record = _parse_b2cl_invoice(
                    invoice, pos, section_name, is_amendment,
                )
                records.append(record)
            except (NormalizationError, ValueError, KeyError, TypeError) as e:
                category, reason_code = _classify_skip_exception(e)
                skipped.append(
                    _make_skip_entry(
                        section_name, "", raw_inum, str(e), invoice,
                        category=category, reason_code=reason_code,
                    )
                )
            except Exception:
                raise

    return "present" if len(records) > records_before else "empty"


# ---------------------------------------------------------------------------
# Section-level processing — B2CS (flat list)
# ---------------------------------------------------------------------------

def _process_b2cs_section(
    root: dict,
    section_name: str,
    records: list,
    skipped: list,
    is_amendment: bool,
) -> str:
    """Process b2cs/b2csa sections (flat consolidated entries)."""
    raw_section = root.get(section_name)
    if raw_section is None:
        return "absent"
    if not isinstance(raw_section, list) or len(raw_section) == 0:
        return "empty"

    records_before = len(records)

    for idx, entry in enumerate(raw_section):
        if not isinstance(entry, dict):
            continue
        try:
            record = _parse_b2cs_entry(entry, section_name, is_amendment, idx)
            records.append(record)
        except (NormalizationError, ValueError, KeyError, TypeError) as e:
            category, reason_code = _classify_skip_exception(e)
            skipped.append(
                _make_skip_entry(
                    section_name, "", f"b2cs-entry-{idx}", str(e), entry,
                    category=category, reason_code=reason_code,
                )
            )
        except Exception:
            raise

    return "present" if len(records) > records_before else "empty"


# ---------------------------------------------------------------------------
# Section-level processing — CDNUR (flat list of notes)
# ---------------------------------------------------------------------------

def _process_cdnur_section(
    root: dict,
    section_name: str,
    records: list,
    skipped: list,
    is_amendment: bool,
) -> str:
    """Process cdnur/cdnura sections (flat list, no GSTIN grouping)."""
    raw_section = root.get(section_name)
    if raw_section is None:
        return "absent"
    if not isinstance(raw_section, list) or len(raw_section) == 0:
        return "empty"

    records_before = len(records)

    for invoice in raw_section:
        if not isinstance(invoice, dict):
            continue
        raw_inum = _get_inv_num(invoice, is_cdnr=True)
        try:
            record = _parse_cdnur_invoice(invoice, section_name, is_amendment)
            records.append(record)
        except (NormalizationError, ValueError, KeyError, TypeError) as e:
            category, reason_code = _classify_skip_exception(e)
            skipped.append(
                _make_skip_entry(
                    section_name, "", raw_inum, str(e), invoice,
                    category=category, reason_code=reason_code,
                )
            )
        except Exception:
            raise

    return "present" if len(records) > records_before else "empty"


# ---------------------------------------------------------------------------
# Section-level processing — EXP (grouped by export type)
# ---------------------------------------------------------------------------

def _process_exp_section(
    root: dict,
    section_name: str,
    records: list,
    skipped: list,
    is_amendment: bool,
) -> str:
    """Process exp/expa sections.

    Export structure::

        [ {"exp_typ": "WPAY", "inv": [{invoice}, ...]}, ... ]
    """
    raw_section = root.get(section_name)
    if raw_section is None:
        return "absent"
    if not isinstance(raw_section, list) or len(raw_section) == 0:
        return "empty"

    records_before = len(records)

    for exp_group in raw_section:
        if not isinstance(exp_group, dict):
            continue
        export_type = str(exp_group.get("exp_typ") or "").strip().upper()
        inv_list = exp_group.get("inv", [])
        if not isinstance(inv_list, list):
            inv_list = []

        for invoice in inv_list:
            if not isinstance(invoice, dict):
                skipped.append(
                    _make_skip_entry(
                        section_name, "", "unknown",
                        ERR_INVALID_INVOICE_STRUCTURE, invoice,
                        category=SKIP_MALFORMED_INVOICE,
                        reason_code="invalid_invoice_structure",
                    )
                )
                continue
            raw_inum = _get_inv_num(invoice, is_cdnr=False)
            try:
                record = _parse_exp_invoice(
                    invoice, export_type, section_name, is_amendment,
                )
                records.append(record)
            except (NormalizationError, ValueError, KeyError, TypeError) as e:
                category, reason_code = _classify_skip_exception(e)
                skipped.append(
                    _make_skip_entry(
                        section_name, "", raw_inum, str(e), invoice,
                        category=category, reason_code=reason_code,
                    )
                )
            except Exception:
                raise

    return "present" if len(records) > records_before else "empty"


# ---------------------------------------------------------------------------
# Section-level processing — AT/ATA (Advances, flat list)
# ---------------------------------------------------------------------------

def _process_at_section(
    root: dict,
    section_name: str,
    records: list,
    skipped: list,
    is_amendment: bool,
) -> str:
    """Process at/ata sections (advance tax liability, flat entries)."""
    raw_section = root.get(section_name)
    if raw_section is None:
        return "absent"
    if not isinstance(raw_section, list) or len(raw_section) == 0:
        return "empty"

    records_before = len(records)

    for idx, entry in enumerate(raw_section):
        if not isinstance(entry, dict):
            continue
        try:
            record = _parse_at_entry(entry, section_name, is_amendment, idx)
            records.append(record)
        except (NormalizationError, ValueError, KeyError, TypeError) as e:
            category, reason_code = _classify_skip_exception(e)
            skipped.append(
                _make_skip_entry(
                    section_name, "", f"at-entry-{idx}", str(e), entry,
                    category=category, reason_code=reason_code,
                )
            )
        except Exception:
            raise

    return "present" if len(records) > records_before else "empty"


# ---------------------------------------------------------------------------
# Portal layout normalisation
# ---------------------------------------------------------------------------

def _resolve_filing_period(root: dict, parent: dict) -> None:
    """Set ``root['fp']`` from GST portal period fields if missing."""
    if root.get("fp"):
        return
    for source in (root, parent):
        for key in ("fp", "ret_period", "rtnprd"):
            val = source.get(key)
            if val is not None and str(val).strip():
                root["fp"] = str(val).strip()
                return


def normalize_gstr1_payload(data: dict) -> dict:
    """Apply portal layout aliases in-place before ``parse_gstr1``.

    Handles:
    - Filing GSTIN: ``data.gstin`` or top-level ``gstin``
    - Period: ``data.fp`` / ``data.ret_period`` or top-level ``fp``
    - Sections nested under ``data`` or directly on the root
    """
    if not isinstance(data, dict):
        return data

    # Some GSTR-1 downloads wrap everything under "data"
    if "data" in data and isinstance(data["data"], dict):
        root = data["data"]
        if not root.get("gstin"):
            top_gst = data.get("gstin") or data.get("gstnId")
            if top_gst:
                root["gstin"] = top_gst
        _resolve_filing_period(root, data)
        return data

    # Flat structure — treat the whole dict as root
    return {"data": data}


def _parse_filing_period(fp: str) -> datetime.date:
    """Parse GST filing period string to the first day of that month.

    Supports MMYYYY (``042026`` → 2026-04-01) and YYYYMM (``202604``).
    """
    s = str(fp).strip()
    if len(s) != 6 or not s.isdigit():
        raise ValueError("invalid_filing_period")

    a, b = int(s[:2]), int(s[2:])
    if 1 <= a <= 12:
        return datetime.date(b, a, 1)
    if 1 <= b <= 12:
        return datetime.date(a, b, 1)
    raise ValueError("invalid_filing_period")


# ---------------------------------------------------------------------------
# All known GSTR-1 sections
# ---------------------------------------------------------------------------

# Sections that are silently ignored if present (not invoice-level data
# relevant for sales register reconciliation).
_IGNORED_SECTIONS = frozenset({"doc_issue", "isd", "supeco"})

# All sections we actively parse
_ALL_KNOWN_SECTIONS = (
    "b2b", "b2ba", "b2cl", "b2cla", "b2cs", "b2csa",
    "cdnr", "cdnra", "cdnur", "cdnura",
    "exp", "expa", "at", "ata", "nil", "hsn",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_gstr1(file_content) -> dict:
    """Parse GSTR-1 JSON file content into structured records.

    Accepts bytes, str, or a pre-parsed dict.

    Returns::

        {
            "records": [...],
            "skipped": [...],
            "total_rows": int,
            "total_parsed": int,
            "total_skipped": int,
            "section_counts": {"b2b": N, ...},
            "sections_present": [...],
            "sections_absent": [...],
            "filing_gstin": str,
            "filing_period": str,
            "schema_version": str,
        }

    Raises:
        ValueError: For top-level structural errors (invalid JSON, missing
            required keys, unparseable period, unsupported input type).
    """
    # --- Decode input ---
    if isinstance(file_content, dict):
        data = file_content
    elif isinstance(file_content, (bytes, bytearray)):
        try:
            data = json.loads(file_content.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"invalid_json at line {e.lineno}, column {e.colno}: {e.msg}"
            ) from e
    elif isinstance(file_content, str):
        try:
            data = json.loads(file_content)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"invalid_json at line {e.lineno}, column {e.colno}: {e.msg}"
            ) from e
    else:
        raise ValueError("Unsupported input type for GSTR-1 parser")

    if not isinstance(data, dict):
        raise ValueError("invalid_data_structure")

    # --- Normalise layout ---
    data = normalize_gstr1_payload(data)
    root = data.get("data", data)

    if not isinstance(root, dict):
        raise ValueError("invalid_data_structure")

    if not root.get("gstin"):
        raise ValueError("missing_gstin")

    fp_raw = root.get("fp") or root.get("ret_period") or root.get("rtnprd")
    if not fp_raw:
        raise ValueError("missing_filing_period")

    try:
        period = _parse_filing_period(str(fp_raw))
    except ValueError:
        raise ValueError("invalid_filing_period") from None

    filing_gstin_raw = root["gstin"]
    try:
        filing_gstin = normalize_gstin(filing_gstin_raw)
    except NormalizationError:
        filing_gstin = str(filing_gstin_raw).strip().upper()

    logger.debug(
        "gstr1 parse: filing_gstin=%s fp=%s period=%s",
        filing_gstin, fp_raw, period.isoformat(),
    )

    # --- Parse all sections ---
    records: list[dict] = []
    skipped: list[dict] = []
    section_status: dict[str, str] = {}

    # GSTIN-grouped sections: b2b, b2ba, cdnr, cdnra
    for section_name, is_cdnr, is_amendment in [
        ("b2b",   False, False),
        ("b2ba",  False, True),
        ("cdnr",  True,  False),
        ("cdnra", True,  True),
    ]:
        status = _process_gstin_grouped_section(
            root, section_name, records, skipped, is_cdnr, is_amendment,
        )
        section_status[section_name] = status

    # B2CL sections (POS-grouped)
    for section_name, is_amendment in [("b2cl", False), ("b2cla", True)]:
        status = _process_b2cl_section(
            root, section_name, records, skipped, is_amendment,
        )
        section_status[section_name] = status

    # B2CS sections (flat consolidated)
    for section_name, is_amendment in [("b2cs", False), ("b2csa", True)]:
        status = _process_b2cs_section(
            root, section_name, records, skipped, is_amendment,
        )
        section_status[section_name] = status

    # CDNUR sections (flat, no GSTIN grouping)
    for section_name, is_amendment in [("cdnur", False), ("cdnura", True)]:
        status = _process_cdnur_section(
            root, section_name, records, skipped, is_amendment,
        )
        section_status[section_name] = status

    # Export sections (export-type-grouped)
    for section_name, is_amendment in [("exp", False), ("expa", True)]:
        status = _process_exp_section(
            root, section_name, records, skipped, is_amendment,
        )
        section_status[section_name] = status

    # Advance sections (flat)
    for section_name, is_amendment in [("at", False), ("ata", True)]:
        status = _process_at_section(
            root, section_name, records, skipped, is_amendment,
        )
        section_status[section_name] = status

    # Nil-rated / Exempt / Non-GST
    nil_data = root.get("nil")
    if nil_data is not None and isinstance(nil_data, dict):
        section_status["nil"] = _parse_nil_section(nil_data, records, skipped)
    elif nil_data is not None and isinstance(nil_data, list):
        # Some exports wrap nil as a list of dicts
        parsed_any = False
        for nil_item in nil_data:
            if isinstance(nil_item, dict):
                status = _parse_nil_section(nil_item, records, skipped)
                if status == "present":
                    parsed_any = True
        section_status["nil"] = "present" if parsed_any else "empty"
    else:
        section_status["nil"] = "absent"

    # HSN summary
    hsn_data = root.get("hsn")
    if hsn_data is not None and isinstance(hsn_data, dict):
        section_status["hsn"] = _parse_hsn_section(hsn_data, records, skipped)
    else:
        section_status["hsn"] = "absent"

    # --- Aggregate results ---
    sections_present = [s for s, st in section_status.items() if st == "present"]
    sections_absent = [s for s, st in section_status.items() if st == "absent"]

    # Count records per section
    section_counts: dict[str, int] = {}
    for rec in records:
        sec = rec.get("section", "unknown")
        section_counts[sec] = section_counts.get(sec, 0) + 1

    total_parsed = len(records)
    total_skipped = len(skipped)
    total_rows = total_parsed + total_skipped

    # Skip diagnostics
    skip_reasons: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    reason_code_counts: dict[str, int] = {}
    for entry in skipped:
        reason = entry["error_reason"]
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        cat = entry.get("category", SKIP_OTHER)
        code = entry.get("reason_code", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        reason_code_counts[code] = reason_code_counts.get(code, 0) + 1

    skip_breakdown = {
        cat: category_counts[cat]
        for cat in SKIP_CATEGORY_ORDER
        if category_counts.get(cat)
    }
    for cat in sorted(category_counts):
        if cat not in skip_breakdown:
            skip_breakdown[cat] = category_counts[cat]

    skip_breakdown_labeled = [
        {
            "category": cat,
            "label": SKIP_CATEGORY_LABELS.get(cat, cat),
            "count": count,
        }
        for cat, count in skip_breakdown.items()
    ]

    # GSTIN format invalid count
    gstin_format_invalid_count = sum(
        1 for r in records if r.get("gstin_format_invalid")
    )

    # Warn about unknown sections in the JSON
    unknown_sections = [
        k for k in root.keys()
        if k not in _ALL_KNOWN_SECTIONS
        and k not in _IGNORED_SECTIONS
        and k not in ("gstin", "fp", "ret_period", "rtnprd", "gt", "cur_gt",
                       "gendt", "fil_dt", "status", "data", "error")
    ]

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "filing_gstin": filing_gstin,
        "filing_period": period.isoformat(),
        "records": records,
        "skipped": skipped,
        "total_rows": total_rows,
        "total_parsed": total_parsed,
        "total_skipped": total_skipped,
        "section_counts": section_counts,
        "sections_present": sections_present,
        "sections_absent": sections_absent,
        "skip_reasons": skip_reasons,
        "skip_breakdown": skip_breakdown,
        "skip_breakdown_labeled": skip_breakdown_labeled,
        "skip_reason_codes": reason_code_counts,
        "gstin_format_invalid_count": gstin_format_invalid_count,
    }

    if unknown_sections:
        result["unknown_sections"] = unknown_sections

    logger.debug(
        "gstr1 parse result: parsed=%s skipped=%s sections=%s",
        total_parsed, total_skipped, sections_present,
    )

    return result
