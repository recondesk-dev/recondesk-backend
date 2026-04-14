"""GSTR-2B JSON parser.

Parses the official GSTN GSTR-2B JSON format into structured records.

Supported sections: b2b, b2ba (amendments), cdnr (credit/debit notes),
cdnra (credit/debit note amendments).

Sections isd and impg are silently ignored.
"""

import datetime
import json
import re
from typing import Any

from app.services.normalizer import (
    ALLOWED_NOTES,
    NormalizationError,
    NormalizationResult,
    normalize_amount,
    normalize_date,
    normalize_gstin,
    normalize_invoice_number,
)

SCHEMA_VERSION = "gstr2b_v1"


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
) -> dict:
    return {
        "section": section,
        "supplier_gstin": supplier_gstin,
        "invoice_number": invoice_number,
        "error_reason": error_reason,
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
        raw_igst  = _parse_numeric_field(itm.get("igst"),  "igst")
        raw_cgst  = _parse_numeric_field(itm.get("cgst"),  "cgst")
        raw_sgst  = _parse_numeric_field(itm.get("sgst"),  "sgst")
        raw_cess  = _parse_numeric_field(itm.get("cess"),  "cess")

        raw_txvals.append(raw_txval)

        item_record = {
            "tax_rate": tax_rate,
            "taxable_value_raw": raw_txval,
            "taxable_value_paise": _validate_result(normalize_amount(raw_txval), "taxable_value").value,
            "igst_paise":  _validate_result(normalize_amount(raw_igst),  "igst").value,
            "cgst_paise":  _validate_result(normalize_amount(raw_cgst),  "cgst").value,
            "sgst_paise":  _validate_result(normalize_amount(raw_sgst),  "sgst").value,
            "cess_paise":  _validate_result(normalize_amount(raw_cess),  "cess").value,
        }
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
    normalization_notes: dict,
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

    return {
        "doc_type": doc_type,
        "is_amendment": is_amendment,
        "section": section,
        "schema_version": SCHEMA_VERSION,
        "supplier_gstin_raw": supplier_gstin_raw,
        "supplier_gstin": supplier_gstin,
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
        "unique_key": None,
        "items": items,
        "normalization_notes": normalization_notes,
    }


# ---------------------------------------------------------------------------
# Invoice-level parsing — b2b / b2ba
# ---------------------------------------------------------------------------

def _parse_b2b_invoice(
    invoice: dict,
    supplier_gstin: str,
    supplier_gstin_raw: str,
    section: str,
    is_amendment: bool,
) -> dict:
    normalization_notes: dict = {}

    raw_inum_val = invoice.get("inum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = result.value

    raw_dt = invoice.get("dt")
    if raw_dt is None:
        raise ValueError("missing_field for dt")
    result = _validate_result(normalize_date(raw_dt), "invoice_date")
    if result.notes:
        normalization_notes["invoice_date"] = result.notes
    invoice_date = result.value

    raw_val = _parse_numeric_field(invoice.get("val"), "val")
    result = _validate_result(normalize_amount(raw_val), "invoice_value")
    if result.notes:
        normalization_notes["invoice_value"] = result.notes
    invoice_value_paise = result.value

    pos = str(invoice.get("pos", ""))
    reverse_charge = invoice.get("rev", "N") == "Y"
    itc_available = invoice.get("itcavl", "N") == "Y"

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
            original_invoice_number = result.value

        oidt_raw = invoice.get("oidt")
        if oidt_raw is not None:
            original_invoice_date_raw = str(oidt_raw)
            result = _validate_result(normalize_date(oidt_raw), "original_invoice_date")
            if result.notes:
                normalization_notes["original_invoice_date"] = result.notes
            original_invoice_date = result.value

    items_list = invoice.get("itms", [])
    if items_list is not None and not isinstance(items_list, list):
        raise ValueError(f"invalid_type for itms: {type(items_list)}")
    if items_list is None:
        items_list = []
    item_records, raw_txvals = _parse_items(items_list)

    for i, raw_txval in enumerate(raw_txvals):
        result = _validate_result(normalize_amount(raw_txval), f"item_{i}_taxable_value")
        if result.notes:
            normalization_notes[f"item_{i}_taxable_value"] = result.notes

    return _build_invoice_record(
        doc_type="INVOICE",
        is_amendment=is_amendment,
        section=section,
        supplier_gstin_raw=supplier_gstin_raw,
        supplier_gstin=supplier_gstin,
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
        items=item_records,
        normalization_notes=normalization_notes,
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
) -> dict:
    normalization_notes: dict = {}

    ntty = invoice.get("ntty", "")
    if ntty == "C":
        document_type = "CREDIT_NOTE"
    elif ntty == "D":
        document_type = "DEBIT_NOTE"
    else:
        raise ValueError("unknown_note_type")

    # Support both GSTN API field names: "nt_num" (current) and "ntnum" (legacy)
    raw_inum_val = invoice.get("nt_num") or invoice.get("ntnum")
    raw_inum = str(raw_inum_val) if raw_inum_val is not None else ""
    result = _validate_result(normalize_invoice_number(raw_inum), "invoice_number")
    if result.notes:
        normalization_notes["invoice_number"] = result.notes
    invoice_number = result.value

    # Support both "nt_dt" (current GSTN API) and "dt" (legacy)
    raw_dt = invoice.get("nt_dt") or invoice.get("dt")
    if raw_dt is None:
        raise ValueError("missing_field for dt")
    result = _validate_result(normalize_date(raw_dt), "invoice_date")
    if result.notes:
        normalization_notes["invoice_date"] = result.notes
    invoice_date = result.value

    raw_val = _parse_numeric_field(invoice.get("val"), "val")
    result = _validate_result(normalize_amount(raw_val), "invoice_value")
    if result.notes:
        normalization_notes["invoice_value"] = result.notes
    invoice_value_paise = result.value

    pos = str(invoice.get("pos", ""))
    reverse_charge = invoice.get("rev", "N") == "Y"
    itc_available = invoice.get("itcavl", "N") == "Y"

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
            original_invoice_number = result.value

        ointdt_raw = invoice.get("ointdt")
        if ointdt_raw is not None:
            original_invoice_date_raw = str(ointdt_raw)
            result = _validate_result(normalize_date(ointdt_raw), "original_invoice_date")
            if result.notes:
                normalization_notes["original_invoice_date"] = result.notes
            original_invoice_date = result.value

    items_list = invoice.get("itms", [])
    if items_list is not None and not isinstance(items_list, list):
        raise ValueError(f"invalid_type for itms: {type(items_list)}")
    if items_list is None:
        items_list = []
    item_records, raw_txvals = _parse_items(items_list)

    for i, raw_txval in enumerate(raw_txvals):
        result = _validate_result(normalize_amount(raw_txval), f"item_{i}_taxable_value")
        if result.notes:
            normalization_notes[f"item_{i}_taxable_value"] = result.notes

    return _build_invoice_record(
        doc_type=document_type,
        is_amendment=is_amendment,
        section=section,
        supplier_gstin_raw=supplier_gstin_raw,
        supplier_gstin=supplier_gstin,
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
        items=item_records,
        normalization_notes=normalization_notes,
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
    try:
        record["invoice_number_norm"] = str(record["invoice_number"]).strip().upper()
    except Exception:
        record["invoice_number_norm"] = str(record.get("invoice_number_raw", ""))

    # taxable_value — sum of item taxable values in whole rupees (integer)
    try:
        items = record.get("items") or []
        if items:
            total_paise = sum(item.get("taxable_value_paise", 0) for item in items)
        else:
            total_paise = record.get("invoice_value_paise", 0)
        record["taxable_value"] = round(total_paise / 100)
    except Exception:
        record["taxable_value"] = 0

    # unique_key — stable string, safe for JSON / DB keys
    record["unique_key"] = (
        f"{record['buyer_gstin']}"
        f"|{record['invoice_number_norm']}"
        f"|{record['invoice_date_norm']}"
    )


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

        raw_ctin = supplier.get("ctin", "")
        if not isinstance(raw_ctin, str) or not raw_ctin.strip():
            for inv in inv_list:
                inv_num = _get_inv_num(inv, is_cdnr)
                skipped.append(
                    _make_skip_entry(section_name, "unknown", inv_num, "missing_supplier_gstin", inv)
                )
            continue

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
            else:
                for inv in inv_list:
                    inv_num = _get_inv_num(inv, is_cdnr)
                    skipped.append(
                        _make_skip_entry(section_name, raw_ctin, inv_num, str(e), inv)
                    )
                continue

        supplier_gstin = gstin_result.value

        for invoice in inv_list:
            raw_inum = _get_inv_num(invoice, is_cdnr)

            if not isinstance(invoice, dict):
                skipped.append(
                    _make_skip_entry(section_name, supplier_gstin, "unknown", "invalid_invoice_structure", invoice)
                )
                continue

            try:
                if is_cdnr:
                    record = _parse_cdnr_invoice(
                        invoice, supplier_gstin, raw_ctin, section_name, is_amendment
                    )
                else:
                    record = _parse_b2b_invoice(
                        invoice, supplier_gstin, raw_ctin, section_name, is_amendment
                    )
                records.append(record)
            except NormalizationError as e:
                skipped.append(_make_skip_entry(section_name, supplier_gstin, raw_inum, str(e), invoice))
            except (ValueError, KeyError, TypeError) as e:
                skipped.append(_make_skip_entry(section_name, supplier_gstin, raw_inum, str(e), invoice))
            except Exception:
                raise

    if len(records) > records_before:
        return "present"
    return "empty"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_gstr2b(file_content: bytes) -> dict:
    """Parse GSTR-2B JSON file content into structured records.

    Raises:
        ValueError: For top-level structural errors (invalid JSON, missing
            required keys, unparseable period).
    """
    try:
        data = json.loads(file_content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid_json: line {e.lineno} col {e.colno} (char {e.pos})")
    except Exception:
        raise ValueError("invalid_json")

    if not isinstance(data, dict):
        raise ValueError("invalid_data_structure")

    if "data" not in data:
        raise ValueError("missing_data_key")

    root = data["data"]

    if not isinstance(root, dict):
        raise ValueError("invalid_data_structure")

    if not root.get("gstin"):
        raise ValueError("missing_gstin")

    if not root.get("rtnprd"):
        raise ValueError("missing_rtnprd")

    rtnprd = root["rtnprd"]
    try:
        month = int(rtnprd[:2])
        year = int(rtnprd[2:])
        period = datetime.date(year, month, 1)
    except Exception:
        raise ValueError("invalid_rtnprd")

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

    # Enrich every parsed record with standardized output fields.
    for record in records:
        _enrich_record(record, buyer_gstin)

    total_parsed = len(records)
    total_skipped = len(skipped)
    total_invoices_seen = total_parsed + total_skipped

    skip_reasons: dict = {}
    for entry in skipped:
        reason = entry["error_reason"]
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

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
        "sections_present": sections_present,
        "sections_empty": sections_empty,
        "normalization_note_frequency": normalization_note_frequency,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "buyer_gstin": buyer_gstin,
        "period": period.isoformat() if isinstance(period, datetime.date) else str(period),
        "generated_on": str(generated_on),
        "records": records,
        "skipped": skipped,
        "total_parsed": total_parsed,
        "total_skipped": total_skipped,
        "metrics": metrics,
    }
