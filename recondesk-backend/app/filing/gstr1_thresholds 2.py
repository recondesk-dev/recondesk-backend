"""Named GSTR-1 filing thresholds (law / portal cutovers).

Keep amounts and cutover dates here — eligibility logic must import these
constants rather than inlining rupee figures so a future notification is a
one-line update.
"""

from __future__ import annotations

# B2CL (Table 5): inter-state supplies to unregistered persons above this
# *invoice value* are reported invoice-wise; at/below → consolidated B2CS.
#
# Notification No. 12/2024-Central Tax reduced the limit from ₹2.5L to ₹1L
# with effect from 01-Aug-2024 (filing periods from 2024-08 onward).

B2CL_CUTOVER_PERIOD = "2024-08"  # YYYY-MM inclusive start of ₹1L regime

B2CL_INVOICE_VALUE_BEFORE_PAISE = 25_000_000  # ₹2,50,000
B2CL_INVOICE_VALUE_FROM_PAISE = 10_000_000  # ₹1,00,000

GSTR1_THRESHOLDS = {
    "B2CL_CUTOVER_PERIOD": B2CL_CUTOVER_PERIOD,
    "B2CL_INVOICE_VALUE_BEFORE_PAISE": B2CL_INVOICE_VALUE_BEFORE_PAISE,
    "B2CL_INVOICE_VALUE_FROM_PAISE": B2CL_INVOICE_VALUE_FROM_PAISE,
}


def b2cl_invoice_value_threshold_paise(filing_period: str) -> int:
    """Return B2CL invoice-value threshold in paise for ``YYYY-MM`` period.

    Periods before ``B2CL_CUTOVER_PERIOD`` use ₹2.5L; from that month onward
    use ₹1L. ``filing_period`` must be ``YYYY-MM`` (or longer ISO prefix).
    """
    period = (filing_period or "").strip()[:7]
    if len(period) != 7 or period[4] != "-":
        raise ValueError(
            f"filing_period must be YYYY-MM, got {filing_period!r}"
        )
    if period < B2CL_CUTOVER_PERIOD:
        return B2CL_INVOICE_VALUE_BEFORE_PAISE
    return B2CL_INVOICE_VALUE_FROM_PAISE
