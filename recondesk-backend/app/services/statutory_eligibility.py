"""Statutory ITC eligibility, RCM classification, and Section 16(4) time-bar engine.

Architectural role:
Matching determines whether records correspond (PR <-> GSTR-2B).
This statutory layer determines what that match means for ITC claims,
statutory restrictions (Section 16(4), Section 17(5), Rule 37/37A, PoS),
Reverse Charge (Section 9(3)/9(4)), and GSTR-3B Table 4 allocation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Normalized Enums & Constants
# ══════════════════════════════════════════════════════════════════════════════

class ITCEligibilityStatus(str, Enum):
    """Statutory ITC availability status."""
    AVAILABLE = "ITC_AVAILABLE"
    UNAVAILABLE_GSTR2B = "ITC_UNAVAILABLE_GSTR2B"
    BLOCKED = "ITC_BLOCKED"
    RCM = "ITC_RCM"
    TIME_BARRED = "ITC_TIME_BARRED"


class Section16_4Status(str, Enum):
    """Section 16(4) statutory limitation status."""
    OPEN = "ITC_WINDOW_OPEN"
    EXPIRING = "ITC_WINDOW_EXPIRING"
    TIME_BARRED = "ITC_TIME_BARRED"


class NormalizedIneligibilityReason(str, Enum):
    """Standardized reasons for ITC restriction."""
    POS_RESTRICTED = "POS_RESTRICTED"
    SECTION_16_4_TIME_BARRED = "SECTION_16_4_TIME_BARRED"
    BLOCKED_CREDIT = "BLOCKED_CREDIT"
    RULE37A_NON_FILER = "RULE37A_NON_FILER"
    GSTR2B_ITC_UNAVAILABLE = "GSTR2B_ITC_UNAVAILABLE"


# ══════════════════════════════════════════════════════════════════════════════
# Normalized RCM Detection
# ══════════════════════════════════════════════════════════════════════════════

_TRUE_STRINGS = frozenset({"Y", "YES", "TRUE", "1", "T"})
_FALSE_STRINGS = frozenset({"N", "NO", "FALSE", "0", "F"})


def normalize_rcm_flag(value: Any) -> bool:
    """Normalize reverse charge indicator across diverse ERP and GSTN representations.

    Supports:
        - Booleans: True, False
        - Numerics: 1, 0
        - Strings: "Y", "YES", "TRUE", "1", "T", "N", "NO", "FALSE", "0", "F"
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    s = str(value).strip().upper()
    return s in _TRUE_STRINGS


def detect_rcm_supply(
    g: Optional[Mapping[str, Any]] = None,
    g_rd: Optional[Mapping[str, Any]] = None,
    p: Optional[Mapping[str, Any]] = None,
    p_rd: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Detect whether a supply is subject to Reverse Charge Mechanism (RCM).

    Scans both matcher-normalized and raw database dictionaries across both
    GSTR-2B and Purchase Register records.
    """
    candidates = (
        (g or {}).get("reverse_charge"),
        (g or {}).get("rchrg"),
        (g_rd or {}).get("reverse_charge"),
        (g_rd or {}).get("rchrg"),
        (p or {}).get("reverse_charge"),
        (p or {}).get("rchrg"),
        (p_rd or {}).get("reverse_charge"),
        (p_rd or {}).get("rchrg"),
    )
    for c in candidates:
        if normalize_rcm_flag(c):
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Centralized Section 16(4) Cutoff Calculator
# ══════════════════════════════════════════════════════════════════════════════

def parse_optional_date(val: Any) -> Optional[date]:
    """Parse date from date, datetime, pd.Timestamp, or ISO string."""
    if val is None or val == "":
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    # Check if object has .date() method (e.g. pd.Timestamp)
    if hasattr(val, "date") and callable(getattr(val, "date")):
        try:
            return val.date()
        except Exception:
            pass
    s = str(val).strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T")[0]
    if " " in s:
        s = s.split(" ")[0]
    # Check DD-MM-YYYY or DD/MM/YYYY
    if len(s) == 10 and (s[2] == "-" or s[2] == "/"):
        try:
            d, m, y = int(s[0:2]), int(s[3:5]), int(s[6:10])
            return date(y, m, d)
        except (ValueError, TypeError):
            pass
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def compute_section_16_4_cutoff(invoice_date: date) -> tuple[date, str]:
    """Compute the statutory Section 16(4) cutoff date and FY label for an invoice date.

    Statutory rules:
    - Financial Year: 1st April of Year Y to 31st March of Year Y+1.
    - Post-Finance Act 2022 (FY 2022-23 onwards):
      The deadline is 30th November following the end of the financial year.
    - Pre-Finance Act 2022 (FY 2021-22 and earlier):
      Due date of furnishing September return (20th October following FY end).

    Returns:
        (cutoff_date, fy_label) e.g. (date(2024, 11, 30), "2023-24")
    """
    if invoice_date.month >= 4:
        start_year = invoice_date.year
    else:
        start_year = invoice_date.year - 1
    end_year = start_year + 1
    fy_label = f"{start_year}-{end_year % 100:02d}"

    # Statutory amendment: Finance Act 2022 extended cutoff to 30th November
    if start_year >= 2022:
        cutoff_date = date(end_year, 11, 30)
    else:
        cutoff_date = date(end_year, 10, 20)

    return cutoff_date, fy_label


def evaluate_section_16_4(
    invoice_date: Any,
    reporting_period: Any = None,
    evaluation_date: Optional[date] = None,
) -> tuple[Section16_4Status, Optional[date], Optional[str]]:
    """Evaluate Section 16(4) time-bar limitation for an invoice.

    Parameters:
        invoice_date: Date of the invoice.
        reporting_period: Reconciliation return period (e.g. "2024-11", "2024-12", or date(2024, 12, 1)).
        evaluation_date: Optional explicit evaluation date (defaults to reporting_period end or today).

    Returns:
        (status, cutoff_date, fy_label)
    """
    inv_d = parse_optional_date(invoice_date)
    if not inv_d:
        return Section16_4Status.OPEN, None, None

    cutoff_date, fy_label = compute_section_16_4_cutoff(inv_d)

    # Determine evaluation reference date
    eval_ref: Optional[date] = None
    if evaluation_date:
        eval_ref = evaluation_date
    elif reporting_period:
        rep_d = parse_optional_date(reporting_period)
        if rep_d:
            eval_ref = rep_d
        elif isinstance(reporting_period, str):
            clean_rp = reporting_period.strip()
            # YYYY-MM period format
            if len(clean_rp) == 7 and clean_rp[4] == "-":
                try:
                    y, m = int(clean_rp[:4]), int(clean_rp[5:7])
                    # End of reporting month
                    if m == 12:
                        eval_ref = date(y, 12, 31)
                    else:
                        eval_ref = date(y, m + 1, 1) # first day of next month is after reporting period
                except (ValueError, TypeError):
                    pass

    if not eval_ref:
        return Section16_4Status.OPEN, cutoff_date, fy_label

    if eval_ref > cutoff_date:
        return Section16_4Status.TIME_BARRED, cutoff_date, fy_label
    elif (cutoff_date - eval_ref).days <= 60:
        return Section16_4Status.EXPIRING, cutoff_date, fy_label
    else:
        return Section16_4Status.OPEN, cutoff_date, fy_label


# ══════════════════════════════════════════════════════════════════════════════
# Normalized Ineligibility Reason Classifier
# ══════════════════════════════════════════════════════════════════════════════

def normalize_ineligibility_reason(
    raw_reason: Optional[str],
    is_blocked_credit: bool = False,
    is_non_filer: bool = False,
) -> NormalizedIneligibilityReason:
    """Normalize raw reason string into a standardized statutory reason enum."""
    rsn = (raw_reason or "").strip().lower()

    if is_non_filer or any(k in rsn for k in ("3b", "rule 37a", "non-filer", "non filer")):
        return NormalizedIneligibilityReason.RULE37A_NON_FILER
    if is_blocked_credit or any(k in rsn for k in ("17(5)", "17 (5)", "blocked", "sec 17")):
        return NormalizedIneligibilityReason.BLOCKED_CREDIT
    if any(k in rsn for k in ("pos", "place of supply", "different state")):
        return NormalizedIneligibilityReason.POS_RESTRICTED
    if any(k in rsn for k in ("16(4)", "16 (4)", "time barred", "time-barred", "limitation")):
        return NormalizedIneligibilityReason.SECTION_16_4_TIME_BARRED

    return NormalizedIneligibilityReason.GSTR2B_ITC_UNAVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# Statutory Treatment Dataclass & Classifiers
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StatutoryClassification:
    """Complete statutory classification for an invoice outcome row."""

    itc_status: ITCEligibilityStatus
    is_rcm: bool
    is_itc_available: bool
    normalized_reason: Optional[NormalizedIneligibilityReason]
    source_reason: Optional[str]
    supply_type: str
    liability_table: Optional[str]
    claim_table: Optional[str]
    decision_what: str
    decision_why: str
    decision_next: str
    category: str
    rule37a_flag: bool
    blocked_credit_flag: bool
    section_16_4_status: Optional[Section16_4Status] = None


def classify_statutory_treatment_for_matched(
    g: Mapping[str, Any],
    g_rd: Mapping[str, Any],
    p: Mapping[str, Any],
    p_rd: Mapping[str, Any],
    *,
    is_itc_avail: bool,
    itc_rsn: Optional[str],
    is_r37a: bool,
    is_blocked_credit: bool,
    default_d_what: str,
    default_d_why: str,
    default_d_next: str,
    reporting_period: Any = None,
    evaluation_date: Optional[date] = None,
) -> StatutoryClassification:
    """Classify statutory eligibility and GSTR-3B table allocation for a matched record pair."""
    is_rcm = detect_rcm_supply(g, g_rd, p, p_rd)
    supply_type = "RCM" if is_rcm else "REGULAR"

    # CASE 1: Rule 37A Supplier Non-Filer Risk
    if is_r37a:
        norm_rsn = NormalizedIneligibilityReason.RULE37A_NON_FILER
        r37a_what = "ITC unavailable in GSTR-2B (Supplier GSTR-3B Non-Filer / Rule 37A)"
        r37a_why = (
            itc_rsn
            or "Supplier has not filed GSTR-3B for the tax period (Rule 37A risk). "
            "Ineligible to claim ITC until supplier files return."
        )
        r37a_next = (
            "Hold on IMS and do not claim in GSTR-3B. Follow up with supplier to file GSTR-3B. "
            "Claiming prior to filing triggers mandatory reversal under Rule 37A."
        )
        return StatutoryClassification(
            itc_status=ITCEligibilityStatus.UNAVAILABLE_GSTR2B,
            is_rcm=is_rcm,
            is_itc_available=False,
            normalized_reason=norm_rsn,
            source_reason=itc_rsn,
            supply_type=supply_type,
            liability_table="3.1(d)" if is_rcm else None,
            claim_table=None,
            decision_what=r37a_what,
            decision_why=r37a_why,
            decision_next=r37a_next,
            category="rule37_warnings",
            rule37a_flag=True,
            blocked_credit_flag=False,
        )

    # CASE 2: Ineligible ITC in GSTR-2B (itc_available == False) or Blocked u/s 17(5)
    if not is_itc_avail or is_blocked_credit:
        norm_rsn = normalize_ineligibility_reason(
            itc_rsn,
            is_blocked_credit=is_blocked_credit,
            is_non_filer=False,
        )

        if norm_rsn == NormalizedIneligibilityReason.BLOCKED_CREDIT:
            itc_status = ITCEligibilityStatus.BLOCKED
            claim_table = "4(B)(1)"
            bc_what = f"ITC blocked under Section 17(5){f': {itc_rsn}' if itc_rsn else ''}"
            bc_why = (
                f"Ineligible under Section 17(5) blocked credit ({itc_rsn}). "
                if itc_rsn
                else "Identified as Section 17(5) blocked credit (ineligible goods/services). "
            ) + "Credit cannot be claimed in GSTR-3B."
            bc_next = (
                "Do not claim ITC in GSTR-3B. Discharge RCM cash liability in Table 3.1(d)."
                if is_rcm
                else "Do not claim ITC in GSTR-3B. Verify Section 17(5) applicability."
            )
        elif norm_rsn == NormalizedIneligibilityReason.POS_RESTRICTED:
            itc_status = ITCEligibilityStatus.UNAVAILABLE_GSTR2B
            claim_table = "4(D)(2)"
            bc_what = "ITC unavailable in GSTR-2B (Place of Supply restriction)"
            bc_why = (
                itc_rsn
                or "Inward supply Place of Supply (POS) restriction: intra-state tax paid in another state cannot be claimed."
            )
            bc_next = "Do not claim ITC in GSTR-3B Table 4(A). Reported in Table 4(D)(2) for information only per Circular 170."
        elif norm_rsn == NormalizedIneligibilityReason.SECTION_16_4_TIME_BARRED:
            itc_status = ITCEligibilityStatus.TIME_BARRED
            claim_table = "4(D)(2)"
            bc_what = "ITC unavailable in GSTR-2B (Time-barred under Section 16(4))"
            bc_why = (
                itc_rsn
                or "Supplier uploaded invoice after the Section 16(4) statutory deadline (30th November). Credit barred by limitation."
            )
            bc_next = "Do not claim ITC in GSTR-3B Table 4(A). Statutory limitation expired; supplier follow-up cannot restore entitlement."
        else:
            itc_status = ITCEligibilityStatus.UNAVAILABLE_GSTR2B
            claim_table = None
            bc_what = "ITC marked unavailable in GSTR-2B"
            bc_why = (
                itc_rsn
                or "Authoritative GSTR-2B data marks ITC as unavailable for this invoice."
            )
            bc_next = "Do not claim ITC in GSTR-3B Table 4(A). Ineligible credit per GST portal GSTR-2B."

        return StatutoryClassification(
            itc_status=itc_status,
            is_rcm=is_rcm,
            is_itc_available=False,
            normalized_reason=norm_rsn,
            source_reason=itc_rsn,
            supply_type=supply_type,
            liability_table="3.1(d)" if is_rcm else None,
            claim_table=claim_table,
            decision_what=bc_what,
            decision_why=bc_why,
            decision_next=bc_next,
            category="blocked_credit",
            rule37a_flag=False,
            blocked_credit_flag=True,
        )

    # CASE 3: Reverse Charge Supply (RCM) with ITC Available
    if is_rcm:
        rcm_what = "Inward Supply Liable to Reverse Charge (RCM)"
        rcm_why = (
            "Supply attracts reverse charge under Section 9(3)/9(4) of the CGST Act. "
            "Tax liability arises on recipient."
        )
        rcm_next = (
            "Declare & pay tax liability in cash under GSTR-3B Table 3.1(d). "
            "Avail eligible ITC under Table 4(A)(3) (not ordinary Table 4(A)(5)). "
            "Note: RCM identified; verify cash payment before availing credit."
        )
        return StatutoryClassification(
            itc_status=ITCEligibilityStatus.RCM,
            is_rcm=True,
            is_itc_available=True,
            normalized_reason=None,
            source_reason=None,
            supply_type="RCM",
            liability_table="3.1(d)",
            claim_table="4(A)(3)",
            decision_what=rcm_what,
            decision_why=rcm_why,
            decision_next=rcm_next,
            category="matched",
            rule37a_flag=False,
            blocked_credit_flag=False,
        )

    # CASE 4: Standard Regular Eligible Inward Supply
    return StatutoryClassification(
        itc_status=ITCEligibilityStatus.AVAILABLE,
        is_rcm=False,
        is_itc_available=True,
        normalized_reason=None,
        source_reason=None,
        supply_type="REGULAR",
        liability_table=None,
        claim_table="4(A)(5)",
        decision_what=default_d_what,
        decision_why=default_d_why,
        decision_next=default_d_next,
        category="matched",
        rule37a_flag=False,
        blocked_credit_flag=False,
    )


def classify_statutory_treatment_for_gstr_only(
    g: Mapping[str, Any],
    g_rd: Mapping[str, Any],
    *,
    is_itc_avail: bool,
    itc_rsn: Optional[str],
) -> StatutoryClassification:
    """Classify statutory eligibility for an unmatched GSTR-2B record (missing in books)."""
    is_rcm = detect_rcm_supply(g, g_rd)
    supply_type = "RCM" if is_rcm else "REGULAR"

    if not is_itc_avail:
        norm_rsn = normalize_ineligibility_reason(itc_rsn, is_blocked_credit=False, is_non_filer=False)
        bc_what = f"GSTR-2B Only — ITC Ineligible ({norm_rsn.value})"
        bc_why = (
            itc_rsn
            or f"Invoice appears in GSTR-2B but ITC is marked unavailable by GST Portal ({norm_rsn.value})."
        )
        bc_next = (
            "Do NOT book or claim this ITC in GSTR-3B Table 4(A). Ineligible per GSTR-2B."
        )
        return StatutoryClassification(
            itc_status=ITCEligibilityStatus.UNAVAILABLE_GSTR2B,
            is_rcm=is_rcm,
            is_itc_available=False,
            normalized_reason=norm_rsn,
            source_reason=itc_rsn,
            supply_type=supply_type,
            liability_table="3.1(d)" if is_rcm else None,
            claim_table=None,
            decision_what=bc_what,
            decision_why=bc_why,
            decision_next=bc_next,
            category="blocked_credit",
            rule37a_flag=False,
            blocked_credit_flag=True,
        )

    # Eligible GSTR-only invoice
    claim_table = "4(A)(3)" if is_rcm else "4(A)(5)"
    liability_table = "3.1(d)" if is_rcm else None
    d_what = "Inward Supply Missing in Books" if not is_rcm else "RCM Inward Supply Missing in Books"
    d_why = "Invoice present in GSTR-2B but not found in Purchase Register."
    d_next = (
        "Verify & book in accounting software; pay RCM tax under Table 3.1(d) and claim under Table 4(A)(3)."
        if is_rcm
        else "Verify & book invoice in purchase register to claim missed ITC in GSTR-3B."
    )

    return StatutoryClassification(
        itc_status=ITCEligibilityStatus.RCM if is_rcm else ITCEligibilityStatus.AVAILABLE,
        is_rcm=is_rcm,
        is_itc_available=True,
        normalized_reason=None,
        source_reason=None,
        supply_type=supply_type,
        liability_table=liability_table,
        claim_table=claim_table,
        decision_what=d_what,
        decision_why=d_why,
        decision_next=d_next,
        category="missed_itc",
        rule37a_flag=False,
        blocked_credit_flag=False,
    )


def classify_statutory_treatment_for_pr_only(
    p: Mapping[str, Any],
    p_rd: Mapping[str, Any],
    *,
    reporting_period: Any = None,
    evaluation_date: Optional[date] = None,
) -> StatutoryClassification:
    """Classify statutory eligibility for an unmatched PR record (not found in GSTR-2B)."""
    is_rcm = detect_rcm_supply(p=p, p_rd=p_rd)
    inv_date = p.get("invoice_date") or p_rd.get("invoice_date")

    sec16_4_status, cutoff_date, fy_label = evaluate_section_16_4(
        inv_date,
        reporting_period=reporting_period,
        evaluation_date=evaluation_date,
    )

    if sec16_4_status == Section16_4Status.TIME_BARRED:
        cutoff_str = cutoff_date.strftime("%d %b %Y") if cutoff_date else "30 November"
        fy_str = fy_label or "relevant FY"
        tb_what = f"Time-Barred under Section 16(4) ({fy_str})"
        tb_why = (
            f"Statutory ITC claim deadline for FY {fy_str} expired on {cutoff_str} under Section 16(4). "
            "Credit cannot be availed in GSTR-3B even if supplier uploads invoice now."
        )
        tb_next = (
            "Cannot be claimed in GSTR-3B. Supplier follow-up cannot restore expired statutory entitlement. "
            "Consult client on commercial write-off to Expense/P&L or issuing a commercial debit note to supplier."
        )
        return StatutoryClassification(
            itc_status=ITCEligibilityStatus.TIME_BARRED,
            is_rcm=is_rcm,
            is_itc_available=False,
            normalized_reason=NormalizedIneligibilityReason.SECTION_16_4_TIME_BARRED,
            source_reason=f"Section 16(4) deadline expired on {cutoff_str}",
            supply_type="RCM" if is_rcm else "REGULAR",
            liability_table="3.1(d)" if is_rcm else None,
            claim_table=None,
            decision_what=tb_what,
            decision_why=tb_why,
            decision_next=tb_next,
            category="time_barred_itc",
            rule37a_flag=False,
            blocked_credit_flag=True,
            section_16_4_status=Section16_4Status.TIME_BARRED,
        )

    # Valid open window (OPEN or EXPIRING)
    expiring_note = ""
    if sec16_4_status == Section16_4Status.EXPIRING and cutoff_date:
        expiring_note = f" URGENT: Section 16(4) claim window expires on {cutoff_date.strftime('%d %b %Y')}."

    d_what = "ITC at Risk: Not in GSTR-2B"
    d_why = "Invoice recorded in books but not filed by supplier in GSTR-1."
    d_next = f"Follow up with supplier to file GSTR-1.{expiring_note}"

    return StatutoryClassification(
        itc_status=ITCEligibilityStatus.AVAILABLE,
        is_rcm=is_rcm,
        is_itc_available=True,
        normalized_reason=None,
        source_reason=None,
        supply_type="RCM" if is_rcm else "REGULAR",
        liability_table="3.1(d)" if is_rcm else None,
        claim_table="4(A)(3)" if is_rcm else "4(A)(5)",
        decision_what=d_what,
        decision_why=d_why,
        decision_next=d_next,
        category="wrongful_risk",
        rule37a_flag=False,
        blocked_credit_flag=False,
        section_16_4_status=sec16_4_status,
    )
