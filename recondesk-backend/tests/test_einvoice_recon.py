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
