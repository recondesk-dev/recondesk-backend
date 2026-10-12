"""Tests for Form GSTR-11 UIN Statutory Rules and Refund Calculation Engine."""

from datetime import date
from decimal import Decimal
import pytest

from app.rules.gstr11_rules import (
    UinSupplyType,
    aggregate_gstr11_refund_statement,
    calculate_gstr11_due_date,
    validate_uin,
    validate_uin_inward_supply,
)


def test_uin_format_validation():
    """Verify 15-character Unique Identification Number (UIN) formats."""
    # Valid UINs (embassies, consulates, multilateral institutions)
    assert validate_uin("0717USA00001UN1") is True
    assert validate_uin("2718UNP00001UN2") is True
    assert validate_uin("07AABCU0000A1Z5") is True

    # Invalid UINs
    assert validate_uin("0717USA") is False # Too short
    assert validate_uin("0717USA00001UN1XYZ") is False # Too long
    assert validate_uin("") is False


def test_gstr11_due_date_calculation():
    """Verify Rule 82 due date: 28th of the month following the quarter/month."""
    due = calculate_gstr11_due_date("2026-10")
    assert due == date(2026, 11, 28)

    # Year rollover
    due_dec = calculate_gstr11_due_date("2026-12")
    assert due_dec == date(2027, 1, 28)


def test_validate_uin_inward_supply_success():
    """Verify valid Table 3A invoice and Table 3B credit/debit notes."""
    # Table 3A Invoice
    inv = {
        "supply_type": "3A",
        "supplier_gstin": "27AABCU9603R1ZX",
        "doc_number": "INV-100",
        "doc_date": "2026-10-05",
        "taxable_value": 50000,
        "cgst": 4500,
        "sgst": 4500,
        "igst": 0,
        "cess": 0,
    }
    assert validate_uin_inward_supply(inv) == []

    # Table 3B Credit Note
    cdn = {
        "supply_type": "3B",
        "supplier_gstin": "27AABCU9603R1ZX",
        "doc_number": "CN-01",
        "doc_date": "2026-10-15",
        "cdn_type": "C",
        "original_invoice_number": "INV-100",
        "taxable_value": 5000,
        "cgst": 450,
        "sgst": 450,
        "igst": 0,
        "cess": 0,
    }
    assert validate_uin_inward_supply(cdn) == []


def test_validate_uin_inward_supply_violations():
    """Detect invalid supplier GSTIN, missing document references, and negative amounts."""
    bad_cdn = {
        "supply_type": "3B",
        "supplier_gstin": "INVALID_GSTIN",
        "doc_number": "CN-02",
        "doc_date": "2026-10-15",
        "cdn_type": "INVALID",
        # missing original_invoice_number
        "taxable_value": 5000,
        "cgst": -450,
    }
    errs = validate_uin_inward_supply(bad_cdn)
    assert "G11_INVALID_SUPPLIER_GSTIN" in errs
    assert "G11_INVALID_CDN_TYPE" in errs
    assert "G11_MISSING_ORIGINAL_INVOICE_REF" in errs
    assert "G11_NEGATIVE_TAX_HEAD" in errs


def test_aggregate_gstr11_refund_statement():
    """Verify Table 3A and 3B aggregation with Credit Note reductions and Section 55 cash refund claim."""
    supplies = [
        # Table 3A Invoices
        {"supply_type": "3A", "taxable_value": 100000, "cgst": 9000, "sgst": 9000, "igst": 0, "cess": 0, "is_eligible_for_refund": True},
        {"supply_type": "3A", "taxable_value": 200000, "cgst": 0, "sgst": 0, "igst": 36000, "cess": 1000, "is_eligible_for_refund": True},
        # Table 3B Credit Note (Reduces refund)
        {"supply_type": "3B", "cdn_type": "C", "taxable_value": 10000, "cgst": 900, "sgst": 900, "igst": 0, "cess": 0, "is_eligible_for_refund": True},
        # Table 3B Debit Note (Increases refund)
        {"supply_type": "3B", "cdn_type": "D", "taxable_value": 5000, "cgst": 0, "sgst": 0, "igst": 900, "cess": 0, "is_eligible_for_refund": True},
    ]

    summary = aggregate_gstr11_refund_statement(supplies)
    assert summary.invoice_count == 2
    assert summary.cdn_count == 2

    # Inward Taxable = 100k + 200k - 10k + 5k = 295k
    assert summary.total_inward_taxable == Decimal("295000.00")

    # CGST: Gross 9,000 - CN 900 = 8,100
    assert summary.total_gross_cgst == Decimal("9000.00")
    assert summary.total_cdn_adjustment_cgst == Decimal("-900.00")
    assert summary.net_eligible_refund_cgst == Decimal("8100.00")

    # SGST: Gross 9,000 - CN 900 = 8,100
    assert summary.net_eligible_refund_sgst == Decimal("8100.00")

    # IGST: Gross 36,000 + DN 900 = 36,900
    assert summary.total_gross_igst == Decimal("36000.00")
    assert summary.total_cdn_adjustment_igst == Decimal("900.00")
    assert summary.net_eligible_refund_igst == Decimal("36900.00")

    # Cess: 1,000
    assert summary.net_eligible_refund_cess == Decimal("1000.00")

    # Total Net Refund = 8,100 + 8,100 + 36,900 + 1,000 = 54,100
    assert summary.total_net_refund_claimed == Decimal("54100.00")
    assert summary.is_negative_refund_detected is False


def test_aggregate_gstr11_detects_negative_refund():
    """Detect when Credit Notes exceed invoices creating a negative refund state."""
    supplies = [
        {"supply_type": "3A", "taxable_value": 10000, "cgst": 900, "sgst": 900, "igst": 0, "cess": 0},
        # Massive credit note exceeding invoice
        {"supply_type": "3B", "cdn_type": "C", "taxable_value": 20000, "cgst": 1800, "sgst": 1800, "igst": 0, "cess": 0},
    ]
    summary = aggregate_gstr11_refund_statement(supplies)
    assert summary.net_eligible_refund_cgst == Decimal("-900.00")
    assert summary.is_negative_refund_detected is True
