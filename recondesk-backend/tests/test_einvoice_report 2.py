"""Unit tests for app/parsers/einvoice_report.py."""

import pandas as pd
import pytest

from app.parsers.einvoice_report import parse_einvoice_report, ParseError


def test_ack_date_only_column_mapping_exclusivity():
    """1. File with only 'Ack Date' column and no 'Invoice Date' column -> invoice_date is None, NOT equal to ack_date."""
    csv_data = (
        "Invoice No,IRN,Ack No,Ack Date,IRN Status,Total Value,Supplier GSTIN\n"
        "INV-700,IRN700,111222,2024-04-20,Active,1500.00,27AAPCS1429B1Z0\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ack_date"] == "2024-04-20"
    assert row["invoice_date"] is None


def test_supplier_and_buyer_gstin_columns_mapping():
    """2. File with both Supplier GSTIN and Buyer GSTIN columns present -> each maps to correct field, not swapped."""
    csv_data = (
        "Invoice No,IRN,Total Value,Supplier GSTIN,Buyer GSTIN\n"
        "INV-800,IRN800,2000.00,27AAPCS1429B1Z0,29AABCU9603R1ZM\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["supplier_gstin"] == "27AAPCS1429B1Z0"
    assert row["buyer_gstin"] == "29AABCU9603R1ZM"
    assert row["gstin"] == "27AAPCS1429B1Z0"  # gstin strictly matches supplier_gstin


def test_irn_status_recognition_and_unknown_fallback():
    """3. IRN status 'CNL' -> Cancelled; blank -> Unknown; garbled 'XYZ123' -> Unknown."""
    csv_data = (
        "Invoice No,IRN,Total Value,Supplier GSTIN,IRN Status\n"
        "INV-901,IRN901,1000.00,27AAPCS1429B1Z0,CNL\n"
        "INV-902,IRN902,1000.00,27AAPCS1429B1Z0,\n"
        "INV-903,IRN903,1000.00,27AAPCS1429B1Z0,XYZ123\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 3
    assert df.iloc[0]["irn_status"] == "Cancelled"
    assert df.iloc[1]["irn_status"] == "Unknown"
    assert df.iloc[2]["irn_status"] == "Unknown"


def test_supply_type_b2c_row_exclusion():
    """4. File with supply_type column containing a B2C row -> excluded from output."""
    csv_data = (
        "Invoice No,IRN,Total Value,Supplier GSTIN,Supply Type\n"
        "INV-1001,IRN1001,1000.00,27AAPCS1429B1Z0,B2B\n"
        "INV-1002,IRN1002,2000.00,27AAPCS1429B1Z0,B2C\n"
        "INV-1003,IRN1003,3000.00,27AAPCS1429B1Z0,B2C_Invoices\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 1
    assert df.iloc[0]["invoice_number"] == "INV-1001"


def test_no_supply_type_column_no_filtering():
    """5. File without supply_type column at all -> no rows filtered."""
    csv_data = (
        "Invoice No,IRN,Total Value,Supplier GSTIN\n"
        "INV-1101,IRN1101,1000.00,27AAPCS1429B1Z0\n"
        "INV-1102,IRN1102,2000.00,27AAPCS1429B1Z0\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 2
