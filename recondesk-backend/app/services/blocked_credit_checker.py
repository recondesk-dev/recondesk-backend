"""Section 17(5) blocked-credit hints by HSN — advisory warnings only."""

from __future__ import annotations

from typing import Any, Mapping

BLOCKED_HSN_CODES = {
    "8703": {
        "category": "Motor vehicles (<13 seater) -- Section 17(5)(a)",
        "usage_dependent": True,
        "exempt_note": "Exempt if used for transport business, driving school, or further supply",
    },
    "9963": {
        "category": "Food/beverages/catering services -- Section 17(5)(b)",
        "usage_dependent": True,
        "exempt_note": "Exempt if canteen is mandatory under Factories Act",
    },
    "9972": {
        "category": "Construction/real estate services -- Section 17(5)(c)",
        "usage_dependent": False,
        "exempt_note": "",
    },
    "9995": {
        "category": "Club memberships -- Section 17(5)(b)",
        "usage_dependent": False,
        "exempt_note": "",
    },
    "9954": {
        "category": "Works contract for immovable property -- Section 17(5)(c)",
        "usage_dependent": False,
        "exempt_note": "",
    },
    "9993": {
        "category": "Health/beauty/grooming services -- Section 17(5)(b)",
        "usage_dependent": False,
        "exempt_note": "",
    },
}


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


def check_blocked_credits(invoices: list[dict]) -> list[dict]:
    """
    Return advisory warnings for HSN codes commonly restricted under 17(5).

    Works on any list of invoice-like dicts. HSN is read from top-level
    ``hsn`` / ``hsn_code`` (and common GST field names), or from nested
    ``items[]`` / ``items[].itm_det`` when top-level HSN is absent — matching
    GSTR-2B ``record_data`` shape. 8+ digit values use the first four digits
    for lookup, consistent with line-item HSN.

    Never auto-block: CA makes the final call. Only warn.
    """
    warnings: list[dict] = []

    for record in invoices:
        itc_eligibility = str(record.get("itc_eligibility") or "").strip().lower()
        if itc_eligibility in ("no", "false", "ineligible", "n", "f", "0", "not eligible"):
            warnings.append(
                {
                    "invoice_number": record.get("invoice_number")
                    or record.get("invoice_number_norm"),
                    "supplier_gstin": str(
                        record.get("supplier_gstin")
                        or record.get("supplier_gstin_norm")
                        or ""
                    ),
                    "reason": "Marked ITC-ineligible in purchase register",
                    "section": "17(5)",
                }
            )
            continue

        hsn_code = _raw_hsn_from_record(record)
        hsn_chapter = _hsn_chapter_key(hsn_code)
        if hsn_chapter is None or hsn_chapter not in BLOCKED_HSN_CODES:
            continue

        hsn_str = hsn_chapter

        entry = BLOCKED_HSN_CODES[hsn_str]
        category = entry["category"]
        usage_dependent = entry["usage_dependent"]
        exempt_note = entry["exempt_note"]

        if usage_dependent:
            reason = (
                f"HSN {hsn_str} falls under {category}. "
                "Verify before claiming ITC -- may be blocked under Section 17(5). "
                f"Note: {exempt_note}"
            )
        else:
            reason = (
                f"HSN {hsn_str} falls under {category}. "
                "Verify before claiming ITC -- likely blocked under Section 17(5)"
            )

        warnings.append(
            {
                "invoice_number": record.get("invoice_number")
                or record.get("invoice_number_norm"),
                "supplier_gstin": str(
                    record.get("supplier_gstin")
                    or record.get("supplier_gstin_norm")
                    or ""
                ),
                "reason": reason,
                "section": "17(5)",
            }
        )

    return warnings
