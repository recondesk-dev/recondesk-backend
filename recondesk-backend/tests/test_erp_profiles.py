"""Tests for ERP (SAP, Oracle, Busy, Zoho) export profiles and compact date parsing."""

import datetime
import io
import pandas as pd
import pytest

from app.parsers.erp_profiles import (
    ERP_PURCHASE_ALIASES,
    ERP_SALES_ALIASES,
    SAP_PURCHASE_ALIASES,
    is_erp_credit_note,
)
from app.parsers.purchase_register_parser import (
    parse_purchase_register,
    detect_column_mapping as detect_pr_mapping,
)
from app.parsers.sales_register_parser import (
    parse_sales_register,
    detect_column_mapping as detect_sr_mapping,
)
from app.services.normalizer import normalize_date


def test_normalize_date_erp_compact_8_digit():
    """Verify 8-digit ERP dates (YYYYMMDD and DDMMYYYY) are converted accurately."""
    # Integer format (common in raw SAP dumps)
    r1 = normalize_date(20240315)
    assert r1.value == datetime.date(2024, 3, 15)
    assert "erp_compact_date_converted" in r1.notes

    # String format
    r2 = normalize_date("20240315")
    assert r2.value == datetime.date(2024, 3, 15)
    assert "erp_compact_date_converted" in r2.notes

    # DDMMYYYY format
    r3 = normalize_date("15032024")
    assert r3.value == datetime.date(2024, 3, 15)
    assert "erp_compact_date_converted" in r3.notes

    # Float format from pandas reading integer column as float
    r4 = normalize_date(20240315.0)
    assert r4.value == datetime.date(2024, 3, 15)


def test_sap_purchase_register_parsing():
    """Verify SAP MM/FI purchase register with technical column codes and 8-digit dates."""
    data = {
        "BELNR": ["1900000001", "1900000002"],  # SAP accounting document number
        "XBLNR": ["INV-9901", "INV-9902"],       # Vendor invoice number (must take priority!)
        "BUDAT": ["20240315", "20240316"],       # SAP posting date in YYYYMMDD
        "STCD3": ["27ABCDE1234F1Z5", "27ABCDE1234F1Z5"],  # SAP India GSTIN
        "NAME1": ["Acme Solutions Pvt Ltd", "Acme Solutions Pvt Ltd"],
        "WRBTR": [10000.0, 5000.0],              # Taxable base
        "CGST_AMT": [900.0, 450.0],
        "SGST_AMT": [900.0, 450.0],
        "BLART": ["KR", "KR"],                   # Vendor Invoice
    }
    df = pd.DataFrame(data)
    mapping = detect_pr_mapping(df)

    assert mapping["invoice_number"] == "XBLNR"  # Specificity prefers XBLNR over BELNR
    assert mapping["gstin"] == "STCD3"
    assert mapping["taxable_amount"] == "WRBTR"
    assert mapping["cgst"] == "CGST_AMT"
    assert mapping["sgst"] == "SGST_AMT"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SAP_Dump")

    res = parse_purchase_register(buf.getvalue(), "sap_purchase.xlsx")
    records = res["records"]
    assert len(records) == 2
    assert records[0]["invoice_number"] == "INV-9901"
    assert records[0]["invoice_date"] == "2024-03-15"
    assert records[0]["gstin"] == "27ABCDE1234F1Z5"
    assert records[0]["taxable_amount_paise"] == 1000000
    assert records[0]["cgst_paise"] == 90000
    assert records[0]["sgst_paise"] == 90000
    assert records[0]["document_type"] == "INVOICE"


def test_sap_credit_memo_detection():
    """Verify SAP Document Type KG (Vendor Credit Memo) automatically classifies as CREDIT_NOTE."""
    data = {
        "XBLNR": ["CRN-101"],
        "BUDAT": ["20240320"],
        "STCEG": ["27ABCDE1234F1Z5"],
        "NAME1": ["Acme Solutions Pvt Ltd"],
        "WRBTR": [2000.0],  # Positive in SAP export, but document type is KG
        "CGST_VAL": [180.0],
        "SGST_VAL": [180.0],
        "BLART": ["KG"],    # Vendor Credit Memo
    }
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SAP_Credit")

    res = parse_purchase_register(buf.getvalue(), "sap_credit.xlsx")
    records = res["records"]
    assert len(records) == 1
    assert records[0]["invoice_number"] == "CRN-101"
    assert records[0]["document_type"] == "CREDIT_NOTE"
    assert records[0]["is_credit_note"] is True
    assert records[0]["taxable_amount_paise"] == -200000  # Automatically signed negative


def test_sap_sales_register_parsing():
    """Verify SAP SD sales billing documents (VBELN) and customer GSTIN."""
    data = {
        "VBELN": ["90012345", "90012346"],  # SAP Billing Document (must beat BELNR)
        "BELNR": ["10001", "10002"],
        "FKDAT": ["20240401", "20240402"],
        "STCEG": ["29AAGCB1234P1Z3", "29AAGCB1234P1Z3"],
        "NAME1": ["Bharat Tech Corp", "Bharat Tech Corp"],
        "NETWR": [50000.0, 75000.0],
        "J_1IIGST": [9000.0, 13500.0],
        "BLART": ["DR", "DG"],  # DR = Invoice, DG = Customer Credit Memo
    }
    df = pd.DataFrame(data)
    mapping = detect_sr_mapping(df)

    assert mapping["invoice_number"] == "VBELN"
    assert mapping["gstin"] == "STCEG"
    assert mapping["taxable_amount"] == "NETWR"
    assert mapping["igst"] == "J_1IIGST"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SAP_Sales")

    res = parse_sales_register(buf.getvalue(), "sap_sales.xlsx")
    records = res["records"]
    assert len(records) == 2
    assert records[0]["invoice_number"] == "90012345"
    assert records[0]["invoice_date"] == "2024-04-01"
    assert records[0]["invoice_type"] == "B2B"

    # Row 2 is DG (Customer Credit Memo)
    assert records[1]["invoice_number"] == "90012346"
    assert records[1]["invoice_type"] == "CREDIT_NOTE"


def test_oracle_purchase_register_parsing():
    """Verify Oracle Cloud / EBS AP invoice export mapping."""
    data = {
        "TRX_NUMBER": ["AP-2024-001"],
        "TRX_DATE": ["2024-03-10"],
        "TAX_REGISTRATION_NUMBER": ["27ABCDE1234F1Z5"],
        "VENDOR_NAME": ["Oracle Vendor Ltd"],
        "LINE_AMOUNT": [30000.0],
        "IGST_AMOUNT": [5400.0],
        "INVOICE_AMOUNT": [35400.0],
    }
    df = pd.DataFrame(data)
    mapping = detect_pr_mapping(df)

    assert mapping["invoice_number"] == "TRX_NUMBER"
    assert mapping["invoice_date"] == "TRX_DATE"
    assert mapping["gstin"] == "TAX_REGISTRATION_NUMBER"
    assert mapping["taxable_amount"] == "LINE_AMOUNT"
    assert mapping["igst"] == "IGST_AMOUNT"
    assert mapping["total_amount"] == "INVOICE_AMOUNT"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Oracle_AP")

    res = parse_purchase_register(buf.getvalue(), "oracle_ap.xlsx")
    records = res["records"]
    assert len(records) == 1
    assert records[0]["invoice_number"] == "AP-2024-001"
    assert records[0]["taxable_amount_paise"] == 3000000
    assert records[0]["igst_paise"] == 540000


def test_busy_accounting_register_parsing():
    """Verify Busy Accounting export with Vch No, Bill No, and Party GSTIN."""
    data = {
        "Vch No.": ["V-101"],
        "Bill No.": ["B-9021"],
        "Bill Date": ["15-03-2024"],
        "Party GSTIN": ["27ABCDE1234F1Z5"],
        "Party Name": ["Busy Traders"],
        "Taxable Amt": [15000.0],
        "CGST Amt": [1350.0],
        "SGST Amt": [1350.0],
        "Total Amt": [17700.0],
    }
    df = pd.DataFrame(data)
    mapping = detect_pr_mapping(df)

    assert mapping["invoice_number"] == "Bill No."  # Specificity prefers Bill No. over Vch No.
    assert mapping["gstin"] == "Party GSTIN"
    assert mapping["taxable_amount"] == "Taxable Amt"
    assert mapping["cgst"] == "CGST Amt"
    assert mapping["sgst"] == "SGST Amt"


def test_zoho_books_register_parsing():
    """Verify Zoho Books bill export."""
    data = {
        "Bill Number": ["BILL-4451"],
        "Bill Date": ["2024-03-12"],
        "Vendor Name": ["Zoho Cloud Supplies"],
        "GST Identification Number (GSTIN)": ["27ABCDE1234F1Z5"],
        "Taxable Amount": [4000.0],
        "CGST (Rs.)": [360.0],
        "SGST (Rs.)": [360.0],
        "Total": [4720.0],
    }
    df = pd.DataFrame(data)
    mapping = detect_pr_mapping(df)

    assert mapping["invoice_number"] == "Bill Number"
    assert mapping["gstin"] == "GST Identification Number (GSTIN)"
    assert mapping["taxable_amount"] == "Taxable Amount"
    assert mapping["cgst"] == "CGST (Rs.)"
    assert mapping["sgst"] == "SGST (Rs.)"
    assert mapping["total_amount"] == "Total"
