import pandas as pd
import pytest

from app.parsers.purchase_register_parser import detect_column_mapping as detect_pr_mapping
from app.parsers.sales_register_parser import detect_column_mapping as detect_sr_mapping


def test_pr_date_precedence_supplier_invoice_date_over_voucher_date():
    """Verify Supplier Invoice Date takes precedence over generic Date or Voucher Date."""
    df = pd.DataFrame(
        columns=[
            "GSTIN",
            "Supplier Invoice No",
            "Date",  # Generic Tally voucher date
            "Supplier Invoice Date",  # True document date
            "Taxable Amount",
            "Total Tax",
        ]
    )
    mapping = detect_pr_mapping(df)
    assert mapping["invoice_date"] == "Supplier Invoice Date", (
        f"Expected 'Supplier Invoice Date', got '{mapping.get('invoice_date')}'"
    )
    assert mapping["invoice_number"] == "Supplier Invoice No"


def test_pr_date_precedence_bill_date_over_vch_date():
    """Verify Bill Date takes precedence over Voucher Date."""
    df = pd.DataFrame(
        columns=[
            "Party GSTIN",
            "Bill No",
            "Voucher Date",  # Posting / entry date
            "Bill Date",     # Document date
            "Taxable Value",
            "IGST",
        ]
    )
    mapping = detect_pr_mapping(df)
    assert mapping["invoice_date"] == "Bill Date", (
        f"Expected 'Bill Date', got '{mapping.get('invoice_date')}'"
    )
    assert mapping.get("posting_date") == "Voucher Date"


def test_pr_date_fallback_when_only_date_present():
    """When only a single Date column exists, it should be mapped to invoice_date."""
    df = pd.DataFrame(
        columns=[
            "GSTIN",
            "Invoice No",
            "Date",
            "Taxable Amount",
            "CGST",
            "SGST",
        ]
    )
    mapping = detect_pr_mapping(df)
    assert mapping["invoice_date"] == "Date"


def test_pr_date_fallback_when_only_voucher_date_present():
    """When only Voucher Date exists, it should still map to invoice_date as fallback."""
    df = pd.DataFrame(
        columns=[
            "GSTIN",
            "Invoice No",
            "Voucher Date",
            "Taxable Amount",
            "Total Tax",
        ]
    )
    mapping = detect_pr_mapping(df)
    assert mapping["invoice_date"] == "Voucher Date"


def test_sr_date_precedence_sales_invoice_date_over_voucher_date():
    """Verify Sales Register prefers Sales Invoice Date over Voucher Date."""
    df = pd.DataFrame(
        columns=[
            "GSTIN",
            "Sales Invoice No",
            "Date",
            "Sales Invoice Date",
            "Taxable Amount",
            "Total Tax",
        ]
    )
    mapping = detect_sr_mapping(df)
    assert mapping["invoice_date"] == "Sales Invoice Date"
    assert mapping["invoice_number"] == "Sales Invoice No"
