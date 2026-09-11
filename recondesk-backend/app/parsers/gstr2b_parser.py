"""GSTR-2B JSON parser.

Parses the official GSTN GSTR-2B JSON format into structured records.
Also accepts a common third-party flat export (top-level ``invoice`` / ``note``
arrays) via ``normalize_alt_2b_schema``, which rewrites into the portal shape
before the same parse path runs.

Supported sections: b2b, b2ba (amendments), cdnr (credit/debit notes),
cdnra (credit/debit note amendments).

Sections ``isd`` and ``impg`` are not parsed into records, but are detected
(present + line-item counts) so the import wizard can warn the CA.
"""

import datetime
import json
import logging
import re
from typing import Any, Mapping

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

SCHEMA_VERSION = "gstr2b_v1"


class AltGstr2bMissingPeriodError(ValueError):
    """Raised when an alt-format GSTR-2B file lacks period info and no fallback was given."""

    pass


# Private keys attached by the Excel adapter (and preserved through parse).
_UNPARSED_ISD_COUNT_KEY = "_unparsed_isd_count"
_UNPARSED_IMPG_COUNT_KEY = "_unparsed_impg_count"

# Nested document-array keys used by portal ISD / IMPG section rows.
_SECTION_NESTED_DOC_KEYS = ("doc", "inv", "nt", "boe", "data")


def _section_line_item_count(section: Any) -> int:
    """Count document/line items in an ISD or IMPG section without parsing.

    Portal ISD rows are usually supplier objects with a nested ``doc``/``inv``
    list. IMPG rows are often flat Bill-of-Entry objects. Empty nested lists
    fall through to counting the parent entry itself when it looks like a
    document row (has any keys other than empty containers).
    """
    if not isinstance(section, list) or not section:
        return 0
    total = 0
    for entry in section:
        if not isinstance(entry, dict):
            total += 1
            continue
        nested: list | None = None
        for key in _SECTION_NESTED_DOC_KEYS:
            val = entry.get(key)
            if isinstance(val, list) and len(val) > 0:
                nested = val
                break
        if nested is not None:
            total += len(nested)
        else:
            total += 1
    return total


def _resolve_section_blob(root: Mapping[str, Any], key: str) -> Any:
    """Prefer ``root[key]``; fall back to ``root.docdata[key]``."""
    raw = root.get(key)
    if raw not in (None, [], {}):
        return raw
    docdata = root.get("docdata")
    if isinstance(docdata, Mapping):
        nested = docdata.get(key)
        if nested not in (None, [], {}):
            return nested
    return raw


def detect_isd_impg_sections(
    root: Mapping[str, Any] | None,
    *,
    excel_isd_count: int = 0,
    excel_impg_count: int = 0,
) -> dict[str, Any]:
    """Detect (do not parse) ISD / IMPG sections on a portal-shaped root.

    Returns ``isd_present``, ``isd_count``, ``impg_present``, ``impg_count``.
    Excel-detected counts are merged via ``max`` (JSON and Excel paths are
    mutually exclusive in practice).
    """
    isd_count = 0
    impg_count = 0
    if isinstance(root, Mapping):
        isd_count = _section_line_item_count(_resolve_section_blob(root, "isd"))
        impg_count = _section_line_item_count(_resolve_section_blob(root, "impg"))
    isd_count = max(int(isd_count or 0), int(excel_isd_count or 0))
    impg_count = max(int(impg_count or 0), int(excel_impg_count or 0))
    return {
        "isd_present": isd_count > 0,
        "isd_count": isd_count,
        "impg_present": impg_count > 0,
        "impg_count": impg_count,
    }


def format_isd_impg_warning(isd_count: int, impg_count: int) -> str | None:
    """Human-readable CA warning when unparsed ISD/IMPG lines were detected."""
    isd_n = int(isd_count or 0)
    impg_n = int(impg_count or 0)
    if isd_n <= 0 and impg_n <= 0:
        return None
    parts: list[str] = []
    if isd_n > 0:
        parts.append(f"{isd_n} ISD credit line(s)")
    if impg_n > 0:
        parts.append(f"{impg_n} import-of-goods line(s)")
    joined = " and ".join(parts)
    return (
        f"This GSTR-2B file contains {joined} that are NOT included in this "
        "reconciliation. Verify these separately."
    )


# ---------------------------------------------------------------------------
# Skip diagnostics — canonical categories
# ---------------------------------------------------------------------------
# Every skipped invoice is bucketed into exactly one canonical category below.
# These power the human-readable "breakdown by reason" without altering the
# verbose ``error_reason`` strings (kept stable for existing consumers/tests).

SKIP_MISSING_GSTIN = "missing_gstin"
SKIP_INVALID_GSTIN = "invalid_gstin"
SKIP_MISSING_INVOICE_NUMBER = "missing_invoice_number"
SKIP_MISSING_INVOICE_DATE = "missing_invoice_date"
SKIP_INVALID_INVOICE_DATE = "invalid_invoice_date"
SKIP_INVALID_AMOUNT = "invalid_amount"
SKIP_UNSUPPORTED_SCHEMA = "unsupported_schema"
SKIP_MALFORMED_INVOICE = "malformed_invoice"
SKIP_OTHER = "other"

# Stable display order for the breakdown.
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

# Human-readable labels for UI / logs.
SKIP_CATEGORY_LABELS: dict[str, str] = {
    SKIP_MISSING_GSTIN: "Missing supplier GSTIN",
    SKIP_INVALID_GSTIN: "Invalid supplier GSTIN",
    SKIP_MISSING_INVOICE_NUMBER: "Missing invoice number",
    SKIP_MISSING_INVOICE_DATE: "Missing invoice date",
    SKIP_INVALID_INVOICE_DATE: "Invalid invoice date",
    SKIP_INVALID_AMOUNT: "Invalid amount",
    SKIP_UNSUPPORTED_SCHEMA: "Unsupported schema",
    SKIP_MALFORMED_INVOICE: "Malformed invoice object",
    SKIP_OTHER: "Other",
}

# Internal raise messages (kept as constants so the raise site and the
# classifier never drift apart). The exact text is part of ``error_reason``.
ERR_MISSING_DATE = "missing_field for dt"
ERR_INVALID_AMOUNT = "Invalid value format for invoice amount"
ERR_INVALID_INVOICE_STRUCTURE = "invalid_invoice_structure"
ERR_UNKNOWN_NOTE_TYPE = "unknown_note_type"
ERR_MISSING_SUPPLIER_GSTIN = "missing_supplier_gstin"
ERR_INVALID_CTIN_TYPE = "Invalid type for field: ctin"


def _classify_norm_error(field: str, reason: str) -> tuple[str, str]:
    """Map a NormalizationError (field, reason) to (category, reason_code)."""
    reason_code = f"{field}:{reason}"
    if field == "gstin":
        return (
            SKIP_MISSING_GSTIN if reason == "empty" else SKIP_INVALID_GSTIN,
            reason_code,
        )
    if field == "invoice_number":
        # None / non-str / empty-after-normalization all mean "no usable number".
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
        # Numeric tax fields (txval/igst/cgst/sgst/cess) failing type checks.
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
    supplier_gstin: str,
    invoice_number: str,
    error_reason: str,
    raw_invoice: Any,
    *,
    category: str = SKIP_OTHER,
    reason_code: str = "other",
) -> dict:
    return {
        "section": section,
        "supplier_gstin": supplier_gstin,
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


def _hsn_str_or_none(v: Any) -> str | None:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    return str(v).strip()


def _first_present(mapping: dict, *keys: str) -> Any:
    """Return the first key present with a non-None value."""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _invoice_date_value(invoice: dict, *, is_cdnr: bool) -> Any:
    """Invoice/note date from GSTN portal or legacy field names."""
    if is_cdnr:
        return _first_present(invoice, "nt_dt", "dt", "idt")
    return _first_present(invoice, "dt", "idt")


def _note_type_value(invoice: dict) -> str:
    """Credit/debit note type from portal or legacy field names.

    Portal JSON uses ``ntyp``; some API dumps use ``nttyp`` / ``typ``;
    older fixtures use ``ntty``. Values are ``C`` (credit) or ``D`` (debit).
    """
    raw = _first_present(invoice, "ntyp", "nttyp", "ntty", "typ")
    if raw is None:
        return ""
    return str(raw).strip().upper()


def _reverse_charge_value(invoice: dict) -> bool:
    raw = _first_present(invoice, "rev", "rchrg") or "N"
    return str(raw).strip().upper() == "Y"


def resolve_itc_available(*records: Mapping[str, Any] | None) -> bool:
    """Resolve GSTR-2B ITC availability boolean across multiple candidate records in priority order.

    Checks 'itc_available', 'itcavl', and nested 'record_data' for each record.
    Continues to the next candidate if a record has None or missing value.
    Defaults to True only if no source record provides any value at all.
    """
    for record in records:
        if not isinstance(record, (dict, Mapping)):
            continue
        raw = _first_present(record, "itc_available", "itcavl")
        if raw is None and isinstance(record.get("record_data"), (dict, Mapping)):
            raw = _first_present(record["record_data"], "itc_available", "itcavl")
        if raw is not None:
            if isinstance(raw, bool):
                return raw
            s = str(raw).strip().upper()
            if s in ("Y", "YES", "TRUE", "1", "T"):
                return True
            if s in ("N", "NO", "FALSE", "0", "F"):
                return False
            return True
    return True


def resolve_itc_reason(*records: Mapping[str, Any] | None) -> str | None:
    """Extract GSTR-2B ITC ineligibility reason string across multiple candidate records."""
    for record in records:
        if not isinstance(record, (dict, Mapping)):
            continue
        raw = _first_present(
            record,
            "itc_reason",
            "rsn",
            "reason",
            "ineligibility_reason",
            "itc_ineligibility_reason",
        )
        if raw is None and isinstance(record.get("record_data"), (dict, Mapping)):
            raw = _first_present(
                record["record_data"],
                "itc_reason",
                "rsn",
                "reason",
                "ineligibility_reason",
                "itc_ineligibility_reason",
            )
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _itc_available_value(invoice: dict) -> bool:
    return resolve_itc_available(invoice)


def _itc_reason_value(invoice: dict) -> str | None:
    return resolve_itc_reason(invoice)


def _item_tax_value(itm: dict, field: str) -> str:
    aliases = {
        "igst": ("igst", "iamt"),
        "cgst": ("cgst", "camt"),
        "sgst": ("sgst", "samt"),
        "cess": ("cess", "csamt"),
    }
    return _parse_numeric_field(_first_present(itm, *aliases[field]), field)


def _invoice_items_list(invoice: dict) -> list:
    """Return GSTR line items from either official `itms` or portal-style `items`."""
    items_list = invoice.get("itms")
    if items_list is None:
        items_list = invoice.get("items", [])
    if items_list is not None and not isinstance(items_list, list):
        raise ValueError(f"invalid_type for itms: {type(items_list)}")
    return items_list or []


def _invoice_level_amount_paise(invoice: dict) -> dict[str, int] | None:
    """Read invoice-root tax fields when ``itms`` / ``items`` are absent.

    Some GSTR-2B dumps (portal / synthetic) put ``txval``, ``cgst``, ``sgst``,
    ``igst``, ``cess`` on the invoice itself instead of under line items. Without
    promoting those into ``*_paise``, the matcher falls back to invoice ``val``
    as taxable and tax=0, which falsely routes exact pairs to AMOUNT_MISMATCH.
    """
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
# Item-level parsing
# ---------------------------------------------------------------------------

def _parse_items(items_list: list) -> tuple:
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
            # rt may live inside itm_det or at the item level
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
        # itms[] line: GSTR-2B puts HSN in itm_det.hsn; some dumps use a flat hsn
        itm_det_raw = item.get("itm_det")
        if itm_det_raw is None or not isinstance(itm_det_raw, dict):
            itm_det_raw = {}
        raw_hsn = _hsn_str_or_none(itm_det_raw.get("hsn"))
        if raw_hsn is None:
            raw_hsn = _hsn_str_or_none(item.get("hsn"))
        if raw_hsn is not None:
            item_record["hsn"] = raw_hsn
        item_records.append(item_record)

    return item_records, raw_txvals


# ---------------------------------------------------------------------------
# Record assembly
# ---------------------------------------------------------------------------

def _build_invoice_record(
    *,
    doc_type: str,
    is_amendment: bool,
    section: str,
    supplier_gstin_raw: str,
    supplier_gstin: str,
    supplier_name: str,
    invoice_number_raw: str,
    invoice_date_raw: str,
    invoice_value_raw: str,
    invoice_number: str,
    invoice_date: datetime.date,
    invoice_value_paise: int,
    original_invoice_number_raw,
    original_invoice_number,
    original_invoice_date_raw,
    original_invoice_date,
    pos: str,
    reverse_charge: bool,
    itc_available: bool,
    items: list,
    supprd: str,
    normalization_notes: dict,
    gstin_format_invalid: bool = False,
    filing_status: str | None = None,
    invoice_level_paise: dict[str, int] | None = None,
    itc_reason: str | None = None,
) -> dict:
    invoice_date_norm = (
        invoice_date.isoformat()
        if isinstance(invoice_date, datetime.date)
        else str(invoice_date)
    )
    if original_invoice_date is None:
        original_invoice_date_norm = None
    elif isinstance(original_invoice_date, datetime.date):
        original_invoice_date_norm = original_invoice_date.isoformat()
    else:
        original_invoice_date_norm = str(original_invoice_date)

    record = {
        "doc_type": doc_type,
        "is_amendment": is_amendment,
        "section": section,
        "schema_version": SCHEMA_VERSION,
        "supplier_gstin_raw": supplier_gstin_raw,
        "supplier_gstin": supplier_gstin,
        "supplier_name": supplier_name,
        "invoice_number_raw": invoice_number_raw,
        "invoice_date_raw": invoice_date_raw,
        "invoice_value_raw": invoice_value_raw,
        "invoice_number": invoice_number,
        "invoice_date_norm": invoice_date_norm,
        "invoice_value_paise": invoice_value_paise,
        "original_invoice_number_raw": original_invoice_number_raw,
        "original_invoice_number": original_invoice_number,
        "original_invoice_date_raw": original_invoice_date_raw,
        "original_invoice_date_norm": original_invoice_date_norm,
        "pos": pos,
        "reverse_charge": reverse_charge,
        "itc_available": itc_available,
        "itc_reason": itc_reason,
        "supprd": supprd,
        "unique_key": None,
        "items": items,
        "normalization_notes": normalization_notes,
        # True when the ``ctin`` field failed strict GSTIN format validation
        # (wrong pattern / length) but the invoice was kept in the pipeline
        # anyway rather than silently dropped. Downstream matching must not
        # trust ``supplier_gstin`` for these records — see
        # ``execute_phase2_and_3``'s GSTIN_FORMAT_INVALID fallback pass.
        "gstin_format_invalid": gstin_format_invalid,
        "filing_status": filing_status,
    }
    if invoice_level_paise:
        record.update(invoice_level_paise)
        record["total_tax_paise"] = (
            int(invoice_level_paise.get("cgst_paise") or 0)
            + int(invoice_level_paise.get("sgst_paise") or 0)
            + int(invoice_level_paise.get("igst_paise") or 0)
            + int(invoice_level_paise.get("cess_paise") or 0)
        )
    return record


# ---------------------------------------------------------------------------
# Invoice-level parsing — b2b / b2ba
# ---------------------------------------------------------------------------

def _parse_b2b_invoice(
    invoice: dict,
    supplier_gstin: str,
    supplier_gstin_raw: str,
    section: str,
    is_amendment: bool,
    supplier_name: str = "",
    gstin_format_invalid: bool = False,
) -> dict:
    normalization_notes: dict = {}

    raw_inum_val = invoice.get("inum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = normalize_invoice(result.value)

    raw_dt = _invoice_date_value(invoice, is_cdnr=False)
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

    pos = str(invoice.get("pos", ""))
    reverse_charge = _reverse_charge_value(invoice)
    itc_available = _itc_available_value(invoice)

    original_invoice_number_raw = None
    original_invoice_number = None
    original_invoice_date_raw = None
    original_invoice_date = None

    if is_amendment:
        oinum_raw = invoice.get("oinum")
        if oinum_raw is not None:
            original_invoice_number_raw = str(oinum_raw)
            result = _validate_result(
                normalize_invoice_number(original_invoice_number_raw),
                "original_invoice_number",
            )
            if result.notes:
                normalization_notes["original_invoice_number"] = result.notes
            original_invoice_number = normalize_invoice(result.value)

        oidt_raw = invoice.get("oidt")
        if oidt_raw is not None:
            original_invoice_date_raw = str(oidt_raw)
            result = _validate_result(normalize_date(oidt_raw), "original_invoice_date")
            if result.notes:
                normalization_notes["original_invoice_date"] = result.notes
            original_invoice_date = result.value

    items_list = _invoice_items_list(invoice)
    item_records, raw_txvals = _parse_items(items_list)
    invoice_level_paise = (
        None if item_records else _invoice_level_amount_paise(invoice)
    )

    raw_filing_status = invoice.get("filing_status")
    filing_status = (
        str(raw_filing_status).strip().upper()
        if raw_filing_status is not None and str(raw_filing_status).strip() != ""
        else None
    )

    return _build_invoice_record(
        doc_type="INVOICE",
        is_amendment=is_amendment,
        section=section,
        supplier_gstin_raw=supplier_gstin_raw,
        supplier_gstin=supplier_gstin,
        supplier_name=supplier_name,
        invoice_number_raw=raw_inum,
        invoice_date_raw=str(raw_dt),
        invoice_value_raw=raw_val,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        invoice_value_paise=invoice_value_paise,
        original_invoice_number_raw=original_invoice_number_raw,
        original_invoice_number=original_invoice_number,
        original_invoice_date_raw=original_invoice_date_raw,
        original_invoice_date=original_invoice_date,
        pos=pos,
        reverse_charge=reverse_charge,
        itc_available=itc_available,
        supprd=str(invoice.get("supprd", "")).strip(),
        items=item_records,
        normalization_notes=normalization_notes,
        gstin_format_invalid=gstin_format_invalid,
        filing_status=filing_status,
        invoice_level_paise=invoice_level_paise,
        itc_reason=_itc_reason_value(invoice),
    )


# ---------------------------------------------------------------------------
# Invoice-level parsing — cdnr / cdnra
# ---------------------------------------------------------------------------

def _parse_cdnr_invoice(
    invoice: dict,
    supplier_gstin: str,
    supplier_gstin_raw: str,
    section: str,
    is_amendment: bool,
    supplier_name: str = "",
    gstin_format_invalid: bool = False,
) -> dict:
    normalization_notes: dict = {}

    ntty = _note_type_value(invoice)
    if ntty == "C":
        document_type = "CREDIT_NOTE"
    elif ntty == "D":
        document_type = "DEBIT_NOTE"
    else:
        raise ValueError(ERR_UNKNOWN_NOTE_TYPE)

    # Support both GSTN API field names: "nt_num" (current) and "ntnum" (legacy)
    raw_inum_val = invoice.get("nt_num") or invoice.get("ntnum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = normalize_invoice(result.value)

    raw_dt = _invoice_date_value(invoice, is_cdnr=True)
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

    pos = str(invoice.get("pos", ""))
    reverse_charge = _reverse_charge_value(invoice)
    itc_available = _itc_available_value(invoice)

    original_invoice_number_raw = None
    original_invoice_number = None
    original_invoice_date_raw = None
    original_invoice_date = None

    if is_amendment:
        ointnum_raw = invoice.get("ointnum")
        if ointnum_raw is not None:
            original_invoice_number_raw = str(ointnum_raw)
            result = _validate_result(
                normalize_invoice_number(original_invoice_number_raw),
                "original_invoice_number",
            )
            if result.notes:
                normalization_notes["original_invoice_number"] = result.notes
            original_invoice_number = normalize_invoice(result.value)

        ointdt_raw = invoice.get("ointdt")
        if ointdt_raw is not None:
            original_invoice_date_raw = str(ointdt_raw)
            result = _validate_result(normalize_date(ointdt_raw), "original_invoice_date")
            if result.notes:
                normalization_notes["original_invoice_date"] = result.notes
            original_invoice_date = result.value

    items_list = _invoice_items_list(invoice)
    item_records, raw_txvals = _parse_items(items_list)
    invoice_level_paise = (
        None if item_records else _invoice_level_amount_paise(invoice)
    )

    return _build_invoice_record(
        doc_type=document_type,
        is_amendment=is_amendment,
        section=section,
        supplier_gstin_raw=supplier_gstin_raw,
        supplier_gstin=supplier_gstin,
        supplier_name=supplier_name,
        invoice_number_raw=raw_inum,
        invoice_date_raw=str(raw_dt),
        invoice_value_raw=raw_val,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        invoice_value_paise=invoice_value_paise,
        original_invoice_number_raw=original_invoice_number_raw,
        original_invoice_number=original_invoice_number,
        original_invoice_date_raw=original_invoice_date_raw,
        original_invoice_date=original_invoice_date,
        pos=pos,
        reverse_charge=reverse_charge,
        itc_available=itc_available,
        supprd=str(invoice.get("supprd", "")).strip(),
        items=item_records,
        normalization_notes=normalization_notes,
        gstin_format_invalid=gstin_format_invalid,
        invoice_level_paise=invoice_level_paise,
        itc_reason=_itc_reason_value(invoice),
    )


# ---------------------------------------------------------------------------
# Section-level helpers
# ---------------------------------------------------------------------------

def _get_inv_num(invoice: Any, is_cdnr: bool) -> str:
    """Extract the invoice/note number string for use in skip entries."""
    if not isinstance(invoice, dict):
        return "unknown"
    if is_cdnr:
        val = invoice.get("nt_num") or invoice.get("ntnum")
    else:
        val = invoice.get("inum")
    return str(val) if val is not None else "unknown"


# ---------------------------------------------------------------------------
# Output enrichment
# ---------------------------------------------------------------------------

def _enrich_record(record: dict, buyer_gstin: str) -> None:
    """Add standardized output fields to a parsed record (in-place).

    Adds: buyer_gstin, supplier_gstin_norm, invoice_number_norm,
          taxable_value (rupees int), unique_key (string).
    Never removes or renames existing fields.
    Falls back to raw values if normalization fails.
    """
    record["buyer_gstin"] = buyer_gstin

    # supplier_gstin_norm — guaranteed uppercase
    record["supplier_gstin_norm"] = str(record.get("supplier_gstin", "")).upper()

    # invoice_number_norm — uppercase, trimmed
    record["invoice_number_norm"] = str(record["invoice_number"]).strip().upper()

    # taxable_value — sum of item taxable values in whole rupees (integer).
    # Prefer invoice-root taxable_value_paise when line items are absent
    # (flat GSTR dumps); never fall back to invoice val as taxable.
    items = record.get("items") or []
    if items:
        total_paise = sum(item.get("taxable_value_paise", 0) for item in items)
    elif record.get("taxable_value_paise") is not None:
        total_paise = int(record.get("taxable_value_paise") or 0)
    else:
        total_paise = record.get("invoice_value_paise", 0)
    record["taxable_value"] = round(total_paise / 100)

    # unique_key — stable string, safe for JSON / DB keys
    record["unique_key"] = (
        f"{record['buyer_gstin']}"
        f"|{record['invoice_number_norm']}"
        f"|{record['invoice_date_norm']}"
    )


# ---------------------------------------------------------------------------
# Structure validation
# ---------------------------------------------------------------------------

def validate_b2b_record(record: dict) -> None:
    """Validate a single b2b supplier record for required fields and types.

    Raises:
        ValueError: If a required field is missing or has the wrong type.
    """
    if not isinstance(record, dict):
        raise ValueError("Invalid type for field: b2b_record")

    if "ctin" not in record:
        raise ValueError("Missing required field: ctin")
    if not isinstance(record["ctin"], str):
        raise ValueError("Invalid type for field: ctin")

    if "inv" not in record:
        raise ValueError("Missing required field: inv")
    if not isinstance(record["inv"], list):
        raise ValueError("Invalid type for field: inv")

    for idx, invoice in enumerate(record["inv"]):
        if not isinstance(invoice, dict):
            raise ValueError(f"Invalid type for field: inv[{idx}]")

        if "inum" not in invoice:
            raise ValueError("Missing required field: inum")
        if not isinstance(invoice["inum"], str):
            raise ValueError("Invalid type for field: inum")

        if "val" not in invoice:
            raise ValueError("Missing required field: val")
        val = invoice["val"]
        if not isinstance(val, (int, float, str)) or isinstance(val, bool):
            raise ValueError("Invalid type for field: val")


# ---------------------------------------------------------------------------
# Section-level processing
# ---------------------------------------------------------------------------

def _process_section(
    root: dict,
    section_name: str,
    records: list,
    skipped: list,
    is_cdnr: bool,
    is_amendment: bool,
) -> str:
    """Process one section of the GSTR-2B document.

    Returns:
        "present"  — at least one record successfully parsed.
        "empty"    — key exists but zero records were parsed.
        "absent"   — key not present in JSON.
    """
    raw_section = root.get(section_name)
    if raw_section is None:
        return "absent"

    if not isinstance(raw_section, list) or len(raw_section) == 0:
        return "empty"

    records_before = len(records)

    for supplier in raw_section:
        if not isinstance(supplier, dict):
            continue

        # CDNR: GSTN API uses "nt" array; legacy format uses "inv"
        if is_cdnr:
            inv_list = supplier.get("nt") or supplier.get("inv", [])
        else:
            inv_list = supplier.get("inv", [])
        if not isinstance(inv_list, list):
            inv_list = []

        raw_ctin = supplier.get("ctin")
        supplier_name = str(supplier.get("trdnm") or "").strip()
        if raw_ctin is None or (isinstance(raw_ctin, str) and not raw_ctin.strip()):
            ctin_error = ERR_MISSING_SUPPLIER_GSTIN
            ctin_category = SKIP_MISSING_GSTIN
            ctin_reason_code = "missing_supplier_gstin"
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
                        section_name,
                        "unknown",
                        inv_num,
                        ctin_error,
                        inv,
                        category=ctin_category,
                        reason_code=ctin_reason_code,
                    )
                )
            continue

        gstin_format_invalid = False
        try:
            _gstin_out = normalize_gstin(raw_ctin)
            # normalize_gstin currently returns a plain str; tolerate a
            # NormalizationResult-compatible object (e.g. in tests or after a
            # future refactor) by unwrapping .value when present.
            if hasattr(_gstin_out, "value") and hasattr(_gstin_out, "notes"):
                gstin_result = _validate_result(_gstin_out, "supplier_gstin")
            else:
                gstin_result = _validate_result(
                    NormalizationResult(value=_gstin_out, notes=[]),
                    "supplier_gstin",
                )
        except NormalizationError as e:
            if e.reason == "invalid_checksum":
                # GSTIN passes format/length/structure checks but fails checksum.
                # Accept with cleaned uppercase value — real-world and legacy GSTINs
                # may use a different checksum variant.
                cleaned = re.sub(r"[^0-9A-Z]", "", raw_ctin.strip().upper())
                gstin_result = _validate_result(
                    NormalizationResult(value=cleaned, notes=[]),
                    "supplier_gstin",
                )
            elif e.reason == "invalid_format":
                # The cleaned value IS 15 characters (length check already
                # passed) but fails the structural GSTIN/PAN pattern — e.g. a
                # single corrupted character from what was otherwise clearly an
                # attempt at a real GSTIN. This is deliberately narrower than
                # "any GSTIN normalization failure": a hopelessly short/garbage
                # string (invalid_length) carries no real signal and stays
                # dropped below. Do not silently drop this invoice: a corrupted
                # GSTIN digit still leaves a real GSTR-2B invoice that a human
                # (or the invoice_number+amount+trade-name fallback matcher in
                # execute_phase2_and_3) can reconcile. Dropping it here used to
                # make the invoice vanish entirely from Total GSTR and cause its
                # legitimate PR-side counterpart to be mislabeled as "supplier
                # never filed" (ITC at Risk) when the supplier actually did file,
                # just with a mangled GSTIN. Keep the cleaned (whitelisted,
                # uppercased) value so matching still has *something* to compare,
                # and flag the record so GSTIN is never trusted for it downstream.
                cleaned = re.sub(r"[^0-9A-Z]", "", raw_ctin.strip().upper())
                gstin_result = _validate_result(
                    NormalizationResult(value=cleaned, notes=[]),
                    "supplier_gstin",
                )
                gstin_format_invalid = True
            else:
                gstin_category, gstin_reason_code = _classify_norm_error(
                    e.field, e.reason
                )
                for inv in inv_list:
                    inv_num = _get_inv_num(inv, is_cdnr)
                    skipped.append(
                        _make_skip_entry(
                            section_name,
                            raw_ctin,
                            inv_num,
                            str(e),
                            inv,
                            category=gstin_category,
                            reason_code=gstin_reason_code,
                        )
                    )
                continue

        supplier_gstin = gstin_result.value

        for invoice in inv_list:
            raw_inum = _get_inv_num(invoice, is_cdnr)

            if not isinstance(invoice, dict):
                skipped.append(
                    _make_skip_entry(
                        section_name,
                        supplier_gstin,
                        "unknown",
                        ERR_INVALID_INVOICE_STRUCTURE,
                        invoice,
                        category=SKIP_MALFORMED_INVOICE,
                        reason_code="invalid_invoice_structure",
                    )
                )
                continue

            try:
                if is_cdnr:
                    record = _parse_cdnr_invoice(
                        invoice, supplier_gstin, raw_ctin, section_name, is_amendment,
                        supplier_name=supplier_name,
                        gstin_format_invalid=gstin_format_invalid,
                    )
                else:
                    record = _parse_b2b_invoice(
                        invoice, supplier_gstin, raw_ctin, section_name, is_amendment,
                        supplier_name=supplier_name,
                        gstin_format_invalid=gstin_format_invalid,
                    )
                records.append(record)
            except (NormalizationError, ValueError, KeyError, TypeError) as e:
                category, reason_code = _classify_skip_exception(e)
                skipped.append(
                    _make_skip_entry(
                        section_name,
                        supplier_gstin,
                        raw_inum,
                        str(e),
                        invoice,
                        category=category,
                        reason_code=reason_code,
                    )
                )
            except Exception:
                raise

    if len(records) > records_before:
        return "present"
    return "empty"


# ---------------------------------------------------------------------------
# Portal layout normalization (fp / gstin aliases)
# ---------------------------------------------------------------------------

def _resolve_rtnprd(root: dict, parent: dict) -> None:
    """Set ``root['rtnprd']`` from GST portal period fields if missing.

    GSTN exports use ``fp`` (filing period) as MMYYYY, e.g. ``042026`` for Apr 2026.
    It may appear on ``data`` (``data.fp``) or the JSON root (``fp``), not only as
    ``rtnprd``.
    """
    if root.get("rtnprd"):
        return
    for source in (root, parent):
        for key in ("fp", "ret_period", "rtnprd"):
            val = source.get(key)
            if val is not None and str(val).strip():
                root["rtnprd"] = str(val).strip()
                return


def normalize_gstr2b_payload(data: dict) -> dict:
    """Apply portal layout aliases in-place before ``parse_gstr2b``.

    - Buyer GSTIN: ``data.gstin`` or top-level ``gstnId`` / ``gstin``
    - Period: ``data.fp`` / ``data.rtnprd`` or top-level ``fp`` / ``ret_period``
    - Sections: ``data.docdata.b2b`` merged into ``data.b2b`` when needed
    """
    if not isinstance(data, dict) or "data" not in data:
        return data

    root = data["data"]
    if not isinstance(root, dict):
        return data

    if not root.get("gstin"):
        top_gst = data.get("gstnId") or data.get("gstin")
        if top_gst:
            root["gstin"] = top_gst

    _resolve_rtnprd(root, data)

    docdata = root.get("docdata")
    if isinstance(docdata, dict):
        for key in ("b2b", "b2ba", "cdnr", "cdnra"):
            if key not in root or root.get(key) in (None, [], {}):
                if docdata.get(key) not in (None, [], {}):
                    root[key] = docdata[key]

    return data


# ---------------------------------------------------------------------------
# Alternate third-party GSTR-2B JSON (flat ``invoice`` / ``note`` lists)
# ---------------------------------------------------------------------------

_UNSUPPORTED_GSTR2B_SCHEMA = (
    "unsupported_gstr2b_schema: expected either official GST portal JSON "
    '(top-level "data" with b2b/docdata) or third-party export JSON '
    '(top-level "invoice" array of flat records with GSTIN / Invoice No / '
    "Invoice Date). "
    "IMS-only sheets (invoice_ims / note_ims) are not imported yet."
)

# Used when alt-schema JSON has no extractable buyer GSTIN and no client fallback.
ALT_2B_PLACEHOLDER_BUYER_GSTIN = "000000000000000"

BUYER_GSTIN_SOURCE_FILE = "file"
BUYER_GSTIN_SOURCE_CLIENT = "client"
BUYER_GSTIN_SOURCE_PLACEHOLDER = "placeholder"
BUYER_GSTIN_SOURCE_PORTAL = "portal"

BUYER_GSTIN_MISSING_WARNING = (
    "Buyer GSTIN not found in file or client record — matching may be inaccurate"
)


_GSTIN_IN_TEXT_RE = re.compile(
    r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9])\b",
    re.IGNORECASE,
)

_MONTH_ABBR_TO_NUM: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Portal POS is a 2-digit state code; third-party exports often use names.
_POS_NAME_TO_CODE: dict[str, str] = {
    "jammu and kashmir": "01",
    "jammu & kashmir": "01",
    "himachal pradesh": "02",
    "punjab": "03",
    "chandigarh": "04",
    "uttarakhand": "05",
    "haryana": "06",
    "delhi": "07",
    "rajasthan": "08",
    "uttar pradesh": "09",
    "bihar": "10",
    "sikkim": "11",
    "arunachal pradesh": "12",
    "nagaland": "13",
    "manipur": "14",
    "mizoram": "15",
    "tripura": "16",
    "meghalaya": "17",
    "assam": "18",
    "west bengal": "19",
    "jharkhand": "20",
    "odisha": "21",
    "orissa": "21",
    "chhattisgarh": "22",
    "madhya pradesh": "23",
    "gujarat": "24",
    "dadra and nagar haveli and daman and diu": "26",
    "maharashtra": "27",
    "karnataka": "29",
    "goa": "30",
    "lakshadweep": "31",
    "kerala": "32",
    "tamil nadu": "33",
    "puducherry": "34",
    "pondicherry": "34",
    "andaman and nicobar islands": "35",
    "telangana": "36",
    "andhra pradesh": "37",
    "ladakh": "38",
    "other territory": "97",
}


def is_alt_gstr2b_schema(data: dict) -> bool:
    """True when payload is a flat third-party ``invoice`` list export."""
    if not isinstance(data, dict):
        return False
    if "data" in data and isinstance(data.get("data"), dict):
        return False
    invoices = data.get("invoice")
    if not isinstance(invoices, list) or not invoices:
        return False
    # Known column names that identify an alt-format invoice row.
    _IDENTITY_KEYS = {
        "gstin", "gstin of supplier", "supplier gstin", "ctin",
        "invoice no", "invoice number", "invoice number", "inum",
        "document number",
    }
    for row in invoices[:20]:
        if not isinstance(row, dict):
            continue
        keys = {_alt_key_norm(k) for k in row.keys()}
        if keys & _IDENTITY_KEYS:
            return True
    return False


def _alt_key_norm(key: Any) -> str:
    return re.sub(r"\s+", " ", str(key or "").strip().lower())


def _alt_row_get(row: Mapping[str, Any], *names: str) -> Any:
    """Case/space-insensitive field lookup (handles ``Invoice Value ``)."""
    wanted = {_alt_key_norm(n) for n in names}
    first_blank = None
    has_blank = False
    for k, v in row.items():
        if _alt_key_norm(k) in wanted:
            if not _alt_blank(v):
                return v
            if not has_blank:
                first_blank = v
                has_blank = True
    return first_blank if has_blank else None


def _alt_blank(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and val != val:  # NaN
        return True
    s = str(val).strip()
    return s == "" or s.lower() in {"nan", "none", "null"}


def _alt_parse_period_to_rtnprd(raw: Any) -> str | None:
    """Convert ``Jun,2026`` / ``Jun 2026`` / ``06-2026`` / ``2026-06`` / ``2026-06-01`` → ``MMYYYY``."""
    if _alt_blank(raw):
        return None
    s = str(raw).strip()
    m = re.match(r"^([A-Za-z]{3,9})\s*,?\s*(\d{4})$", s)
    if m:
        token = m.group(1).lower()
        mon = _MONTH_ABBR_TO_NUM.get(
            "sept" if token.startswith("sept") else token[:3]
        )
        if mon:
            return f"{mon:02d}{m.group(2)}"
    m2 = re.match(r"^(\d{1,2})[-/](\d{4})$", s)
    if m2:
        mon = int(m2.group(1))
        if 1 <= mon <= 12:
            return f"{mon:02d}{m2.group(2)}"
    m3 = re.match(r"^(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?$", s)
    if m3:
        year = m3.group(1)
        mon = int(m3.group(2))
        if 1 <= mon <= 12:
            return f"{mon:02d}{year}"
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 6:
        m_part, y_part = int(digits[:2]), int(digits[2:])
        if 1 <= m_part <= 12 and 1900 <= y_part <= 2100:
            return digits
        y_part, m_part = int(digits[:4]), int(digits[4:])
        if 1900 <= y_part <= 2100 and 1 <= m_part <= 12:
            return f"{m_part:02d}{y_part}"
        return digits
    return None


def _alt_pos_code(raw: Any) -> str:
    if _alt_blank(raw):
        return ""
    s = str(raw).strip()
    if re.fullmatch(r"\d{1,2}", s):
        return s.zfill(2)
    return _POS_NAME_TO_CODE.get(s.lower(), s)


def _alt_rc_to_rev(raw: Any) -> str:
    if _alt_blank(raw):
        return "N"
    s = str(raw).strip().lower()
    if s in {"y", "yes", "true", "1"}:
        return "Y"
    return "N"


def _alt_num(raw: Any) -> float:
    if _alt_blank(raw):
        return 0.0
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _alt_invoice_date_portal(raw: Any) -> str:
    """Return portal ``dt`` string DD-MM-YYYY when parseable, else original text."""
    if _alt_blank(raw):
        return ""
    try:
        result = normalize_date(raw)
        d = result.value
        if isinstance(d, datetime.date):
            return d.strftime("%d-%m-%Y")
    except NormalizationError:
        pass
    return str(raw).strip()


def _alt_extract_buyer_gstin(data: dict) -> str:
    for key in ("gstin", "gstnId", "buyer_gstin", "recipient_gstin", "client_gstin"):
        val = data.get(key)
        if not _alt_blank(val):
            return str(val).strip().upper()
    for key in ("title", "header", "client", "taxpayer", "trade_name"):
        val = data.get(key)
        if isinstance(val, str):
            m = _GSTIN_IN_TEXT_RE.search(val)
            if m:
                return m.group(1).upper()
    # Excel→JSON dumps sometimes put the title (with GSTIN) as a row *key*.
    for key in list(data.keys()):
        if isinstance(key, str):
            m = _GSTIN_IN_TEXT_RE.search(key)
            if m:
                return m.group(1).upper()
    for section in ("invoice", "note"):
        rows = data.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            for key in row.keys():
                if isinstance(key, str):
                    m = _GSTIN_IN_TEXT_RE.search(key)
                    if m:
                        return m.group(1).upper()
    return ""


def _alt_map_invoice_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Map one flat third-party invoice row → portal-ish inv object.

    Returns ``None`` for blank-Sr totals/summary rows.  When no ``Sr``
    column exists at all (e.g. GSTN portal Excel export), the row is kept
    when it has an identifiable GSTIN **or** invoice number.
    """
    sr = _alt_row_get(row, "Sr", "sr", "S.No", "S No", "Sl", "Sl.", "Sl. No.")

    gstin = str(
        _alt_row_get(
            row, "GSTIN", "gstin", "GSTIN of Supplier",
            "Supplier GSTIN", "ctin",
        ) or ""
    ).strip().upper()
    inum = str(
        _alt_row_get(
            row, "Invoice No", "Invoice Number", "invoice_no", "inum",
            "Document Number", "Doc No",
        ) or ""
    ).strip()

    # Blank-Sr rows are totals/summary — skip UNLESS the row has
    # identifiable data (GSTIN or invoice number), which means the
    # file simply has no Sr column (GSTN portal Excel).
    if _alt_blank(sr):
        if not gstin and not inum:
            return None
        # Has data but no Sr → check if the file genuinely lacks an Sr column
        # by verifying the row has at least one of GSTIN or invoice number.
        # (If both are blank on a blank-Sr row, it really is a totals row.)

    if not gstin and not inum:
        return None

    party = str(
        _alt_row_get(
            row, "Party", "Supplier", "supplier_name",
            "Trade/Legal Name", "Trade/Legal Name of Supplier",
            "Trade Name", "Legal Name", "trdnm",
        ) or ""
    ).strip()

    val = _alt_num(
        _alt_row_get(
            row,
            "Invoice Value", "invoice_value",
            "Invoice Amount", "invoice_amount",
            "Total Amount", "total_amount",
            "Document Value", "Total Value", "val",
        )
    )
    txval = _alt_num(
        _alt_row_get(
            row,
            "Taxable Value", "taxable_value",
            "Taxable Amount", "taxable_amount",
            "Taxable Amt", "taxable_amt",
            "Taxable", "txval",
        )
    )
    igst = _alt_num(
        _alt_row_get(
            row,
            "IGST", "igst", "iamt", "Integrated Tax",
            "IGST Amount", "igst_amount",
            "Integrated Tax Amount", "integrated_tax_amount",
        )
    )
    cgst = _alt_num(
        _alt_row_get(
            row,
            "CGST", "cgst", "camt", "Central Tax",
            "CGST Amount", "cgst_amount",
            "Central Tax Amount", "central_tax_amount",
        )
    )
    sgst = _alt_num(
        _alt_row_get(
            row,
            "SGST", "sgst", "samt", "State/UT Tax",
            "SGST Amount", "sgst_amount",
            "State Tax Amount", "state_tax_amount",
            "State Tax", "state_tax",
        )
    )
    cess = _alt_num(
        _alt_row_get(
            row,
            "CESS", "cess", "csamt",
            "Cess Amount", "cess_amount",
            "Compensation Cess", "compensation_cess",
        )
    )
    if val == 0.0 and (txval > 0.0 or igst > 0.0 or cgst > 0.0 or sgst > 0.0 or cess > 0.0):
        val = round(txval + igst + cgst + sgst + cess, 2)

    return {
        "_supplier_gstin": gstin,
        "_supplier_name": party,
        "_rtnprd": _alt_parse_period_to_rtnprd(
            _alt_row_get(row, "Period", "period", "Return Period", "Filing Period")
        ),
        "inum": inum,
        "dt": _alt_invoice_date_portal(
            _alt_row_get(
                row, "Invoice Date", "invoice_date", "idt",
                "Document Date", "Doc Date",
            )
        ),
        "val": val,
        "txval": txval,
        "igst": igst,
        "cgst": cgst,
        "sgst": sgst,
        "cess": cess,
        "pos": _alt_pos_code(
            _alt_row_get(row, "POS", "pos", "Place of Supply", "Place Of Supply")
        ),
        "rev": _alt_rc_to_rev(
            _alt_row_get(
                row, "RC", "rev", "rchrg", "Reverse Charge",
                "Applicable % of Tax Rate",
            )
        ),
        "itcavl": str(
            _alt_row_get(
                row,
                "ITC Available",
                "itcavl",
                "ITC Availability",
                "ITC Eligibility",
                "itc_available",
                "itc_avl",
            )
            or "Y"
        ).strip().upper()[:1] or "Y",
        "rsn": _alt_row_get(
            row,
            "Reason",
            "rsn",
            "ITC Ineligibility Reason",
            "Reason for Ineligibility",
            "Ineligibility Reason",
            "itc_reason",
            "reason",
        ),
    }


def _alt_map_note_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Map one flat credit/debit note row → portal cdnr note object."""
    sr = _alt_row_get(row, "Sr", "sr", "S.No", "S No", "Sl", "Sl.", "Sl. No.")

    gstin = str(
        _alt_row_get(
            row, "GSTIN", "gstin", "GSTIN of Supplier",
            "Supplier GSTIN", "ctin",
        ) or ""
    ).strip().upper()
    nt_num = str(
        _alt_row_get(
            row, "Note No", "Note Number", "nt_num", "ntnum",
            "Document Number", "Doc No",
        ) or ""
    ).strip()

    if _alt_blank(sr):
        if not gstin and not nt_num:
            return None

    if not gstin and not nt_num:
        return None

    ntty_raw = str(
        _alt_row_get(row, "Note Type", "ntty", "type", "Document Type") or ""
    ).strip().upper()
    if ntty_raw.startswith("C") or "CREDIT" in ntty_raw:
        ntty = "C"
    elif ntty_raw.startswith("D") or "DEBIT" in ntty_raw:
        ntty = "D"
    else:
        ntty = "C"

    party = str(
        _alt_row_get(
            row, "Party", "Supplier", "supplier_name",
            "Trade/Legal Name", "Trade/Legal Name of Supplier",
            "Trade Name", "Legal Name", "trdnm",
        ) or ""
    ).strip()

    val = _alt_num(
        _alt_row_get(
            row,
            "Note Value", "note_value",
            "Invoice Value", "invoice_value",
            "Invoice Amount", "invoice_amount",
            "Total Amount", "total_amount",
            "Document Value", "Total Value", "val",
        )
    )
    txval = _alt_num(
        _alt_row_get(
            row,
            "Taxable Value", "taxable_value",
            "Taxable Amount", "taxable_amount",
            "Taxable Amt", "taxable_amt",
            "Taxable", "txval",
        )
    )
    igst = _alt_num(
        _alt_row_get(
            row,
            "IGST", "igst", "iamt", "Integrated Tax",
            "IGST Amount", "igst_amount",
            "Integrated Tax Amount", "integrated_tax_amount",
        )
    )
    cgst = _alt_num(
        _alt_row_get(
            row,
            "CGST", "cgst", "camt", "Central Tax",
            "CGST Amount", "cgst_amount",
            "Central Tax Amount", "central_tax_amount",
        )
    )
    sgst = _alt_num(
        _alt_row_get(
            row,
            "SGST", "sgst", "samt", "State/UT Tax",
            "SGST Amount", "sgst_amount",
            "State Tax Amount", "state_tax_amount",
            "State Tax", "state_tax",
        )
    )
    cess = _alt_num(
        _alt_row_get(
            row,
            "CESS", "cess", "csamt",
            "Cess Amount", "cess_amount",
            "Compensation Cess", "compensation_cess",
        )
    )
    if val == 0.0 and (txval > 0.0 or igst > 0.0 or cgst > 0.0 or sgst > 0.0 or cess > 0.0):
        val = round(txval + igst + cgst + sgst + cess, 2)

    return {
        "_supplier_gstin": gstin,
        "_supplier_name": party,
        "_rtnprd": _alt_parse_period_to_rtnprd(
            _alt_row_get(row, "Period", "period", "Return Period", "Filing Period")
        ),
        "nt_num": nt_num,
        "ntty": ntty,
        "dt": _alt_invoice_date_portal(
            _alt_row_get(
                row, "Note Date", "note_date", "idt",
                "Document Date", "Doc Date",
            )
        ),
        "val": val,
        "txval": txval,
        "igst": igst,
        "cgst": cgst,
        "sgst": sgst,
        "cess": cess,
        "pos": _alt_pos_code(
            _alt_row_get(row, "POS", "pos", "Place of Supply", "Place Of Supply")
        ),
        "rev": _alt_rc_to_rev(
            _alt_row_get(
                row, "RC", "rev", "rchrg", "Reverse Charge",
                "Applicable % of Tax Rate",
            )
        ),
        "itcavl": str(
            _alt_row_get(
                row,
                "ITC Available",
                "itcavl",
                "ITC Availability",
                "ITC Eligibility",
                "itc_available",
                "itc_avl",
            )
            or "Y"
        ).strip().upper()[:1] or "Y",
        "rsn": _alt_row_get(
            row,
            "Reason",
            "rsn",
            "ITC Ineligibility Reason",
            "Reason for Ineligibility",
            "Ineligibility Reason",
            "itc_reason",
            "reason",
        ),
    }


def _alt_group_by_supplier(mapped_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build portal ``[{ctin, trdnm, inv: [...]}, ...]`` from mapped flat rows."""
    order: list[str] = []
    buckets: dict[str, dict[str, Any]] = {}
    for row in mapped_rows:
        ctin = str(row.pop("_supplier_gstin", "") or "").strip().upper() or "UNKNOWN"
        name = str(row.pop("_supplier_name", "") or "").strip()
        row.pop("_rtnprd", None)
        if ctin not in buckets:
            order.append(ctin)
            buckets[ctin] = {"ctin": ctin, "trdnm": name, "inv": []}
        elif name and not buckets[ctin].get("trdnm"):
            buckets[ctin]["trdnm"] = name
        buckets[ctin]["inv"].append(row)
    return [buckets[k] for k in order]


def normalize_alt_2b_schema(
    data: dict,
    *,
    fallback_buyer_gstin: str | None = None,
    fallback_period: str | None = None,
) -> dict:
    """Convert third-party flat GSTR-2B JSON into portal-shaped ``{"data": ...}``.

    Accepts::

        {"invoice": [{Sr, Party, GSTIN, Invoice No, ...}, ...], "note": [...], ...}

    Skips blank-``Sr`` totals rows. Ignores ``invoice_ims`` / ``note_ims``.
    Output is accepted by the existing portal ``parse_gstr2b`` path.

    When the export has no usable buyer GSTIN, ``fallback_buyer_gstin`` (typically
    ``client_gstins.gstin`` for the run's client) is used. If that is also empty,
    ``ALT_2B_PLACEHOLDER_BUYER_GSTIN`` is used and
    ``_alt_buyer_gstin_source`` is ``"placeholder"``.

    When the export has no return period, ``fallback_period`` (from the CA's
    explicit run period selection) is used. If neither is available, raises
    ``AltGstr2bMissingPeriodError``.
    """
    if not isinstance(data, dict):
        raise ValueError("invalid_data_structure")

    invoice_rows_raw = data.get("invoice") if isinstance(data.get("invoice"), list) else []
    note_rows_raw = data.get("note") if isinstance(data.get("note"), list) else []

    mapped_inv: list[dict[str, Any]] = []
    rtnprd_votes: list[str] = []
    for row in invoice_rows_raw:
        if not isinstance(row, dict):
            continue
        mapped = _alt_map_invoice_row(row)
        if mapped is None:
            continue
        if mapped.get("_rtnprd"):
            rtnprd_votes.append(str(mapped["_rtnprd"]))
        mapped_inv.append(mapped)

    mapped_notes: list[dict[str, Any]] = []
    for row in note_rows_raw:
        if not isinstance(row, dict):
            continue
        mapped = _alt_map_note_row(row)
        if mapped is None:
            continue
        if mapped.get("_rtnprd"):
            rtnprd_votes.append(str(mapped["_rtnprd"]))
        mapped_notes.append(mapped)

    if not mapped_inv and not mapped_notes:
        raise ValueError(
            "alt_gstr2b_empty: no invoice/note rows with a non-blank Sr "
            "(totals-only or empty export)"
        )

    rtnprd = ""
    if rtnprd_votes:
        rtnprd = max(set(rtnprd_votes), key=rtnprd_votes.count)
    if not rtnprd:
        rtnprd = (
            _alt_parse_period_to_rtnprd(data.get("period") or data.get("rtnprd")) or ""
        )
    if not rtnprd and fallback_period:
        rtnprd = _alt_parse_period_to_rtnprd(fallback_period) or ""

    if not rtnprd:
        raise AltGstr2bMissingPeriodError(
            "Could not detect return period from this file — please select the period manually"
        )

    buyer = _alt_extract_buyer_gstin(data)
    if buyer:
        buyer_source = BUYER_GSTIN_SOURCE_FILE
    else:
        fb = str(fallback_buyer_gstin or "").strip()
        if fb:
            buyer = fb.upper()
            buyer_source = BUYER_GSTIN_SOURCE_CLIENT
        else:
            buyer = ALT_2B_PLACEHOLDER_BUYER_GSTIN
            buyer_source = BUYER_GSTIN_SOURCE_PLACEHOLDER

    root: dict[str, Any] = {
        "gstin": buyer,
        "rtnprd": rtnprd,
        "b2b": _alt_group_by_supplier(mapped_inv) if mapped_inv else [],
    }
    if mapped_notes:
        root["cdnr"] = _alt_group_by_supplier(mapped_notes)

    return {
        "data": root,
        "_alt_buyer_gstin_source": buyer_source,
    }


def _parse_rtnprd(rtnprd: str) -> datetime.date:
    """Parse GST filing period string to the first day of that month."""
    from app.services.normalizer import normalize_period_to_date
    try:
        return normalize_period_to_date(rtnprd)
    except Exception as exc:
        raise ValueError("invalid_rtnprd") from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_gstr2b(
    file_content,
    *,
    fallback_buyer_gstin: str | None = None,
    fallback_period: str | None = None,
) -> dict:
    """Parse GSTR-2B JSON file content into structured records.

    Accepts bytes, str, or a pre-parsed dict.

    ``fallback_buyer_gstin`` is used only for the alt flat-export schema when the
    JSON has no extractable buyer GSTIN (typically ``client_gstins.gstin``).

    ``fallback_period`` is used when the alt flat-export schema has no extractable
    return period (typically from the CA's selected run period).

    Raises:
        ValueError: For top-level structural errors (invalid JSON, missing
            required keys, unparseable period, unsupported input type).
    """
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
        raise ValueError("Unsupported input type for GSTR-2B parser")

    if not isinstance(data, dict):
        raise ValueError("invalid_data_structure")

    # Excel adapter attaches unparsed ISD/IMPG sheet counts on the payload.
    excel_isd_count = int(data.pop(_UNPARSED_ISD_COUNT_KEY, 0) or 0)
    excel_impg_count = int(data.pop(_UNPARSED_IMPG_COUNT_KEY, 0) or 0)

    buyer_gstin_source = BUYER_GSTIN_SOURCE_PORTAL
    if "data" not in data:
        if is_alt_gstr2b_schema(data):
            # Preserve excel counts if they rode on the alt dict.
            excel_isd_count = max(
                excel_isd_count, int(data.pop(_UNPARSED_ISD_COUNT_KEY, 0) or 0)
            )
            excel_impg_count = max(
                excel_impg_count, int(data.pop(_UNPARSED_IMPG_COUNT_KEY, 0) or 0)
            )
            data = normalize_alt_2b_schema(
                data,
                fallback_buyer_gstin=fallback_buyer_gstin,
                fallback_period=fallback_period,
            )
            buyer_gstin_source = str(
                data.pop("_alt_buyer_gstin_source", BUYER_GSTIN_SOURCE_FILE)
            )
            excel_isd_count = max(
                excel_isd_count, int(data.pop(_UNPARSED_ISD_COUNT_KEY, 0) or 0)
            )
            excel_impg_count = max(
                excel_impg_count, int(data.pop(_UNPARSED_IMPG_COUNT_KEY, 0) or 0)
            )
        else:
            raise ValueError(_UNSUPPORTED_GSTR2B_SCHEMA)
    elif "_alt_buyer_gstin_source" in data:
        # Pre-normalized by worker loader — preserve source for unique_key / UI.
        buyer_gstin_source = str(
            data.pop("_alt_buyer_gstin_source", BUYER_GSTIN_SOURCE_FILE)
        )
        excel_isd_count = max(
            excel_isd_count, int(data.pop(_UNPARSED_ISD_COUNT_KEY, 0) or 0)
        )
        excel_impg_count = max(
            excel_impg_count, int(data.pop(_UNPARSED_IMPG_COUNT_KEY, 0) or 0)
        )

    data = normalize_gstr2b_payload(data)
    # normalize_* may leave excel keys on the outer dict; pop again defensively.
    excel_isd_count = max(
        excel_isd_count, int(data.pop(_UNPARSED_ISD_COUNT_KEY, 0) or 0)
    )
    excel_impg_count = max(
        excel_impg_count, int(data.pop(_UNPARSED_IMPG_COUNT_KEY, 0) or 0)
    )
    root = data["data"]

    if not isinstance(root, dict):
        raise ValueError("invalid_data_structure")

    if not root.get("rtnprd") and fallback_period:
        parsed_fp = _alt_parse_period_to_rtnprd(fallback_period)
        if parsed_fp:
            root["rtnprd"] = parsed_fp

    if not root.get("gstin"):
        raise ValueError("missing_gstin")

    if not root.get("rtnprd"):
        raise ValueError("missing_rtnprd")

    rtnprd = root["rtnprd"]
    try:
        period = _parse_rtnprd(rtnprd)
    except ValueError:
        raise ValueError("invalid_rtnprd") from None

    logger.debug(
        "gstr2b parse: buyer_gstin=%s rtnprd=%s period=%s b2b_suppliers=%s",
        root.get("gstin"),
        rtnprd,
        period.isoformat(),
        len(root.get("b2b") or []) if isinstance(root.get("b2b"), list) else 0,
    )

    raw_buyer_gstin = root["gstin"]
    try:
        buyer_gstin = normalize_gstin(raw_buyer_gstin)
    except NormalizationError:
        buyer_gstin = raw_buyer_gstin

    generated_on = root.get("gendt", "")

    records: list = []
    skipped: list = []
    sections_present: list = []
    sections_empty: list = []

    b2b_raw = root.get("b2b")
    total_suppliers_b2b = len(b2b_raw) if isinstance(b2b_raw, list) else 0

    cdnr_raw = root.get("cdnr")
    total_suppliers_cdnr = len(cdnr_raw) if isinstance(cdnr_raw, list) else 0

    for section_name, is_cdnr, is_amendment in [
        ("b2b",   False, False),
        ("b2ba",  False, True),
        ("cdnr",  True,  False),
        ("cdnra", True,  True),
    ]:
        status = _process_section(root, section_name, records, skipped, is_cdnr, is_amendment)
        if status == "present":
            sections_present.append(section_name)
        elif status == "empty":
            sections_empty.append(section_name)

    isd_impg = detect_isd_impg_sections(
        root,
        excel_isd_count=excel_isd_count,
        excel_impg_count=excel_impg_count,
    )

    # Enrich every parsed record with standardized output fields.
    for record in records:
        _enrich_record(record, buyer_gstin)

    total_parsed = len(records)
    total_skipped = len(skipped)
    total_invoices_seen = total_parsed + total_skipped

    # Retained-but-flagged records: GSTIN failed strict format validation but
    # the invoice was kept (see the ``gstin_format_invalid`` except branch
    # above). These count towards total_parsed, not total_skipped — they are
    # real invoices needing manual GSTIN verification, not dropped data.
    gstin_format_invalid_count = sum(
        1 for r in records if r.get("gstin_format_invalid")
    )

    skip_reasons: dict = {}
    for entry in skipped:
        reason = entry["error_reason"]
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    # Canonical, low-cardinality aggregations for the "breakdown by reason" UI.
    # ``skip_breakdown`` groups by category; ``skip_reason_codes`` groups by the
    # stable reason_code (neither includes raw values, so they aggregate cleanly).
    category_counts: dict = {}
    reason_code_counts: dict = {}
    for entry in skipped:
        cat = entry.get("category", SKIP_OTHER)
        code = entry.get("reason_code", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        reason_code_counts[code] = reason_code_counts.get(code, 0) + 1

    skip_breakdown = {
        cat: category_counts[cat]
        for cat in SKIP_CATEGORY_ORDER
        if category_counts.get(cat)
    }
    # Surface any unexpected categories deterministically at the end.
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

    normalization_note_frequency: dict = {}
    for record in records:
        for field_notes in record.get("normalization_notes", {}).values():
            for note in field_notes:
                normalization_note_frequency[note] = (
                    normalization_note_frequency.get(note, 0) + 1
                )

    metrics = {
        "total_suppliers_b2b": total_suppliers_b2b,
        "total_suppliers_cdnr": total_suppliers_cdnr,
        "total_invoices_seen": total_invoices_seen,
        "total_parsed": total_parsed,
        "total_skipped": total_skipped,
        "skip_reasons": skip_reasons,
        "skip_breakdown": skip_breakdown,
        "skip_breakdown_labeled": skip_breakdown_labeled,
        "skip_reason_codes": reason_code_counts,
        "sections_present": sections_present,
        "sections_empty": sections_empty,
        "normalization_note_frequency": normalization_note_frequency,
        "gstin_format_invalid_count": gstin_format_invalid_count,
        "buyer_gstin_source": buyer_gstin_source,
        "isd_present": isd_impg["isd_present"],
        "isd_count": isd_impg["isd_count"],
        "impg_present": isd_impg["impg_present"],
        "impg_count": isd_impg["impg_count"],
    }

    result = {
        "schema_version": SCHEMA_VERSION,
        "buyer_gstin": buyer_gstin,
        "buyer_gstin_source": buyer_gstin_source,
        "period": period.isoformat() if isinstance(period, datetime.date) else str(period),
        "generated_on": str(generated_on),
        "records": records,
        "skipped": skipped,
        "total_parsed": total_parsed,
        "total_skipped": total_skipped,
        "skip_breakdown": skip_breakdown,
        "gstin_format_invalid_count": gstin_format_invalid_count,
        "isd_present": isd_impg["isd_present"],
        "isd_count": isd_impg["isd_count"],
        "impg_present": isd_impg["impg_present"],
        "impg_count": isd_impg["impg_count"],
        "metrics": metrics,
    }
    if buyer_gstin_source == BUYER_GSTIN_SOURCE_PLACEHOLDER:
        result["warnings"] = [BUYER_GSTIN_MISSING_WARNING]
    logger.debug(
        "gstr2b parse result: parsed=%s skipped=%s sections=%s buyer_source=%s",
        total_parsed,
        total_skipped,
        sections_present,
        buyer_gstin_source,
    )
    return result
