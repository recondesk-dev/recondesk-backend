import pytest
from datetime import date
from app.services.reconciliation import run_bidirectional_reconciliation

def _gstr(id, gstin, inv, tax=10000, dt="2026-05-01"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": tax * 100,
        "total_tax_paise": tax * 18,
    }

def _pr(id, gstin, inv, tax=10000, dt="2026-05-01"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": tax * 100,
        "total_tax_paise": tax * 18,
    }

def test_a_clean_match():
    # Test A: GSTR: supplier A, INV001, tax ₹100. PR: supplier A, INV001, tax ₹100
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV001", 100)]
    pr = [_pr("p1", "27AAAAA0000A1Z5", "INV001", 100)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))
    stats = res["stats"]
    assert stats["clean_matched_count"] == 1
    assert stats["duplicate_conflict_count"] == 0

def test_b_gstin_mismatch():
    # Test B: GSTR: supplier A, INV001, tax ₹100. PR: supplier B, INV001, tax ₹100
    # Expected: not clean match; routed to gstin_mismatch regardless of edit distance
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV001", 100)]
    pr = [_pr("p1", "29BBBBB0000B1Z5", "INV001", 100)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))
    stats = res["stats"]
    assert stats["clean_matched_count"] == 0
    assert stats["duplicate_conflict_count"] == 0
    assert stats["gstin_mismatch_count"] == 1
    assert stats["genuine_gstr_only_count"] == 0
    assert stats["genuine_pr_only_count"] == 0

def test_c_1_gstr_2_pr():
    # Test C: GSTR has one supplier A / INV001. PR has two supplier A / INV001 rows
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV001", 100)]
    pr = [
        _pr("p1", "27AAAAA0000A1Z5", "INV001", 100),
        _pr("p2", "27AAAAA0000A1Z5", "INV001", 100),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))
    stats = res["stats"]
    # Correct behavior: first PR matches normally, second is a duplicate data-entry flag
    assert stats["clean_matched_count"] == 1
    assert stats["duplicate_pr_count"] == 1
    assert stats["duplicate_conflict_count"] == 0

def test_d_2_gstr_1_pr():
    # Test D: GSTR has two supplier A / INV001 rows. PR has one supplier A / INV001 row
    gstr = [
        _gstr("g1", "27AAAAA0000A1Z5", "INV001", 100),
        _gstr("g2", "27AAAAA0000A1Z5", "INV001", 100),
    ]
    pr = [_pr("p1", "27AAAAA0000A1Z5", "INV001", 100)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))
    stats = res["stats"]
    assert stats["clean_matched_count"] == 0
    assert stats["duplicate_conflict_count"] == 2
    assert len(res["review_required"]) == 3

def test_e_2_gstr_2_pr_unambiguous():
    # Test E: GSTR has two supplier A / INV001 rows. PR has two supplier A / INV001 rows
    # Expected: deterministic pairing only if amount/date make it unambiguous; otherwise review required
    gstr = [
        _gstr("g1", "27AAAAA0000A1Z5", "INV001", 100, "2026-05-01"),
        _gstr("g2", "27AAAAA0000A1Z5", "INV001", 200, "2026-05-02"),
    ]
    pr = [
        _pr("p1", "27AAAAA0000A1Z5", "INV001", 100, "2026-05-01"),
        _pr("p2", "27AAAAA0000A1Z5", "INV001", 200, "2026-05-02"),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))
    stats = res["stats"]
    # They match perfectly on amount/date, so it should be clean matches.
    assert stats["clean_matched_count"] == 2
    assert stats["duplicate_conflict_count"] == 0
    
def test_e_2_gstr_2_pr_ambiguous():
    gstr = [
        _gstr("g1", "27AAAAA0000A1Z5", "INV001", 100, "2026-05-01"),
        _gstr("g2", "27AAAAA0000A1Z5", "INV001", 100, "2026-05-01"),
    ]
    pr = [
        _pr("p1", "27AAAAA0000A1Z5", "INV001", 100, "2026-05-01"),
        _pr("p2", "27AAAAA0000A1Z5", "INV001", 100, "2026-05-01"),
    ]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))
    stats = res["stats"]
    # Same amount/date, cannot deterministically map them
    assert stats["clean_matched_count"] == 0
    assert stats["duplicate_conflict_count"] == 2
    assert len(res["review_required"]) == 4
