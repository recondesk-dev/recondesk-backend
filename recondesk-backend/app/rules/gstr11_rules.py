"""Statutory Rules & Validation Engine for Form GSTR-11 (UIN Inward Supplies & Refund Statement).

Authoritative References:
- Section 55 of the CGST Act, 2017: Refund of taxes paid on inward supplies by specialized agencies
  of the United Nations Organisation, Multilateral Financial Institutions, Consulates, or Embassies of foreign countries.
- Rule 82 of the CGST Rules, 2017: Details of inward supplies of persons having Unique Identity Number (UIN).
  - Sub-rule (1): Every UIN holder claiming refund of taxes paid on inward supplies shall furnish
    details in FORM GSTR-11, along with refund application in FORM GST RFD-10.
  - Sub-rule (2): UIN holders are exempt from furnishing any other GST returns (GSTR-1, GSTR-3B, GSTR-9).
- Due Date: 28th of the month following the relevant tax period/quarter (Rule 82 / portal instructions),
  or prior to filing Form GST RFD-10.
- CRITICAL STATUTORY SAFEGUARD:
  UIN inward tax amounts represent REFUNDABLE TAX CLAIMS under Section 55 and must NEVER be treated
  as ordinary business Input Tax Credit (ITC), posted to an Electronic Credit Ledger, or offset against outward tax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Optional

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
# UIN regex: 15 alphanumeric characters. Common patterns include embassy/consulate codes (e.g., 0717USA00001UN1)
# or standard 15-character structure with 'UN' or letters in positions 12-14.
UIN_REGEX = re.compile(r"^[0-9]{2}[A-Z0-9]{13}$")


class UinSupplyType(str, Enum):
    INWARD_INVOICE_3A = "3A"
    CREDIT_DEBIT_NOTE_3B = "3B"


class CdnType(str, Enum):
    CREDIT_NOTE = "C"
    DEBIT_NOTE = "D"


@dataclass(frozen=True)
class UinRefundSummary:
    total_inward_taxable: Decimal
    total_gross_igst: Decimal
    total_gross_cgst: Decimal
    total_gross_sgst: Decimal
    total_gross_cess: Decimal
    total_cdn_adjustment_igst: Decimal
    total_cdn_adjustment_cgst: Decimal
    total_cdn_adjustment_sgst: Decimal
    total_cdn_adjustment_cess: Decimal
    net_eligible_refund_igst: Decimal
    net_eligible_refund_cgst: Decimal
    net_eligible_refund_sgst: Decimal
    net_eligible_refund_cess: Decimal
    total_net_refund_claimed: Decimal
    invoice_count: int
    cdn_count: int
    is_negative_refund_detected: bool


def validate_uin(uin: str) -> bool:
    """Validate 15-character Unique Identification Number (UIN) format."""
    clean = (uin or "").strip().upper()
    return bool(UIN_REGEX.match(clean) and len(clean) == 15)


def calculate_gstr11_due_date(period_yyyy_mm: str) -> date:
    """Compute default statutory due date for GSTR-11 (28th of succeeding month/quarter).
    
    Format: 'YYYY-MM' -> 28th of next month.
    """
    clean = (period_yyyy_mm or "").strip()
    if "-" in clean:
        parts = clean.split("-")
        year = int(parts[0])
        month = int(parts[1])
    else:
        # MMYYYY
        month = int(clean[:2])
        year = int(clean[2:])
        
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
        
    return date(next_year, next_month, 28)


def validate_uin_inward_supply(
    supply: dict[str, Any],
) -> list[str]:
    """Validate a single GSTR-11 Table 3A/3B inward supply record. Returns error codes."""
    errors: list[str] = []
    
    stype = str(supply.get("supply_type") or "").strip().upper()
    if stype not in {t.value for t in UinSupplyType}:
        errors.append("G11_INVALID_SUPPLY_TYPE")
        
    supplier_gstin = str(supply.get("supplier_gstin") or "").strip().upper()
    if not GSTIN_REGEX.match(supplier_gstin):
        errors.append("G11_INVALID_SUPPLIER_GSTIN")
        
    doc_num = str(supply.get("doc_number") or supply.get("invoice_number") or "").strip()
    if not doc_num:
        errors.append("G11_MISSING_DOC_NUMBER")
        
    doc_date = supply.get("doc_date") or supply.get("invoice_date")
    if not doc_date:
        errors.append("G11_MISSING_DOC_DATE")
        
    taxable_val = Decimal(str(supply.get("taxable_value") or 0))
    if taxable_val < Decimal("0.00"):
        errors.append("G11_NEGATIVE_TAXABLE_VALUE")
        
    igst = Decimal(str(supply.get("igst") or 0))
    cgst = Decimal(str(supply.get("cgst") or 0))
    sgst = Decimal(str(supply.get("sgst") or 0))
    cess = Decimal(str(supply.get("cess") or 0))
    
    if any(x < Decimal("0.00") for x in (igst, cgst, sgst, cess)):
        errors.append("G11_NEGATIVE_TAX_HEAD")
        
    # Intra-state vs Inter-state consistency
    if igst > Decimal("0.00") and (cgst > Decimal("0.00") or sgst > Decimal("0.00")):
        errors.append("G11_MUTUALLY_EXCLUSIVE_HEADS")
        
    if stype == UinSupplyType.CREDIT_DEBIT_NOTE_3B.value:
        cdn_type = str(supply.get("cdn_type") or "").strip().upper()
        if cdn_type not in ("C", "D"):
            errors.append("G11_INVALID_CDN_TYPE")
        orig_inv = str(supply.get("original_invoice_number") or "").strip()
        if not orig_inv:
            errors.append("G11_MISSING_ORIGINAL_INVOICE_REF")
            
    return errors


def aggregate_gstr11_refund_statement(
    supplies: list[dict[str, Any]],
) -> UinRefundSummary:
    """Aggregate GSTR-11 Table 3A (Invoices) and Table 3B (Credit/Debit Notes) into Table 4 refund summary.
    
    Credit notes REDUCE eligible refund.
    Debit notes INCREASE eligible refund.
    Ensures net refund per head is not negative.
    """
    tot_taxable = Decimal("0.00")
    gross_igst = Decimal("0.00")
    gross_cgst = Decimal("0.00")
    gross_sgst = Decimal("0.00")
    gross_cess = Decimal("0.00")
    
    adj_igst = Decimal("0.00")
    adj_cgst = Decimal("0.00")
    adj_sgst = Decimal("0.00")
    adj_cess = Decimal("0.00")
    
    inv_count = 0
    cdn_count = 0
    
    for s in supplies:
        stype = str(s.get("supply_type") or "3A").strip().upper()
        # Only aggregate if eligible for refund under Section 55 (default True)
        if not s.get("is_eligible_for_refund", True):
            continue
            
        t_val = Decimal(str(s.get("taxable_value") or 0))
        i_val = Decimal(str(s.get("igst") or 0))
        c_val = Decimal(str(s.get("cgst") or 0))
        s_val = Decimal(str(s.get("sgst") or 0))
        cs_val = Decimal(str(s.get("cess") or 0))
        
        if stype == UinSupplyType.INWARD_INVOICE_3A.value:
            inv_count += 1
            tot_taxable += t_val
            gross_igst += i_val
            gross_cgst += c_val
            gross_sgst += s_val
            gross_cess += cs_val
        elif stype == UinSupplyType.CREDIT_DEBIT_NOTE_3B.value:
            cdn_count += 1
            cdn_type = str(s.get("cdn_type") or "C").strip().upper()
            multiplier = Decimal("1.00") if cdn_type == "D" else Decimal("-1.00")
            
            tot_taxable += (t_val * multiplier)
            adj_igst += (i_val * multiplier)
            adj_cgst += (c_val * multiplier)
            adj_sgst += (s_val * multiplier)
            adj_cess += (cs_val * multiplier)
            
    net_igst = gross_igst + adj_igst
    net_cgst = gross_cgst + adj_cgst
    net_sgst = gross_sgst + adj_sgst
    net_cess = gross_cess + adj_cess
    
    has_negative = any(x < Decimal("0.00") for x in (net_igst, net_cgst, net_sgst, net_cess))
    total_net = (
        max(Decimal("0.00"), net_igst) +
        max(Decimal("0.00"), net_cgst) +
        max(Decimal("0.00"), net_sgst) +
        max(Decimal("0.00"), net_cess)
    )
    
    return UinRefundSummary(
        total_inward_taxable=tot_taxable.quantize(Decimal("0.01")),
        total_gross_igst=gross_igst.quantize(Decimal("0.01")),
        total_gross_cgst=gross_cgst.quantize(Decimal("0.01")),
        total_gross_sgst=gross_sgst.quantize(Decimal("0.01")),
        total_gross_cess=gross_cess.quantize(Decimal("0.01")),
        total_cdn_adjustment_igst=adj_igst.quantize(Decimal("0.01")),
        total_cdn_adjustment_cgst=adj_cgst.quantize(Decimal("0.01")),
        total_cdn_adjustment_sgst=adj_sgst.quantize(Decimal("0.01")),
        total_cdn_adjustment_cess=adj_cess.quantize(Decimal("0.01")),
        net_eligible_refund_igst=net_igst.quantize(Decimal("0.01")),
        net_eligible_refund_cgst=net_cgst.quantize(Decimal("0.01")),
        net_eligible_refund_sgst=net_sgst.quantize(Decimal("0.01")),
        net_eligible_refund_cess=net_cess.quantize(Decimal("0.01")),
        total_net_refund_claimed=total_net.quantize(Decimal("0.01")),
        invoice_count=inv_count,
        cdn_count=cdn_count,
        is_negative_refund_detected=has_negative,
    )
