"""Issue 3: match_level must distinguish raw-exact L1 from normalized L2.

Format variants (slashes vs hyphens, leading zeros, case) with zero financial
diff stay on the Matched tab but must carry match_level=2 so the Non-exact
chip / FUZZY filter can surface them. L1 is reserved for identical raw invoice
strings. The Matched-tab UI label must read match_level, not financial
match_status==MATCHED.
"""
from __future__ import annotations

from datetime import date

from app.matching.engine import run_bidirectional_reconciliation
from app.routers.reconciliation_api import _matched_ui_match_level
from app.services.matcher import match_gstr_to_pr, normalize_invoice


GSTIN = "27AABCU1234R1ZX"
PERIOD = date(2024, 3, 1)


def _g(rid, inv, *, taxable=100_000, tax=18_000):
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
    }


def _p(rid, inv, *, taxable=100_000, tax=18_000):
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
    }


def _exact_count(matched_rows):
    return sum(
        1
        for m in matched_rows
        if isinstance(m, dict)
        and (
            m.get("match_level") == 1
            or (m.get("match_level") is None and m.get("confidence_score") == 100)
        )
    )


def test_format_variant_zero_diff_is_matched_non_exact():
    """INV/001 vs INV-001 → Matched at L2, not L1; Non-exact chip = 1."""
    gstr = [_g("g1", "INV/001")]
    pr = [_p("p1", "INV-001")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["clean_matched_count"] == 1
    assert res["stats"]["review_required_count"] == 0
    assert res["matched"][0]["match_level"] == 2
    assert _exact_count(res["matched"]) == 0
    non_exact = res["stats"]["clean_matched_count"] - _exact_count(res["matched"])
    assert non_exact == 1


def test_leading_zeros_normalized_is_matched_non_exact():
    gstr = [_g("g1", "INV00001")]
    pr = [_p("p1", "INV1")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["clean_matched_count"] == 1
    assert res["matched"][0]["match_level"] == 2
    assert _exact_count(res["matched"]) == 0


def test_case_difference_is_matched_non_exact():
    gstr = [_g("g1", "inv-001")]
    pr = [_p("p1", "INV-001")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["clean_matched_count"] == 1
    assert res["matched"][0]["match_level"] == 2


def test_raw_identical_is_exact_l1():
    gstr = [_g("g1", "INV-001")]
    pr = [_p("p1", "INV-001")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["matched"][0]["match_level"] == 1
    assert _exact_count(res["matched"]) == 1
    r = match_gstr_to_pr(gstr[0], pr)
    assert r is not None and r.level == 1 and r.requires_human_review is False


def test_matched_ui_level_respects_match_level_not_status():
    """Financial match_status MATCHED must not force EXACT when level is 2."""
    assert (
        _matched_ui_match_level(
            {"match_level": 2, "confidence_score": 95},
            "MATCHED",
            for_matched_tab=True,
        )
        == "FUZZY"
    )
    assert (
        _matched_ui_match_level(
            {"match_level": 1, "confidence_score": 100},
            "MATCHED",
            for_matched_tab=True,
        )
        == "EXACT"
    )
