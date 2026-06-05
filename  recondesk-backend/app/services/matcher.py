"""
GSTR ↔ Purchase Register invoice matcher (levels L1–L6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Mapping

from app.services.vendor_name_matcher import (
    find_best_vendor_match,
    vendor_name_similarity,
)

AMOUNT_TOLERANCE_L1_PAISE = 100
AMOUNT_TOLERANCE_L2_PAISE = 10000
AMOUNT_TOLERANCE_L3_PCT = 0.05
DATE_TOLERANCE_L1_DAYS = 3
DATE_TOLERANCE_L2_DAYS = 7
DATE_TOLERANCE_L3_DAYS = 30

# L2: absolute Rs100 cap AND relative ≤1%. L3: relative in (1%, 5%] — mutually exclusive bands.
AMOUNT_TOLERANCE_L2_PCT = 0.01

TOTAL_TOLERANCE_PAISE = 100  # Rs1 rounding on taxable + total tax

# L5: fuzzy invoice match — Rs50 and normalized Levenshtein similarity
AMOUNT_TOLERANCE_L5_PAISE = 5_000
INVOICE_SIMILARITY_L5_MIN = 0.70

FINANCIAL_MISMATCH_REASON = (
    "Financial mismatch: GSTIN / total / tax structure inconsistency"
)

_RE_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
_RE_LEADING_ALPHA = re.compile(r"^[A-Z]+")
_RE_TRAILING_DIGITS = re.compile(r"\d+$")


def normalize_invoice(inv: str | None) -> str:
    """Uppercase; alphanumerics only; leading zeros removed from the trailing ``\\d+``."""
    if inv is None or inv == "":
        return ""
    s = _RE_NON_ALNUM.sub("", str(inv)).upper()
    if not s:
        return ""
    m = _RE_TRAILING_DIGITS.search(s)
    if not m:
        return s
    digs = m.group(0).lstrip("0") or "0"
    return s[: m.start()] + digs


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
    norm1 = normalize_invoice(inv1)
    norm2 = normalize_invoice(inv2)
    if norm1 == "" or norm2 == "":
        return 0.0
    if norm1 == norm2:
        return 1.0
    d = levenshtein(norm1, norm2)
    denom = max(len(norm1), len(norm2))
    if denom == 0:
        return 0.0
    return 1.0 - (d / denom)


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
    confidence: int
    requires_human_review: bool
    decision_what: str
    decision_why: str
    decision_next: str
    review_reason: str | None = None
    discrepancies: list[str] = field(default_factory=list)
    is_late_filing: bool = False
    original_period: date | None = None
    late_months: int = 0
    vendor_similarity_score: float | None = None


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
) -> MatchResult:
    """If L1–L3 and GSTIN/total safety fails, cap at L3 with mandatory review.

    Tax structure (IGST vs CGST+SGST) is enforced only for L1/L2 via ``l12_finance_ok``;
    it must not suppress L3 or alter L3 outcomes here.
    """
    unsafe = not gstin_match
    if enforce_total_tolerance:
        level_total_tolerance = AMOUNT_TOLERANCE_L2_PAISE if res.level == 2 else TOTAL_TOLERANCE_PAISE
        if total_diff > level_total_tolerance:
            unsafe = True
    if res.level not in (1, 2, 3) or not unsafe:
        return res
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
        review_reason=FINANCIAL_MISMATCH_REASON,
        discrepancies=list(res.discrepancies),
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
    return abs(g - p), False


def _date_diff_days_and_skip(
    dg: date | None, dp: date | None
) -> tuple[int, bool]:
    if dg is None or dp is None:
        return 0, True
    return abs((dg - dp).days), False


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
    total_diff = abs(gstr_total - pr_total)
    gstr_is_igst = _safe_paise_field(gstr_rec, "igst_paise") > 0
    pr_is_igst = _safe_paise_field(pr_rec, "igst_paise") > 0
    tax_structure_match = gstr_is_igst == pr_is_igst
    has_tax_lines = _has_explicit_total_tax_line(gstr_rec, pr_rec)
    l12_total_ok = (
        total_diff <= TOTAL_TOLERANCE_PAISE if has_tax_lines else True
    )
    l12_total_ok_l2 = (
        total_diff <= AMOUNT_TOLERANCE_L2_PAISE if has_tax_lines else True
    )
    l12_finance_ok = l12_total_ok and tax_structure_match
    l12_finance_ok_l2 = l12_total_ok_l2 and tax_structure_match
    enforce_total_for_downgrade = has_tax_lines

    discrepancies = build_discrepancies(
        gstr_rec,
        pr_rec,
        tg=tg,
        tp=tp,
        dg=dg,
        dp=dp,
        amount_diff=amount_diff,
        date_diff_days=date_diff_days,
        skip_amount=skip_amount,
        skip_date=skip_date,
    )
    _append_financial_discrepancies(
        discrepancies,
        gstr_rec=gstr_rec,
        pr_rec=pr_rec,
        gstr_total=gstr_total,
        pr_total=pr_total,
        total_diff=total_diff,
        tax_structure_match=tax_structure_match,
        gstr_is_igst=gstr_is_igst,
        pr_is_igst=pr_is_igst,
    )

    inv_ok = invoices_effectively_match(g_inv, p_inv)

    amount_diff_paise = amount_diff
    percentage_diff = _compute_percentage_diff(amount_diff_paise, skip_amount, tg, tp)

    amount_within_l1 = skip_amount or amount_diff_paise <= AMOUNT_TOLERANCE_L1_PAISE
    amount_within_l2 = skip_amount or amount_diff_paise <= AMOUNT_TOLERANCE_L2_PAISE
    date_within_l1 = skip_date or date_diff_days <= DATE_TOLERANCE_L1_DAYS
    date_within_l2 = skip_date or date_diff_days <= DATE_TOLERANCE_L2_DAYS
    date_within_l3 = skip_date or date_diff_days <= DATE_TOLERANCE_L3_DAYS

    # Fast path — L1 exact match via hash lookup (skip L2–L5 when hash + L1 criteria align)
    if gstr_by_invoice is not None:
        pr_inv = invoice_match_key_for_record(pr_rec)
        if pr_inv and pr_inv in gstr_by_invoice:
            candidate = gstr_by_invoice[pr_inv]
            if (
                str(candidate.get("id")) == str(gstr_rec.get("id"))
                and gstin_match
                and inv_ok
                and amount_within_l1
                and date_within_l1
                and l12_finance_ok
            ):
                return _financial_downgrade_l13(
                    MatchResult(
                        level=1,
                        matched=True,
                        confidence=100,
                        requires_human_review=False,
                        decision_what="Exact match found",
                        decision_why="Invoice number, amount, and date all match within rounding tolerance",
                        decision_next="No action required",
                        discrepancies=discrepancies,
                    ),
                    gstin_match=gstin_match,
                    total_diff=total_diff,
                    enforce_total_tolerance=enforce_total_for_downgrade,
                )

    # Rs1 bucket is L1-only when invoice+GSTIN+L1 date would apply; never L2/L3 for that slice.
    in_l1_rounding_band = (not skip_amount) and amount_diff_paise < AMOUNT_TOLERANCE_L1_PAISE
    may_use_l2_l3 = skip_amount or not in_l1_rounding_band or not date_within_l1

    l2_pct_ok = percentage_diff <= AMOUNT_TOLERANCE_L2_PCT
    l3_pct_ok = (
        percentage_diff > AMOUNT_TOLERANCE_L2_PCT
        and percentage_diff <= AMOUNT_TOLERANCE_L3_PCT
    )
    l3_absolute_guard = skip_amount or amount_diff_paise > AMOUNT_TOLERANCE_L1_PAISE
    within_l3_pct_cap = skip_amount or percentage_diff <= AMOUNT_TOLERANCE_L3_PCT

    # L1 — Exact (supplier GSTIN must align; L4/L5 also require gstin_match)
    if (
        gstin_match
        and inv_ok
        and amount_within_l1
        and date_within_l1
        and l12_finance_ok
    ):
        return _financial_downgrade_l13(
            MatchResult(
                level=1,
                matched=True,
                confidence=100,
                requires_human_review=False,
                decision_what="Exact match found",
                decision_why="Invoice number, amount, and date all match within rounding tolerance",
                decision_next="No action required",
                discrepancies=discrepancies,
            ),
            gstin_match=gstin_match,
            total_diff=total_diff,
            enforce_total_tolerance=enforce_total_for_downgrade,
        )

    # L2 — Near (absolute ≤ Rs100 AND relative ≤ 1%; exclusive with L3)
    if (
        gstin_match
        and inv_ok
        and may_use_l2_l3
        and amount_within_l2
        and l2_pct_ok
        and date_within_l2
        and l12_finance_ok_l2
    ):
        return _financial_downgrade_l13(
            MatchResult(
                level=2,
                matched=True,
                confidence=90,
                requires_human_review=False,
                decision_what="Near match found",
                decision_why="Invoice number matches. Small amount or date difference detected.",
                decision_next="Auto-accepted. Verify with supplier if amount difference exceeds Rs50.",
                discrepancies=discrepancies,
            ),
            gstin_match=gstin_match,
            total_diff=total_diff,
            enforce_total_tolerance=enforce_total_for_downgrade,
        )

    # L3 — Amount mismatch (1% < relative ≤ 5%; mutually exclusive with L2)
    if (
        gstin_match
        and inv_ok
        and may_use_l2_l3
        and l3_absolute_guard
        and l3_pct_ok
        and date_within_l2
    ):
        rupees_diff = amount_diff_paise / 100.0
        pct_display = 100.0 * percentage_diff
        return _financial_downgrade_l13(
            MatchResult(
                level=3,
                matched=True,
                confidence=75,
                requires_human_review=True,
                decision_what="Invoice matched but amount differs significantly",
                decision_why="Same invoice number but taxable amount differs by more than Rs100",
                decision_next="Contact supplier to issue credit/debit note or verify correct invoice",
                review_reason=(
                    f"Amount differs by {pct_display:.1f}% (Rs {rupees_diff:.2f})"
                ),
                discrepancies=discrepancies,
            ),
            gstin_match=gstin_match,
            total_diff=total_diff,
            enforce_total_tolerance=enforce_total_for_downgrade,
        )

    # L2 — Near taxable (≤ Rs100, ≤1%) with tax structure or total discrepancies.
    # Standard L2 requires l12_finance_ok_l2; this path pairs same GSTIN+invoice when
    # taxable is close but IGST vs CGST+SGST or invoice total diverges (e.g. INV-003).
    if (
        gstin_match
        and inv_ok
        and may_use_l2_l3
        and amount_within_l2
        and l2_pct_ok
        and date_within_l2
        and not l12_finance_ok_l2
    ):
        return _financial_downgrade_l13(
            MatchResult(
                level=2,
                matched=True,
                confidence=90,
                requires_human_review=False,
                decision_what="Near match found",
                decision_why=(
                    "Invoice number matches with small taxable difference, "
                    "but tax structure or total value differs"
                ),
                decision_next=(
                    "Verify tax lines and total with supplier; "
                    "reconcile IGST vs CGST+SGST if needed"
                ),
                discrepancies=discrepancies,
            ),
            gstin_match=gstin_match,
            total_diff=total_diff,
            enforce_total_tolerance=enforce_total_for_downgrade,
        )

    # Same invoice + GSTIN + amount within L1, but date beyond L2 window — date-only mismatch
    if (
        gstin_match
        and inv_ok
        and amount_within_l1
        and not date_within_l2
    ):
        return MatchResult(
            level=3,
            matched=True,
            confidence=75,
            requires_human_review=True,
            decision_what="Invoice matched but date differs significantly",
            decision_why="Same invoice number, GSTIN and amount match, but date differs by more than 7 days",
            decision_next="Verify invoice date in purchase register against physical invoice copy. Correct if needed.",
            review_reason=f"Date gap: {date_diff_days} days between GSTR-2B and purchase register",
            discrepancies=discrepancies,
        )

    # Identity + taxable align but invoice total (taxable + tax) differs — match with review, not L6.
    invoice_number_match = inv_ok
    date_match = not skip_date and date_within_l1
    taxable_amount_match = not skip_amount and amount_within_l1
    if (
        gstin_match
        and invoice_number_match
        and date_match
        and taxable_amount_match
        and total_diff > TOTAL_TOLERANCE_PAISE
    ):
        return MatchResult(
            level=3,
            matched=True,
            confidence=75,
            requires_human_review=True,
            decision_what="Invoice matched but total value differs",
            decision_why=(
                "Supplier GSTIN, invoice number, date, and taxable amount align within "
                "tolerance, but total invoice value (taxable + tax) differs beyond Rs1 rounding"
            ),
            decision_next=(
                "Reconcile tax lines in GSTR-2B vs purchase register; "
                "verify with supplier if totals should match"
            ),
            review_reason="Total value mismatch",
            discrepancies=discrepancies,
        )

    # Same invoice identity + taxable as L1, but IGST vs CGST+SGST — L3 review, not L6.
    if (
        gstin_match
        and invoice_number_match
        and date_match
        and taxable_amount_match
        and not tax_structure_match
    ):
        return MatchResult(
            level=3,
            matched=True,
            confidence=75,
            requires_human_review=True,
            decision_what="Invoice matched but tax structure differs",
            decision_why=(
                "Supplier GSTIN, invoice number, date, and taxable amount align within "
                "tolerance, but GSTR and PR disagree on IGST vs CGST+SGST treatment"
            ),
            decision_next=(
                "Verify interstate vs intrastate treatment and tax lines in both books; "
                "reconcile with supplier if needed"
            ),
            review_reason="Tax structure mismatch",
            discrepancies=discrepancies,
        )

    # L4 — Invoice number mismatch
    if (
        gstin_match
        and not inv_ok
        and amount_within_l2
        and date_within_l2
        and invoice_similarity(g_inv, p_inv) >= 0.40
    ):
        vendor_sim = vendor_name_similarity(
            pr_rec.get("vendor_name", ""),
            gstr_rec.get("supplier_name", ""),
        )
        return MatchResult(
            level=4,
            matched=True,
            confidence=50,
            requires_human_review=True,
            decision_what="Possible match on supplier and amount but invoice number differs",
            decision_why="Same supplier GSTIN and similar amount but different invoice number",
            decision_next="Verify invoice number with supplier. May be a typo or amended invoice.",
            review_reason=f"Invoice number mismatch: GSTR has {g_inv}, PR has {p_inv}",
            discrepancies=discrepancies,
            vendor_similarity_score=vendor_sim,
        )

    # L5 — Fuzzy invoice (after L1–L4; GSTIN + Rs50 + normalized similarity)
    amount_within_l5 = skip_amount or amount_diff_paise <= AMOUNT_TOLERANCE_L5_PAISE
    inv_sim = invoice_similarity(g_inv, p_inv)
    if (
        gstin_match
        and not inv_ok
        and amount_within_l5
        and inv_sim >= INVOICE_SIMILARITY_L5_MIN
    ):
        vendor_sim = vendor_name_similarity(
            pr_rec.get("vendor_name", ""),
            gstr_rec.get("supplier_name", ""),
        )
        return MatchResult(
            level=5,
            matched=True,
            confidence=30,
            requires_human_review=True,
            decision_what="Weak fuzzy match on supplier, amount, and similar invoice number",
            decision_why=(
                "Supplier GSTIN matches, taxable amount within Rs50, and invoice numbers are "
                "similar after normalization"
            ),
            decision_next=(
                "Manually verify with supplier. Do not auto-accept this match without "
                "confirming the invoice identity."
            ),
            review_reason=(
                f"Fuzzy invoice match (similarity {inv_sim:.2f}); "
                f"{explain_invoice_difference(g_inv, p_inv)}"
            ),
            discrepancies=discrepancies,
            vendor_similarity_score=vendor_sim,
        )

    # L6 — No match
    return MatchResult(
        level=6,
        matched=False,
        confidence=0,
        requires_human_review=False,
        decision_what="No match found in purchase register",
        decision_why="No PR record matches this GSTR invoice on any criteria",
        decision_next="Check if supplier filed late. If missing, raise ITC risk flag and follow up with supplier.",
        discrepancies=discrepancies,
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
        r = _match_gstr_to_pr_pair(gstr_rec, pr_rec, gstr_by_invoice)
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
                        int(gstr.get("taxable_amount_paise") or 0)
                        - int(pr.get("taxable_amount_paise") or 0)
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
                int(c["pr"].get("taxable_amount_paise") or 0)
                - int(gstr.get("taxable_amount_paise") or 0)
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

    return replace(
        best_candidate["r"],
        is_late_filing=is_late_filing_sel,
        original_period=original_period_sel,
    )
