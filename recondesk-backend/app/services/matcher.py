"""
GSTR ↔ Purchase Register invoice matcher (levels L1–L6).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Mapping

from app.services.normalizer import is_urp_gstin, URP_NORMALIZED
from app.services.statutory_eligibility import (
    RCM_TRUE,
    RCM_FALSE,
    RCM_UNKNOWN,
    normalize_rcm_tristate,
    detect_rcm_conflict,
    get_rcm_conflict_details,
    detect_tax_head_mismatch,
    get_tax_head_mismatch_details,
)
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
_RE_SERIES_PREFIX = re.compile(r"^[A-Z0-9]*[A-Z]+")
_RE_TRAILING_DIGITS = re.compile(r"\d+$")
_RE_NOTE_IDENTIFIER = re.compile(
    r"(^|[\-_/])(CRN|CN|DBN|DN|CDN|DRN|CREDIT|DEBIT)([\-_/\s0-9]|$)", re.IGNORECASE
)
_RE_FISCAL_SERIES = re.compile(
    r"^[A-Z0-9]{1,5}[/-](?:20\d\d|19\d\d|\d{2}-\d{2})[/-]", re.IGNORECASE
)
_RE_NOTE_IN_B2B = re.compile(
    r"^(?:DBN|CBN|CRN|DRN|CDN|CREDIT(?:NOTE)?|DEBIT(?:NOTE)?)[-_/\s]", re.IGNORECASE
)



def normalise_inv_no(s: Any) -> str:
    """Shared invoice and credit note normaliser for comparison.

    Strips all non-alphanumeric characters and converts to uppercase.
    Only applied at comparison time — does NOT modify stored values.
    Equivalent to:
        const normaliseInvNo = (s) => String(s ?? '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase()
    """
    if s is None:
        return ""
    return _RE_NON_ALNUM.sub("", str(s)).upper()


def normalize_invoice(inv: str | None) -> str:
    """Normalize invoice number by stripping leading zeros per numeric segment and removing non-alphanumerics.

    Also strips a leading ``0`` that sits alone before letters (e.g. portal
    artifacts ``0SI-1798`` / ``0INV/24-25/5024`` → ``SI1798`` / ``INV24255024``),
    matching aggressive ground-truth keying. A lone ``"0"`` is preserved.
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


_OCR_MAP = str.maketrans({
    "O": "0", "o": "0",
    "I": "1", "i": "1", "l": "1",
    "S": "5", "s": "5",
    "Z": "2", "z": "2",
    "B": "8", "b": "8",
})


def ocr_canonical_invoice(s: str | None) -> str:
    """Normalize invoice number with OCR-confused character transliteration."""
    if not s:
        return ""
    norm = normalize_invoice(s)
    return norm.translate(_OCR_MAP)


def count_ocr_substitutions(a: str, b: str) -> tuple[int, bool]:
    """Count OCR transliteration differences between two normalized invoices.

    Returns:
        (substitution_count, has_prefix_or_structural_substitution)
    """
    na, nb = normalize_invoice(a), normalize_invoice(b)
    if not na or not nb or na == nb:
        return 0, False

    ocr_a = ocr_canonical_invoice(na)
    ocr_b = ocr_canonical_invoice(nb)
    if ocr_a != ocr_b:
        return levenshtein(na, nb), True

    subs = 0
    prefix_sub = False
    pa = _RE_LEADING_ALPHA.match(na)
    pb = _RE_LEADING_ALPHA.match(nb)
    p_len_a = pa.end() if pa else 0
    p_len_b = pb.end() if pb else 0
    p_len = max(p_len_a, p_len_b)

    for i, (ca, cb) in enumerate(zip(na, nb)):
        if ca != cb:
            subs += 1
            if i < p_len or (i < 3 and (ca in "15280" or cb in "15280")):
                prefix_sub = True

    diff_len = abs(len(na) - len(nb))
    subs += diff_len
    if diff_len > 0:
        prefix_sub = True

    return subs, prefix_sub


def _pan_of(gstin: str | None) -> str:
    """Return the 10-char PAN embedded in a GSTIN (positions 3-12), else ``""``."""
    g = (gstin or "").strip().upper()
    return g[2:12] if len(g) >= 12 else ""


def same_pan(a: str | None, b: str | None) -> bool:
    """True when both GSTINs carry the same (non-empty) PAN — i.e. likely a typo."""
    pa, pb = _pan_of(a), _pan_of(b)
    return bool(pa) and pa == pb


def supplier_identity_compatible(
    gstr_rec: Mapping[str, Any] | str,
    pr_rec: Mapping[str, Any] | str,
    g_vendor: str | None = None,
    p_vendor: str | None = None,
) -> tuple[bool, str, str]:
    """Evaluate supplier identity compatibility between GSTR and PR records.

    Centralized supplier identity decision helper for all reconciliation passes.
    Enforces deterministic identity boundaries to prevent cross-supplier false
    positives in fuzzy/typo candidate matching.

    Returns:
        (compatible: bool, reason: str, identity_type: str)

    Identity types:
        - "EXACT_GSTIN": Identical 15-character GSTIN.
        - "PAN_MATCH": Same 10-character PAN across different state/branch GSTINs.
        - "URP_SPECIAL_CASE": Unregistered supplier identity validated via vendor name.
        - "BOTH_MISSING": Neither record has a GSTIN.
        - "UNKNOWN": Identity cannot be conclusively verified or refuted.
        - "IDENTITY_CONFLICT": Explicit conflict between suppliers (different PAN/state
          or conflicting URP vendor names).
    """
    if isinstance(gstr_rec, Mapping):
        g_gst = str(gstr_rec.get("supplier_gstin") or gstr_rec.get("gstin") or "").strip().upper()
        g_name = str(gstr_rec.get("supplier_name") or g_vendor or "").strip()
        g_invalid = bool(gstr_rec.get("gstin_format_invalid"))
    else:
        g_gst = str(gstr_rec or "").strip().upper()
        g_name = str(g_vendor or "").strip()
        g_invalid = False

    if isinstance(pr_rec, Mapping):
        p_gst = str(pr_rec.get("supplier_gstin") or pr_rec.get("gstin") or "").strip().upper()
        p_name = str(pr_rec.get("vendor_name") or pr_rec.get("supplier_name") or p_vendor or "").strip()
    else:
        p_gst = str(pr_rec or "").strip().upper()
        p_name = str(p_vendor or "").strip()

    # Normalize URP identifiers
    g_is_urp = is_urp_gstin(g_gst) or g_gst in ("URP", "UNREGISTERED", "URP/RCM", "CONSUMER", "UNREG")
    p_is_urp = is_urp_gstin(p_gst) or p_gst in ("URP", "UNREGISTERED", "URP/RCM", "CONSUMER", "UNREG")

    # 1. URP / Unregistered supplier handling
    if g_is_urp and p_is_urp:
        # DO NOT treat literal "URP" as identity; verify actual vendor names
        if g_name and p_name:
            if l1_vendor_name_ok(g_name, p_name):
                return True, "URP supplier names compatible", "URP_SPECIAL_CASE"
            return False, f"URP supplier identity conflict: {g_name!r} vs {p_name!r}", "IDENTITY_CONFLICT"
        return True, "URP supplier with unverified vendor name", "UNKNOWN"

    if g_is_urp != p_is_urp and (g_gst and p_gst):
        # One is explicitly URP and the other has a registered GSTIN
        return False, "Conflict between unregistered (URP) and registered GSTIN supplier", "IDENTITY_CONFLICT"

    # 2. Both missing GSTIN
    if not g_gst and not p_gst:
        if g_name and p_name:
            if l1_vendor_name_ok(g_name, p_name):
                return True, "Both GSTINs missing, vendor names compatible", "BOTH_MISSING"
            return False, f"Both GSTINs missing, vendor names conflict: {g_name!r} vs {p_name!r}", "IDENTITY_CONFLICT"
        return True, "Both GSTINs missing", "UNKNOWN"

    # 3. One missing GSTIN
    if not g_gst or not p_gst:
        if g_name and p_name:
            if l1_vendor_name_ok(g_name, p_name):
                return True, "One GSTIN missing, vendor names compatible", "UNKNOWN"
            return False, f"One GSTIN missing, vendor names conflict: {g_name!r} vs {p_name!r}", "IDENTITY_CONFLICT"
        return True, "One GSTIN missing", "UNKNOWN"

    # 4. Both have GSTIN - Exact match
    if g_gst == p_gst:
        return True, "Exact GSTIN match", "EXACT_GSTIN"

    # 5. GSTINs differ - Check PAN equality
    pan_g = _pan_of(g_gst)
    pan_p = _pan_of(p_gst)
    if pan_g and pan_p and pan_g == pan_p:
        return True, f"Same PAN ({pan_g}) across different state/branch GSTINs", "PAN_MATCH"

    # 6. Near-match GSTIN (Levenshtein <= 2 for single-character typos/OCR errors)
    if len(g_gst) >= 14 and len(p_gst) >= 14 and levenshtein(g_gst, p_gst) <= 2:
        return True, f"GSTIN near-match (Levenshtein distance <= 2: {g_gst} vs {p_gst})", "PAN_MATCH"

    # 7. Explicit GSTIN/PAN conflict
    return False, f"Supplier GSTIN/PAN conflict: {g_gst} vs {p_gst}", "IDENTITY_CONFLICT"


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

    # OCR transliteration equality (e.g. O↔0, I↔1, S↔5, Z↔2, B↔8)
    ocr_a = ocr_canonical_invoice(na)
    ocr_b = ocr_canonical_invoice(nb)
    if ocr_a and ocr_b and ocr_a == ocr_b:
        return True

    # Check 1: Shared prefix and financial-year expansion or omission
    # e.g. DS/26/78 (DS2678) vs DS-2026-00078 (DS202678), or INV/24-25/78 vs INV-78
    pa = _RE_SERIES_PREFIX.match(na)
    pb = _RE_SERIES_PREFIX.match(nb)
    if pa and pb and pa.group(0) == pb.group(0):
        short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
        pref = pa.group(0)
        rem_s = short[len(pref):]
        rem_l = long[len(pref):]
        # Leading 2-digit FY expansion: e.g. 2678 -> 202678
        if len(rem_s) >= 2 and 20 <= int(rem_s[:2]) <= 35 and "20" + rem_s == rem_l:
            return True
        # Trailing 2-digit FY expansion: e.g. 7826 -> 782026
        if len(rem_s) >= 2 and 20 <= int(rem_s[-2:]) <= 35 and rem_s[:-2] + "20" + rem_s[-2:] == rem_l:
            return True
        # FY expansion: 2425 -> 20242025
        if len(rem_s) >= 4 and rem_s[:4].isdigit() and len(rem_l) >= 8 and rem_l[:8].isdigit():
            if rem_s[:2] == rem_l[2:4] and rem_s[2:4] == rem_l[6:8] and rem_l[:2] == "20" and rem_l[4:6] == "20":
                if rem_s[4:] == rem_l[8:]:
                    return True
        # FY omission: PR dropped the financial year prefix, e.g. INV/24-25/78 (INV242578) vs INV-78 (INV78)
        diff = len(rem_l) - len(rem_s)
        if diff in (2, 4, 6, 8) and rem_l[diff:] == rem_s and rem_s:
            fy_tok = rem_l[:diff]
            raw_l = (a_raw or a or "") if len(na) > len(nb) else (b_raw or b or "")
            # Check FY span pairs: 2425, 202425, 20242025
            if diff == 4 and 20 <= int(fy_tok[:2]) <= 35 and int(fy_tok[2:]) == int(fy_tok[:2]) + 1:
                return True
            if diff == 6 and 2020 <= int(fy_tok[:4]) <= 2035 and int(fy_tok[4:]) == int(fy_tok[2:4]) + 1:
                return True
            if diff == 8 and 2020 <= int(fy_tok[:4]) <= 2035 and int(fy_tok[4:]) == int(fy_tok[:4]) + 1:
                return True
            # For single-year token (diff 2 or 4), must be bounded by delimiters in raw string
            if diff in (2, 4) and raw_l:
                if (diff == 2 and 20 <= int(fy_tok) <= 35) or (diff == 4 and 2020 <= int(fy_tok) <= 2035):
                    if re.search(rf"(?:^|[^0-9A-Za-z]){fy_tok}(?:[^0-9A-Za-z]|$)", raw_l):
                        return True

    # Check 2: Shared exact core numeric sequence (using raw tokens to split by separators)
    # We enforce len(na) != len(nb) so we don't accidentally swallow equal-length typos like "INV1" vs "INX1"
    if len(na) != len(nb):
        def _extract_numeric(s: str) -> list[int]:
            # Include numbers >= 1 not directly followed by letters (prevents '2' in '2BONLY' matching '2')
            return [int(t) for t in re.findall(r"\d+(?![A-Za-z])", str(s)) if int(t) >= 1]

        tokens_a = _extract_numeric(a_raw or a or "")
        tokens_b = _extract_numeric(b_raw or b or "")
        if tokens_a and tokens_b:
            shared_nums = set(tokens_a) & set(tokens_b)
            # Financial-year tokens (e.g. 26 or 2026) cannot by themselves establish format variance
            meaningful_shared = {n for n in shared_nums if not (20 <= n <= 35 or 2020 <= n <= 2035)}
            if meaningful_shared:
                has_alpha_a = bool(re.search(r'[A-Za-z]', (a_raw or a or "")))
                has_alpha_b = bool(re.search(r'[A-Za-z]', (b_raw or b or "")))

                # Sub-check A: Pure numeric invoices with financial year prefix (e.g. 2024-25/089 vs 89)
                if not has_alpha_a and not has_alpha_b and len(tokens_a) != len(tokens_b):
                    short_n, long_n = (tokens_a, tokens_b) if len(tokens_a) < len(tokens_b) else (tokens_b, tokens_a)
                    if short_n and long_n[-len(short_n):] == short_n:
                        pref_tokens = long_n[:-len(short_n)]
                        if all(20 <= t <= 35 or 2020 <= t <= 2035 for t in pref_tokens):
                            return True

                # Sub-check B: Alphanumeric invoices with prefixes/suffixes
                if has_alpha_a or has_alpha_b:
                    if pa and pb:
                        pref_a = pa.group(0)
                        pref_b = pb.group(0)
                        if pref_a == pref_b:
                            # When BOTH sides share the exact same alpha prefix (e.g. "TYPO1" vs
                            # "TYPO1A"), extra characters must be digit-only padding, not a
                            # fresh appended letter which signals a distinct document (amendment).
                            short2, long2 = (na, nb) if len(na) <= len(nb) else (nb, na)
                            if _extra_chars_are_digits_only(short2, long2):
                                return True
                        elif (
                            pref_a.startswith(pref_b)
                            or pref_b.startswith(pref_a)
                            or pref_a.endswith(pref_b)
                            or pref_b.endswith(pref_a)
                        ):
                            # Prefix abbreviation (e.g. "FZ" vs "F") or branch prefix (e.g. "MUMINV" vs "INV")
                            if na[-1].isdigit() and nb[-1].isdigit():
                                return True
                    elif not (pa and pb):
                        # One side has no alpha prefix (e.g. pure numeric '100' or '89').
                        # The core invoice sequence number (last non-FY numeric token) must match!
                        core_a = [t for t in tokens_a if not (20 <= t <= 35 or 2020 <= t <= 2035)]
                        core_b = [t for t in tokens_b if not (20 <= t <= 35 or 2020 <= t <= 2035)]
                        if core_a and core_b and core_a[-1] == core_b[-1]:
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


def is_sequential_series_mismatch(
    inv1: str | None,
    inv2: str | None,
    inv1_raw: str | None = None,
    inv2_raw: str | None = None,
    is_note: bool | None = None,
) -> bool:
    """True when two invoices share the same series/prefix structure but have
    distinct numeric sequence numbers in a sequential series (e.g. INV/25-26/0101
    vs INV/25-26/0197, or INV-100 vs INV-101).

    Such pairs must NEVER be treated as fuzzy typos (L5) in outward sales
    reconciliation because they represent distinct commercial documents.
    """
    s1 = str(inv1 or "").strip()
    s2 = str(inv2 or "").strip()
    if not s1 or not s2:
        return False
    r1 = str(inv1_raw or s1).strip()
    r2 = str(inv2_raw or s2).strip()

    n1 = normalize_invoice(s1)
    n2 = normalize_invoice(s2)
    if not n1 or not n2 or n1 == n2:
        return False

    # Digit transpositions (e.g. 650125 ↔ 605125 or 185025 ↔ 815025) are typos,
    # not sequential series mismatches.
    d1 = "".join(re.findall(r"\d", s1)).lstrip("0")
    d2 = "".join(re.findall(r"\d", s2)).lstrip("0")
    if len(d1) >= 4 and len(d2) >= 4 and Counter(d1) == Counter(d2):
        return False

    def _extract_nums(s: str) -> list[int]:
        return [int(m) for m in re.findall(r"\d+", s)]

    nums1 = _extract_nums(r1)
    nums2 = _extract_nums(r2)

    if nums1 and nums2:
        last1 = nums1[-1]
        last2 = nums2[-1]
        if last1 != last2:
            # Single-character typos that are not consecutive increments (abs(last1 - last2) != 1)
            # are legitimate typos, not sequential series mismatches (e.g. TYPO/26/00113 vs TYPO/26/00116).
            # Exception: Credit/debit notes (e.g. CRN-8812 vs CRN-8813, CRN-901 vs CRN-902)
            # are individual adjustments where single-character differences are clerical typos,
            # not sequential series collisions.
            is_note_doc = bool(is_note) or bool(
                _RE_NOTE_IDENTIFIER.search(s1)
                or _RE_NOTE_IDENTIFIER.search(s2)
                or _RE_NOTE_IDENTIFIER.search(r1)
                or _RE_NOTE_IDENTIFIER.search(r2)
            )
            if levenshtein(n1, n2) == 1:
                if is_note_doc or abs(last1 - last2) != 1:
                    return False

            # 1. Same leading alphabetic prefix (e.g. "INV" on both)
            p1 = _RE_LEADING_ALPHA.match(n1)
            p2 = _RE_LEADING_ALPHA.match(n2)
            if p1 and p2 and p1.group(0) == p2.group(0):
                return True
            # 2. Same normalized series prefix before trailing digits
            m1 = _RE_TRAILING_DIGITS.search(n1)
            m2 = _RE_TRAILING_DIGITS.search(n2)
            if m1 and m2 and m1.group(0) != m2.group(0):
                pref1 = n1[: m1.start()]
                pref2 = n2[: m2.start()]
                if pref1 == pref2:
                    return True
            # 3. Same leading numeric tokens (e.g. same FY [25, 26, 101] vs [25, 26, 197])
            if len(nums1) > 1 and len(nums2) > 1 and nums1[:-1] == nums2[:-1]:
                return True

    return False


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

    ocr_a = ocr_canonical_invoice(a)
    ocr_b = ocr_canonical_invoice(b)
    if ocr_a and ocr_b and ocr_a == ocr_b:
        return 0.95

    max_len = max(len(a), len(b))
    dist = levenshtein(a, b)
    raw_sim = 1.0 - (dist / max_len) if max_len else 0.0

    # Also compute similarity in OCR canonical space (accounting for O↔0, I↔1, S↔5, etc.)
    if ocr_a and ocr_b:
        ocr_max = max(len(ocr_a), len(ocr_b))
        ocr_dist = levenshtein(ocr_a, ocr_b)
        ocr_sim = (1.0 - (ocr_dist / ocr_max)) if ocr_max else 0.0
        return max(raw_sim, ocr_sim)

    return raw_sim


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


def _is_note_doc(rec: Mapping[str, Any] | None) -> bool:
    if not rec:
        return False
    sec = str(rec.get("section") or "").lower().strip()
    if sec in ("cdnr", "cdnra", "cdnur", "cdnura"):
        return True
    doc = str(rec.get("doc_type") or rec.get("document_type") or "").upper().strip()
    return doc in ("CREDIT_NOTE", "DEBIT_NOTE", "CRN", "DRN", "CN", "DN") or bool(rec.get("pr_note_quarantine"))


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

    g_is_note = _is_note_doc(gstr_rec)
    p_is_note = _is_note_doc(pr_rec)
    if not g_is_note and not p_is_note:
        g_orig = str(gstr_rec.get("original_invoice_number") or gstr_rec.get("oinum") or "").strip()
        p_orig = str(pr_rec.get("original_invoice_number") or pr_rec.get("oinum") or "").strip()
        if g_orig and not inv_ok and not format_variant:
            if invoices_effectively_match(g_orig, p_inv) or is_invoice_format_variant(g_orig, p_inv):
                format_variant = True
                inv_ok = True
        if p_orig and not inv_ok and not format_variant:
            if invoices_effectively_match(g_inv, p_orig) or is_invoice_format_variant(g_inv, p_orig):
                format_variant = True
                inv_ok = True
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

    tax_g = _safe_paise_field(gstr_rec, "total_tax_paise")
    tax_p = _safe_paise_field(pr_rec, "total_tax_paise")
    if tax_g or tax_p:
        tax_diff = abs(tax_g - tax_p)
        if tax_diff <= AMOUNT_TOLERANCE_L1_PAISE:
            out.append(_field_entry("tax_amount", "exact"))
        else:
            tax_pct = tax_diff / float(max(tax_g, tax_p)) if max(tax_g, tax_p) > 0 else 1.0
            if tax_pct <= AMOUNT_TOLERANCE_L3_PCT:
                out.append(_field_entry("tax_amount", "fuzzy", int(round(max(0.0, 1.0 - tax_pct) * 100))))
            else:
                out.append(_field_entry("tax_amount", "not_matched"))

    dg = _parse_invoice_date(gstr_rec)
    dp = _parse_invoice_date(pr_rec)
    date_diff_days, skip_date = _date_diff_days_and_skip(dg, dp)
    if skip_date or date_diff_days == 0:
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

    g_rcm_cf = _is_record_rcm(gstr_rec)
    p_rcm_cf = _is_record_rcm(pr_rec)
    if detect_rcm_conflict(g_rcm_cf, p_rcm_cf):
        out.append(_field_entry("reverse_charge", "not_matched"))
    elif g_rcm_cf in (RCM_TRUE, RCM_FALSE) and g_rcm_cf == p_rcm_cf:
        out.append(_field_entry("reverse_charge", "exact"))
    elif g_rcm_cf != RCM_UNKNOWN or p_rcm_cf != RCM_UNKNOWN:
        out.append(_field_entry("reverse_charge", "exact"))

    th_mismatch, _ = detect_tax_head_mismatch(gstr_rec, pr_rec)
    both_have_bd = _has_component_tax_breakdown(gstr_rec) and _has_component_tax_breakdown(pr_rec)
    if both_have_bd:
        if th_mismatch:
            out.append(_field_entry("tax_heads", "not_matched"))
        else:
            out.append(_field_entry("tax_heads", "exact"))

    return out


def _safe_paise_field(rec: Mapping[str, Any], key: str) -> int:
    v = rec.get(key, 0)
    if v is None:
        return 0
    return int(v)


def _optional_taxable(rec: Mapping[str, Any]) -> int | None:
    # 1. Direct paise fields (PR standard: taxable_amount_paise; GSTR standard: taxable_value_paise)
    for k in ("taxable_amount_paise", "taxable_value_paise", "taxable_paise"):
        if k in rec:
            v = rec[k]
            if v is not None:
                return int(v)

    # 2. Rupee fields (taxable_amount, taxable_value, txval, taxable_amt)
    for k in ("taxable_amount", "taxable_value", "txval", "taxable_amt"):
        if k in rec:
            v = rec[k]
            if v is not None:
                try:
                    return int(round(float(v) * 100))
                except (ValueError, TypeError):
                    pass

    # 3. Item-level roll-up if items array present
    items = rec.get("items")
    if isinstance(items, list) and items:
        total_items = 0
        has_item = False
        for itm in items:
            if isinstance(itm, dict):
                iv = itm.get("taxable_value_paise") or itm.get("taxable_amount_paise")
                if iv is not None:
                    total_items += int(iv)
                    has_item = True
                elif itm.get("txval") is not None or itm.get("taxable_value") is not None:
                    try:
                        total_items += int(round(float(itm.get("txval") or itm.get("taxable_value")) * 100))
                        has_item = True
                    except (ValueError, TypeError):
                        pass
        if has_item:
            return total_items

    # 4. Derivation from total invoice value minus total tax
    inv_val = None
    for k in ("invoice_value_paise", "total_amount_paise", "total_value_paise"):
        if k in rec and rec[k] is not None:
            try:
                inv_val = int(rec[k])
                break
            except (ValueError, TypeError):
                pass
    if inv_val is None:
        for k in ("invoice_value", "total_amount", "val", "total_value"):
            if k in rec and rec[k] is not None:
                try:
                    inv_val = int(round(float(rec[k]) * 100))
                    break
                except (ValueError, TypeError):
                    pass

    if inv_val is not None:
        tot_tax = _safe_paise_field(rec, "total_tax_paise")
        if tot_tax == 0:
            tot_tax = (
                _safe_paise_field(rec, "igst_paise")
                + _safe_paise_field(rec, "cgst_paise")
                + _safe_paise_field(rec, "sgst_paise")
                + _safe_paise_field(rec, "cess_paise")
            )
        if tot_tax >= 0 and inv_val >= tot_tax:
            return inv_val - tot_tax

    return None


def _invoice_total_paise(rec: Mapping[str, Any]) -> int:
    # 1. Prefer explicit invoice total when present and non-zero
    for k in ("invoice_value_paise", "total_amount_paise", "total_value_paise"):
        if k in rec and rec[k] is not None:
            try:
                v = int(rec[k])
                if v != 0:
                    return v
            except (ValueError, TypeError):
                pass
    for k in ("invoice_value", "total_amount", "val", "total_value"):
        if k in rec and rec[k] is not None:
            try:
                v = int(round(float(rec[k]) * 100))
                if v != 0:
                    return v
            except (ValueError, TypeError):
                pass

    # 2. Derive as taxable + total tax
    taxable = _optional_taxable(rec) or 0
    tot_tax = _safe_paise_field(rec, "total_tax_paise")
    if tot_tax == 0:
        tot_tax = (
            _safe_paise_field(rec, "igst_paise")
            + _safe_paise_field(rec, "cgst_paise")
            + _safe_paise_field(rec, "sgst_paise")
            + _safe_paise_field(rec, "cess_paise")
        )
    return taxable + tot_tax


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
    if v is None or str(v).strip() == "":
        v = (
            rec.get("inum")
            or rec.get("nt_num")
            or rec.get("ntnum")
            or rec.get("credit_note_number")
            or rec.get("note_number")
            or rec.get("invoice_number_raw")
        )
    return "" if v is None else str(v).strip()


def _supplier_gstin(rec: Mapping[str, Any]) -> str:
    v = rec.get("supplier_gstin")
    if v is None or str(v).strip() == "":
        v = rec.get("gstin")
    if v is None:
        return ""
    val_str = str(v).strip().upper()
    if is_urp_gstin(val_str):
        return URP_NORMALIZED
    return val_str


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


def normalise_inv_no(s: Any) -> str:
    """Symmetric invoice / document number normalisation.

    Strips all characters except alphanumeric [0-9a-zA-Z] and converts to upper case.
    Matches TypeScript helper:
      (s) => String(s ?? '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase()
    """
    if s is None:
        return ""
    val = str(s).strip()
    if not val:
        return ""
    return re.sub(r"[^0-9a-zA-Z]", "", val).upper()


_STANDARD_DOC_PREFIXES = (
    "INV", "TAX", "BILL", "CN", "DN", "INVOICE", "DOC", "CR", "DR", "RET",
    "SI", "TI", "PI", "VCH", "PV", "TAXINV", "TAX_INV",
)


def invoices_effectively_match(g_inv: str, p_inv: str) -> bool:
    if not g_inv or not p_inv:
        return False
    norm_g = normalise_inv_no(g_inv)
    norm_p = normalise_inv_no(p_inv)
    if norm_g and norm_p and norm_g == norm_p:
        return True
    ocr_g = ocr_canonical_invoice(g_inv)
    ocr_p = ocr_canonical_invoice(p_inv)
    if ocr_g and ocr_p and ocr_g == ocr_p:
        return True
    # If one side includes a standard prefix (INV, CN, etc.) and the other omits it
    if norm_g and norm_p:
        for pref in _STANDARD_DOC_PREFIXES:
            if norm_g.startswith(pref) and norm_g[len(pref):] == norm_p:
                return True
            if norm_p.startswith(pref) and norm_p[len(pref):] == norm_g:
                return True
    a = _invoice_key_for_match(g_inv)
    b = _invoice_key_for_match(p_inv)
    return bool(a) and bool(b) and a == b



def _is_credit_note(rec: Mapping[str, Any] | None) -> bool:
    """Return True if rec represents a credit note or sales return.

    Document-type aware helper used to normalize signs between negative-entry
    accounting systems (Sales Register / Purchase Register) and positive-document
    GST portals (GSTR-1 CDNR / GSTR-2B CDNR).
    """
    if not rec:
        return False
    section = str(rec.get("section") or "").lower().strip()
    if section in ("cdnr", "cdnra", "cdnur", "cdnura"):
        return True
    if section in ("b2b", "b2ba", "b2cl", "b2cla", "b2cs", "b2csa", "exp", "expa"):
        return False
    doc_type = str(rec.get("doc_type") or "").upper().strip()
    inv_type = str(rec.get("invoice_type") or "").upper().strip()
    document_type = str(rec.get("document_type") or "").upper().strip()
    if (
        doc_type in ("INVOICE", "TAX_INVOICE", "INV")
        or inv_type in ("INVOICE", "TAX_INVOICE", "INV")
        or document_type in ("INVOICE", "TAX_INVOICE", "INV")
    ):
        if not (rec.get("credit_note_number") or rec.get("note_number") or rec.get("nt_num") or rec.get("ntnum") or str(rec.get("ntty") or "").upper().strip() in ("C", "CR")):
            return False
    if doc_type in ("CREDIT_NOTE", "CN", "CREDIT", "C"):
        return True
    if inv_type in ("CREDIT_NOTE", "CN", "CREDIT", "C"):
        return True
    ntty = str(rec.get("ntty") or "").upper().strip()
    if ntty in ("C", "CR", "CREDIT", "CREDIT_NOTE"):
        return True
    voucher_type = str(rec.get("voucher_type") or "").upper().strip()
    if "CREDIT" in voucher_type or voucher_type in ("CN", "CR NOTE", "CR. NOTE"):
        return True
    if rec.get("credit_note_number") or rec.get("note_number") or rec.get("nt_num") or rec.get("ntnum"):
        return True
    inv_num = str(rec.get("invoice_number_raw") or rec.get("invoice_number") or "").strip()
    if inv_num and _RE_FISCAL_SERIES.search(inv_num):
        pass
    elif inv_num and re.search(r"(^|[\-_/])(CRN|CN)([\-_/\s0-9]|$)", inv_num, re.IGNORECASE):
        return True
    taxable = _optional_taxable(rec)
    if taxable is not None:
        try:
            if int(taxable) < 0:
                return True
        except (ValueError, TypeError):
            pass
    tot = rec.get("total_tax_paise")
    if tot is not None:
        try:
            if int(tot) < 0:
                return True
        except (ValueError, TypeError):
            pass
    return False


def _is_debit_note(rec: Mapping[str, Any] | None) -> bool:
    """Return True if rec represents a debit note."""
    if not rec:
        return False
    doc_type = str(rec.get("doc_type") or "").upper().strip()
    inv_type = str(rec.get("invoice_type") or "").upper().strip()
    document_type = str(rec.get("document_type") or "").upper().strip()
    if (
        doc_type in ("INVOICE", "TAX_INVOICE", "INV")
        or inv_type in ("INVOICE", "TAX_INVOICE", "INV")
        or document_type in ("INVOICE", "TAX_INVOICE", "INV")
    ):
        if not (rec.get("debit_note_number") or rec.get("note_number") or rec.get("nt_num") or rec.get("ntnum") or str(rec.get("ntty") or "").upper().strip() in ("D", "DR")):
            return False
    if doc_type in ("DEBIT_NOTE", "DN", "DEBIT", "D", "DBN"):
        return True
    if inv_type in ("DEBIT_NOTE", "DN", "DEBIT", "D", "DBN"):
        return True
    ntty = str(rec.get("ntty") or "").upper().strip()
    if ntty in ("D", "DR", "DEBIT", "DEBIT_NOTE"):
        return True
    voucher_type = str(rec.get("voucher_type") or "").upper().strip()
    if "DEBIT" in voucher_type or voucher_type in ("DN", "DR NOTE", "DR. NOTE"):
        return True
    inv_num = str(rec.get("invoice_number_raw") or rec.get("invoice_number") or "").strip()
    if inv_num and _RE_FISCAL_SERIES.search(inv_num):
        pass
    elif inv_num and re.search(r"(^|[\-_/])(DBN|DN)([\-_/\s0-9]|$)", inv_num, re.IGNORECASE):
        return True
    return False


def _is_record_rcm(rec: Mapping[str, Any] | None) -> str:
    """Return RCM_TRUE, RCM_FALSE, or RCM_UNKNOWN using normalize_rcm_tristate.

    Checks standard GSTN keys (rev, rchrg, reverse_charge) as well as PR columns.
    """
    if not rec:
        return RCM_UNKNOWN
    for k in (
        "reverse_charge",
        "reverse_charge_raw",
        "rev",
        "rchrg",
        "rev_chg",
        "rcm",
        "is_rcm",
        "reverse_charge_applicable",
    ):
        val = rec.get(k)
        if val is not None:
            norm = normalize_rcm_tristate(val)
            if norm != RCM_UNKNOWN:
                return norm
    return RCM_UNKNOWN


def are_document_types_compatible(
    gstr_rec: Mapping[str, Any] | None, pr_rec: Mapping[str, Any] | None
) -> tuple[bool, str]:
    """Strict compatibility gate enforcing note direction and blocking cross-type matches.

    Distinguishes:
      - Invoices vs Notes (invoices cannot match notes).
      - Supplier Credit Note vs Buyer Credit Note / Purchase Return / Return Debit Note.
      - Supplier Debit Note vs Buyer Debit Note / Supplementary Invoice.
    """
    if not gstr_rec or not pr_rec:
        return True, "MISSING_RECORD"

    g_is_cn = _is_credit_note(gstr_rec)
    g_is_dn = _is_debit_note(gstr_rec)
    g_is_note = g_is_cn or g_is_dn

    p_is_cn = _is_credit_note(pr_rec)
    p_is_dn = _is_debit_note(pr_rec)
    p_is_note = p_is_cn or p_is_dn or bool(pr_rec.get("pr_note_quarantine"))

    # 1. Reject cross-type match (Invoice <-> Note)
    if g_is_note != p_is_note:
        # Failsafe: If GSTR is a verified B2B invoice (not a note) and PR has non-negative
        # amount and was not explicitly quarantined in a notes sheet, treat as compatible invoice pair.
        if not g_is_note:
            p_quarantine = bool(pr_rec.get("pr_note_quarantine"))
            p_note_no = bool(pr_rec.get("note_number"))
            p_taxable = _optional_taxable(pr_rec)
            p_taxable_val = int(p_taxable) if p_taxable is not None else 0
            if not p_quarantine and not p_note_no and p_taxable_val >= 0:
                return True, "INVOICE_PAIR"
        return False, "CROSS_DOCUMENT_TYPE_REJECTED"

    if not g_is_note:
        # Both are normal purchase invoices
        return True, "INVOICE_PAIR"

    # 2. Both are notes — evaluate directional semantic compatibility
    p_taxable = _optional_taxable(pr_rec)
    p_taxable_val = int(p_taxable) if p_taxable is not None else 0
    p_is_negative = p_taxable_val < 0

    if g_is_cn:
        # GSTR is a CREDIT_NOTE (supplier reduced liability / ITC reduction for buyer)
        if p_is_cn:
            # PR is also credit note (or negative purchase return)
            return True, "COMPATIBLE_CREDIT_NOTE"
        if p_is_dn and (p_is_negative or bool(pr_rec.get("pr_note_quarantine"))):
            # PR recorded as buyer debit note for return / chargeback
            return True, "COMPATIBLE_BUYER_RETURN_DEBIT_NOTE"
        return False, "CREDIT_NOTE_VS_DEBIT_NOTE_MISMATCH"

    if g_is_dn:
        # GSTR is a DEBIT_NOTE (supplier increased liability / additional ITC for buyer)
        if p_is_dn and not p_is_negative:
            # PR is debit note / supplementary charge with positive amount
            return True, "COMPATIBLE_DEBIT_NOTE"
        return False, "DEBIT_NOTE_VS_CREDIT_NOTE_MISMATCH"

    return False, "UNKNOWN_NOTE_TYPE"


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
    # Strict semantic compatibility gate: reject invoice <-> note or incompatible note types
    compat, compat_reason = are_document_types_compatible(gstr_rec, pr_rec)
    if not compat:
        return MatchResult(
            level=6,
            matched=False,
            confidence=0,
            requires_human_review=False,
            decision_what="Document type mismatch",
            decision_why=f"Incompatible document types: {compat_reason}",
            decision_next="Review document types. Invoices cannot match credit/debit notes.",
            discrepancies=[f"doc_type: {compat_reason}"],
        )

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
    both_have_tax_breakdown = _has_component_tax_breakdown(
        gstr_rec
    ) and _has_component_tax_breakdown(pr_rec)

    tax_head_mismatch, tax_head_msg = detect_tax_head_mismatch(gstr_rec, pr_rec)
    tax_structure_match = not tax_head_mismatch
    has_tax_lines = _has_explicit_total_tax_line(gstr_rec, pr_rec)

    g_rcm = _is_record_rcm(gstr_rec)
    p_rcm = _is_record_rcm(pr_rec)
    rcm_conflict = detect_rcm_conflict(g_rcm, p_rcm)

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

    if tax_head_mismatch:
        g_igst = _safe_paise_field(gstr_rec, "igst_paise")
        g_cgst = _safe_paise_field(gstr_rec, "cgst_paise")
        g_sgst = _safe_paise_field(gstr_rec, "sgst_paise")
        g_cess = _safe_paise_field(gstr_rec, "cess_paise")
        p_igst = _safe_paise_field(pr_rec, "igst_paise")
        p_cgst = _safe_paise_field(pr_rec, "cgst_paise")
        p_sgst = _safe_paise_field(pr_rec, "sgst_paise")
        p_cess = _safe_paise_field(pr_rec, "cess_paise")
        gstr_heads = f"IGST={g_igst/100:.2f}, CGST={g_cgst/100:.2f}, SGST={g_sgst/100:.2f}, Cess={g_cess/100:.2f}"
        pr_heads = f"IGST={p_igst/100:.2f}, CGST={p_cgst/100:.2f}, SGST={p_sgst/100:.2f}, Cess={p_cess/100:.2f}"
        discrepancies.append(f"tax_head_mismatch: GSTR-2B=({gstr_heads}), PR=({pr_heads})")

    if rcm_conflict:
        discrepancies.append(f"rcm_conflict: GSTR-2B={g_rcm}, PR={p_rcm}")

    inv_ok = invoices_effectively_match(g_inv, p_inv)
    format_variant = False
    if not inv_ok:
        format_variant = is_invoice_format_variant(g_inv, p_inv, gstr_rec.get("invoice_number"), pr_rec.get("invoice_number"))

    g_orig = str(gstr_rec.get("original_invoice_number") or gstr_rec.get("oinum") or "").strip()
    p_orig = str(pr_rec.get("original_invoice_number") or pr_rec.get("oinum") or "").strip()
    if not inv_ok and not format_variant and not _is_note_doc(gstr_rec) and not _is_note_doc(pr_rec):
        if g_orig:
            if invoices_effectively_match(g_orig, p_inv) or is_invoice_format_variant(
                g_orig, p_inv, gstr_rec.get("original_invoice_number_raw") or g_orig, pr_rec.get("invoice_number")
            ):
                inv_ok = True
                format_variant = True
                discrepancies.append(f"amendment: Amended invoice {g_inv} links to original {g_orig}")
        if not inv_ok and not format_variant and p_orig:
            if invoices_effectively_match(g_inv, p_orig) or is_invoice_format_variant(
                g_inv, p_orig, gstr_rec.get("invoice_number"), pr_rec.get("original_invoice_number_raw") or p_orig
            ):
                inv_ok = True
                format_variant = True
                discrepancies.append(f"amendment: PR original invoice {p_orig} links to GSTR {g_inv}")

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

    # Note-in-B2B document type guard:
    # If a supplier files a Credit Note or Debit Note under the B2B invoice table
    # (e.g. prefix DBN/, CBN/, CRN/, DRN/, or explicit CBT/DBT doc_type hint),
    # link the pair but route to Review Required. A Credit Note in B2B requires
    # ITC reversal in GSTR-3B Table 4(B)(2) rather than regular Table 4(A)(5) claim.
    g_sec = str(gstr_rec.get("section") or gstr_rec.get("table_name") or "").lower().strip()
    is_cdnr = g_sec in ("cdnr", "cdnra", "cdnur", "cdnura")
    is_b2b_section = g_sec in ("b2b", "b2ba", "")

    g_is_cn = _is_credit_note(gstr_rec)
    g_is_dn = _is_debit_note(gstr_rec)
    p_is_cn = _is_credit_note(pr_rec)
    p_is_dn = _is_debit_note(pr_rec)
    is_legit_note_pair = is_cdnr or (g_is_cn and p_is_cn) or (g_is_dn and p_is_dn)

    g_raw_inv = str(gstr_rec.get("invoice_number_raw") or gstr_rec.get("invoice_number") or "").strip()
    p_raw_inv = str(pr_rec.get("invoice_number_raw") or pr_rec.get("invoice_number") or "").strip()

    note_in_b2b = not is_legit_note_pair and is_b2b_section and (
        bool(_RE_NOTE_IN_B2B.match(g_raw_inv))
        or bool(_RE_NOTE_IN_B2B.match(p_raw_inv))
        or str(gstr_rec.get("inv_typ") or "").upper().strip() in ("CBT", "DBT")
        or str(pr_rec.get("document_type") or "").upper().strip() in ("CREDIT_NOTE", "DEBIT_NOTE", "CBT", "DBT")
        or str(pr_rec.get("invoice_type") or "").upper().strip() in ("CREDIT_NOTE", "DEBIT_NOTE", "CBT", "DBT")
    )

    if note_in_b2b and gstin_match and (inv_ok or format_variant):
        is_credit = bool(
            re.search(r"^(?:CBN|CRN|CDN|CREDIT)", g_raw_inv or p_raw_inv, re.IGNORECASE)
            or "C" in str(pr_rec.get("document_type") or "").upper()
            or "C" in str(pr_rec.get("invoice_type") or "").upper()
            or str(gstr_rec.get("inv_typ") or "").upper().strip() == "CBT"
        )
        note_type_str = "Credit Note (CBN/CRN)" if is_credit else "Debit Note (DBN/DRN)"
        b2b_discrepancies = list(discrepancies) + [f"doc_type: Note in B2B table ({note_type_str})"]
        return _ret(
            level=2,
            matched=True,
            confidence=85,
            requires_human_review=True,
            decision_what="Potential Credit/Debit Note filed in B2B table",
            decision_why=(
                f"Invoice number prefix or document type indicates a {note_type_str} filed "
                "in the B2B invoice table instead of the CDNR table. Verify document nature."
            ),
            decision_next=(
                "Verify document nature with supplier. If this is a Credit Note, "
                "ensure ITC is reversed in GSTR-3B Table 4(B)(2); do not claim as domestic inward ITC."
            ),
            discrepancies=b2b_discrepancies,
            identity_confidence="High",
            financial_status=financial_status,
            review_reason="DOC_TYPE_NOTE_IN_B2B",
        )

    # ── Tax-head allocation mismatch guard ───────────────────────────────────
    if tax_head_mismatch and gstin_match and (inv_ok or format_variant):
        th_what, th_why, th_next = get_tax_head_mismatch_details(gstr_rec, pr_rec, tax_head_msg)
        return _ret(
            level=3,
            matched=True,
            confidence=75,
            requires_human_review=True,
            decision_what=th_what,
            decision_why=th_why,
            decision_next=th_next,
            discrepancies=discrepancies,
            identity_confidence="High",
            financial_status="Tax Mismatch",
            review_reason="TAX_HEAD_MISMATCH",
        )

    # ── Reverse Charge (RCM) conflict guard ──────────────────────────────────
    if rcm_conflict and gstin_match and (inv_ok or format_variant):
        rcm_what, rcm_why, rcm_next = get_rcm_conflict_details(g_rcm, p_rcm)
        return _ret(
            level=3,
            matched=True,
            confidence=75,
            requires_human_review=True,
            decision_what=rcm_what,
            decision_why=rcm_why,
            decision_next=rcm_next,
            discrepancies=discrepancies,
            identity_confidence="High",
            financial_status=financial_status,
            review_reason="RCM_FLAG_CONFLICT",
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
    norm_g = normalize_invoice(g_inv)
    norm_p = normalize_invoice(p_inv)
    ocr_subs, ocr_pfx = count_ocr_substitutions(g_inv, p_inv)
    ocr_only_match = (
        not raw_inv_ok
        and bool(norm_g and norm_p and norm_g != norm_p)
        and ocr_canonical_invoice(norm_g) == ocr_canonical_invoice(norm_p)
    )
    is_risky_ocr = ocr_only_match and ((ocr_subs >= 2) or ocr_pfx)

    if (
        gstin_match
        and (inv_ok or format_variant)
        and _vendor_name_ok
        and zero_discrepancy
        and date_within_l1
        and tax_structure_match
        and not rcm_conflict
    ):
        if is_risky_ocr:
            ocr_discrepancies = list(discrepancies) + [
                f"ocr_review: Invoice numbers differ by {ocr_subs} OCR character(s) ({g_inv} vs {p_inv})"
            ]
            return _ret(
                level=3,
                matched=True,
                confidence=75,
                requires_human_review=True,
                decision_what=f"Invoice matched via OCR correction with {ocr_subs} character substitutions",
                decision_why=(
                    f"Invoice numbers {g_inv} (GSTR-2B) and {p_inv} (PR) differ by {ocr_subs} "
                    "OCR character substitutions. Physical invoice review required."
                ),
                decision_next="Verify physical document to ensure invoice number OCR reading is correct before claiming ITC.",
                discrepancies=ocr_discrepancies,
                identity_confidence="Medium",
                financial_status="Exact",
                review_reason="OCR_CONFIDENCE_REVIEW",
            )
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
            if is_risky_ocr:
                rr = "OCR_CONFIDENCE_REVIEW"
                d_what = f"Invoice matched via OCR correction with {ocr_subs} character substitutions"
                d_why = f"Same normalized invoice identity via OCR transliteration ({ocr_subs} corrections); verification required"
            elif date_diff_days > 0 and amount_within_l1 and tax_only_diff <= AMOUNT_TOLERANCE_L1_PAISE:
                d_what = f"Invoice matched; invoice date differs by {date_diff_days} days"
                d_why = f"Same normalized invoice and GSTIN, date differs by {date_diff_days} days (within {DATE_TOLERANCE_L2_DAYS}-day tolerance)"
                rr = "DATE_MISMATCH"
            elif amount_diff > AMOUNT_TOLERANCE_L1_PAISE or tax_only_diff > AMOUNT_TOLERANCE_L1_PAISE:
                diff_to_report = amount_diff if amount_diff > AMOUNT_TOLERANCE_L1_PAISE else tax_only_diff
                d_what = f"Invoice matched; minor amount difference of {_rs_str(diff_to_report)}"
                d_why = f"Same normalized invoice and GSTIN, amount differs by {_rs_str(diff_to_report)} (within 1% tolerance)"
                rr = "AMOUNT_MISMATCH"
            elif date_diff_days > 0:
                d_what = f"Invoice matched; invoice date differs by {date_diff_days} days"
                d_why = f"Same normalized invoice and GSTIN, date differs by {date_diff_days} days (within {DATE_TOLERANCE_L2_DAYS}-day tolerance)"
                rr = "DATE_MISMATCH"
            else:
                d_what = "Invoice matched with normalized invoice and minor amount difference"
                d_why = "Same normalized invoice and GSTIN, amount within acceptable tolerance"
                rr = "AMOUNT_MISMATCH"

            return _ret(
                level=2, matched=True, confidence=90, requires_human_review=True,
                decision_what=d_what,
                decision_why=d_why,
                decision_next="Verify if needed",
                discrepancies=discrepancies,
                identity_confidence="High", financial_status=financial_status,
                review_reason=rr,
            )

        # Same GSTIN + same normalized invoice but amount or date exceeds L2 — L3 review.
        # Exact invoice identity is never rejected: even when BOTH amount and date
        # exceed L2 (e.g. 5.83% amount + 10-day date gap), link as Review Required.
        # Returning L6 here previously orphaned the pair into Missed ITC + ITC at
        # Risk as if the invoice numbers had never matched.
        if not tax_structure_match:
            th_what, th_why, th_next = get_tax_head_mismatch_details(gstr_rec, pr_rec, tax_head_msg)
            rr = "TAX_HEAD_MISMATCH"
            d_what = th_what
            d_why = th_why
            d_next = th_next
        elif not l12_finance_ok or not amount_within_l2:
            rr = "AMOUNT_MISMATCH"
            d_what = "Invoice matched but with differences"
            d_why = "Same invoice number and GSTIN, but amount or date differ"
            d_next = "Review differences and correct if needed"
        else:
            rr = "Amount Mismatch or Date mismatch"
            d_what = "Invoice matched but with differences"
            d_why = "Same invoice number and GSTIN, but amount or date differ"
            d_next = "Review differences and correct if needed"
        return _ret(
            level=3, matched=True, confidence=75, requires_human_review=True,
            decision_what=d_what,
            decision_why=d_why,
            decision_next=d_next,
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
            if amount_within_l1 and not skip_amount:
                d_what = f"Format variant with date difference of {date_diff_days} days"
                d_why = f"Invoice format matches, date differs by {date_diff_days} days"
            elif date_within_l1 and not skip_date:
                d_what = f"Format variant with amount difference of {_rs_str(amount_diff)}"
                d_why = f"Invoice format matches, amount differs by {_rs_str(amount_diff)}"
            else:
                d_what = "Format variant with amount or date mismatch"
                d_why = "Invoice format matches, amount/date within L3 tolerances"

            return _ret(
                level=3, matched=True, confidence=75, requires_human_review=True,
                decision_what=d_what,
                decision_why=d_why,
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
                        abs(int(_optional_taxable(gstr) or 0))
                        - abs(int(_optional_taxable(pr) or 0))
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
                abs(int(_optional_taxable(c["pr"]) or 0))
                - abs(int(_optional_taxable(gstr) or 0))
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
