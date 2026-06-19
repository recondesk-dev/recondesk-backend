"""Late filing detection for matched records."""

from __future__ import annotations

from typing import Any

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

def check_late_filing(
    matched_records: list[dict[str, Any]],
    gstr_raw_by_id: dict[str, dict[str, Any]],
    claim_period: str,
) -> list[dict[str, Any]]:
    """
    Find matched invoices where the supplier's actual filing period (supprd)
    differs from the run's claim period.
    """
    claim_tuple = _parse_claim_period(claim_period)
    if not claim_tuple:
        return []

    results: list[dict[str, Any]] = []

    for m in matched_records:
        gstr_id = str(m.get("gstr_id", ""))
        gstr_raw = gstr_raw_by_id.get(gstr_id) or {}
        
        supprd = gstr_raw.get("supprd")
        if not supprd:
            continue
            
        supprd_str = str(supprd).strip()
        supprd_tuple = _parse_supprd(supprd_str)
        
        if supprd_tuple and supprd_tuple != claim_tuple:
            amount_paise = int(m.get("taxable_amount_paise") or 0)
            results.append(
                {
                    "gstr_id": gstr_id,
                    "supplier_gstin": m.get("supplier_gstin"),
                    "invoice_number": m.get("invoice_number_normalized"),
                    "claim_period": claim_period,
                    "actual_filing_period": supprd_str,
                    "amount_paise": amount_paise,
                }
            )

    return results
