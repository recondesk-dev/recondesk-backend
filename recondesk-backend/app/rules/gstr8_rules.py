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
from datetime import date, datetime
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional, Union

# Statutory transition date for reduced TCS rate (10th July 2024)
# Notification No. 15/2024-Central Tax & Notification No. 01/2024-Integrated Tax:
# - Transactions from 1-Jul-2024 through 9-Jul-2024: 1.0% (0.5% CGST + 0.5% SGST or 1.0% IGST)
# - Transactions from 10-Jul-2024 onward: 0.5% (0.25% CGST + 0.25% SGST or 0.5% IGST)
TCS_STATUTORY_CUTOFF_DATE = "2024-07-10"
TCS_RATE_REDUCED_PERIOD_THRESHOLD = "2024-07"

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def normalize_transaction_date(tx_date: Any, *, strict: bool = True) -> Optional[str]:
    """Normalize transaction date to standard YYYY-MM-DD string format.
    Rejects invalid calendar dates and ambiguous formats instead of guessing.
    """
    if tx_date is None:
        return None
    if isinstance(tx_date, datetime):
        return tx_date.date().isoformat()
    if isinstance(tx_date, date):
        return tx_date.isoformat()
    s = str(tx_date).strip()
    if not s:
        return None

    # Strip time component if ISO 8601 (e.g. 2024-07-09T14:30:00Z)
    if "T" in s:
        s = s.split("T")[0].strip()
    elif " " in s:
        s = s.split(" ")[0].strip()

    # Reject slash formats as ambiguous across locales (e.g. 07/08/2024 could be 7-Jul or 8-Jul)
    if "/" in s:
        if strict:
            raise ValueError(
                f"Ambiguous date format with slashes: '{tx_date}'. "
                "Use standard ISO 'YYYY-MM-DD' or unambiguous hyphenated 'DD-MM-YYYY'."
            )
        return None

    # Standard ISO format: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            if strict:
                raise ValueError(f"Invalid calendar date '{s}' for YYYY-MM-DD: {exc}") from exc
            return None

    # Hyphenated Indian format: DD-MM-YYYY
    if re.match(r"^\d{2}-\d{2}-\d{4}$", s):
        try:
            return datetime.strptime(s, "%d-%m-%Y").date().isoformat()
        except ValueError as exc:
            if strict:
                raise ValueError(f"Invalid calendar date '{s}' for DD-MM-YYYY: {exc}") from exc
            return None

    if strict:
        raise ValueError(
            f"Invalid transaction date format: '{tx_date}'. "
            "Expected valid calendar date in 'YYYY-MM-DD' or 'DD-MM-YYYY' format."
        )
    return None


@dataclass(frozen=True)
class TcsRateStructure:
    period: str
    total_rate_pct: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    notification_reference: str
    requires_review: bool = False
    review_reason: Optional[str] = None


def get_applicable_tcs_rates(
    period: str,
    transaction_date: Optional[Union[str, datetime, date]] = None,
    rate_basis: Optional[str] = None,
) -> TcsRateStructure:
    """Determine statutory TCS rates based on return period, exact transaction date, or verifiable rate basis.

    Statutory Ground Rules:
    - Transactions prior to 10-Jul-2024: 1.0% total (0.5% CGST + 0.5% SGST or 1.0% IGST)
      under Notification No. 52/2018-Central Tax.
    - Transactions from 10-Jul-2024 onward: 0.5% total (0.25% CGST + 0.25% SGST or 0.5% IGST)
      under Notification No. 15/2024-Central Tax & Notification No. 01/2024-Integrated Tax.
    - For July 2024 (2024-07):
      - If transaction_date is provided, exact date determines rate.
      - If verifiable rate_basis is provided ("PRE_CUTOFF" / "POST_CUTOFF"), rate basis is applied.
      - If NEITHER is provided, the record is flagged for review (requires_review=True) to prevent
        silently assuming the reduced rate.
    - For other periods (e.g. post-August 2024 or pre-July 2024), standard statutory rates apply.
    """
    clean = (period or "").strip()
    if "-" in clean:
        parts = clean.split("-")
        norm_period = f"{parts[0]}-{parts[1].zfill(2)}"
    elif len(clean) == 6:
        # MMYYYY -> YYYY-MM
        norm_period = f"{clean[2:6]}-{clean[0:2]}"
    else:
        norm_period = clean

    norm_tx_date = normalize_transaction_date(transaction_date)

    if norm_tx_date:
        if norm_tx_date >= TCS_STATUTORY_CUTOFF_DATE:
            return TcsRateStructure(
                period=norm_period,
                total_rate_pct=Decimal("0.50"),
                cgst_rate=Decimal("0.0025"),  # 0.25%
                sgst_rate=Decimal("0.0025"),  # 0.25%
                igst_rate=Decimal("0.0050"),  # 0.50%
                notification_reference="Notification No. 15/2024-Central Tax (effective 10-Jul-2024)",
            )
        else:
            return TcsRateStructure(
                period=norm_period,
                total_rate_pct=Decimal("1.00"),
                cgst_rate=Decimal("0.0050"),  # 0.50%
                sgst_rate=Decimal("0.0050"),  # 0.50%
                igst_rate=Decimal("0.0100"),  # 1.00%
                notification_reference="Notification No. 52/2018-Central Tax (prior to 10-Jul-2024)",
            )

    # Check for explicit verifiable rate_basis
    if rate_basis:
        basis_upper = str(rate_basis).strip().upper()
        if basis_upper in ("PRE_CUTOFF", "1.0", "1.0%", "1%", "PRIOR_TO_10_JULY"):
            return TcsRateStructure(
                period=norm_period,
                total_rate_pct=Decimal("1.00"),
                cgst_rate=Decimal("0.0050"),
                sgst_rate=Decimal("0.0050"),
                igst_rate=Decimal("0.0100"),
                notification_reference="Notification No. 52/2018-Central Tax (verified pre-cutoff basis)",
            )
        elif basis_upper in ("POST_CUTOFF", "0.5", "0.5%", "0.50", "TEN_JULY_ONWARD"):
            return TcsRateStructure(
                period=norm_period,
                total_rate_pct=Decimal("0.50"),
                cgst_rate=Decimal("0.0025"),
                sgst_rate=Decimal("0.0025"),
                igst_rate=Decimal("0.0050"),
                notification_reference="Notification No. 15/2024-Central Tax (verified post-cutoff basis)",
            )
        else:
            raise ValueError(
                f"Unrecognized verifiable rate_basis: '{rate_basis}'. "
                "Expected 'PRE_CUTOFF' (1.0%) or 'POST_CUTOFF' (0.5%)."
            )

    # For July 2024 specifically: missing both date and rate basis -> requires review!
    if norm_period == "2024-07":
        return TcsRateStructure(
            period=norm_period,
            total_rate_pct=Decimal("0.50"),  # provisional
            cgst_rate=Decimal("0.0025"),
            sgst_rate=Decimal("0.0025"),
            igst_rate=Decimal("0.0050"),
            notification_reference="UNRESOLVED_RATE_BASIS: July 2024 transition period requires transaction_date or verifiable rate basis (1.0% pre-10-Jul vs 0.5% post-10-Jul). Record flagged for review.",
            requires_review=True,
            review_reason="July 2024 transition record missing transaction_date or verifiable rate basis (1.0% pre-10-Jul vs 0.5% post-10-Jul).",
        )

    # August 2024 onwards: strictly 0.50%
    if norm_period > "2024-07":
        return TcsRateStructure(
            period=norm_period,
            total_rate_pct=Decimal("0.50"),
            cgst_rate=Decimal("0.0025"),
            sgst_rate=Decimal("0.0025"),
            igst_rate=Decimal("0.0050"),
            notification_reference="Notification No. 15/2024-Central Tax (effective 10-Jul-2024)",
        )

    # Prior to July 2024: strictly 1.00%
    return TcsRateStructure(
        period=norm_period,
        total_rate_pct=Decimal("1.00"),
        cgst_rate=Decimal("0.0050"),
        sgst_rate=Decimal("0.0050"),
        igst_rate=Decimal("0.0100"),
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
    requires_review: bool = False
    review_reason: Optional[str] = None


def calculate_gstr8_tcs(
    *,
    period: str,
    gross_supplies: float | Decimal,
    returned_supplies: float | Decimal,
    eco_state: str,
    pos: str,
    supplier_state: Optional[str] = None,
    transaction_date: Optional[Union[str, datetime, date]] = None,
    rate_basis: Optional[str] = None,
) -> TcsCalculationResult:
    """Calculate statutory GSTR-8 TCS collection amounts.

    Net Supplies = Gross Supplies - Returned Supplies.
    TCS rate applied according to statutory transaction date if supplied, verifiable rate basis, or period rules:
    - 1.0% (0.5% + 0.5% or 1.0% IGST) prior to 10th July 2024.
    - 0.5% (0.25% + 0.25% or 0.5% IGST) from 10th July 2024 onward.
    - July 2024 requires transaction_date or rate_basis; otherwise flagged for review.
    If net supplies is negative (returns exceed sales), TCS is ₹0.00 for the period with warning flag.
    """
    g_val = Decimal(str(gross_supplies or 0))
    r_val = Decimal(str(returned_supplies or 0))
    net_val = (g_val - r_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    rates = get_applicable_tcs_rates(period, transaction_date=transaction_date, rate_basis=rate_basis)

    # Supply nature: Inter vs Intra state
    comp_state = (supplier_state or eco_state or "").strip()
    clean_pos = (pos or "").strip()

    is_intra = bool(comp_state and clean_pos and comp_state == clean_pos)
    supply_nature = "INTRA_STATE" if is_intra else "INTER_STATE"

    if net_val <= Decimal("0.00"):
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
            requires_review=rates.requires_review,
            review_reason=rates.review_reason,
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
        requires_review=rates.requires_review,
        review_reason=rates.review_reason,
    )


def calculate_gstr8_mixed_period_tcs(
    *,
    period: str,
    pre_cutoff_gross: float | Decimal = 0,
    pre_cutoff_returned: float | Decimal = 0,
    post_cutoff_gross: float | Decimal = 0,
    post_cutoff_returned: float | Decimal = 0,
    eco_state: str,
    pos: str,
    supplier_state: Optional[str] = None,
) -> dict[str, Any]:
    """Calculate blended TCS for a transition period (e.g. July 2024) containing
    both pre-10-July supplies (1.0% rate) and post-10-July supplies (0.5% rate).
    """
    calc_pre = calculate_gstr8_tcs(
        period=period,
        gross_supplies=pre_cutoff_gross,
        returned_supplies=pre_cutoff_returned,
        eco_state=eco_state,
        pos=pos,
        supplier_state=supplier_state,
        transaction_date="2024-07-09",
    )
    calc_post = calculate_gstr8_tcs(
        period=period,
        gross_supplies=post_cutoff_gross,
        returned_supplies=post_cutoff_returned,
        eco_state=eco_state,
        pos=pos,
        supplier_state=supplier_state,
        transaction_date="2024-07-10",
    )
    tot_gross = calc_pre.gross_supplies + calc_post.gross_supplies
    tot_returned = calc_pre.returned_supplies + calc_post.returned_supplies
    tot_net = calc_pre.net_supplies + calc_post.net_supplies
    tot_cgst = calc_pre.tcs_cgst + calc_post.tcs_cgst
    tot_sgst = calc_pre.tcs_sgst + calc_post.tcs_sgst
    tot_igst = calc_pre.tcs_igst + calc_post.tcs_igst
    total_tcs = tot_cgst + tot_sgst + tot_igst

    return {
        "period": period,
        "pre_cutoff": calc_pre,
        "post_cutoff": calc_post,
        "total_gross": tot_gross,
        "total_returned": tot_returned,
        "total_net": tot_net,
        "total_tcs_cgst": tot_cgst,
        "total_tcs_sgst": tot_sgst,
        "total_tcs_igst": tot_igst,
        "total_tcs": total_tcs,
        "effective_blended_rate_pct": (
            (total_tcs / tot_net * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if tot_net > 0 else Decimal("0.00")
        ),
    }
