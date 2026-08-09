"""Unit tests for RCM applicability detector."""

from __future__ import annotations

import pytest
from app.reconciliation.rcm_detector import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    REASON_IMPORT_OF_SERVICES,
    REASON_KEYWORD_MATCH,
    REASON_NOTIFIED_GOODS,
    REASON_NOTIFIED_SERVICES,
    REASON_PR_REVERSE_CHARGE_FLAG,
    detect_rcm_inward_supplies,
)


def test_detect_rcm_notified_goods_cashew_nuts():
    records = [
        {
            "invoice_number": "INV-001",
            "supplier_gstin": "27AAACB1234A1Z1",
            "hsn": "0801",
            "taxable_amount_paise": 1000000,
            "igst_paise": 50000,
            "ledger_name": "Raw Materials Purchase",
        }
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 1
    assert res[0]["invoice_number"] == "INV-001"
    assert res[0]["reason_code"] == REASON_NOTIFIED_GOODS
    assert res[0]["confidence"] == CONFIDENCE_HIGH
    assert res[0]["pending_review"] is False
    assert "Cashew nuts" in res[0]["category"]


def test_detect_rcm_notified_goods_tobacco_silk_cotton():
    records = [
        {"invoice_number": "INV-T", "hsn": "24011000", "taxable_amount_paise": 500000},
        {"invoice_number": "INV-S", "hsn": "5004", "taxable_amount_paise": 200000},
        {"invoice_number": "INV-C", "hsn": "52010010", "taxable_amount_paise": 300000},
        {"invoice_number": "INV-B", "hsn": "14049010", "taxable_amount_paise": 100000},
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 4
    for item in res:
        assert item["reason_code"] == REASON_NOTIFIED_GOODS
        assert item["confidence"] == CONFIDENCE_HIGH


def test_detect_rcm_notified_services_gta_sac():
    records = [
        {
            "invoice_number": "GTA-101",
            "supplier_gstin": "27BBBCB5678B1Z2",
            "sac": "996511",
            "taxable_amount_paise": 2500000,
            "igst_paise": 125000,
            "ledger_name": "Freight Inward",
        }
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 1
    assert res[0]["reason_code"] == REASON_NOTIFIED_SERVICES
    assert res[0]["confidence"] == CONFIDENCE_HIGH
    assert "Goods Transport Agency" in res[0]["category"]


def test_detect_rcm_legal_services_advocate_keyword():
    records = [
        {
            "invoice_number": "LEG-2026",
            "supplier_gstin": "27CCCCB9999C1Z3",
            "taxable_amount_paise": 1500000,
            "ledger_name": "Legal Fees paid to Advocate Senior Counsel",
        }
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 1
    assert res[0]["reason_code"] == REASON_NOTIFIED_SERVICES
    assert res[0]["confidence"] == CONFIDENCE_HIGH
    assert res[0]["flag_source"] == "keyword"
    assert "Legal Services" in res[0]["category"]


def test_detect_rcm_director_remuneration_keyword():
    records = [
        {
            "invoice_number": "DIR-01",
            "supplier_gstin": "",
            "taxable_amount_paise": 5000000,
            "ledger_name": "Director Sitting Fees & Remuneration",
        }
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 1
    assert res[0]["reason_code"] == REASON_NOTIFIED_SERVICES
    assert res[0]["confidence"] == CONFIDENCE_HIGH
    assert "Director" in res[0]["category"]


def test_detect_rcm_import_of_services_keyword():
    records = [
        {
            "invoice_number": "AWS-AUG-2026",
            "supplier_gstin": "",
            "taxable_amount_paise": 10000000,
            "remarks": "Import of services cloud hosting Amazon Web Services",
        }
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 1
    assert res[0]["reason_code"] == REASON_IMPORT_OF_SERVICES
    assert res[0]["confidence"] == CONFIDENCE_HIGH
    assert res[0]["pending_review"] is False


def test_detect_rcm_freight_keyword_ambiguous_pending_review():
    records = [
        {
            "invoice_number": "FRT-55",
            "supplier_gstin": "27DDDCB1111D1Z4",
            "taxable_amount_paise": 400000,
            "ledger_name": "General Freight Charges",
        }
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 1
    assert res[0]["reason_code"] == REASON_NOTIFIED_SERVICES
    assert res[0]["confidence"] == CONFIDENCE_MEDIUM
    assert res[0]["pending_review"] is True


def test_detect_rcm_explicit_pr_column_flag():
    records = [
        {
            "invoice_number": "EXPLICIT-1",
            "supplier_gstin": "27EEECB2222E1Z5",
            "taxable_amount_paise": 800000,
            "reverse_charge": "Y",
            "ledger_name": "Misc Expenses",
        }
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 1
    assert res[0]["reason_code"] == REASON_PR_REVERSE_CHARGE_FLAG
    assert res[0]["confidence"] == CONFIDENCE_HIGH
    assert res[0]["flag_source"] == "pr_flag"
    assert res[0]["pending_review"] is False


def test_detect_rcm_deliberate_non_rcm_no_false_positives():
    records = [
        {
            "invoice_number": "LAPTOP-01",
            "supplier_gstin": "27FFFFB3333F1Z6",
            "hsn": "8471",
            "taxable_amount_paise": 7500000,
            "igst_paise": 1350000,
            "ledger_name": "Office Equipment Dell Laptops",
        },
        {
            "invoice_number": "RENT-01",
            "supplier_gstin": "27GGGBB4444G1Z7",
            "sac": "997212",
            "taxable_amount_paise": 5000000,
            "cgst_paise": 450000,
            "sgst_paise": 450000,
            "ledger_name": "Commercial Office Rent",
        },
        {
            "invoice_number": "STEEL-99",
            "supplier_gstin": "27HHHBB5555H1Z8",
            "hsn": "7208",
            "taxable_amount_paise": 20000000,
            "cgst_paise": 1800000,
            "sgst_paise": 1800000,
            "ledger_name": "Raw Steel Plates",
        },
        {
            "invoice_number": "AUDIT-01",
            "supplier_gstin": "27IIIBC6666I1Z9",
            "taxable_amount_paise": 1000000,
            "cgst_paise": 90000,
            "sgst_paise": 90000,
            "ledger_name": "Statutory Financial Audit Fees",
        },
    ]
    res = detect_rcm_inward_supplies(records)
    assert len(res) == 0, f"Expected 0 false positives, got {len(res)}: {res}"
