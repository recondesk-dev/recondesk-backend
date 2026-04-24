"""Section 17(5) blocked-credit hints by HSN — advisory warnings only."""

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


def check_blocked_credits(matched_records: list[dict]) -> list[dict]:
    """
    Return advisory warnings for HSN codes commonly restricted under 17(5).

    Never auto-block: CA makes the final call. Only warn.
    """
    warnings: list[dict] = []

    for record in matched_records:
        hsn_code = record.get("hsn_code")
        if hsn_code is None:
            continue

        hsn_str = str(hsn_code).strip()
        if hsn_str not in BLOCKED_HSN_CODES:
            continue

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
                "invoice_number": record.get("invoice_number"),
                "supplier_gstin": str(record.get("supplier_gstin") or ""),
                "reason": reason,
                "section": "17(5)",
            }
        )

    return warnings
