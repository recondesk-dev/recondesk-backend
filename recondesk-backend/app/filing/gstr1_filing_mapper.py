"""Map Sales Register records → Sandbox Save GSTR-1 JSON.

Source of truth is ``sales_register_parser`` normalized records (unfiled books),
not ``gstr1_parser`` (already-filed portal JSON).

Tables implemented
------------------
- **B2B**: invoice-level; clear ``inv_typ == \"R\"`` → Save; else review.
- **B2CS**: rate+POS aggregates; clear B2C-small rows sum into ``b2cs[]``;
  ambiguous rows → ``pending_review``; clear B2CL → ``b2cl_candidates``.
- **B2CL**: consumes ``b2cl_candidates`` (no threshold re-derive); missing
  Save fields / tax×rate mismatch → ``pending_review``.
- **CDNR**: credit/debit notes to registered recipients; ``cdnur_candidates``
  hand-off when GSTIN absent; ``ntty`` / ``inv_typ`` with no silent defaults.
- **CDNUR**: consumes ``cdnur_candidates``; ``typ: B2CL`` via shared B2CL
  threshold; INTRA / INTER≤threshold → ``b2cs_net_candidates``.
- **EXP**: Table 6A genuine exports only; ``exp_typ`` text-first then tax
  fallback; shipping bill trio required for Save; B2B-SEZ excluded
  defensively (independent of orchestration order).
- **B2CS netting** (two-pass): ``apply_b2cs_netting`` adjusts B2CS buckets
  with CDNUR ``b2cs_net_candidates`` (CN subtracts, DN adds). Use
  ``build_netted_b2cs_save`` at the filing boundary so callers cannot
  forget the second pass.
- **HSN**: Table 12 bifurcated ``hsn_b2b`` / ``hsn_b2c``; aggregate
  ``(hsn_sc, uqc, rt)``. Any coverage gap (missing HSN, or goods missing
  uqc/qty) → one ``NeedsExternalInput`` and **no** partial Save. Services
  default ``uqc=NA``, ``qty=0``. Malformed HSN → ``pending_review``.
- **DOC_ISSUE**: Table 13 — never derived from SR / G1M8 / G1M10. If any
  outward Save tables have data → ``NeedsExternalInput`` only (empty
  ``doc_issue``). True nil period (no outward Save data) → omit entirely.
- **NIL**: Table 8 consolidated ``nil.inv[]`` by ``sply_ty``. Save only when
  every nil-class row has an unambiguous nil/exempt/non-GST label; any lump
  → ``NeedsExternalInput`` and no partial Save. No nil-class rows → omit.
- **AT / TXPD**: Table 11 — no reliable SR advance schedule in practice
  (0 advances on sample SR; typical books exports omit them). Thin envelope
  only: any ``ADVANCES``-class row → ``NeedsExternalInput`` (never invent
  ``at``/``txpd`` Save); no advance rows → omit cleanly.

Known deferred gaps (not silent drops)
--------------------------------------
- ``cdnur_export_typ_needs_review``: stays on CDNUR (manual review until a
  CDNUR ``typ: EXPWP|EXPWOP`` branch ships). That branch will reuse
  ``resolve_exp_typ_from_sr`` — it will **not** feed ``exp[]`` / Table 6A.
  Notes vs invoices are different GSTN tables.

Data-gap channels (do not conflate)
-----------------------------------
- ``pending_review``: per-row; human can decide from existing SR fields.
- ``NeedsExternalInput`` (see ``gstr1_external_input``): period/table-level;
  SR cannot supply the table — CA needs a separate artifact.

Tax×rate gate: ``taxable × (rate/100)`` vs stated GST (IGST+CGST+SGST for
B2B/B2CS; IGST for B2CL/CDNUR/EXP) within ±₹1 before Save.

Per-invoice / per-row granularity: a minority of review rows never blocks the
rest of the Save payload. Exception: missing ``filer_state`` fails the whole
B2CS call up front (precondition, not a row-level data issue).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.filing.gstr1_thresholds import b2cl_invoice_value_threshold_paise
from app.filing.gstr1_external_input import (
    NeedsExternalInput,
    advances_unavailable_from_sr,
)
from app.services.normalizer import NormalizationError, normalize_gstin

# GSTN B2B inv_typ codes (Tables 4A/4B/6B/6C).
INV_TYP_R = "R"
INV_TYP_SEZWP = "SEZWP"
INV_TYP_SEZWOP = "SEZWOP"
INV_TYP_DE = "DE"
INV_TYP_CBW = "CBW"

# Known GSTN state / UT codes for POS validation (B2CS aggregation).
_VALID_STATE_CODES: frozenset[str] = frozenset({
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "32", "33", "34", "35", "36", "37", "38",
    "96", "97",
})

_B2C_TYPES = frozenset({"B2C", "B2C_SMALL", "B2C_LARGE"})
_NON_B2C_TYPES = frozenset({
    "B2B", "EXPORT", "CREDIT_NOTE", "DEBIT_NOTE", "NIL_RATED", "ADVANCES",
    "HSN_SUMMARY",
})

_CLEAR_R_KEYWORDS: tuple[str, ...] = (
    "regular",
    "b2b",
    "b 2 b",
    "business to business",
    "tax invoice",
    "taxable",
)

# More-specific patterns first. Bare "sez" / "export" alone are ambiguous.
_INV_TYP_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (INV_TYP_SEZWP, (
        "sez with payment",
        "sez wp",
        "sezwp",
        "sez-wp",
        "supply to sez with payment",
    )),
    (INV_TYP_SEZWOP, (
        "sez without payment",
        "sez wop",
        "sezwop",
        "sez-wop",
        "supply to sez without payment",
        "sez zero rated",
    )),
    (INV_TYP_DE, (
        "deemed export",
        "deemed exports",
    )),
    (INV_TYP_CBW, (
        "cbw",
        "bonded warehouse",
        "customs bonded warehouse",
    )),
)

_AMBIGUOUS_SEZ_EXPORT_HINTS: tuple[str, ...] = (
    "sez",
    "export",
    "exports",
    "exp",
    "zero rated",
    "zero-rated",
)

# Save amount / rate keys that must serialize as JSON ints when whole
# (GSTN schema marks many of these as ``integer``; ``18.0`` fails validation).
_GSTN_AMOUNT_KEYS: frozenset[str] = frozenset({
    "rt",
    "txval",
    "iamt",
    "camt",
    "samt",
    "csamt",
    "val",
    "qty",
    "nil_amt",
    "expt_amt",
    "ngsup_amt",
    "ad_amt",
    "num",  # item / HSN row sequence — always whole
    "gt",
    "cur_gt",
})


def _gstn_json_number(value: Any) -> int | float | None:
    """Coerce a numeric Save field so whole values serialize without ``.0``.

    GSTN/Sandbox JSON Schema treats ``rt`` / ``csamt`` (and several others) as
    ``integer``. Python ``18.0`` becomes JSON ``18.0``, which fails that check
    even when the value is mathematically whole. Fractional rates/amounts stay
    as ``float``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    rounded = round(f)
    if abs(f - rounded) < 1e-9:
        return int(rounded)
    return f


def _gstn_finalize_amounts(obj: Any) -> Any:
    """Recursively apply :func:`_gstn_json_number` to Save amount keys."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, val in obj.items():
            if key in _GSTN_AMOUNT_KEYS and isinstance(val, (int, float)) and not isinstance(
                val, bool
            ):
                coerced = _gstn_json_number(val)
                out[key] = coerced if coerced is not None else val
            else:
                out[key] = _gstn_finalize_amounts(val)
        return out
    if isinstance(obj, list):
        return [_gstn_finalize_amounts(item) for item in obj]
    return obj


def _validated_counterparty_gstin(raw: Any) -> str | None:
    """Format + check-digit via ``normalize_gstin`` (same as SR parser).

    G1M7's ``gstin_format_ok`` is regex-only and must **not** be reused here.
    """
    if raw is None:
        return None
    try:
        return normalize_gstin(str(raw))
    except NormalizationError:
        return None


def _counterparty_gstin_ok(rec: dict[str, Any]) -> bool:
    """True when recipient GSTIN passes checksum (not format-regex alone)."""
    return _validated_counterparty_gstin(rec.get("gstin")) is not None


# Kept for callers that only need the pattern; prefer ``_validated_counterparty_gstin``.
_GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
)


@dataclass
class InvTypResolution:
    """Result of resolving GSTN ``inv_typ`` from SR raw type text."""

    inv_typ: Optional[str]
    needs_review: bool
    reason: str


@dataclass
class PendingReviewInvoice:
    """Invoice held out of Save until CA confirms ``inv_typ`` / table."""

    record: dict[str, Any]
    proposed_inv_typ: Optional[str]
    reason: str
    suggested_table: str = "b2b"


@dataclass
class B2BMapResult:
    """B2B Save fragment plus per-invoice review queue."""

    b2b: list[dict[str, Any]] = field(default_factory=list)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    skipped_non_b2b: int = 0

    @property
    def save_invoice_count(self) -> int:
        return sum(len(group.get("inv") or []) for group in self.b2b)

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)


@dataclass
class B2CSMapResult:
    """B2CS Save fragment, review queue, and clear B2CL hand-off rows."""

    b2cs: list[dict[str, Any]] = field(default_factory=list)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    b2cl_candidates: list[dict[str, Any]] = field(default_factory=list)
    skipped_non_b2c: int = 0
    threshold_paise: int = 0
    filer_state: str = ""
    bucket_records: dict[tuple[str, float], list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def bucket_count(self) -> int:
        return len(self.b2cs)


@dataclass
class B2CLMapResult:
    """B2CL Save fragment plus per-invoice review queue."""

    b2cl: list[dict[str, Any]] = field(default_factory=list)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    filer_state: str = ""

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def save_invoice_count(self) -> int:
        return sum(len(group.get("inv") or []) for group in self.b2cl)


@dataclass
class CDNRMapResult:
    """CDNR Save fragment, review queue, and CDNUR hand-off rows."""

    cdnr: list[dict[str, Any]] = field(default_factory=list)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    cdnur_candidates: list[dict[str, Any]] = field(default_factory=list)
    skipped_non_cdn: int = 0
    filer_state: str = ""

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def save_note_count(self) -> int:
        return sum(len(group.get("nt") or []) for group in self.cdnr)


@dataclass
class B2CSNetCandidate:
    """Unregistered CN/DN that belongs in Table 7 netting, not CDNUR.

    Consumed by ``apply_b2cs_netting`` (CN subtracts, DN adds) into ``(pos, rt)``
    B2CS buckets. Amounts are absolute paise snapshots from the SR row.
    """

    record: dict[str, Any]
    nt_num: str
    ntty: str
    pos: str
    sply_ty: str  # INTER | INTRA
    val_paise: int
    tax_rate: float
    taxable_amount_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int
    reason: str  # why not CDNUR: intra | inter_at_or_below_threshold


@dataclass
class B2CSNetResult:
    """Output of the second-pass B2CS netting step."""

    b2cs: list[dict[str, Any]] = field(default_factory=list)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    applied_candidate_count: int = 0
    omitted_zero_buckets: int = 0
    negative_bucket_records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def bucket_count(self) -> int:
        return len(self.b2cs)


@dataclass
class CDNURMapResult:
    """CDNUR Save fragment, review queue, and B2CS-netting hand-off."""

    cdnur: list[dict[str, Any]] = field(default_factory=list)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    b2cs_net_candidates: list[B2CSNetCandidate] = field(default_factory=list)
    threshold_paise: int = 0
    filer_state: str = ""

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def save_note_count(self) -> int:
        return len(self.cdnur)


@dataclass
class EXPMapResult:
    """EXP Save fragment plus per-invoice review queue."""

    exp: list[dict[str, Any]] = field(default_factory=list)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    skipped_non_exp: int = 0

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def save_invoice_count(self) -> int:
        return sum(len(group.get("inv") or []) for group in self.exp)


@dataclass
class HSNMapResult:
    """Table 12 HSN Save fragment, review queue, and optional external-input gap."""

    hsn: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"hsn_b2b": [], "hsn_b2c": []}
    )
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    needs_external_input: Optional[NeedsExternalInput] = None
    skipped_non_hsn: int = 0
    taxable_line_count: int = 0
    coverage_gap_line_count: int = 0
    filing_period: str = ""

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def save_row_count(self) -> int:
        return len(self.hsn.get("hsn_b2b") or []) + len(self.hsn.get("hsn_b2c") or [])

    @property
    def blocked_by_external_input(self) -> bool:
        return self.needs_external_input is not None


@dataclass
class DocIssueMapResult:
    """Table 13 Documents Issued — external-input gap only (never SR-derived)."""

    doc_issue: Optional[dict[str, Any]] = None
    needs_external_input: Optional[NeedsExternalInput] = None
    filing_period: str = ""
    outward_save_count: int = 0

    @property
    def blocked_by_external_input(self) -> bool:
        return self.needs_external_input is not None


@dataclass
class NILMapResult:
    """Table 8 nil/exempt/non-GST Save fragment + review / external-input."""

    nil: Optional[dict[str, Any]] = None
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    needs_external_input: Optional[NeedsExternalInput] = None
    skipped_non_nil: int = 0
    nil_class_line_count: int = 0
    lump_line_count: int = 0
    filer_state: str = ""
    filing_period: str = ""

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)

    @property
    def save_row_count(self) -> int:
        if not self.nil:
            return 0
        return len(self.nil.get("inv") or [])

    @property
    def blocked_by_external_input(self) -> bool:
        return self.needs_external_input is not None


@dataclass
class AtTxpdMapResult:
    """Table 11 AT/TXPD — external-input envelope only (never SR-derived Save).

    Coverage (sample + typical synthetic): advance rows are absent in practice.
    When ``ADVANCES``-class rows do appear, SR still lacks a real advance
    schedule (AT vs TXPD, tax breakdown, adjustments) — always external.
    """

    at: Optional[list[dict[str, Any]]] = None
    txpd: Optional[list[dict[str, Any]]] = None
    needs_external_input: list[NeedsExternalInput] = field(default_factory=list)
    advance_line_count: int = 0
    filing_period: str = ""

    @property
    def blocked_by_external_input(self) -> bool:
        return bool(self.needs_external_input)


# Nil Table 8 amount columns.
NIL_COL_NIL = "nil_amt"
NIL_COL_EXEMPT = "expt_amt"
NIL_COL_NON_GST = "ngsup_amt"

_NIL_SPLY_TYPES: tuple[str, ...] = (
    "INTERB2B", "INTRB2B", "INTERB2C", "INTRB2C",
)


@dataclass
class NttyResolution:
    """Result of resolving GSTN ``ntty`` (C/D) from SR type fields."""

    ntty: Optional[str]
    needs_review: bool
    reason: str


@dataclass
class ExpTypResolution:
    """Result of resolving GSTN ``exp_typ`` (WPAY/WOPAY) from SR fields."""

    exp_typ: Optional[str]
    needs_review: bool
    reason: str


class MissingFilerStateError(ValueError):
    """Raised when B2CS/B2CL mapping is called without a valid filer state code."""


# GSTN Table 6A export payment types.
EXP_TYP_WPAY = "WPAY"
EXP_TYP_WOPAY = "WOPAY"

_WPAY_KEYWORDS: tuple[str, ...] = (
    "wpay",
    "with payment",
    "with pay",
    "expwp",
    "export with payment",
    "exports with payment",
    "igst paid",
    "with igst",
)

_WOPAY_KEYWORDS: tuple[str, ...] = (
    "wopay",
    "without payment",
    "without pay",
    "expwop",
    "export without payment",
    "exports without payment",
    "lut",
    "under lut",
    "bond",
    "under bond",
    "without igst",
)

# ±₹1 tolerance for txval × (rt/100) vs stated GST (paise→rupee rounding).
TAX_RATE_AMOUNT_TOLERANCE_RUPEES = 1.0


def resolve_inv_typ_from_sr_raw(
    *,
    invoice_type_raw: str | None,
    export_type_raw: str | None = None,
    invoice_type: str | None = None,
) -> InvTypResolution:
    """Resolve GSTN B2B ``inv_typ`` from SR raw type / export-type text.

    There is **no** existing recon-side classifier for SEZWP / SEZWOP / DE / CBW
    vs genuine EXPORT (see module notes). This is the single filing-side
    implementation — do not duplicate elsewhere.

    Rules:
    - Clear regular/B2B keywords → ``R`` (no review).
    - Clear SEZWP / SEZWOP / DE / CBW keywords → proposed code + **needs review**
      (never auto-saved).
    - Ambiguous SEZ/export wording or unrecognised type text → needs review.
    - Blank / missing type column **and** derived ``invoice_type`` in
      ``{B2B, CREDIT_NOTE, DEBIT_NOTE}`` → ``R`` without review.
      This is the common path for books exports that omit a type column; it is
      not a silent default over SEZ/DE rows.
    - Blank type column when derived type is not B2B/CN/DN → needs review.
    """
    combined = " ".join(
        p for p in (
            (invoice_type_raw or "").strip(),
            (export_type_raw or "").strip(),
        ) if p
    )
    norm = re.sub(r"\s+", " ", combined.lower()).strip()
    derived = (invoice_type or "").strip().upper()

    if not norm:
        if derived in {"B2B", "CREDIT_NOTE", "DEBIT_NOTE"}:
            return InvTypResolution(
                inv_typ=INV_TYP_R,
                needs_review=False,
                reason="inferred_b2b_no_type_column",
            )
        return InvTypResolution(
            inv_typ=None,
            needs_review=True,
            reason="missing_or_blank_invoice_type_raw",
        )

    for code, keywords in _INV_TYP_PATTERNS:
        for kw in keywords:
            if _keyword_match(norm, kw):
                return InvTypResolution(
                    inv_typ=code,
                    needs_review=True,
                    reason=f"non_r_inv_typ:{code}",
                )

    for kw in _CLEAR_R_KEYWORDS:
        if _keyword_match(norm, kw):
            return InvTypResolution(
                inv_typ=INV_TYP_R,
                needs_review=False,
                reason="explicit_regular_b2b",
            )

    # Bare "sez" / "export" / etc. without with-payment / deemed specificity.
    for hint in _AMBIGUOUS_SEZ_EXPORT_HINTS:
        if _keyword_match(norm, hint):
            return InvTypResolution(
                inv_typ=None,
                needs_review=True,
                reason="ambiguous_sez_or_export_wording",
            )

    # Unrecognised free text — never invent R.
    return InvTypResolution(
        inv_typ=None,
        needs_review=True,
        reason="unrecognised_invoice_type_raw",
    )


def map_sales_register_to_gstr1_b2b(
    records: list[dict[str, Any]],
) -> B2BMapResult:
    """Transform SR records into Sandbox ``b2b`` Save shape + review queue.

    Invoices that need ``inv_typ`` review are **excluded** from ``b2b``; the
    remaining clear-R invoices still form a valid Save payload (per-invoice
    granularity, not all-or-nothing).
    """
    result = B2BMapResult()
    # ctin → list of inv dicts
    by_ctin: dict[str, list[dict[str, Any]]] = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue

        derived = str(rec.get("invoice_type") or "").strip().upper()
        ctin = _validated_counterparty_gstin(rec.get("gstin"))
        gstin_ok = ctin is not None

        type_raw = _coalesce_str(
            rec.get("invoice_type_raw"),
            # Older payloads / tests may only have the raw value under invoice_type
            # when it was never classified — prefer explicit *_raw fields.
        )
        export_raw = _coalesce_str(
            rec.get("export_type_raw"),
            rec.get("export_type"),
        )

        # EXPORT rows that look like SEZ/DE with a valid recipient GSTIN belong
        # on the B2B review queue (GSTN tables 6B/6C), not silent EXP routing.
        if derived == "EXPORT" and gstin_ok and _looks_like_sez_or_deemed(
            type_raw, export_raw
        ):
            resolution = resolve_inv_typ_from_sr_raw(
                invoice_type_raw=type_raw,
                export_type_raw=export_raw,
                invoice_type=derived,
            )
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=resolution.inv_typ,
                    reason=resolution.reason or "export_classified_sez_or_deemed",
                    suggested_table="b2b",
                )
            )
            continue

        if derived != "B2B" or not gstin_ok:
            result.skipped_non_b2b += 1
            continue

        resolution = resolve_inv_typ_from_sr_raw(
            invoice_type_raw=type_raw,
            export_type_raw=export_raw,
            invoice_type=derived,
        )
        if resolution.needs_review:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=resolution.inv_typ,
                    reason=resolution.reason,
                    suggested_table="b2b",
                )
            )
            continue

        assert resolution.inv_typ == INV_TYP_R
        if not _sr_tax_reconciles_with_rate(rec):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=INV_TYP_R,
                    reason="tax_amount_inconsistent_with_rate",
                    suggested_table="b2b",
                )
            )
            continue
        inv = _sr_record_to_b2b_inv(rec, inv_typ=INV_TYP_R)
        if inv is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=INV_TYP_R,
                    reason="incomplete_b2b_fields",
                    suggested_table="b2b",
                )
            )
            continue
        assert ctin is not None
        by_ctin.setdefault(ctin, []).append(inv)

    result.b2b = [
        {"ctin": ctin, "inv": invs}
        for ctin, invs in sorted(by_ctin.items())
    ]
    return result


def require_filer_state(filer_state: str | None) -> str:
    """Validate filer state (first 2 digits of filing GSTIN). Raises if unusable."""
    code = (filer_state or "").strip()
    if len(code) >= 2 and code[:2].isdigit():
        code = code[:2]
    if not code or code not in _VALID_STATE_CODES:
        raise MissingFilerStateError(
            "filer_state is required for B2C filing mappers "
            "(2-digit state code from the filing-run GSTIN); "
            f"got {filer_state!r}"
        )
    return code


def map_sales_register_to_gstr1_b2cs(
    records: list[dict[str, Any]],
    *,
    filer_state: str,
    filing_period: str,
) -> B2CSMapResult:
    """Aggregate SR B2C-small rows into Sandbox ``b2cs[]`` + review / B2CL queues.

    Parameters
    ----------
    filer_state:
        Required 2-digit state code from the filing-run GSTIN. Missing/invalid
        raises ``MissingFilerStateError`` (whole-batch precondition).
    filing_period:
        ``YYYY-MM`` used to select the period-aware B2CL invoice-value threshold.
    """
    state = require_filer_state(filer_state)
    threshold = b2cl_invoice_value_threshold_paise(filing_period)

    result = B2CSMapResult(
        threshold_paise=threshold,
        filer_state=state,
    )
    # (pos, rt) → running totals in rupees + supply type
    buckets: dict[tuple[str, float], dict[str, Any]] = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue
        if not _is_b2c_candidate(rec):
            result.skipped_non_b2c += 1
            continue

        derived = str(rec.get("invoice_type") or "").strip().upper()
        pos = _pos_code(rec.get("place_of_supply"))
        if not pos or pos not in _VALID_STATE_CODES:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_or_malformed_pos",
                    suggested_table="b2cs",
                )
            )
            continue

        rt = _tax_rate(rec)
        if rt is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_tax_rate",
                    suggested_table="b2cs",
                )
            )
            continue

        value_paise = _invoice_value_paise(rec)
        is_inter = pos != state
        sply_ty = "INTER" if is_inter else "INTRA"

        flag_conflict = _interstate_flag_conflict(rec, is_inter=is_inter)
        if flag_conflict:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="interstate_flag_conflicts_with_pos",
                    suggested_table="b2cs",
                )
            )
            continue

        # Inter-state needs invoice value to apply the B2CL threshold gate.
        if is_inter and value_paise is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_invoice_value_for_b2cl_gate",
                    suggested_table="b2cs",
                )
            )
            continue

        above_threshold = bool(
            is_inter and value_paise is not None and value_paise > threshold
        )

        # Label vs numbers conflicts → review (do not silent-route).
        if derived == "B2C_LARGE" and not above_threshold:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="label_vs_numbers_b2cl",
                    suggested_table="b2cl" if is_inter else "b2cs",
                )
            )
            continue
        if derived == "B2C_SMALL" and above_threshold:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="label_vs_numbers_b2cs",
                    suggested_table="b2cl",
                )
            )
            continue

        # Clear B2CL hand-off: inter-state invoice value strictly above threshold.
        # (Plain B2C / explicit B2C_LARGE; B2C_SMALL conflict already reviewed.)
        if above_threshold:
            result.b2cl_candidates.append(rec)
            continue

        # B2CS path — need taxable value to sum.
        txval = _paise_to_rupees(rec.get("taxable_amount_paise"))
        if txval is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_taxable_value",
                    suggested_table="b2cs",
                )
            )
            continue

        if not _sr_tax_reconciles_with_rate(rec):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="tax_amount_inconsistent_with_rate",
                    suggested_table="b2cs",
                )
            )
            continue

        key = (pos, rt)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "sply_ty": sply_ty,
                "pos": pos,
                "rt": rt,
                "typ": "OE",
                "txval": 0.0,
                "iamt": 0.0,
                "camt": 0.0,
                "samt": 0.0,
                "csamt": 0.0,
            }
            buckets[key] = bucket
        elif bucket["sply_ty"] != sply_ty:
            # Same POS+rate cannot flip INTER/INTRA for one filer — data bug.
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="sply_ty_inconsistent_for_bucket",
                    suggested_table="b2cs",
                )
            )
            continue

        bucket["txval"] += txval
        bucket["iamt"] += _paise_to_rupees(rec.get("igst_paise")) or 0.0
        bucket["camt"] += _paise_to_rupees(rec.get("cgst_paise")) or 0.0
        bucket["samt"] += _paise_to_rupees(rec.get("sgst_paise")) or 0.0
        bucket["csamt"] += _paise_to_rupees(rec.get("cess_paise")) or 0.0
        result.bucket_records.setdefault(key, []).append(rec)

    result.b2cs = [
        _gstn_finalize_amounts(buckets[k])
        for k in sorted(buckets.keys(), key=lambda x: (x[0], x[1]))
    ]
    return result


def apply_b2cs_netting(
    b2cs: list[dict[str, Any]],
    candidates: list[B2CSNetCandidate],
    *,
    filer_state: str,
    b2cs_bucket_records: dict[tuple[str, float], list[dict[str, Any]]] | None = None,
) -> B2CSNetResult:
    """Second pass: fold CDNUR ``b2cs_net_candidates`` into B2CS ``(pos, rt)`` buckets.

    Credit notes (``ntty=C``) subtract; debit notes (``ntty=D``) add. Buckets may
    be created by netting alone (e.g. DN with no matching gross B2CS row).

    GSTN Table 7 is a **net** figure — portal practice does not accept a
    negative bucket as a Save row. If netting drives ``txval`` below -₹1,
    that bucket is held in ``pending_review`` (``b2cs_net_negative_bucket``)
    and omitted from Save. Near-zero nets (|txval| ≤ ₹1) are omitted quietly
    (no row to file).
    """
    state = require_filer_state(filer_state)
    result = B2CSNetResult()
    buckets: dict[tuple[str, float], dict[str, Any]] = {}
    candidates_by_bucket: dict[tuple[str, float], list[dict[str, Any]]] = {}

    for row in b2cs:
        if not isinstance(row, dict):
            continue
        pos = str(row.get("pos") or "").strip()
        try:
            rt = float(row.get("rt"))
        except (TypeError, ValueError):
            continue
        if not pos:
            continue
        buckets[(pos, rt)] = {
            "sply_ty": row.get("sply_ty") or ("INTRA" if pos == state else "INTER"),
            "pos": pos,
            "rt": rt,
            "typ": row.get("typ") or "OE",
            "txval": float(row.get("txval") or 0.0),
            "iamt": float(row.get("iamt") or 0.0),
            "camt": float(row.get("camt") or 0.0),
            "samt": float(row.get("samt") or 0.0),
            "csamt": float(row.get("csamt") or 0.0),
        }

    for cand in candidates:
        if not isinstance(cand, B2CSNetCandidate):
            continue

        ntty = (cand.ntty or "").strip().upper()
        if ntty not in {"C", "D"}:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=cand.record,
                    proposed_inv_typ=None,
                    reason="b2cs_net_invalid_ntty",
                    suggested_table="b2cs",
                )
            )
            continue

        pos = (cand.pos or "").strip()
        if not pos or pos not in _VALID_STATE_CODES:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=cand.record,
                    proposed_inv_typ=None,
                    reason="missing_or_malformed_pos",
                    suggested_table="b2cs",
                )
            )
            continue

        rt = float(cand.tax_rate)
        expected_sply = "INTRA" if pos == state else "INTER"
        if cand.sply_ty and cand.sply_ty != expected_sply:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=cand.record,
                    proposed_inv_typ=None,
                    reason="sply_ty_inconsistent_for_bucket",
                    suggested_table="b2cs",
                )
            )
            continue

        txval = cand.taxable_amount_paise / 100.0
        iamt = cand.igst_paise / 100.0
        camt = cand.cgst_paise / 100.0
        samt = cand.sgst_paise / 100.0
        csamt = cand.cess_paise / 100.0
        gst_tax = iamt + camt + samt
        if not _tax_amount_matches_rate(txval, rt, gst_tax):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=cand.record,
                    proposed_inv_typ=None,
                    reason="tax_amount_inconsistent_with_rate",
                    suggested_table="b2cs",
                )
            )
            continue

        sign = -1.0 if ntty == "C" else 1.0
        key = (pos, rt)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "sply_ty": expected_sply,
                "pos": pos,
                "rt": rt,
                "typ": "OE",
                "txval": 0.0,
                "iamt": 0.0,
                "camt": 0.0,
                "samt": 0.0,
                "csamt": 0.0,
            }
            buckets[key] = bucket
        elif bucket["sply_ty"] != expected_sply:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=cand.record,
                    proposed_inv_typ=None,
                    reason="sply_ty_inconsistent_for_bucket",
                    suggested_table="b2cs",
                )
            )
            continue

        bucket["txval"] += sign * txval
        bucket["iamt"] += sign * iamt
        bucket["camt"] += sign * camt
        bucket["samt"] += sign * samt
        bucket["csamt"] += sign * csamt
        candidates_by_bucket.setdefault(key, []).append(cand.record)
        result.applied_candidate_count += 1

    save_rows: list[dict[str, Any]] = []
    for key in sorted(buckets.keys(), key=lambda x: (x[0], x[1])):
        bucket = buckets[key]
        txval = bucket["txval"]
        if txval < -TAX_RATE_AMOUNT_TOLERANCE_RUPEES:
            contributing: list[dict[str, Any]] = []
            if b2cs_bucket_records:
                contributing.extend(b2cs_bucket_records.get(key, []))
            contributing.extend(candidates_by_bucket.get(key, []))
            result.negative_bucket_records.extend(contributing)
            result.pending_review.append(
                PendingReviewInvoice(
                    record={
                        "pos": bucket["pos"],
                        "rt": bucket["rt"],
                        "sply_ty": bucket["sply_ty"],
                        "net_txval": txval,
                        "net_iamt": bucket["iamt"],
                        "net_camt": bucket["camt"],
                        "net_samt": bucket["samt"],
                        "net_csamt": bucket["csamt"],
                        "contributing_record_count": len(contributing),
                    },
                    proposed_inv_typ=None,
                    reason="b2cs_net_negative_bucket",
                    suggested_table="b2cs",
                )
            )
            continue
        if abs(txval) <= TAX_RATE_AMOUNT_TOLERANCE_RUPEES:
            result.omitted_zero_buckets += 1
            continue
        save_rows.append(_gstn_finalize_amounts(bucket))

    result.b2cs = save_rows
    return result


def build_netted_b2cs_save(
    records: list[dict[str, Any]],
    net_candidates: list[B2CSNetCandidate],
    *,
    filer_state: str,
    filing_period: str,
) -> tuple[B2CSMapResult, B2CSNetResult]:
    """Filing-boundary helper: B2CS aggregate then apply CDNUR net candidates.

    Prefer this over calling ``map_sales_register_to_gstr1_b2cs`` alone when
    CDNUR may have produced ``b2cs_net_candidates`` — so netting is not
    forgotten. Unit tests may still call each pass independently.
    """
    gross = map_sales_register_to_gstr1_b2cs(
        records, filer_state=filer_state, filing_period=filing_period,
    )
    netted = apply_b2cs_netting(
        gross.b2cs,
        net_candidates,
        filer_state=filer_state,
        b2cs_bucket_records=gross.bucket_records,
    )
    return gross, netted


def map_sales_register_to_gstr1_b2cl(
    candidates: list[dict[str, Any]],
    *,
    filer_state: str,
) -> B2CLMapResult:
    """Map B2CS ``b2cl_candidates`` → Sandbox ``b2cl[]``.

    Does **not** re-run the B2CL invoice-value threshold. Eligibility was
    decided by ``map_sales_register_to_gstr1_b2cs``; this mapper only applies
    Save-field completeness + tax×rate consistency + a defensive INTRA leak
    check against ``filer_state``.
    """
    state = require_filer_state(filer_state)
    result = B2CLMapResult(filer_state=state)
    by_pos: dict[str, list[dict[str, Any]]] = {}

    for rec in candidates:
        if not isinstance(rec, dict):
            continue

        inum = _coalesce_str(rec.get("invoice_number_raw"))
        if not inum:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_inum",
                    suggested_table="b2cl",
                )
            )
            continue

        idt = _iso_to_ddmmyyyy(rec.get("invoice_date"))
        if not idt:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_or_invalid_idt",
                    suggested_table="b2cl",
                )
            )
            continue

        pos = _pos_code(rec.get("place_of_supply"))
        if not pos or pos not in _VALID_STATE_CODES:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_or_malformed_pos",
                    suggested_table="b2cl",
                )
            )
            continue

        if pos == state:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="b2cl_pos_not_interstate",
                    suggested_table="b2cl",
                )
            )
            continue

        rt = _tax_rate(rec)
        if rt is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_tax_rate",
                    suggested_table="b2cl",
                )
            )
            continue

        txval = _paise_to_rupees(rec.get("taxable_amount_paise"))
        if txval is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_taxable_value",
                    suggested_table="b2cl",
                )
            )
            continue

        # Invoice value for B2CL Save ``val`` — require explicit total (same
        # basis as the B2CS threshold gate); do not silently invent from tax.
        val = _paise_to_rupees(rec.get("total_amount_paise"))
        if val is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_invoice_value",
                    suggested_table="b2cl",
                )
            )
            continue

        iamt = _paise_to_rupees(rec.get("igst_paise")) or 0.0
        csamt = _paise_to_rupees(rec.get("cess_paise")) or 0.0

        # INTER-only: stated IGST must match txval × (rt/100) within tolerance.
        if not _tax_amount_matches_rate(txval, rt, iamt):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="tax_amount_inconsistent_with_rate",
                    suggested_table="b2cl",
                )
            )
            continue

        inv = _gstn_finalize_amounts({
            "inum": inum,
            "idt": idt,
            "val": val,
            "itms": [
                {
                    "num": 1,
                    "itm_det": {
                        "rt": rt,
                        "txval": txval,
                        "iamt": iamt,
                        "csamt": csamt,
                    },
                }
            ],
        })
        by_pos.setdefault(pos, []).append(inv)

    result.b2cl = [
        {"pos": pos, "inv": invs}
        for pos, invs in sorted(by_pos.items())
    ]
    return result


# Same keywords as sales_register_parser._INVOICE_TYPE_KEYWORDS for CN/DN —
# keep in sync so "raw suggests C/D" cannot diverge from SR classification.
_CREDIT_NOTE_RAW_KEYWORDS: tuple[str, ...] = (
    "credit note", "cr note", "credit memo", "cn", "sales return",
    "credit", "credit note (b2b)", "credit note (b2c)",
)
_DEBIT_NOTE_RAW_KEYWORDS: tuple[str, ...] = (
    "debit note", "dr note", "debit memo", "dn", "debit",
    "debit note (b2b)", "debit note (b2c)",
)


def resolve_ntty_from_sr(
    *,
    invoice_type: str | None,
    invoice_type_raw: str | None,
) -> NttyResolution:
    """Resolve GSTN ``ntty`` (C/D) — no silent guess when derived and raw disagree.

    Raw text that is an ``inv_typ`` signal (SEZ / regular / …) is ignored for
    ``ntty`` when derived is already CREDIT_NOTE/DEBIT_NOTE — that wording
    belongs to the shared inv_typ resolver, not C vs D.
    """
    derived = (invoice_type or "").strip().upper()
    raw_side = _raw_ntty_hint(invoice_type_raw)

    if derived == "CREDIT_NOTE":
        if raw_side == "D":
            return NttyResolution(None, True, "ntty_label_conflict")
        if raw_side == "AMBIGUOUS":
            if _raw_is_inv_typ_signal(invoice_type_raw):
                return NttyResolution("C", False, "derived_credit_note")
            return NttyResolution(None, True, "ntty_ambiguous_raw")
        return NttyResolution("C", False, "derived_credit_note")

    if derived == "DEBIT_NOTE":
        if raw_side == "C":
            return NttyResolution(None, True, "ntty_label_conflict")
        if raw_side == "AMBIGUOUS":
            if _raw_is_inv_typ_signal(invoice_type_raw):
                return NttyResolution("D", False, "derived_debit_note")
            return NttyResolution(None, True, "ntty_ambiguous_raw")
        return NttyResolution("D", False, "derived_debit_note")

    # Defensive: raw alone looks like CN/DN but derived is something else.
    # Unreachable on parse_sales_register output when raw is unambiguous
    # (SR classifier assigns CREDIT_NOTE/DEBIT_NOTE first). Kept for
    # hand-edited records.
    if raw_side in {"C", "D"}:
        return NttyResolution(None, True, "ntty_unclassified")
    return NttyResolution(None, True, "ntty_not_a_note")


def resolve_exp_typ_from_sr(
    *,
    export_type: str | None = None,
    export_type_raw: str | None = None,
    igst_paise: Any = None,
) -> ExpTypResolution:
    """Resolve GSTN ``exp_typ`` (WPAY/WOPAY).

    Primary signal: ``export_type`` / ``export_type_raw`` text.
    Tax-presence (IGST paid vs zero) is a fallback **only** when that text is
    absent. When both are present and disagree → ``export_typ_signal_conflict``
    (never pick silently).
    """
    text = _coalesce_str(export_type_raw, export_type)
    text_typ = _exp_typ_from_text(text) if text else None
    tax_typ = _exp_typ_from_igst(igst_paise)

    if text:
        if text_typ is None:
            return ExpTypResolution(None, True, "unrecognised_export_type_raw")
        if tax_typ is not None and tax_typ != text_typ:
            return ExpTypResolution(None, True, "export_typ_signal_conflict")
        return ExpTypResolution(text_typ, False, "explicit_export_type_text")

    if tax_typ is not None:
        return ExpTypResolution(tax_typ, False, "igst_presence_fallback")

    return ExpTypResolution(None, True, "export_typ_unresolved")


def map_sales_register_to_gstr1_cdnr(
    records: list[dict[str, Any]],
    *,
    filer_state: str,
) -> CDNRMapResult:
    """Map SR credit/debit notes → Sandbox ``cdnr[]`` + CDNUR hand-off."""
    state = require_filer_state(filer_state)
    result = CDNRMapResult(filer_state=state)
    by_ctin: dict[str, list[dict[str, Any]]] = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue

        derived = str(rec.get("invoice_type") or "").strip().upper()
        type_raw = _coalesce_str(rec.get("invoice_type_raw"))
        export_raw = _coalesce_str(
            rec.get("export_type_raw"),
            rec.get("export_type"),
        )

        ctin = _validated_counterparty_gstin(rec.get("gstin"))
        gstin_ok = ctin is not None

        if derived not in {"CREDIT_NOTE", "DEBIT_NOTE"}:
            # Defensive unclassified branch (see resolve_ntty_from_sr).
            ntty_res = resolve_ntty_from_sr(
                invoice_type=derived, invoice_type_raw=type_raw,
            )
            if ntty_res.reason == "ntty_unclassified":
                result.pending_review.append(
                    PendingReviewInvoice(
                        record=rec,
                        proposed_inv_typ=None,
                        reason="ntty_unclassified",
                        suggested_table="cdnr",
                    )
                )
            else:
                result.skipped_non_cdn += 1
            continue

        if not gstin_ok:
            result.cdnur_candidates.append(rec)
            continue

        ntty_res = resolve_ntty_from_sr(
            invoice_type=derived, invoice_type_raw=type_raw,
        )
        if ntty_res.needs_review:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason=ntty_res.reason,
                    suggested_table="cdnr",
                )
            )
            continue

        inv_typ_res = resolve_inv_typ_from_sr_raw(
            invoice_type_raw=_invoice_type_raw_for_inv_typ(type_raw),
            export_type_raw=export_raw,
            invoice_type=derived,
        )
        if inv_typ_res.needs_review:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=inv_typ_res.inv_typ,
                    reason=inv_typ_res.reason,
                    suggested_table="cdnr",
                )
            )
            continue

        note = _sr_record_to_cdnr_nt(
            rec,
            ntty=ntty_res.ntty or "C",
            inv_typ=inv_typ_res.inv_typ or INV_TYP_R,
            filer_state=state,
        )
        if isinstance(note, str):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=inv_typ_res.inv_typ,
                    reason=note,
                    suggested_table="cdnr",
                )
            )
            continue
        assert ctin is not None
        by_ctin.setdefault(ctin, []).append(note)

    result.cdnr = [
        {"ctin": ctin, "nt": notes}
        for ctin, notes in sorted(by_ctin.items())
    ]
    return result


def map_sales_register_to_gstr1_cdnur(
    candidates: list[dict[str, Any]],
    *,
    filer_state: str,
    filing_period: str,
) -> CDNURMapResult:
    """Map CDNR ``cdnur_candidates`` → Sandbox ``cdnur[]`` + B2CS-net hand-off.

    Does **not** re-decide that a row is an unregistered credit/debit note —
    that was fixed by ``map_sales_register_to_gstr1_cdnr``. This mapper only
    chooses table destination (``typ: B2CL`` vs B2CS netting vs export review)
    using the shared period-aware B2CL invoice-value threshold.
    """
    state = require_filer_state(filer_state)
    threshold = b2cl_invoice_value_threshold_paise(filing_period)
    result = CDNURMapResult(filer_state=state, threshold_paise=threshold)

    for rec in candidates:
        if not isinstance(rec, dict):
            continue

        type_raw = _coalesce_str(rec.get("invoice_type_raw"))
        derived = str(rec.get("invoice_type") or "").strip().upper()

        # Deferred: CDNUR typ EXPWP/EXPWOP (reuse resolve_exp_typ_from_sr later).
        # Not an exp[] hand-off — notes stay on cdnur until that branch ships.
        if _looks_like_cdnur_export(rec):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="cdnur_export_typ_needs_review",
                    suggested_table="cdnur",
                )
            )
            continue

        ntty_res = resolve_ntty_from_sr(
            invoice_type=derived, invoice_type_raw=type_raw,
        )
        if ntty_res.needs_review:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason=ntty_res.reason,
                    suggested_table="cdnur",
                )
            )
            continue

        nt_num = _coalesce_str(rec.get("invoice_number_raw"))
        if not nt_num:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_nt_num",
                    suggested_table="cdnur",
                )
            )
            continue

        nt_dt = _iso_to_ddmmyyyy(rec.get("invoice_date"))
        if not nt_dt:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_or_invalid_nt_dt",
                    suggested_table="cdnur",
                )
            )
            continue

        pos = _pos_code(rec.get("place_of_supply"))
        if not pos or pos not in _VALID_STATE_CODES:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_or_malformed_pos",
                    suggested_table="cdnur",
                )
            )
            continue

        rt = _tax_rate(rec)
        if rt is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_tax_rate",
                    suggested_table="cdnur",
                )
            )
            continue

        txval = _abs_paise_to_rupees(rec.get("taxable_amount_paise"))
        if txval is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_taxable_value",
                    suggested_table="cdnur",
                )
            )
            continue

        val_paise = _abs_invoice_value_paise(rec)
        if val_paise is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_invoice_value_for_b2cl_gate",
                    suggested_table="cdnur",
                )
            )
            continue

        is_inter = pos != state
        sply_ty = "INTER" if is_inter else "INTRA"
        above = is_inter and val_paise > threshold

        # INTRA or INTER ≤ threshold → Table 7 netting (not CDNUR lines).
        if not above:
            result.b2cs_net_candidates.append(
                _b2cs_net_candidate_from_rec(
                    rec,
                    nt_num=nt_num,
                    ntty=ntty_res.ntty or "C",
                    pos=pos,
                    sply_ty=sply_ty,
                    val_paise=val_paise,
                    tax_rate=rt,
                    reason=(
                        "intra"
                        if not is_inter
                        else "inter_at_or_below_threshold"
                    ),
                )
            )
            continue

        iamt = _abs_paise_to_rupees(rec.get("igst_paise")) or 0.0
        csamt = _abs_paise_to_rupees(rec.get("cess_paise")) or 0.0
        if not _tax_amount_matches_rate(txval, rt, iamt):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="tax_amount_inconsistent_with_rate",
                    suggested_table="cdnur",
                )
            )
            continue

        result.cdnur.append(
            _gstn_finalize_amounts(
                {
                    "typ": "B2CL",
                    "ntty": ntty_res.ntty or "C",
                    "nt_num": nt_num,
                    "nt_dt": nt_dt,
                    "pos": pos,
                    "val": val_paise / 100.0,
                    "itms": [
                        {
                            "num": 1,
                            "itm_det": {
                                "rt": rt,
                                "txval": txval,
                                "iamt": iamt,
                                "csamt": csamt,
                            },
                        }
                    ],
                }
            )
        )

    return result


def map_sales_register_to_gstr1_exp(
    records: list[dict[str, Any]],
) -> EXPMapResult:
    """Map SR records → Sandbox ``exp[]`` (Table 6A) + review queue.

    Genuine physical/deemed-as-export invoices only. SEZ/DE to a registered
    recipient is excluded defensively (``already_routed_b2b_sez``) even if
    B2B was never run first — recon's lump ``EXPORT`` category is not reused
    as eligibility.
    """
    result = EXPMapResult()
    by_typ: dict[str, list[dict[str, Any]]] = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue

        derived = str(rec.get("invoice_type") or "").strip().upper()
        type_raw = _coalesce_str(rec.get("invoice_type_raw"))
        export_raw = _coalesce_str(
            rec.get("export_type_raw"),
            rec.get("export_type"),
        )
        gstin_ok = _counterparty_gstin_ok(rec)

        # Notes / nil / advances / HSN are other tables.
        if derived in {
            "CREDIT_NOTE", "DEBIT_NOTE", "NIL_RATED", "ADVANCES", "HSN_SUMMARY",
        }:
            result.skipped_non_exp += 1
            continue

        # Defensive B2B-SEZ/DE peel — independent of orchestration order.
        if gstin_ok and _looks_like_sez_or_deemed(type_raw, export_raw):
            resolution = resolve_inv_typ_from_sr_raw(
                invoice_type_raw=type_raw,
                export_type_raw=export_raw,
                invoice_type=derived,
            )
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=resolution.inv_typ,
                    reason="already_routed_b2b_sez",
                    suggested_table="b2b",
                )
            )
            continue

        if not _looks_like_exp_invoice(rec):
            result.skipped_non_exp += 1
            continue

        # Registered recipient without SEZ/DE wording — do not silent-EXP.
        if gstin_ok:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="export_with_recipient_gstin",
                    suggested_table="exp",
                )
            )
            continue

        inum = _coalesce_str(rec.get("invoice_number_raw"))
        if not inum:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_inum",
                    suggested_table="exp",
                )
            )
            continue

        idt = _iso_to_ddmmyyyy(rec.get("invoice_date"))
        if not idt:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_idt",
                    suggested_table="exp",
                )
            )
            continue

        val = _invoice_value_rupees(rec)
        if val is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_val",
                    suggested_table="exp",
                )
            )
            continue

        sbnum = _coalesce_str(rec.get("shipping_bill_number"))
        sbpcode = _coalesce_str(rec.get("shipping_port_code"))
        sbdt_raw = rec.get("shipping_bill_date")
        sbdt_present = _coalesce_str(sbdt_raw) is not None
        if not sbnum or not sbpcode or not sbdt_present:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_shipping_bill_details",
                    suggested_table="exp",
                )
            )
            continue

        sbdt = _iso_to_ddmmyyyy(sbdt_raw)
        if not sbdt:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="invalid_shipping_bill_date",
                    suggested_table="exp",
                )
            )
            continue

        cgst = abs(_paise_to_rupees(rec.get("cgst_paise")) or 0.0)
        sgst = abs(_paise_to_rupees(rec.get("sgst_paise")) or 0.0)
        if (
            cgst > TAX_RATE_AMOUNT_TOLERANCE_RUPEES
            or sgst > TAX_RATE_AMOUNT_TOLERANCE_RUPEES
        ):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="export_has_cgst_or_sgst",
                    suggested_table="exp",
                )
            )
            continue

        typ_res = resolve_exp_typ_from_sr(
            export_type=rec.get("export_type"),
            export_type_raw=rec.get("export_type_raw"),
            igst_paise=rec.get("igst_paise"),
        )
        if typ_res.needs_review:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=typ_res.exp_typ,
                    reason=typ_res.reason,
                    suggested_table="exp",
                )
            )
            continue

        rt = _tax_rate(rec)
        if rt is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=typ_res.exp_typ,
                    reason="missing_tax_rate",
                    suggested_table="exp",
                )
            )
            continue

        txval = _paise_to_rupees(rec.get("taxable_amount_paise"))
        if txval is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=typ_res.exp_typ,
                    reason="missing_taxable_value",
                    suggested_table="exp",
                )
            )
            continue

        iamt = _paise_to_rupees(rec.get("igst_paise")) or 0.0
        csamt = _paise_to_rupees(rec.get("cess_paise")) or 0.0
        if not _tax_amount_matches_rate(txval, rt, iamt):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=typ_res.exp_typ,
                    reason="tax_amount_inconsistent_with_rate",
                    suggested_table="exp",
                )
            )
            continue

        assert typ_res.exp_typ in (EXP_TYP_WPAY, EXP_TYP_WOPAY)
        by_typ.setdefault(typ_res.exp_typ, []).append(
            _gstn_finalize_amounts(
                {
                    "inum": inum,
                    "idt": idt,
                    "val": val,
                    "sbpcode": sbpcode,
                    "sbnum": sbnum,
                    "sbdt": sbdt,
                    "itms": [
                        {
                            "txval": txval,
                            "rt": rt,
                            "iamt": iamt,
                            "csamt": csamt,
                        }
                    ],
                }
            )
        )

    # Stable order: WPAY then WOPAY.
    result.exp = [
        {"exp_typ": typ, "inv": invs}
        for typ in (EXP_TYP_WPAY, EXP_TYP_WOPAY)
        if typ in by_typ
        for invs in [by_typ[typ]]
    ]
    return result


def map_sales_register_to_gstr1_hsn(
    records: list[dict[str, Any]],
    *,
    filing_period: str,
) -> HSNMapResult:
    """Map SR taxable lines → Sandbox Table 12 ``hsn.hsn_b2b`` / ``hsn.hsn_b2c``.

    Aggregation key within each side: ``(hsn_sc, uqc, rt)``.

    Coverage policy (confirmed): any gap — missing HSN on a taxable line, or
    goods HSN without ``uqc``/``qty`` — emits a single ``NeedsExternalInput``
    and **blocks the entire HSN Save** (no partial). Services may default
    ``uqc=NA``, ``qty=0``. Malformed HSN codes → ``pending_review`` only.
    """
    period = (filing_period or "").strip()
    if len(period) != 7 or period[4] != "-" or not (
        period[:4].isdigit() and period[5:].isdigit()
    ):
        raise ValueError(
            f"filing_period must be YYYY-MM for HSN mapping; got {filing_period!r}"
        )
    result = HSNMapResult(filing_period=period)
    # Provisional aggregates — only emitted if no coverage gap.
    buckets: dict[tuple[str, str, str, float], dict[str, Any]] = {}
    coverage_gap = False
    coverage_reasons: set[str] = set()

    for rec in records:
        if not isinstance(rec, dict):
            continue
        if not _is_hsn_taxable_line(rec):
            result.skipped_non_hsn += 1
            continue

        result.taxable_line_count += 1
        derived = str(rec.get("invoice_type") or "").strip().upper()
        sign = -1.0 if derived == "CREDIT_NOTE" else 1.0

        hsn_sc, hsn_err = _normalize_hsn_code(rec.get("hsn"))
        if hsn_err == "missing_hsn":
            coverage_gap = True
            coverage_reasons.add("missing_hsn")
            result.coverage_gap_line_count += 1
            continue
        if hsn_err == "malformed_hsn_code":
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="malformed_hsn_code",
                    suggested_table="hsn",
                )
            )
            continue

        assert hsn_sc is not None
        uqc, qty, uqc_gap = _resolve_hsn_uqc_qty(rec, hsn_sc)
        if uqc_gap:
            coverage_gap = True
            coverage_reasons.add("missing_uqc_or_qty")
            result.coverage_gap_line_count += 1
            continue

        rt = _tax_rate(rec)
        if rt is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_tax_rate",
                    suggested_table="hsn",
                )
            )
            continue

        txval = _paise_to_rupees(rec.get("taxable_amount_paise"))
        if txval is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_taxable_value",
                    suggested_table="hsn",
                )
            )
            continue

        if not _sr_tax_reconciles_with_rate(rec):
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="tax_amount_inconsistent_with_rate",
                    suggested_table="hsn",
                )
            )
            continue

        assert uqc is not None and qty is not None
        side = _hsn_b2b_or_b2c(rec)
        key = (side, hsn_sc, uqc, rt)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "hsn_sc": hsn_sc,
                "desc": "",
                "uqc": uqc,
                "qty": 0.0,
                "rt": rt,
                "txval": 0.0,
                "iamt": 0.0,
                "camt": 0.0,
                "samt": 0.0,
                "csamt": 0.0,
            }
            buckets[key] = bucket

        bucket["qty"] += sign * qty
        bucket["txval"] += sign * txval
        bucket["iamt"] += sign * (_paise_to_rupees(rec.get("igst_paise")) or 0.0)
        bucket["camt"] += sign * (_paise_to_rupees(rec.get("cgst_paise")) or 0.0)
        bucket["samt"] += sign * (_paise_to_rupees(rec.get("sgst_paise")) or 0.0)
        bucket["csamt"] += sign * (_paise_to_rupees(rec.get("cess_paise")) or 0.0)

    if coverage_gap:
        if "missing_hsn" in coverage_reasons and "missing_uqc_or_qty" in coverage_reasons:
            reason = "sr_incomplete_hsn_coverage"
            missing_fields: tuple[str, ...] = ("hsn", "uqc", "qty")
        elif "missing_hsn" in coverage_reasons:
            reason = "sr_lacks_hsn_code"
            missing_fields = ("hsn",)
        else:
            reason = "sr_lacks_uqc_qty"
            missing_fields = ("uqc", "qty")
        result.needs_external_input = NeedsExternalInput(
            table="hsn",
            filing_period=period,
            reason=reason,
            message=(
                f"Table 12 blocked: {result.coverage_gap_line_count} of "
                f"{result.taxable_line_count} taxable SR lines lack HSN Save "
                f"fields ({reason}). Upload an HSN schedule."
            ),
            missing_fields=missing_fields,
        )
        result.hsn = {"hsn_b2b": [], "hsn_b2c": []}
        return result

    b2b: list[dict[str, Any]] = []
    b2c: list[dict[str, Any]] = []
    for key in sorted(buckets.keys(), key=lambda x: (x[0], x[1], x[2], x[3])):
        side, _hsn, _uqc, _rt = key
        bucket = buckets[key]
        if abs(bucket["txval"]) <= TAX_RATE_AMOUNT_TOLERANCE_RUPEES:
            continue
        if bucket["txval"] < -TAX_RATE_AMOUNT_TOLERANCE_RUPEES:
            result.pending_review.append(
                PendingReviewInvoice(
                    record={
                        "hsn_sc": bucket["hsn_sc"],
                        "uqc": bucket["uqc"],
                        "rt": bucket["rt"],
                        "net_txval": bucket["txval"],
                        "side": side,
                    },
                    proposed_inv_typ=None,
                    reason="hsn_net_negative_bucket",
                    suggested_table="hsn",
                )
            )
            continue
        row = _gstn_finalize_amounts(dict(bucket))
        if side == "hsn_b2b":
            b2b.append(row)
        else:
            b2c.append(row)

    for i, row in enumerate(b2b, start=1):
        row["num"] = i
    for i, row in enumerate(b2c, start=1):
        row["num"] = i

    result.hsn = {"hsn_b2b": b2b, "hsn_b2c": b2c}
    return result


def map_sales_register_to_gstr1_doc_issue(
    *,
    filing_period: str,
    b2b_save_count: int = 0,
    b2cs_save_count: int = 0,
    b2cl_save_count: int = 0,
    cdnr_save_count: int = 0,
    cdnur_save_count: int = 0,
    exp_save_count: int = 0,
) -> DocIssueMapResult:
    """Table 13 Documents Issued — envelope only; never invent series from SR.

    Does **not** read Sales Register rows, G1M8 continuity, or G1M10 summaries.
    Presence of any outward Save table data → one ``NeedsExternalInput`` and
    empty ``doc_issue`` (CA must supply a document series register / portal
    entry). True nil period (all outward Save counts zero) → omit ``doc_issue``
    with no external-input flag.
    """
    period = (filing_period or "").strip()
    if len(period) != 7 or period[4] != "-" or not (
        period[:4].isdigit() and period[5:].isdigit()
    ):
        raise ValueError(
            f"filing_period must be YYYY-MM for DOC_ISSUE mapping; got {filing_period!r}"
        )

    outward = (
        max(0, int(b2b_save_count))
        + max(0, int(b2cs_save_count))
        + max(0, int(b2cl_save_count))
        + max(0, int(cdnr_save_count))
        + max(0, int(cdnur_save_count))
        + max(0, int(exp_save_count))
    )
    result = DocIssueMapResult(filing_period=period, outward_save_count=outward)

    if outward <= 0:
        # True nil period — Table 13 gate does not apply.
        result.doc_issue = None
        result.needs_external_input = None
        return result

    result.doc_issue = None  # never invent; omit from Save payload
    result.needs_external_input = NeedsExternalInput(
        table="doc_issue",
        filing_period=period,
        reason="sr_has_no_document_series",
        message=(
            "Table 13 (Documents Issued) is required when outward supplies "
            "are filed, but Sales Register has no document-series / "
            "cancellation data. Do not invent from/to from invoice numbers. "
            "Upload a document series register or enter Table 13 on the portal "
            "before File."
        ),
        missing_fields=("doc_num", "from", "to", "totnum", "cancel", "net_issue"),
    )
    return result


def resolve_nil_amount_column_from_sr_raw(
    *,
    invoice_type: str | None = None,
    invoice_type_raw: str | None = None,
) -> tuple[Optional[str], str]:
    """Map SR type text → Table 8 column or a routing outcome.

    Returns ``(column, reason)`` where ``column`` is ``nil_amt`` / ``expt_amt`` /
    ``ngsup_amt`` when unambiguous, else ``None`` and ``reason`` is one of
    ``lump_nil_exempt_non_gst``, ``nil_bucket_ambiguous``, ``not_nil_class``.
    """
    derived = (invoice_type or "").strip().upper()
    raw = (invoice_type_raw or "").strip()
    norm = re.sub(r"\s+", " ", raw.lower()) if raw else ""

    if not norm and derived != "NIL_RATED":
        return None, "not_nil_class"
    if not norm and derived == "NIL_RATED":
        return None, "lump_nil_exempt_non_gst"

    # Explicit lump labels from books exports.
    if any(
        phrase in norm
        for phrase in (
            "nil rated/exempt",
            "nil/exempt",
            "nil rated / exempt",
            "nil & exempt",
            "nil and exempt",
            "exempt/nil",
        )
    ):
        return None, "lump_nil_exempt_non_gst"

    hit_nil = any(
        _keyword_match(norm, kw)
        for kw in ("nil rated", "nil-rated", "nilrated")
    ) or norm == "nil"
    hit_exempt = any(
        _keyword_match(norm, kw)
        for kw in ("exempt", "exempted", "exemption")
    )
    hit_nongst = any(
        _keyword_match(norm, kw)
        for kw in ("non gst", "non-gst", "nongst", "outside gst", "non gst supply")
    )

    hits = sum(1 for h in (hit_nil, hit_exempt, hit_nongst) if h)
    if hits > 1:
        return None, "nil_bucket_ambiguous"
    if hit_nil:
        return NIL_COL_NIL, "explicit_nil_rated"
    if hit_exempt:
        return NIL_COL_EXEMPT, "explicit_exempt"
    if hit_nongst:
        return NIL_COL_NON_GST, "explicit_non_gst"

    if derived == "NIL_RATED":
        # Derived lump with unrecognised / empty-ish raw after normalisation.
        return None, "lump_nil_exempt_non_gst"
    return None, "not_nil_class"


def map_sales_register_to_gstr1_nil(
    records: list[dict[str, Any]],
    *,
    filer_state: str,
    filing_period: str,
) -> NILMapResult:
    """Map SR nil-class rows → Sandbox ``nil.inv[]`` or external-input / review.

    Save only when every nil-class row has an unambiguous nil / exempt /
    non-GST label. Any lump label → one ``NeedsExternalInput`` and empty
    ``nil`` (no partial Save). No nil-class rows → omit ``nil`` cleanly.
    """
    state = require_filer_state(filer_state)
    period = (filing_period or "").strip()
    if len(period) != 7 or period[4] != "-" or not (
        period[:4].isdigit() and period[5:].isdigit()
    ):
        raise ValueError(
            f"filing_period must be YYYY-MM for NIL mapping; got {filing_period!r}"
        )

    result = NILMapResult(filer_state=state, filing_period=period)
    # sply_ty → running amounts
    buckets: dict[str, dict[str, float]] = {}
    has_lump = False
    has_ambiguous = False
    clear_valid = 0

    for rec in records:
        if not isinstance(rec, dict):
            continue

        derived = str(rec.get("invoice_type") or "").strip().upper()
        type_raw = _coalesce_str(rec.get("invoice_type_raw"))
        col, reason = resolve_nil_amount_column_from_sr_raw(
            invoice_type=derived, invoice_type_raw=type_raw,
        )

        if reason == "not_nil_class":
            result.skipped_non_nil += 1
            continue

        result.nil_class_line_count += 1

        if reason == "lump_nil_exempt_non_gst":
            has_lump = True
            result.lump_line_count += 1
            continue

        if reason == "nil_bucket_ambiguous" or col is None:
            has_ambiguous = True
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="nil_bucket_ambiguous",
                    suggested_table="nil",
                )
            )
            continue

        pos = _pos_code(rec.get("place_of_supply"))
        if not pos or pos not in _VALID_STATE_CODES:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_or_malformed_pos",
                    suggested_table="nil",
                )
            )
            continue

        gst_tax = abs(_sr_gst_tax_rupees(rec))
        if gst_tax > TAX_RATE_AMOUNT_TOLERANCE_RUPEES:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="nil_row_has_gst",
                    suggested_table="nil",
                )
            )
            continue

        txval = _paise_to_rupees(rec.get("taxable_amount_paise"))
        if txval is None:
            result.pending_review.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="missing_taxable_value",
                    suggested_table="nil",
                )
            )
            continue
        txval = abs(txval)

        gstin_ok = _counterparty_gstin_ok(rec)
        is_inter = pos != state
        if is_inter and gstin_ok:
            sply_ty = "INTERB2B"
        elif (not is_inter) and gstin_ok:
            sply_ty = "INTRB2B"
        elif is_inter and not gstin_ok:
            sply_ty = "INTERB2C"
        else:
            sply_ty = "INTRB2C"

        bucket = buckets.get(sply_ty)
        if bucket is None:
            bucket = {
                "sply_ty": sply_ty,
                NIL_COL_NIL: 0.0,
                NIL_COL_EXEMPT: 0.0,
                NIL_COL_NON_GST: 0.0,
            }
            buckets[sply_ty] = bucket
        bucket[col] += txval
        clear_valid += 1

    if result.nil_class_line_count == 0:
        result.nil = None
        return result

    if has_lump:
        result.needs_external_input = NeedsExternalInput(
            table="nil",
            filing_period=period,
            reason="sr_lumps_nil_exempt_non_gst",
            message=(
                f"Table 8 blocked: {result.lump_line_count} of "
                f"{result.nil_class_line_count} nil-class SR rows lack a "
                "clear nil / exempt / non-GST split. Upload a nil split worksheet."
            ),
            missing_fields=("nil_amt", "expt_amt", "ngsup_amt"),
        )
        result.nil = None
        return result

    # Save only when every nil-class row was unambiguous (no ambiguous pending
    # for split) and contributed or was held only for POS/tax/value issues.
    # Ambiguous labels block the whole table Save (confirmed policy).
    if has_ambiguous:
        result.nil = None
        return result

    # Field-level reviews (POS / GST / taxable) exclude those lines; remaining
    # clear lines may Save (labels were unambiguous on all nil-class rows).
    if clear_valid == 0:
        result.nil = None
        return result

    inv = [
        _gstn_finalize_amounts(buckets[k])
        for k in _NIL_SPLY_TYPES
        if k in buckets
    ]
    result.nil = {"inv": inv}
    return result


def map_sales_register_to_gstr1_at_txpd(
    records: list[dict[str, Any]],
    *,
    filing_period: str,
) -> AtTxpdMapResult:
    """Table 11 AT/TXPD — envelope only; never invent advance Save from SR.

    Coverage measurement (repo sample + typical synthetic): advance rows are
    **absent** in practice. When ``ADVANCES``-class rows appear, SR still is
    not an advance schedule (no AT vs TXPD split, unreliable pos/rt/ad_amt) —
    always ``NeedsExternalInput`` for both ``at`` and ``txpd``, never a Save
    fragment. No advance rows → omit both cleanly (no notice).
    """
    period = (filing_period or "").strip()
    if len(period) != 7 or period[4] != "-" or not (
        period[:4].isdigit() and period[5:].isdigit()
    ):
        raise ValueError(
            f"filing_period must be YYYY-MM for AT/TXPD mapping; got {filing_period!r}"
        )

    result = AtTxpdMapResult(filing_period=period)
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if not _is_advances_class_row(rec):
            continue
        result.advance_line_count += 1

    if result.advance_line_count == 0:
        result.at = None
        result.txpd = None
        return result

    # Never invent at[] / txpd[] from SR amounts.
    result.at = None
    result.txpd = None
    result.needs_external_input = [
        advances_unavailable_from_sr(
            period,
            table="at",
            reason="sr_lacks_advance_schedule",
            message=(
                f"Table 11 AT blocked: {result.advance_line_count} ADVANCES-class "
                "SR row(s) found, but Sales Register is not an advance schedule "
                "(no AT vs TXPD split). Upload an advances schedule or enter "
                "Table 11 on the portal."
            ),
        ),
        advances_unavailable_from_sr(
            period,
            table="txpd",
            reason="sr_lacks_advance_schedule",
            message=(
                f"Table 11 TXPD blocked: {result.advance_line_count} ADVANCES-class "
                "SR row(s) found, but Sales Register cannot supply tax-paid-on-"
                "advance adjustments. Upload an advances schedule or enter "
                "Table 11 on the portal."
            ),
        ),
    ]
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_advances_class_row(rec: dict[str, Any]) -> bool:
    derived = str(rec.get("invoice_type") or "").strip().upper()
    if derived == "ADVANCES":
        return True
    raw = _coalesce_str(rec.get("invoice_type_raw"))
    if not raw:
        return False
    norm = re.sub(r"\s+", " ", raw.lower())
    return any(
        _keyword_match(norm, kw)
        for kw in ("advance", "advances received", "advance receipt", "advances")
    )


_HSN_ELIGIBLE_TYPES: frozenset[str] = frozenset({
    "B2B", "B2C", "B2C_SMALL", "B2C_LARGE", "EXPORT",
    "CREDIT_NOTE", "DEBIT_NOTE",
})


def _is_hsn_taxable_line(rec: dict[str, Any]) -> bool:
    derived = str(rec.get("invoice_type") or "").strip().upper()
    if derived in {"NIL_RATED", "ADVANCES", "HSN_SUMMARY"}:
        return False
    return derived in _HSN_ELIGIBLE_TYPES


def _normalize_hsn_code(raw: Any) -> tuple[Optional[str], Optional[str]]:
    """Return ``(hsn_sc, None)`` or ``(None, reason)``."""
    if raw is None:
        return None, "missing_hsn"
    s = str(raw).strip()
    if not s:
        return None, "missing_hsn"
    digits = re.sub(r"[\s.\-/]", "", s)
    if not digits.isdigit():
        return None, "malformed_hsn_code"
    if len(digits) not in {4, 6, 8}:
        return None, "malformed_hsn_code"
    return digits, None


def _is_service_hsn(hsn_sc: str) -> bool:
    return hsn_sc.startswith("99")


def _resolve_hsn_uqc_qty(
    rec: dict[str, Any],
    hsn_sc: str,
) -> tuple[Optional[str], Optional[float], bool]:
    """Return ``(uqc, qty, is_coverage_gap)``."""
    uqc = _coalesce_str(rec.get("uqc"), rec.get("unit"), rec.get("unit_of_measure"))
    qty_raw = rec.get("qty")
    if qty_raw is None:
        qty_raw = rec.get("quantity")

    if _is_service_hsn(hsn_sc):
        if not uqc:
            uqc = "NA"
        if qty_raw is None or qty_raw == "":
            qty = 0.0
        else:
            try:
                qty = float(qty_raw)
            except (TypeError, ValueError):
                return None, None, True
        return uqc, qty, False

    if not uqc or qty_raw is None or qty_raw == "":
        return None, None, True
    try:
        qty = float(qty_raw)
    except (TypeError, ValueError):
        return None, None, True
    return uqc, qty, False


def _hsn_b2b_or_b2c(rec: dict[str, Any]) -> str:
    return "hsn_b2b" if _counterparty_gstin_ok(rec) else "hsn_b2c"


def _exp_typ_from_text(text: str) -> str | None:
    """Map export-type cell text → WPAY / WOPAY, or None if unrecognised."""
    norm = re.sub(r"\s+", " ", text.strip().lower())
    if not norm:
        return None
    hit_w = any(_keyword_match(norm, kw) for kw in _WPAY_KEYWORDS)
    hit_wo = any(_keyword_match(norm, kw) for kw in _WOPAY_KEYWORDS)
    if hit_w and not hit_wo:
        return EXP_TYP_WPAY
    if hit_wo and not hit_w:
        return EXP_TYP_WOPAY
    return None


def _exp_typ_from_igst(igst_paise: Any) -> str | None:
    """Tax-presence signal only: IGST paid → WPAY, zero → WOPAY."""
    if igst_paise is None:
        return None
    try:
        paise = int(igst_paise)
    except (TypeError, ValueError):
        return None
    # ±₹1 in paise terms for "zero".
    if abs(paise) <= int(TAX_RATE_AMOUNT_TOLERANCE_RUPEES * 100):
        return EXP_TYP_WOPAY
    return EXP_TYP_WPAY


def _looks_like_exp_invoice(rec: dict[str, Any]) -> bool:
    """True when the row is a Table-6A export candidate (not SEZ/DE B2B)."""
    derived = str(rec.get("invoice_type") or "").strip().upper()
    if derived == "EXPORT":
        return True
    pos = _pos_code(rec.get("place_of_supply"))
    if pos in {"96", "97"}:
        return True
    for key in (
        "export_type",
        "export_type_raw",
        "shipping_bill_number",
        "shipping_bill_date",
        "shipping_port_code",
    ):
        if _coalesce_str(rec.get(key)):
            return True
    type_raw = _coalesce_str(rec.get("invoice_type_raw"))
    if type_raw:
        norm = type_raw.lower()
        if "export" in norm or "expwp" in norm or "expwop" in norm:
            # Bare SEZ/DE wording without "export" is handled by B2B peel.
            if not _looks_like_sez_or_deemed(type_raw, None):
                return True
    return False


def _raw_ntty_hint(invoice_type_raw: str | None) -> str | None:
    """Return ``C``, ``D``, ``AMBIGUOUS``, or ``None`` (blank raw)."""
    if invoice_type_raw is None:
        return None
    norm = re.sub(r"\s+", " ", str(invoice_type_raw).strip().lower())
    if not norm:
        return None
    is_c = any(_keyword_match(norm, kw) for kw in _CREDIT_NOTE_RAW_KEYWORDS)
    is_d = any(_keyword_match(norm, kw) for kw in _DEBIT_NOTE_RAW_KEYWORDS)
    if is_c and not is_d:
        return "C"
    if is_d and not is_c:
        return "D"
    return "AMBIGUOUS"


def _raw_is_inv_typ_signal(invoice_type_raw: str | None) -> bool:
    """True when raw text carries B2B-style inv_typ wording (SEZ / regular / …)."""
    if not invoice_type_raw or not str(invoice_type_raw).strip():
        return False
    norm = re.sub(r"\s+", " ", str(invoice_type_raw).strip().lower())
    for _code, keywords in _INV_TYP_PATTERNS:
        for kw in keywords:
            if _keyword_match(norm, kw):
                return True
    for kw in _CLEAR_R_KEYWORDS:
        if _keyword_match(norm, kw):
            return True
    for kw in _AMBIGUOUS_SEZ_EXPORT_HINTS:
        if _keyword_match(norm, kw):
            return True
    return False


def _invoice_type_raw_for_inv_typ(invoice_type_raw: str | None) -> str | None:
    """Strip pure CN/DN labels so they do not fail the shared inv_typ resolver.

    ``\"Credit Note\"`` is an ``ntty`` signal, not an ``inv_typ`` signal. Passing
    it into ``resolve_inv_typ_from_sr_raw`` would yield
    ``unrecognised_invoice_type_raw``. If the same cell also carries SEZ/DE
    wording, keep the raw string for inv_typ.
    """
    if not invoice_type_raw or not str(invoice_type_raw).strip():
        return None
    hint = _raw_ntty_hint(invoice_type_raw)
    if hint in {"C", "D"} and not _raw_is_inv_typ_signal(invoice_type_raw):
        return None
    return invoice_type_raw


def _abs_paise_to_rupees(paise: Any) -> float | None:
    """Paise → rupees using absolute value (CN rows often store negatives)."""
    r = _paise_to_rupees(paise)
    if r is None:
        return None
    return abs(r)


def _abs_invoice_value_paise(rec: dict[str, Any]) -> int | None:
    """Absolute invoice value in paise (explicit total preferred)."""
    total = rec.get("total_amount_paise")
    if total is not None:
        try:
            return abs(int(total))
        except (TypeError, ValueError):
            pass
    return None


def _looks_like_cdnur_export(rec: dict[str, Any]) -> bool:
    """True when the note looks like an export UR type (deferred in v1)."""
    pos = _pos_code(rec.get("place_of_supply"))
    if pos in {"96", "97"}:
        return True
    derived = str(rec.get("invoice_type") or "").strip().upper()
    if derived == "EXPORT":
        return True
    for key in ("export_type", "export_type_raw", "shipping_bill_number", "shipping_port_code"):
        if _coalesce_str(rec.get(key)):
            return True
    type_raw = _coalesce_str(rec.get("invoice_type_raw"))
    if type_raw:
        norm = type_raw.lower()
        if "export" in norm or "expwp" in norm or "expwop" in norm:
            return True
    return False


def _b2cs_net_candidate_from_rec(
    rec: dict[str, Any],
    *,
    nt_num: str,
    ntty: str,
    pos: str,
    sply_ty: str,
    val_paise: int,
    tax_rate: float,
    reason: str,
) -> B2CSNetCandidate:
    """Snapshot absolute amount fields for ``apply_b2cs_netting``."""

    def _abs_int(key: str) -> int:
        v = rec.get(key)
        if v is None:
            return 0
        try:
            return abs(int(v))
        except (TypeError, ValueError):
            return 0

    return B2CSNetCandidate(
        record=rec,
        nt_num=nt_num,
        ntty=ntty,
        pos=pos,
        sply_ty=sply_ty,
        val_paise=val_paise,
        tax_rate=tax_rate,
        taxable_amount_paise=_abs_int("taxable_amount_paise"),
        igst_paise=_abs_int("igst_paise"),
        cgst_paise=_abs_int("cgst_paise"),
        sgst_paise=_abs_int("sgst_paise"),
        cess_paise=_abs_int("cess_paise"),
        reason=reason,
    )


def _sr_record_to_cdnr_nt(
    rec: dict[str, Any],
    *,
    ntty: str,
    inv_typ: str,
    filer_state: str,
) -> dict[str, Any] | str:
    """Build one CDNR ``nt`` object, or a pending_review reason string."""
    nt_num = _coalesce_str(rec.get("invoice_number_raw"))
    if not nt_num:
        return "missing_nt_num"

    nt_dt = _iso_to_ddmmyyyy(rec.get("invoice_date"))
    if not nt_dt:
        return "missing_or_invalid_nt_dt"

    pos = _pos_code(rec.get("place_of_supply"))
    if not pos or pos not in _VALID_STATE_CODES:
        return "missing_or_malformed_pos"

    is_inter = pos != filer_state
    if _interstate_flag_conflict(rec, is_inter=is_inter):
        return "interstate_flag_conflicts_with_pos"

    rt = _tax_rate(rec)
    if rt is None:
        return "missing_tax_rate"

    txval = _abs_paise_to_rupees(rec.get("taxable_amount_paise"))
    if txval is None:
        return "missing_taxable_value"

    val = _abs_paise_to_rupees(rec.get("total_amount_paise"))
    if val is None:
        return "missing_invoice_value"

    iamt = _abs_paise_to_rupees(rec.get("igst_paise")) or 0.0
    camt = _abs_paise_to_rupees(rec.get("cgst_paise")) or 0.0
    samt = _abs_paise_to_rupees(rec.get("sgst_paise")) or 0.0
    csamt = _abs_paise_to_rupees(rec.get("cess_paise")) or 0.0
    gst_tax = iamt + camt + samt

    if not _tax_amount_matches_rate(txval, rt, gst_tax):
        return "tax_amount_inconsistent_with_rate"

    return _gstn_finalize_amounts({
        "ntty": ntty,
        "nt_num": nt_num,
        "nt_dt": nt_dt,
        "pos": pos,
        "rchrg": _rchrg(rec.get("reverse_charge")),
        "inv_typ": inv_typ,
        "val": val,
        "itms": [
            {
                "num": 1,
                "itm_det": {
                    "rt": rt,
                    "txval": txval,
                    "iamt": iamt,
                    "camt": camt,
                    "samt": samt,
                    "csamt": csamt,
                },
            }
        ],
    })


def _is_b2c_candidate(rec: dict[str, Any]) -> bool:
    derived = str(rec.get("invoice_type") or "").strip().upper()
    if derived in _B2C_TYPES:
        return True
    if derived in _NON_B2C_TYPES:
        return False
    # Fallback: no valid recipient GSTIN → treat as B2C-ish for routing.
    return not _counterparty_gstin_ok(rec)


def _tax_rate(rec: dict[str, Any]) -> float | None:
    rate = rec.get("tax_rate")
    if rate is None:
        rate = rec.get("gst_rate")
    if rate is None:
        return None
    try:
        rt = float(rate)
    except (TypeError, ValueError):
        return None
    if rt != rt or rt < 0.0 or rt > 100.0:  # NaN / absurd
        return None
    return rt


def _tax_amount_matches_rate(
    txval_rupees: float,
    rate_pct: float,
    tax_rupees: float,
    *,
    tolerance_rupees: float = TAX_RATE_AMOUNT_TOLERANCE_RUPEES,
) -> bool:
    """True when ``tax ≈ txval × (rate/100)`` within ``tolerance_rupees``."""
    expected = txval_rupees * (rate_pct / 100.0)
    return abs(tax_rupees - expected) <= tolerance_rupees


def _sr_gst_tax_rupees(rec: dict[str, Any]) -> float:
    """IGST+CGST+SGST in rupees (cess excluded — not rate×taxable)."""
    return (
        (_paise_to_rupees(rec.get("igst_paise")) or 0.0)
        + (_paise_to_rupees(rec.get("cgst_paise")) or 0.0)
        + (_paise_to_rupees(rec.get("sgst_paise")) or 0.0)
    )


def _sr_tax_reconciles_with_rate(rec: dict[str, Any]) -> bool:
    """Shared B2B/B2CS gate: total GST vs taxable × rate (±₹1)."""
    rt = _tax_rate(rec)
    txval = _paise_to_rupees(rec.get("taxable_amount_paise"))
    if rt is None or txval is None:
        return False
    return _tax_amount_matches_rate(txval, rt, _sr_gst_tax_rupees(rec))


def _invoice_value_paise(rec: dict[str, Any]) -> int | None:
    total = rec.get("total_amount_paise")
    if total is not None:
        try:
            return int(total)
        except (TypeError, ValueError):
            pass
    taxable = rec.get("taxable_amount_paise")
    if taxable is None:
        return None
    try:
        base = int(taxable)
    except (TypeError, ValueError):
        return None
    tax = rec.get("total_tax_paise")
    if tax is None:
        tax = (
            int(rec.get("igst_paise") or 0)
            + int(rec.get("cgst_paise") or 0)
            + int(rec.get("sgst_paise") or 0)
            + int(rec.get("cess_paise") or 0)
        )
    else:
        try:
            tax = int(tax)
        except (TypeError, ValueError):
            tax = 0
    return base + tax


def _interstate_flag_conflict(rec: dict[str, Any], *, is_inter: bool) -> bool:
    """True when SR ``is_interstate`` disagrees with POS vs filer state."""
    flag = rec.get("is_interstate")
    if flag is None:
        return False
    if isinstance(flag, str):
        token = flag.strip().lower()
        if token in {"", "nan", "none"}:
            return False
        if token in {"y", "yes", "1", "true", "interstate", "inter"}:
            flag_bool: bool | None = True
        elif token in {"n", "no", "0", "false", "intrastate", "intra", "local"}:
            flag_bool = False
        else:
            return False
    elif isinstance(flag, bool):
        flag_bool = flag
    else:
        return False
    return flag_bool != is_inter

def _keyword_match(norm: str, kw: str) -> bool:
    if not kw:
        return False
    if norm == kw:
        return True
    if norm.startswith(kw + " ") or norm.startswith(kw + "("):
        return True
    # Whole-token containment for multi-word phrases inside longer labels.
    if " " in kw and kw in norm:
        return True
    # Single-token: require word boundary-ish match.
    if " " not in kw:
        return bool(re.search(rf"(?:^|[\s/(]){re.escape(kw)}(?:$|[\s)/])", norm))
    return False


def _looks_like_sez_or_deemed(
    invoice_type_raw: str | None,
    export_type_raw: str | None,
) -> bool:
    blob = " ".join(
        p for p in (
            (invoice_type_raw or "").strip().lower(),
            (export_type_raw or "").strip().lower(),
        ) if p
    )
    if not blob:
        return False
    for code, keywords in _INV_TYP_PATTERNS:
        if code in (INV_TYP_SEZWP, INV_TYP_SEZWOP, INV_TYP_DE, INV_TYP_CBW):
            for kw in keywords:
                if _keyword_match(blob, kw):
                    return True
    for hint in ("sez", "deemed export", "deemed exports"):
        if _keyword_match(blob, hint):
            return True
    return False


def _coalesce_str(*vals: Any) -> str | None:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _paise_to_rupees(paise: Any) -> float | None:
    if paise is None:
        return None
    try:
        return int(paise) / 100.0
    except (TypeError, ValueError):
        return None


def _pos_code(place_of_supply: Any) -> str | None:
    if place_of_supply is None:
        return None
    s = str(place_of_supply).strip()
    if not s:
        return None
    m = re.match(r"^(\d{2})", s)
    return m.group(1) if m else None


def _iso_to_ddmmyyyy(iso_date: Any) -> str | None:
    if iso_date is None:
        return None
    s = str(iso_date).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        y, m, d = s.split("-")
        return f"{d}-{m}-{y}"
    # Already DD-MM-YYYY
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", s):
        return s
    return None


def _rchrg(reverse_charge: Any) -> str:
    if reverse_charge is True:
        return "Y"
    return "N"


def _invoice_value_rupees(rec: dict[str, Any]) -> float | None:
    total = _paise_to_rupees(rec.get("total_amount_paise"))
    if total is not None:
        return total
    taxable = _paise_to_rupees(rec.get("taxable_amount_paise")) or 0.0
    tax = _paise_to_rupees(rec.get("total_tax_paise"))
    if tax is None:
        parts = [
            _paise_to_rupees(rec.get("igst_paise")) or 0.0,
            _paise_to_rupees(rec.get("cgst_paise")) or 0.0,
            _paise_to_rupees(rec.get("sgst_paise")) or 0.0,
            _paise_to_rupees(rec.get("cess_paise")) or 0.0,
        ]
        tax = sum(parts)
    if taxable == 0.0 and tax == 0.0 and rec.get("taxable_amount_paise") is None:
        return None
    return taxable + tax


def _sr_record_to_b2b_inv(
    rec: dict[str, Any],
    *,
    inv_typ: str,
) -> dict[str, Any] | None:
    inum = _coalesce_str(rec.get("invoice_number_raw"))
    if not inum:
        return None
    idt = _iso_to_ddmmyyyy(rec.get("invoice_date"))
    if not idt:
        return None
    pos = _pos_code(rec.get("place_of_supply"))
    if not pos:
        return None
    val = _invoice_value_rupees(rec)
    if val is None:
        return None
    txval = _paise_to_rupees(rec.get("taxable_amount_paise"))
    if txval is None:
        return None

    rate = rec.get("tax_rate")
    if rate is None:
        rate = rec.get("gst_rate")
    try:
        rt = float(rate) if rate is not None else None
    except (TypeError, ValueError):
        rt = None
    if rt is None:
        return None

    return _gstn_finalize_amounts({
        "inum": inum,
        "idt": idt,
        "val": val,
        "pos": pos,
        "rchrg": _rchrg(rec.get("reverse_charge")),
        "inv_typ": inv_typ,
        "itms": [
            {
                "num": 1,
                "itm_det": {
                    "rt": rt,
                    "txval": txval,
                    "iamt": _paise_to_rupees(rec.get("igst_paise")) or 0.0,
                    "camt": _paise_to_rupees(rec.get("cgst_paise")) or 0.0,
                    "samt": _paise_to_rupees(rec.get("sgst_paise")) or 0.0,
                    "csamt": _paise_to_rupees(rec.get("cess_paise")) or 0.0,
                },
            }
        ],
    })
