"""Tests for the matching-engine double-counting / GSTIN-safety / normalization patch.

Covers the acceptance scenarios:
  - same GSTIN + same invoice + same amount        -> EXACT
  - same GSTIN + DS-2026-00078 vs DS/26/78         -> NORMALIZED/FUZZY match
  - same GSTIN + same invoice + amount mismatch     -> DISCREPANCY (not two orphans)
  - different GSTIN (same PAN) + same invoice       -> GSTIN_MISMATCH review (not EXACT/FUZZY)
  - duplicate PR invoice                            -> not double-counted
  - Rule 37 candidates                              -> untouched by the orphan resolver
"""

import uuid
from datetime import date

from app.services.matcher import (
    _match_gstr_to_pr_pair,
    is_invoice_format_variant,
    match_gstr_to_pr,
    normalize_invoice_number,
    same_pan,
)
from app.matching.engine import run_bidirectional_reconciliation, resolve_orphans

GSTIN = "27AABCU9603R1ZX"
GSTIN_TYPO = "27AABCU9603R1ZF"  # same PAN (AABCU9603R), different check char
GSTIN_OTHER = "29ABCDE1234F1Z5"


def _rec(rid, gstin, inv, taxable, *, inv_date="2026-05-10", cgst=None, sgst=None):
    cg = taxable * 9 // 100 if cgst is None else cgst
    sg = taxable * 9 // 100 if sgst is None else sgst
    return {
        "id": rid,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "cgst_paise": cg,
        "sgst_paise": sg,
        "igst_paise": 0,
        "total_tax_paise": cg + sg,
    }


# --- shared helpers ---------------------------------------------------------


def test_normalize_invoice_number_examples():
    assert normalize_invoice_number("DS-2026-00078") == "DS202600078"
    assert normalize_invoice_number("DS/26/78") == "DS2678"
    assert normalize_invoice_number("INV 001") == "INV1"   # space stripped, 001→1
    assert normalize_invoice_number("inv_001") == "INV1"   # underscore stripped, 001→1
    
    # Bug fix regression tests: zero-padded without separators
    assert normalize_invoice_number("002312526") == normalize_invoice_number("2312526")
    assert normalize_invoice_number("003652526") == normalize_invoice_number("3652526")
    assert normalize_invoice_number("004992526") == normalize_invoice_number("4992526")
    assert normalize_invoice_number("INV-001") == normalize_invoice_number("INV001")
    assert normalize_invoice_number("RD-25-APR-00224") != normalize_invoice_number("RD/2025/APR/00224")

    assert normalize_invoice_number(None) == ""
    assert normalize_invoice_number("") == ""


def test_is_invoice_format_variant():
    assert is_invoice_format_variant("DS-2026-00078", "DS/26/78") is True
    assert is_invoice_format_variant("INV-001", "INV001") is True
    # equal-length single-char typos are NOT variants (kept as L4 review)
    assert is_invoice_format_variant("INV001", "INV002") is False
    # different prefix is not a variant
    assert is_invoice_format_variant("ABC123", "XYZ123") is False


def test_same_pan():
    assert same_pan(GSTIN, GSTIN_TYPO) is True
    assert same_pan(GSTIN, GSTIN_OTHER) is False
    assert same_pan("", GSTIN) is False


# --- matcher-level scenarios ------------------------------------------------


def test_exact_match_same_gstin_invoice_amount():
    g = _rec("g1", GSTIN, "INV-100", 1_000_000)
    p = _rec("p1", GSTIN, "INV-100", 1_000_000)
    r = match_gstr_to_pr(g, [p])
    assert r is not None and r.level == 1 and r.matched is True
    assert r.requires_human_review is False


def test_format_variant_is_fuzzy_normalized_match():
    g = _rec("g1", GSTIN, "DS-2026-00078", 8_500_000)
    p = _rec("p1", GSTIN, "DS/26/78", 8_500_000)
    r = match_gstr_to_pr(g, [p])
    assert r is not None and r.matched is True
    # Bug 1 fix: zero-discrepancy format variants (same GSTIN, same amount, same
    # date — only the invoice-number formatting differs) are promoted to a clean
    # L1 match, not left as an L2 review item.
    assert r.level == 1
    assert r.requires_human_review is False
    assert r.review_reason is None


def test_amount_mismatch_links_as_discrepancy():
    g = _rec("g1", GSTIN, "ALPHA-91", 12_000_000)
    p = _rec("p1", GSTIN, "ALPHA-91", 10_200_000)  # 15% lower
    r = match_gstr_to_pr(g, [p])
    assert r is not None and r.matched is True
    assert r.level == 3
    assert r.requires_human_review is True
    assert r.review_reason.startswith('AMOUNT_MISMATCH')


def test_gstin_mismatch_is_review_not_match():
    g = _rec("g1", GSTIN, "CAP-88", 2_500_000)
    p = _rec("p1", GSTIN_TYPO, "CAP-88", 2_500_000)
    # match_gstr_to_pr filters non-matched candidates, so inspect the pair directly.
    r = _match_gstr_to_pr_pair(g, p)
    assert r.matched is False  # never a clean EXACT/FUZZY
    assert r.review_reason.startswith("GSTIN_MISMATCH")
    assert r.requires_human_review is True


# --- reconciliation-level (no double counting) ------------------------------


def test_amount_mismatch_not_two_orphans():
    # 15% amount diff is outside L3's 5% band, but same GSTIN + same invoice
    # number means these are still clearly the same invoice, not two unrelated
    # orphans — the pair must link as ONE reviewable record, never split into
    # both missed_itc (GSTR-side orphan) and wrongful_itc_risk (PR-side orphan).
    res = run_bidirectional_reconciliation(
        [_rec("g1", GSTIN, "ALPHA-91", 12_000_000)],
        [_rec("p1", GSTIN, "ALPHA-91", 10_200_000)],
        gstr_period=date(2026, 5, 1),
    )
    assert res["stats"]["total_linked_count"] == 1
    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["wrongful_risk_count"] == 0
    assert res["stats"]["sanity_passed"] is True


def test_format_variant_not_two_orphans():
    res = run_bidirectional_reconciliation(
        [_rec("g1", GSTIN, "DS-2026-00078", 8_500_000)],
        [_rec("p1", GSTIN, "DS/26/78", 8_500_000)],
        gstr_period=date(2026, 5, 1),
    )
    assert res["stats"]["matched_count"] == 1
    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["wrongful_risk_count"] == 0


def test_gstin_typo_pairs_into_gstin_mismatch_not_double_orphan():
    res = run_bidirectional_reconciliation(
        [_rec("g1", GSTIN, "CAP-88", 2_500_000)],
        [_rec("p1", GSTIN_TYPO, "CAP-88", 2_500_000)],
        gstr_period=date(2026, 5, 1),
    )
    assert res["stats"]["gstin_mismatch_count"] == 1
    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["wrongful_risk_count"] == 0
    assert res["stats"]["sanity_passed"] is True


def test_duplicate_pr_invoice_does_not_double_count():
    res = run_bidirectional_reconciliation(
        [_rec("g1", GSTIN, "DUP-55", 2_500_000)],
        [
            _rec("p1", GSTIN, "DUP-55", 2_500_000),
            _rec("p2", GSTIN, "DUP-55", 2_500_000),  # exact duplicate booking
        ],
        gstr_period=date(2026, 5, 1),
    )
    # Correct behavior: first PR matches normally, second is a duplicate data-entry flag
    assert res["stats"]["matched_count"] == 1
    assert res["stats"]["wrongful_risk_count"] == 0
    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["duplicate_pr_count"] == 1
    assert res["stats"]["duplicate_conflict_count"] == 0
    assert res["stats"]["sanity_passed"] is True


def test_duplicate_gstr_invoice_not_counted_as_missed_itc():
    res = run_bidirectional_reconciliation(
        [
            _rec("g1", GSTIN, "DUP-2B", 2_500_000),
            _rec("g2", GSTIN, "DUP-2B", 2_500_000),  # supplier filed twice
        ],
        [_rec("p1", GSTIN, "DUP-2B", 2_500_000)],
        gstr_period=date(2026, 5, 1),
    )
    # New behavior: many-to-one maps to review_required
    assert res["stats"]["matched_count"] == 0
    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["duplicate_conflict_count"] == 2


# --- Rule 37 untouched ------------------------------------------------------


def test_resolver_leaves_genuine_pr_only_risk_for_rule37():
    """A genuine PR-only invoice (unique PAN, no GSTR partner) must remain in the
    ITC-at-Risk pool so the Rule 37 tracker still sees it — resolver must not eat it.
    """
    missed = []  # no GSTR orphans
    wrongful = [
        {
            "id": "p1",
            "supplier_gstin": GSTIN_OTHER,
            "invoice_number_normalized": "R37OLD001",
            "invoice_date": "2025-10-01",
            "taxable_amount_paise": 9_000_000,
            "total_tax_paise": 1_620_000,
        }
    ]
    matched_final, new_missed, new_wrongful, gm, review_required, _dup_pr = resolve_orphans(
        matched=[],
        missed_itc=missed,
        wrongful_itc_risk=wrongful,
        gstr_by_id={},
        pr_by_id={"p1": wrongful[0]},
    )
    assert new_wrongful == wrongful
    assert gm == []
    assert review_required == []
