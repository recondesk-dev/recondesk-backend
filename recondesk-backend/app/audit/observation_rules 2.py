"""Static catalogue of audit observation rules.

Keys match engine ``mismatch_type`` values (GSTR-1) or synthetic purchase-side
source codes derived from compliance buckets. This module is configuration only —
it does not evaluate violations.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ObservationRuleConfig(TypedDict):
    title: str
    severity: str
    section_reference: str
    impact_type: str


# impact_type meanings:
# "tax_amount"        -> invoice tax value
# "tax_differential"  -> abs(value_a - value_b)
# "itc_amount"        -> ITC claimed on the flagged invoice
# "itc_plus_interest" -> ITC amount + interest per Rule 37(3) (18% p.a. from deadline breach)
# "none"              -> compliance-only flag, no ₹ figure

OBSERVATION_RULES: dict[str, ObservationRuleConfig] = {
    "G1M1_MISSING_INVOICE": {
        "title": "Missing invoice in GSTR-1",
        "severity": "Critical",
        "section_reference": "Section 37",
        "impact_type": "tax_amount",
    },
    "G1M2_EXTRA_INVOICE": {
        "title": "Extra invoice in GSTR-1 not in books",
        "severity": "High",
        "section_reference": "Section 37",
        "impact_type": "tax_amount",
    },
    "G1M3_AMOUNT_MISMATCH": {
        "title": "Invoice value mismatch",
        "severity": "High",
        "section_reference": "Section 37 / Rule 59",
        "impact_type": "tax_differential",
    },
    "G1M4_WRONG_CLASSIFICATION": {
        "title": "Invoice wrongly classified",
        "severity": "Medium",
        "section_reference": "Rule 46",
        "impact_type": "none",
    },
    "G1M5_RATE_MISMATCH": {
        "title": "Tax rate mismatch",
        "severity": "High",
        "section_reference": "Rule 46(o)",
        "impact_type": "tax_differential",
    },
    "G1M6_PERIOD_MISMATCH": {
        "title": "Invoice reported in wrong period",
        "severity": "Medium",
        "section_reference": "Section 39",
        "impact_type": "none",
    },
    "G1M7_INVALID_GSTIN": {
        "title": "Invalid/mismatched GSTIN",
        "severity": "Critical",
        "section_reference": "Rule 46(b)",
        "impact_type": "none",
    },
    "G1M8_INVOICE_SERIES_ISSUE": {
        "title": "Invoice series continuity gap",
        "severity": "Medium",
        "section_reference": "Rule 46(b)",
        "impact_type": "none",
    },
    "G1M9_HSN_RATE_ISSUE": {
        "title": "HSN/tax rate mismatch",
        "severity": "High",
        "section_reference": "Rule 46(o)",
        "impact_type": "tax_differential",
    },
    "G1M10_DOCUMENTS_ISSUED_SUMMARY": {
        "title": "Table 13 discrepancy",
        "severity": "Low",
        "section_reference": "Rule 59(4)",
        "impact_type": "none",
    },
    "RULE37_UNPAID_180": {
        "title": "ITC unpaid beyond 180 days — reversal due",
        "severity": "Critical",
        "section_reference": "Section 16(2)(c), Rule 37",
        "impact_type": "itc_plus_interest",
    },
    "BLOCKED_ITC_17_5": {
        "title": "Blocked ITC claimed (ineligible category)",
        "severity": "Critical",
        "section_reference": "Section 17(5)",
        "impact_type": "itc_amount",
    },
    "GSTR1_VS_3B_LIABILITY_MISMATCH": {
        "title": "Output tax liability mismatch (GSTR-1 vs 3B)",
        "severity": "High",
        "section_reference": "Section 39",
        "impact_type": "tax_differential",
    },
}

# Rule 37(3) interest rate (18% p.a.) for itc_plus_interest impact.
RULE37_INTEREST_RATE_PA = 0.18

SEVERITY_RANK: dict[str, int] = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}


def get_rule_config(source_rule: str) -> ObservationRuleConfig | None:
    """Return the catalogue entry for *source_rule*, or ``None`` if unknown."""
    cfg = OBSERVATION_RULES.get(source_rule)
    return cfg  # typed as ObservationRuleConfig | None via dict.get


def rule_title(source_rule: str) -> str:
    cfg: dict[str, Any] | None = OBSERVATION_RULES.get(source_rule)
    if cfg:
        return str(cfg["title"])
    return source_rule
