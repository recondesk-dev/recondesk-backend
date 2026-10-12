"""Statutory Rules & Validation Engine for Form GSTR-8 (TCS under Section 52).

Authoritative References:
- Section 52 of the CGST Act, 2017: Tax collection at source by electronic commerce operator.
- Rule 67 of the CGST Rules, 2017: Form and manner of submission of return in Form GSTR-8.
- Notification No. 52/2018-Central Tax (20 Sept 2018): Initial TCS rate of 0.5% CGST + 0.5% SGST (1% total).
- Notification No. 15/2024-Central Tax (10 July 2024) & Notification No. 01/2024-Integrated Tax:
  Reduced TCS rate to 0.25% CGST + 0.25% SGST (0.5% total) effective from 10th July 2024.
- Net Value Calculation: Gross value of taxable supplies minus value of returned supplies.
- Due Date: 10th of the month following the month in which collection was made (Rule 67(1)).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

# Statutory transition date for reduced TCS rate (10th July 2024)
# For monthly periods YYYY-MM, '2024-07' onwards uses 0.5% (0.25% + 0.25%).
# Prior periods use 1.0% (0.5% + 0.5%).
TCS_RATE_REDUCED_PERIOD_THRESHOLD = "2024-07"

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


@dataclass(frozen=True)
class TcsRateStructure:
    period: str
    total_rate_pct: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    notification_reference: str


def get_applicable_tcs_rates(period: str) -> TcsRateStructure:
    """Determine statutory TCS rates based on return period (YYYY-MM or MMYYYY)."""
    clean = (period or "").strip()
    if "-" in clean:
        parts = clean.split("-")
        norm_period = f"{parts[0]}-{parts[1].zfill(2)}"
    elif len(clean) == 6:
        # MMYYYY -> YYYY-MM
        norm_period = f"{clean[2:6]}-{clean[0:2]}"
    else:
        norm_period = clean

    if norm_period >= TCS_RATE_REDUCED_PERIOD_THRESHOLD:
        return TcsRateStructure(
            period=norm_period,
            total_rate_pct=Decimal("0.50"),
            cgst_rate=Decimal("0.0025"),  # 0.25%
            sgst_rate=Decimal("0.0025"),  # 0.25%
            igst_rate=Decimal("0.0050"),  # 0.50%
            notification_reference="Notification No. 15/2024-Central Tax (effective 10-Jul-2024)",
        )
    return TcsRateStructure(
        period=norm_period,
        total_rate_pct=Decimal("1.00"),
        cgst_rate=Decimal("0.0050"),  # 0.50%
        sgst_rate=Decimal("0.0050"),  # 0.50%
        igst_rate=Decimal("0.0100"),  # 1.00%
        notification_reference="Notification No. 52/2018-Central Tax (prior to 10-Jul-2024)",
    )


@dataclass(frozen=True)
class TcsCalculationResult:
    gross_supplies: Decimal
    returned_supplies: Decimal
    net_supplies: Decimal
    is_negative_net: bool
    supply_nature: str  # "INTRA_STATE" or "INTER_STATE"
    rate_structure: TcsRateStructure
    tcs_igst: Decimal
    tcs_cgst: Decimal
    tcs_sgst: Decimal
    total_tcs: Decimal


def calculate_gstr8_tcs(
    *,
    period: str,
    gross_supplies: float | Decimal,
    returned_supplies: float | Decimal,
    eco_state: str,
    pos: str,
    supplier_state: Optional[str] = None,
) -> TcsCalculationResult:
    """Calculate statutory GSTR-8 TCS collection amounts.

    Net Supplies = Gross Supplies - Returned Supplies.
    TCS rate applied according to statutory period rules (0.5% post-July 2024, 1.0% pre-July 2024).
    If net supplies is negative (returns exceed sales), TCS is ₹0.00 for the period with warning flag.
    """
    g_val = Decimal(str(gross_supplies or 0))
    r_val = Decimal(str(returned_supplies or 0))
    net_val = (g_val - r_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    rates = get_applicable_tcs_rates(period)

    # Supply nature: Inter vs Intra state
    # For e-commerce transactions, POS vs Supplier State (or ECO state if unregistered B2C)
    comp_state = (supplier_state or eco_state or "").strip()
    clean_pos = (pos or "").strip()

    is_intra = bool(comp_state and clean_pos and comp_state == clean_pos)
    supply_nature = "INTRA_STATE" if is_intra else "INTER_STATE"

    if net_val <= Decimal("0.00"):
        # Negative or zero net supplies: no positive TCS collected
        return TcsCalculationResult(
            gross_supplies=g_val,
            returned_supplies=r_val,
            net_supplies=net_val,
            is_negative_net=(net_val < Decimal("0.00")),
            supply_nature=supply_nature,
            rate_structure=rates,
            tcs_igst=Decimal("0.00"),
            tcs_cgst=Decimal("0.00"),
            tcs_sgst=Decimal("0.00"),
            total_tcs=Decimal("0.00"),
        )

    if is_intra:
        tcs_cgst = (net_val * rates.cgst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tcs_sgst = (net_val * rates.sgst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tcs_igst = Decimal("0.00")
        total_tcs = tcs_cgst + tcs_sgst
    else:
        tcs_cgst = Decimal("0.00")
        tcs_sgst = Decimal("0.00")
        tcs_igst = (net_val * rates.igst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_tcs = tcs_igst

    return TcsCalculationResult(
        gross_supplies=g_val,
        returned_supplies=r_val,
        net_supplies=net_val,
        is_negative_net=False,
        supply_nature=supply_nature,
        rate_structure=rates,
        tcs_igst=tcs_igst,
        tcs_cgst=tcs_cgst,
        tcs_sgst=tcs_sgst,
        total_tcs=total_tcs,
    )
