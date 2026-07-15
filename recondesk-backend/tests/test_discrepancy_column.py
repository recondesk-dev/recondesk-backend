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
from unittest.mock import patch

from app.matching.engine import run_bidirectional_reconciliation
from app.routers.reconciliation_api import (
    _build_matched_pair_records,
    _matched_ui_match_level,
    _pair_tax_diff_paise,
)
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


def test_gstin_mismatch_api_exposes_amount_and_discrepancy_reason():
    """Review API must show real ITC amount and GSTIN_MISMATCH reason (not blank ₹0)."""
    from app.routers import reconciliation_api as api

    tax_paise = 4_500_000
    gstr_db = {
        "g1": {
            "matcher": {
                "taxable_amount_paise": 25_000_000,
                "total_tax_paise": tax_paise,
                "supplier_gstin": "27AAAAA0000A1Z5",
                "invoice_number_normalized": "INV5001",
                "invoice_date": "2026-05-01",
            },
            "record_data": {},
        }
    }
    pr_db = {
        "p1": {
            "matcher": {
                "taxable_amount_paise": 25_000_000,
                "total_tax_paise": tax_paise,
                "supplier_gstin": "29BBBBB0000B1Z5",
                "invoice_number_normalized": "INV5001",
                "invoice_date": "2026-05-01",
            },
            "record_data": {},
        }
    }
    # Slim engine row omits total_tax_paise — amount must come from gm.
    en_row = {
        "gstr_id": "g1",
        "pr_id": "p1",
        "id": "p1",
        "confidence_score": 70,
        "match_status": "review_required",
        "review_reason": "GSTIN_MISMATCH",
        "reason": "GSTIN_MISMATCH",
        "match_level": 0,
        "taxable_diff_paise": 0,
    }
    payload = {
        "engine": {"duplicates": [en_row], "review_required_typo": []},
        "decisions": {"rows": []},
    }

    with patch.object(api.ro, "load_gstr_map", return_value=gstr_db), patch.object(
        api.ro, "load_pr_map", return_value=pr_db
    ):
        pairs = _build_matched_pair_records(
            None,
            rid="r1",
            payload=payload,
            note_counts={},
            fetch_review_required=True,
            precomputed_outcome_rows=[],
        )

    assert len(pairs) == 1
    row, _orow = pairs[0]
    assert row["amount"] == tax_paise / 100.0
    assert row["tax_difference_paise"] == 0
    assert row["discrepancy_reason"] == "GSTIN_MISMATCH"


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


# ── L2_NORMALIZED tier: same helper must apply, no separate/short-circuited
#    code path that hardcodes or defaults the diff to ₹0 ──────────────────


def test_l2_normalized_small_taxable_diff_reports_actual_delta():
    """Same GSTIN + same invoice number, taxable off by ₹300 on a ₹280,000
    invoice (~0.11%, well inside the 1% L2 tolerance) -> Phase 1 classifies
    this as match_level == 2 (L2_NORMALIZED) with requires_human_review=True.
    The stored discrepancy must be the real ₹300 gap (in paise), not ₹0 —
    there is no tier where "the match is close enough" should mean "don't
    bother computing the actual number"."""
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV02326", 280000, tax_rs=50400)]
    pr = [_pr("p1", "27AAAAA0000A1Z5", "INV02326", 280300, tax_rs=50400)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    row = _review_row_for(res, gid="g1")
    assert row.get("match_level") == 2, (
        f"Expected this small (<1%) taxable diff to land at L2_NORMALIZED "
        f"(match_level=2), got match_level={row.get('match_level')}"
    )
    expected_diff_paise = abs(280000 - 280300) * 100
    assert row["taxable_diff_paise"] == expected_diff_paise, (
        f"L2_NORMALIZED row must report the real ₹300 diff "
        f"({expected_diff_paise} paise), got {row['taxable_diff_paise']}"
    )
    assert row["taxable_diff_paise"] != 0


def test_matched_ui_match_level_labels_l2_as_l2_normalized():
    """The Review Required tab's Match Method column must show L2_NORMALIZED
    (not FUZZY, not a blank) for match_level == 2 rows."""
    en_row = {"match_level": 2, "reason": "Amount/Date mismatch"}
    label = _matched_ui_match_level(en_row, None, for_matched_tab=False)
    assert label == "L2_NORMALIZED"


def test_l2_normalized_end_to_end_api_response_reports_actual_delta():
    """Full simulation of the Review Required API path (_build_matched_pair_records)
    for an L2_NORMALIZED row: gm/pm resolved from the DB matcher projection must
    yield the real diff in the API response's tax_difference_paise field, exactly
    like L3_AMOUNT_MISMATCH / GSTIN_MISMATCH rows do. This locks in that L2 is
    NOT a separate, short-circuited code path."""
    from app.routers import reconciliation_api as api

    gstr_db = {
        "g1": {
            "matcher": {
                "taxable_amount_paise": 28000000,
                "total_tax_paise": 5040000,
                "supplier_gstin": "27AAAAA0000A1Z5",
                "invoice_number_normalized": "INV02326",
                "invoice_date": "2026-05-01",
            },
            "record_data": {},
        }
    }
    pr_db = {
        "p1": {
            "matcher": {
                "taxable_amount_paise": 28030000,
                "total_tax_paise": 5040000,
                "supplier_gstin": "27AAAAA0000A1Z5",
                "invoice_number_normalized": "INV02326",
                "invoice_date": "2026-05-01",
            },
            "record_data": {},
        }
    }
    en_row = {
        "gstr_id": "g1",
        "pr_id": "p1",
        "id": "p1",
        "confidence_score": 90,
        "match_status": "review_required",
        "review_reason": "Amount/Date mismatch",
        "reason": "Amount/Date mismatch",
        "match_level": 2,
        "taxable_diff_paise": 30000,
    }
    payload = {"engine": {"duplicates": [en_row], "review_required_typo": []}, "decisions": {"rows": []}}

    with patch.object(api.ro, "load_gstr_map", return_value=gstr_db), \
         patch.object(api.ro, "load_pr_map", return_value=pr_db):
        pairs = _build_matched_pair_records(
            None, rid="r1", payload=payload, note_counts={},
            fetch_review_required=True, precomputed_outcome_rows=[],
        )

    assert len(pairs) == 1
    row, _orow = pairs[0]
    assert row["match_level"] == "L2_NORMALIZED"
    assert row["tax_difference_paise"] == 30000, (
        f"L2_NORMALIZED API response must show the real ₹300 diff (30000 paise), "
        f"got {row['tax_difference_paise']}"
    )


def test_discrepancy_helper_is_level_agnostic():
    """_pair_tax_diff_paise takes only gm/pm — it has no match_level parameter
    and therefore cannot special-case any tier. This test pins that behavior:
    the same gm/pm pair yields the identical diff no matter what match_level /
    review_reason the caller attaches to the row, proving every tier (L1-L5,
    GSTIN_MISMATCH, TYPO_MISMATCH, ...) that reaches this helper is diffed
    identically."""
    gm = {"taxable_amount_paise": 28000000, "total_tax_paise": 5040000}
    pm = {"taxable_amount_paise": 28030000, "total_tax_paise": 5040000}
    expected = abs(28000000 - 28030000)
    for level in (1, 2, 3, 4, 5, None):
        en_row = {"match_level": level, "reason": "whatever"}
        assert _pair_tax_diff_paise(gm, pm, en_row) == expected


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


# ── Matched tab: multi-line PR split must not fabricate a sibling-sized gap ─


def test_matched_pr_matcher_for_diff_sums_multiline_siblings():
    """Production bug (4483A): GSTR has two line items; PR books them as two
    rows. Engine correctly clean-matches the group, but the Matched row only
    stores the primary pr_id. Diffing GSTR vs that one line must NOT report the
    sibling's full value as a 'tax difference'."""
    from app.routers.reconciliation_api import _matched_pr_matcher_for_diff

    gstin = "23HQCYW1875Y6Z5"
    inv = "4483A"
    gm = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 82611808,
        "total_tax_paise": 14870125,
    }
    pm_primary = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 49567085,
        "total_tax_paise": 8922075,
    }
    pm_sibling = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 33044723,
        "total_tax_paise": 5948050,
    }
    pr_db = {
        "p1": {"matcher": pm_primary, "record_data": {}},
        "p2": {"matcher": pm_sibling, "record_data": {}},
    }

    # Primary-only (the old bug): fake ₹3,89,927.73 gap.
    assert _pair_tax_diff_paise(gm, pm_primary, {}) == 38992773

    # With sibling aggregation (no persisted pr_ids — rediscovery path):
    pm_eff = _matched_pr_matcher_for_diff(gm, pm_primary, {"pr_id": "p1"}, pr_db)
    assert _pair_tax_diff_paise(gm, pm_eff, {}) == 0

    # Persisted pr_ids path (new runs):
    pm_eff2 = _matched_pr_matcher_for_diff(
        gm, pm_primary, {"pr_id": "p1", "pr_ids": ["p1", "p2"], "multiline_pr_split": True}, pr_db
    )
    assert _pair_tax_diff_paise(gm, pm_eff2, {}) == 0


def test_matched_pr_matcher_for_diff_does_not_sum_true_duplicates():
    """Two full-value PR copies of one GSTR invoice are duplicates, not a
    multi-line split. Summing them would invent a 1×-invoice fake gap. The
    multiline gate must refuse and leave the primary (exact) amounts alone."""
    from app.routers.reconciliation_api import _matched_pr_matcher_for_diff

    gstin = "27AAAAA0000A1Z5"
    inv = "DUP-1"
    gm = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 100_000,
        "total_tax_paise": 18_000,
    }
    pm_full = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 100_000,
        "total_tax_paise": 18_000,
    }
    pr_db = {
        "p-canon": {"matcher": pm_full, "record_data": {}},
        "p-extra": {"matcher": dict(pm_full), "record_data": {}},
    }
    pm_eff = _matched_pr_matcher_for_diff(
        gm, pm_full, {"pr_id": "p-canon", "pr_ids": ["p-canon", "p-extra"]}, pr_db
    )
    # Must stay primary-only (exact), not sum to 2×.
    assert pm_eff["taxable_amount_paise"] == 100_000
    assert pm_eff["total_tax_paise"] == 18_000
    assert _pair_tax_diff_paise(gm, pm_eff, {}) == 0


def test_matched_pr_matcher_for_diff_does_not_zero_non_partition_siblings():
    """Same invoice number on two PR rows that do NOT sum to GSTR must not be
    silently zeroed — preserve the real primary-vs-GSTR gap."""
    from app.routers.reconciliation_api import _matched_pr_matcher_for_diff

    gstin = "27AAAAA0000A1Z5"
    inv = "MIX-1"
    gm = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 100_000,
        "total_tax_paise": 18_000,
    }
    pm_partial = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 40_000,
        "total_tax_paise": 7_200,
    }
    pm_other = {
        "supplier_gstin": gstin,
        "invoice_number_normalized": inv,
        "taxable_amount_paise": 30_000,  # 40k+30k != 100k
        "total_tax_paise": 5_400,
    }
    pr_db = {
        "p1": {"matcher": pm_partial, "record_data": {}},
        "p2": {"matcher": pm_other, "record_data": {}},
    }
    pm_eff = _matched_pr_matcher_for_diff(gm, pm_partial, {"pr_id": "p1"}, pr_db)
    assert pm_eff is pm_partial or (
        pm_eff["taxable_amount_paise"] == 40_000 and pm_eff["total_tax_paise"] == 7_200
    )
    expected = abs((100_000 + 18_000) - (40_000 + 7_200))
    assert _pair_tax_diff_paise(gm, pm_eff, {}) == expected


def test_matched_tab_api_multiline_reports_zero_discrepancy():
    """End-to-end Matched API path: multi-line PR split → tax_difference_paise=0."""
    from app.routers import reconciliation_api as api

    gstin = "23HQCYW1875Y6Z5"
    inv = "4483A"
    gstr_db = {
        "g1": {
            "matcher": {
                "supplier_gstin": gstin,
                "invoice_number_normalized": inv,
                "invoice_date": "2024-12-26",
                "taxable_amount_paise": 82611808,
                "total_tax_paise": 14870125,
            },
            "record_data": {},
        }
    }
    pr_db = {
        "p1": {
            "matcher": {
                "supplier_gstin": gstin,
                "invoice_number_normalized": inv,
                "invoice_date": "2024-12-26",
                "taxable_amount_paise": 49567085,
                "total_tax_paise": 8922075,
            },
            "record_data": {},
        },
        "p2": {
            "matcher": {
                "supplier_gstin": gstin,
                "invoice_number_normalized": inv,
                "invoice_date": "2024-12-26",
                "taxable_amount_paise": 33044723,
                "total_tax_paise": 5948050,
            },
            "record_data": {},
        },
    }
    # Persisted shape of an already-completed run (pr_ids stripped).
    en_row = {
        "gstr_id": "g1",
        "pr_id": "p1",
        "confidence_score": 80,
        "match_level": 2,
        "financial_status": "Exact",
    }
    payload = {"engine": {"matched": [en_row]}, "decisions": {"rows": []}}

    with patch.object(api.ro, "load_gstr_map", return_value=gstr_db), \
         patch.object(api.ro, "load_pr_map", return_value=pr_db):
        pairs = _build_matched_pair_records(
            None, rid="r1", payload=payload, note_counts={},
            fetch_review_required=False, precomputed_outcome_rows=[],
        )

    assert len(pairs) == 1
    row, _orow = pairs[0]
    assert row["tax_difference_paise"] == 0, (
        f"Multi-line clean match must show ₹0 on Matched, got "
        f"{row['tax_difference_paise']} (Rs {row['tax_difference_paise']/100:,.2f})"
    )


def test_review_required_api_does_not_aggregate_multiline_siblings():
    """Review Required must keep the real primary-vs-GSTR gap even when another
    PR row shares the invoice number — sibling aggregation is Matched-only."""
    from app.routers import reconciliation_api as api

    gstin = "27AAAAA0000A1Z5"
    inv = "REV-1"
    gstr_db = {
        "g1": {
            "matcher": {
                "supplier_gstin": gstin,
                "invoice_number_normalized": inv,
                "invoice_date": "2026-05-01",
                "taxable_amount_paise": 100_000,
                "total_tax_paise": 18_000,
            },
            "record_data": {},
        }
    }
    pr_db = {
        "p1": {
            "matcher": {
                "supplier_gstin": gstin,
                "invoice_number_normalized": inv,
                "invoice_date": "2026-05-01",
                "taxable_amount_paise": 40_000,
                "total_tax_paise": 7_200,
            },
            "record_data": {},
        },
        "p2": {
            "matcher": {
                "supplier_gstin": gstin,
                "invoice_number_normalized": inv,
                "invoice_date": "2026-05-01",
                "taxable_amount_paise": 60_000,
                "total_tax_paise": 10_800,
            },
            "record_data": {},
        },
    }
    # Note: p1+p2 DO sum to GSTR — if Review wrongly aggregated, diff would be 0.
    en_row = {
        "gstr_id": "g1",
        "pr_id": "p1",
        "id": "p1",
        "confidence_score": 60,
        "match_status": "review_required",
        "reason": "AMOUNT_MISMATCH",
        "match_level": 3,
        "taxable_diff_paise": abs((100_000 + 18_000) - (40_000 + 7_200)),
    }
    payload = {"engine": {"duplicates": [en_row], "review_required_typo": []}, "decisions": {"rows": []}}

    with patch.object(api.ro, "load_gstr_map", return_value=gstr_db), \
         patch.object(api.ro, "load_pr_map", return_value=pr_db):
        pairs = _build_matched_pair_records(
            None, rid="r1", payload=payload, note_counts={},
            fetch_review_required=True, precomputed_outcome_rows=[],
        )

    assert len(pairs) == 1
    row, _orow = pairs[0]
    assert row["tax_difference_paise"] == abs((100_000 + 18_000) - (40_000 + 7_200))
    assert row["tax_difference_paise"] != 0


def test_slim_engine_matched_preserves_multiline_pr_ids():
    from app.services.reconciliation_payload_store import slim_engine_matched

    slim = slim_engine_matched(
        [
            {
                "gstr_id": "g1",
                "pr_id": "p1",
                "confidence_score": 80,
                "match_level": 2,
                "financial_status": "Exact",
                "pr_ids": ["p1", "p2"],
                "multiline_pr_split": True,
                "match_reasons": ["should be dropped"],
            }
        ]
    )
    assert slim[0]["pr_ids"] == ["p1", "p2"]
    assert slim[0]["multiline_pr_split"] is True
    assert "match_reasons" not in slim[0]
