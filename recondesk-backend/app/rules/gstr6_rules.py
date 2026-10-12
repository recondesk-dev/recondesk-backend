"""Statutory Rules & Validation Engine for Form GSTR-6 (Input Service Distributor).

Authoritative References:
- Section 20 of the CGST Act, 2017 (read with Finance Act, 2024 amendments / Notification No. 16/2024-CT):
  Manner of distribution of credit by Input Service Distributor.
- Rule 39 of the CGST Rules, 2017: Procedure for distribution of input tax credit by Input Service Distributor.
- Rule 54(1) of the CGST Rules, 2017: ISD Invoice / ISD Credit Note requirements.
- Rule 65 of the CGST Rules, 2017: Form and manner of submission of return in Form GSTR-6.
- Due Date: 13th of the month succeeding the relevant tax period (Rule 65).
- Downstream Treatment: Distributed credit flows into recipient branches' GSTR-2B Table 4(A)(4)
  and must NEVER be claimed as head office ITC or offset against outward liability at ISD level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


@dataclass(frozen=True)
class RecipientTurnoverRatio:
    recipient_gstin: str
    recipient_state: str
    turnover: Decimal
    ratio: Decimal


@dataclass(frozen=True)
class DistributedTaxHead:
    recipient_gstin: str
    recipient_state: str
    is_same_state: bool
    is_eligible: bool
    distributed_igst: Decimal
    distributed_cgst: Decimal
    distributed_sgst: Decimal
    total_distributed: Decimal
    original_cgst_converted_to_igst: Decimal
    original_sgst_converted_to_igst: Decimal


@dataclass(frozen=True)
class IsdDistributionResult:
    total_pool_available: Decimal
    total_pool_eligible: Decimal
    total_pool_ineligible: Decimal
    total_distributed: Decimal
    is_over_distributed: bool
    over_distribution_amount: Decimal
    distributions: list[DistributedTaxHead]
    error_message: Optional[str] = None


def extract_state_code(gstin: str) -> str:
    """Extract 2-digit state code from GSTIN."""
    clean = (gstin or "").strip()
    if len(clean) >= 2 and clean[:2].isdigit():
        return clean[:2]
    return ""


def extract_pan_from_gstin(gstin: str) -> str:
    """Extract 10-character PAN from 15-character GSTIN."""
    clean = (gstin or "").strip().upper()
    if len(clean) >= 12:
        return clean[2:12]
    return ""


def validate_distinct_persons(isd_gstin: str, recipient_gstin: str) -> bool:
    """Verify that ISD and recipient belong to the same entity (distinct persons with same PAN)."""
    isd_pan = extract_pan_from_pan = extract_pan_from_gstin(isd_gstin)
    rec_pan = extract_pan_from_gstin(recipient_gstin)
    return bool(isd_pan and rec_pan and isd_pan == rec_pan)


def compute_turnover_ratios(
    recipient_turnovers: list[dict[str, Any]],
) -> list[RecipientTurnoverRatio]:
    """Compute distribution ratios based on recipient turnovers (Rule 39(1)(d))."""
    total_turnover = Decimal("0.00")
    cleaned_items: list[tuple[str, str, Decimal]] = []

    for item in recipient_turnovers:
        gstin = str(item.get("recipient_gstin") or "").strip().upper()
        st = extract_state_code(gstin)
        t_val = Decimal(str(item.get("turnover") or 0))
        if t_val < Decimal("0.00"):
            t_val = Decimal("0.00")
        total_turnover += t_val
        cleaned_items.append((gstin, st, t_val))

    if total_turnover <= Decimal("0.00"):
        # If total turnover is zero, divide equally
        count = len(cleaned_items)
        equal_ratio = (Decimal("1.00") / Decimal(count)).quantize(Decimal("0.0001")) if count > 0 else Decimal("0")
        return [
            RecipientTurnoverRatio(
                recipient_gstin=g,
                recipient_state=s,
                turnover=t,
                ratio=equal_ratio,
            )
            for g, s, t in cleaned_items
        ]

    ratios: list[RecipientTurnoverRatio] = []
    accumulated_ratio = Decimal("0.00")

    for i, (g, s, t) in enumerate(cleaned_items):
        if i == len(cleaned_items) - 1:
            # Last recipient gets residual ratio to ensure sum == 1.0000 exactly
            r = Decimal("1.0000") - accumulated_ratio
        else:
            r = (t / total_turnover).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            accumulated_ratio += r
        ratios.append(RecipientTurnoverRatio(recipient_gstin=g, recipient_state=s, turnover=t, ratio=r))

    return ratios


def distribute_isd_credit(
    *,
    isd_gstin: str,
    pool_igst: float | Decimal,
    pool_cgst: float | Decimal,
    pool_sgst: float | Decimal,
    is_eligible: bool,
    recipient_turnovers: list[dict[str, Any]],
) -> IsdDistributionResult:
    """Distribute common input service credit to recipient distinct persons (Rule 39).
    
    Statutory Tax-Head Distribution Rules (Rule 39(1)(e) & Rule 39(1)(f)):
    1. If ISD and Recipient are in the SAME State:
       - IGST is distributed as IGST
       - CGST is distributed as CGST
       - SGST is distributed as SGST
    2. If ISD and Recipient are in DIFFERENT States:
       - IGST is distributed as IGST
       - CGST is distributed as IGST!
       - SGST is distributed as IGST!
    """
    isd_state = extract_state_code(isd_gstin)
    p_igst = Decimal(str(pool_igst or 0)).quantize(Decimal("0.01"))
    p_cgst = Decimal(str(pool_cgst or 0)).quantize(Decimal("0.01"))
    p_sgst = Decimal(str(pool_sgst or 0)).quantize(Decimal("0.01"))
    total_pool = p_igst + p_cgst + p_sgst

    ratios = compute_turnover_ratios(recipient_turnovers)
    if not ratios:
        return IsdDistributionResult(
            total_pool_available=total_pool,
            total_pool_eligible=total_pool if is_eligible else Decimal("0.00"),
            total_pool_ineligible=Decimal("0.00") if is_eligible else total_pool,
            total_distributed=Decimal("0.00"),
            is_over_distributed=False,
            over_distribution_amount=Decimal("0.00"),
            distributions=[],
            error_message="No recipient distinct persons specified for credit distribution.",
        )

    def _allocate_head(pool_amount: Decimal) -> list[Decimal]:
        if pool_amount <= Decimal("0.00") or not ratios:
            return [Decimal("0.00")] * len(ratios)
        allocations: list[Decimal] = []
        accum = Decimal("0.00")
        for idx, item in enumerate(ratios):
            if idx == len(ratios) - 1:
                # Deterministic residual paise: guaranteed to sum exactly to pool_amount
                rem = pool_amount - accum
                allocations.append(max(Decimal("0.00"), rem))
            else:
                share = (pool_amount * item.ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                allocations.append(share)
                accum += share
        return allocations

    igst_shares = _allocate_head(p_igst)
    cgst_shares = _allocate_head(p_cgst)
    sgst_shares = _allocate_head(p_sgst)

    distributions: list[DistributedTaxHead] = []
    total_distributed = Decimal("0.00")

    for i, item in enumerate(ratios):
        is_same_state = (item.recipient_state == isd_state)
        share_igst = igst_shares[i]
        share_cgst = cgst_shares[i]
        share_sgst = sgst_shares[i]

        if is_same_state:
            # Rule 39(1)(e): Same state retains respective tax heads
            dist_igst = share_igst
            dist_cgst = share_cgst
            dist_sgst = share_sgst
            conv_cgst = Decimal("0.00")
            conv_sgst = Decimal("0.00")
        else:
            # Rule 39(1)(f): Cross-state distribution converts CGST and SGST into IGST
            dist_igst = share_igst + share_cgst + share_sgst
            dist_cgst = Decimal("0.00")
            dist_sgst = Decimal("0.00")
            conv_cgst = share_cgst
            conv_sgst = share_sgst

        subtotal = dist_igst + dist_cgst + dist_sgst
        total_distributed += subtotal

        distributions.append(
            DistributedTaxHead(
                recipient_gstin=item.recipient_gstin,
                recipient_state=item.recipient_state,
                is_same_state=is_same_state,
                is_eligible=is_eligible,
                distributed_igst=dist_igst,
                distributed_cgst=dist_cgst,
                distributed_sgst=dist_sgst,
                total_distributed=subtotal,
                original_cgst_converted_to_igst=conv_cgst,
                original_sgst_converted_to_igst=conv_sgst,
            )
        )

    # Strictly ZERO tolerance for over-distribution under Rule 39(1)(d)
    is_over = total_distributed > total_pool
    over_amount = (total_distributed - total_pool) if is_over else Decimal("0.00")

    return IsdDistributionResult(
        total_pool_available=total_pool,
        total_pool_eligible=total_pool if is_eligible else Decimal("0.00"),
        total_pool_ineligible=Decimal("0.00") if is_eligible else total_pool,
        total_distributed=total_distributed,
        is_over_distributed=is_over,
        over_distribution_amount=over_amount,
        distributions=distributions,
        error_message=f"Over-distribution detected: distributed ₹{total_distributed:,.2f} exceeds pool ₹{total_pool:,.2f} (Rule 39(1)(d))." if is_over else None,
    )
