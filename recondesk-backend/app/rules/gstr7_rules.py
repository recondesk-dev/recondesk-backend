"""Statutory Rules & Validation Engine for Form GSTR-7 (TDS under Section 51).

Authoritative References:
- Section 51 of the CGST Act, 2017: Tax deduction at source by notified entities.
- Rule 66 of the CGST Rules, 2017: Form and manner of submission of return in Form GSTR-7.
- Proviso to Section 51(1): No deduction when location of supplier and place of supply
  is in a State/UT different from the State/UT of registration of the recipient.
- Notification No. 50/2018-Central Tax (13 Sept 2018): Notified entities liable to deduct TDS.
- Statutory Threshold: Total value of supply under a contract exceeds INR 2,50,000 (excluding taxes).
- Statutory Rate: 2% total (1% CGST + 1% SGST for intra-state; 2% IGST for inter-state).
- Due Date: 10th of the month following the month in which deduction was made (Rule 66(1)).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

GSTR7_CONTRACT_THRESHOLD = Decimal("250000.00")  # ₹2.5 Lakhs
GSTR7_TDS_RATE_INTRA_CGST = Decimal("0.01")     # 1%
GSTR7_TDS_RATE_INTRA_SGST = Decimal("0.01")     # 1%
GSTR7_TDS_RATE_INTER_IGST = Decimal("0.02")     # 2%

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


@dataclass(frozen=True)
class TdsCalculationResult:
    contract_exceeds_threshold: bool
    is_proviso_exempt: bool
    is_eligible: bool
    tax_type: str  # "INTRA_STATE", "INTER_STATE", "EXEMPT"
    taxable_amount: Decimal
    tds_igst: Decimal
    tds_cgst: Decimal
    tds_sgst: Decimal
    total_tds: Decimal
    ineligibility_reason: Optional[str] = None


def extract_state_code(gstin: str) -> str:
    """Extract 2-digit state code from GSTIN."""
    clean = (gstin or "").strip()
    if len(clean) >= 2 and clean[:2].isdigit():
        return clean[:2]
    return ""


def validate_gstin_format(gstin: str) -> bool:
    """Validate 15-character GSTIN format."""
    return bool(GSTIN_REGEX.match((gstin or "").strip().upper()))


def evaluate_section_51_proviso(
    deductor_state: str,
    supplier_state: str,
    pos: str,
) -> bool:
    """Check Section 51(1) Proviso Exemption.

    'Provided that no deduction shall be made if the location of the supplier
    and the place of supply is in a State or Union territory which is different
    from the State or, as the case may be, Union territory of registration of
    the recipient.'

    Returns True if EXEMPT from TDS deduction.
    """
    d_st = deductor_state.strip()
    s_st = supplier_state.strip()
    p_st = pos.strip()

    if not d_st or not s_st or not p_st:
        return False

    # Proviso applies when Supplier State == Place of Supply, but Recipient State != Supplier State
    if s_st == p_st and d_st != s_st:
        return True

    return False


def calculate_gstr7_tds(
    *,
    contract_value: float | Decimal,
    amount_paid: float | Decimal,
    deductor_state: str,
    supplier_state: str,
    pos: str,
) -> TdsCalculationResult:
    """Compute statutory GSTR-7 TDS deduction.

    Rules applied:
    1. Contract threshold: Contract value must exceed ₹2,50,000.
    2. Section 51(1) Proviso: Supplier state == POS != Deductor state -> No TDS.
    3. Intra-state supply (Supplier state == POS == Deductor state): 1% CGST + 1% SGST.
    4. Inter-state supply: 2% IGST.
    """
    c_val = Decimal(str(contract_value or 0))
    a_paid = Decimal(str(amount_paid or 0))

    d_st = (deductor_state or "").strip()
    s_st = (supplier_state or "").strip()
    p_st = (pos or "").strip()

    # Rule 1: Contract threshold check
    contract_exceeds = c_val > GSTR7_CONTRACT_THRESHOLD
    if not contract_exceeds:
        return TdsCalculationResult(
            contract_exceeds_threshold=False,
            is_proviso_exempt=False,
            is_eligible=False,
            tax_type="EXEMPT",
            taxable_amount=a_paid,
            tds_igst=Decimal("0.00"),
            tds_cgst=Decimal("0.00"),
            tds_sgst=Decimal("0.00"),
            total_tds=Decimal("0.00"),
            ineligibility_reason=f"Contract value ₹{c_val:,.2f} does not exceed statutory threshold ₹2,50,000 (Section 51(1)).",
        )

    # Rule 2: Section 51(1) Proviso check
    is_proviso_exempt = evaluate_section_51_proviso(d_st, s_st, p_st)
    if is_proviso_exempt:
        return TdsCalculationResult(
            contract_exceeds_threshold=True,
            is_proviso_exempt=True,
            is_eligible=False,
            tax_type="EXEMPT",
            taxable_amount=a_paid,
            tds_igst=Decimal("0.00"),
            tds_cgst=Decimal("0.00"),
            tds_sgst=Decimal("0.00"),
            total_tds=Decimal("0.00"),
            ineligibility_reason=(
                f"Exempt under Proviso to Section 51(1): Supplier location ({s_st}) and Place of Supply ({p_st}) "
                f"are in the same State, but Recipient/Deductor is registered in different State ({d_st})."
            ),
        )

    # Rule 3 & 4: Intra vs Inter State determination
    # In GST, nature of supply is determined by Supplier Location vs Place of Supply
    is_intra = (s_st == p_st)

    if is_intra:
        # Supplier and POS are in same state (which also matches deductor state since proviso was False)
        tax_type = "INTRA_STATE"
        tds_cgst = (a_paid * GSTR7_TDS_RATE_INTRA_CGST).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tds_sgst = (a_paid * GSTR7_TDS_RATE_INTRA_SGST).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tds_igst = Decimal("0.00")
        total_tds = tds_cgst + tds_sgst
    else:
        # Inter-state supply: 2% IGST
        tax_type = "INTER_STATE"
        tds_cgst = Decimal("0.00")
        tds_sgst = Decimal("0.00")
        tds_igst = (a_paid * GSTR7_TDS_RATE_INTER_IGST).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_tds = tds_igst

    return TdsCalculationResult(
        contract_exceeds_threshold=True,
        is_proviso_exempt=False,
        is_eligible=True,
        tax_type=tax_type,
        taxable_amount=a_paid,
        tds_igst=tds_igst,
        tds_cgst=tds_cgst,
        tds_sgst=tds_sgst,
        total_tds=total_tds,
        ineligibility_reason=None,
    )
