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
from app.services.gstr9c_itc_fy_rollup import assemble_fy_rollup
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
