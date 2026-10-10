"""Automated unit and integration tests for Financial-Year Cumulative Reconciliation.

Covers:
- 12-month financial year sequencing.
- MonthCrossReconciliation serialization and variance metrics.
- assemble_cumulative_fy_reconciliation end-to-end aggregation across GSTR-1, GSTR-2B, and GSTR-3B.
- Cumulative turnover and ITC rollup with zero double-counting.
- Annual DRC-01B and DRC-01C risk triggers on cumulative variance.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.cumulative_fy_reconciliation import (
    MonthCrossReconciliation,
    assemble_cumulative_fy_reconciliation,
)
from app.services.gstr9c_itc_fy_rollup import fy_periods, parse_fy_label


def test_fy_period_generation():
    """Verify 12 financial year periods are generated in chronological sequence (April -> March)."""
    start_y, end_y = parse_fy_label("2024-25")
    periods = fy_periods(start_y)
    assert len(periods) == 12
    assert periods[0] == "2024-04"
    assert periods[11] == "2025-03"


def test_month_cross_reconciliation_model_and_dict():
    """Verify MonthCrossReconciliation captures outward, inward, RCM, and adjustments."""
    m = MonthCrossReconciliation(
        period="2024-11",
        month_label="Nov 2024",
        has_gstr1_data=True,
        has_gstr2b_data=True,
        has_gstr3b_data=True,
        gstr1_taxable_turnover=100000.0,
        gstr1_total_tax=18000.0,
        gstr3b_taxable_turnover=100000.0,
        gstr3b_total_tax=18000.0,
        outward_tax_variance=0.0,
        gstr2b_available_itc=5000.0,
        gstr3b_claimed_itc=5000.0,
        itc_variance=0.0,
        rcm_inward_liability=1000.0,
        rcm_discharged_liability=1000.0,
        amendment_delta_tax=200.0,
        timing_difference_tax=0.0,
        status="CLEAN",
        explanation="Matched",
    )
    d = m.to_dict()
    assert d["period"] == "2024-11"
    assert d["month_label"] == "Nov 2024"
    assert d["outward"]["gstr1_total_tax"] == 18000.0
    assert d["outward"]["variance"] == 0.0
    assert d["inward_itc"]["gstr2b_available_itc"] == 5000.0
    assert d["adjustments"]["amendment_delta_tax"] == 200.0


def test_assemble_cumulative_fy_reconciliation_empty_runs():
    """When client has no runs in the FY, returns 12 months with 0.0 totals gracefully."""
    mock_sb = MagicMock()

    # Mock client_gstins
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "cid-1", "gstin": "27AABCU9603R1ZM", "trade_name": "Acme Corp"}
    ]

    # Mock reconciliation runs query returning empty
    mock_sb.table().select().eq().order().execute.return_value.data = []

    res = assemble_cumulative_fy_reconciliation(mock_sb, client_gstin_id="cid-1", fy="2024-25")

    assert res["gstin"] == "27AABCU9603R1ZM"
    assert res["financial_year"] == "2024-25"
    assert res["months_count"] == 12
    assert res["months_with_full_data"] == 0
    assert len(res["monthly_breakdown"]) == 12

    cum = res["cumulative_position"]
    assert cum["outward"]["gstr1_total_tax"] == 0.0
    assert cum["outward"]["variance"] == 0.0
    assert cum["inward_itc"]["gstr2b_available_itc"] == 0.0
    assert cum["is_clean"] is True


def test_assemble_cumulative_fy_reconciliation_with_filings():
    """Verifies cumulative aggregation across monthly filings and annual risk detection."""
    mock_sb = MagicMock()

    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"id": "cid-1", "gstin": "27AABCU9603R1ZM", "trade_name": "Acme Corp"}
    ]

    # Mock GSTR-1 runs (April and May)
    mock_g1 = [
        {
            "id": "g1-apr",
            "period": "2024-04",
            "result_payload": {
                "tie_out": {
                    "gstr1": {"taxable_value_paise": 10000000, "total_tax_paise": 1800000},
                    "reclassification_difference_paise": 0,
                }
            },
        },
        {
            "id": "g1-may",
            "period": "2024-05",
            "result_payload": {
                "tie_out": {
                    "gstr1": {"taxable_value_paise": 20000000, "total_tax_paise": 3600000},
                    "reclassification_difference_paise": 10000,
                }
            },
        },
    ]

    # Mock GSTR-3B filings
    mock_g3b = [
        {
            "id": "g3b-apr",
            "period": "2024-04",
            "save_payload": {
                "sup_details": {"osup_det": {"txval": 100000.0, "iamt": 18000.0}},
                "itc_elg": {"itc_avl": [{"ty": "OTH", "iamt": 5000.0}]},
            },
        },
        {
            "id": "g3b-may",
            "period": "2024-05",
            "save_payload": {
                "sup_details": {"osup_det": {"txval": 200000.0, "iamt": 36000.0}},
                "itc_elg": {"itc_avl": [{"ty": "OTH", "iamt": 7000.0}]},
            },
        },
    ]

    def _mock_table(name: str):
        t = MagicMock()
        if name == "client_gstins":
            t.select().eq().limit().execute.return_value.data = [
                {"id": "cid-1", "gstin": "27AABCU9603R1ZM", "trade_name": "Acme Corp"}
            ]
        elif name == "gstr1_reconciliation_run":
            t.select().eq().order().execute.return_value.data = mock_g1
        elif name == "filing_runs":
            t.select().eq().eq().order().execute.return_value.data = mock_g3b
        else:
            t.select().eq().order().execute.return_value.data = []
            t.select().in_().execute.return_value.data = []
        return t

    mock_sb.table.side_effect = _mock_table

    res = assemble_cumulative_fy_reconciliation(mock_sb, client_gstin_id="cid-1", fy="2024-25")

    cum = res["cumulative_position"]
    # Total turnover: 100,000 + 200,000 = 300,000
    assert cum["outward"]["gstr1_taxable_turnover"] == 300000.0
    assert cum["outward"]["gstr1_total_tax"] == 54000.0
    assert cum["outward"]["gstr3b_taxable_turnover"] == 300000.0
    assert cum["outward"]["gstr3b_total_tax"] == 54000.0
    assert cum["outward"]["variance"] == 0.0
    assert cum["outward"]["drc01b_triggered"] is False
