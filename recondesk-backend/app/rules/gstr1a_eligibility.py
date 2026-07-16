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

    The window opens after GSTR-1 is filed and closes when GSTR-3B is filed.
    Until then, ``days_remaining`` counts down to the monthly GSTR-3B due date
    (20th of the month following the return period).

    Parameters
    ----------
    gstr1_filed_date
        Date GSTR-1 was filed for the period. ``None`` → window not open yet.
    gstr3b_filed_date
        Date GSTR-3B was filed. When set, returns ``window_closed`` immediately.
    period
        Tax period as ``YYYY-MM`` or ``MMYYYY``. Required for due-date math.
    as_of
        Reference "today" (defaults to ``date.today()``).
    filing_frequency
        ``"monthly"`` (default) or ``"qrmp"``. QRMP due dates differ by state
        (typically 22nd/24th after quarter-end) and are not auto-computed here.

    Returns
    -------
    dict
        ``status``, ``days_remaining``, ``gstr3b_due_date``, ``note``.
    """
    g1 = _parse_iso_date(gstr1_filed_date)
    g3 = _parse_iso_date(gstr3b_filed_date)
    today = as_of or date.today()

    if g3 is not None:
        return {
            "status": Gstr1aWindowStatus.WINDOW_CLOSED.value,
            "days_remaining": 0,
            "gstr3b_due_date": None,
            "gstr1_filed_date": g1.isoformat() if g1 else None,
            "gstr3b_filed_date": g3.isoformat(),
            "note": "GSTR-3B already filed; GSTR-1A window is closed.",
        }

    if g1 is None:
        return {
            "status": Gstr1aWindowStatus.NOT_OPEN.value,
            "days_remaining": None,
            "gstr3b_due_date": None,
            "gstr1_filed_date": None,
            "gstr3b_filed_date": None,
            "note": "GSTR-1 not yet filed; GSTR-1A window has not opened.",
        }

    if filing_frequency == "qrmp":
        return {
            "status": Gstr1aWindowStatus.REVIEW_REQUIRED.value,
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
            "days_remaining": None,
            "gstr3b_due_date": None,
            "gstr1_filed_date": g1.isoformat(),
            "gstr3b_filed_date": None,
            "note": "Tax period (YYYY-MM) is required to compute the GSTR-3B due date.",
        }

    due = gstr3b_due_date_monthly(ym[0], ym[1])
    days_remaining = (due - today).days
    status = (
        Gstr1aWindowStatus.EXPIRED.value
        if days_remaining < 0
        else Gstr1aWindowStatus.OPEN.value
    )
    return {
        "status": status,
        "days_remaining": days_remaining,
        "gstr3b_due_date": due.isoformat(),
        "gstr1_filed_date": g1.isoformat(),
        "gstr3b_filed_date": None,
        "note": None,
    }
