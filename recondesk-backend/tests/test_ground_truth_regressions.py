"""Ground-truth regressions for silent-drop / latest-run anti-patterns.

These fixtures encode adversarial cases that previously looked clean on summary
screens while a per-run page still showed the risk. Exact numbers are locked —
do not soften assertions to ``approx``.

Add a new finding:
  1. Drop a JSON file under ``tests/ground_truth/``
  2. Set ``module`` to one of the handlers below (or extend the dispatch)
  3. Put paisa/rupee-exact values in ``expect``

CI runs this file explicitly before the full suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.routers.dashboard import _sum_itc_at_risk_across_periods
from app.reconciliation.gstr1_vs_3b import aggregate_gstr1
from app.rules.gstr1_mismatch_rules import detect_amendments
from app.services.gstr3b_reconciliation import (
    accumulate_gstr2b_available_itc,
    compute_drc01c_threshold,
)
from app.services.gstr9c_itc_fy_rollup import assemble_fy_rollup, periods_match_yyyy_mm
from app.services.rule37_alert_scan import select_alert_run_ids_by_period

_GROUND_TRUTH_DIR = Path(__file__).resolve().parent / "ground_truth"


def _load_fixtures() -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(_GROUND_TRUTH_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "id" not in data:
            raise AssertionError(f"Invalid ground-truth fixture: {path.name}")
        out.append((path.name, data))
    return out


_FIXTURES = _load_fixtures()


def test_ground_truth_fixtures_exist():
    assert _FIXTURES, "expected at least one tests/ground_truth/*.json fixture"
    ids = [fx["id"] for _, fx in _FIXTURES]
    assert len(ids) == len(set(ids)), f"duplicate fixture ids: {ids}"


@pytest.mark.parametrize(
    "filename,fixture",
    _FIXTURES,
    ids=[fx["id"] for _, fx in _FIXTURES],
)
def test_ground_truth_case(filename: str, fixture: dict[str, Any]):
    module = str(fixture.get("module") or "").strip()
    if module == "gstr9c_itc_fy_rollup":
        _assert_gstr9c(fixture)
    elif module == "rule37_alert_scan":
        _assert_rule37(fixture)
    elif module == "dashboard":
        _assert_dashboard(fixture)
    elif module == "gstr3b_period_match":
        _assert_gstr3b_period(fixture)
    elif module == "gstr3b_available_itc":
        _assert_gstr3b_available(fixture)
    elif module == "gstr1_vs_3b_aggregate":
        _assert_gstr1_aggregate(fixture)
    elif module == "gstr1_amendment_detect":
        _assert_gstr1_amendment(fixture)
    else:
        raise AssertionError(
            f"{filename}: unknown module {module!r} — extend test_ground_truth_regressions.py"
        )


def _assert_gstr9c(fixture: dict[str, Any]) -> None:
    inp = fixture["input"]
    expect = fixture["expect"]
    out = assemble_fy_rollup(
        client_gstin_id=inp["client_gstin_id"],
        gstin=inp["gstin"],
        trade_name=inp.get("trade_name"),
        fy=inp["fy"],
        runs_by_period=inp["runs_by_period"],
        g3b_by_run_id=inp.get("g3b_by_run_id") or {},
        g3b_by_period=inp.get("g3b_by_period"),
    )
    by_period = {m["period"]: m for m in out["months"]}
    may = by_period["2026-05"]

    assert out["months_with_both"] == expect["months_with_both"]
    assert out["totals"]["months_in_variance"] == expect["months_in_variance"]
    assert may["status"] == expect["may_status"]
    assert may["claimed_itc_rupees"] == expect["may_claimed_itc_rupees"]
    assert may["included_in_variance"] is expect["may_included_in_variance"]
    assert out["totals"]["claimed_itc_rupees"] == expect["claimed_itc_rupees"]


def _assert_rule37(fixture: dict[str, Any]) -> None:
    inp = fixture["input"]
    expect = fixture["expect"]
    nonempty = set(inp["pr_nonempty_run_ids"])
    got = select_alert_run_ids_by_period(
        inp["runs"],
        has_pr_records=lambda rid: rid in nonempty,
    )
    assert set(got) == set(expect["selected_run_ids_set"])
    assert got == expect["selected_run_ids_order"]
    for rid in expect.get("must_not_select") or []:
        assert rid not in got


def _assert_dashboard(fixture: dict[str, Any]) -> None:
    inp = fixture["input"]
    expect = fixture["expect"]
    assert _sum_itc_at_risk_across_periods(inp["runs"]) == expect["itc_at_risk"]


def _assert_gstr3b_period(fixture: dict[str, Any]) -> None:
    cases = fixture["input"]["cases"]
    expected = fixture["expect"]["matches"]
    assert len(cases) == len(expected)
    for case, want in zip(cases, expected):
        got = periods_match_yyyy_mm(case["file_period"], case["run_period"])
        assert got is want, case


def _assert_gstr3b_available(fixture: dict[str, Any]) -> None:
    inp = fixture["input"]
    expect = fixture["expect"]
    avail = accumulate_gstr2b_available_itc(inp["records"])
    assert avail["igst"] == expect["available_igst"]
    total = round(avail["igst"] + avail["cgst"] + avail["sgst"], 2)
    assert total == expect["available_total"]
    drc = compute_drc01c_threshold(inp["claimed_total"], total)
    assert drc["triggers_drc01c"] is expect["triggers_drc01c"]

    wrong = compute_drc01c_threshold(
        inp["claimed_total"],
        expect["wrong_available_if_cn_positive_and_itcavl_included"],
    )
    assert wrong["triggers_drc01c"] is expect["wrong_would_trigger_drc01c"]


def _assert_gstr1_aggregate(fixture: dict[str, Any]) -> None:
    inp = fixture["input"]
    expect = fixture["expect"]
    agg = aggregate_gstr1(inp["records"])
    assert agg.taxable_value_paise == expect["taxable_value_paise"]
    assert agg.igst_paise == expect["igst_paise"]
    assert agg.record_count == expect["record_count"]


def _assert_gstr1_amendment(fixture: dict[str, Any]) -> None:
    inp = fixture["input"]
    expect = fixture["expect"]
    results = detect_amendments(
        inp.get("sr") or [],
        inp.get("prior") or [],
        prior_provided=True,
        current_amendment_records=inp.get("filed"),
    )
    assert len(results) == expect["flag_count"]
