"""
GSTR ↔ Purchase Register invoice matcher (levels L1–L6).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Mapping

from app.services.vendor_name_matcher import (
    find_best_vendor_match,
    l1_vendor_name_ok,
    vendor_name_similarity,
)

AMOUNT_TOLERANCE_L1_PAISE = 100  # Rs1 rounding tolerance — still an exact/clean match
AMOUNT_TOLERANCE_L2_PCT = 0.01
AMOUNT_TOLERANCE_L3_PCT = 0.05
DATE_TOLERANCE_L1_DAYS = 3
DATE_TOLERANCE_L2_DAYS = 7
DATE_TOLERANCE_L3_DAYS = 30

TOTAL_TOLERANCE_PAISE = 100  # Rs1 rounding on taxable + total tax
AMOUNT_TOLERANCE_L2_PAISE = 5000  # Rs50 — 0.5% of a typical Rs10k invoice

INVOICE_SIMILARITY_L5_MIN = 0.70

FINANCIAL_MISMATCH_REASON = (
    "Financial mismatch: GSTIN / total / tax structure inconsistency"
)

_RE_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
_RE_LEADING_ALPHA = re.compile(r"^[A-Z]+")
_RE_TRAILING_DIGITS = re.compile(r"\d+$")


def normalize_invoice(inv: str | None) -> str:
    """Normalize invoice number by stripping leading zeros per numeric segment and removing non-alphanumerics.

    Also strips a leading ``0`` that sits alone before letters (e.g. portal
    artifacts ``0SI-1798`` / ``0INV/24-25/5024`` → ``SI1798`` / ``INV24255024``),
    matching aggressive ground-truth keying. A lone ``\"0\"`` is preserved.
    """
    if not inv:
        return ""
    s = str(inv).strip().upper()
    s = _RE_NON_ALNUM.sub("", s)
    parts = re.findall(r'\d+|\D+', s)
    parts = [p.lstrip('0') or '0' if p.isdigit() else p for p in parts]
    joined = "".join(parts)
    return joined.lstrip("0") or joined


def normalize_invoice_number(value: str | None) -> str:
    """Shared invoice normalization: uppercase, alphanumerics only, leading zeros stripped per segment."""
    return normalize_invoice(value)


def _pan_of(gstin: str | None) -> str:
    """Return the 10-char PAN embedded in a GSTIN (positions 3-12), else ``""``."""
    g = (gstin or "").strip().upper()
    return g[2:12] if len(g) >= 12 else ""


def same_pan(a: str | None, b: str | None) -> bool:
    """True when both GSTINs carry the same (non-empty) PAN — i.e. likely a typo."""
    pa, pb = _pan_of(a), _pan_of(b)
    return bool(pa) and pa == pb


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _extra_chars_are_digits_only(short: str, long: str) -> bool:
    """True when every character ``long`` has beyond what ``short`` already has
    is a digit (zero-padding / separator-derived digits), never a fresh letter.

    Distinguishes genuine format padding (``DS2678`` -> ``DS202600078``, all
    extra characters are digits from year/zero expansion) from a materially
    different identity that merely happens to be a superstring (``TYPO0`` ->
    ``TYPO0A``, where the extra ``A`` is a real appended suffix — e.g. an
    amendment tag — not formatting noise).
    """
    extra = Counter(long)
    extra.subtract(Counter(short))
    return all(ch.isdigit() for ch, cnt in extra.items() if cnt > 0)


def is_invoice_format_variant(
    a: str | None, b: str | None, a_raw: str | None = None, b_raw: str | None = None
) -> bool:
    """True when two invoice numbers are the same identity in a different format.

    Conservative: requires the same leading alphabetic prefix and that the shorter
    normalized token is a subsequence of the longer one with a genuine length gap
    (e.g. ``DS/26/78`` vs ``DS-2026-00078``). Equal-length single-character typos
    are intentionally NOT treated as variants (they remain L4 review).

    Fuzzy fallback: if the invoices share at least one identical non-zero numeric
    sequence (e.g. ``INV-00001-26`` vs ``1``), they are also treated as variants.
    """
    na, nb = normalize_invoice_number(a), normalize_invoice_number(b)
    if not na or not nb:
        return False
    if na == nb:
        return True

    # Check 1: Shared prefix and subsequence
    pa = _RE_LEADING_ALPHA.match(na)
    pb = _RE_LEADING_ALPHA.match(nb)
    if pa and pb and pa.group(0) == pb.group(0):
        short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
        if (
            len(short) != len(long)
            and _is_subsequence(short, long)
            and _extra_chars_are_digits_only(short, long)
        ):
            return True

    # Check 2: Shared exact core numeric sequence (using raw tokens to split by separators)
    # We enforce len(na) != len(nb) so we don't accidentally swallow equal-length typos like "INV1" vs "INX1"
    if len(na) != len(nb):
        def _extract_numeric(s: str) -> set[int]:
            # Include numbers >= 1 (allows short numbers like "1" to match as format variants)
            return {int(t) for t in re.findall(r"\d+", str(s)) if int(t) >= 1}

        nums_a = _extract_numeric(a_raw or a or "")
        nums_b = _extract_numeric(b_raw or b or "")
        if nums_a and nums_b:
            has_alpha_a = bool(re.search(r'[A-Za-z]', (a_raw or a or "")))
            has_alpha_b = bool(re.search(r'[A-Za-z]', (b_raw or b or "")))
            if (nums_a & nums_b):
                # Extra guard: one side must have more structure (alpha prefix or longer numeric)
                # to prevent "123" matching "456" via coincidence
                if has_alpha_a or has_alpha_b:
                    # When BOTH sides share the same alpha prefix (e.g. "TYPO1" vs
                    # "TYPO1A"), a shared numeric core is not enough on its own —
                    # the extra characters must also be digit-only padding, not a
                    # fresh appended letter, which more likely signals a distinct
                    # document (e.g. an amendment suffix) than a format variant.
                    if pa and pb and pa.group(0) == pb.group(0):
                        short2, long2 = (na, nb) if len(na) <= len(nb) else (nb, na)
                        if _extra_chars_are_digits_only(short2, long2):
                            return True
                    else:
                        return True
            # Note: a fuzzy "1-char-edit-distance numeric core" fallback used to live
            # here (intended to catch zero-padding typos like '00051' vs '00057').
            # It was removed: an equal-length, 1-digit-different numeric core is
            # fundamentally indistinguishable from two adjacent, genuinely different
            # invoices in a normal sequential numbering series (e.g. '100' vs '101'),
            # which is an extremely common real-world pattern — treating it as a
            # guaranteed format variant caused false auto-matches. A same-invoice
            # digit typo without any other corroborating signal belongs in L4/L5
            # human review, not an auto-detected format variant.

    return False


def levenshtein(s1: str, s2: str) -> int:
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    la, lb = len(s1), len(s2)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            cur[j] = min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + cost,
            )
        prev = cur
    return prev[lb]


def invoice_similarity(inv1: str, inv2: str) -> float:
    """Similarity score between two normalized invoice strings [0.0, 1.0]."""
    a = normalize_invoice(inv1)
    b = normalize_invoice(inv2)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Strip leading zeros per numeric segment for fuzzy comparison
    a = re.sub(r'(?<![0-9])0+(?=[0-9])', '', a)
    b = re.sub(r'(?<![0-9])0+(?=[0-9])', '', b)
    if a == b:
        return 1.0
    
    max_len = max(len(a), len(b))
    dist = levenshtein(a, b)
    if max_len == 0:
        return 0.0
    return 1.0 - (dist / max_len)


def explain_invoice_difference(inv1: str, inv2: str) -> str:
    n1 = normalize_invoice(inv1)
    n2 = normalize_invoice(inv2)
    if n1 == n2:
        return ""
    p1 = _RE_LEADING_ALPHA.match(n1)
    p2 = _RE_LEADING_ALPHA.match(n2)
    if p1 and p2 and p1.group(0) != p2.group(0):
        return "Prefix abbreviation difference"

    num1 = _RE_TRAILING_DIGITS.search(n1)
    num2 = _RE_TRAILING_DIGITS.search(n2)
    if num1 and num2:
        v1 = int(num1.group(0))
        v2 = int(num2.group(0))
        if v1 != v2:
            return f"Sequence number differs by {abs(v1 - v2)}"

    dist = levenshtein(n1, n2)
    if dist == 1:
        return "One character difference -- likely a typo"
    if dist == 2:
        return "Two character differences -- verify with supplier"
    return "Invoice numbers differ -- verify with supplier"


@dataclass
class MatchResult:
    level: int
    matched: bool
    confidence: int | None
    requires_human_review: bool
    decision_what: str
    decision_why: str
    decision_next: str
    identity_confidence: str = "High"
    financial_status: str = "Exact"
    review_reason: str | None = None
    discrepancies: list[str] = field(default_factory=list)
    is_late_filing: bool = False
    original_period: date | None = None
    late_months: int = 0
    vendor_similarity_score: float | None = None
    # Field-by-field comparison snapshot for the CA rationale drawer.
    # Additive / observational only — never feeds matching decisions.
    compared_fields: list[dict[str, Any]] = field(default_factory=list)


def _field_entry(
    field_name: str,
    match_type: str,
    field_score: int | None = None,
) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "match_type": match_type,
        "field_score": field_score,
    }


def build_compared_fields(
    gstr_rec: Mapping[str, Any],
    pr_rec: Mapping[str, Any],
    *,
    invoice_sim_override: float | None = None,
) -> list[dict[str, Any]]:
    """Observe (do not decide) per-field comparison outcomes for a GSTR↔PR pair.

    Uses the same helpers / tolerances as ``_match_gstr_to_pr_pair`` so the
    rationale drawer reflects what the engine actually compared. Returns a list
    of ``{field_name, match_type, field_score}`` dicts where ``match_type`` is
    ``exact`` / ``fuzzy`` / ``not_matched`` and ``field_score`` is a 0–100
    similarity percentage for fuzzy fields (``None`` for exact / not_matched).
    """
    out: list[dict[str, Any]] = []

    g_gst = _supplier_gstin(gstr_rec)
    p_gst = _supplier_gstin(pr_rec)
    gstin_exact = bool(g_gst) and bool(p_gst) and g_gst.upper().strip() == p_gst.upper().strip()
    if gstin_exact:
        out.append(_field_entry("gstin", "exact"))
    elif g_gst and p_gst and same_pan(g_gst, p_gst):
        out.append(_field_entry("gstin", "fuzzy"))
    elif g_gst and p_gst:
        dist = levenshtein(g_gst.upper().strip(), p_gst.upper().strip())
        if dist <= 2:
            max_len = max(len(g_gst), len(p_gst))
            score = int(round((1.0 - dist / max_len) * 100)) if max_len else None
            out.append(_field_entry("gstin", "fuzzy", score))
        else:
            out.append(_field_entry("gstin", "not_matched"))
    else:
        out.append(_field_entry("gstin", "not_matched"))

    g_inv = _invoice_number(gstr_rec)
    p_inv = _invoice_number(pr_rec)
    g_inv_raw = str(gstr_rec.get("invoice_number", "")).strip()
    p_inv_raw = str(pr_rec.get("invoice_number", "")).strip()
    inv_ok = invoices_effectively_match(g_inv, p_inv) if g_inv and p_inv else False
    raw_inv_ok = bool(g_inv_raw and p_inv_raw and g_inv_raw == p_inv_raw)
    format_variant = False
    if g_inv and p_inv and not inv_ok:
        format_variant = is_invoice_format_variant(
            g_inv, p_inv, gstr_rec.get("invoice_number"), pr_rec.get("invoice_number")
        )
    # Normalized / format-variant identity with different raw strings is not "exact".
    # Labelling those exact made Matched FUZZY rationale identical to L1 and hid the
    # only real difference a CA needs to see (GST/0001/26 ↔ GST126).
    if g_inv and p_inv and not raw_inv_ok and (inv_ok or format_variant):
        format_variant = True
    inv_sim = (
        float(invoice_sim_override)
        if invoice_sim_override is not None
        else (invoice_similarity(g_inv, p_inv) if g_inv and p_inv else 0.0)
    )
    if raw_inv_ok:
        out.append(_field_entry("invoice_number", "exact"))
    elif format_variant or inv_ok or inv_sim >= INVOICE_SIMILARITY_L5_MIN:
        if not raw_inv_ok and (inv_ok or format_variant):
            # Cap below 100 so rationale never reads as "fuzzy 100%" for a
            # formatting-only difference — that still isn't raw-exact identity.
            score = 95
        else:
            score = int(round(inv_sim * 100)) if inv_sim > 0 else None
        out.append(_field_entry("invoice_number", "fuzzy", score))
    else:
        score = int(round(inv_sim * 100)) if inv_sim > 0 else None
        out.append(_field_entry("invoice_number", "not_matched", score))

    tg = _optional_taxable(gstr_rec)
    tp = _optional_taxable(pr_rec)
    amount_diff, skip_amount = _amount_diff_and_skip(tg, tp)
    amount_pct = _compute_percentage_diff(amount_diff, skip_amount, tg, tp)
    if skip_amount or amount_diff <= AMOUNT_TOLERANCE_L1_PAISE:
        out.append(_field_entry("taxable_amount", "exact"))
    elif amount_pct <= AMOUNT_TOLERANCE_L3_PCT:
        out.append(
            _field_entry(
                "taxable_amount",
                "fuzzy",
                int(round(max(0.0, 1.0 - amount_pct) * 100)),
            )
        )
    else:
        out.append(_field_entry("taxable_amount", "not_matched"))

    dg = _parse_invoice_date(gstr_rec)
    dp = _parse_invoice_date(pr_rec)
    date_diff_days, skip_date = _date_diff_days_and_skip(dg, dp)
    if skip_date or date_diff_days <= DATE_TOLERANCE_L1_DAYS:
        out.append(_field_entry("date", "exact"))
    elif date_diff_days <= DATE_TOLERANCE_L3_DAYS:
        closeness = max(
            0.0, 1.0 - (date_diff_days / float(DATE_TOLERANCE_L3_DAYS))
        )
        out.append(_field_entry("date", "fuzzy", int(round(closeness * 100))))
    else:
        out.append(_field_entry("date", "not_matched"))

    g_vendor = str(gstr_rec.get("supplier_name") or "").strip()
    p_vendor = str(pr_rec.get("vendor_name") or "").strip()
    if g_vendor and p_vendor:
        if l1_vendor_name_ok(g_vendor, p_vendor):
            out.append(_field_entry("vendor_name", "exact"))
        else:
            v_sim = vendor_name_similarity(g_vendor, p_vendor)
            if v_sim >= 0.70:
                out.append(
                    _field_entry("vendor_name", "fuzzy", int(round(v_sim * 100)))
                )
            else:
                out.append(
                    _field_entry(
                        "vendor_name",
                        "not_matched",
                        int(round(v_sim * 100)) if v_sim > 0 else None,
                    )
                )

    return out


def _safe_paise_field(rec: Mapping[str, Any], key: str) -> int:
    v = rec.get(key, 0)
    if v is None:
        return 0
    return int(v)


def _invoice_total_paise(rec: Mapping[str, Any]) -> int:
    return _safe_paise_field(rec, "taxable_amount_paise") + _safe_paise_field(
        rec, "total_tax_paise"
    )


def _gstin_match_spec(gstr_rec: Mapping[str, Any], pr_rec: Mapping[str, Any]) -> bool:
    g = _supplier_gstin(gstr_rec)
    p = _supplier_gstin(pr_rec)
    return bool(g) and bool(p) and g.upper().strip() == p.upper().strip()


def _has_explicit_total_tax_line(
    gstr_rec: Mapping[str, Any], pr_rec: Mapping[str, Any]
) -> bool:
    """True if either side carries a non-zero total_tax_paise (full-invoice check applies)."""
    return (
        _safe_paise_field(gstr_rec, "total_tax_paise") != 0
        or _safe_paise_field(pr_rec, "total_tax_paise") != 0
    )


def _has_component_tax_breakdown(rec: Mapping[str, Any]) -> bool:
    """True when a record carries a genuine IGST/CGST/SGST split, as opposed to
    only an aggregate total_tax_paise.

    Many real-world Purchase Register exports only have a single "Total Tax"
    column with no separate IGST/CGST/SGST columns. In that case the adapters
    coerce the missing per-head fields to 0 (see reconciliation_record_adapter.py),
    which is indistinguishable from "genuinely zero" at the field level. Treating
    that coerced 0 as proof of "not IGST" fabricates a tax-structure conflict out
    of absent data. This helper lets callers tell "known to be zero" apart from
    "unknown" by checking whether *any* component on the record is non-zero.
    """
    return (
        _safe_paise_field(rec, "igst_paise") != 0
        or _safe_paise_field(rec, "cgst_paise") != 0
        or _safe_paise_field(rec, "sgst_paise") != 0
    )


def _append_financial_discrepancies(
    out: list[str],
    *,
    gstr_rec: Mapping[str, Any],
    pr_rec: Mapping[str, Any],
    gstr_total: int,
    pr_total: int,
    total_diff: int,
    tax_structure_match: bool,
    gstr_is_igst: bool,
    pr_is_igst: bool,
) -> None:
    if (
        gstr_total != pr_total
        and _has_explicit_total_tax_line(gstr_rec, pr_rec)
    ):
        out.append(
            "total_value: GSTR="
            f"{_rs_str(gstr_total)}, PR={_rs_str(pr_total)}, diff={_rs_str(total_diff)}"
        )
    if not tax_structure_match:
        g_lbl = "IGST" if gstr_is_igst else "CGST+SGST"
        p_lbl = "IGST" if pr_is_igst else "CGST+SGST"
        out.append(f"tax_structure: GSTR={g_lbl}, PR={p_lbl}")


def _financial_downgrade_l13(
    res: MatchResult,
    *,
    gstin_match: bool,
    total_diff: int,
    enforce_total_tolerance: bool,
    total_base_paise: int = 0,
) -> MatchResult:
    """If L1–L3 and GSTIN/total safety fails, cap at L3 with mandatory review.

    Tax structure (IGST vs CGST+SGST) is enforced only for L1/L2 via ``l12_finance_ok``;
    it must not suppress L3 or alter L3 outcomes here.

    The total-tolerance safety net is percentage-based (matching the same
    AMOUNT_TOLERANCE_L2_PCT / AMOUNT_TOLERANCE_L3_PCT bands already used to admit
    the pair into L2/L3), not a flat rupee figure. A flat absolute cap here would
    silently re-tighten large invoices below their own level's percentage
    tolerance — e.g. a Rs100 diff on a Rs1,00,000 invoice (0.1%) is comfortably
    inside the 1% L2 band, but a flat Rs50 cap would incorrectly downgrade it to L3.
    """
    unsafe = not gstin_match
    gstin_unsafe = not gstin_match
    total_unsafe = False
    if enforce_total_tolerance:
        pct = AMOUNT_TOLERANCE_L2_PCT if res.level == 2 else AMOUNT_TOLERANCE_L3_PCT
        level_total_tolerance = max(TOTAL_TOLERANCE_PAISE, int(total_base_paise * pct))
        if total_diff > level_total_tolerance:
            unsafe = True
            total_unsafe = True
    if res.level not in (1, 2, 3) or not unsafe:
        return res
    # Preserve a specific, actionable reason instead of a generic financial-mismatch
    # label: when the GSTIN genuinely matches and the only reason this pair is
    # unsafe is the taxable/total-tax gap, the review reason must say so
    # (AMOUNT_MISMATCH) rather than the GSTIN-safety message, which would be
    # misleading here since the GSTIN is not actually in question.
    if gstin_unsafe:
        review_reason = FINANCIAL_MISMATCH_REASON
    else:
        review_reason = (
            f"AMOUNT_MISMATCH: taxable/total-tax differs by Rs {total_diff / 100:.2f}"
        )
    return MatchResult(
        level=max(res.level, 3),
        matched=True,
        confidence=75,
        requires_human_review=True,
        decision_what="Invoice matched but amount differs significantly",
        decision_why="Same invoice number but taxable amount differs by more than Rs100",
        decision_next=(
            "Contact supplier to issue credit/debit note or verify correct invoice"
        ),
        review_reason=review_reason,
        discrepancies=list(res.discrepancies),
        compared_fields=list(res.compared_fields),
        vendor_similarity_score=res.vendor_similarity_score,
        identity_confidence=res.identity_confidence,
        financial_status=res.financial_status,
    )


def _optional_taxable(rec: Mapping[str, Any]) -> int | None:
    if "taxable_amount_paise" in rec:
        v = rec["taxable_amount_paise"]
        if v is None:
            return None
        return int(v)
    if "taxable_amount" in rec:
        v = rec["taxable_amount"]
        if v is None:
            return None
        return int(round(float(v) * 100))
    return None


def _parse_invoice_date(rec: Mapping[str, Any]) -> date | None:
    if not isinstance(rec, dict):
        raise TypeError(f"Expected dict, got {type(rec)}")
    v = rec.get("invoice_date")
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except (ValueError, TypeError):
        return None


def _invoice_number(rec: Mapping[str, Any]) -> str:
    v = rec.get("invoice_number_normalized")
    if v is None or str(v).strip() == "":
        v = rec.get("invoice_number")
    return "" if v is None else str(v).strip()


def _supplier_gstin(rec: Mapping[str, Any]) -> str:
    v = rec.get("supplier_gstin")
    if v is None or str(v).strip() == "":
        v = rec.get("gstin")
    return "" if v is None else str(v).strip()


def _amount_diff_and_skip(
    g: int | None, p: int | None
) -> tuple[int, bool]:
    if g is None or p is None:
        return 0, True
    # Compare magnitudes: PR credit notes / Purchase Returns store negative
    # taxable and tax, while GSTR-2B CDNR amounts are positive. Using signed
    # values made equal abs amounts look like a 2× mismatch and pushed real
    # CN↔CDNR pairs into Review / ITC at Risk.
    return abs(abs(int(g)) - abs(int(p))), False


def _date_diff_days_and_skip(
    dg: date | None, dp: date | None
) -> tuple[int, bool]:
    if dg is None or dp is None:
        return 0, True
    return abs((dg - dp).days), False


def _gst_return_period_key(d: date) -> tuple[int, int]:
    """GST return period identity: calendar month + year of the invoice date."""
    return (d.year, d.month)


def _crosses_gst_return_period(dg: date | None, dp: date | None) -> bool:
    """True when GSTR and PR invoice dates fall in different return periods."""
    if dg is None or dp is None:
        return False
    return _gst_return_period_key(dg) != _gst_return_period_key(dp)


def _format_gst_return_period_label(d: date | str | None) -> str:
    if d is None or d == "":
        return "unknown period"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except (ValueError, TypeError):
            return str(d)
    return d.strftime("%B %Y")


def _format_invoice_date_label(d: date | str | None) -> str:
    if d is None or d == "":
        return "—"
    if isinstance(d, str):
        try:
            parsed = date.fromisoformat(d[:10])
            return parsed.strftime("%d %b %Y")
        except (ValueError, TypeError):
            return str(d)
    return d.strftime("%d %b %Y")


def _invoice_key_for_match(inv: str | None) -> str:
    """Match key: same rules as GSTR-2B / PR adapter (alnum-only, case-fold)."""
    return normalize_invoice(inv)


def invoices_effectively_match(g_inv: str, p_inv: str) -> bool:
    a = _invoice_key_for_match(g_inv)
    b = _invoice_key_for_match(p_inv)
    return bool(a) and bool(b) and a == b


def invoice_match_key_for_record(rec: Mapping[str, Any]) -> str:
    """Normalized invoice identity for a matcher row (GSTR or PR)."""
    return _invoice_key_for_match(_invoice_number(rec))


def _compute_percentage_diff(
    amount_diff_paise: int,
    skip_amount: bool,
    tg: int | None,
    tp: int | None,
) -> float:
    """Ratio in [0, 1], e.g. 0.03 = 3%. Zero when amounts are not comparable or base is 0."""
    if skip_amount:
        return 0.0
    if tg is None or tp is None:
        return 0.0
    g_amt = int(tg)
    p_amt = int(tp)
    if g_amt == 0 and p_amt == 0:
        return 0.0
    max_amt = max(abs(g_amt), abs(p_amt))
    if max_amt == 0:
        return 0.0
    return amount_diff_paise / max_amt


def _rs_str(paise: int) -> str:
    return f"Rs {paise / 100:.2f}"


def build_discrepancies(
    gstr_rec: Mapping[str, Any],
    pr_rec: Mapping[str, Any],
    *,
    tg: int | None,
    tp: int | None,
    dg: date | None,
    dp: date | None,
    amount_diff: int,
    date_diff_days: int,
    skip_amount: bool,
    skip_date: bool,
) -> list[str]:
    out: list[str] = []
    g_inv = _invoice_number(gstr_rec)
    p_inv = _invoice_number(pr_rec)
    g_gst = _supplier_gstin(gstr_rec)
    p_gst = _supplier_gstin(pr_rec)

    if g_inv != p_inv:
        out.append(f"invoice_number: GSTR={g_inv}, PR={p_inv}")

    if g_gst != p_gst:
        out.append(f"supplier_gstin: GSTR={g_gst}, PR={p_gst}")

    if not skip_amount and tg is not None and tp is not None and amount_diff != 0:
        out.append(
            "amount: GSTR="
            f"{_rs_str(tg)}, PR={_rs_str(tp)}, diff={_rs_str(amount_diff)}"
        )

    if not skip_date and dg is not None and dp is not None and date_diff_days != 0:
        out.append(
            f"date: GSTR={dg.isoformat()}, PR={dp.isoformat()}, "
            f"diff={date_diff_days} days"
        )
    elif skip_date and (dg is not None or dp is not None):
        dg_s = dg.isoformat() if dg else "None"
        dp_s = dp.isoformat() if dp else "None"
        if dg_s != dp_s:
            out.append(
                f"date: GSTR={dg_s}, PR={dp_s}, diff={date_diff_days} days"
            )

    return out


def _match_gstr_to_pr_pair(
    gstr_rec: Mapping[str, Any],
    pr_rec: Mapping[str, Any],
    gstr_by_invoice: Mapping[str, Mapping[str, Any]] | None = None,
) -> MatchResult:
    tg = _optional_taxable(gstr_rec)
    tp = _optional_taxable(pr_rec)
    dg = _parse_invoice_date(gstr_rec)
    dp = _parse_invoice_date(pr_rec)

    g_inv = _invoice_number(gstr_rec)
    p_inv = _invoice_number(pr_rec)
    # g_inv_raw / p_inv_raw: must be the truly raw (pre-normalization) invoice strings.
    # The adapters (gstr_db_row_to_matcher_row / pr_db_row_to_matcher_row) are responsible
    # for ensuring that "invoice_number" = original raw, "invoice_number_normalized" = normalized.
    g_inv_raw = str(gstr_rec.get("invoice_number", "")).strip()
    p_inv_raw = str(pr_rec.get("invoice_number", "")).strip()

    pass

    if not g_inv or not p_inv:
        return MatchResult(
            level=6,
            matched=False,
            confidence=0,
            requires_human_review=False,
            decision_what="No match found in purchase register",
            decision_why="Invoice number is missing on one or both sides — cannot match",
            decision_next="Check source data for missing invoice numbers.",
            discrepancies=[],
        )
    g_gst = _supplier_gstin(gstr_rec)
    p_gst = _supplier_gstin(pr_rec)

    amount_diff, skip_amount = _amount_diff_and_skip(tg, tp)
    date_diff_days, skip_date = _date_diff_days_and_skip(dg, dp)

    gstin_match = _gstin_match_spec(gstr_rec, pr_rec)
    gstr_total = _invoice_total_paise(gstr_rec)
    pr_total = _invoice_total_paise(pr_rec)
    total_diff = abs(abs(gstr_total) - abs(pr_total))
    gstr_is_igst = _safe_paise_field(gstr_rec, "igst_paise") > 0
    pr_is_igst = _safe_paise_field(pr_rec, "igst_paise") > 0
    # Only treat a structure disagreement as real when BOTH sides actually
    # report a per-head breakdown. If one side has no IGST/CGST/SGST data at
    # all (common when a Purchase Register only tracks an aggregate total),
    # there is nothing to compare — default to "not conflicting" rather than
    # inferring CGST+SGST from an absent/zero-coerced field.
    both_have_tax_breakdown = _has_component_tax_breakdown(
        gstr_rec
    ) and _has_component_tax_breakdown(pr_rec)
    tax_structure_match = (
        (gstr_is_igst == pr_is_igst) if both_have_tax_breakdown else True
    )
    has_tax_lines = _has_explicit_total_tax_line(gstr_rec, pr_rec)

    discrepancies = build_discrepancies(
        gstr_rec, pr_rec, tg=tg, tp=tp, dg=dg, dp=dp,
        amount_diff=amount_diff, date_diff_days=date_diff_days,
        skip_amount=skip_amount, skip_date=skip_date,
    )
    _append_financial_discrepancies(
        discrepancies, gstr_rec=gstr_rec, pr_rec=pr_rec,
        gstr_total=gstr_total, pr_total=pr_total, total_diff=total_diff,
        tax_structure_match=tax_structure_match, gstr_is_igst=gstr_is_igst, pr_is_igst=pr_is_igst,
    )

    inv_ok = invoices_effectively_match(g_inv, p_inv)
    format_variant = False
    if not inv_ok:
        format_variant = is_invoice_format_variant(g_inv, p_inv, gstr_rec.get("invoice_number"), pr_rec.get("invoice_number"))

    raw_inv_ok = bool(g_inv_raw and p_inv_raw and g_inv_raw == p_inv_raw)
    amount_pct = _compute_percentage_diff(amount_diff, skip_amount, tg, tp)

    amount_within_l1 = skip_amount or (amount_diff <= AMOUNT_TOLERANCE_L1_PAISE)
    amount_within_l2 = skip_amount or (amount_pct <= AMOUNT_TOLERANCE_L2_PCT)
    amount_within_l3 = skip_amount or (amount_pct <= AMOUNT_TOLERANCE_L3_PCT)
    
    date_within_l1 = skip_date or (date_diff_days <= DATE_TOLERANCE_L1_DAYS)
    date_within_l2 = skip_date or (date_diff_days <= DATE_TOLERANCE_L2_DAYS)
    date_within_l3 = skip_date or (date_diff_days <= DATE_TOLERANCE_L3_DAYS)

    crosses_return_period = (
        not skip_date and _crosses_gst_return_period(dg, dp)
    )

    # Observational snapshot for the CA rationale drawer — does not affect tiers.
    compared = build_compared_fields(gstr_rec, pr_rec)

    def _ret(**kwargs: Any) -> MatchResult:
        kwargs.setdefault("compared_fields", compared)
        return MatchResult(**kwargs)

    # Financial severity classification
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

    # ── Tier 1: Same GSTIN + exact raw invoice number + amount within 1% ─────────────────
    # Vendor-name guard: if both sides carry a name and they are clearly different
    # vendors (after suffix-stripping and abbreviation expansion), do NOT grant a
    # clean L1 — fall through so Tier 2/3 flags the name discrepancy.
    # Uses l1_vendor_name_ok() which normalises trailing legal suffixes (Pvt Ltd,
    # Corp, etc.) and expands abbreviations (Soln→Solutions, Mfg→Manufacturing)
    # before comparing, with a 0.80 threshold on normalized cores.
    g_vendor = str(gstr_rec.get("supplier_name") or "").strip()
    p_vendor = str(pr_rec.get("vendor_name") or "").strip()
    _vendor_names_present = bool(g_vendor and p_vendor)
    _vendor_name_ok = (
        not _vendor_names_present
        or l1_vendor_name_ok(g_vendor, p_vendor)
    )
    if not _vendor_name_ok:
        discrepancies.append(
            f"vendor_name: GSTR={g_vendor!r}, PR={p_vendor!r}"
        )

    # Period-boundary date mismatch: same ±N-day tolerance does NOT apply when
    # the invoice dates fall in different GST return periods (month+year).
    #
    # Invoice identity here MUST be exact-normalized or a recognised format
    # variant — never Levenshtein/fuzzy similarity. Using ``strong_invoice``
    # (which includes sim ≥ 0.70) caused adjacent sequential invoices that
    # differ by one digit (e.g. ``09454`` vs ``09754``, sim=0.75 after
    # leading-zero strip) to auto-link across a month boundary, steal the
    # exact PR counterpart, and orphan the real match into Missed ITC.
    if crosses_return_period and gstin_match and (inv_ok or format_variant):
        g_period = _format_gst_return_period_label(dg)
        p_period = _format_gst_return_period_label(dp)
        g_date_label = _format_invoice_date_label(dg)
        p_date_label = _format_invoice_date_label(dp)
        period_discrepancies = list(discrepancies) + [
            f"return_period: GSTR={g_period} ({g_date_label}), "
            f"PR={p_period} ({p_date_label}), diff={date_diff_days} days"
        ]
        return _ret(
            level=2,
            matched=True,
            confidence=75,
            requires_human_review=True,
            decision_what=(
                f"Invoice date crosses GST return period "
                f"(GSTR: {g_period}, PR: {p_period})"
            ),
            decision_why=(
                "GSTR-2B and purchase register dates fall in different filing "
                "periods — wrong-period ITC claim risk"
            ),
            decision_next=(
                f"Confirm correct return period: GSTR date {g_date_label} "
                f"({g_period}) vs PR date {p_date_label} ({p_period}). "
                "Claim ITC only in the period the supply belongs to."
            ),
            discrepancies=period_discrepancies,
            identity_confidence="High",
            financial_status=financial_status,
            review_reason="PERIOD_BOUNDARY_DATE_MISMATCH",
        )

    # ── Zero-discrepancy invariant — single authoritative rule ───────────────
    # If the supplier GSTIN, invoice identity, and vendor name all agree, and
    # BOTH the taxable amount and the total tax agree (within Rs1 rounding),
    # this pair is an exact match — full stop. No downstream tier or heuristic
    # (tax-structure inference, financial_status classification, etc.) may
    # reclassify a genuinely zero-discrepancy pair as a review item. This is
    # the single place that decides "zero discrepancy ⇒ L1/Matched"; it must
    # still yield to a *proven* tax-structure conflict (tax_structure_match is
    # only False when both sides report real, comparable IGST/CGST/SGST data —
    # see _has_component_tax_breakdown) since a genuine IGST/CGST head-swap is
    # a real compliance risk even when the totals coincidentally agree.
    g_total_tax_paise = _safe_paise_field(gstr_rec, "total_tax_paise")
    p_total_tax_paise = _safe_paise_field(pr_rec, "total_tax_paise")
    tax_only_diff = abs(abs(g_total_tax_paise) - abs(p_total_tax_paise))
    zero_discrepancy = (
        not skip_amount
        and amount_diff <= AMOUNT_TOLERANCE_L1_PAISE
        and tax_only_diff <= AMOUNT_TOLERANCE_L1_PAISE
    )
    if (
        gstin_match
        and (inv_ok or format_variant)
        and _vendor_name_ok
        and zero_discrepancy
        and date_within_l1
        and tax_structure_match
    ):
        # L1 only when raw invoice strings are identical. Normalized / format-
        # variant identity with zero financial diff stays on Matched as L2
        # (requires_human_review=False) so the Non-exact chip and FUZZY filter
        # can surface formatting-only matches. Do not promote those to L1.
        if raw_inv_ok:
            return _ret(
                level=1, matched=True, confidence=100, requires_human_review=False,
                decision_what="Exact match found",
                decision_why="Invoice number, amount, and date align",
                decision_next="No action required",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status="Exact",
                review_reason=None,
            )
        return _ret(
            level=2, matched=True, confidence=95, requires_human_review=False,
            decision_what="Normalized invoice match",
            decision_why=(
                "Invoice numbers match after normalization or format variant; "
                "amounts and dates align"
            ),
            decision_next="No action required — formatting differs, amounts align",
            discrepancies=discrepancies,
            identity_confidence="High", financial_status="Exact",
            review_reason=None,
        )

    if gstin_match and raw_inv_ok and _vendor_name_ok:
        if amount_within_l1 and date_within_l1 and l12_finance_ok:
            return _ret(
                level=1, matched=True, confidence=100, requires_human_review=False,
                decision_what="Exact match found",
                decision_why="Invoice number, amount, and date align",
                decision_next="No action required",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
            )
        # Same raw invoice, same GSTIN, vendor ok — but financial mismatch (tax
        # structure or total_tax differs). Fall through to L2/L3 for human review.
    # ── Tier 2: Same GSTIN + normalized invoice number (L2) ─────────────────
    if gstin_match and inv_ok:
        if amount_within_l2 and date_within_l2 and tax_structure_match:
            # A genuinely zero-discrepancy pair is already handled by the
            # zero-discrepancy invariant above and never reaches this branch;
            # anything landing here has a real (if small) amount/date diff.
            return _ret(
                level=2, matched=True, confidence=90, requires_human_review=True,
                decision_what="Invoice matched with normalized invoice and minor amount difference",
                decision_why="Same normalized invoice and GSTIN, amount within acceptable tolerance",
                decision_next="Verify if needed",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
                review_reason="Amount/Date mismatch",
            )

        # Same GSTIN + same normalized invoice but amount or date exceeds L2 — L3 review.
        # Exact invoice identity is never rejected: even when BOTH amount and date
        # exceed L2 (e.g. 5.83% amount + 10-day date gap), link as Review Required.
        # Returning L6 here previously orphaned the pair into Missed ITC + ITC at
        # Risk as if the invoice numbers had never matched.
        if not tax_structure_match or not l12_finance_ok or not amount_within_l2:
            rr = "AMOUNT_MISMATCH"
        else:
            rr = "Amount Mismatch or Date mismatch"
        return _ret(
            level=3, matched=True, confidence=75, requires_human_review=True,
            decision_what="Invoice matched but with differences",
            decision_why="Same invoice number and GSTIN, but amount or date differ",
            decision_next="Review differences and correct if needed",
            review_reason=rr,
            discrepancies=discrepancies,
            identity_confidence="High", financial_status=financial_status,
        )

    # ── Tier 3: Same GSTIN + format-variant invoice ──────────────────────────
    # A genuinely zero-discrepancy format-variant pair is already handled by
    # the zero-discrepancy invariant above; anything reaching here has a real
    # (if small) amount/date diff.
    if gstin_match and format_variant:
        if amount_within_l3 and date_within_l3:
            return _ret(
                level=3, matched=True, confidence=75, requires_human_review=True,
                decision_what="Format variant with amount or date mismatch",
                decision_why="Invoice format matches, amount/date within L3 tolerances",
                decision_next="Review differences",
                review_reason="Amount Mismatch or Date mismatch",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
            )

    # ── Tier 4: Same-PAN GSTIN typo + same/near invoice ─────────────────────
    # Different GSTIN but same PAN (positions 3-12) is almost certainly a
    # check-digit / state-code typo on one side, not a genuinely different
    # supplier. Never auto-match (matched=False) — a human must confirm which
    # GSTIN is correct before ITC can be claimed — but flag it explicitly as
    # GSTIN_MISMATCH review rather than silently falling through to "no match".
    if not gstin_match and same_pan(g_gst, p_gst) and (inv_ok or format_variant) and amount_within_l2:
        return _ret(
            level=4, matched=False, confidence=50, requires_human_review=True,
            decision_what="Possible GSTIN typo",
            decision_why="Same PAN and invoice number, but GSTIN check-digit/state-code differs",
            decision_next="Verify the correct GSTIN with the supplier before claiming this ITC.",
            review_reason="GSTIN_MISMATCH: same PAN, different GSTIN",
            discrepancies=discrepancies,
            identity_confidence="Medium", financial_status=financial_status,
        )

    # ── L6 — No match ────────────────────────────────────────────────────────
    return _ret(
        level=6, matched=False, confidence=0, requires_human_review=False,
        decision_what="No match found in purchase register",
        decision_why="No PR record matches this GSTR invoice on any criteria",
        decision_next="Check if supplier filed late. If missing, raise ITC risk flag and follow up with supplier.",
        discrepancies=discrepancies, identity_confidence="None", financial_status="None",
    )



def match_gstr_to_pr(
    gstr_rec: Mapping[str, Any],
    pr_records: list[Mapping[str, Any]],
    gstr_by_invoice: Mapping[str, Mapping[str, Any]] | None = None,
) -> MatchResult | None:
    """Compare one GSTR row to many PR rows; return the best match or ``None``.

    Chooses the candidate with the **lowest** ``level`` (L1 preferred over L5), then
    **highest** ``confidence`` on ties. Unmatched candidates (L6) are ignored; if none
    match, returns ``None``. ``pr_records`` must be a ``list`` (possibly empty).
    """
    assert isinstance(pr_records, list)
    if not pr_records:
        return None
    candidates: list[dict[str, Any]] = []
    for pr_rec in pr_records:
        # Bug-1a fix: removed the broken 'status'-field guard that was here.
        # Matcher rows (from gstr_db_row_to_matcher_row / pr_db_row_to_matcher_row)
        # never carry a 'status' field, so the old code always defaulted to
        # 'matched' and then skipped any pair whose id was falsy (id=0, None, "").
        # This caused 0 matched records on runs with early test data.  The callers
        # (process_gstr_records_chunk, execute_phase2_and_3) already control which
        # records are passed in; no status guard is needed or correct here.
        r = _match_gstr_to_pr_pair(gstr_rec, pr_rec, gstr_by_invoice)
        if r is None:
            continue
        if not r.matched:
            continue
        gstr = gstr_rec
        pr = pr_rec
        score = 0
        reasons: list[str] = []
        is_late_filing = False
        original_period = None
        g_date = _parse_invoice_date(gstr)
        pr_date = _parse_invoice_date(pr)
        if g_date and pr_date:
            date_diff = abs((g_date - pr_date).days)

            if date_diff == 0:
                score += 20
                reasons.append("exact_date_match")

            elif date_diff <= 1:
                score += 5
                reasons.append("near_date_match")

            elif date_diff <= 90:
                # GST late filing window
                score += 8
                reasons.append("possible_late_filing")

                # mark late filing ONLY if strong match on other fields
                if (
                    invoice_match_key_for_record(gstr)
                    == invoice_match_key_for_record(pr)
                    and gstr.get("supplier_gstin") == pr.get("supplier_gstin")
                    and abs(
                        abs(int(gstr.get("taxable_amount_paise") or 0))
                        - abs(int(pr.get("taxable_amount_paise") or 0))
                    )
                    <= 100
                ):
                    is_late_filing = True
                    original_period = pr_date

            else:
                score -= 5
                reasons.append("date_mismatch")

        else:
            # missing date case
            score -= 2
            reasons.append("missing_date")

        rank_key = (
            r.level,
            -r.confidence,
            -score,
            str(pr_rec.get("id", "")),
        )
        candidates.append(
            {
                "pr": pr_rec,
                "r": r,
                "reasons": reasons,
                "date_signal": score,
                "is_late_filing": is_late_filing,
                "original_period": original_period,
                "rank_key": rank_key,
                # Lex max encodes the same ordering as ``rank_key`` (lower L, higher conf, stronger date).
                "score": (-r.level, r.confidence, score),
            }
        )

    if not candidates:
        return None

    gstr = gstr_rec

    # Filter strong identity matches
    strong_matches = [
        c
        for c in candidates
        if (
            invoice_match_key_for_record(c["pr"])
            == invoice_match_key_for_record(gstr)
            and c["pr"].get("supplier_gstin") == gstr.get("supplier_gstin")
            and abs(
                abs(int(c["pr"].get("taxable_amount_paise") or 0))
                - abs(int(gstr.get("taxable_amount_paise") or 0))
            )
            <= 100
        )
    ]

    if strong_matches:
        # Prefer earliest invoice date (original filing)

        def get_date(c: dict[str, Any]) -> str:
            v = c["pr"].get("invoice_date")
            if v is None or v == "":
                return "9999-12-31"
            if isinstance(v, date):
                return v.isoformat()
            return str(v)

        best_candidate = min(strong_matches, key=get_date)

        pr_date_sel = _parse_invoice_date(best_candidate["pr"])
        gstr_date_sel = _parse_invoice_date(gstr_rec)
        if pr_date_sel and gstr_date_sel:
            gap_days = abs((gstr_date_sel - pr_date_sel).days)
            is_late_filing_sel = gap_days > 7
        else:
            is_late_filing_sel = False
        original_period_sel = pr_date_sel
    else:
        # fallback to normal scoring (level → confidence → date signal); ties broken like ``rank_key``
        if not candidates:
            return None
        best_scored = max(candidates, key=lambda x: x["score"])
        tied = [c for c in candidates if c["score"] == best_scored["score"]]
        if len(tied) > 1 and tied[0]["r"].level == 5:
            vendor_pick = find_best_vendor_match(
                gstr_rec.get("supplier_name", ""),
                [
                    {
                        "vendor_name": c["pr"].get("vendor_name", ""),
                        "record": c["pr"],
                    }
                    for c in tied
                ],
                threshold=0.82,
            )
            if vendor_pick is not None:
                picked_pr = vendor_pick["record"]
                best_candidate = next(
                    c for c in tied if c["pr"] is picked_pr
                )
                best_candidate = {
                    **best_candidate,
                    "r": replace(
                        best_candidate["r"],
                        vendor_similarity_score=vendor_pick["vendor_similarity_score"],
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
    # Safety net: if an L2/L3 slipped through with a financial mismatch
    # (e.g. has_tax_lines was False so the l12_finance_ok guard wasn't active),
    # cap it to L3-review so it never lands in clean_matched.
    # NOTE: L1 pairs are intentionally EXCLUDED from the total-tolerance enforcement
    # below. The pair-level L1 gate in _match_gstr_to_pr_pair already enforces
    # 0-paise amount tolerance.  Re-enforcing Rs-1 total-tolerance here against
    # parser-rounded totals (taxable + total_tax may differ by 1–2 paise between
    # GSTR-2B item sums and PR pre-computed fields) incorrectly demotes L1 to L3.
    pr_sel = best_candidate["pr"]
    gstr_total = _invoice_total_paise(gstr_rec)
    pr_total = _invoice_total_paise(pr_sel)
    # Magnitude compare — same rule as _amount_diff_and_skip. Signed totals make
    # equal-abs CDNR↔credit-note pairs look like a 2× mismatch and incorrectly
    # demote clean L2 matches into L3 AMOUNT_MISMATCH review.
    total_diff_sel = abs(abs(gstr_total) - abs(pr_total))
    gstin_match_sel = _gstin_match_spec(gstr_rec, pr_sel)
    enforce = bool(
        final.level >= 2  # skip enforcement for L1: pair gate already validated
        and (
            _safe_paise_field(gstr_rec, "total_tax_paise") != 0
            or _safe_paise_field(pr_sel, "total_tax_paise") != 0
        )
    )
    return _financial_downgrade_l13(
        final,
        gstin_match=gstin_match_sel,
        total_diff=total_diff_sel,
        enforce_total_tolerance=enforce,
        total_base_paise=max(abs(gstr_total), abs(pr_total)),
    )
