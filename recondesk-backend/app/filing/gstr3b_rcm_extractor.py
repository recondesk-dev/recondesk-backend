"""
GSTR-3B RCM (Reverse Charge Mechanism) Field Extractor.

Thin wrapper around GSTR-3B payload / get_gstr3b_details() to extract:
- Table 3.1(d): Inward supplies liable to reverse charge (taxable value + tax amounts)
- Table 4(A)(3): Inward supplies liable to reverse charge (other than import of services) ITC claimed (IGST/CGST/SGST/Cess split)
- Table 4(A)(2): Import of services ITC claimed

Explicitly handles GSTN Cash Ledger limitation: RCM challan payments are not
separable from general liability cash offsets in GST portal responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.parsers.gstr3b_parser import parse_gstr3b

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Data Structures
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GSTR3BRCMData:
    """Extracted RCM figures from GSTR-3B in integer paise."""

    gstin: str
    period: str  # YYYY-MM

    # Table 3.1(d) -- Inward supplies (liable to reverse charge) tax liability declared/paid
    table_31d_taxable_value_paise: int = 0
    table_31d_igst_paise: int = 0
    table_31d_cgst_paise: int = 0
    table_31d_sgst_paise: int = 0
    table_31d_cess_paise: int = 0

    # Table 4(A)(3) -- Inward supplies liable to reverse charge (other than import of services) ITC claimed
    table_4a3_igst_paise: int = 0
    table_4a3_cgst_paise: int = 0
    table_4a3_sgst_paise: int = 0
    table_4a3_cess_paise: int = 0

    # Table 4(A)(2) -- Import of services ITC claimed
    table_4a2_igst_paise: int = 0
    table_4a2_cess_paise: int = 0

    # Portal API limitation metadata
    cash_ledger_rcm_separable: bool = False
    cash_ledger_note: str = (
        "GSTN Cash Ledger does not separate RCM challan payments from general cash ledger liability offsets. "
        "Tax liability declared under Table 3.1(d) represents the self-assessed RCM liability paid via cash ledger offset."
    )

    @property
    def table_31d_total_tax_paise(self) -> int:
        return (
            self.table_31d_igst_paise
            + self.table_31d_cgst_paise
            + self.table_31d_sgst_paise
            + self.table_31d_cess_paise
        )

    @property
    def table_4a3_total_itc_paise(self) -> int:
        return (
            self.table_4a3_igst_paise
            + self.table_4a3_cgst_paise
            + self.table_4a3_sgst_paise
            + self.table_4a3_cess_paise
        )

    @property
    def table_4a2_total_itc_paise(self) -> int:
        return self.table_4a2_igst_paise + self.table_4a2_cess_paise

    @property
    def total_rcm_itc_claimed_paise(self) -> int:
        """Total RCM ITC claimed across domestic 4(A)(3) and import-of-services 4(A)(2)."""
        return self.table_4a3_total_itc_paise + self.table_4a2_total_itc_paise

    def to_dict(self) -> dict[str, Any]:
        return {
            "gstin": self.gstin,
            "period": self.period,
            "table_31d": {
                "taxable_value_paise": self.table_31d_taxable_value_paise,
                "igst_paise": self.table_31d_igst_paise,
                "cgst_paise": self.table_31d_cgst_paise,
                "sgst_paise": self.table_31d_sgst_paise,
                "cess_paise": self.table_31d_cess_paise,
                "total_tax_paise": self.table_31d_total_tax_paise,
            },
            "table_4a3": {
                "igst_paise": self.table_4a3_igst_paise,
                "cgst_paise": self.table_4a3_cgst_paise,
                "sgst_paise": self.table_4a3_sgst_paise,
                "cess_paise": self.table_4a3_cess_paise,
                "total_itc_paise": self.table_4a3_total_itc_paise,
            },
            "table_4a2": {
                "igst_paise": self.table_4a2_igst_paise,
                "cess_paise": self.table_4a2_cess_paise,
                "total_itc_paise": self.table_4a2_total_itc_paise,
            },
            "total_rcm_itc_claimed_paise": self.total_rcm_itc_claimed_paise,
            "cash_ledger_rcm_separable": self.cash_ledger_rcm_separable,
            "cash_ledger_note": self.cash_ledger_note,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Internal Converters
# ══════════════════════════════════════════════════════════════════════════════

def _to_paise(val: Any) -> int:
    """Convert rupees float/int/str to integer paise."""
    if val is None:
        return 0
    try:
        return int(round(float(val) * 100))
    except (TypeError, ValueError):
        return 0


# ══════════════════════════════════════════════════════════════════════════════
# Extraction Engine
# ══════════════════════════════════════════════════════════════════════════════

def extract_gstr3b_rcm_data(raw_or_parsed_3b: Mapping[str, Any]) -> GSTR3BRCMData:
    """
    Extract Table 3.1(d) and Table 4(A)(3) RCM figures from GSTR-3B payload.

    Accepts raw GSTN JSON payload or normalized output from parse_gstr3b().
    """
    if "isup_rev" in raw_or_parsed_3b and "itc_avl_by_source" in raw_or_parsed_3b:
        parsed = dict(raw_or_parsed_3b)
    else:
        parsed = parse_gstr3b(dict(raw_or_parsed_3b))

    gstin = str(parsed.get("gstin", "")).strip().upper()
    period = str(parsed.get("ret_period", ""))

    # Table 3.1(d) Inward supplies liable to RCM
    isup_rev = parsed.get("isup_rev") or {}
    t31d_txval = _to_paise(isup_rev.get("taxable_value"))
    t31d_igst = _to_paise(isup_rev.get("igst"))
    t31d_cgst = _to_paise(isup_rev.get("cgst"))
    t31d_sgst = _to_paise(isup_rev.get("sgst"))
    t31d_cess = _to_paise(isup_rev.get("cess"))

    # Table 4(A)(3) Inward supplies liable to RCM (ISRC)
    itc_sources = parsed.get("itc_avl_by_source") or {}
    isrc = itc_sources.get("ISRC") or {}
    t4a3_igst = _to_paise(isrc.get("igst"))
    t4a3_cgst = _to_paise(isrc.get("cgst"))
    t4a3_sgst = _to_paise(isrc.get("sgst"))
    t4a3_cess = _to_paise(isrc.get("cess"))

    # Table 4(A)(2) Import of services (IMPS)
    imps = itc_sources.get("IMPS") or {}
    t4a2_igst = _to_paise(imps.get("igst"))
    t4a2_cess = _to_paise(imps.get("cess"))

    return GSTR3BRCMData(
        gstin=gstin,
        period=period,
        table_31d_taxable_value_paise=t31d_txval,
        table_31d_igst_paise=t31d_igst,
        table_31d_cgst_paise=t31d_cgst,
        table_31d_sgst_paise=t31d_sgst,
        table_31d_cess_paise=t31d_cess,
        table_4a3_igst_paise=t4a3_igst,
        table_4a3_cgst_paise=t4a3_cgst,
        table_4a3_sgst_paise=t4a3_sgst,
        table_4a3_cess_paise=t4a3_cess,
        table_4a2_igst_paise=t4a2_igst,
        table_4a2_cess_paise=t4a2_cess,
    )
