"""
RCM (Reverse Charge Mechanism) Three-Way Tie-Out Engine.

Performs a 3-way reconciliation per GSTIN per period comparing:
  A. Purchase Register (PR) RCM-applicable inward supplies (from rcm_detector)
  B. GSTR-3B Table 3.1(d) RCM liability declared & paid (from gstr3b_rcm_extractor)
  C. GSTR-3B Table 4(A)(3) [& 4(A)(2)] RCM ITC claimed (from gstr3b_rcm_extractor)

Emits standard compliance mismatch results (WHAT-WHY-NEXT contract) compatible with
the ReconDesk decision layer and tie-out UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.filing.gstr3b_rcm_extractor import GSTR3BRCMData, extract_gstr3b_rcm_data
from app.reconciliation.rcm_detector import detect_rcm_inward_supplies
from app.rules.gstr1_mismatch_rules import MismatchResult, MismatchSeverity, _rs

logger = logging.getLogger(__name__)

# Default tolerance: ₹1 (100 paise)
DEFAULT_TOLERANCE_PAISE: int = 100

# ══════════════════════════════════════════════════════════════════════════════
# Flag Categories / Reason Codes
# ══════════════════════════════════════════════════════════════════════════════

REASON_RCM_UNDERPAID = "REASON_RCM_UNDERPAID"
REASON_RCM_ITC_BEFORE_PAYMENT = "REASON_RCM_ITC_BEFORE_PAYMENT"
REASON_RCM_ITC_NOT_CLAIMED = "REASON_RCM_ITC_NOT_CLAIMED"
REASON_RCM_TIMING_MISMATCH = "REASON_RCM_TIMING_MISMATCH"


# ══════════════════════════════════════════════════════════════════════════════
# Result Dataclass (Envelope mirroring tie_out result structure)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RCMVariance:
    """A specific variance item in the 3-way tie-out."""

    reason_code: str
    description: str
    diff_paise: int
    pr_tax_paise: int
    gstr3b_31d_tax_paise: int
    gstr3b_rcm_itc_paise: int


@dataclass
class RCMTieOutResult:
    """Complete envelope result for RCM 3-way tie-out."""

    gstin: str
    ret_period: str
    is_clean: bool

    # PR detected totals
    pr_rcm_taxable_paise: int
    pr_rcm_tax_paise: int
    pr_flagged_count: int
    pr_flagged_rows: list[dict[str, Any]]

    # 3B declared totals
    gstr3b_31d_taxable_paise: int
    gstr3b_31d_tax_paise: int
    gstr3b_4a3_itc_paise: int
    gstr3b_4a2_itc_paise: int
    total_gstr3b_rcm_itc_paise: int

    # Results
    variances: list[RCMVariance] = field(default_factory=list)
    mismatches: list[MismatchResult] = field(default_factory=list)
    summary_by_reason: dict[str, int] = field(default_factory=dict)
    cash_ledger_note: str = ""

    def summary_dict(self) -> dict[str, Any]:
        """Flat envelope dict matching existing tie-out JSON shapes."""
        return {
            "gstin": self.gstin,
            "ret_period": self.ret_period,
            "is_clean": self.is_clean,
            "summary_by_reason": self.summary_by_reason,
            "pr_summary": {
                "taxable_value_paise": self.pr_rcm_taxable_paise,
                "taxable_value": _rs(self.pr_rcm_taxable_paise),
                "total_tax_paise": self.pr_rcm_tax_paise,
                "total_tax": _rs(self.pr_rcm_tax_paise),
                "flagged_count": self.pr_flagged_count,
            },
            "gstr3b_summary": {
                "table_31d_taxable_value_paise": self.gstr3b_31d_taxable_paise,
                "table_31d_taxable_value": _rs(self.gstr3b_31d_taxable_paise),
                "table_31d_tax_paise": self.gstr3b_31d_tax_paise,
                "table_31d_tax": _rs(self.gstr3b_31d_tax_paise),
                "table_4a3_itc_paise": self.gstr3b_4a3_itc_paise,
                "table_4a3_itc": _rs(self.gstr3b_4a3_itc_paise),
                "table_4a2_itc_paise": self.gstr3b_4a2_itc_paise,
                "table_4a2_itc": _rs(self.gstr3b_4a2_itc_paise),
                "total_rcm_itc_claimed_paise": self.total_gstr3b_rcm_itc_paise,
                "total_rcm_itc_claimed": _rs(self.total_gstr3b_rcm_itc_paise),
            },
            "variances": [
                {
                    "reason_code": v.reason_code,
                    "description": v.description,
                    "diff_paise": v.diff_paise,
                    "diff": _rs(abs(v.diff_paise)),
                    "pr_tax": _rs(v.pr_tax_paise),
                    "gstr3b_31d_tax": _rs(v.gstr3b_31d_tax_paise),
                    "gstr3b_rcm_itc": _rs(v.gstr3b_rcm_itc_paise),
                }
                for v in self.variances
            ],
            "flagged_rows": [
                {
                    "invoice_number": r.get("invoice_number"),
                    "supplier_gstin": r.get("supplier_gstin"),
                    "supplier_name": r.get("supplier_name"),
                    "invoice_date": r.get("invoice_date"),
                    "hsn_sac": r.get("hsn_sac"),
                    "taxable_value": _rs(r.get("taxable_value_paise", 0)),
                    "total_tax": _rs(r.get("total_tax_paise", 0)),
                    "category": r.get("category"),
                    "reason_code": r.get("reason_code"),
                    "confidence": r.get("confidence"),
                    "pending_review": r.get("pending_review"),
                    "explanation": r.get("explanation"),
                }
                for r in self.pr_flagged_rows
            ],
            "cash_ledger_note": self.cash_ledger_note,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Engine Logic
# ══════════════════════════════════════════════════════════════════════════════

def reconcile_rcm_three_way(
    *,
    pr_records: Sequence[Mapping[str, Any]] | None = None,
    detected_rcm_rows: list[dict[str, Any]] | None = None,
    gstr3b_rcm_data: GSTR3BRCMData | Mapping[str, Any],
    cumulative_31d_paid_to_date_paise: int | None = None,
    tolerance_paise: int = DEFAULT_TOLERANCE_PAISE,
) -> RCMTieOutResult:
    """
    Execute three-way RCM tie-out reconciliation.

    Parameters
    ----------
    pr_records : Sequence[Mapping[str, Any]] | None
        Raw purchase register records (optional if detected_rcm_rows provided).
    detected_rcm_rows : list[dict[str, Any]] | None
        Pre-detected RCM rows from detect_rcm_inward_supplies (optional if pr_records provided).
    gstr3b_rcm_data : GSTR3BRCMData | Mapping[str, Any]
        Extracted GSTR-3B RCM object or raw GSTR-3B dict.
    cumulative_31d_paid_to_date_paise : int | None
        Cumulative Table 3.1(d) RCM liability paid in 3B to date (default: current period 3.1d paid).
    tolerance_paise : int
        Rounding tolerance in paise (default: 100 = ₹1).
    """
    # 1. Resolve 3B data
    if isinstance(gstr3b_rcm_data, GSTR3BRCMData):
        g3b = gstr3b_rcm_data
    else:
        g3b = extract_gstr3b_rcm_data(gstr3b_rcm_data)

    gstin = g3b.gstin
    period = g3b.period

    # 2. Resolve PR detected rows
    if detected_rcm_rows is not None:
        flagged_rows = list(detected_rcm_rows)
    elif pr_records is not None:
        flagged_rows = detect_rcm_inward_supplies(pr_records)
    else:
        flagged_rows = []

    pr_taxable_paise = sum(r.get("taxable_value_paise", 0) for r in flagged_rows)
    pr_tax_paise = sum(r.get("total_tax_paise", 0) for r in flagged_rows)
    pr_flagged_count = len(flagged_rows)

    # 3. Unpack 3B figures
    g3b_31d_taxable = g3b.table_31d_taxable_value_paise
    g3b_31d_tax = g3b.table_31d_total_tax_paise
    g3b_4a3_itc = g3b.table_4a3_total_itc_paise
    g3b_4a2_itc = g3b.table_4a2_total_itc_paise
    g3b_total_rcm_itc = g3b.total_rcm_itc_claimed_paise

    cum_paid_paise = (
        cumulative_31d_paid_to_date_paise
        if cumulative_31d_paid_to_date_paise is not None
        else g3b_31d_tax
    )

    variances: list[RCMVariance] = []
    mismatches: list[MismatchResult] = []
    summary_by_reason: dict[str, int] = {
        REASON_RCM_UNDERPAID: 0,
        REASON_RCM_ITC_BEFORE_PAYMENT: 0,
        REASON_RCM_ITC_NOT_CLAIMED: 0,
        REASON_RCM_TIMING_MISMATCH: 0,
    }

    # ── CHECK 1: REASON_RCM_UNDERPAID ─────────────────────────────────────────
    # PR detected RCM liability higher than GSTR-3B Table 3.1(d) declared/paid
    underpaid_diff = pr_tax_paise - g3b_31d_tax
    if underpaid_diff > tolerance_paise:
        summary_by_reason[REASON_RCM_UNDERPAID] += 1
        desc = (
            f"RCM tax liability underpaid in GSTR-3B Table 3.1(d) for {period}: "
            f"Purchase register detects {_rs(pr_tax_paise)} RCM tax but GSTR-3B 3.1(d) "
            f"declares {_rs(g3b_31d_tax)} (shortfall of {_rs(underpaid_diff)})."
        )
        variances.append(
            RCMVariance(
                reason_code=REASON_RCM_UNDERPAID,
                description=desc,
                diff_paise=underpaid_diff,
                pr_tax_paise=pr_tax_paise,
                gstr3b_31d_tax_paise=g3b_31d_tax,
                gstr3b_rcm_itc_paise=g3b_total_rcm_itc,
            )
        )
        mismatches.append(
            MismatchResult(
                mismatch_type=REASON_RCM_UNDERPAID,  # type: ignore
                severity=(
                    MismatchSeverity.CRITICAL
                    if underpaid_diff > 50000
                    else MismatchSeverity.HIGH
                ),
                decision_what=f"RCM tax underpaid by {_rs(underpaid_diff)} in GSTR-3B 3.1(d)",
                decision_why=(
                    f"Books show {_rs(pr_tax_paise)} RCM-applicable tax across {pr_flagged_count} "
                    f"inward transactions, but GSTR-3B Table 3.1(d) paid only {_rs(g3b_31d_tax)}. "
                    f"Failure to pay RCM liability attracts mandatory interest under Section 50."
                ),
                decision_next=(
                    f"Issue self-invoice and pay {_rs(underpaid_diff)} RCM liability in cash ledger "
                    f"under Table 3.1(d) in the upcoming GSTR-3B return."
                ),
                rule_id="RCM_UNDERPAID",
                gst_ref="Section 9(3)/9(4) CGST Act & Notification 13/2017-CT(Rate)",
                details={
                    "pr_tax_paise": pr_tax_paise,
                    "gstr3b_31d_tax_paise": g3b_31d_tax,
                    "diff_paise": underpaid_diff,
                },
            )
        )

    # ── CHECK 2: REASON_RCM_ITC_BEFORE_PAYMENT ──────────────────────────────
    # Table 4(A)(3)+4(A)(2) ITC claimed exceeds cumulative 3.1(d) paid to date
    itc_before_payment_diff = g3b_total_rcm_itc - cum_paid_paise
    if itc_before_payment_diff > tolerance_paise:
        summary_by_reason[REASON_RCM_ITC_BEFORE_PAYMENT] += 1
        desc = (
            f"RCM ITC claimed in Table 4(A) exceeds tax paid in 3.1(d) for {period}: "
            f"Claimed {_rs(g3b_total_rcm_itc)} but cumulative 3.1(d) paid is {_rs(cum_paid_paise)} "
            f"(excess claim of {_rs(itc_before_payment_diff)})."
        )
        variances.append(
            RCMVariance(
                reason_code=REASON_RCM_ITC_BEFORE_PAYMENT,
                description=desc,
                diff_paise=itc_before_payment_diff,
                pr_tax_paise=pr_tax_paise,
                gstr3b_31d_tax_paise=g3b_31d_tax,
                gstr3b_rcm_itc_paise=g3b_total_rcm_itc,
            )
        )
        mismatches.append(
            MismatchResult(
                mismatch_type=REASON_RCM_ITC_BEFORE_PAYMENT,  # type: ignore
                severity=MismatchSeverity.CRITICAL,
                decision_what=f"RCM ITC of {_rs(itc_before_payment_diff)} claimed before tax payment",
                decision_why=(
                    f"Under Section 16(2)(b) read with Rule 36, ITC on reverse charge supplies "
                    f"can only be claimed AFTER discharging the liability in cash under Table 3.1(d). "
                    f"GSTR-3B claims {_rs(g3b_total_rcm_itc)} RCM ITC but 3.1(d) paid is {_rs(cum_paid_paise)}."
                ),
                decision_next=(
                    f"Reverse excessive RCM ITC claim of {_rs(itc_before_payment_diff)} in Table 4(B)(2) "
                    f"until corresponding RCM tax liability is paid in cash."
                ),
                rule_id="RCM_ITC_BEFORE_PAYMENT",
                gst_ref="Section 16(2)(b) CGST Act & Rule 36",
                details={
                    "gstr3b_total_rcm_itc_paise": g3b_total_rcm_itc,
                    "cum_paid_paise": cum_paid_paise,
                    "diff_paise": itc_before_payment_diff,
                },
            )
        )

    # ── CHECK 3: REASON_RCM_ITC_NOT_CLAIMED ─────────────────────────────────
    # 3.1(d) tax paid in cash but eligible RCM ITC left unclaimed in 4(A)(3)/4(A)(2)
    unclaimed_diff = g3b_31d_tax - g3b_total_rcm_itc
    if unclaimed_diff > tolerance_paise and g3b_31d_tax > tolerance_paise:
        # Only flag if not already flagged under timing mismatch (i.e. if claimed is zero or substantially lower)
        summary_by_reason[REASON_RCM_ITC_NOT_CLAIMED] += 1
        desc = (
            f"RCM tax paid in Table 3.1(d) but eligible ITC unclaimed in Table 4(A) for {period}: "
            f"Paid {_rs(g3b_31d_tax)} in 3.1(d) but claimed only {_rs(g3b_total_rcm_itc)} in 4(A)(3)/4(A)(2) "
            f"(unclaimed credit of {_rs(unclaimed_diff)})."
        )
        variances.append(
            RCMVariance(
                reason_code=REASON_RCM_ITC_NOT_CLAIMED,
                description=desc,
                diff_paise=unclaimed_diff,
                pr_tax_paise=pr_tax_paise,
                gstr3b_31d_tax_paise=g3b_31d_tax,
                gstr3b_rcm_itc_paise=g3b_total_rcm_itc,
            )
        )
        mismatches.append(
            MismatchResult(
                mismatch_type=REASON_RCM_ITC_NOT_CLAIMED,  # type: ignore
                severity=MismatchSeverity.MEDIUM,
                decision_what=f"Eligible RCM ITC of {_rs(unclaimed_diff)} left unclaimed in GSTR-3B",
                decision_why=(
                    f"RCM liability of {_rs(g3b_31d_tax)} was paid in cash in Table 3.1(d), but "
                    f"only {_rs(g3b_total_rcm_itc)} ITC was claimed in Table 4(A)(3)/4(A)(2). "
                    f"Eligible RCM credit is currently unutilised."
                ),
                decision_next=(
                    f"Claim remaining eligible RCM ITC of {_rs(unclaimed_diff)} in Table 4(A)(3) "
                    f"in the current or subsequent period GSTR-3B return within Section 16(4) deadline."
                ),
                rule_id="RCM_ITC_NOT_CLAIMED",
                gst_ref="Section 16(2) CGST Act",
                details={
                    "gstr3b_31d_tax_paise": g3b_31d_tax,
                    "gstr3b_total_rcm_itc_paise": g3b_total_rcm_itc,
                    "unclaimed_diff_paise": unclaimed_diff,
                },
            )
        )

    # ── CHECK 4: REASON_RCM_TIMING_MISMATCH ─────────────────────────────────
    # Both paid and claimed present and non-zero, but claimed != paid in current period while claimed <= cum_paid
    if (
        g3b_31d_tax > tolerance_paise
        and g3b_total_rcm_itc > tolerance_paise
        and abs(g3b_31d_tax - g3b_total_rcm_itc) > tolerance_paise
        and itc_before_payment_diff <= tolerance_paise
    ):
        summary_by_reason[REASON_RCM_TIMING_MISMATCH] += 1
        timing_diff = abs(g3b_31d_tax - g3b_total_rcm_itc)
        desc = (
            f"RCM tax paid ({_rs(g3b_31d_tax)}) and ITC claimed ({_rs(g3b_total_rcm_itc)}) differ in period {period} "
            f"by {_rs(timing_diff)} (timing shift across return periods)."
        )
        variances.append(
            RCMVariance(
                reason_code=REASON_RCM_TIMING_MISMATCH,
                description=desc,
                diff_paise=timing_diff,
                pr_tax_paise=pr_tax_paise,
                gstr3b_31d_tax_paise=g3b_31d_tax,
                gstr3b_rcm_itc_paise=g3b_total_rcm_itc,
            )
        )
        mismatches.append(
            MismatchResult(
                mismatch_type=REASON_RCM_TIMING_MISMATCH,  # type: ignore
                severity=MismatchSeverity.LOW,
                decision_what=f"RCM timing mismatch of {_rs(timing_diff)} between 3.1(d) paid and 4(A) claimed",
                decision_why=(
                    f"GSTR-3B Table 3.1(d) shows {_rs(g3b_31d_tax)} paid while Table 4(A) shows "
                    f"{_rs(g3b_total_rcm_itc)} claimed for period {period}. RCM ITC may be claimed in a later "
                    f"period after cash payment."
                ),
                decision_next=(
                    f"Informational warning. Verify that RCM credit claims across periods align with "
                    f"cumulative RCM tax payments in cash."
                ),
                rule_id="RCM_TIMING_MISMATCH",
                gst_ref="Section 16(2) CGST Act",
                details={
                    "gstr3b_31d_tax_paise": g3b_31d_tax,
                    "gstr3b_total_rcm_itc_paise": g3b_total_rcm_itc,
                    "diff_paise": timing_diff,
                },
            )
        )

    is_clean = len(variances) == 0

    return RCMTieOutResult(
        gstin=gstin,
        ret_period=period,
        is_clean=is_clean,
        pr_rcm_taxable_paise=pr_taxable_paise,
        pr_rcm_tax_paise=pr_tax_paise,
        pr_flagged_count=pr_flagged_count,
        pr_flagged_rows=flagged_rows,
        gstr3b_31d_taxable_paise=g3b_31d_taxable,
        gstr3b_31d_tax_paise=g3b_31d_tax,
        gstr3b_4a3_itc_paise=g3b_4a3_itc,
        gstr3b_4a2_itc_paise=g3b_4a2_itc,
        total_gstr3b_rcm_itc_paise=g3b_total_rcm_itc,
        variances=variances,
        mismatches=mismatches,
        summary_by_reason=summary_by_reason,
        cash_ledger_note=g3b.cash_ledger_note,
    )
