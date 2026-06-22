"""test_partial_no_date.py — Rule 37 partial payment via build_payment_records_from_pr.

The _obsolete tests that exercised the removed payment-status filter have been deleted.
This module tests build_payment_records_from_pr directly.
"""
import pytest
from datetime import date
from app.services.rule37_tracker import check_rule_37_compliance, build_payment_records_from_pr, OK


def test_build_payment_records_partial_with_date():
    """Partial payment with a date should produce a payment record."""
    pr_rows = [{"id": "pr1", "taxable_amount_paise": 100000, "total_tax_paise": 18000}]
    pr_raw = {"pr1": {"payment_status": "partial", "amount_paid_paise": 59000, "payment_date": "2023-06-01"}}
    payments = build_payment_records_from_pr(pr_rows, pr_raw)
    assert len(payments) == 1
    assert payments[0]["amount_paise"] == 59000
    assert payments[0]["payment_date"] == "2023-06-01"


def test_build_payment_records_unpaid_skipped():
    """Unpaid records should not produce payment entries."""
    pr_rows = [{"id": "pr1", "taxable_amount_paise": 100000, "total_tax_paise": 18000}]
    pr_raw = {"pr1": {"payment_status": "unpaid"}}
    payments = build_payment_records_from_pr(pr_rows, pr_raw)
    assert len(payments) == 0
