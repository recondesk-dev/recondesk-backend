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
    l1_vendor_name_ok,
    vendor_name_similarity,
)

AMOUNT_TOLERANCE_L1_PAISE = 0
AMOUNT_TOLERANCE_L2_PCT = 0.005
AMOUNT_TOLERANCE_L3_PCT = 0.02
DATE_TOLERANCE_L1_DAYS = 0
DATE_TOLERANCE_L2_DAYS = 7
DATE_TOLERANCE_L3_DAYS = 30

TOTAL_TOLERANCE_PAISE = 100  # Rs1 rounding on taxable + total tax

INVOICE_SIMILARITY_L5_MIN = 0.70

FINANCIAL_MISMATCH_REASON = (
    "Financial mismatch: GSTIN / total / tax structure inconsistency"
)

_RE_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
_RE_LEADING_ALPHA = re.compile(r"^[A-Z]+")
_RE_TRAILING_DIGITS = re.compile(r"\d+$")


def normalize_invoice(inv: str | None) -> str:
    """Normalize invoice number by stripping leading zeros per numeric segment and removing non-alphanumerics."""
    if not inv:
        return ""
    s = str(inv).strip().upper()
    s = _RE_NON_ALNUM.sub("", s)
    parts = re.findall(r'\d+|\D+', s)
    parts = [p.lstrip('0') or '0' if p.isdigit() else p for p in parts]
    return ''.join(parts)


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
        if len(short) != len(long) and _is_subsequence(short, long):
            return True

    # Check 2: Shared exact core numeric sequence (using raw tokens to split by separators)
    # We enforce len(na) != len(nb) so we don't accidentally swallow equal-length typos like "INV1" vs "INX1"
    if len(na) != len(nb):
        def _extract_numeric(s: str) -> set[int]:
            # Include numbers >= 1 (allows short numbers like "1" to match as format variants)
            return {int(t) for t in re.findall(r"\d+", str(s)) if int(t) >= 1}

        nums_a = _extract_numeric(a_raw or a or "")
        nums_b = _extract_numeric(b_raw or b or "")
        if nums_a and nums_b and (nums_a & nums_b):
            # Extra guard: one side must have more structure (alpha prefix or longer numeric)
            # to prevent "123" matching "456" via coincidence
            has_alpha_a = bool(re.search(r'[A-Za-z]', (a_raw or a or "")))
            has_alpha_b = bool(re.search(r'[A-Za-z]', (b_raw or b or "")))
            if has_alpha_a or has_alpha_b:
                return True

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
    total_diff = abs(gstr_total - pr_total)
    gstr_is_igst = _safe_paise_field(gstr_rec, "igst_paise") > 0
    pr_is_igst = _safe_paise_field(pr_rec, "igst_paise") > 0
    tax_structure_match = gstr_is_igst == pr_is_igst
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
    inv_sim = invoice_similarity(g_inv, p_inv)
    strong_invoice = inv_ok or format_variant or inv_sim >= INVOICE_SIMILARITY_L5_MIN

    raw_inv_ok = bool(g_inv_raw and p_inv_raw and g_inv_raw == p_inv_raw)
    amount_pct = _compute_percentage_diff(amount_diff, skip_amount, tg, tp)

    amount_within_l1 = skip_amount or (amount_diff == 0)
    amount_within_l2 = skip_amount or (amount_pct <= AMOUNT_TOLERANCE_L2_PCT)
    amount_within_l3 = skip_amount or (amount_pct <= AMOUNT_TOLERANCE_L3_PCT)
    
    date_within_l1 = skip_date or (date_diff_days == 0)
    date_within_l2 = skip_date or (date_diff_days <= DATE_TOLERANCE_L2_DAYS)
    date_within_l3 = skip_date or (date_diff_days <= DATE_TOLERANCE_L3_DAYS)

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
    if gstin_match and raw_inv_ok and _vendor_name_ok:
        if amount_within_l1 and date_within_l1:
            return MatchResult(
                level=1, matched=True, confidence=100, requires_human_review=False,
                decision_what="Exact match found",
                decision_why="Invoice number, amount, and date align",
                decision_next="No action required",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
            )
    # ── Tier 2: Same GSTIN + normalized invoice number (L2) ─────────────────
    if gstin_match and inv_ok:
        if amount_within_l2 and date_within_l2 and tax_structure_match:
            return MatchResult(
                level=2, matched=True, confidence=90, requires_human_review=True,
                decision_what="Invoice matched with normalized invoice and minor amount difference",
                decision_why="Same normalized invoice and GSTIN, amount within acceptable tolerance",
                decision_next="Verify if needed",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
                review_reason=None,
            )
        # Same GSTIN + same normalized invoice but amount or date exceeds L2 — L3 review
        # Large diff + date outside L2 window → return L6 (no match) for extreme cases
        if not date_within_l2 and not amount_within_l2:
            return MatchResult(
                level=6, matched=False, confidence=0, requires_human_review=False,
                decision_what="No match found in purchase register",
                decision_why="Invoice number matches but amount and date differences are too large",
                decision_next="Check if this is the same transaction or raise ITC risk flag.",
                discrepancies=discrepancies, identity_confidence="None", financial_status="None",
            )
        # Determine the dominant reason
        if not tax_structure_match or not l12_finance_ok:
            rr = "AMOUNT_MISMATCH"
        else:
            rr = "Amount Mismatch or Date mismatch"
        return MatchResult(
            level=3, matched=True, confidence=75, requires_human_review=True,
            decision_what="Invoice matched but with differences",
            decision_why="Same invoice number and GSTIN, but amount or date differ",
            decision_next="Review differences and correct if needed",
            review_reason=rr,
            discrepancies=discrepancies,
            identity_confidence="High", financial_status=financial_status,
        )

    # ── Tier 3: Same GSTIN + normalized invoice number + amount within 2% + date within 30 days (L3) ─────────────────
    if gstin_match and inv_ok:
        if amount_within_l3 and date_within_l3:
            return MatchResult(
                level=3, matched=True, confidence=75, requires_human_review=True,
                decision_what="Invoice matched with differences",
                decision_why="Same normalized invoice and GSTIN, but amount or date differ within 2%/30d",
                decision_next="Review differences and correct if needed",
                review_reason="Amount Mismatch or Date mismatch",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
            )

    # ── Tier 3: Same GSTIN + format-variant invoice (L3) ────────────────────
    if gstin_match and format_variant:
        if amount_within_l3 and date_within_l3:
            return MatchResult(
                level=3, matched=True, confidence=75, requires_human_review=True,
                decision_what="Format variant with amount or date mismatch",
                decision_why="Invoice format matches, amount/date within L3 tolerances",
                decision_next="Review differences",
                review_reason="Amount Mismatch or Date mismatch",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
            )

    # ── L6 — No match ────────────────────────────────────────────────────────
    return MatchResult(
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
    skipped_count = 0
    for pr_rec in pr_records:
        gstr_record_id = gstr_rec.get("id")
        pr_record_id = pr_rec.get("id")
        status = gstr_rec.get("status") or pr_rec.get("status") or "matched"

        if status == 'matched':
            if not gstr_record_id or not pr_record_id:
                skipped_count += 1
                continue
        elif status == 'review_required':
            if not gstr_record_id and not pr_record_id:
                skipped_count += 1
                continue

        r = _match_gstr_to_pr_pair(gstr_rec, pr_rec, gstr_by_invoice)
        if r is None:
            skipped_count += 1
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

    if skipped_count > 0:
        import logging
        logging.getLogger(__name__).warning(f"Skipped {skipped_count} invalid match records missing gstr_record_id or pr_record_id")

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
