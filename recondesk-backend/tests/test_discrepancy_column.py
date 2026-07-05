"""
test_discrepancy_column.py

Regression coverage for the "Discrepancy" column on both the Review Required
and Matched tables. Three distinct bugs have hit this column and are all
covered here so a fix for one direction can never silently reintroduce another:

  Bug A/B (fabricated large discrepancy): comparing a tax-only figure against a
  full invoice value, or diffing a one-sided row against an implicit zero.
  Symptom: non-financial mismatches (date shift, GSTIN typo) or one-sided rows
  showed a huge fake "discrepancy" equal to a raw side value.

  Matched-tab total_tax_paise=0 projection: the PR DB adapter didn't fall back
  to summing tax components, so a clean match could show a fake discrepancy
  equal to its own Amount.

  False-negative regression: the fix for the above two bugs diffed only
  taxable_amount_paise (falling back to total_tax_paise ONLY when both taxable
  values were exactly zero). A genuine, deliberate mismatch whose amount gap
  lives in the tax component (not the taxable value) then silently reported
  ₹0 — hiding a real discrepancy from the CA.

The correct, single definition used everywhere: diff the TOTAL invoice value
(taxable + total tax) on each side when both sides are genuinely present;
₹0 when only one side (or neither) resolves.

Layers covered:
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


def _gstr(id, gstin, inv, taxable_rs, tax_rs=None, dt="2026-05-01"):
    tax_rs = int(taxable_rs * 0.18) if tax_rs is None else tax_rs
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": taxable_rs * 100,
        "total_tax_paise": tax_rs * 100,
    }


def _pr(id, gstin, inv, taxable_rs, tax_rs=None, dt="2026-05-01"):
    tax_rs = int(taxable_rs * 0.18) if tax_rs is None else tax_rs
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": taxable_rs * 100,
        "total_tax_paise": tax_rs * 100,
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


def test_genuine_taxable_mismatch_reports_actual_delta():
    """Taxable value differs (tax component held equal) -> reported diff equals
    the true taxable delta, not a raw side value and not ₹0."""
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV7003", 300000, tax_rs=54000)]
    pr = [_pr("p1", "27AAAAA0000A1Z5", "INV7003", 300094, tax_rs=54000)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    row = _review_row_for(res, gid="g1")
    expected_diff_paise = abs(300000 - 300094) * 100
    assert row["taxable_diff_paise"] == expected_diff_paise
    assert row["taxable_diff_paise"] not in (300000 * 100, 300094 * 100)


def test_genuine_tax_only_mismatch_reports_actual_delta_not_zero():
    """Regression: taxable value is IDENTICAL on both sides, but the tax
    component genuinely differs (e.g. a wrong GST rate). The old fix diffed
    taxable_amount_paise only and fell back to total_tax_paise ONLY when both
    taxable values were zero, so this scenario silently reported ₹0 — hiding a
    real discrepancy. It must report the actual tax delta instead."""
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV7100", 300000, tax_rs=54000)]
    pr = [_pr("p1", "27AAAAA0000A1Z5", "INV7100", 300000, tax_rs=54940)]  # ₹940 tax-only gap
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    row = _review_row_for(res, gid="g1")
    expected_diff_paise = abs(54000 - 54940) * 100
    assert row["taxable_diff_paise"] == expected_diff_paise
    assert row["taxable_diff_paise"] != 0


# ── API layer: _pair_tax_diff_paise pure helper ────────────────────────────


def test_api_helper_zero_for_paired_identical_taxable_and_tax():
    gm = {"taxable_amount_paise": 25000000, "total_tax_paise": 4500000}
    pm = {"taxable_amount_paise": 25000000, "total_tax_paise": 4500000}
    assert _pair_tax_diff_paise(gm, pm, {}) == 0


def test_api_helper_actual_delta_when_taxable_differs():
    gm = {"taxable_amount_paise": 30000000, "total_tax_paise": 5400000}
    pm = {"taxable_amount_paise": 30009438, "total_tax_paise": 5400000}
    assert _pair_tax_diff_paise(gm, pm, {}) == abs(30000000 - 30009438)


def test_api_helper_actual_delta_when_only_tax_differs():
    """Regression: taxable is identical on both sides, only total_tax_paise
    differs -> must report the real gap, not ₹0. This is the exact "large_amount
    _review" / "small_amount_diff" symptom: taxable_amount_paise resolves to the
    same value on both sides while the deliberately-injected mismatch lives in
    total_tax_paise."""
    gm = {"taxable_amount_paise": 30000000, "total_tax_paise": 5400000}
    pm = {"taxable_amount_paise": 30000000, "total_tax_paise": 5409438}
    assert _pair_tax_diff_paise(gm, pm, {}) == abs(5400000 - 5409438)
    assert _pair_tax_diff_paise(gm, pm, {}) != 0


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
