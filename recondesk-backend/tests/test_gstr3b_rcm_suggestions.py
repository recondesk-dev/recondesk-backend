"""Automated unit and integration tests for GSTR-3B Table 3.1(d) RCM suggestions.

Covers:
- Detection of reverse charge inward supplies from Purchase Register.
- Aggregation of taxable value and tax heads (IGST, CGST, SGST, Cess).
- Inward invoice count tracking.
- Enforcement of Section 49(4) cash ledger discharge reminder.
- Graceful fallback when no RCM supplies exist.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.filing.gstr3b_suggestions import load_rcm_suggestion


def test_rcm_suggestion_returns_aggregated_values():
    """Verify load_rcm_suggestion aggregates reverse charge inward supplies from PR."""
    mock_sb = MagicMock()

    sample_pr_records = [
        {
            "invoice_number": "INV-RCM-01",
            "invoice_date": "2024-11-10",
            "reverse_charge": "Y",
            "taxable_value": 50000.0,
            "igst": 9000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "itc_eligibility": "Ineligible",
            "supplier_gstin": "27AABCT1234A1Z1",
        },
        {
            "invoice_number": "INV-RCM-02",
            "invoice_date": "2024-11-15",
            "reverse_charge": "Y",
            "taxable_value": 30000.0,
            "igst": 0.0,
            "cgst": 2700.0,
            "sgst": 2700.0,
            "cess": 500.0,
            "itc_eligibility": "Ineligible",
            "supplier_gstin": "27AABCT5678B1Z2",
        },
        {
            # Normal supply (non-RCM) - should be excluded from 3.1(d)
            "invoice_number": "INV-NORM-03",
            "invoice_date": "2024-11-20",
            "reverse_charge": "N",
            "taxable_value": 100000.0,
            "igst": 18000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "itc_eligibility": "Input Goods",
            "supplier_gstin": "27AABCT9999C1Z3",
        },
    ]

    with patch("app.filing.gstr3b_suggestions._latest_gstr2b_run", return_value={"id": "run-test-12345678"}):
        with patch("app.filing.gstr3b_suggestions._load_pr_record_datas", return_value=sample_pr_records):
            res = load_rcm_suggestion(mock_sb, client_gstin_id="cid-1", period="2024-11")

    assert res["available"] is True
    assert res["status"] == "available"
    assert res["record_count"] == 2

    isup = res["isup_rev"]
    assert isup["txval"] == 80000.0  # 50,000 + 30,000
    assert isup["iamt"] == 9000.0
    assert isup["camt"] == 2700.0
    assert isup["samt"] == 2700.0
    assert isup["csamt"] == 500.0
    assert "Section 49(4)" in res["cash_ledger_note"]


def test_rcm_suggestion_clean_zero_when_no_rcm_records():
    """When no RCM inward supplies exist in the PR, available is True with record_count 0 and zeroed heads."""
    mock_sb = MagicMock()

    non_rcm_records = [
        {
            "invoice_number": "INV-NORM-01",
            "reverse_charge": "N",
            "taxable_value": 50000.0,
            "igst": 9000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
        }
    ]

    with patch("app.filing.gstr3b_suggestions._latest_gstr2b_run", return_value={"id": "run-test-12345678"}):
        with patch("app.filing.gstr3b_suggestions._load_pr_record_datas", return_value=non_rcm_records):
            res = load_rcm_suggestion(mock_sb, client_gstin_id="cid-1", period="2024-11")

    assert res["available"] is True
    assert res["status"] == "available"
    assert res["record_count"] == 0
    assert res["isup_rev"]["txval"] == 0.0
    assert res["isup_rev"]["iamt"] == 0.0


def test_rcm_suggestion_unavailable_when_no_run():
    """When no reconcile run exists for the period, available is False with clean reason."""
    mock_sb = MagicMock()

    with patch("app.filing.gstr3b_suggestions._latest_gstr2b_run", return_value=None):
        res = load_rcm_suggestion(mock_sb, client_gstin_id="cid-1", period="2024-11")

    assert res["available"] is False
    assert res["status"] == "unavailable"
    assert res["reason"] == "no_gstr2b_reconcile_run"


def test_rcm_suggestion_deduplicates_identical_rows():
    """Duplicate imported rows in PR do not produce doubled liability."""
    mock_sb = MagicMock()

    duplicate_pr_records = [
        {
            "invoice_number": "INV-DUP-01",
            "invoice_date": "2024-11-10",
            "reverse_charge": "Y",
            "taxable_value": 40000.0,
            "igst": 7200.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "supplier_gstin": "27AABCT1234A1Z1",
        },
        {
            # Exact duplicate line item
            "invoice_number": "INV-DUP-01",
            "invoice_date": "2024-11-10",
            "reverse_charge": "Y",
            "taxable_value": 40000.0,
            "igst": 7200.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "supplier_gstin": "27AABCT1234A1Z1",
        },
    ]

    with patch("app.filing.gstr3b_suggestions._latest_gstr2b_run", return_value={"id": "run-test-dup", "client_gstin": "27AABCU9603R1ZM"}):
        with patch("app.filing.gstr3b_suggestions._load_pr_record_datas", return_value=duplicate_pr_records):
            res = load_rcm_suggestion(mock_sb, client_gstin_id="cid-1", period="2024-11")

    assert res["available"] is True
    assert res["record_count"] == 1  # Deduplicated from 2 to 1
    assert res["isup_rev"]["txval"] == 40000.0
    assert res["isup_rev"]["iamt"] == 7200.0


def test_rcm_suggestion_handles_credit_notes():
    """Credit notes with doc_type 'CR' reduce net Table 3.1(d) liability."""
    mock_sb = MagicMock()

    records_with_cn = [
        {
            "invoice_number": "INV-GTA-10",
            "invoice_date": "2024-11-05",
            "reverse_charge": "Y",
            "taxable_value": 100000.0,
            "igst": 5000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "supplier_gstin": "06AABCT1234A1Z1",
            "doc_type": "INV",
        },
        {
            "invoice_number": "CN-GTA-01",
            "invoice_date": "2024-11-12",
            "reverse_charge": "Y",
            "taxable_value": 20000.0,
            "igst": 1000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "supplier_gstin": "06AABCT1234A1Z1",
            "doc_type": "CR",  # Credit Note
        },
    ]

    with patch("app.filing.gstr3b_suggestions._latest_gstr2b_run", return_value={"id": "run-test-cn", "client_gstin": "27AABCU9603R1ZM"}):
        with patch("app.filing.gstr3b_suggestions._load_pr_record_datas", return_value=records_with_cn):
            res = load_rcm_suggestion(mock_sb, client_gstin_id="cid-1", period="2024-11")

    assert res["available"] is True
    assert res["isup_rev"]["txval"] == 80000.0  # 100k - 20k
    assert res["isup_rev"]["iamt"] == 4000.0    # 5k - 1k


def test_rcm_suggestion_allocates_interstate_vs_intrastate_heads():
    """Unbilled statutory RCM items are partitioned into IGST for interstate and CGST+SGST for intrastate."""
    mock_sb = MagicMock()

    unbilled_records = [
        {
            # Interstate (supplier 06 Haryana, client 27 Maharashtra) -> 5% GTA -> IGST
            "invoice_number": "INV-INTER-01",
            "invoice_date": "2024-11-08",
            "hsn_sac": "9965",
            "description": "Freight charges from Gurugram",
            "taxable_value": 100000.0,
            "igst": 0.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "supplier_gstin": "06AABCT9999A1Z1",
        },
        {
            # Intrastate (supplier 27 Maharashtra, client 27 Maharashtra) -> 5% GTA -> CGST 2.5% + SGST 2.5%
            "invoice_number": "INV-INTRA-02",
            "invoice_date": "2024-11-09",
            "hsn_sac": "9965",
            "description": "Local tempo freight Mumbai",
            "taxable_value": 200000.0,
            "igst": 0.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "supplier_gstin": "27AABCT8888B1Z2",
        },
    ]

    with patch("app.filing.gstr3b_suggestions._latest_gstr2b_run", return_value={"id": "run-test-state", "client_gstin": "27AABCU9603R1ZM"}):
        with patch("app.filing.gstr3b_suggestions._load_pr_record_datas", return_value=unbilled_records):
            res = load_rcm_suggestion(mock_sb, client_gstin_id="cid-1", period="2024-11")

    assert res["available"] is True
    assert res["isup_rev"]["txval"] == 300000.0
    # Interstate 5% of 100k = 5,000 IGST
    assert res["isup_rev"]["iamt"] == 5000.0
    # Intrastate 5% of 200k = 10,000 split: 5,000 CGST + 5,000 SGST
    assert res["isup_rev"]["camt"] == 5000.0
    assert res["isup_rev"]["samt"] == 5000.0

