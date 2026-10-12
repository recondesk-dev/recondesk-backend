"""Statutory Rules & Validation Engine for Form GSTR-5A (OIDAR Services).

Authoritative References:
- Section 14 of the IGST Act, 2017: Special provision for payment of tax by a person providing
  online information and database access or retrieval (OIDAR) services from a place outside India
  to a non-taxable online recipient (NTOR) in India.
- Rule 64 of the CGST Rules, 2017: Form and manner of submission of return in Form GSTR-5A.
- Due Date: 20th of the month following the calendar month in which supplies were made (Rule 64).
- Statutory Tax Head: Cross-border supply to NTOR is deemed inter-State supply under Section 7(5)(a)
  of the IGST Act, 2017 -> Strictly Integrated Tax (IGST) at standard 18% rate.
- Input Tax Credit (ITC): Strictly 0.00 (overseas OIDAR suppliers are NOT entitled to claim ITC).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

OIDAR_STANDARD_IGST_RATE = Decimal("0.18")  # 18% standard rate
OIDAR_DUE_DATE_DAY = 20  # 20th of succeeding month

# Authoritative Statutory Rate Schedules for Form GSTR-5A (OIDAR & Section 14A)
STATUTORY_OIDAR_RATES: dict[Decimal, dict[str, str]] = {
    Decimal("18.0"): {
        "description": "Standard OIDAR Services (cloud computing, streaming, digital content)",
        "notification": "Notification No. 11/2017-Integrated Tax (Rate) Entry 17 (Heading 9984)",
        "effective_date": "2017-07-01",
    },
    Decimal("28.0"): {
        "description": "Specified Actionable Claims / Online Money Gaming by Overseas Suppliers",
        "notification": "Section 14A of IGST Act, 2017 & Notification No. 11/2023-Integrated Tax (Rate)",
        "effective_date": "2023-10-01",
    },
    Decimal("5.0"): {
        "description": "Electronic Books supplied through digital mode",
        "notification": "Notification No. 13/2018-Integrated Tax (Rate) Entry 11B",
        "effective_date": "2018-07-27",
    },
    Decimal("0.0"): {
        "description": "Exempt digital services under statutory exemption notifications",
        "notification": "Notification No. 9/2017-Integrated Tax (Rate) as amended",
        "effective_date": "2017-07-01",
    },
}

VALID_OIDAR_RATE_PERCENTAGES = frozenset(STATUTORY_OIDAR_RATES.keys())


def is_valid_statutory_oidar_rate(rate_pct: float | Decimal) -> bool:
    """Validate whether declared tax rate matches an authoritative GST statutory OIDAR rate schedule."""
    try:
        r = Decimal(str(rate_pct)).quantize(Decimal("0.1"))
        return r in VALID_OIDAR_RATE_PERCENTAGES
    except Exception:
        return False


@dataclass(frozen=True)
class OidarSupplyItem:
    pos: str
    taxable_value: Decimal
    rate_pct: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    total_tax: Decimal


@dataclass(frozen=True)
class OidarSummaryResult:
    period: str
    total_taxable_value: Decimal
    total_igst: Decimal
    total_cess: Decimal
    total_tax_payable: Decimal
    total_amendment_taxable: Decimal
    total_amendment_tax: Decimal
    net_tax_payable: Decimal
    eligible_itc: Decimal  # Strictly Decimal("0.00")
    due_date_day: int
    rule_reference: str


def compute_oidar_tax_for_supply(
    *,
    taxable_value: float | Decimal,
    rate_pct: float | Decimal = 18.0,
    cess_amount: float | Decimal = 0.0,
) -> tuple[Decimal, Decimal, Decimal]:
    """Calculate 18% IGST for an OIDAR supply to an Indian NTOR recipient."""
    t_val = Decimal(str(taxable_value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    r_pct = Decimal(str(rate_pct or 18.0)) / Decimal("100")
    cess = Decimal(str(cess_amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    igst = (t_val * r_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_tax = igst + cess

    return igst, cess, total_tax


def summarize_gstr5a_supplies(
    *,
    period: str,
    table5_supplies: list[dict[str, Any]],
    table5a_amendments: list[dict[str, Any]],
) -> OidarSummaryResult:
    """Compute period summary for Form GSTR-5A (Table 5 & Table 5A).
    
    Strict statutory guarantee:
    Eligible ITC is strictly 0.00 (Section 14 of IGST Act).
    """
    tot_t5_val = Decimal("0.00")
    tot_t5_igst = Decimal("0.00")
    tot_t5_cess = Decimal("0.00")

    for item in table5_supplies:
        val = Decimal(str(item.get("taxable_value") or 0))
        igst = Decimal(str(item.get("igst") or 0))
        cess = Decimal(str(item.get("cess") or 0))
        tot_t5_val += val
        tot_t5_igst += igst
        tot_t5_cess += cess

    tot_t5a_val = Decimal("0.00")
    tot_t5a_tax = Decimal("0.00")

    for item in table5a_amendments:
        val = Decimal(str(item.get("differential_taxable_value") or item.get("taxable_value") or 0))
        igst = Decimal(str(item.get("differential_igst") or item.get("igst") or 0))
        tot_t5a_val += val
        tot_t5a_tax += igst

    tot_taxable = (tot_t5_val + tot_t5a_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tot_igst = (tot_t5_igst + tot_t5a_tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net_payable = tot_igst + tot_t5_cess

    return OidarSummaryResult(
        period=period,
        total_taxable_value=tot_taxable,
        total_igst=tot_igst,
        total_cess=tot_t5_cess.quantize(Decimal("0.01")),
        total_tax_payable=(tot_igst + tot_t5_cess).quantize(Decimal("0.01")),
        total_amendment_taxable=tot_t5a_val.quantize(Decimal("0.01")),
        total_amendment_tax=tot_t5a_tax.quantize(Decimal("0.01")),
        net_tax_payable=net_payable,
        eligible_itc=Decimal("0.00"),  # Strictly zero ITC under Section 14
        due_date_day=OIDAR_DUE_DATE_DAY,
        rule_reference="Rule 64 of CGST Rules, 2017 & Section 14 of IGST Act, 2017 - Due 20th of succeeding month",
    )
