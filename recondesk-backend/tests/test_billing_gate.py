"""Billing credit sync helpers."""

from app.services.billing_gate import (
    FREE_GSTIN_LIMIT,
    FREE_RUNS_ALLOCATION,
    PLAN_CONFIG,
    _is_successful_run_status,
)


def test_successful_run_statuses():
    assert _is_successful_run_status("COMPLETED")
    assert _is_successful_run_status("FINAL")
    assert _is_successful_run_status("complete")
    assert _is_successful_run_status("finalized")
    assert not _is_successful_run_status("MATCHING")
    assert not _is_successful_run_status("PROCESSING")


def test_free_runs_allocation_is_two():
    assert FREE_RUNS_ALLOCATION == 2


def test_free_gstin_limit_is_two():
    assert FREE_GSTIN_LIMIT == 2


def test_gstin_plan_catalog():
    assert set(PLAN_CONFIG) == {"starter", "growth", "pro"}
    assert PLAN_CONFIG["starter"]["gstin_limit"] == 25
    assert PLAN_CONFIG["starter"]["period_days"] == 30
    assert PLAN_CONFIG["starter"]["base_paise"] == 99_900
    assert PLAN_CONFIG["growth"]["gstin_limit"] == 50
    assert PLAN_CONFIG["growth"]["period_days"] == 365
    assert PLAN_CONFIG["growth"]["base_paise"] == 799_900
    assert PLAN_CONFIG["pro"]["gstin_limit"] == 75
    assert PLAN_CONFIG["pro"]["period_days"] == 365
    assert PLAN_CONFIG["pro"]["base_paise"] == 1_199_900
    for cfg in PLAN_CONFIG.values():
        assert cfg["total_paise"] == cfg["base_paise"] + cfg["gst_paise"]


def test_expected_free_runs_after_successful_runs():
    for successful, expected in [(0, 2), (1, 1), (2, 0), (5, 0)]:
        assert (
            max(0, FREE_RUNS_ALLOCATION - min(successful, FREE_RUNS_ALLOCATION))
            == expected
        )
