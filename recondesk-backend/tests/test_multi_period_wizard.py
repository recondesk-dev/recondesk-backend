"""
test_multi_period_wizard.py
Unit & integration tests for multi-period reconciliation wizard service and router.
Run: PYTHONPATH=. pytest tests/test_multi_period_wizard.py -v
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, call, patch
import pytest

from app.integrations.gstr2b_autofetch import SandboxGstnError
from app.services.gstr9c_itc_fy_rollup import parse_fy_label, fy_periods
from app.services.multi_period_wizard import (
    attach_manual_pr,
    check_pr_availability,
    fetch_gstr2b_for_batch,
    run_batch,
)


class TestMultiPeriodWizardHelpers:
    def test_fy_parsing_for_12_months(self):
        start_year, end_year = parse_fy_label("2025-26")
        assert start_year == 2025
        assert end_year == 2026

        periods = fy_periods(2025)
        assert len(periods) == 12
        assert periods[0] == "2025-04"
        assert periods[-1] == "2026-03"

    def test_check_pr_availability_tally_sync(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "id": "run-123",
                    "status": "COMPLETED",
                    "r2_key": "uploads/client-1/2025-04/tally_pr_12345.xlsx",
                    "pr_r2_key": "uploads/client-1/2025-04/tally_pr_12345.xlsx",
                    "file_type": "purchase_register",
                    "pr_records_imported": 150,
                }
            ]
        )

        res = check_pr_availability(mock_sb, "client-1", "2025-04")
        assert res["pr_source"] == "tally_bridge_existing"
        assert res["reconciliation_run_id"] == "run-123"

    def test_check_pr_availability_missing(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        res = check_pr_availability(mock_sb, "client-1", "2025-05")
        assert res["pr_source"] == "missing"
        assert res["pr_file_path"] is None
        assert res["reconciliation_run_id"] is None


class TestMultiPeriodWizardExecution:
    @patch("app.services.multi_period_wizard.get_supabase")
    @patch("app.services.multi_period_wizard.get_batch_with_items")
    @patch("app.services.multi_period_wizard.execute_reconciliation")
    @patch("app.services.multi_period_wizard.run_import_job")
    def test_sequential_execution_order_preserved_across_periods(
        self, mock_import_job, mock_execute_recon, mock_get_batch, mock_get_sb
    ):
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb

        # Unsorted items
        items = [
            {"id": "i3", "period": "2025-06", "gstr2b_file_path": "g3.json", "pr_file_path": "p3.xlsx", "pr_source": "manual_upload"},
            {"id": "i1", "period": "2025-04", "gstr2b_file_path": "g1.json", "pr_file_path": "p1.xlsx", "pr_source": "tally_bridge_existing"},
            {"id": "i2", "period": "2025-05", "gstr2b_file_path": "g2.json", "pr_file_path": "p2.xlsx", "pr_source": "already_uploaded"},
        ]
        mock_get_batch.return_value = {
            "id": "batch-1",
            "client_gstin_id": "client-1",
            "financial_year": "2025-26",
            "items": items,
        }

        executed_order = []

        def track_recon_execution(args):
            executed_order.append(args[0])

        mock_execute_recon.apply.side_effect = track_recon_execution

        run_batch("batch-1")

        # Verify that all 3 periods were executed sequentially
        assert len(executed_order) == 3

        # Verify batch final status updated to completed
        mock_sb.table.return_value.update.assert_any_call({"status": "running", "updated_at": ANY})
        mock_sb.table.return_value.update.assert_any_call({"status": "completed", "updated_at": ANY})

    @patch("app.services.multi_period_wizard.get_supabase")
    @patch("app.services.multi_period_wizard.get_batch_with_items")
    @patch("app.services.multi_period_wizard._load_client_gstin")
    @patch("app.services.multi_period_wizard._assert_gstn_token_fresh")
    @patch("app.services.multi_period_wizard.get_gstr2b")
    @patch("app.services.multi_period_wizard._gstr2b_payload_for_parser")
    @patch("app.services.multi_period_wizard.parse_gstr2b")
    @patch("app.services.multi_period_wizard.upload_file_to_r2")
    def test_one_period_fetch_failure_does_not_abort_others(
        self,
        mock_r2,
        mock_parse,
        mock_payload_parser,
        mock_get_2b,
        mock_fresh_token,
        mock_client_gstin,
        mock_get_batch,
        mock_get_sb,
    ):
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_client_gstin.return_value = {"gstin": "27AAABC1234D1Z5", "gstn_access_token": "token123"}

        items = [
            {"id": "item-1", "period": "2025-04", "status": "pending"},
            {"id": "item-2", "period": "2025-05", "status": "pending"},
            {"id": "item-3", "period": "2025-06", "status": "pending"},
        ]
        mock_get_batch.return_value = {
            "id": "batch-1",
            "client_gstin_id": "client-1",
            "items": items,
        }

        # Item 1 succeeds, Item 2 fails with SandboxGstnError, Item 3 succeeds
        def get_2b_side_effect(token, gstin, year, month):
            if month == 5:
                raise SandboxGstnError("GSTR-2B not yet filed for this period", "RET2B1023")
            return {"data": {}}

        mock_get_2b.side_effect = get_2b_side_effect
        mock_payload_parser.return_value = {"b2b": []}

        fetch_gstr2b_for_batch("batch-1")

        # Verify get_gstr2b was called for all 3 periods despite month 5 failure
        assert mock_get_2b.call_count == 3

    @patch("app.services.multi_period_wizard.get_supabase")
    @patch("app.services.multi_period_wizard.get_batch_with_items")
    @patch("app.services.multi_period_wizard._load_client_gstin")
    @patch("app.services.multi_period_wizard._assert_gstn_token_fresh")
    @patch("app.services.multi_period_wizard.get_gstr2b")
    @patch("app.services.multi_period_wizard._gstr2b_payload_for_parser")
    @patch("app.services.multi_period_wizard.parse_gstr2b")
    @patch("app.services.multi_period_wizard.upload_file_to_r2")
    def test_batch_correctly_marked_partially_failed_when_some_periods_fail(
        self,
        mock_r2,
        mock_parse,
        mock_payload_parser,
        mock_get_2b,
        mock_fresh_token,
        mock_client_gstin,
        mock_get_batch,
        mock_get_sb,
    ):
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_client_gstin.return_value = {"gstin": "27AAABC1234D1Z5", "gstn_access_token": "token123"}

        items = [
            {"id": "item-1", "period": "2025-04", "status": "pending"},
            {"id": "item-2", "period": "2025-05", "status": "pending"},
        ]
        mock_get_batch.return_value = {
            "id": "batch-1",
            "client_gstin_id": "client-1",
            "items": items,
        }

        # Item 1 succeeds, Item 2 fails
        mock_get_2b.side_effect = [
            {"data": {}},
            SandboxGstnError("OTP Session Expired"),
        ]
        mock_payload_parser.return_value = {"b2b": []}

        fetch_gstr2b_for_batch("batch-1")

        # Batch final status should be set to "partially_failed"
        mock_sb.table("multi_period_recon_batches").update.assert_any_call({
            "status": "partially_failed",
            "updated_at": ANY,
        })

    @patch("app.services.multi_period_wizard.get_supabase")
    @patch("app.services.multi_period_wizard.get_batch_with_items")
    @patch("app.services.multi_period_wizard._load_client_gstin")
    @patch("app.services.multi_period_wizard._assert_gstn_token_fresh")
    @patch("app.services.multi_period_wizard.get_gstr2b")
    def test_batch_marked_failed_when_all_periods_fail(
        self,
        mock_get_2b,
        mock_fresh_token,
        mock_client_gstin,
        mock_get_batch,
        mock_get_sb,
    ):
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_client_gstin.return_value = {"gstin": "27AAABC1234D1Z5", "gstn_access_token": "token123"}

        items = [
            {"id": "item-1", "period": "2025-04", "status": "pending"},
            {"id": "item-2", "period": "2025-05", "status": "pending"},
        ]
        mock_get_batch.return_value = {
            "id": "batch-1",
            "client_gstin_id": "client-1",
            "items": items,
        }

        # Both items fail
        mock_get_2b.side_effect = SandboxGstnError("OTP Session Expired")

        fetch_gstr2b_for_batch("batch-1")

        # Batch final status should be set to "failed" when 0 completed
        mock_sb.table("multi_period_recon_batches").update.assert_any_call({
            "status": "failed",
            "updated_at": ANY,
        })

    @patch("app.services.multi_period_wizard.get_supabase")
    @patch("app.services.multi_period_wizard.get_batch_with_items")
    def test_pr_missing_in_run_batch_marked_failed_with_clear_message(
        self, mock_get_batch, mock_get_sb
    ):
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb

        items = [
            {
                "id": "item-1",
                "period": "2025-04",
                "gstr2b_file_path": "gstr2b_2025-04.json",
                "pr_file_path": None,
                "pr_source": "missing",
            }
        ]
        mock_get_batch.return_value = {
            "id": "batch-1",
            "client_gstin_id": "client-1",
            "items": items,
        }

        run_batch("batch-1")

        # Confirm item status updated to "failed" with explicit error_message
        mock_sb.table("multi_period_recon_batch_items").update.assert_any_call({
            "status": "failed",
            "error_message": "Missing GSTR-2B or Purchase Register file",
            "updated_at": ANY,
        })

    @patch("app.services.multi_period_wizard.get_batch_with_items")
    @patch("app.services.multi_period_wizard.parse_purchase_register")
    @patch("app.services.multi_period_wizard.upload_file_to_r2")
    def test_pr_missing_fallback_triggers_manual_upload_path(
        self, mock_r2_upload, mock_parse_pr, mock_get_batch
    ):
        mock_sb = MagicMock()
        mock_get_batch.return_value = {
            "id": "batch-1",
            "client_gstin_id": "client-1",
            "items": [{"period": "2025-05", "pr_source": "missing"}],
        }
        mock_r2_upload.return_value = "https://r2/multi-period/client-1/batch-1/manual_pr_2025-05.xlsx"

        file_bytes = b"dummy_excel_content"
        filename = "may2025_pr.xlsx"

        attach_manual_pr(mock_sb, "batch-1", "2025-05", file_bytes, filename)

        # Confirm PR parser validated file
        mock_parse_pr.assert_called_once_with(file_bytes, filename)

        # Confirm item updated with manual_upload source and R2 path
        mock_sb.table("multi_period_recon_batch_items").update.assert_called_once()
        update_args = mock_sb.table("multi_period_recon_batch_items").update.call_args[0][0]
        assert update_args["pr_source"] == "manual_upload"
        assert "manual_pr_2025-05.xlsx" in update_args["pr_file_path"]
