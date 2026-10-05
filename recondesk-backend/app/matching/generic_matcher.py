"""
Generic configurable matching engine for GST reconciliation.

Provides a 5-level matching hierarchy (L1 exact → L5 fuzzy) parameterised by
``MatchFieldsConfig`` so the same algorithm can drive both purchase-side
(GSTR-2B ↔ Purchase Register) and sales-side (Sales Register ↔ GSTR-1)
reconciliation without duplicating logic.

**This module does NOT modify or replace any existing files.** The existing
``app.services.matcher`` and ``app.services.reconciliation`` remain untouched;
this module imports proven helpers from them and wraps them behind a
configurable interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Mapping

# ──────────────────────────────────────────────────────────────────────────────
# Reuse proven utilities from the existing matcher — no reimplementation.
# Private helpers are imported intentionally: this module is the first step in
# an incremental refactoring that will eventually consolidate all matching
# behind this generic interface.
# ──────────────────────────────────────────────────────────────────────────────
from app.services.matcher import (
    # Constants / tolerances
    AMOUNT_TOLERANCE_L1_PAISE,
    AMOUNT_TOLERANCE_L2_PCT,
    AMOUNT_TOLERANCE_L3_PCT,
    DATE_TOLERANCE_L1_DAYS,
    DATE_TOLERANCE_L2_DAYS,
    DATE_TOLERANCE_L3_DAYS,
    TOTAL_TOLERANCE_PAISE,
    INVOICE_SIMILARITY_L5_MIN,
    FINANCIAL_MISMATCH_REASON,
    # Dataclass
    MatchResult,
    # Invoice helpers
    normalize_invoice,
    invoice_similarity,
    is_invoice_format_variant,
    is_sequential_series_mismatch,
    invoices_effectively_match,
    invoice_match_key_for_record,
    same_pan,
    levenshtein,
    # Field helpers (generic — no hardcoded field names)
    _field_entry,
    _safe_paise_field,
    _invoice_total_paise,
    _optional_taxable,
    _parse_invoice_date,
    _invoice_number,
    normalise_inv_no,
    _amount_diff_and_skip,
    _date_diff_days_and_skip,
    _compute_percentage_diff,
    _rs_str,
    _has_component_tax_breakdown,
    _has_explicit_total_tax_line,
    _crosses_gst_return_period,
    _format_gst_return_period_label,
    _format_invoice_date_label,
    _is_credit_note,
    _is_debit_note,
)
from app.services.vendor_name_matcher import (
    find_best_vendor_match,
    l1_vendor_name_ok,
    vendor_name_similarity,
)
from app.rules.gstr1_rules import GSTR1_INVOICE_DATE_TOLERANCE_DAYS



# ──────────────────────────────────────────────────────────────────────────────
# L5 thresholds — derived from the TYPO_MISMATCH path in reconciliation.py
# ──────────────────────────────────────────────────────────────────────────────
_L5_INVOICE_SIM_THRESHOLD = 0.75   # invoice_similarity floor for L5
_L5_DATE_TOLERANCE_DAYS = 45       # relaxed date window for fuzzy invoice


# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MatchFieldsConfig:
    """Declares which record fields carry the GSTIN, counterparty name, and
    human-readable labels for each side of a reconciliation pair.

    All other fields (``invoice_number``, ``taxable_amount_paise``, ``*_paise``,
    ``invoice_date``, etc.) are already standardised across all parsers and do
    not need per-context configuration.

    Naming convention: **side A** is the anchor record (the one being matched),
    **side B** is the candidate pool.

    * Purchase-side: A = GSTR-2B, B = Purchase Register
    * Sales-side:    A = Sales Register, B = GSTR-1
    """

    # --- Field name mapping ------------------------------------------------
    # GSTIN field lookup order on each side — tried left-to-right until a
    # non-empty value is found.  Supports parsers that use different key names
    # for the same logical field (e.g. PR uses ``supplier_gstin`` *or* ``gstin``).
    a_gstin_fields: tuple[str, ...]
    b_gstin_fields: tuple[str, ...]

    # Counterparty name field on each side.
    a_name_field: str
    b_name_field: str

    # --- Labels for human-readable output ----------------------------------
    a_label: str        # short side-A label in discrepancies (e.g. "GSTR", "SR")
    b_label: str        # short side-B label (e.g. "PR", "GSTR1")
    gstin_label: str    # label for GSTIN in discrepancies (e.g. "supplier_gstin")

    # --- Decision text (only the parts that differ between contexts) -------
    no_match_what: str
    no_match_why: str
    no_match_next: str
    gstin_typo_next: str
    period_mismatch_why: str
    financial_mismatch_next: str

    # When True, invoice identity does not require GSTIN equality. GSTIN
    # differences are reported as discrepancies / G1M7 on matched pairs
    # instead of forcing missing+extra double-counts.
    allow_gstin_mismatch: bool = False

    # Authoritative L1 date tolerance window in days
    date_tolerance_days: int = 3


# ──────────────────────────────────────────────────────────────────────────────
# Pre-built configs
# ──────────────────────────────────────────────────────────────────────────────

PURCHASE_MATCH_CONFIG = MatchFieldsConfig(
    a_gstin_fields=("supplier_gstin", "gstin"),
    b_gstin_fields=("supplier_gstin", "gstin"),
    a_name_field="supplier_name",
    b_name_field="vendor_name",
    a_label="GSTR",
    b_label="PR",
    gstin_label="supplier_gstin",
    no_match_what="No match found in purchase register",
    no_match_why="No PR record matches this GSTR invoice on any criteria",
    no_match_next=(
        "Check if supplier filed late. If missing, raise ITC risk flag "
        "and follow up with supplier."
    ),
    gstin_typo_next=(
        "Verify the correct GSTIN with the supplier before claiming this ITC."
    ),
    period_mismatch_why=(
        "GSTR-2B and purchase register dates fall in different filing "
        "periods — wrong-period ITC claim risk"
    ),
    financial_mismatch_next=(
        "Contact supplier to issue credit/debit note or verify correct invoice"
    ),
    date_tolerance_days=DATE_TOLERANCE_L1_DAYS,
)

SALES_MATCH_CONFIG = MatchFieldsConfig(
    a_gstin_fields=("gstin",),
    b_gstin_fields=("recipient_gstin", "gstin"),
    a_name_field="recipient_name",
    b_name_field="recipient_name",
    a_label="SR",
    b_label="GSTR1",
    gstin_label="recipient_gstin",
    no_match_what="No match found in GSTR-1 return",
    no_match_why=(
        "No GSTR-1 record matches this Sales Register invoice on any criteria"
    ),
    no_match_next=(
        "Verify if invoice was filed in GSTR-1. If missing, file or amend "
        "the return."
    ),
    gstin_typo_next=(
        "Verify the correct recipient GSTIN and amend GSTR-1 filing if needed."
    ),
    period_mismatch_why=(
        "Sales Register and GSTR-1 dates fall in different filing "
        "periods — wrong-period output tax risk"
    ),
    financial_mismatch_next=(
        "Review invoice details and amend GSTR-1 filing if needed"
    ),
    allow_gstin_mismatch=True,
    date_tolerance_days=GSTR1_INVOICE_DATE_TOLERANCE_DAYS,
)


# ══════════════════════════════════════════════════════════════════════════════
# Config-aware field accessors
# ══════════════════════════════════════════════════════════════════════════════

def _get_gstin(rec: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    """Extract GSTIN from *rec* by trying field names in *fields* order.

    Always ``strip().upper()``.  Placeholder tokens (``NA``, ``N/A``, blank)
    are treated as absent so B2C / unregistered rows share the same empty
    identity key instead of comparing as literal mismatched strings.
    """
    _absent = {
        "NA", "N/A", "N.A", "N.A.", "NONE", "NULL", "NIL", "-", "--", ".",
        "0", "UNREGISTERED", "URP",
    }
    for f in fields:
        v = rec.get(f)
        if v is None:
            continue
        s = str(v).strip().upper()
        if not s:
            continue
        collapsed = "".join(ch for ch in s if ch.isalnum())
        if s in _absent or collapsed in {"NA", "NIL", "NULL", "NONE", "URP"}:
            continue
        return s
    return ""


def _gstin_match(
    rec_a: Mapping[str, Any],
    rec_b: Mapping[str, Any],
    config: MatchFieldsConfig,
) -> bool:
    """True when both sides carry the same non-empty GSTIN."""
    a = _get_gstin(rec_a, config.a_gstin_fields)
    b = _get_gstin(rec_b, config.b_gstin_fields)
    return bool(a) and bool(b) and a.upper() == b.upper()


def _gstin_both_absent(
    rec_a: Mapping[str, Any],
    rec_b: Mapping[str, Any],
    config: MatchFieldsConfig,
) -> bool:
    """True when neither side has a GSTIN (B2CL / Export / unregistered)."""
    a = _get_gstin(rec_a, config.a_gstin_fields)
    b = _get_gstin(rec_b, config.b_gstin_fields)
    return not a and not b


def _gstin_identity_ok(
    rec_a: Mapping[str, Any],
    rec_b: Mapping[str, Any],
    config: MatchFieldsConfig,
) -> bool:
    """Identity gate for L1–L3: matching GSTIN, or both sides blank.

    When GSTIN is present on at least one side it remains the primary key
    (both must match). When both sides are empty/null — legitimate for
    B2CL and Export — identity falls through to invoice + amount + date.
    """
    return _gstin_match(rec_a, rec_b, config) or _gstin_both_absent(
        rec_a, rec_b, config
    )


def _get_name(rec: Mapping[str, Any], field_name: str) -> str:
    """Extract counterparty name from *rec*."""
    return str(rec.get(field_name) or "").strip()


def _extract_doc_number(rec: Mapping[str, Any]) -> str:
    """Extract invoice or credit/debit note number from a record."""
    for field in (
        "inum",
        "nt_num",
        "ntnum",
        "credit_note_number",
        "note_number",
        "invoice_number_raw",
        "invoice_number",
        "invoice_number_normalized",
    ):
        v = rec.get(field)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# Config-aware discrepancy / compared-fields builders
# ══════════════════════════════════════════════════════════════════════════════

def _build_discrepancies(
    rec_a: Mapping[str, Any],
    rec_b: Mapping[str, Any],
    *,
    ta: int | None,
    tb: int | None,
    da: date | None,
    db: date | None,
    amount_diff: int,
    date_diff_days: int,
    skip_amount: bool,
    skip_date: bool,
    config: MatchFieldsConfig,
) -> list[str]:
    """Config-aware version of ``build_discrepancies``."""
    out: list[str] = []
    a_inv = _invoice_number(rec_a)
    b_inv = _invoice_number(rec_b)
    a_gst = _get_gstin(rec_a, config.a_gstin_fields)
    b_gst = _get_gstin(rec_b, config.b_gstin_fields)

    if a_inv != b_inv:
        out.append(
            f"invoice_number: {config.a_label}={a_inv}, "
            f"{config.b_label}={b_inv}"
        )

    if a_gst != b_gst:
        out.append(
            f"{config.gstin_label}: {config.a_label}={a_gst}, "
            f"{config.b_label}={b_gst}"
        )

    if not skip_amount and ta is not None and tb is not None and amount_diff != 0:
        out.append(
            f"amount: {config.a_label}={_rs_str(ta)}, "
            f"{config.b_label}={_rs_str(tb)}, diff={_rs_str(amount_diff)}"
        )

    if not skip_date and da is not None and db is not None and date_diff_days != 0:
        signed = (db - da).days
        signed_str = (
            f"+{signed} day" if signed == 1
            else f"+{signed} days" if signed > 0
            else f"{signed} day" if signed == -1
            else f"{signed} days"
        )
        out.append(
            f"date: {config.a_label}={da.isoformat()}, "
            f"{config.b_label}={db.isoformat()}, diff={signed_str}"
        )
    elif skip_date and (da is not None or db is not None):
        da_s = da.isoformat() if da else "None"
        db_s = db.isoformat() if db else "None"
        if da_s != db_s:
            out.append(
                f"date: {config.a_label}={da_s}, "
                f"{config.b_label}={db_s}, diff={date_diff_days} days"
            )

    return out


def _append_financial_discrepancies(
    out: list[str],
    *,
    rec_a: Mapping[str, Any],
    rec_b: Mapping[str, Any],
    a_total: int,
    b_total: int,
    total_diff: int,
    tax_structure_match: bool,
    a_is_igst: bool,
    b_is_igst: bool,
    config: MatchFieldsConfig,
) -> None:
    """Config-aware version of ``_append_financial_discrepancies``."""
    is_cn = _is_credit_note(rec_a) or _is_credit_note(rec_b)
    diff_to_check = total_diff if is_cn else abs(a_total - b_total)
    if diff_to_check > AMOUNT_TOLERANCE_L1_PAISE and _has_explicit_total_tax_line(rec_a, rec_b):
        out.append(
            f"total_value: {config.a_label}={_rs_str(a_total)}, "
            f"{config.b_label}={_rs_str(b_total)}, diff={_rs_str(total_diff)}"
        )
    if not tax_structure_match:
        a_lbl = "IGST" if a_is_igst else "CGST+SGST"
        b_lbl = "IGST" if b_is_igst else "CGST+SGST"
        out.append(
            f"tax_structure: {config.a_label}={a_lbl}, {config.b_label}={b_lbl}"
        )


def _build_compared_fields(
    rec_a: Mapping[str, Any],
    rec_b: Mapping[str, Any],
    config: MatchFieldsConfig,
    *,
    invoice_sim_override: float | None = None,
) -> list[dict[str, Any]]:
    """Config-aware per-field comparison snapshot for the rationale drawer.

    Observational only — never feeds matching decisions.
    """
    out: list[dict[str, Any]] = []

    # ── GSTIN ────────────────────────────────────────────────────────────────
    a_gst = _get_gstin(rec_a, config.a_gstin_fields)
    b_gst = _get_gstin(rec_b, config.b_gstin_fields)
    gstin_exact = (
        bool(a_gst) and bool(b_gst) and a_gst.upper() == b_gst.upper()
    )
    if gstin_exact:
        out.append(_field_entry("gstin", "exact"))
    elif not a_gst and not b_gst:
        # Both blank (B2CL / Export) — not a mismatch; identity is invoice-based.
        out.append(_field_entry("gstin", "exact"))
    elif a_gst and b_gst and same_pan(a_gst, b_gst):
        out.append(_field_entry("gstin", "fuzzy"))
    elif a_gst and b_gst:
        dist = levenshtein(a_gst.upper(), b_gst.upper())
        if dist <= 2:
            max_len = max(len(a_gst), len(b_gst))
            score = (
                int(round((1.0 - dist / max_len) * 100)) if max_len else None
            )
            out.append(_field_entry("gstin", "fuzzy", score))
        else:
            out.append(_field_entry("gstin", "not_matched"))
    else:
        # One side present, other blank — identity mismatch.
        out.append(_field_entry("gstin", "not_matched"))

    # ── Document (Invoice / Credit Note / Debit Note) number ─────────────────
    a_inv = _invoice_number(rec_a)
    b_inv = _invoice_number(rec_b)
    a_doc = _extract_doc_number(rec_a) or a_inv
    b_doc = _extract_doc_number(rec_b) or b_inv
    is_cn = _is_credit_note(rec_a) or _is_credit_note(rec_b)
    is_dn = _is_debit_note(rec_a) or _is_debit_note(rec_b)
    doc_field_name = "credit_note_number" if is_cn else ("debit_note_number" if is_dn else "invoice_number")
    norm_a = normalise_inv_no(a_doc)
    norm_b = normalise_inv_no(b_doc)
    a_inv_raw = str(rec_a.get("invoice_number", "")).strip()
    b_inv_raw = str(rec_b.get("invoice_number", "")).strip()
    inv_ok = (
        bool(norm_a and norm_b and norm_a == norm_b)
        or invoices_effectively_match(a_doc, b_doc)
        or (invoices_effectively_match(a_inv, b_inv) if a_inv and b_inv else False)
    )
    raw_inv_ok = bool(
        (a_doc and b_doc and a_doc == b_doc)
        or (a_inv_raw and b_inv_raw and a_inv_raw == b_inv_raw)
    )
    format_variant = False
    if a_inv and b_inv and not inv_ok:
        format_variant = is_invoice_format_variant(
            a_inv, b_inv,
            rec_a.get("invoice_number"), rec_b.get("invoice_number"),
        )
    if (inv_ok or format_variant) and not raw_inv_ok:
        format_variant = True
    inv_sim = (
        float(invoice_sim_override)
        if invoice_sim_override is not None
        else (invoice_similarity(a_inv, b_inv) if a_inv and b_inv else 0.0)
    )
    if raw_inv_ok:
        out.append(_field_entry(doc_field_name, "exact"))
    elif format_variant or inv_ok or inv_sim >= INVOICE_SIMILARITY_L5_MIN:
        if not raw_inv_ok and (inv_ok or format_variant):
            score = 95
        else:
            score = int(round(inv_sim * 100)) if inv_sim > 0 else None
        out.append(_field_entry(doc_field_name, "fuzzy", score))
    else:
        score = int(round(inv_sim * 100)) if inv_sim > 0 else None
        out.append(_field_entry(doc_field_name, "not_matched", score))

    # ── Taxable amount ───────────────────────────────────────────────────────
    t_a = _optional_taxable(rec_a)
    t_b = _optional_taxable(rec_b)
    amt_diff, skip_amt = _amount_diff_and_skip(t_a, t_b)
    amt_pct = _compute_percentage_diff(amt_diff, skip_amt, t_a, t_b)
    if skip_amt or amt_diff <= AMOUNT_TOLERANCE_L1_PAISE:
        out.append(_field_entry("taxable_amount", "exact"))
    elif amt_pct <= AMOUNT_TOLERANCE_L3_PCT:
        out.append(
            _field_entry(
                "taxable_amount",
                "fuzzy",
                int(round(max(0.0, 1.0 - amt_pct) * 100)),
            )
        )
    else:
        out.append(_field_entry("taxable_amount", "not_matched"))

    # ── Date ─────────────────────────────────────────────────────────────────
    d_a = _parse_invoice_date(rec_a)
    d_b = _parse_invoice_date(rec_b)
    dd_days, skip_d = _date_diff_days_and_skip(d_a, d_b)
    if skip_d or dd_days == 0:
        out.append(_field_entry("date", "exact"))
    elif dd_days <= config.date_tolerance_days:
        out.append(_field_entry("date", "tolerance"))
    elif dd_days <= DATE_TOLERANCE_L3_DAYS:
        closeness = max(0.0, 1.0 - (dd_days / float(DATE_TOLERANCE_L3_DAYS)))
        out.append(_field_entry("date", "fuzzy", int(round(closeness * 100))))
    else:
        out.append(_field_entry("date", "not_matched"))

    # ── Counterparty name ────────────────────────────────────────────────────
    a_name = _get_name(rec_a, config.a_name_field)
    b_name = _get_name(rec_b, config.b_name_field)
    if a_name and b_name:
        if l1_vendor_name_ok(a_name, b_name):
            out.append(_field_entry("counterparty_name", "exact"))
        else:
            v_sim = vendor_name_similarity(a_name, b_name)
            if v_sim >= 0.70:
                out.append(
                    _field_entry(
                        "counterparty_name", "fuzzy", int(round(v_sim * 100))
                    )
                )
            else:
                out.append(
                    _field_entry(
                        "counterparty_name",
                        "not_matched",
                        int(round(v_sim * 100)) if v_sim > 0 else None,
                    )
                )

    return out


# ══════════════════════════════════════════════════════════════════════════════
# Financial downgrade safety net
# ══════════════════════════════════════════════════════════════════════════════

def _financial_downgrade(
    res: MatchResult,
    *,
    gstin_match: bool,
    total_diff: int,
    enforce_total_tolerance: bool,
    total_base_paise: int = 0,
    config: MatchFieldsConfig,
) -> MatchResult:
    """If L1-L3 and GSTIN/total safety fails, cap at L3 with mandatory review.

    Config-aware version of ``_financial_downgrade_l13`` from
    ``app.services.matcher``.
    """
    unsafe = not gstin_match
    gstin_unsafe = not gstin_match
    if enforce_total_tolerance:
        pct = (
            AMOUNT_TOLERANCE_L2_PCT
            if res.level == 2
            else AMOUNT_TOLERANCE_L3_PCT
        )
        level_total_tolerance = max(
            TOTAL_TOLERANCE_PAISE, int(total_base_paise * pct)
        )
        if total_diff > level_total_tolerance:
            unsafe = True
    if res.level not in (1, 2, 3) or not unsafe:
        return res
    if gstin_unsafe:
        review_reason = FINANCIAL_MISMATCH_REASON
    else:
        review_reason = (
            f"AMOUNT_MISMATCH: taxable/total-tax differs by "
            f"Rs {total_diff / 100:.2f}"
        )
    return MatchResult(
        level=max(res.level, 3),
        matched=True,
        confidence=75,
        requires_human_review=True,
        decision_what="Invoice matched but amount differs significantly",
        decision_why=(
            "Same invoice number but taxable amount differs by more than Rs100"
        ),
        decision_next=config.financial_mismatch_next,
        review_reason=review_reason,
        discrepancies=list(res.discrepancies),
        compared_fields=list(res.compared_fields),
        vendor_similarity_score=res.vendor_similarity_score,
        identity_confidence=res.identity_confidence,
        financial_status=res.financial_status,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Core pair-level matcher  (L1 → L5 → L6)
# ══════════════════════════════════════════════════════════════════════════════

def generic_match_pair(
    rec_a: Mapping[str, Any],
    rec_b: Mapping[str, Any],
    config: MatchFieldsConfig,
) -> MatchResult:
    """Score a single pair of records through the L1-L5 matching hierarchy.

    Logic-equivalent to ``_match_gstr_to_pr_pair`` in ``app.services.matcher``
    but with field names and labels driven by *config*.

    Additionally includes an L5 tier (fuzzy invoice similarity ≥ 0.75) which
    the existing pair matcher delegates to the orchestration layer.

    Parameters
    ----------
    rec_a : Mapping
        Record from side A (e.g. GSTR-2B row or Sales Register row).
    rec_b : Mapping
        Record from side B (e.g. Purchase Register row or GSTR-1 row).
    config : MatchFieldsConfig
        Field name / label configuration for this reconciliation context.
    """
    # ── Extract basic fields (generic across all contexts) ────────────────
    ta = _optional_taxable(rec_a)
    tb = _optional_taxable(rec_b)
    da = _parse_invoice_date(rec_a)
    db = _parse_invoice_date(rec_b)

    a_inv = _invoice_number(rec_a)
    b_inv = _invoice_number(rec_b)
    a_doc = _extract_doc_number(rec_a) or a_inv
    b_doc = _extract_doc_number(rec_b) or b_inv
    norm_a = normalise_inv_no(a_doc)
    norm_b = normalise_inv_no(b_doc)
    a_inv_raw = str(rec_a.get("invoice_number", "")).strip()
    b_inv_raw = str(rec_b.get("invoice_number", "")).strip()

    if not (norm_a or a_inv) or not (norm_b or b_inv):
        return MatchResult(
            level=6,
            matched=False,
            confidence=0,
            requires_human_review=False,
            decision_what=config.no_match_what,
            decision_why=(
                "Invoice number is missing on one or both sides — cannot match"
            ),
            decision_next="Check source data for missing invoice numbers.",
            discrepancies=[],
        )

    # ── GSTIN extraction (config-driven) ─────────────────────────────────
    a_gst = _get_gstin(rec_a, config.a_gstin_fields)
    b_gst = _get_gstin(rec_b, config.b_gstin_fields)

    # ── Numeric diffs ────────────────────────────────────────────────────
    amount_diff, skip_amount = _amount_diff_and_skip(ta, tb)
    date_diff_days, skip_date = _date_diff_days_and_skip(da, db)

    # Exact non-empty GSTIN equality (L4 typo / L5 fuzzy still require this).
    gstin_ok = _gstin_match(rec_a, rec_b, config)
    # L1–L3 identity: matching GSTIN, OR both blank (B2CL / Export).
    identity_ok = _gstin_identity_ok(rec_a, rec_b, config)
    a_total = _invoice_total_paise(rec_a)
    b_total = _invoice_total_paise(rec_b)
    total_diff = abs(abs(a_total) - abs(b_total))
    a_is_igst = abs(_safe_paise_field(rec_a, "igst_paise")) > 0
    b_is_igst = abs(_safe_paise_field(rec_b, "igst_paise")) > 0
    both_have_tax_breakdown = (
        _has_component_tax_breakdown(rec_a)
        and _has_component_tax_breakdown(rec_b)
    )
    tax_structure_match = (
        (a_is_igst == b_is_igst) if both_have_tax_breakdown else True
    )
    has_tax_lines = _has_explicit_total_tax_line(rec_a, rec_b)

    # ── Discrepancies ────────────────────────────────────────────────────
    discrepancies = _build_discrepancies(
        rec_a, rec_b,
        ta=ta, tb=tb, da=da, db=db,
        amount_diff=amount_diff, date_diff_days=date_diff_days,
        skip_amount=skip_amount, skip_date=skip_date,
        config=config,
    )
    _append_financial_discrepancies(
        discrepancies,
        rec_a=rec_a, rec_b=rec_b,
        a_total=a_total, b_total=b_total, total_diff=total_diff,
        tax_structure_match=tax_structure_match,
        a_is_igst=a_is_igst, b_is_igst=b_is_igst,
        config=config,
    )

    # ── Invoice identity checks ──────────────────────────────────────────
    inv_ok = (
        bool(norm_a and norm_b and norm_a == norm_b)
        or invoices_effectively_match(a_doc, b_doc)
        or invoices_effectively_match(a_inv, b_inv)
    )
    format_variant = False
    if not inv_ok:
        format_variant = (
            is_invoice_format_variant(
                a_inv, b_inv,
                rec_a.get("invoice_number"), rec_b.get("invoice_number"),
            )
            or is_invoice_format_variant(
                norm_a, norm_b,
                a_doc, b_doc,
            )
        )

    raw_inv_ok = bool(
        (a_doc and b_doc and a_doc == b_doc)
        or (a_inv_raw and b_inv_raw and a_inv_raw == b_inv_raw)
    )
    if inv_ok and not raw_inv_ok:
        format_variant = True
    amount_pct = _compute_percentage_diff(amount_diff, skip_amount, ta, tb)

    # ── Tolerance bands ──────────────────────────────────────────────────
    amount_within_l1 = skip_amount or (amount_diff <= AMOUNT_TOLERANCE_L1_PAISE)
    amount_within_l2 = skip_amount or (amount_pct <= AMOUNT_TOLERANCE_L2_PCT)
    amount_within_l3 = skip_amount or (amount_pct <= AMOUNT_TOLERANCE_L3_PCT)

    date_within_l1 = skip_date or (date_diff_days <= config.date_tolerance_days)
    date_within_l2 = skip_date or (date_diff_days <= DATE_TOLERANCE_L2_DAYS)
    date_within_l3 = skip_date or (date_diff_days <= DATE_TOLERANCE_L3_DAYS)

    crosses_return_period = (
        not skip_date and _crosses_gst_return_period(da, db)
    )

    # ── Observational snapshot (does NOT affect tier decisions) ───────────
    compared = _build_compared_fields(rec_a, rec_b, config)

    def _ret(**kwargs: Any) -> MatchResult:
        kwargs.setdefault("compared_fields", compared)
        return MatchResult(**kwargs)

    # ── Financial severity classification ────────────────────────────────
    financial_status = "Exact"
    if not tax_structure_match:
        financial_status = "Tax Mismatch"
    elif not skip_amount and amount_diff > AMOUNT_TOLERANCE_L1_PAISE:
        financial_status = "Amount Mismatch"
    elif has_tax_lines and total_diff > TOTAL_TOLERANCE_PAISE:
        financial_status = "Tax Mismatch"
    elif not skip_amount and amount_diff > 0:
        financial_status = "Round-off"

    l12_finance_ok = financial_status in ("Exact", "Round-off")

    # ── Counterparty name guard ──────────────────────────────────────────
    a_name = _get_name(rec_a, config.a_name_field)
    b_name = _get_name(rec_b, config.b_name_field)
    _names_present = bool(a_name and b_name)
    _name_ok = not _names_present or l1_vendor_name_ok(a_name, b_name)
    if not _name_ok:
        discrepancies.append(
            f"counterparty_name: {config.a_label}={a_name!r}, "
            f"{config.b_label}={b_name!r}"
        )

    # ══════════════════════════════════════════════════════════════════════
    # PERIOD-BOUNDARY DATE MISMATCH
    # ══════════════════════════════════════════════════════════════════════
    if crosses_return_period and identity_ok and (inv_ok or format_variant):
        a_period = _format_gst_return_period_label(da)
        b_period = _format_gst_return_period_label(db)
        a_date_label = _format_invoice_date_label(da)
        b_date_label = _format_invoice_date_label(db)
        period_discrepancies = list(discrepancies) + [
            f"return_period: {config.a_label}={a_period} ({a_date_label}), "
            f"{config.b_label}={b_period} ({b_date_label}), "
            f"diff={date_diff_days} days"
        ]
        return _ret(
            level=2,
            matched=True,
            confidence=75,
            requires_human_review=True,
            decision_what=(
                f"Invoice date crosses GST return period "
                f"({config.a_label}: {a_period}, {config.b_label}: {b_period})"
            ),
            decision_why=config.period_mismatch_why,
            decision_next=(
                f"Confirm correct return period: {config.a_label} date "
                f"{a_date_label} ({a_period}) vs {config.b_label} date "
                f"{b_date_label} ({b_period}). File in the correct period."
            ),
            discrepancies=period_discrepancies,
            identity_confidence="High",
            financial_status=financial_status,
            review_reason="PERIOD_BOUNDARY_DATE_MISMATCH",
        )

    # ══════════════════════════════════════════════════════════════════════
    # ZERO-DISCREPANCY INVARIANT
    # ══════════════════════════════════════════════════════════════════════
    a_total_tax = _safe_paise_field(rec_a, "total_tax_paise")
    b_total_tax = _safe_paise_field(rec_b, "total_tax_paise")
    tax_only_diff = abs(abs(a_total_tax) - abs(b_total_tax))
    zero_discrepancy = (
        not skip_amount
        and amount_diff <= AMOUNT_TOLERANCE_L1_PAISE
        and tax_only_diff <= AMOUNT_TOLERANCE_L1_PAISE
    )
    if (
        identity_ok
        and (inv_ok or format_variant)
        and _name_ok
        and zero_discrepancy
        and date_within_l1
        and tax_structure_match
    ):
        delta_days = (db - da).days if (da and db) else date_diff_days
        delta_str = (
            f"+{delta_days} day" if delta_days == 1
            else f"+{delta_days} days" if delta_days > 0
            else f"{delta_days} day" if delta_days == -1
            else f"{delta_days} days"
        )
        if raw_inv_ok:
            if not skip_date and date_diff_days != 0:
                return _ret(
                    level=1, matched=True, confidence=100,
                    requires_human_review=False,
                    decision_what="Matched within date tolerance",
                    decision_why=(
                        f"Invoice number and amount align; date difference is {delta_str} "
                        f"(within {config.date_tolerance_days}-day tolerance)"
                    ),
                    decision_next="No action required",
                    discrepancies=discrepancies,
                    identity_confidence="High", financial_status="Exact",
                    review_reason="DATE_TOLERANCE_MATCH",
                )
            return _ret(
                level=1, matched=True, confidence=100,
                requires_human_review=False,
                decision_what="Exact match found",
                decision_why="Invoice number, amount, and date align",
                decision_next="No action required",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status="Exact",
                review_reason=None,
            )
        why_text = (
            "Invoice numbers match after normalization or format variant; amounts and dates align"
            if (skip_date or date_diff_days == 0)
            else (
                f"Invoice numbers match after normalization or format variant; amounts align; "
                f"date difference is {delta_str} (within {config.date_tolerance_days}-day tolerance)"
            )
        )
        what_text = (
            "Normalized invoice match"
            if (skip_date or date_diff_days == 0)
            else "Normalized invoice match (within date tolerance)"
        )
        return _ret(
            level=2, matched=True, confidence=95,
            requires_human_review=False,
            decision_what=what_text,
            decision_why=why_text,
            decision_next=(
                "No action required — formatting differs, amounts align"
            ),
            discrepancies=discrepancies,
            identity_confidence="High", financial_status="Exact",
            review_reason="DATE_TOLERANCE_MATCH" if not skip_date and date_diff_days != 0 else None,
        )

    # ══════════════════════════════════════════════════════════════════════
    # TIER 1 — Identity OK + exact raw invoice + amount/date within L1
    # Identity = same GSTIN, or both GSTINs blank (B2CL / Export).
    # ══════════════════════════════════════════════════════════════════════
    if identity_ok and raw_inv_ok and _name_ok:
        if amount_within_l1 and date_within_l1 and l12_finance_ok:
            delta_days = (db - da).days if (da and db) else date_diff_days
            delta_str = (
                f"+{delta_days} day" if delta_days == 1
                else f"+{delta_days} days" if delta_days > 0
                else f"{delta_days} day" if delta_days == -1
                else f"{delta_days} days"
            )
            if not skip_date and date_diff_days != 0:
                return _ret(
                    level=1, matched=True, confidence=100,
                    requires_human_review=False,
                    decision_what="Matched within date tolerance",
                    decision_why=(
                        f"Invoice number and amount align; date difference is {delta_str} "
                        f"(within {config.date_tolerance_days}-day tolerance)"
                    ),
                    decision_next="No action required",
                    discrepancies=discrepancies,
                    identity_confidence="High", financial_status=financial_status,
                    review_reason="DATE_TOLERANCE_MATCH",
                )
            return _ret(
                level=1, matched=True, confidence=100,
                requires_human_review=False,
                decision_what="Exact match found",
                decision_why="Invoice number, amount, and date align",
                decision_next="No action required",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
                review_reason=None,
            )
        # Same raw invoice + identity ok + vendor ok but financial mismatch —
        # fall through to L2/L3 for human review.

    # ══════════════════════════════════════════════════════════════════════
    # DATE OUTSIDE TOLERANCE — Invoice & financial align, but date > tolerance
    # (Does not cross return period; those are handled by period boundary check)
    # ══════════════════════════════════════════════════════════════════════
    if (
        identity_ok
        and (inv_ok or format_variant)
        and _name_ok
        and amount_within_l1
        and l12_finance_ok
        and not date_within_l1
    ):
        delta_days = (db - da).days if (da and db) else date_diff_days
        delta_str = (
            f"+{delta_days} day" if delta_days == 1
            else f"+{delta_days} days" if delta_days > 0
            else f"{delta_days} day" if delta_days == -1
            else f"{delta_days} days"
        )
        return _ret(
            level=2,
            matched=True,
            confidence=85,
            requires_human_review=True,
            decision_what=f"Invoice date difference outside tolerance ({delta_str})",
            decision_why=(
                f"Invoice number and amount align; date difference is {delta_str} "
                f"(exceeds {config.date_tolerance_days}-day tolerance). "
                f"Review required before filing."
            ),
            decision_next="Verify correct invoice date between books and return, and amend if needed.",
            discrepancies=discrepancies,
            identity_confidence="High",
            financial_status=financial_status,
            review_reason="DATE_OUTSIDE_TOLERANCE",
        )

    # ══════════════════════════════════════════════════════════════════════
    # TIER 2 — Identity OK + normalised invoice match
    # ══════════════════════════════════════════════════════════════════════
    if identity_ok and inv_ok:
        if amount_within_l2 and date_within_l2 and tax_structure_match:
            delta_days = (db - da).days if (da and db) else date_diff_days
            delta_str = (
                f"+{delta_days} day" if delta_days == 1
                else f"+{delta_days} days" if delta_days > 0
                else f"{delta_days} day" if delta_days == -1
                else f"{delta_days} days"
            )
            if not date_within_l1:
                rr = "DATE_OUTSIDE_TOLERANCE"
                what_msg = f"Invoice date difference outside tolerance ({delta_str})"
                why_msg = (
                    f"Same invoice and GSTIN, amount aligns within tolerance, but date difference is {delta_str} "
                    f"(exceeds {config.date_tolerance_days}-day tolerance). Review required before filing."
                )
            else:
                rr = "Amount/Date mismatch"
                what_msg = "Invoice matched with normalized invoice and minor amount difference"
                why_msg = "Same normalized invoice and GSTIN, amount within acceptable tolerance"
            return _ret(
                level=2, matched=True, confidence=90,
                requires_human_review=True,
                decision_what=what_msg,
                decision_why=why_msg,
                decision_next="Verify if needed",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
                review_reason=rr,
            )

        # Identity ok + same normalised invoice but amount or date exceeds
        # L2 — link as L3 review. Exact invoice identity is never rejected.
        if not tax_structure_match or not l12_finance_ok or not amount_within_l2:
            rr = "AMOUNT_MISMATCH"
        elif not date_within_l1:
            rr = "DATE_OUTSIDE_TOLERANCE"
        else:
            rr = "Amount Mismatch or Date mismatch"
        return _ret(
            level=3, matched=True, confidence=75,
            requires_human_review=True,
            decision_what="Invoice matched but with differences",
            decision_why=(
                "Same invoice number and GSTIN, but amount or date differ"
            ),
            decision_next="Review differences and correct if needed",
            review_reason=rr,
            discrepancies=discrepancies,
            identity_confidence="High", financial_status=financial_status,
        )

    # ══════════════════════════════════════════════════════════════════════
    # TIER 3 — Identity OK + format-variant invoice
    # ══════════════════════════════════════════════════════════════════════
    if identity_ok and format_variant:
        # Guard: weak invoice identity cannot be rescued by L3 when date difference
        # is large (> date tolerance) and amount/tax-profile difference is material.
        has_large_date_diff = not date_within_l1
        has_material_financial_diff = (
            not amount_within_l1
            or not tax_structure_match
            or not l12_finance_ok
        )
        if has_large_date_diff and has_material_financial_diff:
            # Cannot match: weak invoice identity cannot be rescued by L3 when
            # date difference is large and amount/tax-profile difference is material.
            pass
        elif amount_within_l3 and date_within_l3:
            return _ret(
                level=3, matched=True, confidence=75,
                requires_human_review=True,
                decision_what="Format variant with amount or date mismatch",
                decision_why=(
                    "Invoice format matches, amount/date within L3 tolerances"
                ),
                decision_next="Review differences",
                review_reason="Amount Mismatch or Date mismatch",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
            )

    # ══════════════════════════════════════════════════════════════════════
    # TIER 4 — Same-PAN GSTIN typo + same/near invoice
    # ══════════════════════════════════════════════════════════════════════
    if (
        not gstin_ok
        and same_pan(a_gst, b_gst)
        and (inv_ok or format_variant)
        and amount_within_l2
    ):
        return _ret(
            level=4, matched=False, confidence=50,
            requires_human_review=True,
            decision_what="Possible GSTIN typo",
            decision_why=(
                "Same PAN and invoice number, but GSTIN "
                "check-digit/state-code differs"
            ),
            decision_next=config.gstin_typo_next,
            review_reason="GSTIN_MISMATCH: same PAN, different GSTIN",
            discrepancies=discrepancies,
            identity_confidence="Medium", financial_status=financial_status,
        )

    # ══════════════════════════════════════════════════════════════════════
    # TIER 5 — Same GSTIN + fuzzy invoice (similarity ≥ 0.75)
    # Catches typos, OCR errors, and digit transpositions in invoice
    # numbers. Always requires human review.
    # Disqualified if invoices represent distinct sequential numbers
    # in the same series (e.g. INV/25-26/0101 vs INV/25-26/0197).
    # ══════════════════════════════════════════════════════════════════════
    if gstin_ok and not inv_ok and not format_variant:
        if not is_sequential_series_mismatch(a_inv, b_inv, a_inv_raw, b_inv_raw):
            inv_sim = invoice_similarity(a_inv, b_inv)
            if inv_sim >= _L5_INVOICE_SIM_THRESHOLD:
                date_within_l5 = skip_date or (
                    date_diff_days <= _L5_DATE_TOLERANCE_DAYS
                )
                if amount_within_l3 and date_within_l5:
                    return _ret(
                        level=5, matched=True, confidence=60,
                        requires_human_review=True,
                        decision_what="Fuzzy invoice match — possible typo",
                        decision_why=(
                            f"Same GSTIN, invoice similarity "
                            f"{inv_sim:.0%}, amount and date within tolerance"
                        ),
                        decision_next=(
                            "Verify invoice numbers match with counterparty"
                        ),
                        review_reason="TYPO_MISMATCH",
                        discrepancies=discrepancies,
                        identity_confidence="Low",
                        financial_status=financial_status,
                    )

    # ══════════════════════════════════════════════════════════════════════
    # L6 — No match
    # ══════════════════════════════════════════════════════════════════════
    what = config.no_match_what
    why = config.no_match_why
    next_step = config.no_match_next
    if _is_credit_note(rec_a):
        doc_no = _extract_doc_number(rec_a) or a_inv or "Credit Note"
        what = f"Credit Note {doc_no} is present in the Sales Register but is missing from GSTR-1."
        why = (
            "The Credit Note has been recorded in the Sales Register but no "
            "corresponding Credit Note was found in the GSTR-1 data for this return period."
        )
        next_step = (
            f"Verify whether Credit Note {doc_no} was reported in GSTR-1. "
            f"If it was not reported, review the filing and amendment requirements."
        )
    elif _is_debit_note(rec_a):
        doc_no = _extract_doc_number(rec_a) or a_inv or "Debit Note"
        what = f"Debit Note {doc_no} is present in the Sales Register but is missing from GSTR-1."
        why = (
            "The Debit Note has been recorded in the Sales Register but no "
            "corresponding Debit Note was found in the GSTR-1 data for this return period."
        )
        next_step = (
            f"Verify whether Debit Note {doc_no} was reported in GSTR-1. "
            f"If it was not reported, review the filing and amendment requirements."
        )

    return _ret(
        level=6, matched=False, confidence=0,
        requires_human_review=False,
        decision_what=what,
        decision_why=why,
        decision_next=next_step,
        discrepancies=discrepancies,
        identity_confidence="None", financial_status="None",
    )


# ══════════════════════════════════════════════════════════════════════════════
# One-to-many candidate selector
# ══════════════════════════════════════════════════════════════════════════════

def generic_match_one_to_many(
    rec_a: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    config: MatchFieldsConfig,
) -> MatchResult | None:
    """Compare one record against many candidates; return the best match.

    Logic-equivalent to ``match_gstr_to_pr`` in ``app.services.matcher``:

    * Chooses the candidate with the **lowest** ``level`` (L1 preferred over
      L5), then **highest** ``confidence`` on ties.
    * Unmatched candidates (L6) are ignored; returns ``None`` if no match.
    * Applies the financial downgrade safety net before returning.

    Parameters
    ----------
    rec_a : Mapping
        The anchor record from side A.
    candidates : list[Mapping]
        All candidate records from side B to compare against.
    config : MatchFieldsConfig
        Field name / label configuration for this reconciliation context.
    """
    assert isinstance(candidates, list)
    if not candidates:
        return None

    scored: list[dict[str, Any]] = []
    for rec_b in candidates:
        r = generic_match_pair(rec_a, rec_b, config)
        if r is None or not r.matched:
            continue

        # Date-signal scoring (identical to existing match_gstr_to_pr)
        score = 0
        reasons: list[str] = []
        is_late_filing = False
        original_period = None
        a_date = _parse_invoice_date(rec_a)
        b_date = _parse_invoice_date(rec_b)
        if a_date and b_date:
            date_diff = abs((a_date - b_date).days)
            if date_diff == 0:
                score += 20
                reasons.append("exact_date_match")
            elif date_diff <= 1:
                score += 5
                reasons.append("near_date_match")
            elif date_diff <= 90:
                score += 8
                reasons.append("possible_late_filing")
                # Mark late filing ONLY if strong match on other fields
                a_gstin = _get_gstin(rec_a, config.a_gstin_fields)
                b_gstin = _get_gstin(rec_b, config.b_gstin_fields)
                inv_ident_ok = (
                    invoices_effectively_match(
                        _extract_doc_number(rec_a), _extract_doc_number(rec_b)
                    )
                    or (
                        invoice_match_key_for_record(rec_a)
                        == invoice_match_key_for_record(rec_b)
                    )
                )
                if (
                    inv_ident_ok
                    and a_gstin == b_gstin
                    and abs(
                        abs(int(_optional_taxable(rec_a) or 0))
                        - abs(int(_optional_taxable(rec_b) or 0))
                    )
                    <= 100
                ):
                    is_late_filing = True
                    original_period = b_date
            else:
                score -= 5
                reasons.append("date_mismatch")
        else:
            score -= 2
            reasons.append("missing_date")

        rank_key = (
            r.level,
            -r.confidence,
            -score,
            str(rec_b.get("id", "")),
        )
        scored.append({
            "rec_b": rec_b,
            "r": r,
            "reasons": reasons,
            "date_signal": score,
            "is_late_filing": is_late_filing,
            "original_period": original_period,
            "rank_key": rank_key,
            "score": (-r.level, r.confidence, score),
        })

    if not scored:
        return None

    # ── Filter strong identity matches ───────────────────────────────────
    a_gstin = _get_gstin(rec_a, config.a_gstin_fields)
    strong_matches = [
        c for c in scored
        if (
            (
                invoices_effectively_match(
                    _extract_doc_number(c["rec_b"]), _extract_doc_number(rec_a)
                )
                or (
                    invoice_match_key_for_record(c["rec_b"])
                    == invoice_match_key_for_record(rec_a)
                )
            )
            and _get_gstin(c["rec_b"], config.b_gstin_fields) == a_gstin
            and abs(
                abs(int(_optional_taxable(c["rec_b"]) or 0))
                - abs(int(_optional_taxable(rec_a) or 0))
            )
            <= 100
        )
    ]

    if strong_matches:
        # Prefer earliest invoice date (original filing)
        def get_date(c: dict[str, Any]) -> str:
            v = c["rec_b"].get("invoice_date")
            if v is None or v == "":
                return "9999-12-31"
            if isinstance(v, date):
                return v.isoformat()
            return str(v)

        best_candidate = min(strong_matches, key=get_date)

        b_date_sel = _parse_invoice_date(best_candidate["rec_b"])
        a_date_sel = _parse_invoice_date(rec_a)
        if b_date_sel and a_date_sel:
            gap_days = abs((a_date_sel - b_date_sel).days)
            is_late_filing_sel = gap_days > 7
        else:
            is_late_filing_sel = False
        original_period_sel = b_date_sel
    else:
        # Fallback: normal scoring (level → confidence → date signal)
        best_scored = max(scored, key=lambda x: x["score"])
        tied = [c for c in scored if c["score"] == best_scored["score"]]
        if len(tied) > 1 and tied[0]["r"].level == 5:
            # L5 tiebreaker: counterparty name similarity
            vendor_pick = find_best_vendor_match(
                _get_name(rec_a, config.a_name_field),
                [
                    {
                        "vendor_name": _get_name(
                            c["rec_b"], config.b_name_field
                        ),
                        "record": c["rec_b"],
                    }
                    for c in tied
                ],
                threshold=0.82,
            )
            if vendor_pick is not None:
                picked_rec_b = vendor_pick["record"]
                best_candidate = next(
                    c for c in tied if c["rec_b"] is picked_rec_b
                )
                best_candidate = {
                    **best_candidate,
                    "r": replace(
                        best_candidate["r"],
                        vendor_similarity_score=vendor_pick[
                            "vendor_similarity_score"
                        ],
                    ),
                }
            else:
                best_candidate = min(tied, key=lambda x: x["rank_key"])
        else:
            best_candidate = min(tied, key=lambda x: x["rank_key"])
        is_late_filing_sel = best_candidate["is_late_filing"]
        original_period_sel = best_candidate["original_period"]

    final = replace(
        best_candidate["r"],
        is_late_filing=is_late_filing_sel,
        original_period=original_period_sel,
    )

    # ── Financial safety net ─────────────────────────────────────────────
    rec_b_sel = best_candidate["rec_b"]
    sel_a_total = _invoice_total_paise(rec_a)
    sel_b_total = _invoice_total_paise(rec_b_sel)
    total_diff_sel = abs(abs(sel_a_total) - abs(sel_b_total))
    # Both-blank GSTIN is identity-safe (B2CL / Export); do not downgrade.
    gstin_match_sel = _gstin_identity_ok(rec_a, rec_b_sel, config)
    enforce = bool(
        final.level >= 2
        and (
            _safe_paise_field(rec_a, "total_tax_paise") != 0
            or _safe_paise_field(rec_b_sel, "total_tax_paise") != 0
        )
    )
    return _financial_downgrade(
        final,
        gstin_match=gstin_match_sel,
        total_diff=total_diff_sel,
        enforce_total_tolerance=enforce,
        total_base_paise=max(abs(sel_a_total), abs(sel_b_total)),
        config=config,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Convenience wrappers
# ══════════════════════════════════════════════════════════════════════════════

def match_sales_register_to_gstr1(
    sr_rec: Mapping[str, Any],
    gstr1_candidates: list[Mapping[str, Any]],
) -> MatchResult | None:
    """Match one Sales Register record against GSTR-1 candidates.

    Convenience wrapper around :func:`generic_match_one_to_many` pre-configured
    for sales-side reconciliation (``SALES_MATCH_CONFIG``).

    Parameters
    ----------
    sr_rec : Mapping
        A normalised Sales Register record (from ``sales_register_parser``).
        Expected fields: ``gstin``, ``recipient_name``, ``invoice_number``,
        ``invoice_number_normalized``, ``invoice_date``,
        ``taxable_amount_paise``, ``igst_paise``, ``cgst_paise``,
        ``sgst_paise``, ``cess_paise``, ``total_tax_paise``.
    gstr1_candidates : list[Mapping]
        GSTR-1 records to search (from ``gstr1_parser``).
        Expected fields: ``recipient_gstin``, ``recipient_name``,
        ``invoice_number``, ``invoice_number_normalized``, ``invoice_date``,
        ``taxable_amount_paise``, ``igst_paise``, ``cgst_paise``,
        ``sgst_paise``, ``cess_paise``, ``total_tax_paise``.
    """
    return generic_match_one_to_many(sr_rec, gstr1_candidates, SALES_MATCH_CONFIG)


def match_purchase_gstr2b_to_pr(
    gstr_rec: Mapping[str, Any],
    pr_candidates: list[Mapping[str, Any]],
) -> MatchResult | None:
    """Match one GSTR-2B record against Purchase Register candidates.

    Convenience wrapper around :func:`generic_match_one_to_many` pre-configured
    for purchase-side reconciliation (``PURCHASE_MATCH_CONFIG``).

    This is provided for symmetry and future migration; the existing
    ``match_gstr_to_pr`` in ``app.services.matcher`` remains the production
    entry point until you are ready to swap.
    """
    return generic_match_one_to_many(gstr_rec, pr_candidates, PURCHASE_MATCH_CONFIG)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    "MatchFieldsConfig",
    "PURCHASE_MATCH_CONFIG",
    "SALES_MATCH_CONFIG",
    "generic_match_pair",
    "generic_match_one_to_many",
    "match_sales_register_to_gstr1",
    "match_purchase_gstr2b_to_pr",
]
