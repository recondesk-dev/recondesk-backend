"""Billing credit sync helpers."""

from app.services.billing_gate import (
    FREE_GSTIN_LIMIT,
    FREE_RUNS_ALLOCATION,
    PLAN_CONFIG,
    _is_successful_run_status,
    get_plan_details,
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


def test_gstin_plan_catalog_v2():
    assert {"free", "solo", "firm", "large_firm"}.issubset(set(PLAN_CONFIG))

    # Free
    fr_yr = get_plan_details("free", "yearly")
    assert fr_yr["gstin_limit"] == 2
    assert fr_yr["base_paise"] == 0

    # Solo
    so_yr = get_plan_details("solo", "yearly")
    assert so_yr["gstin_limit"] == 25
    assert so_yr["period_days"] == 365
    assert so_yr["base_paise"] == 5999_00
    so_mo = get_plan_details("solo", "monthly")
    assert so_mo["gstin_limit"] == 25
    assert so_mo["period_days"] == 30
    assert so_mo["base_paise"] == 799_00

    # Firm
    fi_yr = get_plan_details("firm", "yearly")
    assert fi_yr["gstin_limit"] == 75
    assert fi_yr["base_paise"] == 8999_00
    fi_mo = get_plan_details("firm", "monthly")
    assert fi_mo["gstin_limit"] == 75
    assert fi_mo["base_paise"] == 1499_00

    # Large Firm
    lf_yr = get_plan_details("large_firm", "yearly")
    assert lf_yr["gstin_limit"] == 150
    assert lf_yr["base_paise"] == 11999_00
    lf_mo = get_plan_details("large_firm", "monthly")
    assert lf_mo["gstin_limit"] == 150
    assert lf_mo["base_paise"] == 2499_00


def test_expected_free_runs_after_successful_runs():
    for successful, expected in [(0, 2), (1, 1), (2, 0), (5, 0)]:
        assert (
            max(0, FREE_RUNS_ALLOCATION - min(successful, FREE_RUNS_ALLOCATION))
            == expected
        )
