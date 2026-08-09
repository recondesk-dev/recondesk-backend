"""Unit tests for GET /api/reconcile/runs/{run_id}/rcm-tie-out API endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

RUN_ID = "00000000-0000-0000-0000-000000000099"


def test_rcm_tie_out_api_unauthorized(client: TestClient):
    """Unauthenticated requests must be rejected with 401."""
    res = client.get(f"/api/reconcile/runs/{RUN_ID}/rcm-tie-out")
    assert res.status_code == 401


@patch("app.routers.reconciliation_api.assert_run_accessible")
@patch("app.routers.reconciliation_api.get_supabase")
@patch("app.routers.reconciliation_api.ro.load_pr_map")
@patch("app.routers.reconciliation_api.ro.load_payload")
def test_rcm_tie_out_api_success(
    mock_load_payload: MagicMock,
    mock_load_pr_map: MagicMock,
    mock_get_supabase: MagicMock,
    mock_assert_accessible: MagicMock,
    client: TestClient,
    auth_headers: dict,
):
    """Authenticated request returns structured RCM 3-way tie-out response."""
    mock_assert_accessible.return_value = {
        "id": RUN_ID,
        "client_gstin": "27AAACB1234A1Z1",
        "period": "2026-05",
    }

    mock_load_pr_map.return_value = {
        "pr-1": {
            "invoice_number": "GTA-001",
            "supplier_gstin": "27BBBCB5678B1Z2",
            "sac": "9965",
            "taxable_amount_paise": 1000000,
            "igst_paise": 50000,
            "ledger_name": "Freight Charges",
        }
    }

    mock_load_payload.return_value = {
        "gstr3b": {
            "gstin": "27AAACB1234A1Z1",
            "ret_period": "052026",
            "sup_details": {
                "isup_rev": {
                    "txval": 10000.0,
                    "iamt": 500.0,
                    "camt": 0.0,
                    "samt": 0.0,
                    "csamt": 0.0,
                }
            },
            "itcElg": {
                "itcAvl": [
                    {"ty": "ISRC", "iamt": 500.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
                ]
            },
        }
    }

    mock_sb = MagicMock()
    # Return empty data for gstr3b_reconciliation table query so it falls back to load_payload
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_order = MagicMock()
    mock_limit = MagicMock()
    mock_limit.execute.return_value = MagicMock(data=[])
    mock_order.limit.return_value = mock_limit
    mock_eq.order.return_value = mock_order
    mock_select.eq.return_value = mock_eq
    mock_table.select.return_value = mock_select
    mock_sb.table.return_value = mock_table
    mock_get_supabase.return_value = mock_sb

    res = client.get(
        f"/api/reconcile/runs/{RUN_ID}/rcm-tie-out",
        headers=auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["gstin"] == "27AAACB1234A1Z1"
    assert data["ret_period"] == "2026-05"
    assert "is_clean" in data
    assert "summary_by_reason" in data
    assert "pr_summary" in data
    assert "gstr3b_summary" in data
    assert "flagged_rows" in data
    assert len(data["flagged_rows"]) == 1
    assert data["flagged_rows"][0]["invoice_number"] == "GTA-001"
