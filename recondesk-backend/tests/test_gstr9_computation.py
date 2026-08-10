"""Unit tests for GSTR-9 & GSTR-9C computation engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.gstr9_computation import build_gstr9_portal_json, compute_gstr9
from app.services.gstr9c_computation import build_gstr9c_portal_json, compute_gstr9c


@patch("app.services.gstr9_computation.build_gstr9c_itc_fy_rollup")
def test_compute_gstr9(mock_rollup):
    """Test GSTR-9 Table 4-9 system computation."""
    mock_sb = MagicMock()

    # Mock client row
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "client-123", "gstin": "27AAAAA0000A1Z5", "trade_name": "Test Trader"}
    ]
    # Mock overrides query (empty)
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_rollup.return_value = {
        "totals": {
            "matched_itc_rupees": 500000.0,
            "claimed_itc_rupees": 480000.0,
        }
    }

    res = compute_gstr9(mock_sb, "client-123", "2025-26")

    assert res["gstin"] == "27AAAAA0000A1Z5"
    assert res["financial_year"] == "2025-26"
    assert "table4" in res
    assert "table6" in res
    assert "table8" in res
    assert res["table6"]["6A_total_3b_itc"] == 480000.0
    assert res["table8"]["8A_itc_2b"] == 500000.0

    # Test portal JSON builder
    portal_json = build_gstr9_portal_json(mock_sb, "client-123", "2025-26")
    assert portal_json["gstin"] == "27AAAAA0000A1Z5"
    assert portal_json["fp"] == "202526"


@patch("app.services.gstr9c_computation.compute_gstr9")
def test_compute_gstr9c(mock_g9):
    """Test GSTR-9C reconciliation statement computation."""
    mock_sb = MagicMock()

    mock_g9.return_value = {
        "gstin": "27AAAAA0000A1Z5",
        "trade_name": "Test Trader",
        "table4": {"4N_total_taxable": 5000000.0},
        "table5": {"5N_total_exempted": 500000.0},
        "table6": {"6A_total_3b_itc": 480000.0},
        "table7": {"7H_total_reversals": 10000.0},
        "table9": {
            "igst_cash": 100000.0, "cgst_cash": 50000.0, "sgst_cash": 50000.0,
            "igst_itc": 200000.0, "cgst_itc": 50000.0, "sgst_itc": 50000.0,
        },
    }

    res = compute_gstr9c(
        mock_sb,
        "client-123",
        "2025-26",
        audited_turnover=5600000.0,
        audited_itc=475000.0,
        audited_tax=500000.0,
    )

    assert res["gstin"] == "27AAAAA0000A1Z5"
    assert res["part_ii_turnover"]["5R_unreconciled_turnover_variance"] == 100000.0
    assert res["part_iii_itc"]["12G_unreconciled_itc_variance"] == 5000.0

    portal_json = build_gstr9c_portal_json(mock_sb, "client-123", "2025-26", 5600000.0, 475000.0, 500000.0)
    assert portal_json["fp"] == "202526"
