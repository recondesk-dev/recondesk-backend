"""Unit tests for E-Invoice Report parser and reconciliation service."""

import pandas as pd
import pytest

from app.parsers.einvoice_report import parse_einvoice_report, ParseError
from app.services.einvoice_recon import reconcile_books_vs_einvoice
from app.services.decision_templates import generate_decision


def test_einvoice_parser_csv():
    csv_data = (
        "Invoice No,Invoice Date,IRN,Ack No,Ack Date,IRN Status,Total Value,GSTIN\n"
        "INV-2024-001,2024-04-15,1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef,987654,2024-04-15,Active,10000.00,27AAPCS1429B1Z0\n"
        "INV-2024-002,2024-04-16,abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890,987655,2024-04-16,Cancelled,5000.00,27AAPCS1429B1Z0\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "einvoice_report.csv")
    assert len(df) == 2

    row1 = df.iloc[0]
    assert row1["invoice_number"] == "INV-2024-001"
    assert row1["invoice_number_normalized"] == "INV2024001"
    assert row1["irn_status"] == "Active"
    assert row1["value_paise"] == 1000000
    assert row1["gstin"] == "27AAPCS1429B1Z0"

    row2 = df.iloc[1]
    assert row2["irn_status"] == "Cancelled"
    assert row2["value_paise"] == 500000


def test_einvoice_recon_categories():
    books = [
        {"invoice_number": "INV-101", "gstin": "27AAPCS1429B1Z0", "total_amount": 1000.0, "invoice_date": "2024-04-10"},
        {"invoice_number": "INV-102", "gstin": "27AAPCS1429B1Z0", "total_amount": 2500.0, "invoice_date": "2024-04-11"},
        {"invoice_number": "INV-103", "gstin": "27AAPCS1429B1Z0", "total_amount": 3000.0, "invoice_date": "2024-04-12"},
        {"invoice_number": "INV-104", "gstin": "27AAPCS1429B1Z0", "total_amount": 4000.0, "invoice_date": "2024-04-13"},
    ]

    einvoices = [
        {"invoice_number": "INV-101", "gstin": "27AAPCS1429B1Z0", "total_value": 1000.0, "irn": "IRN1", "irn_status": "Active"},
        {"invoice_number": "INV-102", "gstin": "27AAPCS1429B1Z0", "total_value": 2500.0, "irn": "IRN2", "irn_status": "Cancelled"},
        {"invoice_number": "INV-103", "gstin": "27AAPCS1429B1Z0", "total_value": 3500.0, "irn": "IRN3", "irn_status": "Active"},
        {"invoice_number": "INV-999", "gstin": "27AAPCS1429B1Z0", "total_value": 8000.0, "irn": "IRN999", "irn_status": "Active"},
    ]

    res = reconcile_books_vs_einvoice(books, einvoices, e_invoice_applicable=True)
    summary = res["summary"]
    results = res["results"]

    assert summary["matched_count"] == 1  # INV-101
    assert summary["irn_cancelled_count"] == 1  # INV-102
    assert summary["value_mismatch_count"] == 1  # INV-103
    assert summary["irn_missing_count"] == 1  # INV-104
    assert summary["extra_irn_count"] == 1  # INV-999

    cat_map = {r["invoice_number"]: r["category"] for r in results}
    assert cat_map["INV-101"] == "MATCHED"
    assert cat_map["INV-102"] == "IRN_CANCELLED"
    assert cat_map["INV-103"] == "VALUE_MISMATCH"
    assert cat_map["INV-104"] == "IRN_MISSING"
    assert cat_map["INV-999"] == "EXTRA_IRN"


def test_einvoice_decision_templates():
    dec_missing = generate_decision("EINVOICE_IRN_MISSING")
    assert "not registered" in dec_missing.what.lower() or "missing" in dec_missing.what.lower()
    assert "30-day" in dec_missing.next.lower() or "reporting window" in dec_missing.next.lower()

    dec_cancelled = generate_decision("EINVOICE_CANCELLED_MISMATCH")
    assert "cancelled" in dec_cancelled.what.lower()
    assert "accounting software" in dec_cancelled.why.lower() or "portal" in dec_cancelled.why.lower()
    assert "credit note" in dec_cancelled.next.lower()


def test_einvoice_ranking_active_over_cancelled():
    """Two e-invoice rows with same invoice_number+GSTIN, one Cancelled one Active -> books matches Active."""
    books = [
        {"invoice_number": "INV-200", "gstin": "27AAPCS1429B1Z0", "total_amount": 5000.0, "invoice_date": "2024-04-10"},
    ]
    einvoices = [
        {"invoice_number": "INV-200", "gstin": "27AAPCS1429B1Z0", "total_value": 5000.0, "irn": "IRN_OLD_CANCELLED", "irn_status": "Cancelled", "ack_date": "2024-04-10"},
        {"invoice_number": "INV-200", "gstin": "27AAPCS1429B1Z0", "total_value": 5000.0, "irn": "IRN_NEW_ACTIVE", "irn_status": "Active", "ack_date": "2024-04-11"},
    ]
    res = reconcile_books_vs_einvoice(books, einvoices)
    r = res["results"][0]
    assert r["category"] == "MATCHED"
    assert r["irn"] == "IRN_NEW_ACTIVE"
    assert r["match_confidence"] == "HIGH"


def test_blank_gstin_single_candidate():
    """Books row with blank GSTIN, exactly one e-invoice candidate matching invoice_number -> matches with LOW_GSTIN_BLANK."""
    books = [
        {"invoice_number": "INV-300", "gstin": "", "total_amount": 1200.0, "invoice_date": "2024-04-10"},
    ]
    einvoices = [
        {"invoice_number": "INV-300", "gstin": "27AAPCS1429B1Z0", "total_value": 1200.0, "irn": "IRN300", "irn_status": "Active"},
    ]
    res = reconcile_books_vs_einvoice(books, einvoices)
    r = res["results"][0]
    assert r["category"] == "MATCHED"
    assert r["irn"] == "IRN300"
    assert r["match_confidence"] == "LOW_GSTIN_BLANK"
    assert "GSTIN was missing in books" in r["decision_why"]


def test_blank_gstin_multiple_candidates():
    """Books row with blank GSTIN, multiple e-invoice candidates matching invoice_number -> routes to IRN_MISSING with custom decision_why."""
    books = [
        {"invoice_number": "INV-400", "gstin": "", "total_amount": 1000.0, "invoice_date": "2024-04-10"},
    ]
    einvoices = [
        {"invoice_number": "INV-400", "gstin": "27AAPCS1429B1Z0", "total_value": 1000.0, "irn": "IRN400A", "irn_status": "Active"},
        {"invoice_number": "INV-400", "gstin": "29AABCU9603R1ZM", "total_value": 1000.0, "irn": "IRN400B", "irn_status": "Active"},
    ]
    res = reconcile_books_vs_einvoice(books, einvoices)
    r = res["results"][0]
    assert r["category"] == "IRN_MISSING"
    assert r["match_confidence"] == "LOW_GSTIN_BLANK"
    assert "Multiple e-invoice candidates share this invoice number" in r["decision_why"]
    assert "GSTIN missing in books prevents disambiguation" in r["decision_why"]


def test_populated_gstin_mismatch():
    """Books row with populated GSTIN that doesn't match any e-invoice GSTIN -> does NOT match, routes to IRN_MISSING."""
    books = [
        {"invoice_number": "INV-500", "gstin": "27AAPCS1429B1Z0", "total_amount": 2000.0, "invoice_date": "2024-04-10"},
    ]
    einvoices = [
        {"invoice_number": "INV-500", "gstin": "29AABCU9603R1ZM", "total_value": 2000.0, "irn": "IRN500", "irn_status": "Active"},
    ]
    res = reconcile_books_vs_einvoice(books, einvoices)
    r = res["results"][0]
    assert r["category"] == "IRN_MISSING"
    assert r["match_confidence"] == "HIGH"
    assert "registered" in r["decision_what"].lower() or "missing" in r["decision_what"].lower()


def test_ack_date_only_column_mapping_exclusivity():
    """File with only 'Ack Date' column and no 'Invoice Date' column -> invoice_date should be None, not equal to ack_date."""
    csv_data = (
        "Invoice No,IRN,Ack No,Ack Date,IRN Status,Total Value,Supplier GSTIN\n"
        "INV-700,IRN700,111222,2024-04-20,Active,1500.00,27AAPCS1429B1Z0\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ack_date"] == "2024-04-20"
    assert row["invoice_date"] is None


def test_supplier_and_buyer_gstin_columns():
    """File with both Supplier GSTIN and Buyer GSTIN columns -> populated correctly and not swapped."""
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


def test_buyer_gstin_only_no_fallback_to_gstin():
    """File with only Buyer GSTIN column -> gstin should be empty (no fallback to buyer_gstin)."""
    csv_data = (
        "Invoice No,IRN,Total Value,Buyer GSTIN\n"
        "INV-850,IRN850,2000.00,29AABCU9603R1ZM\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["supplier_gstin"] == ""
    assert row["buyer_gstin"] == "29AABCU9603R1ZM"
    assert row["gstin"] == ""  # strictly empty, no silent fallback to buyer_gstin


def test_irn_status_unknown_fallback():
    """IRN status 'CNL' -> Cancelled; blank -> Unknown; 'XYZ123' -> Unknown."""
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


def test_supply_type_b2c_filtering():
    """File with supply_type column containing a B2C row -> B2C row excluded from output."""
    csv_data = (
        "Invoice No,IRN,Total Value,Supplier GSTIN,Supply Type\n"
        "INV-1001,IRN1001,1000.00,27AAPCS1429B1Z0,B2B\n"
        "INV-1002,IRN1002,2000.00,27AAPCS1429B1Z0,B2C\n"
        "INV-1003,IRN1003,3000.00,27AAPCS1429B1Z0,B2C_Invoices\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 1
    assert df.iloc[0]["invoice_number"] == "INV-1001"


def test_no_supply_type_no_filtering():
    """File without supply_type column at all -> no rows filtered (backward compatible)."""
    csv_data = (
        "Invoice No,IRN,Total Value,Supplier GSTIN\n"
        "INV-1101,IRN1101,1000.00,27AAPCS1429B1Z0\n"
        "INV-1102,IRN1102,2000.00,27AAPCS1429B1Z0\n"
    ).encode("utf-8")

    df = parse_einvoice_report(csv_data, "report.csv")
    assert len(df) == 2
