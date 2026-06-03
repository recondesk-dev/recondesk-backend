"""PR payment column parsing and Rule 37 payment-record wiring."""

from __future__ import annotations

import io
from datetime import date

import pandas as pd

from app.parsers.purchase_register_parser import parse_purchase_register
from app.services.reconciliation_record_adapter import pr_db_row_to_matcher_row
from app.services.rule37_tracker import (
    OK,
    OVERDUE_UNPAID,
    build_payment_records_from_pr,
    check_rule_37_compliance,
)


def _csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_parser_reads_payment_status_and_date():
    csv = _csv_bytes(
        [
            {
                "Supplier GSTIN": "27AAAPZ1234A1Z5",
                "Supplier Name": "Vendor",
                "Invoice Number": "INV-001",
                "Invoice Date": "01/05/2026",
                "Taxable Amount": "10000",
                "IGST": "0",
                "CGST": "900",
                "SGST": "900",
                "Total Invoice Value": "11800",
                "Payment Status": "Paid",
                "Payment Date": "05/06/2026",
            }
        ]
    )
    result = parse_purchase_register(csv, "pay.csv")
    assert result["success"] is True
    rec = result["records"][0]
    assert rec["payment_status"] == "paid"
    assert rec["payment_date"] == "2026-06-05"


def test_build_payment_records_from_paid_row():
    raw = {
        "payment_status": "paid",
        "payment_date": "2026-06-05",
        "taxable_amount_paise": 10000,
    }
    matcher = pr_db_row_to_matcher_row(
        {
            "id": "pr-1",
            "record_data": {
                **raw,
                "gstin": "27AAAPZ1234A1Z5",
                "invoice_number_normalized": "INV001",
                "invoice_date": "2026-05-01",
                "total_tax_paise": 1800,
            },
        }
    )
    payments = build_payment_records_from_pr([matcher], {"pr-1": raw})
    assert len(payments) == 1
    assert payments[0]["invoice_id"] == "pr-1"
    assert payments[0]["payment_date"] == "2026-06-05"
    assert payments[0]["amount_paise"] == 1_000_000


def test_build_payment_records_skips_unpaid():
    raw = {"payment_status": "unpaid", "taxable_amount_paise": 10000}
    matcher = pr_db_row_to_matcher_row(
        {
            "id": "pr-2",
            "record_data": {
                **raw,
                "gstin": "27AAAPZ1234A1Z5",
                "invoice_number_normalized": "INV002",
                "invoice_date": "2025-10-30",
                "total_tax_paise": 2700,
            },
        }
    )
    assert build_payment_records_from_pr([matcher], {"pr-2": raw}) == []


def test_rule37_paid_on_time_after_payment_parse():
    raw = {
        "payment_status": "paid",
        "payment_date": "2026-06-05",
        "taxable_amount_paise": 10000,
    }
    matcher = pr_db_row_to_matcher_row(
        {
            "id": "pr-3",
            "record_data": {
                **raw,
                "gstin": "27AAAPZ1234A1Z5",
                "invoice_number_normalized": "INV001",
                "invoice_date": "2026-05-01",
                "total_tax_paise": 1800,
            },
        }
    )
    payments = build_payment_records_from_pr([matcher], {"pr-3": raw})
    pr_row = {
        **matcher,
        "invoice_date": "2026-05-01",
    }
    results = check_rule_37_compliance([pr_row], payments, today=date(2026, 6, 10))
    assert results[0]["status"] == OK


def test_rule37_unpaid_overdue_from_pr_status():
    raw = {"payment_status": "unpaid", "taxable_amount_paise": 15000}
    matcher = pr_db_row_to_matcher_row(
        {
            "id": "pr-4",
            "record_data": {
                **raw,
                "gstin": "27AAAPZ1234A1Z5",
                "invoice_number_normalized": "INV012",
                "invoice_date": "2025-10-30",
                "total_tax_paise": 2700,
            },
        }
    )
    payments = build_payment_records_from_pr([matcher], {"pr-4": raw})
    pr_row = {**matcher, "invoice_date": "2025-10-30"}
    results = check_rule_37_compliance(
        [pr_row], payments, today=date(2026, 6, 3)
    )
    assert results[0]["status"] == OVERDUE_UNPAID


def test_adversarial_pr_payment_columns_detected():
    from pathlib import Path

    path = Path("/Users/omkarkadam/Downloads/recondesk_adversarial_purchase_register.xlsx")
    if not path.is_file():
        return
    parsed = parse_purchase_register(path.read_bytes(), "adv.xlsx")
    paid = [
        r
        for r in parsed["records"]
        if r.get("invoice_number_normalized") == "INV-001"
    ]
    assert len(paid) == 1
    assert paid[0].get("payment_status") == "paid"
    assert paid[0].get("payment_date") == "2026-06-05"
    unpaid = [
        r
        for r in parsed["records"]
        if r.get("invoice_number_normalized") == "INV-012"
    ]
    assert len(unpaid) == 1
    assert unpaid[0].get("payment_status") == "unpaid"
