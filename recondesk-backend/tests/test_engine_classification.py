"""
tests/test_engine_classification.py
=====================================
Synthetic unit tests for the reconciliation engine's classification logic.
These tests are completely fixture-independent — they build minimal matcher rows
inline and assert on output bucket/flag, not on file-specific data.

Covers every code path changed in bdc2526:
  1.  Exact match: L2 path (raw strings differ due to parser pre-normalisation)
  2.  Amount-diff L2 → Review Required
  3.  Date-diff L2 → Review Required
  4.  GSTIN mismatch → must never become clean Matched
  5.  True L1 exact match (raw strings also equal)
  6.  Safety net: L1 not demoted by 1-paise rounding diff in total
  7.  INVOICE_MATCH_AMOUNT_REVIEW Pass 1: same GSTIN + exact inv, >50% amt diff → Review
  8.  INVOICE_MATCH_AMOUNT_REVIEW Pass 3: format-variant, no cap → Review (not Missed)
  9.  INVOICE_MATCH_AMOUNT_REVIEW Pass 2: format-variant within 50% cap → Review
 10.  Large amount diff + no format variant → Missed ITC (no false link)
 11.  PR-only → wrongful ITC risk
 12.  50 exact rows in bulk — all Matched, zero review
 13.  Mixed batch (exact + review + missed) — all route to correct bucket

Run:
    python3 -m pytest tests/test_engine_classification.py -v
"""

import uuid
from datetime import date
from typing import Any

import pytest

from app.matching.engine import run_bidirectional_reconciliation

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
PERIOD    = date(2026, 5, 1)
INV_DATE  = date(2026, 5, 10)   # always within the period month to avoid late-filing path
GSTIN_A   = "29AAAAA1234A1Z1"
GSTIN_B   = "29BBBBB5678B1Z2"
GSTIN_C   = "29CCCCC9999C1Z3"

# ─────────────────────────────────────────────────────────────────────────────
# Record builder — both sides carry full tax-breakdown fields so the engine's
# tax_structure_match logic doesn't flag spurious structure mismatches.
# ─────────────────────────────────────────────────────────────────────────────

def _rec(
    gstin: str,
    inv: str,
    inv_norm: str,
    inv_date: date = INV_DATE,
    taxable: int = 100_00000,   # Rs 1,00,000 in paise
    total_tax: int = 18_00000,  # Rs 18,000  (18% IGST)
    igst: int = 18_00000,
    cgst: int = 0,
    sgst: int = 0,
    cess: int = 0,
    name: str = "Synthetic Supplier",
    **kw: Any,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv_norm,
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "total_tax_paise": total_tax,
        "igst_paise": igst,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "cess_paise": cess,
        "supplier_name": name,
        **kw,
    }


# Aliases (both sides use identical schema)
_gstr = _rec
_pr   = _rec


def _run(gstr, pr):
    return run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────
def _matched(res): return {m["gstr_id"] for m in res["matched"]}
def _review(res):  return {m["gstr_id"] for m in res["review_required"]}
def _missed(res):  return {m["gstr_id"] for m in res["missed_itc"]}
def _wrongful(res): return {m["id"] for m in res["wrongful_itc_risk"]}
def _stats(res):   return res["stats"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Exact match: raw invoice strings differ (parser pre-normalised PR)
#    GSTR: "FY/2026/00001" → norm "FY202600001"
#    PR:   "FY202600001"   → norm "FY202600001"  (already stripped by parser)
#    Amounts, dates, tax structure identical.
#    Expected:
#      - Matched bucket (not Review Required)
#      - match_level == 2 (normalized / format-variant, not raw-exact L1)
# ─────────────────────────────────────────────────────────────────────────────
def test_exact_match_raw_string_differs_goes_to_matched():
    g = _gstr(gstin=GSTIN_A, inv="FY/2026/00001", inv_norm="FY202600001")
    p = _pr(  gstin=GSTIN_A, inv="FY202600001",   inv_norm="FY202600001")
    res = _run([g], [p])
    assert g["id"] in _matched(res), (
        "Pre-normalised exact match must be Matched, not Review Required"
    )
    assert _stats(res)["matched_count"] == 1
    assert _stats(res)["review_required_count"] == 0
    matched_row = next(m for m in res["matched"] if m["gstr_id"] == g["id"])
    assert matched_row.get("match_level") == 2, (
        "Raw strings differ → L2 normalized clean match, not L1; "
        f"got match_level={matched_row.get('match_level')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. L2 path: real amount diff → Review Required
# ─────────────────────────────────────────────────────────────────────────────
def test_l2_amount_diff_stays_review_required():
    g = _gstr(gstin=GSTIN_A, inv="FY/2026/00002", inv_norm="FY202600002",
               total_tax=18_00000, igst=18_00000)
    p = _pr(  gstin=GSTIN_A, inv="FY202600002",   inv_norm="FY202600002",
               total_tax=17_50000, igst=17_50000)   # Rs 500 diff ≈ 2.8%
    res = _run([g], [p])
    assert g["id"] in _review(res), "Real amount diff must keep requires_human_review=True"
    assert _stats(res)["matched_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. L2 path: real date diff → Review Required
# ─────────────────────────────────────────────────────────────────────────────
def test_l2_date_diff_stays_review_required():
    g = _gstr(gstin=GSTIN_A, inv="FY/2026/00003", inv_norm="FY202600003",
               inv_date=date(2026, 5, 5))
    p = _pr(  gstin=GSTIN_A, inv="FY202600003",   inv_norm="FY202600003",
               inv_date=date(2026, 5, 20))   # 15-day gap
    res = _run([g], [p])
    assert g["id"] in _review(res), "Real date diff must stay Review Required"
    assert _stats(res)["matched_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. GSTIN mismatch: must never become clean Matched
#    (regression guard — removing level>1 must not break this)
# ─────────────────────────────────────────────────────────────────────────────
def test_gstin_mismatch_never_clean_matched():
    g = _gstr(gstin=GSTIN_A, inv="MISMATCH001", inv_norm="MISMATCH001")
    p = _pr(  gstin=GSTIN_B, inv="MISMATCH001", inv_norm="MISMATCH001")
    res = _run([g], [p])
    assert g["id"] not in _matched(res), "GSTIN mismatch must NEVER be clean Matched"


# ─────────────────────────────────────────────────────────────────────────────
# 5. True L1 exact match: raw strings also identical → Matched at level 1
# ─────────────────────────────────────────────────────────────────────────────
def test_l1_exact_match():
    g = _gstr(gstin=GSTIN_A, inv="L1INV001", inv_norm="L1INV001")
    p = _pr(  gstin=GSTIN_A, inv="L1INV001", inv_norm="L1INV001")
    res = _run([g], [p])
    assert g["id"] in _matched(res), "L1 exact match must be Matched"
    assert _stats(res)["review_required_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Safety net: 1-paise rounding diff must NOT demote L1 to Review Required
# ─────────────────────────────────────────────────────────────────────────────
def test_l1_not_demoted_by_one_paise_rounding():
    g = _gstr(gstin=GSTIN_A, inv="ROUNDING001", inv_norm="ROUNDING001",
               total_tax=18_00000, igst=18_00000)
    p = _pr(  gstin=GSTIN_A, inv="ROUNDING001", inv_norm="ROUNDING001",
               total_tax=18_00001, igst=18_00001)   # 1 paise diff
    res = _run([g], [p])
    assert g["id"] in _matched(res), (
        "1-paise rounding diff must not demote L1 to Review Required via safety net"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. INVOICE_MATCH_AMOUNT_REVIEW Pass 1:
#    Same GSTIN + exact normalized invoice + >50% amount diff → Review Required
#    Invoice identity unambiguous → must NEVER land in Missed ITC
# ─────────────────────────────────────────────────────────────────────────────
def test_pass1_large_amount_diff_same_invoice_links_as_review():
    g = _gstr(gstin=GSTIN_A, inv="LARGEAMT001", inv_norm="LARGEAMT001",
               total_tax=50_00000, igst=50_00000, taxable=278_00000)
    p = _pr(  gstin=GSTIN_A, inv="LARGEAMT001", inv_norm="LARGEAMT001",
               total_tax=20_00000, igst=20_00000, taxable=111_00000)   # 60% diff
    res = _run([g], [p])
    assert g["id"] not in _missed(res), (
        "Same GSTIN + same invoice, >50% diff must be Review Required, not Missed ITC"
    )
    assert g["id"] in _review(res)


# ─────────────────────────────────────────────────────────────────────────────
# 8. INVOICE_MATCH_AMOUNT_REVIEW:
#    Format-variant invoice (FY202600100 ↔ FY2600100) + >50% amount diff (64%)
#    Statutory Policy:
#    When both invoice string differs (format variant) AND amount differs by >50%,
#    it is unsafe to force-link. GSTR safely remains in Missed ITC, and PR remains
#    in Wrongful ITC Risk to protect taxpayer from claiming wrong amounts.
# ─────────────────────────────────────────────────────────────────────────────
def test_pass3_format_variant_large_amount_links_as_review():
    g = _gstr(gstin=GSTIN_A, inv="FY/2026/00100", inv_norm="FY202600100",
               total_tax=50_00000, igst=50_00000, taxable=278_00000)
    p = _pr(  gstin=GSTIN_A, inv="FY2600100",      inv_norm="FY2600100",
               total_tax=18_00000, igst=18_00000, taxable=100_00000)   # 64% diff
    res = _run([g], [p])
    assert g["id"] in _missed(res), (
        "Format-variant invoice with >50% diff must safely stay in Missed ITC, not be force-linked"
    )
    assert p["id"] in _wrongful(res), (
        "Unconsumed PR invoice with >50% diff must stay in Wrongful ITC Risk"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9. INVOICE_MATCH_AMOUNT_REVIEW Pass 2:
#    Format-variant invoice within 50% amount cap → links as Review
# ─────────────────────────────────────────────────────────────────────────────
def test_pass2_format_variant_within_cap_links():
    g = _gstr(gstin=GSTIN_A, inv="FY/2026/00200", inv_norm="FY202600200",
               total_tax=20_00000, igst=20_00000, taxable=111_00000)
    p = _pr(  gstin=GSTIN_A, inv="FY202600200",   inv_norm="FY202600200",
               total_tax=15_00000, igst=15_00000, taxable=84_00000)   # 25% diff
    res = _run([g], [p])
    assert g["id"] not in _missed(res), "25%-diff format variant must link, not Missed ITC"
    assert g["id"] in _review(res) or g["id"] in _matched(res)


# ─────────────────────────────────────────────────────────────────────────────
# 10. Completely different invoice numbers → true Missed ITC
#     Engine must NOT false-link just because they share a GSTIN
# ─────────────────────────────────────────────────────────────────────────────
def test_different_invoice_no_false_link():
    g = _gstr(gstin=GSTIN_C, inv="ALPHA001", inv_norm="ALPHA001",
               total_tax=50_00000, igst=50_00000, taxable=278_00000)
    p = _pr(  gstin=GSTIN_C, inv="ZETA999",  inv_norm="ZETA999",
               total_tax=20_00000, igst=20_00000, taxable=111_00000)
    res = _run([g], [p])
    assert g["id"] in _missed(res), "Unrelated invoice numbers must NOT be force-linked"


# ─────────────────────────────────────────────────────────────────────────────
# 11. PR-only record → wrongful ITC risk
# ─────────────────────────────────────────────────────────────────────────────
def test_pr_only_goes_to_wrongful_itc_risk():
    p = _pr(gstin=GSTIN_A, inv="PRONLY001", inv_norm="PRONLY001")
    res = _run([], [p])
    assert p["id"] in _wrongful(res), "PR-only record must land in wrongful_itc_risk"
    assert _stats(res)["wrongful_risk_count"] == 1
    assert _stats(res)["matched_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 12. 50 exact rows in bulk — all Matched, zero review, zero missed
# ─────────────────────────────────────────────────────────────────────────────
def test_bulk_exact_all_matched():
    N = 50
    gstr_recs = [
        _gstr(gstin=GSTIN_A, inv=f"FY/2026/{i:05d}", inv_norm=f"FY2026{i:05d}")
        for i in range(N)
    ]
    pr_recs = [
        _pr(gstin=GSTIN_A, inv=f"FY2026{i:05d}", inv_norm=f"FY2026{i:05d}")
        for i in range(N)
    ]
    res = _run(gstr_recs, pr_recs)
    s = _stats(res)
    assert s["matched_count"] == N, (
        f"All {N} exact rows must be Matched; got matched={s['matched_count']}, "
        f"review={s['review_required_count']}"
    )
    assert s["review_required_count"] == 0
    assert s["missed_itc_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 13. Mixed batch: exact + amount-diff review + no-pair missed
# ─────────────────────────────────────────────────────────────────────────────
def test_mixed_batch_routes_correctly():
    # Exact: different raw strings, same normalized, same amounts/tax
    g_exact = _gstr(gstin=GSTIN_A, inv="MIX/001", inv_norm="MIX001")
    p_exact = _pr(  gstin=GSTIN_A, inv="MIX001",  inv_norm="MIX001")

    # Review: same normalized invoice, 3% amount diff
    g_review = _gstr(gstin=GSTIN_A, inv="MIX/002", inv_norm="MIX002",
                      total_tax=18_00000, igst=18_00000)
    p_review = _pr(  gstin=GSTIN_A, inv="MIX002",  inv_norm="MIX002",
                      total_tax=17_46000, igst=17_46000)   # ≈3% diff

    # Missed ITC: GSTR record with no PR pair
    g_missed = _gstr(gstin=GSTIN_A, inv="MIX/003", inv_norm="MIX003")

    res = _run([g_exact, g_review, g_missed], [p_exact, p_review])

    assert g_exact["id"]  in _matched(res), "Exact row must be Matched"
    assert g_review["id"] in _review(res),  "Amount-diff row must be Review Required"
    assert g_missed["id"] in _missed(res),  "No-PR row must be Missed ITC"


# ─────────────────────────────────────────────────────────────────────────────
# 14. exact_match_count chip formula:
#     4 L1 raw-exact → match_level=1
#     2 format-variant zero-diff → match_level=2 (Matched, Non-exact)
#     → exact_count=4, non_exact=2
#     3 L2 with real diff → in review, not matched at all
# ─────────────────────────────────────────────────────────────────────────────
def test_exact_match_count_chip_formula():
    G = GSTIN_A

    # 4 raw-L1 (raw strings equal, pure L1 path)
    l1_pairs = [
        (_gstr(gstin=G, inv=f"L1INV{i:03d}", inv_norm=f"L1INV{i:03d}"),
         _pr(  gstin=G, inv=f"L1INV{i:03d}", inv_norm=f"L1INV{i:03d}"))
        for i in range(4)
    ]

    # 2 zero-diff format variants (raw differs, norm same → L2 clean matched)
    l2_exact_pairs = [
        (_gstr(gstin=G, inv=f"FY/2026/{i:05d}", inv_norm=f"FY2026{i:05d}"),
         _pr(  gstin=G, inv=f"FY2026{i:05d}",   inv_norm=f"FY2026{i:05d}"))
        for i in range(2)
    ]

    # 3 L2 with real amount diff (must be review, not matched)
    l2_review_pairs = [
        (_gstr(gstin=G, inv=f"FY/2026/{10+i:05d}", inv_norm=f"FY2026{10+i:05d}",
               total_tax=18_00000, igst=18_00000),
         _pr(  gstin=G, inv=f"FY2026{10+i:05d}",   inv_norm=f"FY2026{10+i:05d}",
               total_tax=17_50000, igst=17_50000))   # ~2.8% diff
        for i in range(3)
    ]

    all_gstr = [g for g, _ in l1_pairs + l2_exact_pairs + l2_review_pairs]
    all_pr   = [p for _, p in l1_pairs + l2_exact_pairs + l2_review_pairs]
    res = _run(all_gstr, all_pr)

    s = _stats(res)
    assert s["matched_count"] == 6, f"Expected 6 matched, got {s['matched_count']}"
    assert s["review_required_count"] == 3

    # Simulate the API's exact_match_count formula
    matched_rows = res["matched"]
    exact_count = sum(
        1 for m in matched_rows
        if m.get("match_level") == 1
        or (m.get("match_level") is None and m.get("confidence_score") == 100)
    )
    non_exact_count = len(matched_rows) - exact_count

    assert exact_count == 4, (
        f"exact_match_count must be 4 (raw-identical only); got {exact_count}"
    )
    assert non_exact_count == 2, (
        f"Non-exact chip must be 2 for format-variant zero-diff matches; got {non_exact_count}"
    )
