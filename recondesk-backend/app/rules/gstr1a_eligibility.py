from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal


class Gstr1aEligibility(str, Enum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    REVIEW_REQUIRED = "review_required"


class Gstr1aWindowStatus(str, Enum):
    OPEN = "open"
    WINDOW_CLOSED = "window_closed"
    EXPIRED = "expired"
    NOT_OPEN = "not_open"
    REVIEW_REQUIRED = "review_required"


GSTR1A_ELIGIBILITY_MAP: dict[str, dict] = {
    "G1M_001": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Add the missing invoice via GSTR-1A before GSTR-3B is filed.",
    },
    "G1M_002": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Amend or remove the incorrect record via GSTR-1A.",
    },
    "G1M_003": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the taxable value / tax amount via GSTR-1A.",
    },
    "G1M_004": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the B2B/B2C classification via GSTR-1A.",
    },
    "G1M_005": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the GST rate applied via GSTR-1A.",
    },
    "G1M_006": {
        "eligibility": Gstr1aEligibility.NOT_ELIGIBLE,
        "note": (
            "This invoice belongs to a different filing period. GSTR-1A only "
            "corrects details within the current period — use the amendment "
            "tables (9/10/11) in the correct period's GSTR-1 instead."
        ),
    },
    "G1M_007": {
        "eligibility": Gstr1aEligibility.REVIEW_REQUIRED,
        "note": (
            "GSTIN correction may be amendable via GSTR-1A, but verify manually — "
            "downstream buyer ITC impact may need separate handling."
        ),
    },
    "G1M_008": {
        "eligibility": Gstr1aEligibility.NOT_ELIGIBLE,
        "note": (
            "Series continuity is a structural numbering issue (Rule 46), not "
            "a single invoice correction — GSTR-1A does not apply here."
        ),
    },
    "G1M_009": {
        "eligibility": Gstr1aEligibility.ELIGIBLE,
        "note": "Correct the HSN/SAC code or tax rate via GSTR-1A.",
    },
    "G1M_010": {
        "eligibility": Gstr1aEligibility.REVIEW_REQUIRED,
        "note": (
            "Table 13 is a period-level aggregate, not an invoice-level record — "
            "confirm GSTR-1A's actual coverage before auto-routing this."
        ),
    },
}


def get_gstr1a_eligibility(rule_id: str) -> dict:
    return GSTR1A_ELIGIBILITY_MAP.get(
        rule_id,
        {
            "eligibility": Gstr1aEligibility.REVIEW_REQUIRED,
            "note": "Eligibility not yet reviewed for this rule.",
        },
    )


def _parse_iso_date(raw: date | datetime | str | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    # YYYY-MM-DD or ISO datetime prefix
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_period_yyyy_mm(period: str | None) -> tuple[int, int] | None:
    """Parse tax period as (year, month) from ``YYYY-MM`` or ``MMYYYY``."""
    if not period:
        return None
    s = str(period).strip()
    if len(s) >= 7 and s[4] == "-":
        try:
            y, m = int(s[:4]), int(s[5:7])
            if 1 <= m <= 12:
                return y, m
        except ValueError:
            return None
    if len(s) == 6 and s.isdigit():
        try:
            m, y = int(s[:2]), int(s[2:6])
            if 1 <= m <= 12:
                return y, m
        except ValueError:
            return None
    return None


def gstr1_due_date_monthly(period_year: int, period_month: int) -> date:
    """Statutory GSTR-1 due date for monthly filers: 11th of the following month (Section 37(1))."""
    if period_month == 12:
        return date(period_year + 1, 1, 11)
    return date(period_year, period_month + 1, 11)


def gstr1_due_date_qrmp(period_year: int, period_month: int) -> date:
    """Statutory quarterly GSTR-1 / IFF due date for QRMP filers: 13th of succeeding month."""
    if period_month == 12:
        return date(period_year + 1, 1, 13)
    return date(period_year, period_month + 1, 13)


def gstr3b_due_date_monthly(period_year: int, period_month: int) -> date:
    """Statutory GSTR-3B due date for monthly filers: 20th of the following month."""
    if period_month == 12:
        return date(period_year + 1, 1, 20)
    return date(period_year, period_month + 1, 20)


def compute_gstr1a_window(
    gstr1_filed_date: date | datetime | str | None,
    gstr3b_filed_date: date | datetime | str | None = None,
    *,
    period: str | None = None,
    as_of: date | None = None,
    filing_frequency: Literal["monthly", "qrmp"] = "monthly",
) -> dict[str, Any]:
    """Compute GSTR-1A amendment-window status for a tax period.

    Statutory Invariants (Section 37 & Rule 59(1A)):
    - Form GSTR-1A amends or adds outward supplies relative to Form GSTR-1.
    - If GSTR-1 due date has passed but GSTR-1 remains unfiled, GSTR-1 is OVERDUE.
      Under GST rules and actual GSTN API requirements, Form GSTR-1 must be furnished
      before Form GSTR-1A can be opened, prepared, or filed.
    - Once GSTR-1 is filed, GSTR-1A remains legally open until GSTR-3B is filed.
    - Once GSTR-3B is filed, GSTR-1A is permanently closed for the period.
    """
    g1 = _parse_iso_date(gstr1_filed_date)
    g3 = _parse_iso_date(gstr3b_filed_date)
    today = as_of or date.today()
    ym = _parse_period_yyyy_mm(period)

    g1_due: date | None = None
    if ym is not None:
        g1_due = (
            gstr1_due_date_qrmp(ym[0], ym[1])
            if filing_frequency == "qrmp"
            else gstr1_due_date_monthly(ym[0], ym[1])
        )

    if g3 is not None:
        return {
            "status": Gstr1aWindowStatus.WINDOW_CLOSED.value,
            "is_open": False,
            "is_overdue": False,
            "is_gstr1_overdue": False,
            "days_remaining": 0,
            "gstr1_due_date": g1_due.isoformat() if g1_due else None,
            "gstr3b_due_date": None,
            "gstr1_filed_date": g1.isoformat() if g1 else None,
            "gstr3b_filed_date": g3.isoformat(),
            "note": "GSTR-3B already filed; GSTR-1A window is permanently closed for this period (Rule 59(1A)).",
        }

    if g1 is None:
        is_g1_overdue = (g1_due is not None) and (today > g1_due)
        if is_g1_overdue and g1_due:
            note = (
                f"GSTR-1 due date ({g1_due.isoformat()}) has passed and GSTR-1 remains unfiled. "
                "Under GST rules and actual GSTN API requirements, Form GSTR-1 must be furnished "
                "before Form GSTR-1A can be accessed or submitted."
            )
        elif g1_due:
            note = f"GSTR-1 not yet filed (due on {g1_due.isoformat()}); Form GSTR-1A window opens once GSTR-1 is filed."
        else:
            note = "GSTR-1 not yet filed; GSTR-1A window has not opened."

        return {
            "status": Gstr1aWindowStatus.NOT_OPEN.value,
            "is_open": False,
            "is_overdue": False,
            "is_gstr1_overdue": is_g1_overdue,
            "days_remaining": None,
            "gstr1_due_date": g1_due.isoformat() if g1_due else None,
            "gstr3b_due_date": None,
            "gstr1_filed_date": None,
            "gstr3b_filed_date": None,
            "note": note,
        }


    if filing_frequency == "qrmp":
        return {
            "status": Gstr1aWindowStatus.REVIEW_REQUIRED.value,
            "is_open": True,
            "is_overdue": False,
            "days_remaining": None,
            "gstr3b_due_date": None,
            "gstr1_filed_date": g1.isoformat(),
            "gstr3b_filed_date": None,
            "note": (
                "QRMP filers have different GSTR-3B due dates (typically the "
                "22nd or 24th of the month following the quarter, varying by "
                "state). Monthly 20th-due logic does not apply — confirm the "
                "applicable QRMP due date before relying on days_remaining."
            ),
        }

    ym = _parse_period_yyyy_mm(period)
    if ym is None:
        return {
            "status": Gstr1aWindowStatus.REVIEW_REQUIRED.value,
            "is_open": False,
            "is_overdue": False,
            "days_remaining": None,
            "gstr3b_due_date": None,
            "gstr1_filed_date": g1.isoformat(),
            "gstr3b_filed_date": None,
            "note": "Tax period (YYYY-MM) is required to compute the GSTR-3B due date.",
        }

    due = gstr3b_due_date_monthly(ym[0], ym[1])
    days_remaining = (due - today).days
    is_overdue = days_remaining < 0

    note = (
        f"GSTR-3B due date ({due.isoformat()}) has passed, but Form GSTR-1A remains legally open under Rule 59(1A) until GSTR-3B is filed."
        if is_overdue
        else None
    )

    return {
        "status": Gstr1aWindowStatus.OPEN.value,
        "is_open": True,
        "is_overdue": is_overdue,
        "days_remaining": days_remaining,
        "gstr3b_due_date": due.isoformat(),
        "gstr1_filed_date": g1.isoformat(),
        "gstr3b_filed_date": None,
        "note": note,
    }

