"""Fuzzy duplicate detection: mangled-invoice extras of already-linked PRs.

When the canonical booking matches GSTR via typo/format-variant (so prepass
never saw a GSTR on the extra's exact key), or when the extra itself has a
mangled invoice number (NIV455325 vs INV455325), the extra must become
Duplicate Entry — not ITC at Risk.
"""
from __future__ import annotations

from datetime import date

from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import invoice_similarity, normalize_invoice

GSTIN = "07ZTQEX7711GGZW"
PERIOD = date(2026, 3, 1)


def _g(rid, inv, taxable, tax, inv_date="2025-08-08"):
    return {
        "id": rid,
        "supplier_gstin": GSTIN,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2,
        "sgst_paise": tax - tax // 2,
        "igst_paise": 0,
    }


def _p(rid, inv, taxable, tax, inv_date="2025-08-08"):
    return {
        "id": rid,
        "supplier_gstin": GSTIN,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2,
        "sgst_paise": tax - tax // 2,
        "igst_paise": 0,
    }


def test_mangled_invoice_extra_is_duplicate_entry_not_itc_at_risk():
    """INV455325 linked; NIV455325 (differing prefix) is not canonical duplicate."""
    g_inv, p_canon, p_extra = "INV-4553/25", "INV455325", "NIV455325"
    assert normalize_invoice(g_inv) == "INV455325"
    assert 0.75 <= invoice_similarity(p_canon, p_extra) < 1.0

    gstr = [_g("g1", g_inv, 33_316_906, 9_328_734)]
    pr = [
        _p("p-canon", p_canon, 33_316_906, 9_328_734),
        _p("p-extra", p_extra, 33_316_906, 9_328_734),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 1
    assert stats["duplicate_entry_count"] == 0
    assert stats["clean_matched_count"] + stats["review_required_count"] == 1
    assert {w["id"] for w in res["wrongful_itc_risk"]} == {"p-extra"}


def test_same_invoice_extra_after_format_variant_match_is_duplicate():
    """GSTR format differs; two identical PRs — one matches, extra is Duplicate Entry.

    Prepass sees 0 GSTR on the PR key (GSTR raw normalizes differently enough that
    Phase 1 still links via format variant / L2). The unconsumed twin must not
    become ITC at Risk.
    """
    # GSTR with separators; both PRs use compact form sharing the same key.
    gstr = [_g("g1", "BILL-8010/2", 18_852_389, 942_619, inv_date="2026-03-11")]
    pr = [
        _p("p-a", "BILL80102", 18_852_389, 942_619, inv_date="2026-03-11"),
        _p("p-b", "BILL80102", 18_852_389, 942_619, inv_date="2026-03-11"),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["wrongful_risk_count"] == 0
    assert stats["duplicate_entry_count"] == 1
    assert stats["clean_matched_count"] + stats["review_required_count"] == 1
    assert {d["id"] for d in res["duplicate_entries"]} <= {"p-a", "p-b"}


def test_digit_transposition_extra_is_duplicate_entry():
    """SL912825 extra of linked SL192825: distinct sequence must not collapse into duplicate."""
    a, b = "SL192825", "SL912825"
    assert abs(invoice_similarity(a, b) - 0.75) < 1e-9

    gstr = [_g("g1", "SL-1928/25", 41_907_614, 2_095_381, inv_date="2025-05-13")]
    pr = [
        _p("p-canon", a, 41_907_614, 2_095_381, inv_date="2025-05-13"),
        _p("p-extra", b, 41_907_614, 2_095_381, inv_date="2025-05-13"),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["wrongful_risk_count"] == 1
    assert stats["duplicate_entry_count"] == 0
    assert {w["id"] for w in res["wrongful_itc_risk"]} == {"p-extra"}


def test_unrelated_invoice_same_amounts_not_fuzzy_duplicate():
    """Low invoice similarity must not flag a coincidental same-amount PR as dup."""
    gstr = [_g("g1", "ALPHA-9999", 300_000, 54_000)]
    pr = [
        _p("p-real", "ALPHA-9999", 300_000, 54_000),
        _p("p-other", "ZYXWV-1234", 300_000, 54_000),
    ]
    assert invoice_similarity("ALPHA9999", "ZYXWV1234") < 0.75

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats.get("duplicate_entry_count", 0) == 0
    assert stats["wrongful_risk_count"] == 1
    assert {w["id"] for w in res["wrongful_itc_risk"]} == {"p-other"}


def test_unconsumed_pr_peer_clones_flag_one_duplicate():
    """Two unlinked PR clones (no GSTR) → one Duplicate Entry, one ITC at Risk."""
    a, b = "INV455325", "NIV455325"
    assert 0.75 <= invoice_similarity(a, b) < 1.0

    gstr = []  # no 2B counterpart
    pr = [
        _p("p-a", a, 33_316_906, 9_328_734),
        _p("p-b", b, 33_316_906, 9_328_734),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["duplicate_entry_count"] == 1
    assert stats["wrongful_risk_count"] == 1
    assert {d["id"] for d in res["duplicate_entries"]} | {
        w["id"] for w in res["wrongful_itc_risk"]
    } == {"p-a", "p-b"}


def test_linked_extra_with_taxable_drift_high_sim_is_duplicate():
    """Linked canonical + sequential extra (INV455325 vs INV455326): distinct sequence is not duplicate."""
    g_inv, p_canon, p_extra = "INV-4553/25", "INV455325", "INV455326"
    assert invoice_similarity(p_canon, p_extra) >= 0.85

    g_taxable = 10_000_000
    p_extra_taxable = 10_180_000  # 1.8%
    g_tax = 1_800_000
    pr_extra_tax = 1_832_400

    gstr = [_g("g1", g_inv, g_taxable, g_tax)]
    pr = [
        _p("p-canon", p_canon, g_taxable, g_tax),
        _p("p-extra", p_extra, p_extra_taxable, pr_extra_tax),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["wrongful_risk_count"] == 1
    assert stats["duplicate_entry_count"] == 0
    assert {w["id"] for w in res["wrongful_itc_risk"]} == {"p-extra"}


def test_exact_invoice_double_booking_with_amount_drift_is_duplicate():
    """Same invoice booked twice with ~4% taxable drift → Duplicate, not ITC at Risk.

    Claude's tame-pack gap: exact-key extras with small amount typos used to leak
    into ITC at Risk because prepass required ₹1 equality.
    """
    g_taxable, g_tax = 10_000_000, 1_800_000
    extra_taxable = 10_400_000  # 4%
    extra_tax = 1_872_000

    gstr = [_g("g1", "INV-9001", g_taxable, g_tax)]
    pr = [
        _p("p-canon", "INV-9001", g_taxable, g_tax),
        _p("p-extra", "INV-9001", extra_taxable, extra_tax),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["wrongful_risk_count"] == 0
    assert stats["duplicate_entry_count"] == 1
    assert stats["clean_matched_count"] + stats["review_required_count"] == 1
    assert res["duplicate_entries"][0]["id"] == "p-extra"
    assert res["duplicate_entries"][0]["matched_pr_id"] == "p-canon"


def test_exact_invoice_double_booking_with_date_drift_is_duplicate():
    """Same invoice twice, 50 days apart → still Duplicate Entry (exact-inv gate)."""
    g_taxable, g_tax = 5_000_000, 900_000
    gstr = [_g("g1", "INV-9002", g_taxable, g_tax, inv_date="2026-01-05")]
    pr = [
        _p("p-canon", "INV-9002", g_taxable, g_tax, inv_date="2026-01-05"),
        _p("p-extra", "INV-9002", g_taxable, g_tax, inv_date="2026-02-24"),  # 50d
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["wrongful_risk_count"] == 0
    assert stats["duplicate_entry_count"] == 1
    assert res["duplicate_entries"][0]["id"] == "p-extra"


def test_exact_invoice_peer_with_amount_drift_flags_one_duplicate():
    """No GSTR: two exact-invoice PR copies with 4% drift → one Dup, one Risk."""
    a_taxable, a_tax = 8_000_000, 1_440_000
    b_taxable, b_tax = 8_320_000, 1_497_600  # 4%

    res = run_bidirectional_reconciliation(
        [],
        [
            _p("p-a", "INV-PEER-01", a_taxable, a_tax),
            _p("p-b", "INV-PEER-01", b_taxable, b_tax),
        ],
        gstr_period=PERIOD,
    )
    stats = res["stats"]

    assert stats["duplicate_entry_count"] == 1
    assert stats["wrongful_risk_count"] == 1
    assert {d["id"] for d in res["duplicate_entries"]} | {
        w["id"] for w in res["wrongful_itc_risk"]
    } == {"p-a", "p-b"}


def test_exact_invoice_amount_drift_over_5pct_not_forced_duplicate():
    """Exact invoice with >5% taxable gap is conflicting duplicate per Run 23/24."""
    g_taxable, g_tax = 10_000_000, 1_800_000
    extra_taxable = 10_600_000  # 6%
    extra_tax = 1_908_000

    gstr = [_g("g1", "INV-9003", g_taxable, g_tax)]
    pr = [
        _p("p-canon", "INV-9003", g_taxable, g_tax),
        _p("p-extra", "INV-9003", extra_taxable, extra_tax),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    # Survivor matches GSTR; conflicting duplicate entry is classified per Run 23/24 policy.
    assert stats["clean_matched_count"] + stats["review_required_count"] == 1
    assert stats["duplicate_entry_count"] == 1
    assert res["duplicate_entries"][0]["id"] == "p-extra"
    assert res["duplicate_entries"][0]["reason"] == "PR_CLAIMED_BY_BETTER_MATCH"


def test_different_invoices_near_amounts_not_collapsed_as_duplicates():
    """Same vendor, different invoice numbers, similar amounts → never Duplicate."""
    gstr = [
        _g("g1", "BOOK-1001", 1_000_000, 180_000),
        _g("g2", "BOOK-1002", 1_020_000, 183_600),
    ]
    pr = [
        _p("p1", "BOOK-1001", 1_000_000, 180_000),
        _p("p2", "BOOK-1002", 1_020_000, 183_600),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats.get("duplicate_entry_count", 0) == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["clean_matched_count"] + stats["review_required_count"] == 2


def test_high_sim_neighbor_with_divergent_tax_is_itc_at_risk_not_duplicate():
    """May tame-pack regression: INV53169 must not clone linked INV53161.

    Same GSTIN, invoice sim ≥ 0.85, taxable within ~1%, dates within 30d — but
    total tax differs by >50% (different rate). That is a genuine PR-only /
    missing-from-2B invoice → ITC at Risk, not Duplicate Entry.

    Prior bug: ``tax_ok = … or sim >= 0.85`` waived the tax gate on similarity
    alone and swallowed the planted missing_from_2b row.
    """
    # Mirrors May-26: linked INV-05-3161 vs planted INV-05-3169 (Delhi Traders).
    linked_inv, orphan_inv = "INV53161", "INV53169"
    assert invoice_similarity(linked_inv, orphan_inv) >= 0.85

    linked_taxable = 7_502_609  # ₹75,026.09
    orphan_taxable = 7_562_793  # ₹75,627.93 (~0.8%)
    linked_tax = 900_313  # ₹9,003.13
    orphan_tax = 378_140  # ₹3,781.40 — far from linked

    gstr = [
        _g("g1", "INV-05-3161", linked_taxable, linked_tax, inv_date="2026-05-03")
    ]
    pr = [
        _p("p-linked", linked_inv, linked_taxable, linked_tax, inv_date="2026-05-03"),
        _p("p-orphan", orphan_inv, orphan_taxable, orphan_tax, inv_date="2026-05-19"),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))
    stats = res["stats"]

    assert stats["clean_matched_count"] + stats["review_required_count"] == 1
    assert stats.get("duplicate_entry_count", 0) == 0
    assert stats["wrongful_risk_count"] == 1
    assert {w["id"] for w in res["wrongful_itc_risk"]} == {"p-orphan"}
    assert res["wrongful_itc_risk"][0]["total_tax_paise"] == orphan_tax
