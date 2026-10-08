"""Issue 2 regressions: CDNR credit notes + Duplicate Entry classification.

(a) PR credit-note / Purchase Return rows (negative amounts) must match
    GSTR-2B CDNR counterparts on absolute magnitude and must NOT land in
    ITC at Risk when a matching CDNR exists.

(b) True duplicate PR bookings (identical full-value rows for one GSTR
    invoice) must auto-match exactly one deterministic canonical PR and
    flag the extras as Duplicate Entry — not ITC at Risk, not Review Required.
    Each duplicate_entry row must record matched_pr_id of the canonical PR.
"""
from __future__ import annotations

from datetime import date

from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import normalize_invoice


GSTIN = "27AABCU1234R1ZX"
PERIOD = date(2024, 3, 1)


def _gstr(rid, inv, taxable, tax, *, doc_type=None, section=None):
    return {
        "id": rid,
        "supplier_gstin": GSTIN,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": date(2024, 3, 15),
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2,
        "sgst_paise": tax - tax // 2,
        "igst_paise": 0,
        "doc_type": doc_type,
        "section": section,
    }


def _pr(rid, inv, taxable, tax, *, invoice_type=None):
    return {
        "id": rid,
        "supplier_gstin": GSTIN,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": date(2024, 3, 15),
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2 if tax >= 0 else -((-tax) // 2),
        "sgst_paise": (tax - tax // 2) if tax >= 0 else -(abs(tax) - abs(tax) // 2),
        "igst_paise": 0,
        "invoice_type": invoice_type,
        "document_type": invoice_type,
    }


# ── (a) Credit note ↔ CDNR ───────────────────────────────────────────────────

def test_pr_credit_note_matches_cdnr_not_in_itc_at_risk():
    """PR CN (negative) + GSTR CDNR (positive), same identity → 1 match, not risk."""
    gstr = [
        _gstr(
            "g-cn",
            "CN-1001",
            100_000,
            18_000,
            doc_type="CREDIT_NOTE",
            section="cdnr",
        )
    ]
    pr = [
        _pr(
            "p-cn",
            "CN-1001",
            -100_000,
            -18_000,
            invoice_type="CREDIT_NOTE",
        )
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["clean_matched_count"] == 1, (
        f"Expected CN↔CDNR clean match; got matched={stats['clean_matched_count']} "
        f"review={stats['review_required_count']} "
        f"reasons={[r.get('review_reason') for r in res['review_required']]}"
    )
    assert stats["wrongful_risk_count"] == 0
    assert stats["missed_itc_count"] == 0
    assert stats["review_required_count"] == 0
    assert res["matched"][0]["gstr_id"] == "g-cn"
    assert res["matched"][0]["pr_id"] == "p-cn"


def test_purchase_return_voucher_matches_cdnr_not_in_itc_at_risk():
    """Negative Purchase Return (no CN prefix) still matches CDNR on magnitude."""
    gstr = [
        _gstr(
            "g-ret",
            "RET/2024/55",
            50_000,
            9_000,
            doc_type="CREDIT_NOTE",
            section="cdnr",
        )
    ]
    pr = [
        _pr("p-ret", "RET/2024/55", -50_000, -9_000),  # negative ⇒ credit note
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]
    assert stats["clean_matched_count"] == 1
    assert stats["wrongful_risk_count"] == 0
    assert stats["missed_itc_count"] == 0


# ── (b) Duplicate Entry ──────────────────────────────────────────────────────

def test_duplicate_pr_is_duplicate_entry_not_itc_at_risk_or_review():
    """1 GSTR + 2 identical PRs → 1 match + 1 Duplicate Entry; not risk/review."""
    gstr = [_gstr("g1", "DUP-55", 250_000, 45_000)]
    pr = [
        _pr("p-zebra", "DUP-55", 250_000, 45_000),
        _pr("p-alpha", "DUP-55", 250_000, 45_000),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["clean_matched_count"] == 1
    assert stats["review_required_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["missed_itc_count"] == 0
    assert stats.get("duplicate_entry_count") == 1
    assert stats.get("duplicate_pr_count") == 1
    assert stats["sanity_passed"] is True

    dup_rows = res.get("duplicate_entries") or []
    assert len(dup_rows) == 1
    dup = dup_rows[0]
    assert dup.get("reason") == "DUPLICATE_ENTRY"
    assert dup.get("id") in ("p-zebra", "p-alpha")
    # Canonical match is deterministic: lowest id string among equal-cost PRs.
    assert res["matched"][0]["pr_id"] == "p-alpha"
    assert dup["matched_pr_id"] == "p-alpha"
    assert dup["id"] == "p-zebra"
    assert dup.get("gstr_id") == "g1"


def test_duplicate_pr_canonical_selection_is_deterministic():
    """Same inputs always pick the same canonical PR (lexicographically lowest id)."""
    gstr = [_gstr("g1", "DUP-DET", 100_000, 18_000)]
    pr = [
        _pr("p-c", "DUP-DET", 100_000, 18_000),
        _pr("p-a", "DUP-DET", 100_000, 18_000),
        _pr("p-b", "DUP-DET", 100_000, 18_000),
    ]
    res1 = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    res2 = run_bidirectional_reconciliation(list(gstr), list(reversed(pr)), gstr_period=PERIOD)

    assert res1["matched"][0]["pr_id"] == "p-a"
    assert res2["matched"][0]["pr_id"] == "p-a"
    assert {d["id"] for d in res1["duplicate_entries"]} == {"p-b", "p-c"}
    for d in res1["duplicate_entries"] + res2["duplicate_entries"]:
        assert d["matched_pr_id"] == "p-a"
        assert d["reason"] == "DUPLICATE_ENTRY"
    assert res1["stats"]["duplicate_entry_count"] == 2
    assert res1["stats"]["wrongful_risk_count"] == 0
    assert res1["stats"]["review_required_count"] == 0


def test_triple_duplicate_pr_one_match_two_duplicate_entries():
    gstr = [_gstr("g1", "TRIP-1", 750_000, 135_000)]
    pr = [
        _pr("p1", "TRIP-1", 750_000, 135_000),
        _pr("p2", "TRIP-1", 750_000, 135_000),
        _pr("p3", "TRIP-1", 750_000, 135_000),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]
    assert stats["clean_matched_count"] == 1
    assert stats["duplicate_entry_count"] == 2
    assert stats["review_required_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    canonical = res["matched"][0]["pr_id"]
    assert canonical == "p1"  # lowest id among p1/p2/p3
    assert {d["matched_pr_id"] for d in res["duplicate_entries"]} == {canonical}


def test_mixed_full_plus_partial_pr_not_mislabeled_duplicate_entry():
    """1 full PR + 1 partial sharing invoice # is not a true-duplicate group.

    Prepass leaves both for Phase 1: full matches cleanly, and the surplus
    conflicting partial row is classified as duplicate review
    (PR_CLAIMED_BY_BETTER_MATCH) per Run 23/24 policy — never double-claiming ITC.
    """
    gstr = [_gstr("g1", "MIX-1", 100_000, 18_000)]
    pr = [
        _pr("p-full", "MIX-1", 100_000, 18_000),
        _pr("p-partial", "MIX-1", 30_000, 5_400),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]
    assert stats["clean_matched_count"] == 1
    assert stats.get("duplicate_entry_count", 0) == 1
    assert res["matched"][0]["pr_id"] == "p-full"
    assert res["duplicate_entries"][0]["id"] == "p-partial"
    assert res["duplicate_entries"][0]["reason"] == "PR_CLAIMED_BY_BETTER_MATCH"


def test_identical_pr_clones_with_gstr_amount_drift_are_duplicate_entries():
    """Two identical PR rows that both drift from GSTR must not leak to ITC at Risk.

    Extreme packs book the invoice twice in PR with the same (wrong) amounts.
    Prepass must flag the extra as Duplicate Entry; the survivor goes to Review
    for the amount gap — never ITC at Risk.
    """
    gstr = [_gstr("g1", "DRIFT-1", 480_340_21, 8_646_124)]
    pr = [
        _pr("p-a", "DRIFT-1", 47_126_801, 8_646_124),
        _pr("p-b", "DRIFT-1", 47_126_801, 8_646_124),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats.get("duplicate_entry_count") == 1
    assert stats["wrongful_risk_count"] == 0
    assert stats["missed_itc_count"] == 0
    # One survivor linked (Review for amount drift, or Matched if tolerances allow)
    assert stats["clean_matched_count"] + stats["review_required_count"] == 1
    dup = res["duplicate_entries"][0]
    survivor = (res["matched"] or res["review_required"])[0]["pr_id"]
    assert dup["id"] in ("p-a", "p-b")
    assert dup["id"] != survivor
    assert dup["matched_pr_id"] == survivor
    assert dup["gstr_id"] == "g1"


def test_duplicate_plus_format_variant_is_l2_matched_not_conflict():
    """True duplicates with GSTR/PR format-variant raw strings → L2 + Duplicate Entry."""
    gstr = [_gstr("g1", "INV/700", 100_000, 18_000)]
    pr = [
        _pr("p-b", "INV-700", 100_000, 18_000),
        _pr("p-a", "INV-700", 100_000, 18_000),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["clean_matched_count"] == 1
    assert res["stats"]["duplicate_entry_count"] == 1
    assert res["matched"][0]["match_level"] == 2
    assert res["matched"][0]["pr_id"] == "p-a"
    assert res["duplicate_entries"][0]["matched_pr_id"] == "p-a"


def test_multiline_format_variant_is_l2_not_forced_l1():
    """Multi-line PR split with format-variant invoice strings → L2 Matched."""
    gstr = [_gstr("g1", "INV/800", 100_000, 18_000)]
    pr = [
        _pr("p1", "INV-800", 60_000, 10_800),
        _pr("p2", "INV-800", 40_000, 7_200),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["clean_matched_count"] == 1
    assert res["stats"].get("duplicate_entry_count", 0) == 0
    m = res["matched"][0]
    assert m.get("multiline_pr_split") is True
    assert m["match_level"] == 2
