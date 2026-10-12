"""Tests for Form GSTR-10 Statutory Rules and Calculation Engine."""

from datetime import date
from decimal import Decimal
import pytest

from app.rules.gstr10_rules import (
    StockItemType,
    aggregate_gstr10_stock_reversals,
    calculate_gstr10_due_date,
    calculate_quarters_elapsed,
    calculate_remaining_useful_life_months,
    compute_capital_goods_reversal,
    validate_stock_item,
)


def test_gstr10_due_date_calculation():
    """Verify Section 45 due date: later of cancellation date or order date + 3 calendar months."""
    # Scenario 1: Cancellation date later than order date
    canc_date = date(2026, 7, 15)
    order_date = date(2026, 6, 20)
    due = calculate_gstr10_due_date(canc_date, order_date)
    assert due == date(2026, 10, 15)

    # Scenario 2: Order date later than cancellation date
    canc_date = date(2026, 5, 10)
    order_date = date(2026, 8, 25)
    due = calculate_gstr10_due_date(canc_date, order_date)
    assert due == date(2026, 11, 25)

    # Scenario 3: Month boundary / leap year / year rollover
    canc_date = date(2026, 11, 30)
    order_date = date(2026, 11, 15)
    due = calculate_gstr10_due_date(canc_date, order_date)
    # November + 3 months -> February 28
    assert due == date(2027, 2, 28)


def test_capital_goods_reversal_rule44():
    """Verify Rule 44(1)(b) & Rule 44(6) 5 percentage points reduction per quarter."""
    inv_date = date(2025, 4, 10)
    canc_date = date(2026, 4, 10) # Exactly 4 quarters (1 year)
    orig_itc = Decimal("100000.00")

    # 4 quarters = 20% reduction -> 80% remaining ITC payable
    res = compute_capital_goods_reversal(
        original_itc=orig_itc,
        invoice_date=inv_date,
        cancellation_date=canc_date,
        transaction_value_tax=Decimal("50000.00"),
    )
    assert res.quarters_elapsed == 4
    assert res.percentage_reduction == Decimal("20.00")
    assert res.reduced_itc == Decimal("80000.00")
    # Reduced ITC (80,000) > Transaction value tax (50,000) -> Higher applies
    assert res.final_reversal_payable == Decimal("80000.00")
    assert res.computation_basis == "REDUCED_ITC"

    # Scenario 2: Transaction value tax is higher (Rule 44(6))
    res2 = compute_capital_goods_reversal(
        original_itc=orig_itc,
        invoice_date=inv_date,
        cancellation_date=canc_date,
        transaction_value_tax=Decimal("95000.00"),
    )
    assert res2.final_reversal_payable == Decimal("95000.00")
    assert res2.computation_basis == "TRANSACTION_VALUE"

    # Scenario 3: Disposal with transaction value higher after 5 years (Section 29(5) proviso)
    old_inv = date(2020, 1, 1)
    res3 = compute_capital_goods_reversal(
        original_itc=orig_itc,
        invoice_date=old_inv,
        cancellation_date=canc_date,
        transaction_value_tax=Decimal("15000.00"),
        is_cancellation_stock_without_supply=False,
    )
    assert res3.quarters_elapsed >= 20
    assert res3.percentage_reduction == Decimal("100.00")
    assert res3.reduced_itc == Decimal("0.00")
    assert res3.final_reversal_payable == Decimal("15000.00")
    assert res3.computation_basis == "TRANSACTION_VALUE"

    # Scenario 4: Retained cancellation stock under Rule 44(1)(b) (No supply/disposal)
    # Protection: Disposal rules are NOT inappropriately applied to cancellation stock
    res4 = compute_capital_goods_reversal(
        original_itc=orig_itc,
        invoice_date=old_inv,
        cancellation_date=canc_date,
        is_cancellation_stock_without_supply=True,
    )
    assert res4.remaining_useful_life_months == 0
    assert res4.final_reversal_payable == Decimal("0.00")
    assert res4.computation_basis == "EXPIRED_USEFUL_LIFE"

    # Scenario 5: Exact CGST Rule 44(1)(b) illustration:
    # 4 years, 6 months, 15 days elapsed -> 5 months remaining useful life
    inv_cgst = date(2020, 1, 1)
    canc_cgst = date(2024, 7, 16) # 4 yrs, 6 mos, 15 days later
    rem_mos = calculate_remaining_useful_life_months(inv_cgst, canc_cgst)
    assert rem_mos == 5
    res5 = compute_capital_goods_reversal(
        original_itc=Decimal("60000.00"),
        invoice_date=inv_cgst,
        cancellation_date=canc_cgst,
        is_cancellation_stock_without_supply=True,
    )
    assert res5.remaining_useful_life_months == 5
    assert res5.is_cancellation_stock_without_supply is True
    # Reversal = C * 5/60 = 60000 * 5/60 = 5000.00
    assert res5.final_reversal_payable == Decimal("5000.00")


def test_validate_stock_item_success():
    """Verify valid stock items across 8A, 8B, 8C, and 8D."""
    canc_date = date(2026, 9, 30)

    # Valid 8A item
    it_8a = {
        "item_type": "8A",
        "supplier_gstin": "27AABCU9603R1ZX",
        "invoice_number": "INV-100",
        "invoice_date": "2026-08-15",
        "description": "Electronic components",
        "uqc": "NOS",
        "quantity": 50,
        "taxable_value": 50000,
        "reverse_cgst": 4500,
        "reverse_sgst": 4500,
        "reverse_igst": 0,
    }
    assert validate_stock_item(it_8a, cancellation_date=canc_date) == []

    # Valid 8D item with CA certificate
    it_8d = {
        "item_type": "8D",
        "description": "Uninvoiced legacy inventory",
        "uqc": "KGS",
        "quantity": 200,
        "taxable_value": 75000,
        "reverse_igst": 13500,
        "reverse_cgst": 0,
        "reverse_sgst": 0,
        "ca_name": "CA Rajesh Mehta",
        "ca_membership_number": "089123",
    }
    assert validate_stock_item(it_8d, cancellation_date=canc_date) == []


def test_validate_stock_item_statutory_violations():
    """Detect negative values, mutually exclusive tax heads, missing invoices, and missing CA certificate."""
    canc_date = date(2026, 9, 30)

    # 1. 8D missing CA certificate
    it_bad_8d = {
        "item_type": "8D",
        "description": "Stock without invoice",
        "taxable_value": 20000,
        "reverse_igst": 3600,
    }
    errs_8d = validate_stock_item(it_bad_8d, cancellation_date=canc_date)
    assert "G10_MISSING_CA_CERTIFICATE" in errs_8d

    # 2. Mutually exclusive IGST and CGST/SGST on same line
    it_bad_heads = {
        "item_type": "8A",
        "supplier_gstin": "27AABCU9603R1ZX",
        "invoice_number": "INV-1",
        "invoice_date": "2026-05-01",
        "description": "Goods",
        "taxable_value": 10000,
        "reverse_igst": 1800,
        "reverse_cgst": 900,
    }
    errs_heads = validate_stock_item(it_bad_heads, cancellation_date=canc_date)
    assert "G10_MUTUALLY_EXCLUSIVE_HEADS" in errs_heads

    # 3. Invoice date after cancellation date
    it_future_inv = {
        "item_type": "8A",
        "supplier_gstin": "27AABCU9603R1ZX",
        "invoice_number": "INV-2",
        "invoice_date": "2026-10-15", # After canc_date
        "description": "Post-cancellation invoice",
        "taxable_value": 10000,
        "reverse_igst": 1800,
    }
    errs_inv = validate_stock_item(it_future_inv, cancellation_date=canc_date)
    assert "G10_INVOICE_DATE_AFTER_CANCELLATION" in errs_inv


def test_aggregate_gstr10_stock_reversals():
    """Verify multi-item Table 8 aggregation."""
    items = [
        {"item_type": "8A", "taxable_value": 100000, "reverse_cgst": 9000, "reverse_sgst": 9000, "reverse_igst": 0, "reverse_cess": 0},
        {"item_type": "8B", "taxable_value": 50000, "reverse_cgst": 4500, "reverse_sgst": 4500, "reverse_igst": 0, "reverse_cess": 0},
        {"item_type": "8C", "taxable_value": 200000, "reverse_cgst": 0, "reverse_sgst": 0, "reverse_igst": 36000, "reverse_cess": 2000},
        {"item_type": "8D", "taxable_value": 30000, "reverse_cgst": 2700, "reverse_sgst": 2700, "reverse_igst": 0, "reverse_cess": 0},
    ]

    summary = aggregate_gstr10_stock_reversals(items)
    assert summary.total_taxable_value == Decimal("380000.00")
    assert summary.total_reversal_cgst == Decimal("16200.00")
    assert summary.total_reversal_sgst == Decimal("16200.00")
    assert summary.total_reversal_igst == Decimal("36000.00")
    assert summary.total_reversal_cess == Decimal("2000.00")
    assert summary.total_reversal_liability == Decimal("70400.00")
    assert summary.count_8a == 1
    assert summary.count_8b == 1
    assert summary.count_8c == 1
    assert summary.count_8d == 1
