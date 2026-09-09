"""Section 17(5) blocked-credit hints by HSN — advisory warnings only."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

INELIGIBLE_ITC_VALUES = frozenset({
    "no",
    "false",
    "ineligible",
    "blocked",
    "n",
    "f",
    "0",
    "not eligible",
    "not claimed",
    "non-eligible",
    "non eligible",
})

BLOCKED_HSN_CODES = {
    "0101": {
        "category": "Live horses, asses, mules -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for passenger transport or further supply",
    },
    "0102": {
        "category": "Live bovine animals -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for agricultural transport or further supply",
    },
    "0103": {
        "category": "Live swine -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for further supply",
    },
    "0104": {
        "category": "Live sheep and goats -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for further supply",
    },
    "8702": {
        "category": "Motor vehicles for transport of >=10 persons -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if seating capacity > 13 persons or used for transport business",
    },
    "8703": {
        "category": "Motor vehicles (<13 seater) -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for transport business, driving school, or further supply",
    },
    "8704": {
        "category": "Motor vehicles for transport of goods -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for transportation of goods",
    },
    "8711": {
        "category": "Two-wheelers / Motorcycles -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for delivery or further supply",
    },
    "2106": {
        "category": "Food preparations -- Section 17(5)(b)(i)",
        "usage_dependent": True,
        "exempt_note": "Verify business use before claiming ITC",
    },
    "9963": {
        "category": "Food/beverages/catering services -- Section 17(5)(b)(i)",
        "usage_dependent": True,
        "exempt_note": "Exempt if canteen is mandatory under Factories Act",
    },
    "9995": {
        "category": "Club memberships -- Section 17(5)(b)(ii)",
        "usage_dependent": False,
        "exempt_note": "",
    },
    "9954": {
        "category": "Works contract for immovable property -- Section 17(5)(c)",
        "usage_dependent": False,
        "exempt_note": "",
    },
    "9993": {
        "category": "Health/beauty/grooming services -- Section 17(5)(b)(i)",
        "usage_dependent": False,
        "exempt_note": "",
    },
    "9971": {
        "category": "Life/Health Insurance services -- Section 17(5)(b)(i)",
        "usage_dependent": True,
        "exempt_note": "Exempt if statutory obligation by employer",
    },
    "9964": {
        "category": "Passenger transport / Rent-a-cab -- Section 17(5)(b)(i)",
        "usage_dependent": True,
        "exempt_note": "Exempt if statutory obligation by employer",
    },
    "9966": {
        "category": "Rental of transport vehicles with operators -- Section 17(5)(b)(i)",
        "usage_dependent": True,
        "exempt_note": "Exempt if statutory employer obligation",
    },
    "9973": {
        "category": "Leasing/renting of motor vehicles without operator -- Section 17(5)(b)(i)",
        "usage_dependent": True,
        "exempt_note": "Exempt if outward supply obligation exists",
    },
    "9987": {
        "category": "Maintenance/servicing of motor vehicles -- Section 17(5)(ab)",
        "usage_dependent": True,
        "exempt_note": "Exempt if motor vehicle itself is ITC-eligible",
    },
    "8802": {
        "category": "Aircraft -- Section 17(5)(aa)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for taxable supply of air transport or training",
    },
    "8901": {
        "category": "Vessels -- Section 17(5)(aa)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for taxable supply of water transport or training",
    },
    "8902": {
        "category": "Vessels -- Section 17(5)(aa)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for taxable supply of water transport or training",
    },
}

BLOCKED_KEYWORDS: list[tuple[str, str]] = [
    ("OUTDOOR CATERING", "Outdoor Catering -- Section 17(5)(b)(i)"),
    ("CATERING", "Catering Services -- Section 17(5)(b)(i)"),
    ("FOOD & BEVERAGE", "Food & Beverages -- Section 17(5)(b)(i)"),
    ("FOOD AND BEVERAGE", "Food & Beverages -- Section 17(5)(b)(i)"),
    ("CLUB MEMBERSHIP", "Club Membership -- Section 17(5)(b)(ii)"),
    ("HEALTH CLUB", "Health Club Membership -- Section 17(5)(b)(ii)"),
    ("GYM MEMBERSHIP", "Health & Fitness Centre -- Section 17(5)(b)(ii)"),
    ("RENT A CAB", "Rent-a-cab Services -- Section 17(5)(b)(i)"),
    ("RENT-A-CAB", "Rent-a-cab Services -- Section 17(5)(b)(i)"),
    ("LIFE INSURANCE", "Life Insurance Services -- Section 17(5)(b)(i)"),
    ("HEALTH INSURANCE", "Health Insurance Services -- Section 17(5)(b)(i)"),
    ("BEAUTY TREATMENT", "Beauty Treatment Services -- Section 17(5)(b)(i)"),
    ("PLASTIC SURGERY", "Cosmetic/Plastic Surgery -- Section 17(5)(b)(i)"),
]


def _hsn_chapter_key(raw: object) -> str | None:
    """4-character chapter heading for lookup (matches GSTR-2B line item style, 4- or 8-digit)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s[:4] or None


_HSN_KEYS = ("hsn", "hsn_code", "hsn_sc", "sac", "sac_code")


def _hsn_value_from_mapping(m: Mapping[str, Any] | None) -> object | None:
    if not m or not isinstance(m, Mapping):
        return None
    for k in _HSN_KEYS:
        v = m.get(k)
        if v is not None and str(v).strip() != "":
            return v
    return None


def _raw_hsn_from_record(record: Mapping[str, Any]) -> object | None:
    """First non-empty HSN / SAC on the invoice, then on ``items`` (GSTR-2B line items)."""
    h = _hsn_value_from_mapping(record)
    if h is not None:
        return h
    items = record.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        h = _hsn_value_from_mapping(item)
        if h is not None:
            return h
        itm_det = item.get("itm_det")
        if isinstance(itm_det, dict):
            h = _hsn_value_from_mapping(itm_det)
            if h is not None:
                return h
    return None


def _invoice_identity(record: Mapping[str, Any]) -> tuple[Any, str]:
    inv = (
        record.get("invoice_number")
        or record.get("invoice_number_norm")
        or record.get("invoice_number_normalized")
    )
    gst = str(
        record.get("supplier_gstin")
        or record.get("supplier_gstin_norm")
        or ""
    ).strip()
    return inv, gst


def _invoice_date(record: Mapping[str, Any]) -> Any:
    return record.get("invoice_date") or record.get("invoice_date_norm") or record.get("idt")


def _amount_rupees(record: Mapping[str, Any]) -> float:
    for key in ("total_tax_paise", "estimated_itc_paise"):
        v = record.get(key)
        if v is not None:
            try:
                amt = abs(int(v))
                if amt > 0:
                    return round(amt / 100.0, 2)
            except (TypeError, ValueError):
                pass
    cgst = int(record.get("cgst_paise") or 0)
    sgst = int(record.get("sgst_paise") or 0)
    igst = int(record.get("igst_paise") or 0)
    cess = int(record.get("cess_paise") or 0)
    comp_total = abs(cgst) + abs(sgst) + abs(igst) + abs(cess)
    if comp_total > 0:
        return round(comp_total / 100.0, 2)
    for key in ("amount", "estimated_itc_amount", "total_tax", "val"):
        v = record.get(key)
        if v is not None:
            try:
                amt = abs(float(v))
                if amt > 0:
                    return round(amt, 2)
            except (TypeError, ValueError):
                pass
    return 0.0


def _base_warning(record: Mapping[str, Any], *, reason: str, **extra: Any) -> dict[str, Any]:
    inv, gst = _invoice_identity(record)
    amt = _amount_rupees(record)
    out: dict[str, Any] = {
        "invoice_number": inv,
        "supplier_gstin": gst,
        "invoice_date": _invoice_date(record),
        "amount": amt,
        "estimated_itc_amount": amt,
        "reason": reason,
        "section": "17(5)",
    }
    out.update(extra)
    return out


def check_blocked_credits(invoices: list[dict]) -> list[dict]:
    """
    Return advisory warnings for HSN codes commonly restricted under 17(5).

    Works on any list of invoice-like dicts. HSN is read from top-level
    ``hsn`` / ``hsn_code`` (and common GST field names), or from nested
    ``items[]`` / ``items[].itm_det`` when top-level HSN is absent — matching
    GSTR-2B ``record_data`` shape. 8+ digit values use the first four digits
    for lookup, consistent with line-item HSN.

    Each warning includes ``hsn_code`` / ``category`` (when known), plus
    ``invoice_date`` and ``amount`` so export / decision templates never fall
    back to literal ``?`` or blank identity columns.

    Never auto-block: CA makes the final call. Only warn.
    """
    warnings: list[dict] = []

    for record in invoices:
        raw_elig = record.get("itc_eligibility")
        itc_eligibility = (
            str(raw_elig).strip().lower()
            if raw_elig is not None and not (isinstance(raw_elig, float) and pd.isna(raw_elig))
            else ""
        )
        if itc_eligibility in INELIGIBLE_ITC_VALUES:
            warnings.append(
                _base_warning(
                    record,
                    reason="Marked ITC-ineligible in purchase register",
                    # No HSN on this path — decision layer uses a no-HSN template.
                    hsn_code=None,
                    category="Marked ITC-ineligible in purchase register",
                    flag_source="pr_eligibility",
                )
            )
            continue

        hsn_code = _raw_hsn_from_record(record)
        hsn_chapter = _hsn_chapter_key(hsn_code)
        if hsn_chapter is not None and hsn_chapter in BLOCKED_HSN_CODES:
            entry = BLOCKED_HSN_CODES[hsn_chapter]
            category = entry["category"]
            usage_dependent = entry["usage_dependent"]
            exempt_note = entry["exempt_note"]

            if usage_dependent:
                reason = (
                    f"HSN {hsn_chapter} falls under {category}. "
                    "Verify before claiming ITC -- may be blocked under Section 17(5). "
                    f"Note: {exempt_note}"
                )
            else:
                reason = (
                    f"HSN {hsn_chapter} falls under {category}. "
                    "Verify before claiming ITC -- likely blocked under Section 17(5)"
                )

            warnings.append(
                _base_warning(
                    record,
                    reason=reason,
                    hsn_code=hsn_chapter,
                    category=category,
                    flag_source="hsn",
                )
            )
            continue

        # Check line item / ledger text description for blocked credit keywords
        desc_text = " ".join([
            str(record.get("description") or ""),
            str(record.get("item_name") or ""),
            str(record.get("ledger_name") or ""),
            str(record.get("remarks") or ""),
        ]).upper()

        if desc_text.strip():
            matched_cat = None
            for kw, cat_desc in BLOCKED_KEYWORDS:
                if kw in desc_text:
                    matched_cat = cat_desc
                    break
            if matched_cat:
                reason = (
                    f"Text description contains blocked credit keyword. "
                    f"Falls under {matched_cat}. Verify before claiming ITC."
                )
                warnings.append(
                    _base_warning(
                        record,
                        reason=reason,
                        hsn_code=None,
                        category=matched_cat,
                        flag_source="keyword",
                    )
                )

    return warnings
