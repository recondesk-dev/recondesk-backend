"""Tests for vendor intelligence scoring (pure functions)."""

from __future__ import annotations

from decimal import Decimal

from app.services.vendor_intelligence import (
    calculate_supplier_score,
    count_ineligible_suppliers,
    dedupe_gstr_rows,
    expand_runs_history,
    score_to_api_dict,
    supplier_gstins_from_runs_history,
)


def _row(
    *,
    sg: str,
    inv: str,
    inv_date: str,
    run_id: str,
    adp: int | None,
    created_at: str,
    period_end: str = "2024-03-31",
    reflection: str | None = None,
):
    return {
        "supplier_gstin": sg,
        "invoice_number": inv,
        "invoice_date": inv_date,
        "reconciliation_run_id": run_id,
        "amount_difference_paise": adp,
        "gstr2b_reflection_date": reflection,
        "period_end_date": period_end,
        "created_at": created_at,
    }


def test_dedupe_keeps_latest_created_at():
    rows = [
        _row(
            sg="22AAAAA0000A1Z5",
            inv="A",
            inv_date="2024-01-15",
            run_id="r1",
            adp=0,
            created_at="2024-01-01T00:00:00Z",
        ),
        _row(
            sg="22AAAAA0000A1Z5",
            inv="A",
            inv_date="2024-01-15",
            run_id="r1",
            adp=50,
            created_at="2024-02-01T00:00:00Z",
        ),
    ]
    d = dedupe_gstr_rows(rows)
    assert len(d) == 1
    assert d[0]["amount_difference_paise"] == 50


def test_dedupe_different_invoice_date_not_collapsed():
    rows = [
        _row(
            sg="22AAAAA0000A1Z5",
            inv="A",
            inv_date="2024-01-15",
            run_id="r1",
            adp=0,
            created_at="2024-01-01T00:00:00Z",
        ),
        _row(
            sg="22AAAAA0000A1Z5",
            inv="A",
            inv_date="2024-02-15",
            run_id="r1",
            adp=0,
            created_at="2024-01-02T00:00:00Z",
        ),
    ]
    assert len(dedupe_gstr_rows(rows)) == 2


def test_filing_reliability_requires_80pct_tolerance_per_run():
    # Run r1: 4 invoices, 3 within tolerance (75%) → not reliable
    # Run r2: 1 invoice, 1 within tolerance (100%) → reliable
    hist = [
        _row(
            sg="22AAAAA0000A1Z5",
            inv="1",
            inv_date="2024-01-01",
            run_id="r1",
            adp=0,
            created_at="a1",
        ),
        _row(
            sg="22AAAAA0000A1Z5",
            inv="2",
            inv_date="2024-01-02",
            run_id="r1",
            adp=0,
            created_at="a2",
        ),
        _row(
            sg="22AAAAA0000A1Z5",
            inv="3",
            inv_date="2024-01-03",
            run_id="r1",
            adp=0,
            created_at="a3",
        ),
        _row(
            sg="22AAAAA0000A1Z5",
            inv="4",
            inv_date="2024-01-04",
            run_id="r1",
            adp=500,
            created_at="a4",
        ),
        _row(
            sg="22AAAAA0000A1Z5",
            inv="5",
            inv_date="2024-02-01",
            run_id="r2",
            adp=50,
            created_at="b1",
        ),
    ]
    s = calculate_supplier_score("22AAAAA0000A1Z5", "TN", hist)
    assert s is not None
    assert s["runs_appeared_in"] == 2
    assert s["filing_reliability_pct"] == Decimal("50.00")
    assert s["risk_level"] == "HIGH"


def test_amount_accuracy_and_mismatch_null_adp():
    hist = [
        _row(
            sg="22BBBBB0000B1Z5",
            inv="1",
            inv_date="2024-01-01",
            run_id="r1",
            adp=0,
            created_at="a1",
        ),
        _row(
            sg="22BBBBB0000B1Z5",
            inv="2",
            inv_date="2024-01-02",
            run_id="r1",
            adp=None,
            created_at="a2",
        ),
        _row(
            sg="22BBBBB0000B1Z5",
            inv="3",
            inv_date="2024-03-01",
            run_id="r2",
            adp=0,
            created_at="b1",
        ),
    ]
    s = calculate_supplier_score("22BBBBB0000B1Z5", "", hist)
    assert s is not None
    assert s["amount_accuracy_pct"] == Decimal("66.67")
    assert s["mismatch_count"] == 1


def test_grouped_runs_history_eligible_supplier_scored():
    """Nested *runs_history*: distinct runs counted once per run when supplier appears."""
    hist = [
        {
            "run_id": "r1",
            "period_end_date": "2024-01-31",
            "records": [
                {
                    "supplier_gstin": "22AAAAA0000A1Z5",
                    "invoice_number": "1",
                    "invoice_date": "2024-01-01",
                    "amount_difference_paise": 0,
                    "created_at": "a",
                },
            ],
        },
        {
            "run_id": "r2",
            "period_end_date": "2024-02-28",
            "records": [
                {
                    "supplier_gstin": "22AAAAA0000A1Z5",
                    "invoice_number": "2",
                    "invoice_date": "2024-02-01",
                    "amount_difference_paise": 0,
                    "created_at": "b",
                },
            ],
        },
    ]
    flat = expand_runs_history(hist)
    assert len(flat) == 2
    assert all(r.get("reconciliation_run_id") for r in flat)
    s = calculate_supplier_score("22AAAAA0000A1Z5", "TN", hist)
    assert s is not None
    assert s["runs_appeared_in"] == 2
    assert s["filing_reliability_pct"] == Decimal("100.00")


def test_count_ineligible():
    hist = [
        _row(
            sg="22AAAAA0000A1Z5",
            inv="1",
            inv_date="2024-01-01",
            run_id="r1",
            adp=0,
            created_at="a",
        ),
        _row(
            sg="22AAAAA0000A1Z5",
            inv="2",
            inv_date="2024-02-01",
            run_id="r2",
            adp=0,
            created_at="b",
        ),
        _row(
            sg="22ONLYONERUN0001Z5",
            inv="1",
            inv_date="2024-01-01",
            run_id="r1",
            adp=0,
            created_at="c",
        ),
    ]
    el, excl = count_ineligible_suppliers(hist, 2)
    assert "22AAAAA0000A1Z5" in el
    assert "22ONLYONERUN0001Z5" not in el
    assert excl == 1

    grouped = [
        {"run_id": "r1", "period_end_date": "2024-01-31", "records": [hist[0], hist[2]]},
        {"run_id": "r2", "period_end_date": "2024-02-28", "records": [hist[1]]},
    ]
    el2, excl2 = count_ineligible_suppliers(grouped, 2)
    assert el2 == el
    assert excl2 == excl


def test_calculate_supplier_score_none_when_fewer_than_two_runs():
    hist = [
        _row(
            sg="22BBBBB0000B1Z5",
            inv="1",
            inv_date="2024-01-01",
            run_id="r1",
            adp=0,
            created_at="a",
        ),
    ]
    assert calculate_supplier_score("22BBBBB0000B1Z5", "", hist) is None


def test_supplier_derivation_exclusion_and_risk_sort():
    """A and B in 2+ runs; C in 1 run only — excluded count 1; response rows all runs_appeared_in >= 2."""
    hist = [
        {
            "run_id": "r1",
            "period_end_date": "2024-01-31",
            "records": [
                {
                    "supplier_gstin": "SUP_A",
                    "invoice_number": "1",
                    "invoice_date": "2024-01-01",
                    "amount_difference_paise": 0,
                    "created_at": "a",
                },
                {
                    "supplier_gstin": "SUP_B",
                    "invoice_number": "1",
                    "invoice_date": "2024-01-01",
                    "amount_difference_paise": 50,
                    "created_at": "b",
                },
                {
                    "supplier_gstin": "SUP_C",
                    "invoice_number": "1",
                    "invoice_date": "2024-01-01",
                    "amount_difference_paise": 0,
                    "created_at": "c",
                },
            ],
        },
        {
            "run_id": "r2",
            "period_end_date": "2024-02-28",
            "records": [
                {
                    "supplier_gstin": "SUP_A",
                    "invoice_number": "2",
                    "invoice_date": "2024-02-01",
                    "amount_difference_paise": 500,
                    "created_at": "d",
                },
                {
                    "supplier_gstin": "SUP_B",
                    "invoice_number": "2",
                    "invoice_date": "2024-02-01",
                    "amount_difference_paise": 0,
                    "created_at": "e",
                },
            ],
        },
    ]
    sups = supplier_gstins_from_runs_history(hist)
    assert sups == {"SUP_A", "SUP_B", "SUP_C"}

    excluded = 0
    results: list[dict] = []
    for sg in sorted(sups):
        sc = calculate_supplier_score(sg, "", hist)
        if sc is None:
            excluded += 1
            continue
        results.append(score_to_api_dict(sg, "", sc))

    assert excluded == 1
    assert {r["supplier_gstin"] for r in results} == {"SUP_A", "SUP_B"}
    assert all(r["runs_appeared_in"] >= 2 for r in results)

    RISK_ORDER = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
    results.sort(
        key=lambda x: (RISK_ORDER[str(x["risk_level"])], x["supplier_gstin"])
    )
    # SUP_A: 0% filing reliability → HIGH; SUP_B: both runs within tolerance → LOW
    assert [r["supplier_gstin"] for r in results] == ["SUP_A", "SUP_B"]
    assert [r["risk_level"] for r in results] == ["HIGH", "LOW"]
