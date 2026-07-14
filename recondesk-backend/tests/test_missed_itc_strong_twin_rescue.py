"""Missed ITC false-positive rescue: strong taxable twins with mangled invoices.

Extreme stress packs mangle invoice digits while keeping GSTIN + taxable + date
aligned (e.g. INV-6501/25 ↔ INV605125, sim≈0.78). Those must land in Review
Required, not Missed ITC. Unrelated invoices that only share GSTIN + amount
must still fall through to Missed ITC.
"""
from __future__ import annotations

from datetime import date

from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import invoice_similarity, normalize_invoice

GSTIN = "06DERHG8501W0ZV"
PERIOD = date(2026, 3, 1)


def _row(side: str, i: str, inv: str, taxable: int, tax: int, inv_date: str = "2025-09-15", **extra):
    return {
        "id": f"{side}{i}",
        "supplier_gstin": GSTIN,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2,
        "sgst_paise": tax - tax // 2,
        "igst_paise": 0,
        **extra,
    }


def test_digit_transposition_twin_goes_to_review_not_missed_itc():
    """INV650125 ↔ INV605125 (sim≈0.78) with exact taxable must not be Missed ITC."""
    g_inv, p_inv = "INV-6501/25", "INV605125"
    assert 0.75 <= invoice_similarity(normalize_invoice(g_inv), normalize_invoice(p_inv)) < 0.85

    gstr = [_row("g", "1", g_inv, 37_668_644, 6_780_356)]
    pr = [_row("p", "1", p_inv, 37_668_644, 6_780_356)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["matched_count"] == 0
    assert res["stats"]["review_required_count"] == 1
    assert res["stats"]["wrongful_risk_count"] == 0


def test_single_char_ocr_twin_at_exactly_080_goes_to_review():
    """BILL952425 ↔ BLIL952425 has sim==0.80; old ``> 0.80`` gate dropped these."""
    g_inv, p_inv = "BILL-9524/25", "BLIL952425"
    sim = invoice_similarity(normalize_invoice(g_inv), normalize_invoice(p_inv))
    assert abs(sim - 0.80) < 1e-9

    gstr = [_row("g", "1", g_inv, 395_736, 71_233)]
    pr = [_row("p", "1", p_inv, 395_736, 71_233)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["review_required_count"] == 1


def test_exact_taxable_twin_with_divergent_total_tax_goes_to_review():
    """Tax-head / total-tax drift >5% but exact taxable + fuzzy invoice → Review."""
    gstr = [_row("g", "1", "GST-1850/25", 21_011_120, 3_782_002)]
    # Same taxable, total_tax ~20% different (outside TYPO's 5% total_tax band)
    pr = [_row("p", "1", "GST815025", 21_011_120, 4_538_402)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["review_required_count"] == 1


def test_invalid_gstin_fuzzy_invoice_twin_goes_to_review():
    """gstin_format_invalid + sim≥0.75 + amount/date must not stay Missed ITC."""
    gstr = [
        _row(
            "g",
            "1",
            "INV-6501/25",
            37_668_644,
            6_780_356,
            gstin_format_invalid=True,
        )
    ]
    pr = [_row("p", "1", "INV605125", 37_668_644, 6_780_356)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["review_required_count"] == 1


def test_unrelated_invoice_same_gstin_and_taxable_stays_missed_itc():
    """Amount-only pairing must not rescue unrelated invoice strings."""
    gstr = [_row("g", "1", "ALPHA-9999", 300_000, 54_000)]
    pr = [_row("p", "1", "ZYXWV-1234", 300_000, 54_000)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    assert res["stats"]["missed_itc_count"] == 1
    assert res["stats"]["review_required_count"] == 0
    assert res["stats"]["wrongful_risk_count"] == 1


def test_low_similarity_digit_noise_stays_missed_itc():
    """sim well below 0.75 must not be rescued even with exact taxable."""
    g_inv, p_inv = "INV111111", "INV999999"
    assert invoice_similarity(normalize_invoice(g_inv), normalize_invoice(p_inv)) < 0.75

    gstr = [_row("g", "1", g_inv, 500_000, 90_000)]
    pr = [_row("p", "1", p_inv, 500_000, 90_000)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    assert res["stats"]["missed_itc_count"] == 1
    assert res["stats"]["review_required_count"] == 0
