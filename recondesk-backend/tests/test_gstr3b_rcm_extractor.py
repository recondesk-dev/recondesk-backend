"""Unit tests for GSTR-3B RCM field extractor."""

from __future__ import annotations

import pytest
from app.filing.gstr3b_rcm_extractor import extract_gstr3b_rcm_data


@pytest.fixture
def sandbox_gstr3b_fixture() -> dict:
    """Fixture shaped like Sandbox API get_gstr3b_details() response envelope."""
    return {
        "status_cd": "1",
        "data": {
            "gstin": "27AAACB1234A1Z1",
            "ret_period": "052026",
            "sup_details": {
                "osup_det": {
                    "txval": 100000.00,
                    "iamt": 18000.00,
                    "camt": 0.00,
                    "samt": 0.00,
                    "csamt": 0.00,
                },
                "isup_rev": {
                    "txval": 50000.00,
                    "iamt": 3000.00,
                    "camt": 1500.00,
                    "samt": 1500.00,
                    "csamt": 0.00,
                },
            },
            "itcElg": {
                "itcAvl": [
                    {
                        "ty": "ISRC",
                        "iamt": 3000.00,
                        "camt": 1500.00,
                        "samt": 1500.00,
                        "csamt": 0.00,
                    },
                    {
                        "ty": "IMPS",
                        "iamt": 5000.00,
                        "camt": 0.00,
                        "samt": 0.00,
                        "csamt": 0.00,
                    },
                    {
                        "ty": "OTH",
                        "iamt": 20000.00,
                        "camt": 10000.00,
                        "samt": 10000.00,
                        "csamt": 0.00,
                    },
                ]
            },
        },
    }


def test_extract_gstr3b_rcm_data_full_payload(sandbox_gstr3b_fixture):
    res = extract_gstr3b_rcm_data(sandbox_gstr3b_fixture)
    assert res.gstin == "27AAACB1234A1Z1"
    assert res.period == "2026-05"

    # Table 3.1(d) assertions
    assert res.table_31d_taxable_value_paise == 5000000
    assert res.table_31d_igst_paise == 300000
    assert res.table_31d_cgst_paise == 150000
    assert res.table_31d_sgst_paise == 150000
    assert res.table_31d_cess_paise == 0
    assert res.table_31d_total_tax_paise == 600000

    # Table 4(A)(3) ISRC assertions
    assert res.table_4a3_igst_paise == 300000
    assert res.table_4a3_cgst_paise == 150000
    assert res.table_4a3_sgst_paise == 150000
    assert res.table_4a3_cess_paise == 0
    assert res.table_4a3_total_itc_paise == 600000

    # Table 4(A)(2) IMPS assertions
    assert res.table_4a2_igst_paise == 500000
    assert res.table_4a2_total_itc_paise == 500000
    assert res.total_rcm_itc_claimed_paise == 1100000

    # Cash ledger limitation metadata check
    assert res.cash_ledger_rcm_separable is False
    assert "does not separate RCM challan payments" in res.cash_ledger_note


def test_extract_gstr3b_rcm_data_empty_or_zero_values():
    raw = {
        "gstin": "27AAACB1234A1Z1",
        "ret_period": "2026-06",
        "data": {
            "sup_details": {},
            "itcElg": {"itcAvl": []},
        },
    }
    res = extract_gstr3b_rcm_data(raw)
    assert res.table_31d_taxable_value_paise == 0
    assert res.table_31d_total_tax_paise == 0
    assert res.table_4a3_total_itc_paise == 0
    assert res.table_4a2_total_itc_paise == 0
    assert res.total_rcm_itc_claimed_paise == 0
