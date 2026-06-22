"""Regression test for duplicate-PR data-entry match-loss bug.

Scenario: 20 invoices (DUP00000–DUP00019) each appearing once in 2B and TWICE
in PR (identical GSTIN/invoice/amount), mixed with 460 normal 1:1 matches.

Expected:
  - matched_count == 480 (460 normal + 20 from duplicate pairs)
  - 20 duplicate-flagged PR rows
  - No 2B invoice is double-counted or left unmatched
  - sanity_passed == True
"""

import uuid
from datetime import date

from app.services.reconciliation import run_bidirectional_reconciliation


GSTIN = "27AABCU9603R1ZX"


def _rec(rid, gstin, inv, taxable, *, inv_date="2026-05-10"):
    cg = taxable * 9 // 100
    sg = taxable * 9 // 100
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


def test_duplicate_pr_at_scale():
    """20 duplicate-PR pairs mixed with 460 normal 1:1 matches."""
    gstr_records = []
    pr_records = []

    # 460 normal 1:1 matches
    for i in range(460):
        inv = f"NORM{i:05d}"
        amount = 100_000 + i * 100  # unique amounts to avoid collisions
        gstr_records.append(_rec(f"g-norm-{i}", GSTIN, inv, amount))
        pr_records.append(_rec(f"p-norm-{i}", GSTIN, inv, amount))

    # 20 duplicate-PR pairs: 1 in 2B, 2 in PR (identical)
    for i in range(20):
        inv = f"DUP{i:05d}"
        amount = 500_000 + i * 1000
        gstr_records.append(_rec(f"g-dup-{i}", GSTIN, inv, amount))
        pr_records.append(_rec(f"p-dup-{i}-a", GSTIN, inv, amount))  # first PR
        pr_records.append(_rec(f"p-dup-{i}-b", GSTIN, inv, amount))  # duplicate PR

    res = run_bidirectional_reconciliation(
        gstr_records,
        pr_records,
        gstr_period=date(2026, 5, 1),
    )

    stats = res["stats"]

    # All 480 2B invoices (460 normal + 20 duplicate-pair) must be matched
    assert stats["matched_count"] == 480, (
        f"Expected 480 matched, got {stats['matched_count']}"
    )

    # 20 PR rows should be flagged as duplicate data entries
    assert stats["duplicate_pr_count"] == 20, (
        f"Expected 20 duplicate PR rows, got {stats['duplicate_pr_count']}"
    )

    # No 2B invoice should be left as missed ITC
    assert stats["missed_itc_count"] == 0, (
        f"Expected 0 missed ITC, got {stats['missed_itc_count']}"
    )

    # No wrongful ITC risk
    assert stats["wrongful_risk_count"] == 0, (
        f"Expected 0 wrongful risk, got {stats['wrongful_risk_count']}"
    )

    # No duplicate conflicts (these are clean duplicate data entries, not ambiguous)
    assert stats["duplicate_conflict_count"] == 0, (
        f"Expected 0 duplicate conflicts, got {stats['duplicate_conflict_count']}"
    )

    # Sanity check must pass
    assert stats["sanity_passed"] is True, (
        f"Sanity check failed: {stats}"
    )

    # Verify no 2B invoice is double-counted
    matched_gstr_ids = [m["gstr_id"] for m in res["matched"]]
    assert len(matched_gstr_ids) == len(set(matched_gstr_ids)), (
        "Some 2B invoices were matched more than once"
    )

    # Verify no PR is double-counted in matched
    matched_pr_ids = [m["pr_id"] for m in res["matched"]]
    assert len(matched_pr_ids) == len(set(matched_pr_ids)), (
        "Some PR rows were matched more than once"
    )


def test_duplicate_pr_single_pair():
    """Single duplicate-PR pair: 1 in 2B, 2 in PR."""
    gstr_records = [_rec("g1", GSTIN, "DUP00001", 500_000)]
    pr_records = [
        _rec("p1", GSTIN, "DUP00001", 500_000),
        _rec("p2", GSTIN, "DUP00001", 500_000),
    ]

    res = run_bidirectional_reconciliation(
        gstr_records,
        pr_records,
        gstr_period=date(2026, 5, 1),
    )

    stats = res["stats"]

    assert stats["matched_count"] == 1
    assert stats["duplicate_pr_count"] == 1
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["sanity_passed"] is True

    # The 2B invoice should be consumed/matched exactly once
    assert len(res["matched"]) == 1
    assert res["matched"][0]["gstr_id"] == "g1"


def test_duplicate_pr_triple_booking():
    """Triple booking: 1 in 2B, 3 in PR (same invoice entered thrice)."""
    gstr_records = [_rec("g1", GSTIN, "TRIP001", 750_000)]
    pr_records = [
        _rec("p1", GSTIN, "TRIP001", 750_000),
        _rec("p2", GSTIN, "TRIP001", 750_000),
        _rec("p3", GSTIN, "TRIP001", 750_000),
    ]

    res = run_bidirectional_reconciliation(
        gstr_records,
        pr_records,
        gstr_period=date(2026, 5, 1),
    )

    stats = res["stats"]

    assert stats["matched_count"] == 1
    assert stats["duplicate_pr_count"] == 2  # two extra PR rows
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["sanity_passed"] is True
