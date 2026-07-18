"""
GSTR-1 vs GSTR-3B tie-out reconciliation.

Aggregates invoice-level GSTR-1 records by tax-type and rate, then compares
the totals against the summary figures declared in GSTR-3B Table 3.1
(outward supply details).  Flags any variance that exceeds a configurable
tolerance (₹1 rounding by default).

Output uses the same ``MismatchResult`` / WHAT-WHY-NEXT contract as
``app.rules.gstr1_mismatch_rules`` for seamless Decision Layer integration.

**Standalone module — does NOT modify any existing file.**
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from app.rules.gstr1_mismatch_rules import (
    MismatchResult,
    MismatchSeverity,
    _rs,
    _safe_int,
)

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

# Default absolute tolerance in paise (₹1) — amounts within this are treated
# as rounding and NOT flagged.
DEFAULT_TOLERANCE_PAISE: int = 100

# GSTR-1 sections that map to GSTR-3B Table 3.1(a) "Outward taxable supplies
# (other than zero rated, nil rated and exempted)".
_TAXABLE_SUPPLY_SECTIONS: frozenset[str] = frozenset({
    "b2b", "b2ba",          # B2B invoices (& amendments)
    "b2cl", "b2cla",        # B2C-Large invoices (& amendments)
    "b2cs", "b2csa",        # B2C-Small (& amendments)
})

# Sections that map to GSTR-3B Table 3.1(b) "Outward taxable supplies
# (zero rated)".
_ZERO_RATED_SECTIONS: frozenset[str] = frozenset({
    "exp", "expa",          # Exports (& amendments)
})

# Sections that represent credit/debit notes — these REDUCE liability.
_CDN_SECTIONS: frozenset[str] = frozenset({
    "cdnr", "cdnra",        # Credit/debit notes registered (& amendments)
    "cdnur", "cdnura",      # Credit/debit notes unregistered (& amendments)
})

# Sections excluded from the outward-supply tie-out (informational only).
_EXCLUDED_SECTIONS: frozenset[str] = frozenset({
    "nil", "hsn", "doc_issue", "at", "ata", "atadj", "atadja",
})


# ══════════════════════════════════════════════════════════════════════════════
# Mismatch type for tie-out variances
# ══════════════════════════════════════════════════════════════════════════════

class TieOutVarianceType(str, Enum):
    """Machine-readable variance classification codes."""
    TAXABLE_VALUE = "G1_3B_TAXABLE_VALUE"
    IGST = "G1_3B_IGST"
    CGST = "G1_3B_CGST"
    SGST = "G1_3B_SGST"
    CESS = "G1_3B_CESS"
    TOTAL_TAX = "G1_3B_TOTAL_TAX"


# ══════════════════════════════════════════════════════════════════════════════
# Aggregated GSTR-1 summary
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GSTR1Aggregate:
    """Aggregated totals computed from GSTR-1 invoice-level records.

    All values are in **paise** (1 paise = ₹0.01) for integer arithmetic
    precision — matching the parser convention.
    """
    taxable_value_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    record_count: int = 0

    @property
    def total_tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise

    def to_dict(self) -> dict[str, int]:
        return {
            "taxable_value_paise": self.taxable_value_paise,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "cess_paise": self.cess_paise,
            "total_tax_paise": self.total_tax_paise,
            "record_count": self.record_count,
        }


@dataclass
class GSTR3BSummary:
    """Normalised GSTR-3B Table 3.1(a) outward-supply figures.

    All values are in **paise**. The GSTR-3B parser outputs rupees (float);
    callers must convert before constructing this.
    """
    taxable_value_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0

    @property
    def total_tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise

    def to_dict(self) -> dict[str, int]:
        return {
            "taxable_value_paise": self.taxable_value_paise,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "cess_paise": self.cess_paise,
            "total_tax_paise": self.total_tax_paise,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Aggregation
# ══════════════════════════════════════════════════════════════════════════════

def aggregate_gstr1(
    records: Sequence[Mapping[str, Any]],
    *,
    include_cdn: bool = True,
    include_zero_rated: bool = True,
) -> GSTR1Aggregate:
    """Sum GSTR-1 invoice-level records into an aggregate total.

    Parameters
    ----------
    records : Sequence[Mapping]
        Parsed GSTR-1 records (from ``gstr1_parser.parse_gstr1``).
    include_cdn : bool
        If True (default), credit/debit note sections (cdnr/cdnur) are
        subtracted from the total. Set to False to compare invoices only.
    include_zero_rated : bool
        If True (default), export/zero-rated sections are included.

    Returns
    -------
    GSTR1Aggregate
        Aggregated totals in paise.
    """
    agg = GSTR1Aggregate()

    for rec in records:
        section = str(rec.get("section", "")).lower().strip()

        # Skip informational-only sections
        if section in _EXCLUDED_SECTIONS:
            continue

        # Determine inclusion
        if section in _CDN_SECTIONS:
            if not include_cdn:
                continue
            sign = -1  # CDNs reduce liability
        elif section in _ZERO_RATED_SECTIONS:
            if not include_zero_rated:
                continue
            sign = 1
        elif section in _TAXABLE_SUPPLY_SECTIONS:
            sign = 1
        else:
            # Unknown section — include with positive sign, log warning
            _log.debug(
                "gstr1_vs_3b: unknown section %r in record %s, including as positive",
                section, rec.get("invoice_number", "?"),
            )
            sign = 1

        agg.taxable_value_paise += sign * _safe_int(rec.get("taxable_amount_paise"))
        agg.igst_paise += sign * _safe_int(rec.get("igst_paise"))
        agg.cgst_paise += sign * _safe_int(rec.get("cgst_paise"))
        agg.sgst_paise += sign * _safe_int(rec.get("sgst_paise"))
        agg.cess_paise += sign * _safe_int(rec.get("cess_paise"))
        agg.record_count += 1

    return agg


def aggregate_gstr1_by_rate(
    records: Sequence[Mapping[str, Any]],
) -> dict[float | None, GSTR1Aggregate]:
    """Aggregate GSTR-1 records grouped by GST rate.

    Returns a dict keyed by rate (e.g. ``5.0``, ``18.0``) or ``None`` for
    records with no determinable rate.
    """
    by_rate: dict[float | None, GSTR1Aggregate] = {}

    for rec in records:
        section = str(rec.get("section", "")).lower().strip()
        if section in _EXCLUDED_SECTIONS:
            continue

        rate = rec.get("rate")
        if rate is not None:
            try:
                rate = float(rate)
            except (TypeError, ValueError):
                rate = None

        if rate not in by_rate:
            by_rate[rate] = GSTR1Aggregate()

        agg = by_rate[rate]
        sign = -1 if section in _CDN_SECTIONS else 1

        agg.taxable_value_paise += sign * _safe_int(rec.get("taxable_amount_paise"))
        agg.igst_paise += sign * _safe_int(rec.get("igst_paise"))
        agg.cgst_paise += sign * _safe_int(rec.get("cgst_paise"))
        agg.sgst_paise += sign * _safe_int(rec.get("sgst_paise"))
        agg.cess_paise += sign * _safe_int(rec.get("cess_paise"))
        agg.record_count += 1

    return by_rate


# ══════════════════════════════════════════════════════════════════════════════
# GSTR-3B extraction
# ══════════════════════════════════════════════════════════════════════════════

def gstr3b_to_summary(parsed_3b: Mapping[str, Any]) -> GSTR3BSummary:
    """Convert the output of ``gstr3b_parser.parse_gstr3b`` into a
    ``GSTR3BSummary`` with paise values.

    The GSTR-3B parser stores ``outward_supply`` values in **rupees**
    (float). This function multiplies by 100 and rounds to paise.
    """
    osup = parsed_3b.get("outward_supply") or {}
    return GSTR3BSummary(
        taxable_value_paise=_rupees_to_paise(osup.get("taxable_value", 0)),
        igst_paise=_rupees_to_paise(osup.get("igst", 0)),
        cgst_paise=_rupees_to_paise(osup.get("cgst", 0)),
        sgst_paise=_rupees_to_paise(osup.get("sgst", 0)),
        cess_paise=_rupees_to_paise(osup.get("cess", 0)),
    )


def _rupees_to_paise(val: Any) -> int:
    """Convert a rupees value (float/int/str) to integer paise."""
    if val is None:
        return 0
    try:
        return int(round(float(val) * 100))
    except (TypeError, ValueError):
        return 0


# ══════════════════════════════════════════════════════════════════════════════
# Variance detection
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FieldVariance:
    """A single field-level variance between GSTR-1 aggregate and GSTR-3B."""
    field: str                   # e.g. "taxable_value", "igst", "cgst"
    gstr1_paise: int
    gstr3b_paise: int
    diff_paise: int              # gstr1 − gstr3b (positive = over-reported in GSTR-1)
    variance_type: TieOutVarianceType

    @property
    def is_rounding(self) -> bool:
        return abs(self.diff_paise) <= DEFAULT_TOLERANCE_PAISE


def compute_variances(
    gstr1_agg: GSTR1Aggregate,
    gstr3b_summary: GSTR3BSummary,
    *,
    tolerance_paise: int = DEFAULT_TOLERANCE_PAISE,
) -> list[FieldVariance]:
    """Compare GSTR-1 aggregate against GSTR-3B summary; return field-level
    variances that exceed *tolerance_paise*.

    Returns an empty list if everything matches within tolerance.
    """
    checks = [
        ("taxable_value", gstr1_agg.taxable_value_paise, gstr3b_summary.taxable_value_paise, TieOutVarianceType.TAXABLE_VALUE),
        ("igst", gstr1_agg.igst_paise, gstr3b_summary.igst_paise, TieOutVarianceType.IGST),
        ("cgst", gstr1_agg.cgst_paise, gstr3b_summary.cgst_paise, TieOutVarianceType.CGST),
        ("sgst", gstr1_agg.sgst_paise, gstr3b_summary.sgst_paise, TieOutVarianceType.SGST),
        ("cess", gstr1_agg.cess_paise, gstr3b_summary.cess_paise, TieOutVarianceType.CESS),
        ("total_tax", gstr1_agg.total_tax_paise, gstr3b_summary.total_tax_paise, TieOutVarianceType.TOTAL_TAX),
    ]

    variances: list[FieldVariance] = []
    for field_name, g1_val, g3b_val, vtype in checks:
        diff = g1_val - g3b_val
        if abs(diff) > tolerance_paise:
            variances.append(FieldVariance(
                field=field_name,
                gstr1_paise=g1_val,
                gstr3b_paise=g3b_val,
                diff_paise=diff,
                variance_type=vtype,
            ))

    return variances


# ══════════════════════════════════════════════════════════════════════════════
# Decision generation
# ══════════════════════════════════════════════════════════════════════════════

def _variance_to_mismatch(
    v: FieldVariance,
    *,
    ret_period: str = "?",
) -> MismatchResult:
    """Convert a single FieldVariance into a Decision Layer MismatchResult."""
    direction = "over-reported" if v.diff_paise > 0 else "under-reported"
    abs_diff = abs(v.diff_paise)

    field_label = v.field.replace("_", " ").title()

    severity = (
        MismatchSeverity.CRITICAL
        if abs_diff > 50000  # > ₹500
        else MismatchSeverity.HIGH
        if abs_diff > 10000  # > ₹100
        else MismatchSeverity.MEDIUM
    )

    return MismatchResult(
        mismatch_type=_variance_type_to_mismatch_type(v.variance_type),
        severity=severity,
        decision_what=(
            f"GSTR-1 vs GSTR-3B {field_label} variance: "
            f"{_rs(abs_diff)} {direction} in GSTR-1 for {ret_period}"
        ),
        decision_why=(
            f"GSTR-1 total {field_label.lower()} is {_rs(v.gstr1_paise)} but "
            f"GSTR-3B declares {_rs(v.gstr3b_paise)}, a difference of "
            f"{_rs(abs_diff)}. This indicates the tax liability declared in "
            f"GSTR-3B does not match the invoices filed in GSTR-1, which may "
            f"trigger a DRC-01B intimation (liability mismatch) from the department."
        ),
        decision_next=(
            f"Reconcile the {_rs(abs_diff)} {field_label.lower()} difference. "
            f"If GSTR-1 is correct, amend GSTR-3B to match. If GSTR-3B is "
            f"correct, verify that all invoices in GSTR-1 are accurate."
        ),
        rule_id="G1_3B_TIEOUT",
        gst_ref="Section 37/Section 39 CGST Act",
        details={
            "field": v.field,
            "gstr1_paise": v.gstr1_paise,
            "gstr3b_paise": v.gstr3b_paise,
            "diff_paise": v.diff_paise,
            "direction": direction,
            "ret_period": ret_period,
            "matched_fields": ["ret_period"],
            "differed_fields": [v.field],
        },
    )


# Map between the two enum types for MismatchResult reuse
from app.rules.gstr1_mismatch_rules import MismatchType as _MT

_VARIANCE_TO_MISMATCH = {
    TieOutVarianceType.TAXABLE_VALUE: _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.IGST:         _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.CGST:         _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.SGST:         _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.CESS:         _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.TOTAL_TAX:    _MT.AMOUNT_MISMATCH,
}

def _variance_type_to_mismatch_type(vt: TieOutVarianceType) -> _MT:
    return _VARIANCE_TO_MISMATCH[vt]


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TieOutResult:
    """Complete result of a GSTR-1 vs GSTR-3B tie-out comparison.

    Attributes
    ----------
    ret_period : str
        Return period in ``"YYYY-MM"`` format.
    gstr1_aggregate : GSTR1Aggregate
        Aggregated GSTR-1 totals.
    gstr3b_summary : GSTR3BSummary
        GSTR-3B declared totals.
    gstr1_by_rate : dict
        GSTR-1 totals broken down by GST rate.
    variances : list[FieldVariance]
        Field-level variances exceeding tolerance.
    mismatches : list[MismatchResult]
        Decision-layer-compatible mismatch results.
    is_clean : bool
        True if all fields match within tolerance.
    """
    ret_period: str
    gstr1_aggregate: GSTR1Aggregate
    gstr3b_summary: GSTR3BSummary
    gstr1_by_rate: dict[float | None, GSTR1Aggregate]
    variances: list[FieldVariance]
    mismatches: list[MismatchResult]
    is_clean: bool

    def summary_dict(self) -> dict[str, Any]:
        """Flat summary for logging / API response."""
        return {
            "ret_period": self.ret_period,
            "is_clean": self.is_clean,
            "variance_count": len(self.variances),
            "gstr1_record_count": self.gstr1_aggregate.record_count,
            "gstr1": self.gstr1_aggregate.to_dict(),
            "gstr3b": self.gstr3b_summary.to_dict(),
            "gstr1_by_rate": {
                str(rate): agg.to_dict()
                for rate, agg in sorted(
                    self.gstr1_by_rate.items(),
                    key=lambda x: (x[0] is None, x[0] or 0),
                )
            },
            "variances": [
                {
                    "field": v.field,
                    "gstr1": _rs(v.gstr1_paise),
                    "gstr3b": _rs(v.gstr3b_paise),
                    "diff": _rs(v.diff_paise),
                    "direction": "over" if v.diff_paise > 0 else "under",
                }
                for v in self.variances
            ],
        }


def reconcile_gstr1_vs_3b(
    gstr1_records: Sequence[Mapping[str, Any]],
    parsed_gstr3b: Mapping[str, Any],
    *,
    tolerance_paise: int = DEFAULT_TOLERANCE_PAISE,
    include_cdn: bool = True,
    include_zero_rated: bool = True,
) -> TieOutResult:
    """Compare GSTR-1 invoice-level records against GSTR-3B summary.

    This is the primary entry point for the GSTR-1 vs GSTR-3B tie-out.

    Parameters
    ----------
    gstr1_records : Sequence[Mapping]
        Parsed GSTR-1 records (from ``gstr1_parser.parse_gstr1``).
    parsed_gstr3b : Mapping
        Parsed GSTR-3B output (from ``gstr3b_parser.parse_gstr3b``).
    tolerance_paise : int
        Absolute tolerance in paise (default ₹1).  Variances at or below
        this are treated as rounding and NOT flagged.
    include_cdn : bool
        Include credit/debit notes in the GSTR-1 aggregate (default True).
    include_zero_rated : bool
        Include exports/zero-rated in the GSTR-1 aggregate (default True).

    Returns
    -------
    TieOutResult
        Complete comparison result with aggregates, variances, and
        decision-layer-compatible mismatches.
    """
    ret_period = str(parsed_gstr3b.get("ret_period", "?"))

    # Aggregate GSTR-1
    gstr1_agg = aggregate_gstr1(
        gstr1_records,
        include_cdn=include_cdn,
        include_zero_rated=include_zero_rated,
    )
    gstr1_by_rate = aggregate_gstr1_by_rate(gstr1_records)

    # Extract GSTR-3B summary
    gstr3b_summary = gstr3b_to_summary(parsed_gstr3b)

    # Compute variances
    variances = compute_variances(
        gstr1_agg, gstr3b_summary, tolerance_paise=tolerance_paise,
    )

    # Convert to Decision Layer mismatches
    mismatches = [
        _variance_to_mismatch(v, ret_period=ret_period)
        for v in variances
    ]

    is_clean = len(variances) == 0

    _log.info(
        "gstr1_vs_3b: period=%s, gstr1_records=%d, variances=%d, clean=%s",
        ret_period, gstr1_agg.record_count, len(variances), is_clean,
    )

    return TieOutResult(
        ret_period=ret_period,
        gstr1_aggregate=gstr1_agg,
        gstr3b_summary=gstr3b_summary,
        gstr1_by_rate=gstr1_by_rate,
        variances=variances,
        mismatches=mismatches,
        is_clean=is_clean,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    "GSTR1Aggregate",
    "GSTR3BSummary",
    "TieOutResult",
    "TieOutVarianceType",
    "FieldVariance",
    "DEFAULT_TOLERANCE_PAISE",
    "aggregate_gstr1",
    "aggregate_gstr1_by_rate",
    "gstr3b_to_summary",
    "compute_variances",
    "reconcile_gstr1_vs_3b",
]
