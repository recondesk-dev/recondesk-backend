"""
GSTR-1 mismatch classification rules for sales-side reconciliation.

Classifies discrepancies between the **Sales Register** (books) and
**GSTR-1** (filed return) into structured mismatch types, each producing a
``MismatchResult`` with WHAT/WHY/NEXT decision text compatible with the
existing Decision Layer (``DecisionOutput`` contract).

Mismatch types
--------------
==== ============================== ===============
Code Type                           Risk
==== ============================== ===============
G1M1 Missing invoice                Under-reporting
G1M2 Extra invoice                  Duplicate/error
G1M3 Amount mismatch                Tax liability
G1M4 Wrong classification (B2B/B2C) Compliance
G1M5 Rate mismatch                  Tax shortfall
G1M6 Filing period mismatch         Period risk
G1M7 Invalid / inactive GSTIN       Compliance
G1M8 Invoice series issue           Continuity
G1M9 HSN / tax rate issue           Rate schedule
==== ============================== ===============

This module is **standalone** — it does NOT modify any existing file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping

from app.data.hsn_rate_reference import (
    DEFAULT_TURNOVER_TIER,
    hsn_raw_is_missing,
    lookup_valid_rates,
    normalise_hsn,
    required_hsn_digits,
)
from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity
from app.rules.gstr1a_eligibility import get_gstr1a_eligibility
from app.services.decision_templates import DecisionOutput
from app.services.matcher import _is_credit_note, _is_debit_note
from app.services.normalizer import GSTIN_REGEX, WHITELIST_PATTERN

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Rule Definitions — registered in the global REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

REGISTRY.register(RuleDefinition(
    id="G1M_001",
    name="GSTR-1 Missing Invoice",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.CRITICAL,
    description=(
        "Invoice exists in Sales Register but is absent from GSTR-1. "
        "Under-reporting of output tax liability."
    ),
    gst_ref="Section 37 CGST Act",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "missing", "under-reporting"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_002",
    name="GSTR-1 Extra Invoice",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description=(
        "Invoice exists in GSTR-1 but is absent from Sales Register. "
        "Possible duplicate filing or data-entry error."
    ),
    gst_ref="Section 37 CGST Act",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "extra", "duplicate"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_003",
    name="GSTR-1 Amount Mismatch",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description=(
        "Taxable value or tax amount differs between Sales Register and "
        "GSTR-1 beyond the configured tolerance."
    ),
    gst_ref="Section 37 CGST Act",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "amount", "mismatch"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_004",
    name="GSTR-1 Wrong Classification",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.CRITICAL,
    description=(
        "Invoice is classified as B2B in one source and B2C in the other. "
        "Recipient's ITC eligibility is affected."
    ),
    gst_ref="Section 37 CGST Act",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "classification", "b2b", "b2c"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_005",
    name="GSTR-1 Rate Mismatch",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description=(
        "GST rate applied in the Sales Register differs from the rate "
        "filed in GSTR-1."
    ),
    gst_ref="Section 37 CGST Act",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "rate", "mismatch"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_006",
    name="GSTR-1 Filing Period Mismatch",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.MEDIUM,
    description=(
        "Invoice was reported in a different month's GSTR-1 than the "
        "invoice date suggests."
    ),
    gst_ref="Section 37 CGST Act",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "period", "mismatch"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_007",
    name="GSTR-1 Invalid / Inactive GSTIN",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description=(
        "Buyer GSTIN fails format validation or is not found / inactive / "
        "cancelled per Sandbox.co.in GSTIN search."
    ),
    gst_ref="Section 37 CGST Act",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "gstin", "verification", "sandbox"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_008",
    name="GSTR-1 Invoice Series Continuity",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.MEDIUM,
    description=(
        "Invoice numbering in the Sales Register shows gaps, duplicates, "
        "or out-of-order dates within a detected series. Rule 46 of CGST "
        "Rules mandates consecutive serial numbering of tax invoices."
    ),
    gst_ref="Rule 46 CGST Rules",
    applies_to=["sales_register"],
    tags=["gstr1", "series", "continuity", "duplicate", "sequence"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_009",
    name="GSTR-1 HSN / Tax Rate Validation",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description=(
        "HSN/SAC code is unknown in the rate reference, the applied GST "
        "rate is not valid for that HSN, or the HSN digit length is below "
        "the turnover-slab reporting requirement."
    ),
    gst_ref="Section 9 CGST Act / Notification 78/2020-CT",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "hsn", "sac", "rate", "schedule"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_010",
    name="GSTR-1 Documents Issued Summary (Table 13)",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.LOW,
    description=(
        "Period-level summary of documents issued by type and series "
        "(opening/closing serial, total issued, cancelled, net issued) "
        "for GSTR-1 Table 13 reconciliation."
    ),
    gst_ref="GSTR-1 Table 13 / Rule 46 CGST Rules",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "table13", "documents_issued", "series"],
))

REGISTRY.register(RuleDefinition(
    id="G1M_011",
    name="GSTR-1 Amendment Required (Tables 9A/9B/9C)",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description=(
        "An invoice (or credit/debit note / export) filed in a prior period's "
        "GSTR-1 now shows different values in the current Sales Register and "
        "should be reported as a Table 9A/9B/9C amendment."
    ),
    gst_ref="Section 37 CGST Act / GSTR-1 Tables 9A, 9B, 9C",
    applies_to=["sales_register", "gstr1"],
    tags=["gstr1", "amendment", "9a", "9b", "9c", "b2ba", "cdnra", "expa"],
))


# ══════════════════════════════════════════════════════════════════════════════
# Result types
# ══════════════════════════════════════════════════════════════════════════════

class MismatchType(str, Enum):
    """Machine-readable mismatch classification codes."""
    MISSING_INVOICE = "G1M1_MISSING_INVOICE"
    EXTRA_INVOICE = "G1M2_EXTRA_INVOICE"
    AMOUNT_MISMATCH = "G1M3_AMOUNT_MISMATCH"
    WRONG_CLASSIFICATION = "G1M4_WRONG_CLASSIFICATION"
    RATE_MISMATCH = "G1M5_RATE_MISMATCH"
    PERIOD_MISMATCH = "G1M6_PERIOD_MISMATCH"
    INVALID_GSTIN = "G1M7_INVALID_GSTIN"
    INVOICE_SERIES_ISSUE = "G1M8_INVOICE_SERIES_ISSUE"
    HSN_RATE_ISSUE = "G1M9_HSN_RATE_ISSUE"
    DOCUMENTS_ISSUED_SUMMARY = "G1M10_DOCUMENTS_ISSUED_SUMMARY"
    AMENDMENT_REQUIRED = "G1M11_AMENDMENT_REQUIRED"


class MismatchSeverity(str, Enum):
    """Severity for UI display and triage ordering."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True)
class MismatchResult:
    """Structured result for a single GSTR-1 mismatch, compatible with the
    Decision Layer's WHAT/WHY/NEXT contract.

    Attributes
    ----------
    mismatch_type : MismatchType
        Machine-readable mismatch code (e.g. ``G1M1_MISSING_INVOICE``).
    severity : MismatchSeverity
        Risk severity (drives triage ordering in the UI).
    decision_what : str
        One-line description of what happened.
    decision_why : str
        Explanation of why this matters / compliance context.
    decision_next : str
        Actionable next step for the accountant.
    rule_id : str
        Back-reference to the ``RuleDefinition.id`` in the global registry.
    gst_ref : str
        Statutory reference (e.g. ``"Section 37 CGST Act"``).
    details : dict[str, Any]
        Freeform bag of context — discrepancy amounts, field values, etc.
    """
    mismatch_type: MismatchType
    severity: MismatchSeverity
    decision_what: str
    decision_why: str
    decision_next: str
    rule_id: str
    gst_ref: str = "Section 37 CGST Act"
    details: dict[str, Any] = field(default_factory=dict)

    # ── Interop with DecisionOutput ──────────────────────────────────────
    def to_decision_output(self) -> DecisionOutput:
        """Convert to a ``DecisionOutput`` for the existing decision layer."""
        return DecisionOutput(
            what=self.decision_what,
            why=self.decision_why,
            next=self.decision_next,
            rule=self.rule_id,
            confidence=_severity_to_confidence(self.severity),
            matched_fields=tuple(self.details.get("matched_fields", ())),
            differed_fields=tuple(self.details.get("differed_fields", ())),
            normalized_pairs=tuple(
                tuple(p) for p in self.details.get("normalized_pairs", ())
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Flat dict for enriching reconciliation rows."""
        gstr1a = get_gstr1a_eligibility(self.rule_id)
        eligibility = gstr1a["eligibility"]
        return {
            "mismatch_type": self.mismatch_type.value,
            "mismatch_severity": self.severity.value,
            "decision_what": self.decision_what,
            "decision_why": self.decision_why,
            "decision_next": self.decision_next,
            "decision_rule": self.rule_id,
            "rule_id": self.rule_id,
            "gst_ref": self.gst_ref,
            **self.details,
            "eligibility": (
                eligibility.value if hasattr(eligibility, "value") else eligibility
            ),
            "note": gstr1a["note"],
        }


def _severity_to_confidence(severity: MismatchSeverity) -> str:
    return {
        MismatchSeverity.CRITICAL: "HIGH",
        MismatchSeverity.HIGH: "MEDIUM",
        MismatchSeverity.WARNING: "MEDIUM",
        MismatchSeverity.MEDIUM: "LOW",
        MismatchSeverity.LOW: "LOW",
        MismatchSeverity.INFO: "LOW",
    }.get(severity, "LOW")


# ══════════════════════════════════════════════════════════════════════════════
# Helper utilities
# ══════════════════════════════════════════════════════════════════════════════

def _rs(paise: int | None) -> str:
    """Format paise as ₹ string. Returns ``"₹0.00"`` for ``None``."""
    if paise is None:
        return "₹0.00"
    return f"₹{abs(paise) / 100:,.2f}"


def _pct(diff_paise: int, base_paise: int) -> str:
    """Percentage string. Returns ``"0.0%"`` when base is zero."""
    if base_paise == 0:
        return "0.0%"
    return f"{(abs(diff_paise) / abs(base_paise)) * 100:.1f}%"


def _safe_int(val: Any, default: int = 0) -> int:
    """Coerce *val* to ``int``; return *default* on failure."""
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_date(val: Any) -> date | None:
    """Best-effort parse of a date value (``date``, ISO string, or None)."""
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None


def _invoice_period_label(d: date | None) -> str:
    """``"Apr-2026"`` style period label from a date."""
    if d is None:
        return "Unknown"
    return d.strftime("%b-%Y")


def _get_field(rec: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    """Return the first non-empty value found for any of *keys*."""
    for k in keys:
        v = rec.get(k)
        if v is not None and str(v).strip():
            return v
    return default


def _normalize_gstin_value(val: Any) -> str | None:
    """Return a cleaned GSTIN, or ``None`` when missing / unregistered."""
    if val is None:
        return None
    s = str(val).strip()
    # "NAN"/"NONE"/"NAT" are pandas/numpy missing-value stringifications —
    # never treat them as a real GSTIN in decision text.
    if not s or s == "?" or s.upper() in ("URP", "NAN", "NONE", "NAT", "<NA>"):
        return None
    return s


def _recipient_display_label(
    *,
    gstin: Any = None,
    name: Any = None,
) -> str:
    """User-facing recipient phrase for decision text.

    Never returns ``"?"`` or an empty string — B2C / missing GSTIN falls back
    to a natural "unregistered B2C customer" description. Structured details
    should still store the raw GSTIN as ``None`` when absent.
    """
    gstin_s = _normalize_gstin_value(gstin)
    if gstin_s:
        return gstin_s
    name_s = str(name).strip() if name is not None else ""
    if name_s and name_s != "?":
        return f"{name_s} (an unregistered B2C customer)"
    return "an unregistered B2C customer"


def _recipient_from_record(
    rec: Mapping[str, Any],
    *gstin_keys: str,
) -> tuple[str | None, str]:
    """Extract ``(gstin_or_none, display_label)`` from a record."""
    keys = gstin_keys or ("recipient_gstin", "gstin")
    gstin = _normalize_gstin_value(_get_field(rec, *keys, default=""))
    name = _get_field(rec, "recipient_name", "customer_name", "trade_name", default="")
    name_s = str(name).strip() if name else ""
    return gstin, _recipient_display_label(gstin=gstin, name=name_s or None)


# ══════════════════════════════════════════════════════════════════════════════
# Tolerance configuration
# ══════════════════════════════════════════════════════════════════════════════

# Absolute tolerance in paise below which an amount diff is treated as rounding
AMOUNT_TOLERANCE_PAISE: int = 100   # ₹1.00

# Percentage tolerance above which an amount diff is flagged
AMOUNT_TOLERANCE_PCT: float = 0.01  # 1%


# ══════════════════════════════════════════════════════════════════════════════
# Classification rules — one function per mismatch type
# ══════════════════════════════════════════════════════════════════════════════

def classify_missing_invoice(
    sr_rec: Mapping[str, Any],
) -> MismatchResult:
    """G1M1 — Invoice in Sales Register, NOT in GSTR-1 (under-reporting risk).

    Parameters
    ----------
    sr_rec : Mapping
        The unmatched Sales Register record.
    """
    inv = str(
        _get_field(
            sr_rec,
            "inum",
            "nt_num",
            "ntnum",
            "credit_note_number",
            "note_number",
            "invoice_number_raw",
            "invoice_number",
            "invoice_number_normalized",
        )
        or "?"
    )
    gstin, recipient_label = _recipient_from_record(
        sr_rec, "gstin", "recipient_gstin",
    )
    taxable = _safe_int(sr_rec.get("taxable_amount_paise"))
    total_tax = _safe_int(sr_rec.get("total_tax_paise"))
    inv_date = _parse_date(sr_rec.get("invoice_date"))

    if _is_credit_note(sr_rec):
        return MismatchResult(
            mismatch_type=MismatchType.MISSING_INVOICE,
            severity=MismatchSeverity.CRITICAL,
            decision_what=(
                f"Credit Note {inv} is present in the Sales Register but is missing from GSTR-1."
            ),
            decision_why=(
                "The Credit Note has been recorded in the Sales Register but "
                "no corresponding Credit Note was found in the GSTR-1 data for "
                "this return period."
            ),
            decision_next=(
                f"Verify whether Credit Note {inv} was reported in GSTR-1. "
                f"If it was not reported, review the filing and amendment requirements."
            ),
            rule_id="G1M_001",
            details={
                "invoice_number": inv,
                "document_type": "CREDIT_NOTE",
                "credit_note_number": inv,
                "recipient_gstin": gstin,
                "taxable_amount_paise": taxable,
                "total_tax_paise": total_tax,
                "invoice_date": inv_date.isoformat() if inv_date else None,
                "matched_fields": [],
                "differed_fields": ["presence"],
            },
        )

    if _is_debit_note(sr_rec):
        return MismatchResult(
            mismatch_type=MismatchType.MISSING_INVOICE,
            severity=MismatchSeverity.CRITICAL,
            decision_what=(
                f"Debit Note {inv} is present in the Sales Register but is missing from GSTR-1."
            ),
            decision_why=(
                f"Output tax of {_rs(total_tax)} on taxable value {_rs(taxable)} "
                f"has not been reported in GSTR-1. This constitutes under-reporting "
                f"of tax liability under Section 37 of the CGST Act and may attract "
                f"interest under Section 50 and penalties under Section 122."
            ),
            decision_next=(
                f"File or amend GSTR-1 Table 9B to include debit note {inv} for "
                f"{('recipient ' + gstin) if gstin else recipient_label}."
            ),
            rule_id="G1M_001",
            details={
                "invoice_number": inv,
                "document_type": "DEBIT_NOTE",
                "debit_note_number": inv,
                "recipient_gstin": gstin,
                "taxable_amount_paise": taxable,
                "total_tax_paise": total_tax,
                "invoice_date": inv_date.isoformat() if inv_date else None,
                "matched_fields": [],
                "differed_fields": ["presence"],
            },
        )

    return MismatchResult(
        mismatch_type=MismatchType.MISSING_INVOICE,
        severity=MismatchSeverity.CRITICAL,
        decision_what=(
            f"Invoice {inv} is in the Sales Register but missing from GSTR-1"
        ),
        decision_why=(
            f"Output tax of {_rs(total_tax)} on taxable value {_rs(taxable)} "
            f"has not been reported in GSTR-1. This constitutes under-reporting "
            f"of tax liability under Section 37 of the CGST Act and may attract "
            f"interest under Section 50 and penalties under Section 122."
        ),
        decision_next=(
            f"File or amend GSTR-1 to include invoice {inv} for "
            f"{('recipient ' + gstin) if gstin else recipient_label}. "
            f"If the invoice was cancelled or returned, record a "
            f"credit note instead."
        ),
        rule_id="G1M_001",
        details={
            "invoice_number": inv,
            "document_type": "INVOICE",
            "recipient_gstin": gstin,
            "taxable_amount_paise": taxable,
            "total_tax_paise": total_tax,
            "invoice_date": inv_date.isoformat() if inv_date else None,
            "matched_fields": [],
            "differed_fields": ["presence"],
        },
    )


def classify_extra_invoice(
    gstr1_rec: Mapping[str, Any],
) -> MismatchResult:
    """G1M2 — Invoice in GSTR-1, NOT in Sales Register (duplicate/error risk).

    Parameters
    ----------
    gstr1_rec : Mapping
        The unmatched GSTR-1 record.
    """
    inv = str(
        _get_field(
            gstr1_rec,
            "inum",
            "nt_num",
            "ntnum",
            "credit_note_number",
            "note_number",
            "invoice_number_raw",
            "invoice_number",
            "invoice_number_normalized",
        )
        or "?"
    )
    gstin, recipient_label = _recipient_from_record(
        gstr1_rec, "recipient_gstin", "gstin",
    )
    taxable = _safe_int(gstr1_rec.get("taxable_amount_paise"))
    total_tax = _safe_int(gstr1_rec.get("total_tax_paise"))
    inv_date = _parse_date(gstr1_rec.get("invoice_date"))

    if _is_credit_note(gstr1_rec):
        return MismatchResult(
            mismatch_type=MismatchType.EXTRA_INVOICE,
            severity=MismatchSeverity.HIGH,
            decision_what=(
                f"Credit Note {inv} is in GSTR-1 but missing from the Sales Register"
            ),
            decision_why=(
                f"A credit note of taxable value {_rs(taxable)} with tax {_rs(total_tax)} was "
                f"reported in GSTR-1 but has no corresponding entry in the books. "
                f"This may be a duplicate filing, a data-entry error, or a "
                f"transaction not yet recorded in the Sales Register."
            ),
            decision_next=(
                f"Verify if Credit Note {inv} for {recipient_label} is genuine. "
                f"If duplicate, amend GSTR-1 to remove it. If genuine, add it to "
                f"the Sales Register."
            ),
            rule_id="G1M_002",
            details={
                "invoice_number": inv,
                "document_type": "CREDIT_NOTE",
                "credit_note_number": inv,
                "recipient_gstin": gstin,
                "taxable_amount_paise": taxable,
                "total_tax_paise": total_tax,
                "invoice_date": inv_date.isoformat() if inv_date else None,
                "matched_fields": [],
                "differed_fields": ["presence"],
            },
        )

    if _is_debit_note(gstr1_rec):
        return MismatchResult(
            mismatch_type=MismatchType.EXTRA_INVOICE,
            severity=MismatchSeverity.HIGH,
            decision_what=(
                f"Debit Note {inv} is in GSTR-1 but missing from the Sales Register"
            ),
            decision_why=(
                f"A debit note of taxable value {_rs(taxable)} with tax {_rs(total_tax)} was "
                f"reported in GSTR-1 but has no corresponding entry in the books. "
                f"This may be a duplicate filing, a data-entry error, or a "
                f"transaction not yet recorded in the Sales Register."
            ),
            decision_next=(
                f"Verify if Debit Note {inv} for {recipient_label} is genuine. "
                f"If duplicate, amend GSTR-1 to remove it. If genuine, add it to "
                f"the Sales Register."
            ),
            rule_id="G1M_002",
            details={
                "invoice_number": inv,
                "document_type": "DEBIT_NOTE",
                "debit_note_number": inv,
                "recipient_gstin": gstin,
                "taxable_amount_paise": taxable,
                "total_tax_paise": total_tax,
                "invoice_date": inv_date.isoformat() if inv_date else None,
                "matched_fields": [],
                "differed_fields": ["presence"],
            },
        )

    return MismatchResult(
        mismatch_type=MismatchType.EXTRA_INVOICE,
        severity=MismatchSeverity.HIGH,
        decision_what=(
            f"Invoice {inv} is in GSTR-1 but missing from the Sales Register"
        ),
        decision_why=(
            f"A taxable value of {_rs(taxable)} with tax {_rs(total_tax)} was "
            f"reported in GSTR-1 but has no corresponding entry in the books. "
            f"This may be a duplicate filing, a data-entry error, or a "
            f"transaction not yet recorded in the Sales Register."
        ),
        decision_next=(
            f"Verify if invoice {inv} for {recipient_label} is a genuine sale. "
            f"If duplicate, amend GSTR-1 to remove it. If genuine, add it to "
            f"the Sales Register."
        ),
        rule_id="G1M_002",
        details={
            "invoice_number": inv,
            "document_type": "INVOICE",
            "recipient_gstin": gstin,
            "taxable_amount_paise": taxable,
            "total_tax_paise": total_tax,
            "invoice_date": inv_date.isoformat() if inv_date else None,
            "matched_fields": [],
            "differed_fields": ["presence"],
        },
    )


def _record_has_tax_amount(rec: Mapping[str, Any]) -> bool:
    """True when the record carries an explicit tax total or component."""
    if rec.get("total_tax_paise") is not None:
        return True
    return any(
        rec.get(k) is not None
        for k in ("igst_paise", "cgst_paise", "sgst_paise", "cess_paise")
    )


def classify_amount_mismatch(
    sr_rec: Mapping[str, Any],
    gstr1_rec: Mapping[str, Any],
    *,
    tolerance_paise: int = AMOUNT_TOLERANCE_PAISE,
    tolerance_pct: float = AMOUNT_TOLERANCE_PCT,
) -> MismatchResult | None:
    """G1M3 — Taxable value or tax amount differs beyond tolerance.

    Returns ``None`` if both taxable and tax amounts are within tolerance
    (i.e. this is NOT an amount mismatch).

    Parameters
    ----------
    sr_rec, gstr1_rec : Mapping
        Matched pair of records from Sales Register and GSTR-1.
    tolerance_paise : int
        Absolute tolerance in paise (default ₹1.00).
    tolerance_pct : float
        Percentage tolerance (default 1%).
    """
    inv = str(_get_field(sr_rec, "invoice_number") or "?")

    is_cn = _is_credit_note(sr_rec) or _is_credit_note(gstr1_rec)
    is_dn = _is_debit_note(sr_rec) or _is_debit_note(gstr1_rec)
    doc_title = "Credit Note" if is_cn else ("Debit Note" if is_dn else "Invoice")
    doc_lower = "credit note" if is_cn else ("debit note" if is_dn else "invoice")

    if is_cn:
        sr_taxable = abs(_safe_int(sr_rec.get("taxable_amount_paise")))
        g1_taxable = abs(_safe_int(gstr1_rec.get("taxable_amount_paise")))
        sr_tax = abs(_safe_int(sr_rec.get("total_tax_paise")))
        g1_tax = abs(_safe_int(gstr1_rec.get("total_tax_paise")))
    else:
        sr_taxable = _safe_int(sr_rec.get("taxable_amount_paise"))
        g1_taxable = _safe_int(gstr1_rec.get("taxable_amount_paise"))
        sr_tax = _safe_int(sr_rec.get("total_tax_paise"))
        g1_tax = _safe_int(gstr1_rec.get("total_tax_paise"))

    taxable_diff = abs(sr_taxable - g1_taxable)

    # Only compare tax when both sides actually carry tax amounts. A missing
    # tax column (None→0) must not look like a 100% shortfall.
    compare_tax = _record_has_tax_amount(sr_rec) and _record_has_tax_amount(
        gstr1_rec
    )
    tax_diff = abs(sr_tax - g1_tax) if compare_tax else 0

    # Within absolute tolerance → not a mismatch (round-off only).
    # Do not suppress material ₹ diffs via a % gate — on large invoices a
    # planted ~0.5–1% taxable error is still a real G1M3.
    if taxable_diff <= tolerance_paise and tax_diff <= tolerance_paise:
        return None

    base_taxable = max(abs(sr_taxable), abs(g1_taxable), 1)
    base_tax = max(abs(sr_tax), abs(g1_tax), 1)

    # Determine which field(s) differ
    differed: list[str] = []
    diff_parts: list[str] = []
    if taxable_diff > tolerance_paise:
        differed.append("taxable_amount")
        diff_parts.append(
            f"taxable value differs by {_rs(taxable_diff)} "
            f"({_pct(taxable_diff, base_taxable)})"
        )
    if compare_tax and tax_diff > tolerance_paise:
        differed.append("total_tax")
        diff_parts.append(
            f"tax amount differs by {_rs(tax_diff)} "
            f"({_pct(tax_diff, base_tax)})"
        )

    # If neither triggered individually (rounding edge), flag taxable
    if not differed:
        differed.append("taxable_amount")
        diff_parts.append(
            f"taxable value differs by {_rs(taxable_diff)}"
        )

    severity = (
        MismatchSeverity.CRITICAL
        if taxable_diff > 50000  # > ₹500
        else MismatchSeverity.HIGH
    )

    return MismatchResult(
        mismatch_type=MismatchType.AMOUNT_MISMATCH,
        severity=severity,
        decision_what=(
            f"{doc_title} {inv}: {'; '.join(diff_parts)}"
        ),
        decision_why=(
            f"Sales Register shows taxable value {_rs(sr_taxable)} / tax "
            f"{_rs(sr_tax)}, but GSTR-1 shows {_rs(g1_taxable)} / "
            f"{_rs(g1_tax)}. The mismatch may result in short or excess "
            f"payment of output tax, attracting interest under Section 50."
        ),
        decision_next=(
            f"Compare {doc_lower} {inv} against the original document. Amend "
            f"GSTR-1 or correct the Sales Register to align the values. If a "
            f"credit/debit note was issued, ensure it is reported separately."
        ),
        rule_id="G1M_003",
        details={
            "invoice_number": inv,
            "document_type": "CREDIT_NOTE" if is_cn else ("DEBIT_NOTE" if is_dn else "INVOICE"),
            "sr_taxable_paise": sr_taxable,
            "gstr1_taxable_paise": g1_taxable,
            "taxable_diff_paise": taxable_diff,
            "sr_tax_paise": sr_tax,
            "gstr1_tax_paise": g1_tax,
            "tax_diff_paise": tax_diff,
            "matched_fields": ["invoice_number", "gstin"],
            "differed_fields": differed,
        },
    )


def classify_wrong_classification(
    sr_rec: Mapping[str, Any],
    gstr1_rec: Mapping[str, Any],
) -> MismatchResult | None:
    """G1M4 — Invoice is B2B in one source and B2C in the other.

    Returns ``None`` if both records have the same classification or if
    classification cannot be determined.

    Classification heuristic
    ------------------------
    * **B2B**: record has a non-empty recipient/counterparty GSTIN.
    * **B2C**: GSTIN is absent, empty, or ``"URP"`` (unregistered person).
    """
    inv = str(_get_field(sr_rec, "invoice_number") or "?")

    sr_gstin_raw = _normalize_gstin_value(
        _get_field(sr_rec, "gstin", "recipient_gstin", default="")
    )
    g1_gstin_raw = _normalize_gstin_value(
        _get_field(gstr1_rec, "recipient_gstin", "gstin", default="")
    )
    sr_gstin = (sr_gstin_raw or "").upper()
    g1_gstin = (g1_gstin_raw or "").upper()

    def _is_b2b(gstin: str) -> bool:
        return bool(gstin) and gstin != "URP" and len(gstin) == 15

    sr_b2b = _is_b2b(sr_gstin)
    g1_b2b = _is_b2b(g1_gstin)

    if sr_b2b == g1_b2b:
        return None

    sr_class = "B2B" if sr_b2b else "B2C"
    g1_class = "B2B" if g1_b2b else "B2C"

    recipient_name = (
        _get_field(sr_rec, "recipient_name", "customer_name", "trade_name", default="")
        or _get_field(
            gstr1_rec, "recipient_name", "customer_name", "trade_name", default=""
        )
    )
    recipient_label = _recipient_display_label(
        gstin=sr_gstin_raw or g1_gstin_raw,
        name=recipient_name or None,
    )

    return MismatchResult(
        mismatch_type=MismatchType.WRONG_CLASSIFICATION,
        severity=MismatchSeverity.CRITICAL,
        decision_what=(
            f"Invoice {inv}: classified as {sr_class} in Sales Register "
            f"but {g1_class} in GSTR-1"
        ),
        decision_why=(
            f"A B2B invoice enables the recipient to claim ITC, while a B2C "
            f"invoice does not. Filing under the wrong table in GSTR-1 "
            f"affects the recipient's ITC eligibility and may trigger a "
            f"DRC-01C notice. Section 37 requires accurate classification."
        ),
        decision_next=(
            f"Verify whether the recipient ({recipient_label}) is a "
            f"registered taxpayer. Amend GSTR-1 to move the invoice to the "
            f"correct table ({sr_class} if the Sales Register is authoritative, "
            f"or update the Sales Register if GSTR-1 is correct)."
        ),
        rule_id="G1M_004",
        details={
            "invoice_number": inv,
            "sr_classification": sr_class,
            "gstr1_classification": g1_class,
            "sr_gstin": sr_gstin_raw,
            "gstr1_gstin": g1_gstin_raw,
            "matched_fields": ["invoice_number"],
            "differed_fields": ["classification"],
        },
    )


def classify_tax_structure_mismatch(
    sr_rec: Mapping[str, Any],
    gstr1_rec: Mapping[str, Any],
) -> MismatchResult | None:
    """G1M3 — IGST vs CGST+SGST structure disagrees (place-of-supply nature).

    Flags when one side is clearly interstate (IGST-only) and the other is
    intrastate (CGST+SGST), which usually means a place-of-supply / interstate
    flag error even when the PoS code string matches.
    """
    def _structure(rec: Mapping[str, Any]) -> str | None:
        igst = abs(_safe_int(rec.get("igst_paise")))
        cgst = abs(_safe_int(rec.get("cgst_paise")))
        sgst = abs(_safe_int(rec.get("sgst_paise")))
        if igst > 0 and cgst == 0 and sgst == 0:
            return "interstate"
        if (cgst > 0 or sgst > 0) and igst == 0:
            return "intrastate"
        # Explicit interstate flag when tax components were derived from rate
        flag = rec.get("is_interstate")
        if flag is True:
            return "interstate"
        if flag is False:
            return "intrastate"
        return None

    sr_struct = _structure(sr_rec)
    g1_struct = _structure(gstr1_rec)
    if not sr_struct or not g1_struct or sr_struct == g1_struct:
        return None

    inv = str(_get_field(sr_rec, "invoice_number") or "?")
    sr_pos = _get_field(sr_rec, "place_of_supply", default=None)
    g1_pos = _get_field(gstr1_rec, "place_of_supply", default=None)
    return MismatchResult(
        mismatch_type=MismatchType.AMOUNT_MISMATCH,
        severity=MismatchSeverity.HIGH,
        decision_what=(
            f"Invoice {inv}: tax structure is {sr_struct} in Sales Register "
            f"but {g1_struct} in GSTR-1 (place-of-supply / interstate nature)"
        ),
        decision_why=(
            "IGST applies to interstate supplies while CGST+SGST apply to "
            "intrastate supplies. A mismatch here usually means the place of "
            "supply or interstate flag is wrong on one side, even when the "
            "state-code text looks the same."
        ),
        decision_next=(
            f"Verify place of supply for invoice {inv} "
            f"(SR={sr_pos or '—'}, GSTR-1={g1_pos or '—'}) and whether the "
            f"supply is interstate. Correct the tax split and amend GSTR-1 "
            f"if filed incorrectly."
        ),
        rule_id="G1M_003",
        details={
            "invoice_number": inv,
            "sr_tax_structure": sr_struct,
            "gstr1_tax_structure": g1_struct,
            "sr_place_of_supply": sr_pos,
            "gstr1_place_of_supply": g1_pos,
            "matched_fields": ["invoice_number"],
            "differed_fields": ["tax_structure", "place_of_supply"],
        },
    )


def classify_rate_mismatch(
    sr_rec: Mapping[str, Any],
    gstr1_rec: Mapping[str, Any],
) -> MismatchResult | None:
    """G1M5 — GST rate differs between Sales Register and GSTR-1.

    Returns ``None`` if rates match or cannot be determined on either side.

    Rate detection
    --------------
    Tries ``gst_rate``, ``rate``, ``tax_rate`` keys first.  Falls back to
    computing ``total_tax_paise / taxable_amount_paise * 100`` if the
    explicit field is missing.
    """
    inv = str(_get_field(sr_rec, "invoice_number") or "?")

    sr_rate = _detect_rate(sr_rec)
    g1_rate = _detect_rate(gstr1_rec)

    if sr_rate is None or g1_rate is None:
        return None

    # Rates are floats — use a tolerance of 0.5pp to avoid rounding noise
    if abs(sr_rate - g1_rate) <= 0.5:
        return None

    return MismatchResult(
        mismatch_type=MismatchType.RATE_MISMATCH,
        severity=MismatchSeverity.HIGH,
        decision_what=(
            f"Invoice {inv}: GST rate is {sr_rate:.1f}% in Sales Register "
            f"but {g1_rate:.1f}% in GSTR-1"
        ),
        decision_why=(
            f"Applying the wrong GST rate results in either short payment "
            f"(attracting interest under Section 50 and penalties under "
            f"Section 122) or excess payment of output tax. The correct rate "
            f"depends on the HSN/SAC classification of the supply."
        ),
        decision_next=(
            f"Verify the applicable GST rate for this supply based on HSN/SAC "
            f"code. Amend GSTR-1 if the filed rate is incorrect, or update "
            f"the Sales Register if the books are wrong."
        ),
        rule_id="G1M_005",
        details={
            "invoice_number": inv,
            "sr_rate": sr_rate,
            "gstr1_rate": g1_rate,
            "rate_diff": round(abs(sr_rate - g1_rate), 2),
            "matched_fields": ["invoice_number", "gstin"],
            "differed_fields": ["gst_rate"],
        },
    )


def _detect_rate(rec: Mapping[str, Any]) -> float | None:
    """Best-effort GST rate detection from a record."""
    # Try explicit rate fields
    for key in ("gst_rate", "rate", "tax_rate"):
        v = rec.get(key)
        if v is not None:
            try:
                r = float(v)
                if 0.0 < r <= 100.0:
                    return round(r, 2)
            except (TypeError, ValueError):
                continue

    # Fall back to computation: total_tax / taxable_amount * 100
    taxable = abs(_safe_int(rec.get("taxable_amount_paise")))
    total_tax = abs(_safe_int(rec.get("total_tax_paise")))
    if taxable > 0 and total_tax > 0:
        computed = (total_tax / taxable) * 100
        # Snap to standard GST rates if close
        for std in (0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 14.0, 18.0, 28.0):
            if abs(computed - std) <= 0.5:
                return std
        return round(computed, 2)

    return None


def classify_period_mismatch(
    sr_rec: Mapping[str, Any],
    gstr1_rec: Mapping[str, Any],
    *,
    gstr1_filing_period: str | None = None,
) -> MismatchResult | None:
    """G1M6 — Invoice reported in a different month's GSTR-1 than invoice date.

    Returns ``None`` if both invoice date and filing period align, or if
    either value cannot be determined.

    The filing period can be supplied explicitly via *gstr1_filing_period*
    (``"MMYYYY"`` or ``"MM-YYYY"`` format) or inferred from the GSTR-1
    record's ``filing_period``, ``return_period``, or ``fp`` field.
    """
    inv = str(_get_field(sr_rec, "invoice_number") or "?")
    inv_date = _parse_date(
        _get_field(sr_rec, "invoice_date") or _get_field(gstr1_rec, "invoice_date")
    )
    if inv_date is None:
        return None

    # Determine filing period
    fp_raw = gstr1_filing_period or str(
        _get_field(gstr1_rec, "filing_period", "return_period", "fp") or ""
    )
    fp_date = _parse_filing_period(fp_raw)
    if fp_date is None:
        return None

    # Compare: invoice month/year vs filing period month/year
    if inv_date.year == fp_date.year and inv_date.month == fp_date.month:
        return None

    inv_period_label = _invoice_period_label(inv_date)
    fp_label = _invoice_period_label(fp_date)
    months_diff = (
        (fp_date.year - inv_date.year) * 12
        + (fp_date.month - inv_date.month)
    )

    severity = (
        MismatchSeverity.HIGH
        if abs(months_diff) > 1
        else MismatchSeverity.MEDIUM
    )

    return MismatchResult(
        mismatch_type=MismatchType.PERIOD_MISMATCH,
        severity=severity,
        decision_what=(
            f"Invoice {inv} dated {inv_period_label} was filed in "
            f"{fp_label} GSTR-1 ({abs(months_diff)} month{'s' if abs(months_diff) != 1 else ''} "
            f"{'later' if months_diff > 0 else 'earlier'})"
        ),
        decision_why=(
            f"Section 37 requires invoices to be reported in the return "
            f"period corresponding to the invoice date. Reporting in a "
            f"different period may lead to interest liability under Section 50 "
            f"and could be flagged during assessment."
        ),
        decision_next=(
            f"If the invoice was genuinely issued in {inv_period_label}, "
            f"amend the {fp_label} GSTR-1 to move it to the correct period "
            f"(or confirm it was a permitted late addition within the "
            f"amendment window under Section 37)."
        ),
        rule_id="G1M_006",
        details={
            "invoice_number": inv,
            "invoice_date": inv_date.isoformat(),
            "invoice_period": inv_period_label,
            "filing_period": fp_label,
            "months_diff": months_diff,
            "matched_fields": ["invoice_number", "gstin"],
            "differed_fields": ["filing_period"],
        },
    )


def _parse_filing_period(raw: str) -> date | None:
    """Parse ``"MMYYYY"``, ``"MM-YYYY"``, ``"YYYY-MM"``, ISO date to first-of-month date."""
    if not raw:
        return None
    try:
        from app.parsers.gstr1_parser import _parse_filing_period as _g1_parse_fp
        return _g1_parse_fp(raw)
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# G1M7 — Invalid / inactive buyer GSTIN
# ══════════════════════════════════════════════════════════════════════════════

_ABSENT_BUYER_GSTIN_TOKENS: frozenset[str] = frozenset({
    "NA", "N/A", "N.A", "N.A.", "NONE", "NULL", "NIL", "-", "--", ".", "0",
    "UNREGISTERED", "URP", "NAN", "NAT", "<NA>",
})


def clean_buyer_gstin(raw: Any) -> str | None:
    """Return a cleaned upper-case GSTIN, or ``None`` when absent / placeholder."""
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    collapsed = WHITELIST_PATTERN.sub("", s)
    if s in _ABSENT_BUYER_GSTIN_TOKENS or collapsed in {
        "NA", "NIL", "NULL", "NONE", "URP", "NAN", "NAT",
    }:
        return None
    return collapsed or None


def gstin_format_ok(gstin: str) -> bool:
    """Basic 15-char GSTIN regex check (no Sandbox API call)."""
    return bool(gstin) and bool(GSTIN_REGEX.match(gstin))


def collect_unique_buyer_gstins(
    *,
    sr_records: list[Mapping[str, Any]] | None = None,
    gstr1_records: list[Mapping[str, Any]] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Map each unique buyer GSTIN to invoice refs ``{source, invoice_number}``.

    Sources are ``\"sales_register\"`` and ``\"gstr1\"``. Placeholders / blanks
    are skipped. Used to cache Sandbox verification once per GSTIN per run.
    """
    out: dict[str, list[dict[str, str]]] = {}

    def _add(rec: Mapping[str, Any], *, source: str, keys: tuple[str, ...]) -> None:
        raw = _get_field(rec, *keys, default=None)
        gstin = clean_buyer_gstin(raw)
        if not gstin:
            return
        inv = str(_get_field(rec, "invoice_number", "invoice_number_normalized") or "?")
        refs = out.setdefault(gstin, [])
        entry = {"source": source, "invoice_number": inv}
        if entry not in refs:
            refs.append(entry)

    for rec in sr_records or []:
        _add(rec, source="sales_register", keys=("gstin", "recipient_gstin"))
    for rec in gstr1_records or []:
        _add(rec, source="gstr1", keys=("recipient_gstin", "gstin"))
    return out


def classify_invalid_gstin(
    *,
    gstin: str,
    source: str,
    invoice_number: str,
    reason: str,
    api_status: str | None = None,
    legal_name: str | None = None,
    trade_name: str | None = None,
) -> MismatchResult:
    """G1M7 — Buyer GSTIN is malformed, not found, cancelled, or inactive.

    Parameters
    ----------
    gstin :
        Cleaned GSTIN string that failed validation / verification.
    source :
        ``\"sales_register\"`` or ``\"gstr1\"``.
    invoice_number :
        Invoice that carries this GSTIN.
    reason :
        ``invalid_format`` | ``not_found`` | ``cancelled`` | ``inactive`` |
        ``unknown_status``.
    api_status, legal_name, trade_name :
        Optional Sandbox verification fields for decision text.
    """
    status_label = (api_status or reason.replace("_", " ")).strip()
    recipient_label = _recipient_display_label(
        gstin=gstin, name=legal_name or trade_name,
    )

    if reason == "invalid_format":
        what = f"Buyer GSTIN {gstin} on invoice {invoice_number} has an invalid format"
        why = (
            "A valid 15-character GSTIN is required for B2B reporting in GSTR-1. "
            "An invalid format means the recipient cannot claim ITC and the "
            "invoice may be rejected or flagged during filing."
        )
        next_step = (
            f"Correct the GSTIN for invoice {invoice_number} in the "
            f"{'Sales Register' if source == 'sales_register' else 'GSTR-1'} "
            f"before filing or amending."
        )
        severity = MismatchSeverity.CRITICAL
    elif reason == "not_found":
        what = (
            f"Buyer GSTIN {gstin} on invoice {invoice_number} was not found "
            f"in the GST registry"
        )
        why = (
            "Sandbox.co.in returned Not Found for this GSTIN. Reporting a "
            "non-existent GSTIN in GSTR-1 risks notices and blocks the "
            f"buyer's ITC claim for {recipient_label}."
        )
        next_step = (
            f"Verify the correct GSTIN with the buyer for invoice "
            f"{invoice_number}, then amend the Sales Register / GSTR-1."
        )
        severity = MismatchSeverity.CRITICAL
    elif reason == "cancelled":
        what = (
            f"Buyer GSTIN {gstin} on invoice {invoice_number} has status "
            f"'{status_label}'"
        )
        why = (
            "A cancelled or suspended GSTIN cannot receive taxable supplies "
            "as a registered person. Filing under this GSTIN can create "
            "output-tax / ITC disputes."
        )
        next_step = (
            f"Confirm registration status with {recipient_label}. If cancelled, "
            f"treat as B2C/unregistered or obtain a valid GSTIN, then amend."
        )
        severity = MismatchSeverity.HIGH
    else:
        what = (
            f"Buyer GSTIN {gstin} on invoice {invoice_number} failed "
            f"verification (status: {status_label})"
        )
        why = (
            "GSTIN verification did not confirm an active registration. "
            "Filing against an inactive or unverified GSTIN creates "
            "compliance risk for both supplier and recipient."
        )
        next_step = (
            f"Re-check GSTIN {gstin} for invoice {invoice_number} with the "
            f"buyer and amend if needed."
        )
        severity = MismatchSeverity.HIGH

    return MismatchResult(
        mismatch_type=MismatchType.INVALID_GSTIN,
        severity=severity,
        decision_what=what,
        decision_why=why,
        decision_next=next_step,
        rule_id="G1M_007",
        details={
            "invoice_number": invoice_number,
            "recipient_gstin": gstin,
            "source": source,
            "reason": reason,
            "gstin_status": status_label,
            "legal_name": legal_name,
            "trade_name": trade_name,
            "matched_fields": [],
            "differed_fields": ["gstin"],
        },
    )


def build_g1m7_mismatches(
    *,
    gstin_refs: Mapping[str, list[Mapping[str, str]]],
    verification_by_gstin: Mapping[str, Mapping[str, Any]],
) -> list[MismatchResult]:
    """Build G1M7 results from a per-run GSTIN verification cache.

    *verification_by_gstin* values should look like ``verify_gstin`` results,
    or ``{\"valid\": False, \"status\": \"Invalid Format\", \"reason\":
    \"invalid_format\"}`` for regex failures that never hit the API.

    Only definitive compliance failures are flagged:

    * ``invalid_format`` (local regex)
    * ``cancelled`` / ``inactive`` / ``suspended`` (explicit Sandbox status)

    ``Not Found`` / API / auth / unknown-status results are ignored here —
    synthetic and newly-issued GSTINs otherwise flood every invoice. Pairwise
    SR↔GSTR-1 GSTIN mismatches are handled by
    :func:`classify_gstin_mismatch` on matched pairs.
    """
    results: list[MismatchResult] = []
    for gstin, refs in gstin_refs.items():
        ver = verification_by_gstin.get(gstin)
        if not ver:
            continue
        reason = str(ver.get("reason") or "").strip().lower()
        status = str(ver.get("status") or "").strip()
        status_l = status.lower()
        valid = bool(ver.get("valid"))

        if reason == "invalid_format" or status_l == "invalid format":
            fail_reason = "invalid_format"
        elif not valid and status_l in ("cancelled", "inactive", "suspended"):
            fail_reason = "cancelled"
        else:
            # Active, Not Found, API Error, Auth Error, unknown → no G1M7 flood
            continue

        for ref in refs:
            results.append(
                classify_invalid_gstin(
                    gstin=gstin,
                    source=str(ref.get("source") or "sales_register"),
                    invoice_number=str(ref.get("invoice_number") or "?"),
                    reason=fail_reason,
                    api_status=status or None,
                    legal_name=ver.get("legal_name"),  # type: ignore[arg-type]
                    trade_name=ver.get("trade_name"),  # type: ignore[arg-type]
                )
            )
    return results


def classify_gstin_mismatch(
    sr_rec: Mapping[str, Any],
    gstr1_rec: Mapping[str, Any],
) -> MismatchResult | None:
    """G1M7 — Buyer GSTIN differs between Sales Register and GSTR-1 on a match.

    Used when invoices match on invoice number but the recipient GSTIN does
    not. Returns ``None`` when GSTINs are equal, both absent, or either side
    lacks an invoice identity.
    """
    sr_gstin = clean_buyer_gstin(
        _get_field(sr_rec, "gstin", "recipient_gstin", default=None)
    )
    g1_gstin = clean_buyer_gstin(
        _get_field(gstr1_rec, "recipient_gstin", "gstin", default=None)
    )
    if not sr_gstin and not g1_gstin:
        return None
    if sr_gstin == g1_gstin:
        return None

    inv = str(
        _get_field(sr_rec, "invoice_number", "invoice_number_normalized")
        or _get_field(gstr1_rec, "invoice_number", "invoice_number_normalized")
        or "?"
    )
    sr_label = sr_gstin or "(blank)"
    g1_label = g1_gstin or "(blank)"
    return MismatchResult(
        mismatch_type=MismatchType.INVALID_GSTIN,
        severity=MismatchSeverity.HIGH,
        decision_what=(
            f"Invoice {inv}: buyer GSTIN is {sr_label} in Sales Register "
            f"but {g1_label} in GSTR-1"
        ),
        decision_why=(
            "Invoice numbers match, but the recipient GSTIN differs between "
            "books and the return. This is usually a typo or amendment that "
            "was not mirrored on both sides. Filing the wrong GSTIN blocks "
            "the buyer's ITC and can trigger notices."
        ),
        decision_next=(
            f"Confirm the correct GSTIN for invoice {inv} with the buyer. "
            f"Amend GSTR-1 and/or correct the Sales Register so both sides "
            f"carry the same 15-character GSTIN."
        ),
        rule_id="G1M_007",
        details={
            "invoice_number": inv,
            "sr_gstin": sr_gstin,
            "gstr1_gstin": g1_gstin,
            "recipient_gstin": sr_gstin or g1_gstin,
            "source": "matched_pair",
            "reason": "gstin_mismatch",
            "matched_fields": ["invoice_number"],
            "differed_fields": ["gstin"],
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Batch classification — run all rules on a reconciled dataset
# ══════════════════════════════════════════════════════════════════════════════

def classify_all_mismatches(
    *,
    unmatched_sr: list[Mapping[str, Any]] | None = None,
    unmatched_gstr1: list[Mapping[str, Any]] | None = None,
    matched_pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] | None = None,
    gstr1_filing_period: str | None = None,
    amount_tolerance_paise: int = AMOUNT_TOLERANCE_PAISE,
    amount_tolerance_pct: float = AMOUNT_TOLERANCE_PCT,
) -> list[MismatchResult]:
    """Run all GSTR-1 mismatch rules on a reconciled dataset.

    Parameters
    ----------
    unmatched_sr : list
        Sales Register records with no GSTR-1 match (→ ``G1M1``).
    unmatched_gstr1 : list
        GSTR-1 records with no Sales Register match (→ ``G1M2``).
    matched_pairs : list[tuple]
        ``(sr_rec, gstr1_rec)`` pairs that matched but may have
        amount/classification/rate/period discrepancies
        (→ ``G1M3``–``G1M6``).
    gstr1_filing_period : str, optional
        GSTR-1 return period in ``"MMYYYY"`` format; used by the
        period-mismatch rule when the record doesn't carry its own.
    amount_tolerance_paise, amount_tolerance_pct : int, float
        Overrides for the amount-mismatch rule.

    Returns
    -------
    list[MismatchResult]
        All detected mismatches, sorted by severity (critical first).
    """
    results: list[MismatchResult] = []

    # G1M1 — Missing invoices
    for sr_rec in unmatched_sr or []:
        results.append(classify_missing_invoice(sr_rec))

    # G1M2 — Extra invoices
    for g1_rec in unmatched_gstr1 or []:
        results.append(classify_extra_invoice(g1_rec))

    # G1M3–G1M7 — Matched-pair rules
    for sr_rec, g1_rec in matched_pairs or []:
        # G1M7 — GSTIN mismatch on an otherwise-matched invoice
        gstin_mm = classify_gstin_mismatch(sr_rec, g1_rec)
        if gstin_mm is not None:
            results.append(gstin_mm)

        # G1M5 — Rate mismatch (before amount, so tax-only diffs can be suppressed)
        rate = classify_rate_mismatch(sr_rec, g1_rec)
        if rate is not None:
            results.append(rate)

        # G1M3 — Amount mismatch
        amt = classify_amount_mismatch(
            sr_rec, g1_rec,
            tolerance_paise=amount_tolerance_paise,
            tolerance_pct=amount_tolerance_pct,
        )
        if amt is not None:
            differed = list(amt.details.get("differed_fields") or [])
            # Tax-only diff is explained by a rate mismatch — don't double-count.
            if rate is not None and differed == ["total_tax"]:
                amt = None
        if amt is not None:
            results.append(amt)

        # Tax structure / place-of-supply nature (IGST vs CGST+SGST)
        tax_struct = classify_tax_structure_mismatch(sr_rec, g1_rec)
        if tax_struct is not None:
            results.append(tax_struct)

        # G1M4 — Wrong classification
        cls = classify_wrong_classification(sr_rec, g1_rec)
        if cls is not None:
            results.append(cls)

        # G1M6 — Filing period mismatch
        period = classify_period_mismatch(
            sr_rec, g1_rec, gstr1_filing_period=gstr1_filing_period,
        )
        if period is not None:
            results.append(period)

    # Sort: critical → high → medium → low
    _sev_order = {
        MismatchSeverity.CRITICAL: 0,
        MismatchSeverity.HIGH: 1,
        MismatchSeverity.MEDIUM: 2,
        MismatchSeverity.LOW: 3,
    }
    results.sort(key=lambda r: _sev_order.get(r.severity, 99))

    _log.info(
        "classify_all_mismatches: %d mismatches (%d missing, %d extra, "
        "%d amount, %d classification, %d rate, %d period)",
        len(results),
        sum(1 for r in results if r.mismatch_type == MismatchType.MISSING_INVOICE),
        sum(1 for r in results if r.mismatch_type == MismatchType.EXTRA_INVOICE),
        sum(1 for r in results if r.mismatch_type == MismatchType.AMOUNT_MISMATCH),
        sum(1 for r in results if r.mismatch_type == MismatchType.WRONG_CLASSIFICATION),
        sum(1 for r in results if r.mismatch_type == MismatchType.RATE_MISMATCH),
        sum(1 for r in results if r.mismatch_type == MismatchType.PERIOD_MISMATCH),
    )

    return results


# ══════════════════════════════════════════════════════════════════════════════
# G1M8 — Invoice series continuity & duplicate detection
# ══════════════════════════════════════════════════════════════════════════════

# Regex to split an invoice number into (prefix, numeric_part).
# Captures the *last* contiguous run of digits as the sequence number;
# everything before it (including separators) is the series prefix.
# Examples:
#   "INV/2024/001"  → prefix="INV/2024/",  num="001"
#   "B2B-0042"      → prefix="B2B-",       num="0042"
#   "EXP/001"       → prefix="EXP/",       num="001"
#   "12345"         → prefix="",            num="12345"
_INVOICE_SERIES_RE = re.compile(r'^(.*?)(\d+)$')

# Only analyse series with at least this many invoices — avoids false
# positives from one-off or two-invoice "series".
_MIN_SERIES_SIZE = 3

# Cap gap reports per series so large ranges don't flood the output.
_MAX_GAPS_PER_SERIES = 20

# Only report contiguous missing runs at least this long. Singleton holes are
# usually cancelled invoices or one-off skips, not a series continuity issue.
_MIN_GAP_RUN_LENGTH = 3

# Skip gap detection when numeric tail span is absurd — mixed invoice formats
# (e.g. RD2026273001 vs RD3002 sharing prefix "RD") can otherwise OOM.
_MAX_SERIES_NUMERIC_SPAN = 10_000


def _contiguous_missing_runs(missing: list[int]) -> list[list[int]]:
    """Split a sorted list of missing numbers into contiguous runs."""
    if not missing:
        return []
    runs: list[list[int]] = [[missing[0]]]
    for n in missing[1:]:
        if n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def _split_invoice_number(inv: str) -> tuple[str, int] | None:
    """Split an invoice number into ``(prefix, numeric_sequence)``.

    Returns ``None`` if the invoice number contains no digits.
    """
    m = _INVOICE_SERIES_RE.match(inv.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _classify_series_gap(
    *,
    series_prefix: str,
    missing_numbers: list[int],
    series_min: int,
    series_max: int,
    series_count: int,
) -> MismatchResult:
    """G1M8 sub-type — gaps (missing sequence numbers) in a series."""
    prefix_label = series_prefix if series_prefix else "(numeric)"
    # Show up to 10 individual numbers, then summarise
    if len(missing_numbers) <= 10:
        nums_str = ", ".join(f"{series_prefix}{n}" for n in missing_numbers)
    else:
        first_five = ", ".join(f"{series_prefix}{n}" for n in missing_numbers[:5])
        nums_str = f"{first_five} … and {len(missing_numbers) - 5} more"

    return MismatchResult(
        mismatch_type=MismatchType.INVOICE_SERIES_ISSUE,
        severity=MismatchSeverity.MEDIUM,
        decision_what=(
            f"Series '{prefix_label}': {len(missing_numbers)} missing invoice "
            f"number(s) detected between {series_prefix}{series_min} and "
            f"{series_prefix}{series_max}"
        ),
        decision_why=(
            f"Rule 46 of CGST Rules mandates consecutive serial numbering of "
            f"tax invoices. Gaps in the series '{prefix_label}' ({series_count} "
            f"invoices found, {len(missing_numbers)} missing) may indicate "
            f"cancelled invoices not recorded, or unreported sales that "
            f"constitute under-reporting of output tax liability."
        ),
        decision_next=(
            f"Verify the missing invoice number(s): {nums_str}. If cancelled, "
            f"record cancellation entries. If the invoices exist but were not "
            f"uploaded, add them to the Sales Register before filing GSTR-1."
        ),
        rule_id="G1M_008",
        gst_ref="Rule 46 CGST Rules",
        details={
            "issue_type": "gap",
            "series_prefix": series_prefix,
            "missing_numbers": missing_numbers,
            "missing_count": len(missing_numbers),
            "series_min": series_min,
            "series_max": series_max,
            "series_invoice_count": series_count,
            "matched_fields": [],
            "differed_fields": ["invoice_sequence"],
        },
    )


def _classify_duplicate_invoice(
    *,
    invoice_number: str,
    occurrence_count: int,
    invoice_dates: list[str],
    source_label: str = "sales_register",
) -> MismatchResult:
    """G1M8 sub-type — duplicate invoice numbers."""
    dates_str = ", ".join(invoice_dates[:5])
    if len(invoice_dates) > 5:
        dates_str += f" … and {len(invoice_dates) - 5} more"

    if source_label in ("sales_register", "sr"):
        source_display = "the Sales Register"
        decision_next = (
            f"Review all {occurrence_count} entries for invoice '{invoice_number}'. "
            f"If duplicates are data-entry errors, remove the extras. If they "
            f"are genuine separate transactions, assign unique invoice numbers "
            f"before filing GSTR-1."
        )
    elif source_label in ("gstr1", "gstr-1"):
        source_display = "GSTR-1"
        decision_next = (
            f"Review all {occurrence_count} entries for invoice '{invoice_number}' in GSTR-1. "
            f"If duplicates are filing errors, remove or amend the extra entries. If they "
            f"are genuine separate transactions, ensure unique invoice numbers "
            f"are assigned under Rule 46."
        )
    else:
        source_display = source_label
        decision_next = (
            f"Review all {occurrence_count} entries for invoice '{invoice_number}'. "
            f"If duplicates are errors, remove the extras. If they are genuine "
            f"separate transactions, assign unique invoice numbers."
        )

    return MismatchResult(
        mismatch_type=MismatchType.INVOICE_SERIES_ISSUE,
        severity=MismatchSeverity.HIGH,
        decision_what=(
            f"Invoice number '{invoice_number}' appears {occurrence_count} "
            f"times in {source_display}"
        ),
        decision_why=(
            f"Duplicate invoice numbers violate Rule 46 of CGST Rules which "
            f"requires unique serial numbering. This may indicate duplicate "
            f"data entry, double billing, or a numbering system error. "
            f"Occurrences found on dates: {dates_str}."
        ),
        decision_next=decision_next,
        rule_id="G1M_008",
        gst_ref="Rule 46 CGST Rules",
        details={
            "issue_type": "duplicate",
            "invoice_number": invoice_number,
            "occurrence_count": occurrence_count,
            "invoice_dates": invoice_dates,
            "source": source_label,
            "matched_fields": [],
            "differed_fields": ["invoice_number"],
        },
    )


def _classify_out_of_order_invoice(
    *,
    invoice_number: str,
    invoice_date: str,
    expected_after: str,
    expected_after_date: str,
    series_prefix: str,
) -> MismatchResult:
    """G1M8 sub-type — invoice date breaks chronological order within series."""
    prefix_label = series_prefix if series_prefix else "(numeric)"
    return MismatchResult(
        mismatch_type=MismatchType.INVOICE_SERIES_ISSUE,
        severity=MismatchSeverity.MEDIUM,
        decision_what=(
            f"Invoice '{invoice_number}' (dated {invoice_date}) is numbered "
            f"after '{expected_after}' (dated {expected_after_date}) but has "
            f"an earlier date"
        ),
        decision_why=(
            f"In series '{prefix_label}', invoice dates should generally "
            f"follow the numeric sequence. A later-numbered invoice with an "
            f"earlier date may indicate backdating, late data entry, or an "
            f"invoice numbering error. This can attract scrutiny during "
            f"GST audits under Section 65."
        ),
        decision_next=(
            f"Verify whether invoice '{invoice_number}' was genuinely issued "
            f"on {invoice_date}. If the date is wrong, correct it in the "
            f"Sales Register. If the invoice was backdated intentionally, "
            f"document the business reason for audit trail purposes."
        ),
        rule_id="G1M_008",
        gst_ref="Rule 46 CGST Rules",
        details={
            "issue_type": "out_of_order",
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "expected_after": expected_after,
            "expected_after_date": expected_after_date,
            "series_prefix": series_prefix,
            "matched_fields": [],
            "differed_fields": ["invoice_date_order"],
        },
    )


def _analyse_series_gaps_and_duplicates(
    records: list[Mapping[str, Any]],
    *,
    source_label: str,
) -> list[MismatchResult]:
    """Gap + duplicate detection for one source (SR or GSTR-1)."""
    results: list[MismatchResult] = []
    if not records:
        return results

    inv_occurrences: dict[str, list[str]] = {}
    series: dict[str, list[tuple[int, str, date | None]]] = {}

    for rec in records:
        inv_raw = str(
            _get_field(rec, "invoice_number", "invoice_number_normalized",
                       default="")
        ).strip()
        if not inv_raw:
            continue
        inv_date = _parse_date(
            _get_field(rec, "invoice_date", default=None)
        )
        date_str = inv_date.isoformat() if inv_date else "unknown"
        inv_occurrences.setdefault(inv_raw, []).append(date_str)

        split = _split_invoice_number(inv_raw)
        if split is None:
            continue
        prefix, num = split
        series.setdefault(prefix, []).append((num, inv_raw, inv_date))

    for inv_num, dates in inv_occurrences.items():
        if len(dates) > 1:
            results.append(
                _classify_duplicate_invoice(
                    invoice_number=inv_num,
                    occurrence_count=len(dates),
                    invoice_dates=dates,
                    source_label=source_label,
                )
            )

    for prefix, entries in series.items():
        if len(entries) < _MIN_SERIES_SIZE:
            continue
        entries_sorted = sorted(entries, key=lambda e: e[0])
        nums_sorted = [e[0] for e in entries_sorted]
        series_min = nums_sorted[0]
        series_max = nums_sorted[-1]
        present = set(nums_sorted)
        span = series_max - series_min
        if span > _MAX_SERIES_NUMERIC_SPAN:
            _log.warning(
                "check_invoice_series_continuity: %s series %r span %d "
                "exceeds cap %d — skipping gap detection",
                source_label,
                prefix or "(numeric)",
                span,
                _MAX_SERIES_NUMERIC_SPAN,
            )
            continue
        missing = sorted(set(range(series_min, series_max + 1)) - present)
        for run in _contiguous_missing_runs(missing):
            if len(run) < _MIN_GAP_RUN_LENGTH:
                continue
            results.append(
                _classify_series_gap(
                    series_prefix=prefix,
                    missing_numbers=run[:_MAX_GAPS_PER_SERIES],
                    series_min=series_min,
                    series_max=series_max,
                    series_count=len(entries),
                )
            )
    return results


def check_invoice_series_continuity(
    sr_records: list[Mapping[str, Any]],
    gstr1_records: list[Mapping[str, Any]] | None = None,
) -> list[MismatchResult]:
    """G1M8 — Detect invoice series gaps and duplicates.

    Analyses Sales Register and (optionally) GSTR-1 invoice numbering:

    1. **Duplicates** — same invoice number appearing more than once.
    2. **Gaps** — missing sequence numbers within a detected series.

    Out-of-order date checks are intentionally omitted: real filings often
    have non-monotonic dates within a series and that path previously
    flooded results with thousands of false positives.

    Series are auto-detected by splitting each invoice number into
    ``(prefix, numeric_part)`` via regex. Different prefixes form
    independent series — gaps are never flagged across series.
    """
    results: list[MismatchResult] = []
    results.extend(
        _analyse_series_gaps_and_duplicates(
            sr_records or [], source_label="sales_register",
        )
    )
    # GSTR-1 gap detection catches unfiled consecutive blocks (e.g. INV1500–1504)
    # that are still present in the Sales Register.
    g1_gaps = _analyse_series_gaps_and_duplicates(
        gstr1_records or [], source_label="gstr1",
    )
    # Prefer GSTR-1 gap reports when the same prefix already appeared from SR
    # with an identical missing set (dedupe). Keep unique gaps from either side.
    seen_gap_keys: set[tuple[str, tuple[int, ...]]] = set()
    for r in results:
        if r.details.get("issue_type") == "gap":
            key = (
                str(r.details.get("series_prefix") or ""),
                tuple(r.details.get("missing_numbers") or ()),
            )
            seen_gap_keys.add(key)
    for r in g1_gaps:
        if r.details.get("issue_type") == "gap":
            key = (
                str(r.details.get("series_prefix") or ""),
                tuple(r.details.get("missing_numbers") or ()),
            )
            if key in seen_gap_keys:
                continue
            seen_gap_keys.add(key)
        results.append(r)

    _sev_order = {
        MismatchSeverity.CRITICAL: 0,
        MismatchSeverity.HIGH: 1,
        MismatchSeverity.MEDIUM: 2,
        MismatchSeverity.LOW: 3,
    }
    results.sort(key=lambda r: _sev_order.get(r.severity, 99))

    _log.info(
        "check_invoice_series_continuity: %d issues (%d duplicates, %d gaps)",
        len(results),
        sum(1 for r in results if r.details.get("issue_type") == "duplicate"),
        sum(1 for r in results if r.details.get("issue_type") == "gap"),
    )

    return results


# ══════════════════════════════════════════════════════════════════════════════
# G1M9 — HSN code & tax rate schedule validation
# ══════════════════════════════════════════════════════════════════════════════

# Rate tolerance (percentage points) when comparing applied vs schedule rates.
_HSN_RATE_TOLERANCE_PP = 0.5


def _classify_missing_hsn(
    *,
    invoice_number: str,
    source: str,
    applied_rate: float | None,
) -> MismatchResult:
    """G1M9 sub-type — invoice row has no HSN/SAC code."""
    rate_note = (
        f" Applied rate on the invoice: {applied_rate:.1f}%."
        if applied_rate is not None
        else ""
    )
    return MismatchResult(
        mismatch_type=MismatchType.HSN_RATE_ISSUE,
        severity=MismatchSeverity.LOW,
        decision_what=(
            f"Invoice {invoice_number}: HSN/SAC code is missing ({source})"
        ),
        decision_why=(
            f"The invoice row does not carry an HSN/SAC code.{rate_note} "
            f"Missing HSN on B2B invoices can attract scrutiny during GST "
            f"audits; confirm whether the Sales Register export omitted "
            f"the column or the value was never captured."
        ),
        decision_next=(
            "Add the correct HSN/SAC code to the Sales Register / GSTR-1 "
            "line item before filing. If the export dropped the column, "
            "re-export with HSN included."
        ),
        rule_id="G1M_009",
        gst_ref="Section 9 CGST Act / Notification 78/2020-CT",
        details={
            "issue_type": "missing_hsn",
            "invoice_number": invoice_number,
            "hsn": None,
            "source": source,
            "applied_rate": applied_rate,
            "matched_fields": [],
            "differed_fields": ["hsn"],
        },
    )


def _classify_malformed_hsn(
    *,
    invoice_number: str,
    raw_hsn: str,
    source: str,
    applied_rate: float | None,
) -> MismatchResult:
    """G1M9 sub-type — HSN/SAC present but not parseable as digits."""
    rate_note = (
        f" Applied rate on the invoice: {applied_rate:.1f}%."
        if applied_rate is not None
        else ""
    )
    return MismatchResult(
        mismatch_type=MismatchType.HSN_RATE_ISSUE,
        severity=MismatchSeverity.LOW,
        decision_what=(
            f"Invoice {invoice_number}: HSN/SAC value '{raw_hsn}' is "
            f"malformed ({source})"
        ),
        decision_why=(
            f"The HSN/SAC field could not be normalised to a numeric "
            f"code (expected digits only).{rate_note} Common causes include "
            f"Excel float artefacts, dashes/spaces, or placeholder text "
            f"left in the column."
        ),
        decision_next=(
            f"Correct HSN/SAC '{raw_hsn}' to a valid numeric code in the "
            f"Sales Register / GSTR-1 before filing."
        ),
        rule_id="G1M_009",
        gst_ref="Section 9 CGST Act / Notification 78/2020-CT",
        details={
            "issue_type": "malformed_hsn",
            "invoice_number": invoice_number,
            "hsn": raw_hsn,
            "source": source,
            "applied_rate": applied_rate,
            "matched_fields": [],
            "differed_fields": ["hsn"],
        },
    )


def _classify_unknown_hsn(
    *,
    invoice_number: str,
    hsn: str,
    source: str,
    applied_rate: float | None,
) -> MismatchResult:
    """G1M9 sub-type — HSN not present in the local rate reference."""
    rate_note = (
        f" Applied rate on the invoice: {applied_rate:.1f}%."
        if applied_rate is not None
        else ""
    )
    return MismatchResult(
        mismatch_type=MismatchType.HSN_RATE_ISSUE,
        severity=MismatchSeverity.LOW,
        decision_what=(
            f"Invoice {invoice_number}: HSN/SAC '{hsn}' is not in the "
            f"local GST rate reference ({source})"
        ),
        decision_why=(
            f"The HSN/SAC could not be matched to any chapter or heading in "
            f"ReconDesk's rate reference table.{rate_note} This is "
            f"informational — the reference may be incomplete and should be "
            f"periodically refreshed against official CBIC rate notifications. "
            f"It does not by itself prove the HSN is invalid."
        ),
        decision_next=(
            f"Confirm HSN/SAC '{hsn}' against the GST tariff / rate finder. "
            f"If correct, no filing change is needed; consider adding the "
            f"code to the local reference. If wrong, correct the HSN in the "
            f"Sales Register / GSTR-1 before filing."
        ),
        rule_id="G1M_009",
        gst_ref="Section 9 CGST Act / Notification 78/2020-CT",
        details={
            "issue_type": "unknown_hsn",
            "invoice_number": invoice_number,
            "hsn": hsn,
            "source": source,
            "applied_rate": applied_rate,
            "matched_fields": [],
            "differed_fields": ["hsn"],
        },
    )


def _classify_hsn_rate_mismatch(
    *,
    invoice_number: str,
    hsn: str,
    source: str,
    applied_rate: float,
    valid_rates: frozenset[float],
    matched_prefix: str,
) -> MismatchResult:
    """G1M9 sub-type — applied rate not valid for this HSN."""
    valid_str = ", ".join(f"{r:g}%" for r in sorted(valid_rates))
    return MismatchResult(
        mismatch_type=MismatchType.HSN_RATE_ISSUE,
        severity=MismatchSeverity.HIGH,
        decision_what=(
            f"Invoice {invoice_number}: HSN '{hsn}' charged at "
            f"{applied_rate:.1f}% but valid rate(s) for this code are "
            f"{valid_str} ({source})"
        ),
        decision_why=(
            f"Per the local GST rate schedule (matched on prefix "
            f"'{matched_prefix}'), HSN/SAC '{hsn}' does not attract "
            f"{applied_rate:.1f}%. Charging an incorrect rate causes short "
            f"payment of output tax (interest under Section 50, penalties "
            f"under Section 122) or excess collection from customers. "
            f"Refresh the reference against CBIC notifications if the "
            f"schedule has recently changed."
        ),
        decision_next=(
            f"Verify the correct GST rate for HSN '{hsn}' in the latest "
            f"CBIC rate schedule. Correct the tax in the Sales Register "
            f"and amend GSTR-1 / GSTR-3B if the filed rate is wrong."
        ),
        rule_id="G1M_009",
        gst_ref="Section 9 CGST Act / Notification 78/2020-CT",
        details={
            "issue_type": "rate_mismatch",
            "invoice_number": invoice_number,
            "hsn": hsn,
            "source": source,
            "applied_rate": applied_rate,
            "valid_rates": sorted(valid_rates),
            "matched_prefix": matched_prefix,
            "matched_fields": ["hsn"],
            "differed_fields": ["gst_rate"],
        },
    )


def _classify_hsn_digit_length(
    *,
    invoice_number: str,
    hsn: str,
    source: str,
    digit_count: int,
    required_digits: int,
    turnover_tier: str,
) -> MismatchResult:
    """G1M9 sub-type — HSN shorter than turnover-slab reporting length."""
    return MismatchResult(
        mismatch_type=MismatchType.HSN_RATE_ISSUE,
        severity=MismatchSeverity.MEDIUM,
        decision_what=(
            f"Invoice {invoice_number}: HSN '{hsn}' has {digit_count} digit(s); "
            f"minimum {required_digits} expected for turnover tier "
            f"'{turnover_tier}' ({source})"
        ),
        decision_why=(
            f"Notification No. 78/2020-Central Tax (as amended) ties the "
            f"mandatory HSN digit length to aggregate turnover. Tier "
            f"'{turnover_tier}' is configured to require {required_digits} "
            f"digits; this invoice reports {digit_count}. Confirm the "
            f"client's actual preceding-FY turnover slab before treating "
            f"this as a definitive compliance failure — the default tier "
            f"may not match this taxpayer."
        ),
        decision_next=(
            f"Confirm the client's aggregate turnover slab and the HSN "
            f"digit length mandated for the relevant tax period. Update "
            f"HSN '{hsn}' to at least {required_digits} digits in the "
            f"Sales Register / GSTR-1 if required."
        ),
        rule_id="G1M_009",
        gst_ref="Section 9 CGST Act / Notification 78/2020-CT",
        details={
            "issue_type": "hsn_digit_length",
            "invoice_number": invoice_number,
            "hsn": hsn,
            "source": source,
            "digit_count": digit_count,
            "required_digits": required_digits,
            "turnover_tier": turnover_tier,
            "matched_fields": [],
            "differed_fields": ["hsn_length"],
        },
    )


def _hsn_matched_prefix(hsn: str, valid_rates: frozenset[float]) -> str:
    """Best-effort prefix key that produced *valid_rates* (for messaging)."""
    from app.data.hsn_rate_reference import HSN_RATE_MAP

    code = normalise_hsn(hsn) or ""
    for n in range(len(code), 1, -1):
        key = code[:n]
        if HSN_RATE_MAP.get(key) == valid_rates:
            return key
    return code[:2] if len(code) >= 2 else code


def _rate_in_schedule(applied: float, valid: frozenset[float]) -> bool:
    if applied != applied or applied in (float("inf"), float("-inf")):  # NaN / inf
        return False
    return any(abs(applied - v) <= _HSN_RATE_TOLERANCE_PP for v in valid)


def _detect_rate_for_hsn(rec: Mapping[str, Any]) -> float | None:
    """Best-effort GST rate for G1M9 — never raises on bad input."""
    try:
        for key in ("gst_rate", "rate", "tax_rate"):
            v = rec.get(key)
            if v is not None:
                try:
                    r = float(v)
                    if r != r:  # NaN
                        continue
                    if 0.0 < r <= 100.0:
                        return round(r, 2)
                except (TypeError, ValueError):
                    continue

        taxable = _safe_int(rec.get("taxable_amount_paise"))
        total_tax = _safe_int(rec.get("total_tax_paise"))
        if total_tax <= 0:
            total_tax = (
                _safe_int(rec.get("igst_paise"))
                + _safe_int(rec.get("cgst_paise"))
                + _safe_int(rec.get("sgst_paise"))
            )
        if taxable > 0 and total_tax > 0:
            computed = (total_tax / taxable) * 100
            if computed != computed or computed in (float("inf"), float("-inf")):
                return None
            for std in (
                0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 14.0, 18.0, 28.0,
            ):
                if abs(computed - std) <= 0.5:
                    return std
            return round(computed, 2)
    except Exception:  # noqa: BLE001 — defensive; caller logs per-record failures
        return None
    return None


def _raw_hsn_display(raw: object) -> str:
    s = str(raw).strip()
    return s[:80] if len(s) > 80 else s


def _append_hsn_candidate(
    out: list[tuple[str, str | None, float | None, str, str | None, object]],
    *,
    inv: str,
    raw_hsn: object,
    applied_rate: float | None,
    source: str,
) -> None:
    """Append one G1M9 validation target with issue hint."""
    if hsn_raw_is_missing(raw_hsn):
        out.append((inv, None, applied_rate, source, "missing", None))
        return
    normalised = normalise_hsn(raw_hsn)
    if normalised:
        out.append((inv, normalised, applied_rate, source, None, None))
    else:
        out.append((inv, None, applied_rate, source, "malformed", raw_hsn))


def _gstr1_section_carries_hsn(rec: Mapping[str, Any]) -> bool:
    """True when this GSTR-1 row actually carries an HSN value to validate.

    Portal JSON only reports HSN on Table 12. Invoice sections (b2b/b2cl/…)
    never include per-invoice HSN — flagging those as ``missing_hsn`` doubles
    the mismatch count for every filed invoice. Empty HSN-summary stubs are
    also skipped.
    """
    raw = _get_field(rec, "hsn", "hsn_sc", "hsn_code", default=None)
    if raw is not None and not hsn_raw_is_missing(raw):
        return True
    items = rec.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            raw_item = item.get("hsn") or item.get("hsn_sc") or item.get("hsn_code")
            if raw_item is not None and not hsn_raw_is_missing(raw_item):
                return True
    return False


def _iter_hsn_rate_candidates(
    records: list[Mapping[str, Any]] | None,
    *,
    source: str,
) -> list[tuple[str, str | None, float | None, str, str | None, object]]:
    """Yield G1M9 validation targets.

    Each tuple is
    ``(invoice_number, hsn_normalised, applied_rate, source, issue_hint, raw_hsn)``.

    *issue_hint* is ``None`` for normal rows, ``"missing"`` or ``"malformed"``.
    """
    out: list[tuple[str, str | None, float | None, str, str | None, object]] = []
    if not records:
        return out

    for rec in records:
        # GSTR-1 invoice-level sections never carry HSN in the portal schema.
        if source == "gstr1" and not _gstr1_section_carries_hsn(rec):
            continue

        inv = str(
            _get_field(
                rec,
                "invoice_number",
                "invoice_number_normalized",
                default="?",
            )
        ).strip() or "?"

        raw_top = _get_field(rec, "hsn", "hsn_sc", "hsn_code", default=None)
        top_rate = _detect_rate_for_hsn(rec)
        # Skip top-level missing_hsn noise:
        # - Sales Register: pairwise rate issues are G1M5
        # - GSTR-1: HSN often lives on items (Table 12), not the parent row
        if hsn_raw_is_missing(raw_top) and (
            source == "sales_register" or source == "gstr1"
        ):
            pass
        else:
            _append_hsn_candidate(
                out,
                inv=inv,
                raw_hsn=raw_top,
                applied_rate=top_rate,
                source=source,
            )

        items = rec.get("items")
        if isinstance(items, list):
            for idx, item in enumerate(items):
                if not isinstance(item, Mapping):
                    continue
                item_inv = f"{inv}#item{idx + 1}"
                raw_item = item.get("hsn") or item.get("hsn_sc") or item.get("hsn_code")
                # Skip item-level missing HSN noise (same schema limitation).
                if hsn_raw_is_missing(raw_item):
                    continue
                item_rate = _detect_rate_for_hsn(item)
                if item_rate is None and item.get("tax_rate") is not None:
                    try:
                        r = float(item["tax_rate"])
                        if r == r and 0.0 < r <= 100.0:
                            item_rate = round(r, 2)
                    except (TypeError, ValueError):
                        item_rate = None
                _append_hsn_candidate(
                    out,
                    inv=item_inv,
                    raw_hsn=raw_item,
                    applied_rate=item_rate,
                    source=f"{source}_item",
                )

    return out


def _validate_one_hsn_candidate(
    *,
    inv: str,
    hsn: str | None,
    applied_rate: float | None,
    source: str,
    issue_hint: str | None,
    raw_hsn: object,
    turnover_tier: str,
    min_digits: int,
    seen: set[tuple[str, str, str, str]],
    results: list[MismatchResult],
) -> None:
    """Run G1M9 checks for a single candidate; append to *results*."""
    if issue_hint == "missing":
        key = (source, inv, "", "missing_hsn")
        if key not in seen:
            seen.add(key)
            results.append(
                _classify_missing_hsn(
                    invoice_number=inv,
                    source=source,
                    applied_rate=applied_rate,
                )
            )
        return

    if issue_hint == "malformed":
        raw_display = _raw_hsn_display(raw_hsn)
        key = (source, inv, raw_display, "malformed_hsn")
        if key not in seen:
            seen.add(key)
            results.append(
                _classify_malformed_hsn(
                    invoice_number=inv,
                    raw_hsn=raw_display,
                    source=source,
                    applied_rate=applied_rate,
                )
            )
        return

    if not hsn:
        return

    digit_count = len(hsn)
    if digit_count < min_digits:
        key = (source, inv, hsn, "hsn_digit_length")
        if key not in seen:
            seen.add(key)
            results.append(
                _classify_hsn_digit_length(
                    invoice_number=inv,
                    hsn=hsn,
                    source=source,
                    digit_count=digit_count,
                    required_digits=min_digits,
                    turnover_tier=turnover_tier,
                )
            )

    valid_rates = lookup_valid_rates(hsn)
    if valid_rates is None:
        # Local schedule is incomplete — do not flood unknown_hsn for every
        # unlisted heading. Pairwise SR↔GSTR-1 rate issues are G1M5.
        return

    if applied_rate is None:
        return

    # Sales Register rate-vs-schedule checks are too noisy against a partial
    # reference map (hundreds of false G1M9s). Keep schedule rate checks for
    # GSTR-1 HSN summary rows only; invoice-level rate diffs use G1M5.
    if source.startswith("sales_register"):
        return

    if not _rate_in_schedule(applied_rate, valid_rates):
        key = (source, inv, hsn, "rate_mismatch")
        if key not in seen:
            seen.add(key)
            results.append(
                _classify_hsn_rate_mismatch(
                    invoice_number=inv,
                    hsn=hsn,
                    source=source,
                    applied_rate=applied_rate,
                    valid_rates=valid_rates,
                    matched_prefix=_hsn_matched_prefix(hsn, valid_rates),
                )
            )


def validate_hsn_rate_mapping(
    sr_records: list[Mapping[str, Any]] | None = None,
    gstr1_records: list[Mapping[str, Any]] | None = None,
    *,
    turnover_tier: str = DEFAULT_TURNOVER_TIER,
) -> list[MismatchResult]:
    """G1M9 — Validate HSN/SAC codes against the GST rate schedule.

    For each Sales Register / GSTR-1 row (or line item) that carries an
    HSN/SAC code, flags:

    1. **unknown_hsn** (LOW) — code not found in the local reference
       (informational; reference may be incomplete).
    2. **rate_mismatch** (HIGH) — applied GST rate (derived from tax
       amounts, or GSTR-1 ``rate`` / item ``tax_rate``) is not among the
       valid rates for that HSN.
    3. **hsn_digit_length** (MEDIUM) — digit count below the minimum for
       ``turnover_tier`` (default ``upto_5cr`` → 4 digits). Confirm the
       client's actual turnover slab before treating as definitive.

    Parameters
    ----------
    sr_records, gstr1_records
        Parsed invoice (or HSN-summary) records.
    turnover_tier
        ``"upto_5cr"`` or ``"above_5cr"`` — selects required HSN digits.
    """
    results: list[MismatchResult] = []
    min_digits = required_hsn_digits(turnover_tier)

    candidates = (
        _iter_hsn_rate_candidates(sr_records, source="sales_register")
        + _iter_hsn_rate_candidates(gstr1_records, source="gstr1")
    )

    seen: set[tuple[str, str, str, str]] = set()

    for inv, hsn, applied_rate, source, issue_hint, raw_hsn in candidates:
        try:
            _validate_one_hsn_candidate(
                inv=inv,
                hsn=hsn,
                applied_rate=applied_rate,
                source=source,
                issue_hint=issue_hint,
                raw_hsn=raw_hsn,
                turnover_tier=turnover_tier,
                min_digits=min_digits,
                seen=seen,
                results=results,
            )
        except Exception:  # noqa: BLE001 — one bad row must not crash the run
            _log.exception(
                "validate_hsn_rate_mapping: failed on inv=%r hsn=%r source=%s "
                "issue_hint=%s raw_hsn=%r — skipping",
                inv,
                hsn,
                source,
                issue_hint,
                raw_hsn,
            )

    _sev_order = {
        MismatchSeverity.CRITICAL: 0,
        MismatchSeverity.HIGH: 1,
        MismatchSeverity.MEDIUM: 2,
        MismatchSeverity.LOW: 3,
    }
    results.sort(key=lambda r: _sev_order.get(r.severity, 99))

    _log.info(
        "validate_hsn_rate_mapping: %d issues (%d rate, %d unknown, "
        "%d digit-length) tier=%s",
        len(results),
        sum(1 for r in results if r.details.get("issue_type") == "rate_mismatch"),
        sum(1 for r in results if r.details.get("issue_type") == "unknown_hsn"),
        sum(1 for r in results if r.details.get("issue_type") == "hsn_digit_length"),
        turnover_tier,
    )
    return results


def reconcile_hsn_summary(
    gstr1_records_all: Sequence[Mapping[str, Any]],
    outward_records: Sequence[Mapping[str, Any]] | None = None,
    *,
    tolerance_paise: int = AMOUNT_TOLERANCE_PAISE,
) -> list[MismatchResult]:
    """Reconcile GSTR-1 Table 12 HSN summary against underlying transactions.

    Validates:
    1. Table 12 taxable value, IGST, CGST, SGST, Cess reconcile against
       the underlying outward supplies.
    2. Does NOT use HSN 'val' as taxable turnover (avoids false 3B mismatches).
    3. Flags an HSN review finding only if:
       - HSN summary taxable/tax totals disagree with outward supplies beyond tolerance.
       - HSN gross 'val' violates basic GST validation (val < txval).
    """
    results: list[MismatchResult] = []
    hsn_records = [
        r for r in (gstr1_records_all or [])
        if str(r.get("section") or "").lower() == "hsn"
    ]
    if not hsn_records:
        return results

    # Sum Table 12 HSN totals
    hsn_txval = sum(_safe_int(r.get("taxable_amount_paise")) for r in hsn_records)
    hsn_iamt = sum(_safe_int(r.get("igst_paise")) for r in hsn_records)
    hsn_camt = sum(_safe_int(r.get("cgst_paise")) for r in hsn_records)
    hsn_samt = sum(_safe_int(r.get("sgst_paise")) for r in hsn_records)
    hsn_csamt = sum(_safe_int(r.get("cess_paise")) for r in hsn_records)
    hsn_tot_tax = hsn_iamt + hsn_camt + hsn_samt + hsn_csamt

    # Check for invalid gross val (< txval)
    for r in hsn_records:
        txval = _safe_int(r.get("taxable_amount_paise"))
        val = _safe_int(r.get("invoice_value_paise"))
        hsn_code = str(r.get("hsn") or _get_field(r, "hsn_sc", "hsn", default="?"))
        if val > 0 and txval > 0 and val < txval:
            results.append(
                MismatchResult(
                    mismatch_type=MismatchType.RATE_MISMATCH,
                    severity=MismatchSeverity.MEDIUM,
                    decision_what=(
                        f"HSN {hsn_code}: total value ({_rs(val)}) is less than "
                        f"taxable value ({_rs(txval)}) in Table 12 summary."
                    ),
                    decision_why=(
                        "In GST Table 12, invoice value must equal or exceed taxable value "
                        "(invoice value = taxable value + taxes). A lower invoice value indicates "
                        "a data entry error in the HSN summary."
                    ),
                    decision_next=f"Review HSN {hsn_code} line in Table 12 and correct the total value.",
                    rule_id="G1M_009_HSN_VAL_INVALID",
                    details={
                        "hsn": hsn_code,
                        "taxable_value": txval,
                        "invoice_value": val,
                        "issue_type": "hsn_val_below_taxable",
                    },
                )
            )

    if not outward_records:
        return results

    # Sum underlying outward supplies (excluding Table 9 earlier-period amendments and informational sections)
    from app.services.matcher import _is_credit_note
    _excluded = {"nil", "hsn", "doc_issue", "at", "ata", "atadj", "atadja"}
    tx_txval_taxable = 0
    tx_txval_zero = 0
    tx_iamt = 0
    tx_camt = 0
    tx_samt = 0
    tx_csamt = 0

    for r in outward_records:
        sec = str(r.get("section") or "").lower().strip()
        if sec in _excluded:
            continue
        if str(r.get("section") or "").lower() in ("b2ba", "b2cla", "b2csa", "cdnra", "cdnura", "expa") or r.get("is_amendment"):
            continue

        txval = abs(_safe_int(r.get("taxable_amount_paise")))
        iamt = abs(_safe_int(r.get("igst_paise")))
        camt = abs(_safe_int(r.get("cgst_paise")))
        samt = abs(_safe_int(r.get("sgst_paise")))
        csamt = abs(_safe_int(r.get("cess_paise")))

        is_zero_rated = (
            sec in ("exp", "expa")
            or str(r.get("invoice_type") or r.get("document_type") or r.get("doc_type") or "").upper() == "EXPORT"
            or str(r.get("place_of_supply") or "").startswith("96")
        )

        if _is_credit_note(r):
            if is_zero_rated:
                tx_txval_zero -= txval
            else:
                tx_txval_taxable -= txval
            tx_iamt -= iamt
            tx_camt -= camt
            tx_samt -= samt
            tx_csamt -= csamt
        else:
            if is_zero_rated:
                tx_txval_zero += txval
            else:
                tx_txval_taxable += txval
            tx_iamt += iamt
            tx_camt += camt
            tx_samt += samt
            tx_csamt += csamt

    tx_tot_tax = tx_iamt + tx_camt + tx_samt + tx_csamt

    # Table 12 HSN summary in GSTR-1 may be reported covering either:
    # 1. Taxable outward supplies (aligning with GSTR-3B Table 3.1(a)), or
    # 2. Total outward supplies including zero-rated exports.
    diff_taxable = abs(hsn_txval - tx_txval_taxable)
    diff_total = abs(hsn_txval - (tx_txval_taxable + tx_txval_zero))
    txval_diff = min(diff_taxable, diff_total)
    tax_diff = abs(hsn_tot_tax - tx_tot_tax)
    tx_best_matched = tx_txval_taxable if diff_taxable <= diff_total else (tx_txval_taxable + tx_txval_zero)

    if txval_diff > tolerance_paise or tax_diff > tolerance_paise:
        results.append(
            MismatchResult(
                mismatch_type=MismatchType.AMOUNT_MISMATCH,
                severity=MismatchSeverity.HIGH,
                decision_what=(
                    f"Table 12 HSN summary taxable value ({_rs(hsn_txval)}) differs "
                    f"from outward transactions ({_rs(tx_best_matched)}) by {_rs(txval_diff)}."
                ),
                decision_why=(
                    "The consolidated HSN summary in GSTR-1 Table 12 must reconcile with the "
                    "taxable value and tax amounts reported across Tables 4-10. Discrepancies "
                    "may trigger GST notice ASMT-10."
                ),
                decision_next="Reconcile HSN summary item lines against sales register invoices and amend Table 12.",
                rule_id="G1M_009_HSN_SUMMARY_MISMATCH",
                details={
                    "hsn_taxable": hsn_txval,
                    "transaction_taxable": tx_best_matched,
                    "taxable_diff": txval_diff,
                    "hsn_tax": hsn_tot_tax,
                    "transaction_tax": tx_tot_tax,
                    "tax_diff": tax_diff,
                    "issue_type": "hsn_summary_mismatch",
                },
            )
        )

    return results


# ══════════════════════════════════════════════════════════════════════════════
# G1M10 — Documents Issued Summary (GSTR-1 Table 13)
# ══════════════════════════════════════════════════════════════════════════════

# Table 13 document buckets used for period-level series summaries.
_TABLE13_TAX_INVOICE = "TAX_INVOICE"
_TABLE13_CREDIT_NOTE = "CREDIT_NOTE"
_TABLE13_DEBIT_NOTE = "DEBIT_NOTE"
_TABLE13_DELIVERY_CHALLAN = "DELIVERY_CHALLAN"
_TABLE13_RECEIPT_VOUCHER = "RECEIPT_VOUCHER"
_TABLE13_PAYMENT_VOUCHER = "PAYMENT_VOUCHER"
_TABLE13_REFUND_VOUCHER = "REFUND_VOUCHER"

# Aggregate / non-document rows — never contribute to Table 13 series.
_TABLE13_SKIP_TYPES: frozenset[str] = frozenset({
    "HSN_SUMMARY", "NIL_RATED", "EXEMPT", "NON_GST", "ADVANCES",
    "NIL_EXEMPT", "HSN",
})

_TABLE13_LABELS: dict[str, str] = {
    _TABLE13_TAX_INVOICE: "Tax invoices (outward supply)",
    _TABLE13_CREDIT_NOTE: "Credit notes",
    _TABLE13_DEBIT_NOTE: "Debit notes",
    _TABLE13_DELIVERY_CHALLAN: "Delivery challans",
    _TABLE13_RECEIPT_VOUCHER: "Receipt vouchers",
    _TABLE13_PAYMENT_VOUCHER: "Payment vouchers",
    _TABLE13_REFUND_VOUCHER: "Refund vouchers",
}


def _record_doc_type_raw(rec: Mapping[str, Any]) -> str:
    """Best-effort document/invoice type string from a parsed record."""
    for key in ("document_type", "invoice_type", "doc_type"):
        v = rec.get(key)
        if v is None:
            continue
        s = str(v).strip().upper()
        if s:
            return s
    return ""


def _map_to_table13_doc_type(rec: Mapping[str, Any]) -> str | None:
    """Map a Sales Register / GSTR-1 record to a Table 13 document bucket.

    Returns ``None`` for aggregate / non-document rows that must not enter
    the documents-issued summary.
    """
    raw = _record_doc_type_raw(rec)
    if not raw or raw in _TABLE13_SKIP_TYPES:
        return None

    if raw in {"CREDIT_NOTE", "C"} or "CREDIT" in raw:
        return _TABLE13_CREDIT_NOTE
    if raw in {"DEBIT_NOTE", "D"} or "DEBIT" in raw:
        return _TABLE13_DEBIT_NOTE
    if "CHALLAN" in raw or "DELIVERY" in raw:
        return _TABLE13_DELIVERY_CHALLAN
    if "RECEIPT" in raw:
        return _TABLE13_RECEIPT_VOUCHER
    if "PAYMENT" in raw:
        return _TABLE13_PAYMENT_VOUCHER
    if "REFUND" in raw:
        return _TABLE13_REFUND_VOUCHER

    # Tax invoices — B2B / B2C / Export / generic INVOICE
    if raw in {
        "B2B", "B2C", "B2C_LARGE", "B2C_SMALL", "B2CL", "B2CS",
        "EXPORT", "INVOICE", "TAX_INVOICE", "SALES",
    }:
        return _TABLE13_TAX_INVOICE

    # Unknown but present type — treat as tax invoice (books sales default)
    return _TABLE13_TAX_INVOICE


def _record_has_cancellation_marker(rec: Mapping[str, Any]) -> bool | None:
    """Return True/False when a cancel flag is present; None if unknown.

    Sales Register exports typically lack a cancelled/status column. We only
    treat an explicit marker as determinable — never infer cancellation from
    credit notes or series gaps.
    """
    for key in (
        "cancelled", "is_cancelled", "is_cancel", "cancel",
        "status", "invoice_status", "document_status",
    ):
        if key not in rec:
            continue
        v = rec.get(key)
        if v is None:
            continue
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if not s or s in {"nan", "none", "null", "na", "n/a", "-"}:
            continue
        if s in {"cancelled", "canceled", "cancel", "yes", "y", "true", "1"}:
            return True
        if s in {"active", "issued", "no", "n", "false", "0", "valid"}:
            return False
        # Status column present but not interpretable as cancel flag
        return None
    return None


def _classify_docs_issued_summary(
    *,
    series_count: int,
    document_types: list[str],
    cancellations_determinable: bool,
) -> MismatchResult:
    types_str = ", ".join(document_types) if document_types else "(none)"
    return MismatchResult(
        mismatch_type=MismatchType.DOCUMENTS_ISSUED_SUMMARY,
        severity=MismatchSeverity.LOW,
        decision_what=(
            f"Table 13 documents issued summary computed for "
            f"{series_count} series across: {types_str}"
        ),
        decision_why=(
            "GSTR-1 Table 13 requires a period summary of documents issued "
            "(opening/closing serial, total issued, cancelled, net issued) "
            "by document type. This informational flag confirms the summary "
            "was derived from the Sales Register series."
        ),
        decision_next=(
            "Review the Table 13 – Documents Issued Summary panel and "
            "cross-check opening/closing serials and counts against the "
            "filed GSTR-1 doc_issue section before submission."
        ),
        rule_id="G1M_010",
        gst_ref="GSTR-1 Table 13 / Rule 46 CGST Rules",
        details={
            "issue_type": "summary_computed",
            "series_count": series_count,
            "document_types": document_types,
            "cancellations_determinable": cancellations_determinable,
            "matched_fields": [],
            "differed_fields": [],
        },
    )


def _classify_docs_cancellations_unknown(
    *,
    series_count: int,
) -> MismatchResult:
    return MismatchResult(
        mismatch_type=MismatchType.DOCUMENTS_ISSUED_SUMMARY,
        severity=MismatchSeverity.LOW,
        decision_what=(
            "Unable to determine cancelled document counts for Table 13 "
            f"({series_count} series)"
        ),
        decision_why=(
            "The Sales Register has no reliable cancelled/status indicator "
            "(cancelled, is_cancelled, or equivalent). Cancellation counts "
            "must not be guessed from credit notes or series gaps — those "
            "are separate reconciliation signals (G1M8)."
        ),
        decision_next=(
            "Enter cancelled counts manually from the books / GSTR-1 "
            "doc_issue section, or re-export the Sales Register with a "
            "cancellation status column if available."
        ),
        rule_id="G1M_010",
        gst_ref="GSTR-1 Table 13 / Rule 46 CGST Rules",
        details={
            "issue_type": "cancellations_unknown",
            "series_count": series_count,
            "cancellations_determinable": False,
            "matched_fields": [],
            "differed_fields": ["cancelled"],
        },
    )


def _classify_docs_span_skipped(
    *,
    document_type: str,
    series_prefix: str,
    span: int,
    total_issued: int,
) -> MismatchResult:
    prefix_label = series_prefix if series_prefix else "(numeric)"
    return MismatchResult(
        mismatch_type=MismatchType.DOCUMENTS_ISSUED_SUMMARY,
        severity=MismatchSeverity.LOW,
        decision_what=(
            f"Table 13 series '{prefix_label}' ({document_type}): numeric "
            f"span {span} exceeds safe bound — range-derived checks skipped"
        ),
        decision_why=(
            f"Opening/closing serials span {span} while only {total_issued} "
            f"records are present. Building a full numeric range for this "
            f"series would risk memory exhaustion (same class of failure "
            f"as the G1M8 OOM guard). Opening/closing and issued counts "
            f"are still reported from actual records."
        ),
        decision_next=(
            "Verify invoice numbering formats are consistent within this "
            "series. Mixed formats (e.g. RD2026273001 vs RD3002) often "
            "share a prefix but are not a continuous sequence."
        ),
        rule_id="G1M_010",
        gst_ref="GSTR-1 Table 13 / Rule 46 CGST Rules",
        details={
            "issue_type": "span_skipped",
            "document_type": document_type,
            "series_prefix": series_prefix,
            "span": span,
            "total_issued": total_issued,
            "max_span": _MAX_SERIES_NUMERIC_SPAN,
            "matched_fields": [],
            "differed_fields": ["series_span"],
        },
    )


def summarize_documents_issued(
    sr_records: list[Mapping[str, Any]] | None = None,
    gstr1_records: list[Mapping[str, Any]] | None = None,
    *,
    gstr1_doc_issue: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[MismatchResult]]:
    """G1M10 — Build GSTR-1 Table 13 documents-issued summary from books.

    Groups Sales Register (and optionally GSTR-1) records by Table 13
    document type, then by invoice series (reusing G1M8's
    ``_split_invoice_number`` + ``_MAX_SERIES_NUMERIC_SPAN`` guard).

    For each series reports:
    - opening / closing serial (from actual min/max numeric tails)
    - total issued (record count)
    - cancelled (only when an explicit cancel marker exists; else ``None``)
    - net issued (issued − cancelled when known, else issued)

    Returns
    -------
    (summary_dict, mismatch_results)
        ``summary_dict`` is JSON-serialisable for the API
        ``documents_issued`` field. ``mismatch_results`` are LOW-severity
        G1M10 informational flags.
    """
    results: list[MismatchResult] = []
    empty_summary: dict[str, Any] = {
        "source": "sales_register",
        "cancellations_determinable": False,
        "series": [],
        "by_document_type": {},
        "gstr1_doc_issue_present": bool(gstr1_doc_issue),
    }

    # Prefer Sales Register as the books source of truth for Table 13.
    # Fall back to invoice-level GSTR-1 only when SR is empty.
    primary = list(sr_records or [])
    source = "sales_register"
    if not primary:
        primary = [
            r for r in (gstr1_records or [])
            if _map_to_table13_doc_type(r) is not None
        ]
        source = "gstr1" if primary else "sales_register"

    if not primary:
        return empty_summary, results

    # Group: document_type → series_prefix → list[(seq, inv_raw, cancelled?)]
    grouped: dict[str, dict[str, list[tuple[int, str, bool | None]]]] = {}
    cancel_markers_seen = 0

    for rec in primary:
        doc_type = _map_to_table13_doc_type(rec)
        if doc_type is None:
            continue
        inv_raw = str(
            _get_field(
                rec, "invoice_number", "invoice_number_normalized", default="",
            )
        ).strip()
        if not inv_raw:
            continue
        split = _split_invoice_number(inv_raw)
        if split is None:
            continue
        prefix, num = split
        cancelled = _record_has_cancellation_marker(rec)
        if cancelled is not None:
            cancel_markers_seen += 1
        grouped.setdefault(doc_type, {}).setdefault(prefix, []).append(
            (num, inv_raw, cancelled)
        )

    series_rows: list[dict[str, Any]] = []
    by_doc: dict[str, dict[str, Any]] = {}

    for doc_type, series_map in sorted(grouped.items()):
        doc_issued = 0
        doc_cancelled: int | None = 0 if cancel_markers_seen > 0 else None
        for prefix, entries in sorted(series_map.items()):
            if not entries:
                continue
            entries_sorted = sorted(entries, key=lambda e: e[0])
            nums = [e[0] for e in entries_sorted]
            series_min = nums[0]
            series_max = nums[-1]
            opening_inv = entries_sorted[0][1]
            closing_inv = entries_sorted[-1][1]
            total_issued = len(entries)

            # Cancelled count only when every row in this series has a marker
            markers = [e[2] for e in entries]
            if all(m is not None for m in markers):
                cancelled_count: int | None = sum(1 for m in markers if m)
            else:
                cancelled_count = None

            span = series_max - series_min
            span_ok = span <= _MAX_SERIES_NUMERIC_SPAN
            expected_count: int | None = None
            if span_ok:
                # Inclusive span of serial numbers — O(1), never materialise
                # the full range as a set (G1M8 OOM lesson).
                expected_count = span + 1
            else:
                results.append(
                    _classify_docs_span_skipped(
                        document_type=doc_type,
                        series_prefix=prefix,
                        span=span,
                        total_issued=total_issued,
                    )
                )

            net_issued = (
                total_issued - cancelled_count
                if cancelled_count is not None
                else total_issued
            )

            series_rows.append({
                "document_type": doc_type,
                "document_type_label": _TABLE13_LABELS.get(doc_type, doc_type),
                "series_prefix": prefix,
                "opening_number": opening_inv,
                "closing_number": closing_inv,
                "opening_seq": series_min,
                "closing_seq": series_max,
                "total_issued": total_issued,
                "cancelled": cancelled_count,
                "net_issued": net_issued,
                "span": span,
                "span_bounded": span_ok,
                "expected_serial_count": expected_count,
            })

            doc_issued += total_issued
            if doc_cancelled is not None and cancelled_count is not None:
                doc_cancelled += cancelled_count
            elif cancelled_count is None:
                doc_cancelled = None

        by_doc[doc_type] = {
            "document_type": doc_type,
            "document_type_label": _TABLE13_LABELS.get(doc_type, doc_type),
            "total_issued": doc_issued,
            "cancelled": doc_cancelled,
            "net_issued": (
                doc_issued - doc_cancelled
                if doc_cancelled is not None
                else doc_issued
            ),
            "series_count": len(series_map),
        }

    cancellations_determinable = cancel_markers_seen > 0 and all(
        row["cancelled"] is not None for row in series_rows
    )

    summary: dict[str, Any] = {
        "source": source,
        "cancellations_determinable": cancellations_determinable,
        "series": series_rows,
        "by_document_type": by_doc,
        "gstr1_doc_issue_present": bool(
            gstr1_doc_issue
            and (
                gstr1_doc_issue.get("doc_det")
                or gstr1_doc_issue.get("docs")
            )
        ),
        "total_series": len(series_rows),
        "total_documents_issued": sum(
            r["total_issued"] for r in series_rows
        ),
    }

    if series_rows:
        results.append(
            _classify_docs_issued_summary(
                series_count=len(series_rows),
                document_types=sorted(by_doc.keys()),
                cancellations_determinable=cancellations_determinable,
            )
        )
        if not cancellations_determinable:
            results.append(
                _classify_docs_cancellations_unknown(
                    series_count=len(series_rows),
                )
            )

    # Optional: note when GSTR-1 doc_issue section is absent (filed summary
    # cannot be cross-checked automatically).
    if series_rows and not summary["gstr1_doc_issue_present"]:
        results.append(
            MismatchResult(
                mismatch_type=MismatchType.DOCUMENTS_ISSUED_SUMMARY,
                severity=MismatchSeverity.LOW,
                decision_what=(
                    "GSTR-1 JSON has no doc_issue (Table 13) section to "
                    "cross-check against the Sales Register summary"
                ),
                decision_why=(
                    "Table 13 is often filed separately in the portal. "
                    "Without a doc_issue block in the uploaded GSTR-1 JSON, "
                    "ReconDesk can only report the books-side summary."
                ),
                decision_next=(
                    "If Table 13 was filed, re-download the GSTR-1 JSON "
                    "including the Documents Issued section and re-run "
                    "reconciliation for an automated cross-check."
                ),
                rule_id="G1M_010",
                gst_ref="GSTR-1 Table 13 / Rule 46 CGST Rules",
                details={
                    "issue_type": "gstr1_doc_issue_absent",
                    "matched_fields": [],
                    "differed_fields": ["doc_issue"],
                },
            )
        )

    _log.info(
        "summarize_documents_issued: %d series, %d docs, "
        "cancellations_determinable=%s source=%s",
        len(series_rows),
        summary["total_documents_issued"],
        cancellations_determinable,
        source,
    )
    return summary, results


# ══════════════════════════════════════════════════════════════════════════════
# G1M11 — Amendment detection (GSTR-1 Tables 9A / 9B / 9C)
# ══════════════════════════════════════════════════════════════════════════════

# Aggregate rows never participate in amendment matching.
_AMENDMENT_SKIP_SECTIONS: frozenset[str] = frozenset({
    "hsn", "nil", "at", "ata", "txpd", "txpda", "doc_issue",
})
_AMENDMENT_SKIP_TYPES: frozenset[str] = frozenset({
    "HSN_SUMMARY", "NIL_RATED", "EXEMPT", "NON_GST", "ADVANCES", "NIL_EXEMPT",
})


def _amendment_invoice_key(rec: Mapping[str, Any]) -> str:
    """Stable invoice key using the same normalisation as matching elsewhere."""
    from app.services.matcher import normalise_inv_no

    raw = (
        rec.get("inum")
        or rec.get("nt_num")
        or rec.get("ntnum")
        or rec.get("credit_note_number")
        or rec.get("note_number")
        or rec.get("invoice_number_raw")
        or rec.get("invoice_number")
        or rec.get("invoice_number_normalized")
        or ""
    )
    return normalise_inv_no(str(raw).strip()) if raw else ""


def _amendment_gstin(rec: Mapping[str, Any]) -> str:
    return clean_buyer_gstin(
        _get_field(rec, "gstin", "recipient_gstin", "ctin", default="")
    ) or ""


def _amendment_table_for(rec: Mapping[str, Any]) -> str:
    """Map a record to GSTR-1 amendment table 9A / 9B / 9C."""
    section = str(rec.get("section") or "").strip().lower()
    inv_type = str(
        rec.get("invoice_type") or rec.get("document_type") or rec.get("doc_type") or ""
    ).strip().upper()

    if section in {"exp", "expa"} or inv_type == "EXPORT":
        return "9C"
    if (
        section in {"cdnr", "cdnra", "cdnur", "cdnura"}
        or inv_type in {"CREDIT_NOTE", "DEBIT_NOTE"}
        or "CREDIT" in inv_type
        or "DEBIT" in inv_type
    ):
        return "9B"
    return "9A"


def _is_amendment_candidate(rec: Mapping[str, Any]) -> bool:
    section = str(rec.get("section") or "").strip().lower()
    if section in _AMENDMENT_SKIP_SECTIONS:
        return False
    inv_type = str(
        rec.get("invoice_type") or rec.get("document_type") or ""
    ).strip().upper()
    if inv_type in _AMENDMENT_SKIP_TYPES:
        return False
    return bool(_amendment_invoice_key(rec))


def _field_diffs_for_amendment(
    current: Mapping[str, Any],
    prior: Mapping[str, Any],
    *,
    tolerance_paise: int = AMOUNT_TOLERANCE_PAISE,
) -> list[str]:
    """Return differed field names when current books ≠ prior filed values."""
    differed: list[str] = []

    cur_taxable = _safe_int(current.get("taxable_amount_paise"))
    prior_taxable = _safe_int(prior.get("taxable_amount_paise"))
    if abs(cur_taxable - prior_taxable) > tolerance_paise:
        differed.append("taxable_amount")

    cur_tax = _safe_int(current.get("total_tax_paise"))
    if cur_tax <= 0:
        cur_tax = (
            _safe_int(current.get("igst_paise"))
            + _safe_int(current.get("cgst_paise"))
            + _safe_int(current.get("sgst_paise"))
        )
    prior_tax = _safe_int(prior.get("total_tax_paise"))
    if prior_tax <= 0:
        prior_tax = (
            _safe_int(prior.get("igst_paise"))
            + _safe_int(prior.get("cgst_paise"))
            + _safe_int(prior.get("sgst_paise"))
        )
    if abs(cur_tax - prior_tax) > tolerance_paise:
        differed.append("total_tax")

    cur_gstin = _amendment_gstin(current)
    prior_gstin = _amendment_gstin(prior)
    # Only flag GSTIN change when both sides have a comparable value
    if cur_gstin and prior_gstin and cur_gstin != prior_gstin:
        differed.append("gstin")

    cur_rate = _detect_rate(current)
    prior_rate = _detect_rate(prior)
    if (
        cur_rate is not None
        and prior_rate is not None
        and abs(cur_rate - prior_rate) > 0.5
    ):
        differed.append("gst_rate")

    return differed


def _classify_amendment_skipped() -> MismatchResult:
    return MismatchResult(
        mismatch_type=MismatchType.AMENDMENT_REQUIRED,
        severity=MismatchSeverity.LOW,
        decision_what=(
            "Amendment detection skipped — prior period GSTR-1 not provided"
        ),
        decision_why=(
            "Tables 9A/9B/9C amendments are detected by comparing the current "
            "Sales Register against a previously filed GSTR-1. No prior-period "
            "GSTR-1 JSON was uploaded for this run, so amendment checks were "
            "not performed."
        ),
        decision_next=(
            "Re-run reconciliation and optionally upload the prior period's "
            "filed GSTR-1 JSON to surface invoices that need 9A/9B/9C "
            "amendments this period."
        ),
        rule_id="G1M_011",
        gst_ref="Section 37 CGST Act / GSTR-1 Tables 9A, 9B, 9C",
        details={
            "issue_type": "amendment_detection_skipped",
            "matched_fields": [],
            "differed_fields": [],
        },
    )


def _classify_amendment_required(
    *,
    invoice_number: str,
    amendment_table: str,
    differed_fields: list[str],
    current: Mapping[str, Any],
    prior: Mapping[str, Any],
    issue_type: str = "amendment_required",
    filed_amendment: Mapping[str, Any] | None = None,
) -> MismatchResult:
    table_label = {
        "9A": "Table 9A (B2B / B2CL invoice amendment)",
        "9B": "Table 9B (credit / debit note amendment)",
        "9C": "Table 9C (export invoice amendment)",
    }.get(amendment_table, f"Table {amendment_table}")

    fields_str = ", ".join(differed_fields)
    cur_taxable = _safe_int(current.get("taxable_amount_paise"))
    prior_taxable = _safe_int(prior.get("taxable_amount_paise"))
    filed_taxable = (
        _safe_int(filed_amendment.get("taxable_amount_paise"))
        if filed_amendment is not None
        else None
    )

    severity = (
        MismatchSeverity.HIGH
        if any(f in differed_fields for f in ("taxable_amount", "total_tax", "gstin"))
        else MismatchSeverity.MEDIUM
    )

    if issue_type == "amendment_missing":
        decision_what = (
            f"Invoice {invoice_number}: books differ from prior-period GSTR-1 "
            f"but no {amendment_table} amendment was filed ({fields_str})"
        )
        decision_why = (
            f"This invoice was filed in a prior GSTR-1, and the current Sales "
            f"Register shows different {fields_str} "
            f"(prior {_rs(prior_taxable)} → books {_rs(cur_taxable)}). "
            f"No matching entry was found in the current period's "
            f"b2ba/cdnra/expa tables, so the portal still holds the old figures."
        )
        decision_next = (
            f"File invoice {invoice_number} under GSTR-1 {table_label} for the "
            f"current period with the corrected Sales Register values."
        )
    elif issue_type == "amendment_still_wrong":
        decision_what = (
            f"Invoice {invoice_number}: {amendment_table} amendment filed but "
            f"still does not match books ({fields_str})"
        )
        decision_why = (
            f"Prior GSTR-1 taxable {_rs(prior_taxable)}, current books "
            f"{_rs(cur_taxable)}, filed amendment "
            f"{_rs(filed_taxable) if filed_taxable is not None else '—'}. "
            f"The amendment is present but {fields_str} still differ from the "
            f"Sales Register, so output tax remains misstated."
        )
        decision_next = (
            f"Correct the {table_label} entry for invoice {invoice_number} to "
            f"match the Sales Register, or fix the books if the amendment is "
            f"the intended figure."
        )
    else:
        decision_what = (
            f"Invoice {invoice_number}: values changed vs prior-period "
            f"GSTR-1 — report as {table_label} ({fields_str})"
        )
        decision_why = (
            f"This invoice was filed in a prior GSTR-1, but the current "
            f"Sales Register shows different {fields_str}. "
            f"Prior filed taxable {_rs(prior_taxable)} vs books "
            f"{_rs(cur_taxable)}. Without a {amendment_table} amendment, "
            f"the portal will retain the previously filed figures and "
            f"output tax / ITC may be misstated."
        )
        decision_next = (
            f"Report invoice {invoice_number} under GSTR-1 {table_label} "
            f"for the current filing period with the corrected values, or "
            f"correct the Sales Register if the books change was unintended."
        )

    return MismatchResult(
        mismatch_type=MismatchType.AMENDMENT_REQUIRED,
        severity=severity,
        decision_what=decision_what,
        decision_why=decision_why,
        decision_next=decision_next,
        rule_id="G1M_011",
        gst_ref="Section 37 CGST Act / GSTR-1 Tables 9A, 9B, 9C",
        details={
            "issue_type": issue_type,
            "amendment_table": amendment_table,
            "invoice_number": invoice_number,
            "differed_fields": differed_fields,
            "prior_taxable_paise": prior_taxable,
            "current_taxable_paise": cur_taxable,
            "filed_amendment_taxable_paise": filed_taxable,
            "prior_gstin": _amendment_gstin(prior) or None,
            "current_gstin": _amendment_gstin(current) or None,
            "prior_rate": _detect_rate(prior),
            "current_rate": _detect_rate(current),
            "matched_fields": ["invoice_number"],
        },
    )


def _index_amendment_records(
    records: list[Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    """Index current-period amendment rows by invoice / original invoice key."""
    by_inv: dict[str, Mapping[str, Any]] = {}
    for rec in records or []:
        if not _is_amendment_candidate(rec):
            continue
        keys: list[str] = []
        primary = _amendment_invoice_key(rec)
        if primary:
            keys.append(primary)
        oinum = (
            rec.get("original_invoice_number_raw")
            or rec.get("original_invoice_number")
            or rec.get("oinum")
            or rec.get("ont_num")
            or ""
        )
        if oinum:
            from app.services.matcher import normalise_inv_no, normalize_invoice

            okey = normalise_inv_no(str(oinum).strip())
            if okey and okey not in keys:
                keys.append(okey)
            legacy_okey = normalize_invoice(str(oinum).strip())
            if legacy_okey and legacy_okey not in keys:
                keys.append(legacy_okey)
        for key in keys:
            if key and key not in by_inv:
                by_inv[key] = rec
    return by_inv


def _amendment_table_choice(
    sr_rec: Mapping[str, Any],
    prior: Mapping[str, Any],
    filed: Mapping[str, Any] | None = None,
) -> str:
    tables = {_amendment_table_for(sr_rec), _amendment_table_for(prior)}
    if filed is not None:
        tables.add(_amendment_table_for(filed))
    if "9C" in tables:
        return "9C"
    if "9B" in tables:
        return "9B"
    return "9A"


def detect_amendments(
    sr_records: list[Mapping[str, Any]] | None = None,
    prior_gstr1_records: list[Mapping[str, Any]] | None = None,
    *,
    prior_provided: bool = False,
    current_amendment_records: list[Mapping[str, Any]] | None = None,
    tolerance_paise: int = AMOUNT_TOLERANCE_PAISE,
) -> list[MismatchResult]:
    """G1M11 — Detect invoices that need Tables 9A / 9B / 9C amendments.

    Compares the **current** Sales Register against a **prior period**
    filed GSTR-1. When books differ from the prior filing:

    - No matching current-period amendment (b2ba/cdnra/expa) → flag
      ``amendment_missing``
    - Amendment filed and matches books → silent (correctly amended)
    - Amendment filed but still differs from books → flag
      ``amendment_still_wrong``

    Invoices absent from the prior period are ignored (normal new sales).
    Identical books vs prior values are ignored (no amendment needed).

    When *prior_provided* is False, returns a single LOW INFO note and
    performs no comparison.
    """
    if not prior_provided:
        return [_classify_amendment_skipped()]

    results: list[MismatchResult] = []

    # Index prior GSTR-1 by normalised invoice number (first occurrence wins).
    # Dict size is O(n) on record count — never built from numeric ranges.
    prior_by_inv: dict[str, Mapping[str, Any]] = {}
    for rec in prior_gstr1_records or []:
        if not _is_amendment_candidate(rec):
            continue
        key = _amendment_invoice_key(rec)
        if key and key not in prior_by_inv:
            prior_by_inv[key] = rec

    if not prior_by_inv:
        _log.info("detect_amendments: prior GSTR-1 has no invoice-level rows")
        return results

    filed_by_inv = _index_amendment_records(current_amendment_records)

    seen: set[str] = set()
    for sr_rec in sr_records or []:
        if not _is_amendment_candidate(sr_rec):
            continue
        key = _amendment_invoice_key(sr_rec)
        if not key or key in seen:
            continue
        prior = prior_by_inv.get(key)
        if prior is None:
            continue  # not in prior period → not an amendment

        differed_vs_prior = _field_diffs_for_amendment(
            sr_rec, prior, tolerance_paise=tolerance_paise,
        )
        if not differed_vs_prior:
            continue  # books still match prior — no amendment needed

        seen.add(key)
        inv_display = str(
            _get_field(sr_rec, "invoice_number", "invoice_number_normalized",
                       default=key)
        ).strip() or key

        filed = filed_by_inv.get(key)
        if filed is None:
            results.append(
                _classify_amendment_required(
                    invoice_number=inv_display,
                    amendment_table=_amendment_table_choice(sr_rec, prior),
                    differed_fields=differed_vs_prior,
                    current=sr_rec,
                    prior=prior,
                    issue_type="amendment_missing",
                )
            )
            continue

        differed_vs_filed = _field_diffs_for_amendment(
            sr_rec, filed, tolerance_paise=tolerance_paise,
        )
        if not differed_vs_filed:
            continue  # correctly amended — silent

        results.append(
            _classify_amendment_required(
                invoice_number=inv_display,
                amendment_table=_amendment_table_choice(sr_rec, prior, filed),
                differed_fields=differed_vs_filed,
                current=sr_rec,
                prior=prior,
                issue_type="amendment_still_wrong",
                filed_amendment=filed,
            )
        )

    # Validate current-period filed amendments against prior GSTR-1
    for amend_rec in current_amendment_records or []:
        oinum = (
            amend_rec.get("original_invoice_number_raw")
            or amend_rec.get("original_invoice_number")
            or amend_rec.get("oinum")
            or amend_rec.get("ont_num")
            or ""
        )
        if not oinum:
            continue
        from app.services.matcher import normalise_inv_no, normalize_invoice

        oinum_norm = normalise_inv_no(str(oinum).strip())
        oinum_legacy = normalize_invoice(str(oinum).strip())
        found = (
            (oinum_norm and oinum_norm in prior_by_inv)
            or (oinum_legacy and oinum_legacy in prior_by_inv)
        )
        if not found:
            section = str(amend_rec.get("section") or "B2BA").upper()
            inv_display = str(
                _get_field(
                    amend_rec,
                    "invoice_number",
                    "invoice_number_raw",
                    "inum",
                    "nt_num",
                    default=oinum,
                )
            ).strip() or oinum or "?"
            fp = str(amend_rec.get("filing_period") or amend_rec.get("fp") or "").strip()
            period_prefix = ""
            if len(fp) == 6 and fp.isdigit():
                m = int(fp[:2])
                month_names = [
                    "", "January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December",
                ]
                if 1 <= m <= 12:
                    period_prefix = f"{month_names[m]} "
            elif len(fp) >= 7 and "-" in fp:
                try:
                    dt = date.fromisoformat(fp[:10])
                    period_prefix = f"{dt.strftime('%B')} "
                except Exception:
                    pass

            results.append(
                MismatchResult(
                    mismatch_type=MismatchType.AMENDMENT_REQUIRED,
                    severity=MismatchSeverity.HIGH,
                    decision_what=(
                        f"REVIEW REQUIRED — UNMATCHED / INVALID {section} AMENDMENT: "
                        f"{period_prefix}GSTR-1 references original invoice '{oinum}' "
                        f"which cannot be located in the prior-period GSTR-1."
                    ),
                    decision_why=(
                        f"{period_prefix}GSTR-1 contains a {section} amendment referencing an "
                        "original invoice that cannot be located in the prior-period GSTR-1. "
                        "Table 9 amendment records must correspond to a valid document previously "
                        "reported in an earlier tax period. An amendment referencing a non-existent "
                        "original document may be rejected by GSTN or indicate an erroneous original "
                        "invoice number or period reference."
                    ),
                    decision_next=(
                        f"Verify original invoice number {oinum} against the prior period filed "
                        "GSTR-1 and books. If the invoice was reported under a different number or "
                        "GSTIN, file a correction with the accurate original document reference."
                    ),
                    rule_id="G1M_011_UNMATCHED_AMENDMENT",
                    details={
                        "invoice_number": inv_display,
                        "original_invoice_number": oinum,
                        "amendment_table": section,
                        "issue_type": "unmatched_amendment",
                        "taxable_value": _safe_int(amend_rec.get("taxable_amount_paise")),
                        "igst": _safe_int(amend_rec.get("igst_paise")),
                        "cgst": _safe_int(amend_rec.get("cgst_paise")),
                        "sgst": _safe_int(amend_rec.get("sgst_paise")),
                    },
                )
            )

    _sev_order = {
        MismatchSeverity.CRITICAL: 0,
        MismatchSeverity.HIGH: 1,
        MismatchSeverity.MEDIUM: 2,
        MismatchSeverity.LOW: 3,
    }
    results.sort(key=lambda r: _sev_order.get(r.severity, 99))

    _log.info(
        "detect_amendments: %d flags from %d prior invoices vs %d SR rows "
        "(%d current amendments indexed)",
        len(results),
        len(prior_by_inv),
        len(sr_records or []),
        len(filed_by_inv),
    )
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    "MismatchType",
    "MismatchSeverity",
    "MismatchResult",
    "classify_missing_invoice",
    "classify_extra_invoice",
    "classify_amount_mismatch",
    "classify_wrong_classification",
    "classify_rate_mismatch",
    "classify_period_mismatch",
    "classify_invalid_gstin",
    "classify_gstin_mismatch",
    "classify_tax_structure_mismatch",
    "collect_unique_buyer_gstins",
    "clean_buyer_gstin",
    "gstin_format_ok",
    "build_g1m7_mismatches",
    "classify_all_mismatches",
    "check_invoice_series_continuity",
    "validate_hsn_rate_mapping",
    "reconcile_hsn_summary",
    "summarize_documents_issued",
    "detect_amendments",
    # Tolerance constants (overridable by callers)
    "AMOUNT_TOLERANCE_PAISE",
    "AMOUNT_TOLERANCE_PCT",
]
