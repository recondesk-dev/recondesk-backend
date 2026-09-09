"""Unit tests for RCM 3-way tie-out engine."""

from __future__ import annotations

import pytest
from app.filing.gstr3b_rcm_extractor import GSTR3BRCMData
from app.reconciliation.rcm_reconciliation import (
    REASON_RCM_ITC_BEFORE_PAYMENT,
    REASON_RCM_ITC_NOT_CLAIMED,
    REASON_RCM_TIMING_MISMATCH,
    REASON_RCM_UNDERPAID,
    reconcile_rcm_three_way,
)


def test_rcm_tie_out_clean_case():
    """Clean case where PR RCM, 3B 3.1(d) paid, and 3B 4(A)(3) claimed match perfectly."""
    pr_records = [
        {
            "invoice_number": "GTA-001",
            "supplier_gstin": "27AAACB1234A1Z1",
            "sac": "9965",
            "taxable_amount_paise": 1000000,
            "igst_paise": 50000,
        }
    ]
    g3b_data = GSTR3BRCMData(
        gstin="27AAACB1234A1Z1",
        period="2026-05",
        table_31d_taxable_value_paise=1000000,
        table_31d_igst_paise=50000,
        table_4a3_igst_paise=50000,
    )
    res = reconcile_rcm_three_way(pr_records=pr_records, gstr3b_rcm_data=g3b_data)

    assert res.is_clean is True
    assert len(res.variances) == 0
    assert len(res.mismatches) == 0
    assert res.pr_rcm_tax_paise == 50000
    assert res.gstr3b_31d_tax_paise == 50000
    assert res.total_gstr3b_rcm_itc_paise == 50000


def test_rcm_tie_out_reason_rcm_underpaid():
    """PR detects ₹1,000 RCM tax, but 3B 3.1(d) declares/pays only ₹200."""
    pr_records = [
        {
            "invoice_number": "LEG-100",
            "supplier_gstin": "27BBBCB5678B1Z2",
            "sac": "9982",
            "taxable_amount_paise": 2000000,
            "cgst_paise": 50000,
            "sgst_paise": 50000,  # Total ₹1,000 tax (100,000 paise)
        }
    ]
    g3b_data = GSTR3BRCMData(
        gstin="27AAACB1234A1Z1",
        period="2026-05",
        table_31d_taxable_value_paise=400000,
        table_31d_cgst_paise=10000,
        table_31d_sgst_paise=10000,  # Total ₹200 tax (20,000 paise)
        table_4a3_cgst_paise=10000,
        table_4a3_sgst_paise=10000,
    )
    res = reconcile_rcm_three_way(pr_records=pr_records, gstr3b_rcm_data=g3b_data)

    assert res.is_clean is False
    assert res.summary_by_reason[REASON_RCM_UNDERPAID] == 1
    underpaid_vars = [v for v in res.variances if v.reason_code == REASON_RCM_UNDERPAID]
    assert len(underpaid_vars) == 1
    assert underpaid_vars[0].diff_paise == 80000  # ₹800 shortfall


def test_rcm_tie_out_reason_rcm_itc_before_payment():
    """3B 4(A)(3) claims ₹1,500 RCM ITC, but 3B 3.1(d) paid only ₹500 and cumulative paid is ₹500."""
    pr_records = []
    g3b_data = GSTR3BRCMData(
        gstin="27AAACB1234A1Z1",
        period="2026-05",
        table_31d_taxable_value_paise=1000000,
        table_31d_igst_paise=50000,  # ₹500
        table_4a3_igst_paise=150000,  # ₹1,500 claimed
    )
    res = reconcile_rcm_three_way(
        pr_records=pr_records,
        gstr3b_rcm_data=g3b_data,
        cumulative_31d_paid_to_date_paise=50000,
    )

    assert res.is_clean is False
    assert res.summary_by_reason[REASON_RCM_ITC_BEFORE_PAYMENT] == 1
    vars_found = [v for v in res.variances if v.reason_code == REASON_RCM_ITC_BEFORE_PAYMENT]
    assert len(vars_found) == 1
    assert vars_found[0].diff_paise == 100000  # ₹1,000 excess claim


def test_rcm_tie_out_reason_rcm_itc_not_claimed():
    """3B 3.1(d) pays ₹2,000 RCM tax, but 0 RCM ITC is claimed in Table 4(A)."""
    pr_records = []
    g3b_data = GSTR3BRCMData(
        gstin="27AAACB1234A1Z1",
        period="2026-05",
        table_31d_taxable_value_paise=4000000,
        table_31d_igst_paise=200000,  # ₹2,000
        table_4a3_igst_paise=0,
    )
    res = reconcile_rcm_three_way(pr_records=pr_records, gstr3b_rcm_data=g3b_data)

    assert res.is_clean is False
    assert res.summary_by_reason[REASON_RCM_ITC_NOT_CLAIMED] == 1
    unclaimed_vars = [v for v in res.variances if v.reason_code == REASON_RCM_ITC_NOT_CLAIMED]
    assert len(unclaimed_vars) == 1
    assert unclaimed_vars[0].diff_paise == 200000


def test_rcm_tie_out_reason_rcm_timing_mismatch():
    """3B 3.1(d) pays ₹3,000, 3B 4(A)(3) claims ₹1,000 in current period, but cumulative paid to date is ₹3,000."""
    pr_records = []
    g3b_data = GSTR3BRCMData(
        gstin="27AAACB1234A1Z1",
        period="2026-05",
        table_31d_taxable_value_paise=6000000,
        table_31d_igst_paise=300000,  # ₹3,000
        table_4a3_igst_paise=100000,  # ₹1,000
    )
    res = reconcile_rcm_three_way(
        pr_records=pr_records,
        gstr3b_rcm_data=g3b_data,
        cumulative_31d_paid_to_date_paise=300000,
    )

    assert res.is_clean is False
    assert res.summary_by_reason[REASON_RCM_TIMING_MISMATCH] == 1
    timing_vars = [v for v in res.variances if v.reason_code == REASON_RCM_TIMING_MISMATCH]
    assert len(timing_vars) == 1
    assert timing_vars[0].diff_paise == 200000
