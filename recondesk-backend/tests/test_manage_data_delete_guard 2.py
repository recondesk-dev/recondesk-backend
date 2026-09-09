"""Delete guard for manage-data file removal."""

import pytest
from fastapi import HTTPException

from app.routers.manage_data import _assert_run_deletable_for_file_delete


def test_delete_blocked_while_reconciliation_in_progress():
    with pytest.raises(HTTPException) as exc:
        _assert_run_deletable_for_file_delete({"status": "MATCHING"})

    assert exc.value.status_code == 400
    assert exc.value.detail == "Cannot delete file while reconciliation is in progress"


@pytest.mark.parametrize("status", ["uploading", "processing", " matching "])
def test_delete_blocked_for_other_in_progress_statuses(status: str):
    with pytest.raises(HTTPException) as exc:
        _assert_run_deletable_for_file_delete({"status": status})

    assert exc.value.status_code == 400
    assert exc.value.detail == "Cannot delete file while reconciliation is in progress"


def test_delete_allowed_when_run_completed():
    _assert_run_deletable_for_file_delete({"status": "COMPLETED"})


@pytest.mark.parametrize("status", ["complete", "failed", "error"])
def test_delete_allowed_for_other_terminal_statuses(status: str):
    _assert_run_deletable_for_file_delete({"status": status})


def test_delete_blocked_for_unknown_status():
    with pytest.raises(HTTPException) as exc:
        _assert_run_deletable_for_file_delete({"status": "draft"})

    assert exc.value.status_code == 400
    assert exc.value.detail == "Cannot delete file while reconciliation is in progress"
