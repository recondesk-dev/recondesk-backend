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
==== ============================== ===============

This module is **standalone** — it does NOT modify any existing file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping

from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity
from app.services.decision_templates import DecisionOutput

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


class MismatchSeverity(str, Enum):
    """Severity for UI display and triage ordering."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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
        return {
            "mismatch_type": self.mismatch_type.value,
            "mismatch_severity": self.severity.value,
            "decision_what": self.decision_what,
            "decision_why": self.decision_why,
            "decision_next": self.decision_next,
            "decision_rule": self.rule_id,
            "gst_ref": self.gst_ref,
            **self.details,
        }


def _severity_to_confidence(severity: MismatchSeverity) -> str:
    return {
        MismatchSeverity.CRITICAL: "HIGH",
        MismatchSeverity.HIGH: "MEDIUM",
        MismatchSeverity.MEDIUM: "LOW",
        MismatchSeverity.LOW: "LOW",
    }[severity]


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
    inv = str(_get_field(sr_rec, "invoice_number") or "?")
    gstin, recipient_label = _recipient_from_record(
        sr_rec, "gstin", "recipient_gstin",
    )
    taxable = _safe_int(sr_rec.get("taxable_amount_paise"))
    total_tax = _safe_int(sr_rec.get("total_tax_paise"))
    inv_date = _parse_date(sr_rec.get("invoice_date"))

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
    inv = str(_get_field(gstr1_rec, "invoice_number") or "?")
    gstin, recipient_label = _recipient_from_record(
        gstr1_rec, "recipient_gstin", "gstin",
    )
    taxable = _safe_int(gstr1_rec.get("taxable_amount_paise"))
    total_tax = _safe_int(gstr1_rec.get("total_tax_paise"))
    inv_date = _parse_date(gstr1_rec.get("invoice_date"))

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
            "recipient_gstin": gstin,
            "taxable_amount_paise": taxable,
            "total_tax_paise": total_tax,
            "invoice_date": inv_date.isoformat() if inv_date else None,
            "matched_fields": [],
            "differed_fields": ["presence"],
        },
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

    sr_taxable = _safe_int(sr_rec.get("taxable_amount_paise"))
    g1_taxable = _safe_int(gstr1_rec.get("taxable_amount_paise"))
    taxable_diff = abs(sr_taxable - g1_taxable)

    sr_tax = _safe_int(sr_rec.get("total_tax_paise"))
    g1_tax = _safe_int(gstr1_rec.get("total_tax_paise"))
    tax_diff = abs(sr_tax - g1_tax)

    # Within absolute tolerance → not a mismatch
    if taxable_diff <= tolerance_paise and tax_diff <= tolerance_paise:
        return None

    # Check percentage tolerance (use the larger base for percentage calc)
    base_taxable = max(abs(sr_taxable), abs(g1_taxable), 1)
    base_tax = max(abs(sr_tax), abs(g1_tax), 1)
    taxable_pct = taxable_diff / base_taxable
    tax_pct = tax_diff / base_tax

    if taxable_pct <= tolerance_pct and tax_pct <= tolerance_pct:
        return None

    # Determine which field(s) differ
    differed: list[str] = []
    diff_parts: list[str] = []
    if taxable_diff > tolerance_paise and taxable_pct > tolerance_pct:
        differed.append("taxable_amount")
        diff_parts.append(
            f"taxable value differs by {_rs(taxable_diff)} "
            f"({_pct(taxable_diff, base_taxable)})"
        )
    if tax_diff > tolerance_paise and tax_pct > tolerance_pct:
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
            f"Invoice {inv}: {'; '.join(diff_parts)}"
        ),
        decision_why=(
            f"Sales Register shows taxable value {_rs(sr_taxable)} / tax "
            f"{_rs(sr_tax)}, but GSTR-1 shows {_rs(g1_taxable)} / "
            f"{_rs(g1_tax)}. The mismatch may result in short or excess "
            f"payment of output tax, attracting interest under Section 50."
        ),
        decision_next=(
            f"Compare invoice {inv} against the original document. Amend "
            f"GSTR-1 or correct the Sales Register to align the values. If a "
            f"credit/debit note was issued, ensure it is reported separately."
        ),
        rule_id="G1M_003",
        details={
            "invoice_number": inv,
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
    taxable = _safe_int(rec.get("taxable_amount_paise"))
    total_tax = _safe_int(rec.get("total_tax_paise"))
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
    """Parse ``"MMYYYY"``, ``"MM-YYYY"``, ``"MM/YYYY"`` to first-of-month date."""
    raw = raw.strip().replace("-", "").replace("/", "")
    if len(raw) == 6 and raw.isdigit():
        try:
            month = int(raw[:2])
            year = int(raw[2:])
            if 1 <= month <= 12:
                return date(year, month, 1)
        except ValueError:
            pass
    return None


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

    # G1M3–G1M6 — Matched-pair rules
    for sr_rec, g1_rec in matched_pairs or []:
        # G1M3 — Amount mismatch
        amt = classify_amount_mismatch(
            sr_rec, g1_rec,
            tolerance_paise=amount_tolerance_paise,
            tolerance_pct=amount_tolerance_pct,
        )
        if amt is not None:
            results.append(amt)

        # G1M4 — Wrong classification
        cls = classify_wrong_classification(sr_rec, g1_rec)
        if cls is not None:
            results.append(cls)

        # G1M5 — Rate mismatch
        rate = classify_rate_mismatch(sr_rec, g1_rec)
        if rate is not None:
            results.append(rate)

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
    "classify_all_mismatches",
    # Tolerance constants (overridable by callers)
    "AMOUNT_TOLERANCE_PAISE",
    "AMOUNT_TOLERANCE_PCT",
]
