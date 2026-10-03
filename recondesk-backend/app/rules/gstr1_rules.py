"""Central domain rules and period-aware resolvers for GSTR-1 reconciliation.

Law references:
- Notification No. 12/2024-Central Tax (effective 01-Aug-2024):
  Reduced B2CL threshold from ₹2.5L to ₹1L for inter-state supplies to unregistered persons.
- Table 12 HSN outward bifurcation (effective May 2025):
  HSN-wise outward supplies bifurcated into B2B and B2C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.normalizer import normalize_period_to_yyyy_mm

# Threshold constants in paise (100 paise = ₹1)
B2CL_CUTOVER_PERIOD = "2024-08"
B2CL_THRESHOLD_BEFORE_PAISE = 25_000_000  # ₹2,50,000
B2CL_THRESHOLD_FROM_PAISE = 10_000_000   # ₹1,00,000

# May 2025 cutover for B2B vs B2C Table 12 HSN reporting
HSN_BIFURCATION_CUTOVER_PERIOD = "2025-05"

# Canonical invoice date tolerance for GSTR-1 matching (2 days)
GSTR1_INVOICE_DATE_TOLERANCE_DAYS: int = 2


@dataclass(frozen=True)
class GSTR1Rules:
    """Immutable statutory rules for a specific return period."""
    return_period: str  # Normalised "YYYY-MM"
    b2cl_threshold_paise: int
    b2cl_threshold_rupees: float
    hsn_bifurcation_active: bool
    b2cs_aggregation_dimensions: tuple[str, ...] = ("pos", "rate", "sply_ty")
    invoice_date_tolerance_days: int = GSTR1_INVOICE_DATE_TOLERANCE_DAYS

    def is_b2cl(
        self,
        *,
        inv_val_paise: int,
        is_interstate: bool,
        is_registered: bool,
    ) -> bool:
        """B2CL: Interstate supplies to unregistered persons where invoice value > threshold."""
        if is_registered:
            return False
        return is_interstate and (inv_val_paise > self.b2cl_threshold_paise)

    def is_b2cs(
        self,
        *,
        inv_val_paise: int,
        is_interstate: bool,
        is_registered: bool,
    ) -> bool:
        """B2CS: Intrastate supplies to unregistered persons, OR interstate supplies <= threshold."""
        if is_registered:
            return False
        if not is_interstate:
            return True
        return inv_val_paise <= self.b2cl_threshold_paise


def get_gstr1_rules(return_period: str | None = None) -> GSTR1Rules:
    """Resolve applicable GST statutory rules based on return period.

    Parameters
    ----------
    return_period : str | None
        Filing period in any common format ('YYYY-MM', 'MMYYYY', 'MM-YYYY', 'YYYYMM').
        If omitted or invalid, defaults to current regime (post-August 2024).

    Returns
    -------
    GSTR1Rules
        Resolved statutory rules object with period-aware thresholds.
    """
    period_norm = ""
    if return_period and str(return_period).strip():
        s = str(return_period).strip()
        try:
            period_norm = normalize_period_to_yyyy_mm(s)
        except Exception:
            # Fallback normalisation
            digits = re.sub(r"\D", "", s)
            if len(digits) == 6:
                # Could be MMYYYY or YYYYMM
                if int(digits[:2]) <= 12 and int(digits[2:]) >= 2017:
                    period_norm = f"{digits[2:]}-{digits[:2]}"
                elif int(digits[:4]) >= 2017 and int(digits[4:]) <= 12:
                    period_norm = f"{digits[:4]}-{digits[4:]}"
            elif len(s) >= 7 and s[:4].isdigit() and s[4] == "-":
                period_norm = s[:7]

    if not period_norm:
        # Default to current law (2024-08 onwards)
        period_norm = "2026-09"

    if period_norm < B2CL_CUTOVER_PERIOD:
        b2cl_threshold = B2CL_THRESHOLD_BEFORE_PAISE
    else:
        b2cl_threshold = B2CL_THRESHOLD_FROM_PAISE

    hsn_bifurcated = period_norm >= HSN_BIFURCATION_CUTOVER_PERIOD

    return GSTR1Rules(
        return_period=period_norm,
        b2cl_threshold_paise=b2cl_threshold,
        b2cl_threshold_rupees=b2cl_threshold / 100.0,
        hsn_bifurcation_active=hsn_bifurcated,
        b2cs_aggregation_dimensions=("pos", "rate", "sply_ty"),
    )
