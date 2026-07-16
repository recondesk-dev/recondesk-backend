from enum import Enum


class Gstr1aEligibility(str, Enum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    REVIEW_REQUIRED = "review_required"


GSTR1A_ELIGIBILITY_MAP: dict[str, dict] = {
    "G1M_001": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Add the missing invoice via GSTR-1A before GSTR-3B is filed.",
    },
    "G1M_002": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Amend or remove the incorrect record via GSTR-1A.",
    },
    "G1M_003": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the taxable value / tax amount via GSTR-1A.",
    },
    "G1M_004": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the B2B/B2C classification via GSTR-1A.",
    },
    "G1M_005": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the GST rate applied via GSTR-1A.",
    },
    "G1M_006": {
        "eligibility": Gstr1aEligibility.NOT_ELIGIBLE,
        "note": (
            "This invoice belongs to a different filing period. GSTR-1A only "
            "corrects details within the current period — use the amendment "
            "tables (9/10/11) in the correct period's GSTR-1 instead."
        ),
    },
    "G1M_007": {
        "eligibility": Gstr1aEligibility.REVIEW_REQUIRED,
        "note": (
            "GSTIN correction may be amendable via GSTR-1A, but verify manually — "
            "downstream buyer ITC impact may need separate handling."
        ),
    },
    "G1M_008": {
        "eligibility": Gstr1aEligibility.NOT_ELIGIBLE,
        "note": (
            "Series continuity is a structural numbering issue (Rule 46), not "
            "a single invoice correction — GSTR-1A does not apply here."
        ),
    },
    "G1M_009": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the HSN/SAC code or tax rate via GSTR-1A.",
    },
    "G1M_010": {
        "eligibility": Gstr1aEligibility.REVIEW_REQUIRED,
        "note": (
            "Table 13 is a period-level aggregate, not an invoice-level record — "
            "confirm GSTR-1A's actual coverage before auto-routing this."
        ),
    },
}


def get_gstr1a_eligibility(rule_id: str) -> dict:
    return GSTR1A_ELIGIBILITY_MAP.get(
        rule_id,
        {
            "eligibility": Gstr1aEligibility.REVIEW_REQUIRED,
            "note": "Eligibility not yet reviewed for this rule.",
        },
    )
