"""Unit tests for multi-period annual reconciliation Excel export."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from openpyxl import load_workbook

from app.services.multi_period_export import build_multi_period_excel_export


@patch("app.services.multi_period_export.build_gstr9c_itc_fy_rollup")
@patch("app.services.multi_period_export.get_batch_with_items")
def test_build_multi_period_excel_export(mock_get_batch, mock_get_rollup):
    """Test generating a multi-sheet XLSX export for a 12-month batch."""
    mock_sb = MagicMock()

    batch_data = {
        "id": "batch-123",
        "client_gstin_id": "client-456",
        "financial_year": "2025-26",
        "status": "completed",
        "items": [
            {
                "id": "item-1",
                "period": "2025-04",
                "gstr2b_source": "auto_fetch",
                "pr_source": "tally_bridge_existing",
                "status": "completed",
                "reconciliation_run_id": "run-001",
                "gstr2b_file_path": "path/2b",
                "pr_file_path": "path/pr",
                "error_message": None,
            },
            {
                "id": "item-2",
                "period": "2025-05",
                "gstr2b_source": "manual_upload",
                "pr_source": "manual_upload",
                "status": "completed",
                "reconciliation_run_id": "run-002",
                "gstr2b_file_path": "path/2b2",
                "pr_file_path": "path/pr2",
                "error_message": None,
            },
        ],
    }

    rollup_data = {
        "total_gstr_itc_paise": 15000000,
        "matched_itc_paise": 12000000,
        "missed_itc_paise": 2000000,
        "wrongful_risk_paise": 1000000,
    }

    mock_get_batch.return_value = batch_data
    mock_get_rollup.return_value = rollup_data

    excel_bytes = build_multi_period_excel_export(mock_sb, "batch-123")

    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 0

    wb = load_workbook(io.BytesIO(excel_bytes))
    assert "FY Summary Rollup" in wb.sheetnames
    assert "Monthly Batch Items" in wb.sheetnames

    ws1 = wb["FY Summary Rollup"]
    assert "RECONDESK — FY 2025-26 ANNUAL RECONCILIATION ROLLUP" in str(ws1["A1"].value)
