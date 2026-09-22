"""Unit tests for Post-IMS Action GSTR-2B sync service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.ims_sync_service import (
    _build_status_map_from_submissions,
    _parse_run_period,
    sync_ims_run_overlay,
)


def test_parse_run_period():
    assert _parse_run_period("2024-05") == (2024, 5)
    assert _parse_run_period("112024") == (2024, 11)
    y, m = _parse_run_period("")
    assert y > 2020 and 1 <= m <= 12


def test_build_status_map_from_submissions():
    fake_sb = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_in = MagicMock()
    fake_sb.table.return_value = mock_select
    mock_select.select.return_value = mock_eq
    mock_eq.eq.return_value = mock_in
    mock_in.in_.return_value.execute.return_value.data = [
        {
            "chosen_action": "accept",
            "writeback_payload": {"stin": "27AABCU9603R1ZP", "inum": "INV-101"},
            "status": "confirmed",
        },
        {
            "chosen_action": "reject",
            "writeback_payload": {"stin": "27AABCU9603R1ZP", "inum": "INV-102"},
            "status": "confirmed",
        },
        {
            "chosen_action": "hold",
            "writeback_payload": {"stin": "07AAACR5055K1ZE", "inum": "INV-201"},
            "status": "pending",
        },
    ]

    status_map = _build_status_map_from_submissions(fake_sb, "run-123")
    assert len(status_map) == 3
    assert status_map[("27AABCU9603R1ZP", "INV101")] == "accepted"
    assert status_map[("27AABCU9603R1ZP", "INV102")] == "rejected"
    assert status_map[("07AAACR5055K1ZE", "INV201")] == "pending"


def test_sync_ims_run_overlay_updates_records_and_payload():
    fake_sb = MagicMock()

    # 1. Run row mock
    run_table = MagicMock()
    run_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {
            "id": "run-test-1",
            "client_gstin_id": "cgid-1",
            "period": "2024-03",
            "status": "COMPLETED",
        }
    ]

    # 2. Submissions mock
    sub_table = MagicMock()
    sub_table.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
        {
            "chosen_action": "accept",
            "writeback_payload": {"stin": "27AABCU9603R1ZP", "inum": "INV-001"},
            "status": "confirmed",
        }
    ]

    # 3. GSTR records mock
    gstr_table = MagicMock()
    gstr_table.select.return_value.eq.return_value.range.return_value.execute.return_value.data = [
        {
            "id": "g-1",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZP",
                "invoice_number": "INV-001",
                "ims_status": "no_action_taken",
            },
        }
    ]

    def table_router(name: str):
        if name == "reconciliation_run":
            return run_table
        if name == "ims_action_submissions":
            return sub_table
        if name == "gstr_records":
            return gstr_table
        m = MagicMock()
        m.select.return_value.eq.return_value.execute.return_value.data = []
        return m

    fake_sb.table.side_effect = table_router

    mock_payload = {
        "engine": {
            "matched": [
                {
                    "gstr_id": "g-1",
                    "supplier_gstin": "27AABCU9603R1ZP",
                    "invoice_number": "INV-001",
                    "ims_status": "no_action_taken",
                }
            ],
            "missed_itc": [],
            "duplicates": [],
        },
        "decisions": {
            "rows": [
                {
                    "supplier_gstin": "27AABCU9603R1ZP",
                    "invoice_number": "INV-001",
                    "ims_status": "no_action_taken",
                }
            ]
        },
    }

    with (
        patch("app.services.ims_sync_service.try_fetch_ims_status_map_for_client", return_value=None),
        patch("app.services.ims_sync_service.load_payload", return_value=mock_payload),
        patch("app.services.ims_sync_service.save_reconciliation_results") as mock_save,
        patch("app.services.ims_sync_service.clear_process_maps_for_run") as mock_clear_proc,
        patch("app.services.ims_sync_service.clear_request_load_cache") as mock_clear_req,
    ):
        result = sync_ims_run_overlay(fake_sb, run_id="run-test-1")

        assert result.synced is True
        assert result.phase4_post_action_2b_sync_pending is False
        assert result.invoices_updated >= 1

        # Check in-memory payload was updated
        assert mock_payload["engine"]["matched"][0]["ims_status"] == "accepted"
        assert mock_payload["decisions"]["rows"][0]["ims_status"] == "accepted"

        # Check save and cache invalidations were called
        mock_save.assert_called_once()
        mock_clear_proc.assert_called_once_with("run-test-1")
        mock_clear_req.assert_called_once()


def test_sync_ims_run_overlay_missing_run_raises():
    fake_sb = MagicMock()
    fake_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    with pytest.raises(ValueError, match="not found"):
        sync_ims_run_overlay(fake_sb, run_id="nonexistent-run")


def test_sync_ims_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    mock_user = {"id": "user-1", "email": "ca@example.com"}
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_sync_result = MagicMock()
    mock_sync_result.as_dict.return_value = {
        "synced": True,
        "run_id": "run-test-1",
        "invoices_updated": 5,
        "phase4_post_action_2b_sync_pending": False,
        "message": "Synchronized 5 invoice(s) with GSTR-2B & IMS overlay.",
    }

    with (
        patch("app.routers.ims_actions.get_supabase"),
        patch("app.routers.ims_actions.assert_run_accessible", return_value={"id": "run-test-1"}),
        patch("app.routers.ims_actions.sync_ims_run_overlay", return_value=mock_sync_result),
    ):
        client = TestClient(app)
        res = client.post("/api/reconcile/runs/run-test-1/ims/sync")
        assert res.status_code == 200
        data = res.json()
        assert data["synced"] is True
        assert data["invoices_updated"] == 5
        assert data["phase4_post_action_2b_sync_pending"] is False

    app.dependency_overrides.clear()

