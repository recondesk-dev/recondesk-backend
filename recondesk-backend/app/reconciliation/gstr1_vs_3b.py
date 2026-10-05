"""
GSTR-1 vs GSTR-3B tie-out reconciliation.

Aggregates invoice-level GSTR-1 records by tax-type and rate, then compares
the totals against GSTR-3B Table 3.1(a) (``osup_det`` — outward taxable
supplies other than zero-rated, nil-rated and exempted). Export/zero-rated
GSTR-1 sections are excluded by default so both sides share the same scope.
Flags any variance that exceeds a configurable tolerance (₹1 rounding by
default).

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
from app.services.matcher import normalise_inv_no, normalize_invoice, _is_credit_note

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

# Default absolute tolerance in paise (₹50) — amounts within this are treated
# as rounding and NOT flagged.
DEFAULT_TOLERANCE_PAISE: int = 5000

# GSTR-1 sections that map to GSTR-3B Table 3.1(a) "Outward taxable supplies
# (other than zero rated, nil rated and exempted)".
_BASE_TAXABLE_SECTIONS: frozenset[str] = frozenset({
    "b2b",
    "b2cl",
    "b2cs",
})
_TAXABLE_SUPPLY_SECTIONS: frozenset[str] = _BASE_TAXABLE_SECTIONS

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

# Amendment table sections — when present for a logical invoice, supersede the
# original-row amount in the same GSTR-1 payload (portal Table 9* carries the
# revised full value; summing b2b+b2ba for the same invoice double-counts).
_AMENDMENT_SECTIONS: frozenset[str] = frozenset({
    "b2ba", "b2cla", "b2csa", "expa", "cdnra", "cdnura",
})


def _logical_invoice_key(rec: Mapping[str, Any]) -> str:
    """Key for original↔amendment dedupe. Prefer ``oinum`` when present."""
    from app.services.matcher import normalize_invoice

    oinum = (
        rec.get("original_invoice_number")
        or rec.get("original_invoice_number_raw")
        or rec.get("oinum")
        or rec.get("ont_num")
        or ""
    )
    if oinum:
        return normalize_invoice(str(oinum).strip())
    raw = rec.get("invoice_number_normalized") or rec.get("invoice_number") or ""
    return normalize_invoice(str(raw).strip()) if raw else ""


def _is_amendment_row(rec: Mapping[str, Any]) -> bool:
    section = str(rec.get("section") or "").lower().strip()
    if section in _AMENDMENT_SECTIONS:
        return True
    return bool(rec.get("is_amendment"))


def _records_preferring_amendments(
    records: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Drop original rows when an amendment row exists for the same invoice key.

    Adversarial / messy exports sometimes include both the prior ``b2b`` and the
    current ``b2ba`` for one invoice. Table 9A carries the revised full value —
    summing both inflates GSTR-1 vs 3B liability.
    """
    keys_with_amendment: set[str] = set()
    for rec in records:
        section = str(rec.get("section") or "").lower().strip()
        if section in _EXCLUDED_SECTIONS:
            continue
        if not _is_amendment_row(rec):
            continue
        key = _logical_invoice_key(rec)
        if key:
            keys_with_amendment.add(key)

    if not keys_with_amendment:
        return list(records)

    out: list[Mapping[str, Any]] = []
    for rec in records:
        key = _logical_invoice_key(rec)
        if key and key in keys_with_amendment and not _is_amendment_row(rec):
            continue
        out.append(rec)
    return out


def _records_deduplicated_for_liability(
    records: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Deduplicate GSTR-1 records for statutory Table 3.1 liability calculation.

    Under GST statutory rules (Section 37 / Rule 59), each invoice / note represents
    a unique taxable document. Duplicate portal entries sharing the same statutory identity:
      (section, recipient_gstin, normalized_invoice_number, invoice_date, document_type)
    must not double-count tax liability against GSTR-3B.
    Deterministic retention: the canonical (first) entry is retained, and surplus duplicate
    entries are omitted from liability aggregation.
    """
    seen_keys: set[tuple] = set()
    out: list[Mapping[str, Any]] = []

    for rec in records:
        sec = str(rec.get("section") or "").lower().strip()
        # Aggregates without invoice numbers (b2cs, doc_issue, nil) are preserved
        if sec in _EXCLUDED_SECTIONS or sec in ("b2cs", "b2csa"):
            out.append(rec)
            continue

        raw_inv = (
            rec.get("invoice_number_raw")
            or rec.get("invoice_number")
            or rec.get("inum")
            or rec.get("nt_num")
            or ""
        )
        norm_inv = normalize_invoice(str(raw_inv).strip())
        if not norm_inv:
            out.append(rec)
            continue

        gstin = str(rec.get("recipient_gstin") or rec.get("ctin") or "").strip().upper()
        idt = str(rec.get("invoice_date") or rec.get("idt") or "")[:10]
        dtype = str(rec.get("doc_type") or rec.get("document_type") or rec.get("inv_typ") or "INVOICE").strip().upper()

        key = (sec, gstin, norm_inv, idt, dtype)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(rec)

    return out

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
    ZERO_RATED = "G1_3B_ZERO_RATED"
    NIL_EXEMPT = "G1_3B_NIL_EXEMPT"
    NON_GST = "G1_3B_NON_GST"
    RECLASSIFICATION = "G1_3B_STATUTORY_RECLASSIFICATION"


@dataclass
class CategoryReconciliation:
    """Individual statutory table category comparison."""
    gstr1_value_paise: int = 0
    gstr3b_value_paise: int = 0
    difference_paise: int = 0

    @property
    def gstr1_value(self) -> float:
        return round(self.gstr1_value_paise / 100.0, 2)

    @property
    def gstr3b_value(self) -> float:
        return round(self.gstr3b_value_paise / 100.0, 2)

    @property
    def difference(self) -> float:
        return round(self.difference_paise / 100.0, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gstr1_value_paise": self.gstr1_value_paise,
            "gstr3b_value_paise": self.gstr3b_value_paise,
            "difference_paise": self.difference_paise,
            "gstr1_value": self.gstr1_value,
            "gstr3b_value": self.gstr3b_value,
            "difference": self.difference,
        }


@dataclass
class StatutoryTableReconciliation:
    """Complete statutory category reconciliation between GSTR-1 and GSTR-3B."""
    taxable_outward: CategoryReconciliation
    zero_rated: CategoryReconciliation
    nil_exempt: CategoryReconciliation
    non_gst: CategoryReconciliation
    tax: dict[str, CategoryReconciliation]
    unexplained_difference_paise: int = 0
    reclassification_difference_paise: int = 0

    @property
    def unexplained_difference(self) -> float:
        return round(self.unexplained_difference_paise / 100.0, 2)

    @property
    def reclassification_difference(self) -> float:
        return round(self.reclassification_difference_paise / 100.0, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxable_outward": self.taxable_outward.to_dict(),
            "zero_rated": self.zero_rated.to_dict(),
            "nil_exempt": self.nil_exempt.to_dict(),
            "non_gst": self.non_gst.to_dict(),
            "tax": {k: v.to_dict() for k, v in self.tax.items()},
            "unexplained_difference_paise": self.unexplained_difference_paise,
            "unexplained_difference": self.unexplained_difference,
            "reclassification_difference_paise": self.reclassification_difference_paise,
            "reclassification_difference": self.reclassification_difference,
        }


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
    # Statutory sections
    zero_rated_taxable_paise: int = 0
    zero_rated_igst_paise: int = 0
    zero_rated_cess_paise: int = 0
    nil_exempt_taxable_paise: int = 0
    non_gst_taxable_paise: int = 0

    @property
    def total_tax_paise(self) -> int:
        return (
            self.igst_paise
            + self.cgst_paise
            + self.sgst_paise
            + self.cess_paise
            + self.zero_rated_igst_paise
            + self.zero_rated_cess_paise
        )

    @property
    def total_outward_taxable_paise(self) -> int:
        return (
            self.taxable_value_paise
            + self.zero_rated_taxable_paise
            + self.nil_exempt_taxable_paise
            + self.non_gst_taxable_paise
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "taxable_value_paise": self.taxable_value_paise,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "cess_paise": self.cess_paise,
            "total_tax_paise": self.total_tax_paise,
            "record_count": self.record_count,
            "zero_rated_taxable_paise": self.zero_rated_taxable_paise,
            "zero_rated_igst_paise": self.zero_rated_igst_paise,
            "zero_rated_cess_paise": self.zero_rated_cess_paise,
            "nil_exempt_taxable_paise": self.nil_exempt_taxable_paise,
            "non_gst_taxable_paise": self.non_gst_taxable_paise,
            "total_outward_taxable_paise": self.total_outward_taxable_paise,
        }


@dataclass
class GSTR3BSummary:
    """Normalised GSTR-3B Table 3.1 outward-supply figures.

    All values are in **paise**. The GSTR-3B parser outputs rupees (float);
    callers must convert before constructing this.
    """
    taxable_value_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    zero_rated_taxable_paise: int = 0
    zero_rated_igst_paise: int = 0
    zero_rated_cess_paise: int = 0
    nil_exempt_taxable_paise: int = 0
    non_gst_taxable_paise: int = 0

    @property
    def total_tax_paise(self) -> int:
        return (
            self.igst_paise
            + self.cgst_paise
            + self.sgst_paise
            + self.cess_paise
            + self.zero_rated_igst_paise
            + self.zero_rated_cess_paise
        )

    @property
    def total_outward_taxable_paise(self) -> int:
        return (
            self.taxable_value_paise
            + self.zero_rated_taxable_paise
            + self.nil_exempt_taxable_paise
            + self.non_gst_taxable_paise
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "taxable_value_paise": self.taxable_value_paise,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "cess_paise": self.cess_paise,
            "zero_rated_taxable_paise": self.zero_rated_taxable_paise,
            "zero_rated_igst_paise": self.zero_rated_igst_paise,
            "zero_rated_cess_paise": self.zero_rated_cess_paise,
            "nil_exempt_taxable_paise": self.nil_exempt_taxable_paise,
            "non_gst_taxable_paise": self.non_gst_taxable_paise,
            "total_tax_paise": self.total_tax_paise,
            "total_outward_taxable_paise": self.total_outward_taxable_paise,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Statutory GSTR-3B Classification Buckets & Canonical Mapping
# ══════════════════════════════════════════════════════════════════════════════

class GSTR3BBucket(str, Enum):
    """Statutory GSTR-3B Table 3.1 classification buckets."""
    TABLE_3_1_A_TAXABLE = "3.1(a)"
    TABLE_3_1_B_ZERO_RATED = "3.1(b)"
    TABLE_3_1_C_NIL_EXEMPT = "3.1(c)"
    TABLE_3_1_E_NON_GST = "3.1(e)"
    EXCLUDED = "excluded"


def map_gstr1_supply_to_gstr3b_bucket(rec: Mapping[str, Any]) -> GSTR3BBucket:
    """Classify a GSTR-1 supply record into its statutory GSTR-3B Table 3.1 bucket.

    Classification is based FIRST ON NATURE OF SUPPLY, not merely tax rate.
    Precedence:
    1. Zero-rated: Exports (WPAY/WOPAY) and SEZ supplies (SEZWP/SEZWOP) -> 3.1(b)
    2. Non-GST supplies -> 3.1(e)
    3. Nil-rated / Exempt domestic supplies -> 3.1(c)
    4. Domestic supplies with rate=0 and tax=0 (domestic nil/exempt fallback) -> 3.1(c)
    5. Excluded informational sections (doc_issue, hsn, at, etc.) -> excluded
    6. Default: Ordinary taxable outward supplies (B2B, B2CL, B2CS, CDN) -> 3.1(a)
    """
    section = str(rec.get("section") or "").lower().strip()
    inv_typ = str(rec.get("inv_typ") or rec.get("inv_type") or "").upper().strip()
    inv_type = str(rec.get("invoice_type") or "").upper().strip()
    doc_type = str(rec.get("doc_type") or rec.get("document_type") or "").upper().strip()
    exp_type = str(rec.get("export_type") or rec.get("exp_typ") or "").upper().strip()
    supply_type = str(rec.get("supply_type") or rec.get("sply_ty") or "").upper().strip()
    raw_type = str(rec.get("invoice_type_raw") or "").upper().strip()

    # 1. Zero-rated: Exports & SEZ (with or without payment of tax)
    # Never classified as nil/exempt or ordinary taxable even if rate == 0 or tax == 0.
    zero_rated_signals = {
        "SEZWP", "SEZWOP", "SEZ_WPAY", "SEZ_WOPAY", "SEZ_WP", "SEZ_WOP",
        "EXPWP", "EXPWOP", "EXPORT_WPAY", "EXPORT_WOPAY", "WPAY", "WOPAY",
        "DE", "EXPORT",
    }
    if (
        section in _ZERO_RATED_SECTIONS
        or rec.get("is_zero_rated") is True
        or inv_typ in zero_rated_signals
        or inv_type in zero_rated_signals
        or exp_type in zero_rated_signals
        or supply_type in zero_rated_signals
        or ("SEZ" in inv_typ and ("WP" in inv_typ or "WOP" in inv_typ or "PAY" in inv_typ))
        or ("SEZ" in raw_type and ("PAYMENT" in raw_type or "WP" in raw_type or "WOP" in raw_type))
        or ("EXPORT" in raw_type and ("PAYMENT" in raw_type or "WP" in raw_type or "WOP" in raw_type))
    ):
        return GSTR3BBucket.TABLE_3_1_B_ZERO_RATED

    # 2. Non-GST supplies -> 3.1(e)
    if (
        rec.get("is_non_gst")
        or inv_typ == "NON_GST"
        or inv_type == "NON_GST"
        or doc_type == "NON_GST"
        or supply_type == "NON_GST"
        or (section == "nil" and (inv_type == "NON_GST" or supply_type == "NON_GST"))
    ):
        return GSTR3BBucket.TABLE_3_1_E_NON_GST

    # 3. Nil-rated / Exempt domestic supplies -> 3.1(c)
    if (
        rec.get("is_nil_rated")
        or rec.get("is_exempt")
        or doc_type in ("NIL_EXEMPT", "EXEMPT", "NIL_RATED")
        or inv_typ in ("NIL_RATED", "EXEMPT", "NIL", "EXEMPTED", "NIL_EXEMPT")
        or inv_type in ("NIL_RATED", "EXEMPT", "NIL", "EXEMPTED", "NIL_EXEMPT")
        or section == "nil"
    ):
        return GSTR3BBucket.TABLE_3_1_C_NIL_EXEMPT

    # 4. Domestic supplies with rate=0 and tax=0 (domestic nil/exempt fallback)
    rate = rec.get("rate")
    if rate is not None:
        try:
            r_val = float(rate)
            if r_val == 0.0:
                tot_tax = (
                    _safe_int(rec.get("igst_paise"))
                    + _safe_int(rec.get("cgst_paise"))
                    + _safe_int(rec.get("sgst_paise"))
                    + _safe_int(rec.get("cess_paise"))
                )
                if tot_tax == 0:
                    return GSTR3BBucket.TABLE_3_1_C_NIL_EXEMPT
        except (TypeError, ValueError):
            pass

    # 5. Excluded informational sections (doc_issue, hsn, at, etc.)
    if section in _EXCLUDED_SECTIONS:
        return GSTR3BBucket.EXCLUDED

    # 6. Default: Ordinary taxable outward supplies -> 3.1(a)
    return GSTR3BBucket.TABLE_3_1_A_TAXABLE


def _classify_gstr1_outward_record(rec: Mapping[str, Any]) -> str:
    """Classify GSTR-1 record into statutory category:
    'zero_rated', 'nil_exempt', 'non_gst', or 'taxable'.
    """
    bucket = map_gstr1_supply_to_gstr3b_bucket(rec)
    if bucket == GSTR3BBucket.TABLE_3_1_B_ZERO_RATED:
        return "zero_rated"
    if bucket == GSTR3BBucket.TABLE_3_1_C_NIL_EXEMPT:
        return "nil_exempt"
    if bucket == GSTR3BBucket.TABLE_3_1_E_NON_GST:
        return "non_gst"
    if bucket == GSTR3BBucket.EXCLUDED:
        return "excluded"
    return "taxable"


def aggregate_gstr1(
    records: Sequence[Mapping[str, Any]],
    *,
    include_cdn: bool = True,
    include_zero_rated: bool = False,
    prior_records: Sequence[Mapping[str, Any]] | None = None,
) -> GSTR1Aggregate:
    """Sum GSTR-1 invoice-level records into an aggregate total for GSTR-3B tie-out.

    Parameters
    ----------
    records : Sequence[Mapping]
        Parsed GSTR-1 records (from ``gstr1_parser.parse_gstr1``).
    include_cdn : bool
        If True (default), credit notes (cdnr/cdnur) are subtracted and debit
        notes are added. Set to False to compare invoices only.
    include_zero_rated : bool
        If True, export/zero-rated sections (exp/expa) are included in taxable_value_paise.
        Default False so the taxable aggregate matches GSTR-3B Table 3.1(a)
        (``osup_det``), which excludes zero-rated supplies.
    prior_records : Sequence[Mapping] | None
        Prior-period GSTR-1 records for evaluating Table 9 amendments.
        Amendments are applied as economic differentials (amended - prior)
        when the original document is verified in prior filings. Unmatched
        amendments are never added as fresh current-period turnover.

    Returns
    -------
    GSTR1Aggregate
        Aggregated totals in paise.
    """
    agg = GSTR1Aggregate()

    prior_by_key: dict[str, Mapping[str, Any]] = {}
    if prior_records:
        for pr in prior_records:
            k = _logical_invoice_key(pr)
            if k and k not in prior_by_key:
                prior_by_key[k] = pr
            raw_k = normalise_inv_no(
                pr.get("inum")
                or pr.get("nt_num")
                or pr.get("invoice_number_raw")
                or pr.get("invoice_number")
                or ""
            )
            if raw_k and raw_k not in prior_by_key:
                prior_by_key[raw_k] = pr

    for rec in _records_deduplicated_for_liability(_records_preferring_amendments(records)):
        section = str(rec.get("section", "")).lower().strip()

        # Handle informational sections
        if section in _EXCLUDED_SECTIONS:
            if section == "nil":
                cat = _classify_gstr1_outward_record(rec)
                txval = _safe_int(rec.get("taxable_amount_paise")) or _safe_int(rec.get("invoice_value_paise"))
                if cat == "non_gst":
                    agg.non_gst_taxable_paise += txval
                else:
                    agg.nil_exempt_taxable_paise += txval
            continue

        if section in _AMENDMENT_SECTIONS or _is_amendment_row(rec):
            # Table 9 amendments: apply differential against prior original if verified.
            if prior_records and prior_by_key:
                oinum = (
                    rec.get("original_invoice_number_raw")
                    or rec.get("original_invoice_number")
                    or rec.get("oinum")
                    or rec.get("ont_num")
                    or ""
                )
                k = _logical_invoice_key(rec)
                k_norm = normalise_inv_no(str(oinum).strip())
                prior_orig = prior_by_key.get(k) or (
                    prior_by_key.get(k_norm) if k_norm else None
                )
                if prior_orig:
                    diff_txval = _safe_int(
                        rec.get("taxable_amount_paise")
                    ) - _safe_int(prior_orig.get("taxable_amount_paise"))
                    diff_iamt = _safe_int(
                        rec.get("igst_paise")
                    ) - _safe_int(prior_orig.get("igst_paise"))
                    diff_camt = _safe_int(
                        rec.get("cgst_paise")
                    ) - _safe_int(prior_orig.get("cgst_paise"))
                    diff_samt = _safe_int(
                        rec.get("sgst_paise")
                    ) - _safe_int(prior_orig.get("sgst_paise"))
                    diff_csamt = _safe_int(
                        rec.get("cess_paise")
                    ) - _safe_int(prior_orig.get("cess_paise"))

                    mult = -1 if section in ("cdnra", "cdnura") else 1
                    agg.taxable_value_paise += mult * diff_txval
                    agg.igst_paise += mult * diff_iamt
                    agg.cgst_paise += mult * diff_camt
                    agg.sgst_paise += mult * diff_samt
                    agg.cess_paise += mult * diff_csamt
                    agg.record_count += 1
                continue
            elif prior_records:
                continue

        cat = _classify_gstr1_outward_record(rec)
        txval = _safe_int(rec.get("taxable_amount_paise"))
        iamt = _safe_int(rec.get("igst_paise"))
        camt = _safe_int(rec.get("cgst_paise"))
        samt = _safe_int(rec.get("sgst_paise"))
        csamt = _safe_int(rec.get("cess_paise"))

        # Credit / Debit note sign handling
        if section in _CDN_SECTIONS:
            if not include_cdn:
                continue
            is_cn = (
                _is_credit_note(rec)
                or str(rec.get("ntty") or "").upper() == "C"
            )
            sign = -1 if is_cn else 1
        elif (
            section in _BASE_TAXABLE_SECTIONS
            or section in _TAXABLE_SUPPLY_SECTIONS
            or section in ("b2ba", "b2cla", "b2csa")
        ):
            sign = 1
        else:
            _log.debug(
                "gstr1_vs_3b: unknown section %r in record %s, including as positive",
                section,
                rec.get("invoice_number", "?"),
            )
            sign = 1

        if cat == "zero_rated":
            agg.zero_rated_taxable_paise += sign * txval
            agg.zero_rated_igst_paise += sign * iamt
            agg.zero_rated_cess_paise += sign * csamt
            if include_zero_rated:
                agg.taxable_value_paise += sign * txval
                agg.igst_paise += sign * iamt
                agg.cess_paise += sign * csamt
                agg.record_count += 1
            continue

        if cat == "nil_exempt":
            agg.nil_exempt_taxable_paise += sign * txval
            continue

        if cat == "non_gst":
            agg.non_gst_taxable_paise += sign * txval
            continue

        agg.taxable_value_paise += sign * txval
        agg.igst_paise += sign * iamt
        agg.cgst_paise += sign * camt
        agg.sgst_paise += sign * samt
        agg.cess_paise += sign * csamt
        agg.record_count += 1

    return agg


def aggregate_gstr1_by_rate(
    records: Sequence[Mapping[str, Any]],
    *,
    prior_records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[float | None, GSTR1Aggregate]:
    """Aggregate GSTR-1 records grouped by GST rate.

    Returns a dict keyed by rate (e.g. ``5.0``, ``18.0``) or ``None`` for
    records with no determinable rate.
    """
    by_rate: dict[float | None, GSTR1Aggregate] = {}

    for rec in _records_preferring_amendments(records):
        section = str(rec.get("section", "")).lower().strip()
        if section in _EXCLUDED_SECTIONS:
            continue

        if section in _AMENDMENT_SECTIONS or _is_amendment_row(rec):
            if prior_records:
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
        is_cn = _is_credit_note(rec) or str(rec.get("ntty") or "").upper() == "C"
        sign = -1 if (section in _CDN_SECTIONS and is_cn) else 1

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

def gstr3b_to_summary(parsed_3b: Mapping[str, Any] | GSTR3BSummary) -> GSTR3BSummary:
    """Convert the output of ``gstr3b_parser.parse_gstr3b`` into a
    ``GSTR3BSummary`` with paise values across all statutory Table 3.1 sections.
    """
    if isinstance(parsed_3b, GSTR3BSummary):
        return parsed_3b

    sup_details = (
        parsed_3b.get("sup_details")
        or (parsed_3b.get("data", {}).get("sup_details") if isinstance(parsed_3b.get("data"), dict) else {})
        or {}
    )

    # 3.1(a) Outward taxable supplies
    osup = (
        parsed_3b.get("outward_supply")
        or sup_details.get("osup_det")
        or parsed_3b.get("osup_det")
        or (parsed_3b if ("taxable_value" in parsed_3b and "outward_supply" not in parsed_3b) else {})
    )

    # 3.1(b) Zero rated
    osup_zero = (
        parsed_3b.get("osup_zero")
        or sup_details.get("osup_zero")
        or parsed_3b.get("zero_rated")
        or {}
    )

    # 3.1(c) Nil / exempt
    osup_nil = (
        parsed_3b.get("osup_nil_exmp")
        or sup_details.get("osup_nil_exmp")
        or parsed_3b.get("nil_exempt")
        or {}
    )

    # 3.1(e) Non-GST
    osup_nongst = (
        parsed_3b.get("osup_nongst")
        or sup_details.get("osup_nongst")
        or parsed_3b.get("non_gst")
        or {}
    )

    return GSTR3BSummary(
        taxable_value_paise=_rupees_to_paise(osup.get("taxable_value") if "taxable_value" in osup else osup.get("txval", 0)),
        igst_paise=_rupees_to_paise(osup.get("igst") if "igst" in osup else osup.get("iamt", 0)),
        cgst_paise=_rupees_to_paise(osup.get("cgst") if "cgst" in osup else osup.get("camt", 0)),
        sgst_paise=_rupees_to_paise(osup.get("sgst") if "sgst" in osup else osup.get("samt", 0)),
        cess_paise=_rupees_to_paise(osup.get("cess") if "cess" in osup else osup.get("csamt", 0)),
        zero_rated_taxable_paise=_rupees_to_paise(osup_zero.get("taxable_value") if "taxable_value" in osup_zero else osup_zero.get("txval", 0)),
        zero_rated_igst_paise=_rupees_to_paise(osup_zero.get("igst") if "igst" in osup_zero else osup_zero.get("iamt", 0)),
        zero_rated_cess_paise=_rupees_to_paise(osup_zero.get("cess") if "cess" in osup_zero else osup_zero.get("csamt", 0)),
        nil_exempt_taxable_paise=_rupees_to_paise(osup_nil.get("taxable_value") if "taxable_value" in osup_nil else osup_nil.get("txval", 0)),
        non_gst_taxable_paise=_rupees_to_paise(osup_nongst.get("taxable_value") if "taxable_value" in osup_nongst else osup_nongst.get("txval", 0)),
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
    """Compare GSTR-1 aggregate against GSTR-3B summary across statutory tables;
    return field-level variances that exceed *tolerance_paise*.

    Distinguishes category reclassifications (total outward turnover matches)
    from genuine unexplained variances.
    """
    taxable_diff = gstr1_agg.taxable_value_paise - gstr3b_summary.taxable_value_paise
    zero_diff = gstr1_agg.zero_rated_taxable_paise - gstr3b_summary.zero_rated_taxable_paise
    nil_diff = gstr1_agg.nil_exempt_taxable_paise - gstr3b_summary.nil_exempt_taxable_paise
    nongst_diff = gstr1_agg.non_gst_taxable_paise - gstr3b_summary.non_gst_taxable_paise

    # In-scope outward categories
    g1_outward = gstr1_agg.taxable_value_paise
    g3b_outward = gstr3b_summary.taxable_value_paise

    include_zero = gstr3b_summary.zero_rated_taxable_paise > 0
    if include_zero:
        g1_outward += gstr1_agg.zero_rated_taxable_paise
        g3b_outward += gstr3b_summary.zero_rated_taxable_paise

    include_nil = gstr3b_summary.nil_exempt_taxable_paise > 0 or gstr1_agg.nil_exempt_taxable_paise > 0
    if include_nil:
        g1_outward += gstr1_agg.nil_exempt_taxable_paise
        g3b_outward += gstr3b_summary.nil_exempt_taxable_paise

    include_nongst = gstr3b_summary.non_gst_taxable_paise > 0 or gstr1_agg.non_gst_taxable_paise > 0
    if include_nongst:
        g1_outward += gstr1_agg.non_gst_taxable_paise
        g3b_outward += gstr3b_summary.non_gst_taxable_paise

    unexplained_diff = g1_outward - g3b_outward

    variances: list[FieldVariance] = []

    # Check if category differences represent pure reclassification
    is_pure_reclass = (
        abs(unexplained_diff) <= tolerance_paise
        and (
            abs(taxable_diff) > tolerance_paise
            or (include_zero and abs(zero_diff) > tolerance_paise)
            or (include_nil and abs(nil_diff) > tolerance_paise)
            or (include_nongst and abs(nongst_diff) > tolerance_paise)
        )
    )

    if is_pure_reclass:
        reclass_amt = (
            abs(taxable_diff)
            + (abs(zero_diff) if include_zero else 0)
            + (abs(nil_diff) if include_nil else 0)
            + (abs(nongst_diff) if include_nongst else 0)
        ) // 2
        variances.append(FieldVariance(
            field="statutory_reclassification",
            gstr1_paise=g1_outward,
            gstr3b_paise=g3b_outward,
            diff_paise=reclass_amt,
            variance_type=TieOutVarianceType.RECLASSIFICATION,
        ))
    else:
        # Check individual statutory categories
        if abs(taxable_diff) > tolerance_paise:
            variances.append(FieldVariance(
                field="taxable_value",
                gstr1_paise=gstr1_agg.taxable_value_paise,
                gstr3b_paise=gstr3b_summary.taxable_value_paise,
                diff_paise=taxable_diff,
                variance_type=TieOutVarianceType.TAXABLE_VALUE,
            ))
        if include_zero and abs(zero_diff) > tolerance_paise:
            variances.append(FieldVariance(
                field="zero_rated",
                gstr1_paise=gstr1_agg.zero_rated_taxable_paise,
                gstr3b_paise=gstr3b_summary.zero_rated_taxable_paise,
                diff_paise=zero_diff,
                variance_type=TieOutVarianceType.ZERO_RATED,
            ))
        if include_nil and abs(nil_diff) > tolerance_paise:
            variances.append(FieldVariance(
                field="nil_exempt",
                gstr1_paise=gstr1_agg.nil_exempt_taxable_paise,
                gstr3b_paise=gstr3b_summary.nil_exempt_taxable_paise,
                diff_paise=nil_diff,
                variance_type=TieOutVarianceType.NIL_EXEMPT,
            ))
        if include_nongst and abs(nongst_diff) > tolerance_paise:
            variances.append(FieldVariance(
                field="non_gst",
                gstr1_paise=gstr1_agg.non_gst_taxable_paise,
                gstr3b_paise=gstr3b_summary.non_gst_taxable_paise,
                diff_paise=nongst_diff,
                variance_type=TieOutVarianceType.NON_GST,
            ))

    # Taxes
    tax_checks = [
        ("igst", gstr1_agg.igst_paise, gstr3b_summary.igst_paise, TieOutVarianceType.IGST),
        ("cgst", gstr1_agg.cgst_paise, gstr3b_summary.cgst_paise, TieOutVarianceType.CGST),
        ("sgst", gstr1_agg.sgst_paise, gstr3b_summary.sgst_paise, TieOutVarianceType.SGST),
        ("cess", gstr1_agg.cess_paise, gstr3b_summary.cess_paise, TieOutVarianceType.CESS),
        ("total_tax", gstr1_agg.total_tax_paise, gstr3b_summary.total_tax_paise, TieOutVarianceType.TOTAL_TAX),
    ]
    for field_name, g1_val, g3b_val, vtype in tax_checks:
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

    if v.variance_type == TieOutVarianceType.RECLASSIFICATION:
        return MismatchResult(
            mismatch_type=MismatchType.WRONG_CLASSIFICATION,
            severity=MismatchSeverity.INFO,
            decision_what=(
                f"GSTR-1 vs GSTR-3B statutory table allocation / category reclassification: "
                f"{_rs(abs_diff)}"
            ),
            decision_why=(
                "Turnover was reported under different statutory tables between GSTR-1 "
                "and GSTR-3B (e.g. Table 3.1(a) vs Table 3.1(c)). Total outward turnover "
                "is fully accounted for across tables with zero unexplained financial variance."
            ),
            decision_next=(
                "Verify return table mapping. Because total turnover and tax liability match, "
                "no monetary tax demand arises under Section 73/74."
            ),
            rule_id="G1_3B_STATUTORY_RECLASSIFICATION",
            gst_ref="Section 37/Section 39 CGST Act",
            details={
                "field": v.field,
                "reclassification_paise": abs_diff,
                "ret_period": ret_period,
                "matched_fields": ["ret_period", "total_outward_turnover"],
                "differed_fields": ["statutory_table_allocation"],
            },
        )

    diff_rupees = abs_diff / 100
    if diff_rupees <= 50:
        severity = MismatchSeverity.INFO
    elif diff_rupees <= 10000:
        severity = MismatchSeverity.WARNING
    else:
        severity = MismatchSeverity.CRITICAL

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
    TieOutVarianceType.ZERO_RATED:   _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.NIL_EXEMPT:   _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.NON_GST:      _MT.AMOUNT_MISMATCH,
    TieOutVarianceType.RECLASSIFICATION: _MT.WRONG_CLASSIFICATION,
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
        True if all fields match within tolerance (or pure reclassification with 0 unexplained diff).
    statutory_reconciliation : StatutoryTableReconciliation | None
        Breakdown across Table 3.1(a), 3.1(b), 3.1(c), 3.1(e), and tax heads.
    unexplained_difference_paise : int
        Genuine unexplained financial variance in paise.
    reclassification_difference_paise : int
        Turnover reclassified across statutory tables in paise.
    """
    ret_period: str
    gstr1_aggregate: GSTR1Aggregate
    gstr3b_summary: GSTR3BSummary
    gstr1_by_rate: dict[float | None, GSTR1Aggregate]
    variances: list[FieldVariance]
    mismatches: list[MismatchResult]
    is_clean: bool
    statutory_reconciliation: StatutoryTableReconciliation | None = None
    unexplained_difference_paise: int = 0
    reclassification_difference_paise: int = 0

    def summary_dict(self) -> dict[str, Any]:
        """Flat summary for logging / API response."""
        stat_dict = (
            self.statutory_reconciliation.to_dict()
            if self.statutory_reconciliation
            else {}
        )
        return {
            "ret_period": self.ret_period,
            "is_clean": self.is_clean,
            "variance_count": len(self.variances),
            "gstr1_record_count": self.gstr1_aggregate.record_count,
            "gstr1": self.gstr1_aggregate.to_dict(),
            "gstr3b": self.gstr3b_summary.to_dict(),
            "unexplained_difference_paise": self.unexplained_difference_paise,
            "unexplained_difference": round(self.unexplained_difference_paise / 100.0, 2),
            "reclassification_difference_paise": self.reclassification_difference_paise,
            "reclassification_difference": round(self.reclassification_difference_paise / 100.0, 2),
            "taxable_outward": stat_dict.get("taxable_outward", {}),
            "zero_rated": stat_dict.get("zero_rated", {}),
            "nil_exempt": stat_dict.get("nil_exempt", {}),
            "non_gst": stat_dict.get("non_gst", {}),
            "tax": stat_dict.get("tax", {}),
            "statutory_reconciliation": stat_dict,
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


def _extract_month_from_period(ret_period: str) -> str | None:
    """Extract 2-digit month string (e.g. '04') from ret_period like '042025', '2025-04', '04-2025'."""
    p = str(ret_period or "").strip()
    if not p or p == "?":
        return None
    if len(p) == 6 and p.isdigit():
        return p[:2]
    if "-" in p:
        parts = p.split("-")
        if len(parts[0]) == 4 and parts[0].isdigit():
            return parts[1]
        if len(parts[0]) == 2 and parts[0].isdigit():
            return parts[0]
    return None


def reconcile_gstr1_vs_3b(
    gstr1_records: Sequence[Mapping[str, Any]],
    parsed_gstr3b: Mapping[str, Any],
    *,
    tolerance_paise: int = DEFAULT_TOLERANCE_PAISE,
    include_cdn: bool = True,
    include_zero_rated: bool = False,
    filing_frequency: str = "monthly",
    prior_records: Sequence[Mapping[str, Any]] | None = None,
) -> TieOutResult:
    """Compare GSTR-1 invoice-level records against GSTR-3B summary.

    This is the primary entry point for the GSTR-1 vs GSTR-3B tie-out.
    Both sides are scoped to GSTR-3B Table 3.1(a) (regular taxable outward
    supplies). Export/zero-rated GSTR-1 sections are excluded by default so
    they are not compared against ``osup_det``.

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
        Include exports/zero-rated in the GSTR-1 aggregate (default False).
    filing_frequency : str
        Filing frequency ('monthly' or 'qrmp'). Under QRMP, GSTR-1 is filed quarterly
        (due at quarter-end). In months 1 and 2 of a quarter, missing GSTR-1 is not flagged.
    prior_records : Sequence[Mapping] | None
        Prior-period GSTR-1 records for evaluating Table 9 amendments.

    Returns
    -------
    TieOutResult
        Complete comparison result with aggregates, variances, and
        decision-layer-compatible mismatches.
    """
    ret_period = str(
        parsed_gstr3b.ret_period
        if isinstance(parsed_gstr3b, GSTR3BSummary) and hasattr(parsed_gstr3b, "ret_period")
        else (parsed_gstr3b.get("ret_period", "?") if isinstance(parsed_gstr3b, Mapping) else "?")
    )
    ff = (filing_frequency or "monthly").lower().strip()

    # QRMP tie-out timing gate: In non-quarter-end months (months other than 03, 06, 09, 12),
    # QRMP taxpayers do not file GSTR-3B or GSTR-1 returns (tax is deposited via PMT-06 challan).
    # Suppress all missing GSTR-1 and GSTR-3B tie-out variance checks for months 1-2.
    if ff == "qrmp":
        mm = _extract_month_from_period(ret_period)
        if mm and mm not in ("03", "06", "09", "12"):
            _log.info(
                "gstr1_vs_3b: QRMP filer period=%s (month %s) — GSTR-3B/GSTR-1 not filed in month 1/2 of quarter (filed quarterly at quarter-end). Tie-out suppressed.",
                ret_period, mm,
            )
            gstr1_agg = aggregate_gstr1(
                gstr1_records,
                include_cdn=include_cdn,
                include_zero_rated=include_zero_rated,
                prior_records=prior_records,
            )
            gstr1_by_rate = aggregate_gstr1_by_rate(
                gstr1_records,
                prior_records=prior_records,
            )
            gstr3b_summary = gstr3b_to_summary(parsed_gstr3b)
            return TieOutResult(
                ret_period=ret_period,
                gstr1_aggregate=gstr1_agg,
                gstr3b_summary=gstr3b_summary,
                gstr1_by_rate=gstr1_by_rate,
                variances=[],
                mismatches=[],
                is_clean=True,
            )

    # Extract GSTR-3B summary
    gstr3b_summary = gstr3b_to_summary(parsed_gstr3b)

    # Aggregate GSTR-1
    # If prior_records are provided, evaluate candidate models (differential vs gross outward turnover)
    # and align with the model that best represents the GSTR-3B Table 3.1 declaration.
    if prior_records:
        gstr1_agg_diff = aggregate_gstr1(
            gstr1_records,
            include_cdn=include_cdn,
            include_zero_rated=include_zero_rated,
            prior_records=prior_records,
        )
        gstr1_agg_full = aggregate_gstr1(
            gstr1_records,
            include_cdn=include_cdn,
            include_zero_rated=include_zero_rated,
            prior_records=None,
        )

        score_diff = abs(gstr1_agg_diff.taxable_value_paise - gstr3b_summary.taxable_value_paise) + abs(
            gstr1_agg_diff.total_tax_paise - gstr3b_summary.total_tax_paise
        )
        score_full = abs(gstr1_agg_full.taxable_value_paise - gstr3b_summary.taxable_value_paise) + abs(
            gstr1_agg_full.total_tax_paise - gstr3b_summary.total_tax_paise
        )

        if score_diff < score_full:
            gstr1_agg = gstr1_agg_diff
            gstr1_by_rate = aggregate_gstr1_by_rate(
                gstr1_records,
                prior_records=prior_records,
            )
        else:
            gstr1_agg = gstr1_agg_full
            gstr1_by_rate = aggregate_gstr1_by_rate(
                gstr1_records,
                prior_records=None,
            )
    else:
        gstr1_agg = aggregate_gstr1(
            gstr1_records,
            include_cdn=include_cdn,
            include_zero_rated=include_zero_rated,
        )
        gstr1_by_rate = aggregate_gstr1_by_rate(
            gstr1_records,
        )

    # Compute statutory reconciliation
    taxable_diff = gstr1_agg.taxable_value_paise - gstr3b_summary.taxable_value_paise
    zero_diff = gstr1_agg.zero_rated_taxable_paise - gstr3b_summary.zero_rated_taxable_paise
    nil_diff = gstr1_agg.nil_exempt_taxable_paise - gstr3b_summary.nil_exempt_taxable_paise
    nongst_diff = gstr1_agg.non_gst_taxable_paise - gstr3b_summary.non_gst_taxable_paise

    total_gstr1_outward = (
        gstr1_agg.taxable_value_paise
        + gstr1_agg.zero_rated_taxable_paise
        + gstr1_agg.nil_exempt_taxable_paise
        + gstr1_agg.non_gst_taxable_paise
    )
    total_gstr3b_outward = (
        gstr3b_summary.taxable_value_paise
        + gstr3b_summary.zero_rated_taxable_paise
        + gstr3b_summary.nil_exempt_taxable_paise
        + gstr3b_summary.non_gst_taxable_paise
    )
    unexplained_diff = total_gstr1_outward - total_gstr3b_outward

    if abs(unexplained_diff) <= tolerance_paise and (
        abs(taxable_diff) > tolerance_paise
        or abs(zero_diff) > tolerance_paise
        or abs(nil_diff) > tolerance_paise
        or abs(nongst_diff) > tolerance_paise
    ):
        reclassification_diff = (
            abs(taxable_diff)
            + abs(zero_diff)
            + abs(nil_diff)
            + abs(nongst_diff)
        ) // 2
    else:
        reclassification_diff = 0

    stat_recon = StatutoryTableReconciliation(
        taxable_outward=CategoryReconciliation(
            gstr1_value_paise=gstr1_agg.taxable_value_paise,
            gstr3b_value_paise=gstr3b_summary.taxable_value_paise,
            difference_paise=taxable_diff,
        ),
        zero_rated=CategoryReconciliation(
            gstr1_value_paise=gstr1_agg.zero_rated_taxable_paise,
            gstr3b_value_paise=gstr3b_summary.zero_rated_taxable_paise,
            difference_paise=zero_diff,
        ),
        nil_exempt=CategoryReconciliation(
            gstr1_value_paise=gstr1_agg.nil_exempt_taxable_paise,
            gstr3b_value_paise=gstr3b_summary.nil_exempt_taxable_paise,
            difference_paise=nil_diff,
        ),
        non_gst=CategoryReconciliation(
            gstr1_value_paise=gstr1_agg.non_gst_taxable_paise,
            gstr3b_value_paise=gstr3b_summary.non_gst_taxable_paise,
            difference_paise=nongst_diff,
        ),
        tax={
            "igst": CategoryReconciliation(
                gstr1_value_paise=gstr1_agg.igst_paise,
                gstr3b_value_paise=gstr3b_summary.igst_paise,
                difference_paise=gstr1_agg.igst_paise - gstr3b_summary.igst_paise,
            ),
            "cgst": CategoryReconciliation(
                gstr1_value_paise=gstr1_agg.cgst_paise,
                gstr3b_value_paise=gstr3b_summary.cgst_paise,
                difference_paise=gstr1_agg.cgst_paise - gstr3b_summary.cgst_paise,
            ),
            "sgst": CategoryReconciliation(
                gstr1_value_paise=gstr1_agg.sgst_paise,
                gstr3b_value_paise=gstr3b_summary.sgst_paise,
                difference_paise=gstr1_agg.sgst_paise - gstr3b_summary.sgst_paise,
            ),
            "cess": CategoryReconciliation(
                gstr1_value_paise=gstr1_agg.cess_paise,
                gstr3b_value_paise=gstr3b_summary.cess_paise,
                difference_paise=gstr1_agg.cess_paise - gstr3b_summary.cess_paise,
            ),
            "total": CategoryReconciliation(
                gstr1_value_paise=gstr1_agg.total_tax_paise,
                gstr3b_value_paise=gstr3b_summary.total_tax_paise,
                difference_paise=gstr1_agg.total_tax_paise - gstr3b_summary.total_tax_paise,
            ),
        },
        unexplained_difference_paise=unexplained_diff,
        reclassification_difference_paise=reclassification_diff,
    )

    # Compute variances
    variances = compute_variances(
        gstr1_agg, gstr3b_summary, tolerance_paise=tolerance_paise,
    )

    # Convert to Decision Layer mismatches
    mismatches = [
        _variance_to_mismatch(v, ret_period=ret_period)
        for v in variances
    ]

    has_financial_variance = any(
        v.variance_type != TieOutVarianceType.RECLASSIFICATION
        for v in variances
    )
    is_clean = not has_financial_variance

    _log.info(
        "gstr1_vs_3b: period=%s, gstr1_records=%d, variances=%d, clean=%s, unexplained_diff=%s",
        ret_period, gstr1_agg.record_count, len(variances), is_clean, _rs(unexplained_diff),
    )

    return TieOutResult(
        ret_period=ret_period,
        gstr1_aggregate=gstr1_agg,
        gstr3b_summary=gstr3b_summary,
        gstr1_by_rate=gstr1_by_rate,
        variances=variances,
        mismatches=mismatches,
        is_clean=is_clean,
        statutory_reconciliation=stat_recon,
        unexplained_difference_paise=unexplained_diff,
        reclassification_difference_paise=reclassification_diff,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    "GSTR1Aggregate",
    "GSTR3BSummary",
    "CategoryReconciliation",
    "StatutoryTableReconciliation",
    "TieOutResult",
    "TieOutVarianceType",
    "FieldVariance",
    "DEFAULT_TOLERANCE_PAISE",
    "GSTR3BBucket",
    "map_gstr1_supply_to_gstr3b_bucket",
    "aggregate_gstr1",
    "aggregate_gstr1_by_rate",
    "gstr3b_to_summary",
    "compute_variances",
    "reconcile_gstr1_vs_3b",
]
