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


def test_free_gstin_limit_is_one():
    assert FREE_GSTIN_LIMIT == 1


def test_gstin_plan_catalog_v2():
    assert {"starter", "growth", "pro", "firm"}.issubset(set(PLAN_CONFIG))
    # Starter
    st_yr = get_plan_details("starter", "yearly")
    assert st_yr["gstin_limit"] == 25
    assert st_yr["period_days"] == 365
    assert st_yr["base_paise"] == 7999_00
    st_mo = get_plan_details("starter", "monthly")
    assert st_mo["gstin_limit"] == 25
    assert st_mo["period_days"] == 30
    assert st_mo["base_paise"] == 1199_00

    # Growth
    gr_yr = get_plan_details("growth", "yearly")
    assert gr_yr["gstin_limit"] == 60
    assert gr_yr["base_paise"] == 12999_00
    gr_mo = get_plan_details("growth", "monthly")
    assert gr_mo["gstin_limit"] == 60
    assert gr_mo["base_paise"] == 1799_00

    # Pro
    pro_yr = get_plan_details("pro", "yearly")
    assert pro_yr["gstin_limit"] == 100
    assert pro_yr["base_paise"] == 17999_00
    pro_mo = get_plan_details("pro", "monthly")
    assert pro_mo["gstin_limit"] == 100
    assert pro_mo["base_paise"] == 2399_00

    # Firm base and overage
    firm_yr = get_plan_details("firm", "yearly", total_gstins=120)
    assert firm_yr["gstin_limit"] == 120
    assert firm_yr["overage_gstins"] == 20
    assert firm_yr["base_paise"] == 17999_00 + 20 * 200_00

    firm_mo = get_plan_details("firm", "monthly", total_gstins=110)
    assert firm_mo["gstin_limit"] == 110
    assert firm_mo["overage_gstins"] == 10
    assert firm_mo["base_paise"] == 2399_00 + 10 * 25_00


def test_expected_free_runs_after_successful_runs():
    for successful, expected in [(0, 2), (1, 1), (2, 0), (5, 0)]:
        assert (
            max(0, FREE_RUNS_ALLOCATION - min(successful, FREE_RUNS_ALLOCATION))
            == expected
        )
