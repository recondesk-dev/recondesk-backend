"""Review Required Priority & Triage Engine.

Classifies Review Required records into actionable statutory and financial priority tiers:
- URGENT: Statutory audit risk, Credit Notes misfiled in B2B, Period boundary crossing,
          GSTIN mismatches, or high-value discrepancies (>= ₹50,000).
- HIGH:   Large financial gap (>= ₹5,000 or > 2%), Duplicate ambiguity / conflict.
- MEDIUM: Moderate amount gap (₹100 to ₹5,000), format/typo variations with discrepancies.
- LOW:    Trivial differences (< ₹100 or <= 0.1%), minor rounding drift.
"""

from typing import Any, Mapping

PRIORITY_URGENT = "URGENT"
PRIORITY_HIGH = "HIGH"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_LOW = "LOW"

PRIORITY_ORDER = {
    PRIORITY_URGENT: 0,
    PRIORITY_HIGH: 1,
    PRIORITY_MEDIUM: 2,
    PRIORITY_LOW: 3,
}

URGENT_REASONS = {
    "DOC_TYPE_NOTE_IN_B2B",
    "PERIOD_BOUNDARY_DATE_MISMATCH",
    "GSTIN_MISMATCH",
    "GSTIN_MISMATCH: same PAN, different GSTIN",
}

HIGH_REASONS = {
    "DUPLICATE_AMBIGUITY",
    "DUPLICATE_AMBIGUITY_PR",
    "DUPLICATE_CLAIM",
    "DUPLICATE_CLAIM_PR",
    "DUPLICATE_CONFLICT",
    "DUPLICATE_ENTRY",
}


def classify_review_priority(record: Mapping[str, Any]) -> str:
    """Return 'URGENT', 'HIGH', 'MEDIUM', or 'LOW' for a Review Required record."""
    if not record:
        return PRIORITY_LOW

    reason = str(record.get("review_reason") or record.get("reason") or "").strip()

    # 1. Statutory audit hazards & legal compliance violations -> URGENT
    if any(u in reason for u in URGENT_REASONS):
        return PRIORITY_URGENT

    # 2. Extract financial delta (paise)
    diff_paise = (
        record.get("taxable_diff_paise")
        or record.get("amount_difference_paise")
        or record.get("amount_diff")
        or 0
    )
    try:
        diff_paise = abs(int(diff_paise))
    except (ValueError, TypeError):
        diff_paise = 0

    # 3. High financial delta: >= ₹50,000 (5,000,000 paise) -> URGENT
    if diff_paise >= 5_000_000:
        return PRIORITY_URGENT

    # 4. Duplicate conflicts and ambiguities -> HIGH
    if any(h in reason for h in HIGH_REASONS):
        return PRIORITY_HIGH

    # 5. Significant financial discrepancy: >= ₹5,000 (500,000 paise) -> HIGH
    if diff_paise >= 500_000:
        return PRIORITY_HIGH

    # 6. Percentage difference check (> 2% -> HIGH)
    pct = record.get("amount_difference_pct")
    if pct is not None:
        try:
            pct_val = abs(float(pct))
            if pct_val > 2.0:
                return PRIORITY_HIGH
        except (ValueError, TypeError):
            pass

    # 7. Moderate financial discrepancy: >= ₹100 (10,000 paise) -> MEDIUM
    if diff_paise >= 10_000:
        return PRIORITY_MEDIUM

    # 8. Minor roundoff with non-zero difference (< ₹100) -> LOW
    if diff_paise > 0:
        return PRIORITY_LOW

    # 9. Zero financial diff: evaluate secondary signals
    reason_lower = reason.lower()
    if "date" in reason_lower or "period" in reason_lower:
        return PRIORITY_HIGH
    if "typo" in reason_lower or "fuzzy" in reason_lower or "gstin_mismatch" in reason_lower:
        return PRIORITY_MEDIUM

    return PRIORITY_LOW


def review_priority_sort_key(record: Mapping[str, Any]) -> tuple:
    """Sort key for Review Required records:
    1. Priority level (URGENT [0] -> HIGH [1] -> MEDIUM [2] -> LOW [3])
    2. Absolute financial delta descending
    3. Invoice amount descending
    """
    prio = record.get("priority") or classify_review_priority(record)
    prio_rank = PRIORITY_ORDER.get(prio, 99)

    diff_paise = (
        record.get("taxable_diff_paise")
        or record.get("amount_difference_paise")
        or record.get("amount_diff")
        or 0
    )
    try:
        diff_paise = abs(int(diff_paise))
    except (ValueError, TypeError):
        diff_paise = 0

    amt = record.get("amount") or record.get("total_amount_paise") or 0
    try:
        amt = abs(float(amt))
    except (ValueError, TypeError):
        amt = 0.0

    return (prio_rank, -diff_paise, -amt)
