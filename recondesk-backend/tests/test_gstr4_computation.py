"""Unit tests for GSTR-4 Composition Scheme Annual Return computation engine."""

import pytest
from unittest.mock import MagicMock
from app.services.gstr4_computation import (
    parse_fy_label,
    fy_periods,
    compute_gstr4,
    build_gstr4_gstn_json,
    load_gstr4_cmp08_records,
    COMPOSITION_RATES,
)


def test_parse_fy_label():
    start, end = parse_fy_label("2025-26")
    assert start == 2025
    assert end == 2026

    start, end = parse_fy_label("2024-25")
    assert start == 2024
    assert end == 2025

    with pytest.raises(ValueError):
        parse_fy_label("202526")


def test_fy_periods():
    periods = fy_periods(2025)
    assert len(periods) == 12
    assert periods[0] == "202504"
    assert periods[11] == "202603"


def test_compute_gstr4_trader_rate():
    mock_sb = MagicMock()
    # Mock empty returns for queries
    mock_sb.table().select().eq().execute.return_value.data = []
    mock_sb.table().select().eq().eq().execute.return_value.data = []
    mock_sb.table().select().eq().in_().execute.return_value.data = []

    comp = compute_gstr4(mock_sb, "11111111-1111-1111-1111-111111111111", "2025-26", "trader")
    assert comp["composition_category"] == "trader"
    table6 = comp["tables"]["table6"]
    assert table6["rate_percentages"]["total_rate"] == 1.0
    assert table6["rate_percentages"]["cgst_rate"] == 0.5
    assert table6["rate_percentages"]["sgst_rate"] == 0.5


def test_compute_gstr4_restaurant_rate():
    mock_sb = MagicMock()
    mock_sb.table().select().eq().execute.return_value.data = []
    mock_sb.table().select().eq().eq().execute.return_value.data = []
    mock_sb.table().select().eq().in_().execute.return_value.data = []

    comp = compute_gstr4(mock_sb, "11111111-1111-1111-1111-111111111111", "2025-26", "restaurant")
    assert comp["composition_category"] == "restaurant"
    table6 = comp["tables"]["table6"]
    assert table6["rate_percentages"]["total_rate"] == 5.0
    assert table6["rate_percentages"]["cgst_rate"] == 2.5
    assert table6["rate_percentages"]["sgst_rate"] == 2.5


def test_compute_gstr4_cmp08_aggregation_and_liability():
    mock_sb = MagicMock()
    # Mock CMP-08 records for Q1..Q4
    cmp08_data = [
        {"quarter": "Q1", "outward_taxable": 250000.0, "outward_tax": 2500.0, "rcm_taxable": 10000.0, "rcm_tax": 500.0, "igst": 0.0, "cgst": 1500.0, "sgst": 1500.0, "cess": 0.0, "interest": 0.0, "late_fee": 0.0},
        {"quarter": "Q2", "outward_taxable": 300000.0, "outward_tax": 3000.0, "rcm_taxable": 0.0, "rcm_tax": 0.0, "igst": 0.0, "cgst": 1500.0, "sgst": 1500.0, "cess": 0.0, "interest": 0.0, "late_fee": 0.0},
        {"quarter": "Q3", "outward_taxable": 200000.0, "outward_tax": 2000.0, "rcm_taxable": 0.0, "rcm_tax": 0.0, "igst": 0.0, "cgst": 1000.0, "sgst": 1000.0, "cess": 0.0, "interest": 0.0, "late_fee": 0.0},
        {"quarter": "Q4", "outward_taxable": 250000.0, "outward_tax": 2500.0, "rcm_taxable": 0.0, "rcm_tax": 0.0, "igst": 0.0, "cgst": 1250.0, "sgst": 1250.0, "cess": 0.0, "interest": 0.0, "late_fee": 0.0},
    ]

    def mock_table(table_name):
        query_mock = MagicMock()
        if table_name == "gstr4_cmp08_records":
            query_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = cmp08_data
        else:
            query_mock.select.return_value.eq.return_value.execute.return_value.data = []
            query_mock.select.return_value.eq.return_value.in_().execute.return_value.data = []
        return query_mock

    mock_sb.table.side_effect = mock_table

    comp = compute_gstr4(mock_sb, "11111111-1111-1111-1111-111111111111", "2025-26", "trader")
    t5 = comp["tables"]["table5"]
    assert t5["outward_taxable"]["effective_value"] == 1000000.0
    assert t5["outward_tax"]["effective_value"] == 10000.0

    t6 = comp["tables"]["table6"]
    # 1% of 1,000,000 = 10,000 (5,000 CGST + 5,000 SGST)
    assert t6["outward_supplies"]["cgst"]["effective_value"] == 5000.0
    assert t6["outward_supplies"]["sgst"]["effective_value"] == 5000.0
    assert t6["outward_supplies"]["tax_total"]["effective_value"] == 10000.0


def test_compute_gstr4_ca_overrides():
    mock_sb = MagicMock()
    override_data = [
        {
            "table_key": "table5",
            "cell_key": "outward_taxable",
            "system_value": 1000000.0,
            "override_value": 1200000.0,
            "notes": "Added unrecorded cash sales",
        }
    ]

    def mock_table(table_name):
        query_mock = MagicMock()
        if table_name == "gstr4_audit_overrides":
            query_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = override_data
        else:
            query_mock.select.return_value.eq.return_value.execute.return_value.data = []
            query_mock.select.return_value.eq.return_value.in_().execute.return_value.data = []
        return query_mock

    mock_sb.table.side_effect = mock_table

    comp = compute_gstr4(mock_sb, "11111111-1111-1111-1111-111111111111", "2025-26", "trader")
    t5_outward = comp["tables"]["table5"]["outward_taxable"]
    assert t5_outward["is_overridden"] is True
    assert t5_outward["effective_value"] == 1200000.0
    assert t5_outward["notes"] == "Added unrecorded cash sales"


def test_build_gstr4_gstn_json():
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {"gstin": "27AAACG1234F1Z5", "legal_name": "Acme Traders", "trade_name": "Acme"}
    ]
    mock_sb.table().select().eq().eq().execute.return_value.data = []
    mock_sb.table().select().eq().in_().execute.return_value.data = []

    gstn_json = build_gstr4_gstn_json(mock_sb, "11111111-1111-1111-1111-111111111111", "2025-26", "trader")
    assert gstn_json["gstin"] == "27AAACG1234F1Z5"
    assert gstn_json["fy"] == "2025-26"
    assert "table4" in gstn_json
    assert "table5" in gstn_json
    assert "table6" in gstn_json
    assert "table8" in gstn_json
