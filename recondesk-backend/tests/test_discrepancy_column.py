"""
test_discrepancy_column.py

Regression coverage for the "Discrepancy" column bug on the Review Required
table: for records whose only difference between GSTR-2B and the Purchase
Register is date or GSTIN (not amount), the reported discrepancy must be ₹0 —
never a fabricated figure equal to one side's raw taxable/invoice value. For a
genuine amount mismatch, the reported discrepancy must equal the actual
computed delta between the two sides.

Two layers are covered:
  1. Engine layer (app.services.reconciliation / app.matching.engine): the
     stored ``taxable_diff_paise`` on state.review_required rows.
  2. API layer (app.routers.reconciliation_api._pair_tax_diff_paise): the pure
     helper that computes the live "Discrepancy" figure served to BOTH the Review
     Required and Matched tables from the DB matcher projection rows (gm/pm).

Run: PYTHONPATH=. pytest tests/test_discrepancy_column.py -v
"""
from datetime import date

from app.matching.engine import run_bidirectional_reconciliation
from app.routers.reconciliation_api import _pair_tax_diff_paise
from app.services.reconciliation_outcomes import _mr_to_decisions
from app.services.reconciliation_record_adapter import pr_db_row_to_matcher_row


def _gstr(id, gstin, inv, taxable_rs, dt="2026-05-01"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": taxable_rs * 100,
        "total_tax_paise": int(taxable_rs * 18),
    }


def _pr(id, gstin, inv, taxable_rs, dt="2026-05-01"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": taxable_rs * 100,
        "total_tax_paise": int(taxable_rs * 18),
    }


def _review_row_for(res, gid=None, pid=None):
    for r in res["review_required"]:
        if gid is not None and str(r.get("gstr_id")) == gid:
            return r
        if pid is not None and str(r.get("pr_id") or r.get("id")) == pid:
            return r
    raise AssertionError(
        f"No review_required row found for gid={gid} pid={pid}: {res['review_required']}"
    )


# ── Engine layer: state.review_required["taxable_diff_paise"] ──────────────


def test_gstin_mismatch_identical_amounts_has_zero_discrepancy():
    """Same invoice/amount, GSTIN corrupted by one character -> real diff is ₹0."""
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV5001", 250000)]
    pr = [_pr("p1", "29BBBBB0000B1Z5", "INV5001", 250000)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    row = _review_row_for(res, gid="g1")
    assert row.get("review_reason") == "GSTIN_MISMATCH" or row.get("reason") == "GSTIN_MISMATCH"
    assert row["taxable_diff_paise"] == 0, (
        "GSTIN-only mismatch with identical amounts must report ₹0 discrepancy, "
        f"got {row['taxable_diff_paise']}"
    )


def test_date_shift_identical_amounts_has_zero_discrepancy():
    """Same GSTIN/invoice/amount, only the date shifted -> real diff is ₹0."""
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV6002", 300000, dt="2026-05-01")]
    pr = [_pr("p1", "27AAAAA0000A1Z5", "INV6002", 300000, dt="2026-05-06")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    row = _review_row_for(res, gid="g1")
    assert row["taxable_diff_paise"] == 0, (
        "Date-shift-only mismatch with identical amounts must report ₹0 "
        f"discrepancy, got {row['taxable_diff_paise']}"
    )


def test_genuine_amount_mismatch_reports_actual_delta():
    """Same GSTIN/invoice, real amount gap -> reported diff equals the true delta, not a raw side value."""
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV7003", 300000)]
    pr = [_pr("p1", "27AAAAA0000A1Z5", "INV7003", 300094)]  # ~9438 paise diff scaled to rupees
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    row = _review_row_for(res, gid="g1")
    expected_diff_paise = abs(300000 - 300094) * 100
    assert row["taxable_diff_paise"] == expected_diff_paise
    # Sanity: must not equal either side's raw taxable value (the old bug's symptom).
    assert row["taxable_diff_paise"] not in (300000 * 100, 300094 * 100)


# ── API layer: _pair_tax_diff_paise pure helper ────────────────────────────


def test_api_helper_zero_for_paired_identical_taxable():
    gm = {"taxable_amount_paise": 25000000, "total_tax_paise": 4500000}
    pm = {"taxable_amount_paise": 25000000, "total_tax_paise": 4500000}
    assert _pair_tax_diff_paise(gm, pm, {}) == 0


def test_api_helper_actual_delta_for_paired_mismatch():
    gm = {"taxable_amount_paise": 30000000, "total_tax_paise": 5400000}
    pm = {"taxable_amount_paise": 30009438, "total_tax_paise": 5401699}
    assert _pair_tax_diff_paise(gm, pm, {}) == abs(30000000 - 30009438)


def test_api_helper_zero_for_one_sided_row_not_full_side_value():
    """One-sided DUPLICATE_AMBIGUITY rows (only gm OR only pm resolves) must not
    fabricate a "discrepancy" equal to the lone side's full taxable value."""
    gm = {"taxable_amount_paise": 29104104, "total_tax_paise": 5238739}
    pm: dict = {}
    assert _pair_tax_diff_paise(gm, pm, {}) == 0

    gm2: dict = {}
    pm2 = {"taxable_amount_paise": 29104104, "total_tax_paise": 5238739}
    assert _pair_tax_diff_paise(gm2, pm2, {}) == 0


def test_api_helper_falls_back_to_stored_value_when_both_sides_missing():
    en_row = {"taxable_diff_paise": 937800}
    assert _pair_tax_diff_paise({}, {}, en_row) == 937800


# ── Matched tab: clean matches must report ₹0 discrepancy ──────────────────


def test_matched_tab_identical_pair_reports_zero_discrepancy():
    """A genuine EXACT match (identical taxable + tax on both sides) must show ₹0
    on the Matched tab — the value the frontend renders straight from
    tax_difference_paise."""
    gm = {"taxable_amount_paise": 8397512, "total_tax_paise": 1511552}
    pm = {"taxable_amount_paise": 8397512, "total_tax_paise": 1511552}
    assert _pair_tax_diff_paise(gm, pm, {}) == 0


def test_matched_tab_pr_missing_total_tax_field_still_zero_discrepancy():
    """Root-cause regression: when the PR record_data carries only component tax
    columns (no top-level total_tax_paise), the DB adapter must still project a
    correct total_tax_paise, and the Matched-tab discrepancy must be ₹0 — not the
    full invoice tax (which previously equalled the row's own Amount)."""
    gstr_matcher = {"taxable_amount_paise": 8390898, "igst_paise": 1510362,
                    "cgst_paise": 0, "sgst_paise": 0, "total_tax_paise": 1510362}
    pr_row = {
        "id": "p-1",
        "record_data": {
            "gstin": "27AAAAA0000A1Z5",
            "invoice_number": "INV5210",
            "taxable_amount_paise": 8390898,
            "igst_paise": 1510362,
            "cgst_paise": 0,
            "sgst_paise": 0,
            # NOTE: intentionally no top-level "total_tax_paise" key.
        },
    }
    pr_matcher = pr_db_row_to_matcher_row(pr_row)

    # Adapter must recover total_tax_paise from components (mirrors GSTR adapter).
    assert pr_matcher["total_tax_paise"] == 1510362

    # Decision layer must classify the pair as MATCHED with zero total-tax delta.
    _w, _y, _n, tvd, _ig, _cg, _sg, ttd, mst = _mr_to_decisions(gstr_matcher, pr_matcher)
    assert mst == "MATCHED"
    assert tvd == 0
    assert ttd == 0

    # And the Discrepancy column figure is ₹0.
    assert _pair_tax_diff_paise(gstr_matcher, pr_matcher, {}) == 0
