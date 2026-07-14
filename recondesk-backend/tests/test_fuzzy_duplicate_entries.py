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
    """INV455325 linked; NIV455325 same amounts → Duplicate Entry."""
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
    assert stats["wrongful_risk_count"] == 0
    assert stats["duplicate_entry_count"] == 1
    assert stats["clean_matched_count"] + stats["review_required_count"] == 1
    dup = res["duplicate_entries"][0]
    assert dup["id"] == "p-extra"
    assert dup["matched_pr_id"] == "p-canon"
    assert dup["reason"] == "DUPLICATE_ENTRY"


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
    """SL912825 extra of linked SL192825 (sim=0.75) with identical amounts."""
    a, b = "SL192825", "SL912825"
    assert abs(invoice_similarity(a, b) - 0.75) < 1e-9

    gstr = [_g("g1", "SL-1928/25", 41_907_614, 2_095_381, inv_date="2025-05-13")]
    pr = [
        _p("p-canon", a, 41_907_614, 2_095_381, inv_date="2025-05-13"),
        _p("p-extra", b, 41_907_614, 2_095_381, inv_date="2025-05-13"),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["wrongful_risk_count"] == 0
    assert stats["duplicate_entry_count"] == 1
    assert res["duplicate_entries"][0]["id"] == "p-extra"
    assert res["duplicate_entries"][0]["matched_pr_id"] == "p-canon"


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
