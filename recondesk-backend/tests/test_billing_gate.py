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
    assert so_yr["base_paise"] == 8999_00
    so_mo = get_plan_details("solo", "monthly")
    assert so_mo["gstin_limit"] == 25
    assert so_mo["period_days"] == 30
    assert so_mo["base_paise"] == 899_00

    # Firm
    fi_yr = get_plan_details("firm", "yearly")
    assert fi_yr["gstin_limit"] == 75
    assert fi_yr["base_paise"] == 14999_00
    fi_mo = get_plan_details("firm", "monthly")
    assert fi_mo["gstin_limit"] == 75
    assert fi_mo["base_paise"] == 1499_00

    # Large Firm
    lf_yr = get_plan_details("large_firm", "yearly")
    assert lf_yr["gstin_limit"] == 150
    assert lf_yr["base_paise"] == 18999_00
    lf_mo = get_plan_details("large_firm", "monthly")
    assert lf_mo["gstin_limit"] == 150
    assert lf_mo["base_paise"] == 1899_00


def test_new_pricing_plan_values_and_gst_totals():
    """Assert new Solo, Firm, and Large Firm ex-GST and total amounts incl 18% GST."""
    # Solo: 899/mo (total: 1060.82), 8999/yr (total: 10618.82)
    solo_mo = get_plan_details("solo", "monthly")
    assert solo_mo["base_paise"] == 899_00
    assert solo_mo["gst_paise"] == 161_82
    assert solo_mo["total_paise"] == 1060_82

    solo_yr = get_plan_details("solo", "yearly")
    assert solo_yr["base_paise"] == 8999_00
    assert solo_yr["gst_paise"] == 1619_82
    assert solo_yr["total_paise"] == 10618_82

    # Firm: 1499/mo (total: 1768.82), 14999/yr (total: 17698.82)
    firm_mo = get_plan_details("firm", "monthly")
    assert firm_mo["base_paise"] == 1499_00
    assert firm_mo["gst_paise"] == 269_82
    assert firm_mo["total_paise"] == 1768_82

    firm_yr = get_plan_details("firm", "yearly")
    assert firm_yr["base_paise"] == 14999_00
    assert firm_yr["gst_paise"] == 2699_82
    assert firm_yr["total_paise"] == 17698_82

    # Large Firm: 1899/mo (total: 2240.82), 18999/yr (total: 22418.82)
    lf_mo = get_plan_details("large_firm", "monthly")
    assert lf_mo["base_paise"] == 1899_00
    assert lf_mo["gst_paise"] == 341_82
    assert lf_mo["total_paise"] == 2240_82

    lf_yr = get_plan_details("large_firm", "yearly")
    assert lf_yr["base_paise"] == 18999_00
    assert lf_yr["gst_paise"] == 3419_82
    assert lf_yr["total_paise"] == 22418_82


def test_expected_free_runs_after_successful_runs():
    for successful, expected in [(0, 2), (1, 1), (2, 0), (5, 0)]:
        assert (
            max(0, FREE_RUNS_ALLOCATION - min(successful, FREE_RUNS_ALLOCATION))
            == expected
        )
