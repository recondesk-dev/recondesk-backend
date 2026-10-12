"""Statutory Rules & Validation Engine for Form GSTR-5 (Non-Resident Taxable Persons).

Authoritative References:
- Section 24(v) of the CGST Act, 2017: Mandatory registration for Non-Resident Taxable Persons.
- Section 27 of the CGST Act, 2017: Special provisions relating to casual taxable person and NRTP.
  - Registration validity: Maximum 90 days (extendable by further 90 days under Section 27(1) proviso).
  - Advance tax deposit: Estimated tax liability required under Section 27(2).
- Rule 63 of the CGST Rules, 2017 (amended via Notification No. 26/2022-Central Tax, 26-Dec-2022):
  - Due date: 13th day of the month succeeding the tax period, or within 7 days after the last
    day of the validity period of registration, whichever is earlier.
- Section 17(5) of the CGST Act, 2017: Input tax credit is NOT available to a non-resident
  taxable person, EXCEPT on goods imported by him (Table 3 Bill of Entry ITC).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


@dataclass(frozen=True)
class NrtpRegistrationStatus:
    is_valid: bool
    registration_start_date: Optional[date]
    registration_expiry_date: Optional[date]
    days_remaining: int
    is_expired: bool
    statutory_due_date: date
    statutory_rule_reference: str
    warning_or_error: Optional[str] = None


@dataclass(frozen=True)
class NrtpTaxSummary:
    total_outward_taxable: Decimal
    total_outward_igst: Decimal
    total_outward_cgst: Decimal
    total_outward_sgst: Decimal
    total_outward_liability: Decimal
    total_import_taxable: Decimal
    total_eligible_import_itc: Decimal
    net_tax_payable: Decimal
    advance_tax_deposited: Decimal
    cash_ledger_balance: Decimal
    is_advance_sufficient: bool
    shortfall_amount: Decimal


def extract_state_code(gstin: str) -> str:
    clean = (gstin or "").strip()
    if len(clean) >= 2 and clean[:2].isdigit():
        return clean[:2]
    return ""


def parse_iso_date(dt_str: Optional[str]) -> Optional[date]:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.split("T")[0]).date()
    except Exception:
        return None


def evaluate_nrtp_registration_and_due_date(
    *,
    period: str,  # YYYY-MM
    registration_start: str | date,
    registration_expiry: str | date,
    reference_date: Optional[date] = None,
) -> NrtpRegistrationStatus:
    """Evaluate NRTP registration validity and compute authoritative due date under Rule 63.
    
    Rule 63 (as amended w.e.f. Dec 2022):
    Filing is due on or before:
    min(13th of month succeeding tax period, expiry_date + 7 days).
    """
    ref_d = reference_date or date.today()
    start_d = registration_start if isinstance(registration_start, date) else parse_iso_date(str(registration_start))
    expiry_d = registration_expiry if isinstance(registration_expiry, date) else parse_iso_date(str(registration_expiry))

    if not start_d or not expiry_d:
        # Fallback to standard 13th of succeeding month
        parts = period.split("-")
        year, month = int(parts[0]), int(parts[1])
        next_m = month + 1 if month < 12 else 1
        next_y = year if month < 12 else year + 1
        std_due = date(next_y, next_m, 13)
        return NrtpRegistrationStatus(
            is_valid=True,
            registration_start_date=start_d,
            registration_expiry_date=expiry_d,
            days_remaining=0,
            is_expired=False,
            statutory_due_date=std_due,
            statutory_rule_reference="Rule 63 of CGST Rules, 2017 (Standard 13th of succeeding month)",
        )

    # Standard 13th of next month
    parts = period.split("-")
    year, month = int(parts[0]), int(parts[1])
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1
    standard_due_date = date(next_y, next_m, 13)

    # Expiry + 7 days
    expiry_plus_7 = expiry_d + timedelta(days=7)

    # Whichever is earlier
    statutory_due_date = min(standard_due_date, expiry_plus_7)
    days_rem = (expiry_d - ref_d).days
    is_exp = ref_d > expiry_d

    warning = None
    if is_exp:
        warning = f"NRTP registration expired on {expiry_d.isoformat()} (Section 27(1))."
    elif days_rem <= 15:
        warning = f"NRTP registration will expire in {days_rem} days on {expiry_d.isoformat()}."

    return NrtpRegistrationStatus(
        is_valid=not is_exp,
        registration_start_date=start_d,
        registration_expiry_date=expiry_d,
        days_remaining=days_rem,
        is_expired=is_exp,
        statutory_due_date=statutory_due_date,
        statutory_rule_reference=(
            f"Rule 63 (Notification No. 26/2022-CT): Earlier of 13th of next month ({standard_due_date.isoformat()}) "
            f"or 7 days post expiry ({expiry_plus_7.isoformat()})"
        ),
        warning_or_error=warning,
    )


def compute_nrtp_tax_summary(
    *,
    outward_records: list[dict[str, Any]],
    import_records: list[dict[str, Any]],
    advance_tax_deposited: float | Decimal = 0.0,
) -> NrtpTaxSummary:
    """Calculate GSTR-5 liability, import credit, and advance tax sufficiency (Section 27(2))."""
    tot_out_taxable = Decimal("0.00")
    tot_igst = Decimal("0.00")
    tot_cgst = Decimal("0.00")
    tot_sgst = Decimal("0.00")

    for rec in outward_records:
        tot_out_taxable += Decimal(str(rec.get("taxable_value") or 0))
        tot_igst += Decimal(str(rec.get("igst") or 0))
        tot_cgst += Decimal(str(rec.get("cgst") or 0))
        tot_sgst += Decimal(str(rec.get("sgst") or 0))

    tot_liability = (tot_igst + tot_cgst + tot_sgst).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Table 3: Import of goods (Bill of Entry ITC)
    tot_imp_taxable = Decimal("0.00")
    tot_imp_itc = Decimal("0.00")

    for rec in import_records:
        tot_imp_taxable += Decimal(str(rec.get("taxable_value") or 0))
        # NRTP can only claim IGST and Cess paid on import of goods (Section 17(5))
        tot_imp_itc += Decimal(str(rec.get("igst_paid") or 0))

    tot_imp_itc = tot_imp_itc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Net tax payable = Liability - Eligible Import ITC
    net_payable = max(Decimal("0.00"), tot_liability - tot_imp_itc).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    adv_dep = Decimal(str(advance_tax_deposited or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    is_sufficient = adv_dep >= net_payable
    shortfall = max(Decimal("0.00"), net_payable - adv_dep)
    rem_balance = max(Decimal("0.00"), adv_dep - net_payable)

    return NrtpTaxSummary(
        total_outward_taxable=tot_out_taxable.quantize(Decimal("0.01")),
        total_outward_igst=tot_igst.quantize(Decimal("0.01")),
        total_outward_cgst=tot_cgst.quantize(Decimal("0.01")),
        total_outward_sgst=tot_sgst.quantize(Decimal("0.01")),
        total_outward_liability=tot_liability,
        total_import_taxable=tot_imp_taxable.quantize(Decimal("0.01")),
        total_eligible_import_itc=tot_imp_itc,
        net_tax_payable=net_payable,
        advance_tax_deposited=adv_dep,
        cash_ledger_balance=rem_balance,
        is_advance_sufficient=is_sufficient,
        shortfall_amount=shortfall,
    )
