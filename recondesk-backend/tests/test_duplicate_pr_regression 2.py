"""Regression test for duplicate-PR data-entry classification.

Scenario: 20 invoices (DUP00000–DUP00019) each appearing once in 2B and TWICE
in PR (identical GSTIN/invoice/amount), mixed with 460 normal 1:1 matches.

Expected:
  - matched_count == 480 (460 normal + 20 canonical duplicate pairs)
  - duplicate_entry_count == 20 (extra PR rows only)
  - review_required_count == 0 for these duplicates
  - wrongful_risk_count == 0
  - sanity_passed == True
"""

from datetime import date

from app.matching.engine import run_bidirectional_reconciliation


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

    for i in range(460):
        inv = f"NORM{i:05d}"
        amount = 100_000 + i * 100
        gstr_records.append(_rec(f"g-norm-{i}", GSTIN, inv, amount))
        pr_records.append(_rec(f"p-norm-{i}", GSTIN, inv, amount))

    for i in range(20):
        inv = f"DUP{i:05d}"
        amount = 500_000 + i * 1000
        gstr_records.append(_rec(f"g-dup-{i}", GSTIN, inv, amount))
        pr_records.append(_rec(f"p-dup-{i}-a", GSTIN, inv, amount))
        pr_records.append(_rec(f"p-dup-{i}-b", GSTIN, inv, amount))

    res = run_bidirectional_reconciliation(
        gstr_records,
        pr_records,
        gstr_period=date(2026, 5, 1),
    )

    stats = res["stats"]

    assert stats["matched_count"] == 480, (
        f"Expected 480 matched, got {stats['matched_count']}"
    )
    assert stats["duplicate_entry_count"] == 20, (
        f"Expected 20 duplicate entries, got {stats['duplicate_entry_count']}"
    )
    assert stats["review_required_count"] == 0, (
        f"Expected 0 review for true duplicates, got {stats['review_required_count']}"
    )
    assert stats["duplicate_pr_count"] == 20
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["duplicate_conflict_count"] == 0
    assert stats["sanity_passed"] is True

    matched_gstr_ids = [m["gstr_id"] for m in res["matched"]]
    assert len(matched_gstr_ids) == len(set(matched_gstr_ids))
    matched_pr_ids = [m["pr_id"] for m in res["matched"]]
    assert len(matched_pr_ids) == len(set(matched_pr_ids))

    for d in res["duplicate_entries"]:
        assert d["reason"] == "DUPLICATE_ENTRY"
        assert d["matched_pr_id"]
        assert d["matched_pr_id"] in matched_pr_ids


def test_duplicate_pr_single_pair():
    """Single duplicate-PR pair: 1 in 2B, 2 in PR → 1 match + 1 Duplicate Entry."""
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
    assert stats["duplicate_entry_count"] == 1
    assert stats["review_required_count"] == 0
    assert stats["duplicate_pr_count"] == 1
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["sanity_passed"] is True

    assert res["matched"][0]["pr_id"] == "p1"
    assert res["duplicate_entries"][0]["id"] == "p2"
    assert res["duplicate_entries"][0]["matched_pr_id"] == "p1"
    assert res["duplicate_entries"][0]["reason"] == "DUPLICATE_ENTRY"


def test_duplicate_pr_triple_booking():
    """Triple booking: 1 in 2B, 3 in PR → 1 match + 2 Duplicate Entries."""
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
    assert stats["duplicate_entry_count"] == 2
    assert stats["review_required_count"] == 0
    assert stats["duplicate_pr_count"] == 2
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["sanity_passed"] is True
    assert res["matched"][0]["pr_id"] == "p1"
    assert {d["matched_pr_id"] for d in res["duplicate_entries"]} == {"p1"}
