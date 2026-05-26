"""Billing credit sync helpers."""

from app.services.billing_gate import (
    FREE_RUNS_ALLOCATION,
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


def test_expected_free_runs_after_successful_runs():
    for successful, expected in [(0, 2), (1, 1), (2, 0), (5, 0)]:
        assert (
            max(0, FREE_RUNS_ALLOCATION - min(successful, FREE_RUNS_ALLOCATION))
            == expected
        )
