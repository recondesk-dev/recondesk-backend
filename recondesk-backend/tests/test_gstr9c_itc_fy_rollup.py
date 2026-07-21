"""
test_gstr9c_itc_fy_rollup.py
Pure-function tests for GSTR-9C ITC FY rollup aggregation.
Run: PYTHONPATH=. pytest tests/test_gstr9c_itc_fy_rollup.py -v
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.gstr9c_itc_fy_rollup import (
    assemble_fy_rollup,
    classify_month,
    default_fy_label,
    extract_claimed_itc_rupees,
    extract_matched_itc_paise,
    format_fy_label,
    fy_periods,
    parse_fy_label,
    period_month_label,
)


class TestFyHelpers:
    def test_parse_and_format(self):
        assert parse_fy_label("2025-26") == (2025, 2026)
        assert format_fy_label(2025) == "2025-26"
        assert format_fy_label(2099) == "2099-00"

    def test_parse_rejects_bad_labels(self):
        with pytest.raises(ValueError):
            parse_fy_label("2025")
        with pytest.raises(ValueError):
            parse_fy_label("2025-27")
        with pytest.raises(ValueError):
            parse_fy_label("abcd-ef")

    def test_fy_periods_april_to_march(self):
        periods = fy_periods(2025)
        assert periods[0] == "2025-04"
        assert periods[-1] == "2026-03"
        assert len(periods) == 12

    def test_default_fy_label_april_boundary(self):
        assert default_fy_label(date(2026, 4, 1)) == "2026-27"
        assert default_fy_label(date(2026, 3, 31)) == "2025-26"

    def test_period_month_label(self):
        assert period_month_label("2025-04") == "Apr 2025"
        assert period_month_label("2026-01") == "Jan 2026"


class TestExtractors:
    def test_matched_itc_from_run_summary(self):
        assert extract_matched_itc_paise({"matched_itc_paise": 12_500}) == 12_500
        assert extract_matched_itc_paise(None) == 0
        assert extract_matched_itc_paise({}) == 0

    def test_claimed_itc_sums_heads(self):
        out = extract_claimed_itc_rupees(
            {
                "gstr3b_igst_claimed": 100.5,
                "gstr3b_cgst_claimed": 50.25,
                "gstr3b_sgst_claimed": 50.25,
            }
        )
        assert out["total"] == 201.0
        assert extract_claimed_itc_rupees(None)["total"] == 0.0


class TestClassify:
    def test_statuses(self):
        assert classify_month(has_run=True, has_gstr3b=True) == "both"
        assert classify_month(has_run=True, has_gstr3b=False) == "run_only"
        assert classify_month(has_run=False, has_gstr3b=False) == "missing"


def _run(period: str, matched_paise: int, run_id: str = "r1") -> dict:
    return {
        "id": run_id,
        "period": period,
        "status": "FINAL",
        "run_summary": {
            "matched_itc_paise": matched_paise,
            "missed_itc_paise": 100,
            "itc_at_risk": 100,
            "wrongful_itc": 0,
        },
    }


def _g3b(run_id: str, total_heads: tuple[float, float, float]) -> dict:
    igst, cgst, sgst = total_heads
    return {
        "run_id": run_id,
        "gstr3b_igst_claimed": igst,
        "gstr3b_cgst_claimed": cgst,
        "gstr3b_sgst_claimed": sgst,
    }


class TestAssemble:
    def test_incomplete_year_flags_and_partial_variance(self):
        runs = {
            "2025-04": _run("2025-04", 10_000, "apr"),
            "2025-05": _run("2025-05", 20_000, "may"),
        }
        g3b = {
            "apr": _g3b("apr", (50.0, 25.0, 25.0)),  # claimed 100
        }
        out = assemble_fy_rollup(
            client_gstin_id="c1",
            gstin="27ABCDE1234F1Z5",
            trade_name="Acme",
            fy="2025-26",
            runs_by_period=runs,
            g3b_by_run_id=g3b,
        )
        assert out["is_complete"] is False
        assert out["variance_available"] is True
        assert out["months_with_both"] == 1
        assert out["months_with_run"] == 2
        assert out["months_run_only"] == 1
        assert out["months_missing"] == 10
        assert out["totals"]["matched_itc_rupees"] == 300.0  # 100 + 200
        assert out["totals"]["claimed_itc_rupees"] == 100.0
        # Variance only for Apr (both): 100 - 100 = 0
        assert out["totals"]["variance_rupees"] == 0.0
        assert out["totals"]["months_in_variance"] == 1
        assert out["totals"]["partial_label"] == "Partial — 1 of 12 months"
        assert "Not an official GSTR-9C Table 8" in out["disclaimer"]

        by_period = {m["period"]: m for m in out["months"]}
        assert by_period["2025-04"]["status"] == "both"
        assert by_period["2025-04"]["included_in_variance"] is True
        assert by_period["2025-04"]["variance_rupees"] == 0.0
        assert by_period["2025-05"]["status"] == "run_only"
        assert by_period["2025-05"]["included_in_variance"] is False
        assert by_period["2025-05"]["variance_rupees"] is None
        assert by_period["2025-06"]["status"] == "missing"
        assert by_period["2025-06"]["matched_itc_rupees"] is None

    def test_zero_both_months_no_variance(self):
        runs = {"2025-04": _run("2025-04", 50_000, "apr")}
        out = assemble_fy_rollup(
            client_gstin_id="c1",
            gstin="27ABCDE1234F1Z5",
            trade_name=None,
            fy="2025-26",
            runs_by_period=runs,
            g3b_by_run_id={},
        )
        assert out["variance_available"] is False
        assert out["months_with_both"] == 0
        assert out["totals"]["variance_rupees"] is None
        assert out["totals"]["matched_itc_rupees"] == 500.0
        assert out["totals"]["claimed_itc_rupees"] == 0.0
        assert "No variance available" in out["totals"]["partial_label"]

    def test_complete_year_no_partial_caveat(self):
        runs = {}
        g3b = {}
        for i, period in enumerate(fy_periods(2024)):
            rid = f"r{i}"
            runs[period] = _run(period, 1_000, rid)
            g3b[rid] = _g3b(rid, (5.0, 2.5, 2.5))  # claimed 10
        out = assemble_fy_rollup(
            client_gstin_id="c1",
            gstin="27ABCDE1234F1Z5",
            trade_name="Full",
            fy="2024-25",
            runs_by_period=runs,
            g3b_by_run_id=g3b,
        )
        assert out["is_complete"] is True
        assert out["variance_available"] is True
        assert out["months_with_both"] == 12
        # matched 12 * 10 rupees = 120; claimed 12 * 10 = 120; variance 0
        assert out["totals"]["matched_itc_rupees"] == 120.0
        assert out["totals"]["claimed_itc_rupees"] == 120.0
        assert out["totals"]["variance_rupees"] == 0.0
        assert out["totals"]["partial_label"] == "Complete — 12 of 12 months"

    def test_variance_excludes_run_only_from_delta(self):
        runs = {
            "2025-04": _run("2025-04", 100_00, "apr"),  # ₹100
            "2025-05": _run("2025-05", 500_00, "may"),  # ₹500 run-only
        }
        g3b = {"apr": _g3b("apr", (40.0, 30.0, 30.0))}  # ₹100 claimed
        out = assemble_fy_rollup(
            client_gstin_id="c1",
            gstin="27ABCDE1234F1Z5",
            trade_name="X",
            fy="2025-26",
            runs_by_period=runs,
            g3b_by_run_id=g3b,
        )
        # Annual matched includes May; variance uses only Apr
        assert out["totals"]["matched_itc_rupees"] == 600.0
        assert out["totals"]["variance_matched_itc_rupees"] == 100.0
        assert out["totals"]["variance_claimed_itc_rupees"] == 100.0
        assert out["totals"]["variance_rupees"] == 0.0

    def test_period_fallback_attaches_3b_from_older_run(self):
        """May: latest 2B run has no 3B, but an older May run does — must count as both."""
        runs = {
            "2026-04": _run("2026-04", 186_311_13, "apr-latest"),  # ₹186,311.13
            "2026-05": _run("2026-05", 193_329_29, "may-latest"),  # ₹193,329.29
            "2026-06": _run("2026-06", 184_403_83, "jun-latest"),
        }
        # 3B only on older May run id — not on may-latest
        g3b_by_run = {
            "apr-latest": _g3b("apr-latest", (62226.8, 62226.8, 62226.79)),  # 186680.39
            "jun-latest": _g3b("jun-latest", (73021.53, 54766.15, 54766.15)),  # 182553.83
        }
        g3b_by_period = {
            "2026-05": {
                "run_id": "may-old",
                "tax_period": "2026-05",
                "gstr3b_igst_claimed": 1_100_000.0,
                "gstr3b_cgst_claimed": 825_000.0,
                "gstr3b_sgst_claimed": 825_000.0,
            },
        }
        out = assemble_fy_rollup(
            client_gstin_id="c1",
            gstin="27ISKPK1273H1ZF",
            trade_name="Acme",
            fy="2026-27",
            runs_by_period=runs,
            g3b_by_run_id=g3b_by_run,
            g3b_by_period=g3b_by_period,
        )
        by_period = {m["period"]: m for m in out["months"]}
        assert by_period["2026-05"]["status"] == "both"
        assert by_period["2026-05"]["claimed_itc_rupees"] == 2_750_000.0
        assert by_period["2026-05"]["included_in_variance"] is True
        assert out["months_with_both"] == 3
        # Without fallback May would be excluded and annual ≈ Apr+Jun only.
        assert out["totals"]["months_in_variance"] == 3
        assert out["totals"]["claimed_itc_rupees"] == round(
            186680.39 + 2_750_000.0 + 182553.83, 2
        )

    def test_normalize_period_yyyy_mm(self):
        from app.services.gstr9c_itc_fy_rollup import normalize_period_yyyy_mm

        assert normalize_period_yyyy_mm("2026-05") == "2026-05"
        assert normalize_period_yyyy_mm("2026-05-01") == "2026-05"
        assert normalize_period_yyyy_mm("052026") == "2026-05"
        assert normalize_period_yyyy_mm("202605") == "2026-05"
        assert normalize_period_yyyy_mm("") == ""
