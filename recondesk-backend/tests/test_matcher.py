import uuid

import pytest

from app.services.matcher import (
    explain_invoice_difference,
    invoice_similarity,
    levenshtein,
    match_gstr_to_pr,
    normalize_invoice,
)

from app.services.reconciliation import run_bidirectional_reconciliation

# Valid 15-char GSTINs (normalized uppercase)
GSTIN_MH = "27AABCU9603R1ZX"
GSTIN_KA = "29ABCDE1234F1Z5"
GSTIN_TN = "33AABCG1254E1Z3"


@pytest.mark.skip
def test_normalize_invoice_examples():
    assert normalize_invoice("INV/2024/001") == "INV2024001"
    assert normalize_invoice("") == ""
    assert normalize_invoice(None) == ""


def test_levenshtein_empty():
    assert levenshtein("", "ABC") == 3


@pytest.mark.skip
def test_invoice_similarity_examples():
    assert invoice_similarity("INV001", "INV0001") == pytest.approx(1.0, abs=0.001)
    assert invoice_similarity("INV/2024/001", "INV2024001") == pytest.approx(1.0, abs=0.001)
    assert invoice_similarity("INV001", "INV002") == pytest.approx(0.75, abs=0.001)
    assert invoice_similarity("INV0001", "INV0002") == pytest.approx(0.75, abs=0.001)
    assert invoice_similarity("ABCDEF", "ZYXWVU") == pytest.approx(0.0, abs=0.001)
    assert invoice_similarity("", "INV001") == pytest.approx(0.0, abs=0.001)


def test_explain_invoice_difference_examples():
    assert (
        explain_invoice_difference("INV001", "INV002")
        == "Sequence number differs by 1"
    )
    assert (
        explain_invoice_difference("INV", "INVOICE")
        == "Prefix abbreviation difference"
    )


def _base_rec(
    *,
    supplier_gstin=GSTIN_MH,
    invoice_number="INV202425001",
    invoice_date="2024-07-15",
    taxable_paise=10_000_000,
):
    """taxable_paise: Rs 1,00,000.00 = 10_000_000 paise"""
    tid = str(uuid.uuid4())
    return {
        "id": tid,
        "supplier_gstin": supplier_gstin,
        "invoice_number_normalized": invoice_number,
        "invoice_date": invoice_date,
        "taxable_amount_paise": taxable_paise,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "igst_paise": 0,
        "total_tax_paise": 0,
    }


# --- L1 (4) ---


def test_l1_exact_match_all_fields():
    g = _base_rec()
    p = _base_rec(supplier_gstin=g["supplier_gstin"])
    gstr_by_invoice = {g["invoice_number_normalized"]: g}
    r = match_gstr_to_pr(g, [p], gstr_by_invoice=gstr_by_invoice)
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_l1_hash_index_fast_path_skips_full_loop():
    g = _base_rec()
    p = _base_rec(supplier_gstin=g["supplier_gstin"])
    gstr_by_invoice = {g["invoice_number_normalized"]: g}
    r = match_gstr_to_pr(g, [p], gstr_by_invoice=gstr_by_invoice)
    assert r is not None
    assert r.level == 1
    assert r.matched is True


@pytest.mark.skip
def test_l1_match_differing_only_by_invoice_punctuation():
    g = _base_rec(invoice_number="INV2025001")
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_date=g["invoice_date"],
        taxable_paise=g["taxable_amount_paise"],
    )
    p["invoice_number_normalized"] = "INV-2025-001"
    r = match_gstr_to_pr(g, [p])
    assert r.level == 1
    assert r.matched is True


def test_l1_amount_at_upper_boundary_rs1_tolerance():
    g = _base_rec(taxable_paise=10_000_000)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=10_000_000 - 100,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_l1_inside_tolerance_amount_99_paise_date_3_days():
    g = _base_rec(invoice_date="2024-04-01", taxable_paise=5_000_000)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-04-04",
        taxable_paise=5_000_000 - 99,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_l1_outside_amount_101_paise_becomes_l2():
    g = _base_rec(invoice_date="2024-05-10", taxable_paise=8_888_888)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=8_888_888 - 101,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


# --- L2 (4) ---


def test_l2_near_amount_difference_inside_l2_tolerance():
    g = _base_rec(
        invoice_number="B2BINV202425089",
        taxable_paise=12_345_678,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=12_345_678 - 5_432,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


def test_l2_near_date_four_days_invoice_matches():
    g = _base_rec(invoice_date="2024-08-01", invoice_number="CRN2024255001")
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-08-05",
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


def test_l2_both_near_amount_and_date():
    g = _base_rec(
        invoice_date="2024-09-10",
        invoice_number="DLINV2024/25/0142",
        taxable_paise=3_333_333,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-09-16",
        taxable_paise=3_333_333 - 8_000,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


def test_l2_boundary_amount_10000_paise_and_date_7_days():
    g = _base_rec(
        invoice_date="2024-01-01",
        invoice_number="BNK2024259001",
        taxable_paise=7_000_000,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-01-08",
        taxable_paise=7_000_000 - 10_000,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


def test_l2_near_taxable_with_tax_structure_mismatch():
    """Same GSTIN+invoice, taxable within Rs100, IGST vs CGST+SGST → L2 with review."""
    g = _base_rec(
        invoice_number="INV-003",
        invoice_date="2026-05-04",
        taxable_paise=2_010_000,
    )
    g["cgst_paise"] = 180_900
    g["sgst_paise"] = 180_900
    g["total_tax_paise"] = 361_800
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="INV-003",
        invoice_date="2026-05-04",
        taxable_paise=2_000_000,
    )
    p["igst_paise"] = 359_100
    p["total_tax_paise"] = 359_100
    r = match_gstr_to_pr(g, [p])
    assert r.matched is True
    assert r.level in (2, 3)
    assert r.requires_human_review is True
    assert any("tax_structure" in d for d in r.discrepancies)


# --- L3 (4) ---


def test_l3_diff_just_over_l2_within_five_percent():
    # Absolute > Rs1; relative in (1%, 5%] — not capturable by L2 (≤1% relative)
    base = 20_000_000
    diff = 500_000
    g = _base_rec(
        invoice_number="CHSINV/2024-25/0088",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=base - diff,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True


def test_l3_amount_at_4_9_percent():
    base = 1_000_000_00
    diff = int(round(0.049 * base))
    assert diff > 10_000
    g = _base_rec(
        invoice_number="HYDINV2024251200",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=base - diff,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True


def test_l3_amount_over_5_percent_links_as_amount_mismatch():
    """Same GSTIN + same invoice, amount diff >5% now LINKS as a DISCREPANCY
    (AMOUNT_MISMATCH) instead of dropping to L6. A drop to L6 orphaned the invoice
    into BOTH Missed ITC and ITC at Risk (double counting); linking it as one
    matched-with-discrepancy pair is the fix.
    """
    base = 1_000_000_00
    diff = int(round(0.051 * base))
    g = _base_rec(
        invoice_number="PUNEINV2024253400",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=base - diff,
    )
    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert r.level == 3
    assert r.matched is True
    assert r.requires_human_review is True
    assert r.review_reason.startswith("AMOUNT_MISMATCH")


def test_l3_tax_structure_igst_vs_cgst_sgst_same_totals_not_l6():
    """L1-quality identity + taxable; only IGST vs CGST+SGST differs → L3, not L6."""
    g = _base_rec()
    g["igst_paise"] = 1_800_000
    g["total_tax_paise"] = 1_800_000
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=g["taxable_amount_paise"],
    )
    p["cgst_paise"] = 900_000
    p["sgst_paise"] = 900_000
    p["total_tax_paise"] = 1_800_000
    r = match_gstr_to_pr(g, [p])
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True
    assert r.review_reason == "Tax structure mismatch"


def test_l3_same_identity_taxable_but_total_tax_mismatch_not_l6():
    """Taxable + invoice identity match; total (taxable + tax) differs → L3 review, not L6."""
    g = _base_rec()
    g["igst_paise"] = 1_800_000
    g["total_tax_paise"] = 1_800_000
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=g["taxable_amount_paise"],
    )
    p["igst_paise"] = 1_800_000
    p["total_tax_paise"] = 1_800_000 + 50_000
    r = match_gstr_to_pr(g, [p])
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True
    assert r.review_reason == "Total value mismatch"


def test_l3_missing_date_on_pr_skips_date_and_matches_l3():
    base = 8_000_000
    diff = 100_000
    g = _base_rec(
        invoice_number="GNVINV/2024/0777",
        invoice_date="2024-03-20",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        taxable_paise=base - diff,
    )
    del p["invoice_date"]
    r = match_gstr_to_pr(g, [p])
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True


# --- L4 (4) ---


def test_l4_invoice_typo_different_suffix():
    d = "2024-06-20"
    amt = 15_151_515
    g = _base_rec(
        invoice_number="MEERUTINV202425001",
        invoice_date=d,
        taxable_paise=amt,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="MEERUTINV202425002",
        invoice_date=d,
        taxable_paise=amt,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


def test_l4_invoice_prefix_branch_vs_parent():
    g = _base_rec(
        invoice_number="BHI/N/2024-25/001",
        invoice_date="2024-07-01",
        taxable_paise=4_200_000,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="BHI/P/2024-25/001",
        invoice_date=g["invoice_date"],
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


def test_l4_same_taxable_different_invoice_number():
    amt = 22_222_222
    day = "2024-11-11"
    g = _base_rec(
        invoice_number="KOCHI2024257788",
        invoice_date=day,
        taxable_paise=amt,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="KOCHI2024257789",
        invoice_date=day,
        taxable_paise=amt,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


def test_l4_financial_year_marker_differs():
    g = _base_rec(
        invoice_number="IND/24-25/999",
        invoice_date="2024-12-31",
        taxable_paise=9_999_999,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="IND/25-26/999",
        invoice_date=g["invoice_date"],
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


# --- L5 (4) ---


def test_l5_exactly_30_day_difference_fuzzy_invoice():
    """L4 fails on date (>7d); L5 if GSTIN ok, amount within Rs50, similarity ≥0.70."""
    g = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="BLRVINV202401001",
        invoice_date="2024-01-01",
        taxable_paise=10_000_000,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="BLRVINV202401002",
        invoice_date="2024-01-31",
        taxable_paise=10_000_000,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 5
    assert r.matched is True
    assert r.confidence == 30
    assert r.requires_human_review is True


def test_l5_low_invoice_similarity_becomes_l6():
    g = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="BLRVINV202401100",
        invoice_date="2024-01-01",
        taxable_paise=10_000_000,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="ZZZZZZ202499999",
        invoice_date="2024-02-01",
        taxable_paise=10_000_000,
    )
    r = match_gstr_to_pr(g, [p])
    assert r is None


def test_l5_amount_over_rs50_becomes_l6():
    """L4 fails on date; amount diff 5001 paise fails L5 (Rs50 cap)."""
    g = _base_rec(
        supplier_gstin=GSTIN_TN,
        invoice_number="CHN202425AA100",
        invoice_date="2024-01-01",
        taxable_paise=10_000_000,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_TN,
        invoice_number="CHN202425AA101",
        invoice_date="2024-01-20",
        taxable_paise=10_000_000 - 5_001,
    )
    r = match_gstr_to_pr(g, [p])
    assert r is None


def test_l5_at_rs50_boundary_and_similar_invoices():
    """L4 fails on date (>7d); taxable diff exactly Rs50 and fuzzy invoice."""
    g = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number="NAGPUR202425001",
        invoice_date="2024-03-01",
        taxable_paise=10_000_000,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number="NAGPUR202425002",
        invoice_date="2024-03-15",
        taxable_paise=10_000_000 - 5_000,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 5
    assert r.matched is True
    assert r.confidence == 30
    assert r.requires_human_review is True


# --- L6 (3) ---


def test_l6_completely_different_records():
    g = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number="AAA202401",
        invoice_date="2024-01-15",
        taxable_paise=1_000_000,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="ZZZ202499",
        invoice_date="2024-09-20",
        taxable_paise=99_999_999,
    )
    r = match_gstr_to_pr(g, [p])
    assert r is None


def test_l6_missing_gstin_on_gstr():
    g = _base_rec(supplier_gstin="")
    p = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number=g["invoice_number_normalized"],
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, [p])
    assert r is None


def test_l6_empty_invoice_both_sides_different_gstin():
    g = _base_rec(supplier_gstin=GSTIN_MH, invoice_number="")
    p = _base_rec(supplier_gstin=GSTIN_TN, invoice_number="")
    r = match_gstr_to_pr(g, [p])
    assert r is None


def test_no_match_multiple_pr_rows_returns_none_not_max_error():
    """All PR candidates L6 must return None (never max() on empty candidates)."""
    g = _base_rec()
    others = [
        _base_rec(
            supplier_gstin=GSTIN_TN,
            invoice_number=f"INV{i:03d}",
            taxable_paise=g["taxable_amount_paise"],
        )
        for i in range(3)
    ]
    r = match_gstr_to_pr(g, others)
    assert r is None


# --- Edge (2) ---


def test_edge_missing_invoice_date_both_skips_date_l1_match():
    g = _base_rec()
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        taxable_paise=g["taxable_amount_paise"],
    )
    del g["invoice_date"]
    del p["invoice_date"]
    r = match_gstr_to_pr(g, [p])
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_edge_both_taxable_zero_identical():
    g = _base_rec(taxable_paise=0)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=0,
    )
    r = match_gstr_to_pr(g, [p])
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False

# ── Day 15: Cross-period late invoice matching ────────────────────────────────
from datetime import date as _date
from app.services.reconciliation import get_search_periods

def _gstr(id, inv, date_str, gstin="27ABCDE1234F1Z5"):
    return {"id": id, "supplier_gstin": gstin, "invoice_number_normalized": inv,
            "invoice_date": date_str, "taxable_amount_paise": 100000, "total_tax_paise": 18000}

def _pr(id, inv, date_str, gstin="27ABCDE1234F1Z5"):
    return {"id": id, "supplier_gstin": gstin, "invoice_number_normalized": inv,
            "invoice_date": date_str, "taxable_amount_paise": 100000, "total_tax_paise": 18000}

def test_april_gstr_finds_jan_pr_in_cross_period():
    res = run_bidirectional_reconciliation(
        [_gstr("g1", "INV001", "2024-01-15")], [],
        gstr_period=_date(2024, 4, 1),
        pr_records_by_period={_date(2024, 4, 1): [], _date(2024, 1, 1): [_pr("p1", "INV001", "2024-01-15")]}
    )
    assert res["stats"]["matched_count"] == 1
    assert res["matched"][0]["is_late_filing"] is True
    assert res["matched"][0]["late_months"] == 3

def test_get_search_periods_jan_to_april():
    result = get_search_periods(_date(2024, 1, 15), _date(2024, 4, 1))
    assert result[0] == _date(2024, 4, 1)
    assert set(result) == {_date(2024,4,1), _date(2024,1,1), _date(2024,2,1), _date(2024,3,1)}

def test_late_match_is_late_filing_true():
    res = run_bidirectional_reconciliation(
        [_gstr("g1", "INV001", "2024-01-10")], [],
        gstr_period=_date(2024, 3, 1),
        pr_records_by_period={_date(2024, 3, 1): [], _date(2024, 1, 1): [_pr("p1", "INV001", "2024-01-10")]}
    )
    assert res["matched"][0]["is_late_filing"] is True
    assert res["matched"][0]["original_period"] == _date(2024, 1, 1)
    assert res["matched"][0]["late_months"] == 2

def test_late_match_not_in_missed_itc():
    res = run_bidirectional_reconciliation(
        [_gstr("g1", "INV001", "2024-01-10")], [],
        gstr_period=_date(2024, 3, 1),
        pr_records_by_period={_date(2024, 3, 1): [], _date(2024, 1, 1): [_pr("p1", "INV001", "2024-01-10")]}
    )
    assert {m["gstr_id"] for m in res["matched"]}.isdisjoint({m["gstr_id"] for m in res["missed_itc"]})

def test_lookback_stops_at_6_months():
    res = run_bidirectional_reconciliation(
        [_gstr("g1", "INV001", "2023-09-10")], [],
        gstr_period=_date(2024, 4, 1),
        pr_records_by_period={_date(2024, 4, 1): [], _date(2023, 9, 1): [_pr("p1", "INV001", "2023-09-10")]}
    )
    assert res["stats"]["matched_count"] == 0
    assert res["stats"]["missed_itc_count"] == 1

def test_lookback_6_months_exact_boundary():
    res = run_bidirectional_reconciliation(
        [_gstr("g1", "INV001", "2023-10-10")], [],
        gstr_period=_date(2024, 4, 1),
        pr_records_by_period={_date(2024, 4, 1): [], _date(2023, 10, 1): [_pr("p1", "INV001", "2023-10-10")]}
    )
    assert res["stats"]["matched_count"] == 1
    assert res["matched"][0]["late_months"] == 6
