"""Late filing detection for matched records."""

from __future__ import annotations

from typing import Any
from datetime import date

def _parse_supprd(val: str) -> tuple[int, int] | None:
    s = str(val).strip()
    if len(s) == 6 and s.isdigit():
        try:
            return int(s[2:]), int(s[:2])
        except ValueError:
            pass
    return None

def _parse_claim_period(val: str) -> tuple[int, int] | None:
    try:
        y, m = val.strip().split("-", 1)
        return int(y), int(m)
    except ValueError:
        return None

def _get_due_date(year: int, month: int) -> date:
    # 11th of the following month
    if month == 12:
        return date(year + 1, 1, 11)
    return date(year, month + 1, 11)

def _parse_supfildt(val: str) -> date | None:
    # Expected format: DD-MM-YYYY
    val = str(val).strip()
    if len(val) == 10 and val[2] == "-" and val[5] == "-":
        try:
            return date(int(val[6:]), int(val[3:5]), int(val[:2]))
        except ValueError:
            pass
    return None

def check_late_filing(
    matched_records: list[dict[str, Any]],
    gstr_raw_by_id: dict[str, dict[str, Any]],
    claim_period: str,
) -> list[dict[str, Any]]:
    """
    Find matched invoices where the supplier's actual filing date (supfildt)
    is after the statutory due date (11th of the month following the return period).
    """
    claim_tuple = _parse_claim_period(claim_period)
    if not claim_tuple:
        return []
    
    # We will compute due date based on the document's supprd, or fallback to claim_period
    default_due_date = _get_due_date(claim_tuple[0], claim_tuple[1])

    results: list[dict[str, Any]] = []

    for m in matched_records:
        gstr_id = str(m.get("gstr_id", ""))
        gstr_raw = gstr_raw_by_id.get(gstr_id) or {}
        
        supfildt_str = gstr_raw.get("supfildt")
        if not supfildt_str:
            continue
            
        supfildt = _parse_supfildt(supfildt_str)
        if not supfildt:
            continue

        supprd = gstr_raw.get("supprd")
        supprd_tuple = _parse_supprd(str(supprd)) if supprd else None
        
        if supprd_tuple:
            due_date = _get_due_date(supprd_tuple[0], supprd_tuple[1])
        else:
            due_date = default_due_date
            
        if supfildt > due_date:
            amount_paise = int(m.get("taxable_amount_paise") or 0)
            # Add total tax paise since Rule 37 is about ITC at risk
            igst = int(m.get("igst_paise") or 0)
            cgst = int(m.get("cgst_paise") or 0)
            sgst = int(m.get("sgst_paise") or 0)
            tax_paise = igst + cgst + sgst
            if tax_paise == 0:
                tax_paise = int(m.get("total_tax_paise") or 0)
            
            results.append(
                {
                    "pr_id": m.get("pr_id"),
                    "gstr_id": gstr_id,
                    "supplier_gstin": m.get("supplier_gstin"),
                    "invoice_number": m.get("invoice_number_normalized"),
                    "claim_period": claim_period,
                    "actual_filing_date": supfildt.isoformat(),
                    "due_date": due_date.isoformat(),
                    "amount_paise": amount_paise,
                    "itc_at_risk_paise": tax_paise,
                    "status": "LATE_FILING",
                }
            )

    return results
