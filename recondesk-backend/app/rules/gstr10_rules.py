"""Statutory Rules & Validation Engine for Form GSTR-10 (Final Return).

Authoritative References:
- Section 45 of the CGST Act, 2017: Final Return requirement on cancellation of registration.
  Due date: within 3 months of the date of cancellation OR date of order of cancellation, whichever is LATER.
- Section 29(5) of the CGST Act, 2017: Debit in credit/cash ledger equal to input tax credit
  on inputs in stock / inputs in semi-finished/finished goods or output tax, whichever is higher.
- Rule 44 of the CGST Rules, 2017: Manner of reversal of credit under Section 29(5).
  - Rule 44(1)(b) & Rule 44(6): Capital goods reversal reduced by 5 percentage points per quarter
    or part thereof from invoice date (5-year / 20-quarter useful life), OR tax on transaction value,
    whichever is HIGHER.
  - Rule 44(3): Inward invoices not available (Table 8D) -> Market valuation certified by practicing CA/CMA.
- Rule 81 of the CGST Rules, 2017: Form and manner of submission of Form GSTR-10.
- Exclusions: GSTR-10 is NOT applicable to ISD (Section 20), NRTP (Section 27), Composition (Section 10),
  TDS deductors (Section 51), TCS collectors (Section 52), or UIN holders (Section 55).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Optional

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


class StockItemType(str, Enum):
    INPUTS_IN_STOCK_8A = "8A"
    INPUTS_SEMI_FINISHED_8B = "8B"
    CAPITAL_GOODS_8C = "8C"
    INPUTS_NO_INVOICE_8D = "8D"


@dataclass(frozen=True)
class CapitalGoodsReversalResult:
    original_itc: Decimal
    quarters_elapsed: int
    remaining_useful_life_months: int
    percentage_reduction: Decimal
    reduced_itc: Decimal
    transaction_value_tax: Decimal
    final_reversal_payable: Decimal
    computation_basis: str  # "REDUCED_ITC", "TRANSACTION_VALUE", or "EXPIRED_USEFUL_LIFE"
    is_cancellation_stock_without_supply: bool = True


@dataclass(frozen=True)
class StockReversalSummary:
    total_taxable_value: Decimal
    total_reversal_igst: Decimal
    total_reversal_cgst: Decimal
    total_reversal_sgst: Decimal
    total_reversal_cess: Decimal
    total_reversal_liability: Decimal
    count_8a: int
    count_8b: int
    count_8c: int
    count_8d: int


def calculate_gstr10_due_date(
    cancellation_date: date,
    cancellation_order_date: date,
) -> date:
    """Compute statutory due date under Section 45.
    
    Due Date = Later of (cancellation_date, cancellation_order_date) + 3 calendar months.
    """
    later_date = max(cancellation_date, cancellation_order_date)
    # Add 3 calendar months
    # Handle month rollover properly
    month = later_date.month + 3
    year = later_date.year
    if month > 12:
        month -= 12
        year += 1
    
    # Handle end of month boundary
    import calendar
    max_days = calendar.monthrange(year, month)[1]
    day = min(later_date.day, max_days)
    return date(year, month, day)


def calculate_remaining_useful_life_months(invoice_date: date, cancellation_date: date) -> int:
    """Calculate remaining useful life in months under Rule 44(1)(b).
    
    Total statutory useful life is 5 years = 60 months.
    Under Rule 44(1)(b) illustration:
    Capital goods in use for 4 years, 6 months, 15 days -> remaining useful life = 5 months ignoring part of a month.
    """
    if invoice_date >= cancellation_date:
        return 60
    
    years = cancellation_date.year - invoice_date.year
    months = cancellation_date.month - invoice_date.month
    days = cancellation_date.day - invoice_date.day
    
    if days < 0:
        months -= 1
        has_part_month_used = True
    elif days > 0:
        has_part_month_used = True
    else:
        has_part_month_used = False
        
    total_months_used = years * 12 + months
    if total_months_used < 0:
        return 60
    
    remaining_months = 60 - total_months_used - (1 if has_part_month_used else 0)
    return max(0, min(60, remaining_months))


def calculate_quarters_elapsed(invoice_date: date, cancellation_date: date) -> int:
    """Calculate quarters or part thereof elapsed between invoice date and cancellation date.
    
    Under Rule 44(1)(b) & Rule 44(6), useful life is 5 years = 20 quarters.
    Any fraction of a quarter is counted as a full quarter.
    """
    if invoice_date >= cancellation_date:
        return 0
    
    days_elapsed = (cancellation_date - invoice_date).days
    if days_elapsed <= 0:
        return 0
    
    months_elapsed = (cancellation_date.year - invoice_date.year) * 12 + (cancellation_date.month - invoice_date.month)
    if cancellation_date.day > invoice_date.day:
        months_elapsed += 1
    
    import math
    quarters = math.ceil(months_elapsed / 3.0) if months_elapsed > 0 else 1
    return max(1, quarters)


def compute_capital_goods_reversal(
    *,
    original_itc: Decimal,
    invoice_date: date,
    cancellation_date: date,
    transaction_value_tax: Decimal = Decimal("0.00"),
    is_cancellation_stock_without_supply: Optional[bool] = None,
) -> CapitalGoodsReversalResult:
    """Compute Capital Goods ITC reversal under Section 29(5) and Rule 44(1)(b).
    
    Statutory Safeguards against Inappropriate Application of Supply/Disposal Rules:
    - On cancellation of registration under Section 29(5), capital goods held in stock
      are NOT an outward supply or disposal under Section 7 or Section 18(6).
    - When is_cancellation_stock_without_supply is True (or transaction_value_tax is 0),
      reversal is strictly the ITC attributable to remaining useful life under Rule 44(1)(b).
      Supply/disposal transaction value comparisons do NOT apply to retained cancellation stock.
    - If > 20 quarters / 60 months have elapsed, remaining useful life is 0, and cancellation
      reversal liability is 0.00.
    - If is_cancellation_stock_without_supply is False (actual disposal/sale upon cancellation
      under Section 29(5) proviso), higher of reduced ITC or transaction value tax applies.
    """
    orig = original_itc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tv_tax = transaction_value_tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    quarters = calculate_quarters_elapsed(invoice_date, cancellation_date)
    rem_months = calculate_remaining_useful_life_months(invoice_date, cancellation_date)
    
    # Determine cancellation stock mode
    if is_cancellation_stock_without_supply is None:
        pure_cancellation_stock = (tv_tax == Decimal("0.00"))
    else:
        pure_cancellation_stock = is_cancellation_stock_without_supply
        
    if pure_cancellation_stock:
        # Retention of stock upon cancellation: Rule 44(1)(b) pro-rata monthly useful life
        if rem_months == 0 or quarters >= 20:
            pct_reduction = Decimal("100.00")
            reduced_itc = Decimal("0.00")
            final_payable = Decimal("0.00")
            basis = "EXPIRED_USEFUL_LIFE"
        else:
            reduced_itc = (orig * Decimal(rem_months) / Decimal("60")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            pct_reduction = (((Decimal("60") - Decimal(rem_months)) / Decimal("60")) * Decimal("100.00")).quantize(Decimal("0.01"))
            final_payable = reduced_itc
            basis = "REDUCED_ITC"
    else:
        # Outward disposal/supply comparison under Section 29(5) proviso / Section 18(6) Rule 44(6)
        if quarters >= 20:
            pct_reduction = Decimal("100.00")
            reduced_itc = Decimal("0.00")
        else:
            pct_reduction = (Decimal(quarters) * Decimal("5.00")).quantize(Decimal("0.01"))
            multiplier = Decimal("1.00") - (pct_reduction / Decimal("100.00"))
            reduced_itc = (orig * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if reduced_itc < Decimal("0.00"):
                reduced_itc = Decimal("0.00")

        if reduced_itc >= tv_tax:
            final_payable = reduced_itc
            basis = "REDUCED_ITC"
        else:
            final_payable = tv_tax
            basis = "TRANSACTION_VALUE"
        
    return CapitalGoodsReversalResult(
        original_itc=orig,
        quarters_elapsed=quarters,
        remaining_useful_life_months=rem_months,
        percentage_reduction=pct_reduction,
        reduced_itc=reduced_itc,
        transaction_value_tax=tv_tax,
        final_reversal_payable=final_payable,
        computation_basis=basis,
        is_cancellation_stock_without_supply=pure_cancellation_stock,
    )


def validate_stock_item(
    item: dict[str, Any],
    cancellation_date: Optional[date] = None,
) -> list[str]:
    """Validate a single GSTR-10 closing stock line item. Returns list of error codes."""
    errors: list[str] = []
    
    item_type = str(item.get("item_type") or "").strip().upper()
    if item_type not in {t.value for t in StockItemType}:
        errors.append("G10_INVALID_STOCK_TYPE")
        
    taxable_val = Decimal(str(item.get("taxable_value") or 0))
    if taxable_val < Decimal("0.00"):
        errors.append("G10_NEGATIVE_TAXABLE_VALUE")
        
    rev_igst = Decimal(str(item.get("reverse_igst") or 0))
    rev_cgst = Decimal(str(item.get("reverse_cgst") or 0))
    rev_sgst = Decimal(str(item.get("reverse_sgst") or 0))
    rev_cess = Decimal(str(item.get("reverse_cess") or 0))
    
    if any(x < Decimal("0.00") for x in (rev_igst, rev_cgst, rev_sgst, rev_cess)):
        errors.append("G10_NEGATIVE_TAX_REVERSAL")
        
    # Cannot have both IGST and CGST/SGST on same line item
    if rev_igst > Decimal("0.00") and (rev_cgst > Decimal("0.00") or rev_sgst > Decimal("0.00")):
        errors.append("G10_MUTUALLY_EXCLUSIVE_HEADS")
        
    # For 8A, 8B, 8C: invoice details are required
    if item_type in (StockItemType.INPUTS_IN_STOCK_8A.value, StockItemType.INPUTS_SEMI_FINISHED_8B.value, StockItemType.CAPITAL_GOODS_8C.value):
        inv_num = str(item.get("invoice_number") or "").strip()
        inv_date_raw = item.get("invoice_date")
        if not inv_num:
            errors.append("G10_MISSING_INVOICE_NUMBER")
        if not inv_date_raw:
            errors.append("G10_MISSING_INVOICE_DATE")
        else:
            try:
                inv_d = date.fromisoformat(str(inv_date_raw)) if isinstance(inv_date_raw, str) else inv_date_raw
                if cancellation_date and inv_d > cancellation_date:
                    errors.append("G10_INVOICE_DATE_AFTER_CANCELLATION")
            except Exception:
                errors.append("G10_INVALID_INVOICE_DATE_FORMAT")
                
    # For 8D: invoices are not available, CA certificate is required under Rule 44(3)
    if item_type == StockItemType.INPUTS_NO_INVOICE_8D.value:
        ca_name = str(item.get("ca_name") or "").strip()
        ca_mem_num = str(item.get("ca_membership_number") or "").strip()
        if not ca_name or not ca_mem_num:
            errors.append("G10_MISSING_CA_CERTIFICATE")
            
    return errors


def aggregate_gstr10_stock_reversals(
    items: list[dict[str, Any]],
) -> StockReversalSummary:
    """Aggregate all stock reversal line items by head and count."""
    tot_taxable = Decimal("0.00")
    tot_igst = Decimal("0.00")
    tot_cgst = Decimal("0.00")
    tot_sgst = Decimal("0.00")
    tot_cess = Decimal("0.00")
    
    c_8a = 0
    c_8b = 0
    c_8c = 0
    c_8d = 0
    
    for it in items:
        tot_taxable += Decimal(str(it.get("taxable_value") or 0))
        tot_igst += Decimal(str(it.get("reverse_igst") or 0))
        tot_cgst += Decimal(str(it.get("reverse_cgst") or 0))
        tot_sgst += Decimal(str(it.get("reverse_sgst") or 0))
        tot_cess += Decimal(str(it.get("reverse_cess") or 0))
        
        itype = str(it.get("item_type") or "").strip().upper()
        if itype == StockItemType.INPUTS_IN_STOCK_8A.value:
            c_8a += 1
        elif itype == StockItemType.INPUTS_SEMI_FINISHED_8B.value:
            c_8b += 1
        elif itype == StockItemType.CAPITAL_GOODS_8C.value:
            c_8c += 1
        elif itype == StockItemType.INPUTS_NO_INVOICE_8D.value:
            c_8d += 1
            
    tot_liability = tot_igst + tot_cgst + tot_sgst + tot_cess
    
    return StockReversalSummary(
        total_taxable_value=tot_taxable.quantize(Decimal("0.01")),
        total_reversal_igst=tot_igst.quantize(Decimal("0.01")),
        total_reversal_cgst=tot_cgst.quantize(Decimal("0.01")),
        total_reversal_sgst=tot_sgst.quantize(Decimal("0.01")),
        total_reversal_cess=tot_cess.quantize(Decimal("0.01")),
        total_reversal_liability=tot_liability.quantize(Decimal("0.01")),
        count_8a=c_8a,
        count_8b=c_8b,
        count_8c=c_8c,
        count_8d=c_8d,
    )
