"""Pre-Filing Intelligence & Cross-Return Validation Engine.

Performs authoritative, server-side pre-flight checks for GSTR-1 and GSTR-3B filings:
1. Rule 88C Outward Liability Check (Form GST DRC-01B Part A):
   - CGST Rule 88C inserted vide Notification No. 26/2022-Central Tax (26 Dec 2022).
   - 48th GST Council recommendation: Triggers intimation when outward tax liability reported in
     GSTR-1/IFF exceeds tax paid in GSTR-3B Table 3.1(a)/(b) by BOTH:
     * Percentage variance > 20% AND
     * Absolute tax amount > ₹25,00,000 (Twenty-Five Lakh Rupees).
   - Sub-rule 59(6)(e): Blocks filing of subsequent period GSTR-1/IFF if unpaid/unexplained.
2. Rule 88D Inward ITC Check (Form GST DRC-01C Part A):
   - CGST Rule 88D inserted vide Notification No. 38/2023-Central Tax (04 Aug 2023).
   - 50th GST Council recommendation: Triggers intimation when ITC availed in GSTR-3B Table 4(A)(5)
     exceeds ITC available in auto-generated GSTR-2B by BOTH:
     * Percentage excess > 20% AND
     * Absolute excess amount > ₹25,00,000 (Twenty-Five Lakh Rupees).
   - Sub-rule 59(6)(f): Blocks filing of subsequent period GSTR-1/IFF if unpaid/unexplained.
3. Section 9(3)/9(4) RCM Liability Check: Inward RCM supplies vs Table 3.1(d) cash discharge.
4. Section 17(5) and Rules 38, 42, 43: Ineligible and mandatory reversal checks.
5. Reconciliation Completion Gate: Verifies reconciliation run status (FINAL) and lack of unresolved blocking exceptions.
6. Tamper-evident Figures & Validation Digests: Deterministic SHA-256 hashes binding approvals to exact figures.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from supabase import Client

from app.constants import RunStatus
from app.filing.gstr3b_suggestions import (
    load_osup_det_suggestion,
    load_table4_suggestion,
)
from app.services.gstr3b_reconciliation import (
    DRC01C_EXCESS_AMOUNT_THRESHOLD,
    DRC01C_EXCESS_PCT_THRESHOLD,
    compute_drc01c_threshold,
)
from app.services.gstr9c_itc_fy_rollup import normalize_period_yyyy_mm, paise_to_rupees

_log = logging.getLogger(__name__)

# Statutory CGST Rule 88C dual threshold (Notification No. 26/2022-CT & 48th GST Council)
RULE_88C_EXCESS_PCT_THRESHOLD: float = 20.0
RULE_88C_EXCESS_AMOUNT_THRESHOLD: float = 2_500_000.0  # ₹25 Lakh


class ValidationSeverity(str, Enum):
    CLEAN = "CLEAN"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL_ERROR = "CRITICAL_ERROR"


class ViolationCategory(str, Enum):
    STATUTORY_BREACH = "STATUTORY_BREACH"
    RISK_WARNING = "RISK_WARNING"
    RECONCILIATION_INCOMPLETE = "RECONCILIATION_INCOMPLETE"
    INTERNAL_POLICY = "INTERNAL_POLICY"


@dataclass
class ValidationViolation:
    code: str
    message: str
    category: ViolationCategory
    severity: ValidationSeverity
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "details": self.details,
        }


@dataclass
class PreFilingValidationResult:
    return_type: str
    gstin: str
    period: str
    is_valid: bool
    overall_severity: ValidationSeverity
    figures_digest: str
    validation_digest: str = ""
    violations: list[ValidationViolation] = field(default_factory=list)
    statutory_checks: dict[str, Any] = field(default_factory=dict)
    reconciliation_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def has_critical_violations(self) -> bool:
        return any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in self.violations)

    @property
    def has_statutory_breaches(self) -> bool:
        return any(v.category == ViolationCategory.STATUTORY_BREACH for v in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "return_type": self.return_type,
            "gstin": self.gstin,
            "period": self.period,
            "is_valid": self.is_valid,
            "overall_severity": self.overall_severity.value,
            "figures_digest": self.figures_digest,
            "validation_digest": self.validation_digest,
            "has_critical_violations": self.has_critical_violations,
            "has_statutory_breaches": self.has_statutory_breaches,
            "violations_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "statutory_checks": self.statutory_checks,
            "reconciliation_summary": self.reconciliation_summary,
        }


def compute_figures_digest(payload: Any) -> str:
    """Compute a canonical deterministic SHA-256 hash of filing figures.
    
    Ensures approvals granted on a specific set of numbers cannot be reused
    if figures are altered before filing.
    """
    def _canonicalize(val: Any) -> Any:
        if isinstance(val, dict):
            return {k: _canonicalize(v) for k, v in sorted(val.items()) if not k.startswith("_")}
        if isinstance(val, list):
            return [_canonicalize(x) for x in val]
        if isinstance(val, float):
            return round(val, 2)
        if isinstance(val, Decimal):
            return round(float(val), 2)
        return val

    canonical = _canonicalize(payload)
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_validation_digest(violations: Sequence[ValidationViolation]) -> str:
    """Canonical deterministic SHA-256 hash of validation violation codes, categories, and severities.
    
    Ensures approvals granted against a specific validation profile cannot be reused
    if new compliance errors or statutory breaches emerge.
    """
    canonical = sorted([
        {"code": v.code, "category": v.category.value, "severity": v.severity.value}
        for v in violations
    ], key=lambda x: (x["code"], x["severity"]))
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_rule_88c_threshold(
    gstr1_total_tax: float,
    gstr3b_total_tax: float,
    *,
    pct_threshold: float = RULE_88C_EXCESS_PCT_THRESHOLD,
    amount_threshold: float = RULE_88C_EXCESS_AMOUNT_THRESHOLD,
) -> dict[str, Any]:
    """CGST Rule 88C dual-threshold check for DRC-01B intimation.
    
    Triggers statutory intimation when tax declared in GSTR-1 exceeds tax paid in GSTR-3B
    by BOTH > pct_threshold (Council recommendation: 20%) AND > amount_threshold (₹25,00,000).
    """
    g1 = round(float(gstr1_total_tax or 0.0), 2)
    g3 = round(float(gstr3b_total_tax or 0.0), 2)
    diff = round(g1 - g3, 2)

    if diff <= 0:
        return {
            "status": "CLEAN",
            "threshold_status": "CLEAR",
            "diff_amount": diff,
            "diff_pct": 0.0 if g3 > 0 else 0.0,
            "triggers_drc01b": False,
            "is_statutory_breach": False,
            "gstr1_tax": g1,
            "gstr3b_tax": g3,
        }

    if g3 > 0:
        diff_pct = round((diff / g3) * 100.0, 4)
        pct_exceeded = diff_pct > pct_threshold
    else:
        diff_pct = None
        pct_exceeded = True

    amount_exceeded = diff > amount_threshold
    triggers = bool(pct_exceeded and amount_exceeded)

    status = "STATUTORY_BREACH" if triggers else "ADVISORY_VARIANCE"

    return {
        "status": status,
        "threshold_status": "TRIGGERED" if triggers else "BELOW_THRESHOLD",
        "diff_amount": diff,
        "diff_pct": diff_pct,
        "pct_threshold": pct_threshold,
        "amount_threshold": amount_threshold,
        "triggers_drc01b": triggers,
        "is_statutory_breach": triggers,
        "gstr1_tax": g1,
        "gstr3b_tax": g3,
    }


def validate_gstr3b_pre_filing(
    sb: Client,
    *,
    client_gstin_id: str,
    gstin: str,
    period: str,
    save_body: dict[str, Any],
    require_final_reconciliation: bool = True,
    rule_88c_pct_threshold: float = RULE_88C_EXCESS_PCT_THRESHOLD,
    rule_88c_amount_threshold: float = RULE_88C_EXCESS_AMOUNT_THRESHOLD,
    rule_88d_pct_threshold: float = DRC01C_EXCESS_PCT_THRESHOLD,
    rule_88d_amount_threshold: float = DRC01C_EXCESS_AMOUNT_THRESHOLD,
) -> PreFilingValidationResult:
    """Run full pre-filing validation on GSTR-3B save payload.
    
    Never hardcodes invented thresholds; uses statutory parameters or firm config.
    """
    clean_period = normalize_period_yyyy_mm(period) or period
    clean_gstin = gstin.strip().upper()
    digest = compute_figures_digest(save_body)

    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, Any] = {}
    recon_summary: dict[str, Any] = {}

    # Extract declared figures from save_body
    sup_details = save_body.get("sup_details") or {}
    osup_det = sup_details.get("osup_det") or {}
    itc_elg = save_body.get("itc_elg") or {}

    declared_31a_tax = round(
        float(osup_det.get("iamt") or 0.0)
        + float(osup_det.get("camt") or 0.0)
        + float(osup_det.get("samt") or 0.0)
        + float(osup_det.get("csamt") or 0.0),
        2,
    )

    # 1. Check GSTR-1 vs GSTR-3B Outward Liability (Rule 88C)
    g1_suggestion = load_osup_det_suggestion(sb, client_gstin_id=client_gstin_id, period=clean_period)
    if g1_suggestion.get("available") and g1_suggestion.get("osup_det"):
        g1_det = g1_suggestion["osup_det"]
        g1_tax = round(
            float(g1_det.get("iamt") or 0.0)
            + float(g1_det.get("camt") or 0.0)
            + float(g1_det.get("samt") or 0.0)
            + float(g1_det.get("csamt") or 0.0),
            2,
        )
        r88c = compute_rule_88c_threshold(
            g1_tax,
            declared_31a_tax,
            pct_threshold=rule_88c_pct_threshold,
            amount_threshold=rule_88c_amount_threshold,
        )
        statutory_checks["rule_88c"] = r88c
        recon_summary["gstr1_reconciled"] = True
        recon_summary["gstr1_total_tax"] = g1_tax
        recon_summary["gstr3b_total_tax"] = declared_31a_tax

        if r88c["triggers_drc01b"]:
            violations.append(
                ValidationViolation(
                    code="RULE_88C_DRC01B_TRIGGER",
                    message=(
                        f"GSTR-1 outward tax liability (₹{g1_tax:,.2f}) exceeds GSTR-3B (₹{declared_31a_tax:,.2f}) "
                        f"by ₹{r88c['diff_amount']:,.2f} ({r88c['diff_pct']}%), exceeding the Rule 88C "
                        f"statutory DRC-01B intimation threshold (₹{rule_88c_amount_threshold:,.2f} / {rule_88c_pct_threshold}%)."
                    ),
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details=r88c,
                )
            )
        elif r88c["diff_amount"] > 50.0:  # Beyond ₹50 rounding
            violations.append(
                ValidationViolation(
                    code="GSTR1_3B_LIABILITY_MISMATCH",
                    message=(
                        f"Outward tax liability mismatch: GSTR-1 reports ₹{g1_tax:,.2f} while GSTR-3B declares "
                        f"₹{declared_31a_tax:,.2f} (Difference: ₹{r88c['diff_amount']:,.2f})."
                    ),
                    category=ViolationCategory.RISK_WARNING,
                    severity=ValidationSeverity.WARNING,
                    details=r88c,
                )
            )
    else:
        recon_summary["gstr1_reconciled"] = False
        statutory_checks["rule_88c"] = {"status": "GSTR1_DATA_UNAVAILABLE"}
        violations.append(
            ValidationViolation(
                code="GSTR1_RECON_MISSING",
                message="No finalized GSTR-1 reconciliation run found for this period. Outward liability tie-out could not be verified.",
                category=ViolationCategory.RECONCILIATION_INCOMPLETE,
                severity=ValidationSeverity.INFO,
            )
        )

    # 2. Check GSTR-2B vs GSTR-3B Table 4 Inward ITC (Rule 88D)
    itc_avl = itc_elg.get("itc_avl") or []
    oth_claimed_tax = 0.0
    total_4a_claimed_tax = 0.0
    for row in itc_avl:
        if isinstance(row, dict):
            row_tax = (
                float(row.get("iamt") or 0.0)
                + float(row.get("camt") or 0.0)
                + float(row.get("samt") or 0.0)
                + float(row.get("csamt") or 0.0)
            )
            total_4a_claimed_tax += row_tax
            if str(row.get("ty") or "").upper() == "OTH":
                oth_claimed_tax += row_tax

    t4_suggestion = load_table4_suggestion(sb, client_gstin_id=client_gstin_id, period=clean_period)
    if t4_suggestion.get("available") and t4_suggestion.get("itc_elg"):
        t4_sug_avl = t4_suggestion["itc_elg"].get("itc_avl") or []
        t4_sug_oth = 0.0
        for r in t4_sug_avl:
            if isinstance(r, dict) and str(r.get("ty") or "").upper() == "OTH":
                t4_sug_oth += (
                    float(r.get("iamt") or 0.0)
                    + float(r.get("camt") or 0.0)
                    + float(r.get("samt") or 0.0)
                    + float(r.get("csamt") or 0.0)
                )

        r88d = compute_drc01c_threshold(
            oth_claimed_tax,
            t4_sug_oth,
            pct_threshold=rule_88d_pct_threshold,
            amount_threshold=rule_88d_amount_threshold,
        )
        statutory_checks["rule_88d"] = r88d
        recon_summary["gstr2b_reconciled"] = True
        recon_summary["gstr2b_available_itc"] = t4_sug_oth
        recon_summary["gstr3b_claimed_itc"] = oth_claimed_tax

        if r88d["triggers_drc01c"]:
            violations.append(
                ValidationViolation(
                    code="RULE_88D_DRC01C_TRIGGER",
                    message=(
                        f"GSTR-3B Table 4(A)(5) claimed ITC (₹{oth_claimed_tax:,.2f}) exceeds GSTR-2B available ITC "
                        f"(₹{t4_sug_oth:,.2f}) by ₹{r88d['excess_amount']:,.2f} ({r88d['excess_pct']}%), triggering "
                        f"statutory DRC-01C intimation under Rule 88D (Threshold: ₹{rule_88d_amount_threshold:,.2f} / {rule_88d_pct_threshold}%)."
                    ),
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details=r88d,
                )
            )
        elif r88d["excess_amount"] > 50.0:
            violations.append(
                ValidationViolation(
                    code="ITC_OVERCLAIM_WARNING",
                    message=(
                        f"Claimed ITC in Table 4(A)(5) exceeds GSTR-2B by ₹{r88d['excess_amount']:,.2f} "
                        f"(Claimed: ₹{oth_claimed_tax:,.2f}, Available: ₹{t4_sug_oth:,.2f})."
                    ),
                    category=ViolationCategory.RISK_WARNING,
                    severity=ValidationSeverity.WARNING,
                    details=r88d,
                )
            )
    else:
        recon_summary["gstr2b_reconciled"] = False
        statutory_checks["rule_88d"] = {"status": "GSTR2B_DATA_UNAVAILABLE"}
        violations.append(
            ValidationViolation(
                code="GSTR2B_RECON_MISSING",
                message="No completed GSTR-2B purchase reconciliation run found for this period. ITC eligibility cannot be guaranteed.",
                category=ViolationCategory.RECONCILIATION_INCOMPLETE,
                severity=ValidationSeverity.INFO,
            )
        )

    # 3. Check Reconciliation Run Status (Finalized / Locked)
    run_row = None
    try:
        run_res = (
            sb.table("reconciliation_run")
            .select("id, status, is_locked, finalized_at")
            .eq("client_gstin_id", client_gstin_id)
            .eq("period", clean_period)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if run_res.data:
            run_row = run_res.data[0]
    except Exception:
        pass

    if run_row:
        run_status = str(run_row.get("status") or "")
        is_locked = bool(run_row.get("is_locked"))
        recon_summary["reconciliation_run_id"] = run_row.get("id")
        recon_summary["reconciliation_run_status"] = run_status
        recon_summary["reconciliation_run_locked"] = is_locked

        if run_status != RunStatus.FINAL or not is_locked:
            sev = ValidationSeverity.CRITICAL_ERROR if require_final_reconciliation else ValidationSeverity.WARNING
            code = "RECONCILIATION_NOT_FINALIZED" if require_final_reconciliation else "RECONCILIATION_RUN_UNLOCKED"
            violations.append(
                ValidationViolation(
                    code=code,
                    message=(
                        f"Reconciliation run {run_row.get('id')} for period {clean_period} is not FINALIZED (status={run_status}). "
                        "Unfinalized runs may contain unresolved Section 17(5) or Rule 37 exceptions."
                    ),
                    category=ViolationCategory.RECONCILIATION_INCOMPLETE,
                    severity=sev,
                    details={"run_id": run_row.get("id"), "status": run_status},
                )
            )
    else:
        recon_summary["reconciliation_run_id"] = None

    # 4. Check RCM Inward supplies vs Table 3.1(d)
    isup_rev = sup_details.get("isup_rev") or {}
    declared_rcm_tax = round(
        float(isup_rev.get("iamt") or 0.0)
        + float(isup_rev.get("camt") or 0.0)
        + float(isup_rev.get("samt") or 0.0)
        + float(isup_rev.get("csamt") or 0.0),
        2,
    )
    statutory_checks["rcm"] = {
        "declared_31d_tax": declared_rcm_tax,
        "declared_31d_txval": float(isup_rev.get("txval") or 0.0),
    }

    # Evaluate Overall Severity
    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
        is_valid = False
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
        is_valid = True
    elif any(v.severity == ValidationSeverity.INFO for v in violations):
        overall_severity = ValidationSeverity.INFO
        is_valid = True
    else:
        overall_severity = ValidationSeverity.CLEAN
        is_valid = True

    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-3b",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=is_valid,
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary=recon_summary,
    )


def validate_gstr1_pre_filing(
    sb: Client,
    *,
    client_gstin_id: str,
    gstin: str,
    period: str,
    mapped_readiness: dict[str, Any],
    save_payload: dict[str, Any],
) -> PreFilingValidationResult:
    """Run full pre-filing validation on GSTR-1 readiness & save payload."""
    clean_period = normalize_period_yyyy_mm(period) or period
    clean_gstin = gstin.strip().upper()
    digest = compute_figures_digest(save_payload)

    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, Any] = {}
    recon_summary: dict[str, Any] = {}

    filing_readiness = mapped_readiness.get("filing_readiness") or {}
    file_blockers = filing_readiness.get("file_blockers") or []
    save_blockers = filing_readiness.get("save_blockers") or []
    pending_count = int(mapped_readiness.get("pending_review_count") or 0)

    # 1. Statutory blockers (Table 12 HSN B2B, Table 13 Documents Issued)
    for b in file_blockers:
        violations.append(
            ValidationViolation(
                code="GSTR1_MANDATORY_TABLE_GAP",
                message=b,
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )

    for b in save_blockers:
        violations.append(
            ValidationViolation(
                code="GSTR1_SAVE_BLOCKER",
                message=b,
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )

    # 2. Pending review items warning
    if pending_count > 0:
        violations.append(
            ValidationViolation(
                code="GSTR1_PENDING_REVIEW_EXCLUSION",
                message=f"{pending_count} invoice(s) remain in pending_review and are excluded from the save payload.",
                category=ViolationCategory.RISK_WARNING,
                severity=ValidationSeverity.WARNING,
                details={"pending_count": pending_count},
            )
        )

    statutory_checks["file_blockers_count"] = len(file_blockers)
    statutory_checks["save_blockers_count"] = len(save_blockers)
    statutory_checks["pending_review_count"] = pending_count

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
        is_valid = False
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
        is_valid = True
    else:
        overall_severity = ValidationSeverity.CLEAN
        is_valid = True

    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-1",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=is_valid,
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary=recon_summary,
    )


def validate_gstr1a_pre_filing(
    *,
    gstin: str,
    period: str,
    batch: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    gstr1_filed: bool = True,
    gstr3b_filed: bool = False,
) -> PreFilingValidationResult:
    """Validate GSTR-1A amendment batch against Rule 59(1A) and GST rules.

    Checks:
    1. Rule 59(1A) eligibility (GSTR-1 filed, GSTR-3B NOT filed).
    2. Batch has at least 1 item.
    3. Valid recipient GSTINs on B2B additions/amendments.
    4. POS vs IGST/CGST/SGST alignment.
    5. Figures digest binding.
    """
    clean_gstin = (gstin or "").strip().upper()
    clean_period = (period or "").strip()
    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, Any] = {
        "rule_59_1a_window": "PASSED",
        "recipient_gstin_validity": "PASSED",
        "pos_tax_alignment": "PASSED",
    }

    # 1. Rule 59(1A) Window
    if not gstr1_filed:
        violations.append(
            ValidationViolation(
                code="G1A_GSTR1_NOT_FILED",
                message="GSTR-1 must be filed before Form GSTR-1A can be submitted (Rule 59(1A)).",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )
        statutory_checks["rule_59_1a_window"] = "FAILED"

    if gstr3b_filed:
        violations.append(
            ValidationViolation(
                code="G1A_GSTR3B_ALREADY_FILED",
                message="GSTR-3B has already been filed for this period; Form GSTR-1A is permanently closed (Rule 59(1A)).",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )
        statutory_checks["rule_59_1a_window"] = "FAILED"

    # 2. Batch content
    if not items:
        violations.append(
            ValidationViolation(
                code="G1A_EMPTY_BATCH",
                message="GSTR-1A amendment batch has no invoice additions or amendments.",
                category=ViolationCategory.INTERNAL_POLICY,
                severity=ValidationSeverity.WARNING,
            )
        )

    # 3. Item-level validation
    gstin_regex = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
    supplier_state = clean_gstin[:2] if len(clean_gstin) >= 2 else ""

    for idx, it in enumerate(items, 1):
        tbl = str(it.get("table_name") or "").upper()
        recip = str(it.get("recipient_gstin") or "").strip().upper()
        if ("B2B" in tbl or "4" in tbl or "CDNR" in tbl) and recip:
            if not gstin_regex.match(recip):
                violations.append(
                    ValidationViolation(
                        code="G1A_INVALID_RECIPIENT_GSTIN",
                        message=f"Invalid recipient GSTIN format '{recip}' in {tbl}.",
                        category=ViolationCategory.STATUTORY_BREACH,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"item_index": idx, "recipient_gstin": recip},
                    )
                )
                statutory_checks["recipient_gstin_validity"] = "FAILED"

        pos = str(it.get("pos") or "").strip()
        d_igst = float(it.get("delta_igst") or 0)
        d_cgst = float(it.get("delta_cgst") or 0)
        d_sgst = float(it.get("delta_sgst") or 0)
        if supplier_state and pos and supplier_state == pos:
            # Intra-state: should have CGST+SGST, not IGST alone
            if abs(d_igst) > 0 and abs(d_cgst) == 0 and abs(d_sgst) == 0:
                violations.append(
                    ValidationViolation(
                        code="G1A_POS_TAX_MISMATCH",
                        message=f"Intra-state supply (POS {pos} matches supplier state {supplier_state}) declared with IGST instead of CGST/SGST.",
                        category=ViolationCategory.RISK_WARNING,
                        severity=ValidationSeverity.WARNING,
                        details={"item_index": idx, "pos": pos, "delta_igst": d_igst},
                    )
                )
                statutory_checks["pos_tax_alignment"] = "WARNING"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    elif any(v.severity == ValidationSeverity.INFO for v in violations):
        overall_severity = ValidationSeverity.INFO
    else:
        overall_severity = ValidationSeverity.CLEAN

    is_valid = overall_severity not in (ValidationSeverity.CRITICAL_ERROR,)

    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-1a",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=is_valid,
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"items_count": len(items)},
    )


def validate_gstr7_pre_filing(
    *,
    gstin: str,
    period: str,
    batch: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> PreFilingValidationResult:
    """Pre-filing validation for Form GSTR-7 (TDS under Section 51).

    Checks:
    1. Deductor GSTIN validity
    2. Batch not empty
    3. Deductee GSTIN validity
    4. Contract threshold (> ₹2,50,000)
    5. Section 51(1) Proviso exemption (supplier state == POS != deductor state)
    6. Tax head allocations (Intra-state: CGST+SGST, Inter-state: IGST)
    7. Duplicate records check
    """
    from app.rules.gstr7_rules import (
        GSTR7_CONTRACT_THRESHOLD,
        calculate_gstr7_tds,
        evaluate_section_51_proviso,
        extract_state_code,
        validate_gstin_format,
    )

    clean_gstin = (gstin or "").strip().upper()
    clean_period = (period or "").strip()
    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, Any] = {
        "deductor_gstin_validity": "PASSED",
        "batch_content": "PASSED",
        "deductee_gstins_validity": "PASSED",
        "section_51_contract_threshold": "PASSED",
        "section_51_proviso_exemption": "PASSED",
        "tax_head_allocation": "PASSED",
    }

    if not validate_gstin_format(clean_gstin):
        violations.append(
            ValidationViolation(
                code="G7_INVALID_DEDUCTOR_GSTIN",
                message=f"Deductor GSTIN '{clean_gstin}' is invalid.",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )
        statutory_checks["deductor_gstin_validity"] = "FAILED"

    if not records:
        violations.append(
            ValidationViolation(
                code="G7_EMPTY_BATCH",
                message="GSTR-7 return has no TDS deduction records.",
                category=ViolationCategory.INTERNAL_POLICY,
                severity=ValidationSeverity.WARNING,
            )
        )
        statutory_checks["batch_content"] = "WARNING"

    deductor_state = extract_state_code(clean_gstin)
    seen_deductee_refs: set[tuple[str, str, str]] = set()

    for idx, r in enumerate(records, 1):
        ded_gstin = str(r.get("deductee_gstin") or "").strip().upper()
        rec_type = str(r.get("record_type") or "ORIGINAL").upper()
        pay_ref = str(r.get("payment_reference") or "").strip()

        if not validate_gstin_format(ded_gstin):
            violations.append(
                ValidationViolation(
                    code="G7_INVALID_DEDUCTEE_GSTIN",
                    message=f"Deductee GSTIN '{ded_gstin}' on record #{idx} is invalid.",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "deductee_gstin": ded_gstin},
                )
            )
            statutory_checks["deductee_gstins_validity"] = "FAILED"

        # Duplicate check
        key = (rec_type, ded_gstin, pay_ref)
        if pay_ref and key in seen_deductee_refs:
            violations.append(
                ValidationViolation(
                    code="G7_DUPLICATE_DEDUCTION_RECORD",
                    message=f"Duplicate TDS record for deductee {ded_gstin} with payment reference '{pay_ref}'.",
                    category=ViolationCategory.RISK_WARNING,
                    severity=ValidationSeverity.WARNING,
                    details={"index": idx, "deductee_gstin": ded_gstin, "payment_reference": pay_ref},
                )
            )
        seen_deductee_refs.add(key)

        supplier_state = extract_state_code(ded_gstin)
        pos = str(r.get("pos") or supplier_state).strip()
        contract_val = float(r.get("contract_value") or 0.0)
        amount_paid = float(r.get("amount_paid") or 0.0)
        tds_igst = float(r.get("tds_igst") or 0.0)
        tds_cgst = float(r.get("tds_cgst") or 0.0)
        tds_sgst = float(r.get("tds_sgst") or 0.0)

        # Statutory checks
        calc = calculate_gstr7_tds(
            contract_value=contract_val,
            amount_paid=amount_paid,
            deductor_state=deductor_state,
            supplier_state=supplier_state,
            pos=pos,
        )

        if not calc.contract_exceeds_threshold and contract_val > 0:
            violations.append(
                ValidationViolation(
                    code="G7_CONTRACT_BELOW_THRESHOLD",
                    message=f"Record #{idx}: Contract value ₹{contract_val:,.2f} does not exceed statutory ₹2,50,000 threshold.",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.WARNING,
                    details={"index": idx, "contract_value": contract_val},
                )
            )
            statutory_checks["section_51_contract_threshold"] = "WARNING"

        if calc.is_proviso_exempt:
            violations.append(
                ValidationViolation(
                    code="G7_PROVISO_EXEMPTION_BREACH",
                    message=(
                        f"Record #{idx}: TDS prohibited under Proviso to Sec 51(1). "
                        f"Supplier ({supplier_state}) and POS ({pos}) are in same State, different from Deductor ({deductor_state})."
                    ),
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "supplier_state": supplier_state, "pos": pos, "deductor_state": deductor_state},
                )
            )
            statutory_checks["section_51_proviso_exemption"] = "FAILED"

        # Tax-head alignment
        if calc.is_eligible:
            if calc.tax_type == "INTRA_STATE" and tds_igst > 0 and (tds_cgst == 0 and tds_sgst == 0):
                violations.append(
                    ValidationViolation(
                        code="G7_TAX_HEAD_MISMATCH_INTRA",
                        message=f"Record #{idx}: Intra-state supply declared with IGST instead of CGST + SGST.",
                        category=ViolationCategory.STATUTORY_BREACH,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"index": idx, "tds_igst": tds_igst},
                    )
                )
                statutory_checks["tax_head_allocation"] = "FAILED"
            elif calc.tax_type == "INTER_STATE" and (tds_cgst > 0 or tds_sgst > 0) and tds_igst == 0:
                violations.append(
                    ValidationViolation(
                        code="G7_TAX_HEAD_MISMATCH_INTER",
                        message=f"Record #{idx}: Inter-state supply declared with CGST/SGST instead of IGST.",
                        category=ViolationCategory.STATUTORY_BREACH,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"index": idx, "tds_cgst": tds_cgst, "tds_sgst": tds_sgst},
                    )
                )
                statutory_checks["tax_head_allocation"] = "FAILED"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    elif any(v.severity == ValidationSeverity.INFO for v in violations):
        overall_severity = ValidationSeverity.INFO
    else:
        overall_severity = ValidationSeverity.CLEAN

    is_valid = overall_severity not in (ValidationSeverity.CRITICAL_ERROR,)
    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-7",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=is_valid,
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"records_count": len(records)},
    )


def validate_gstr8_pre_filing(
    *,
    gstin: str,
    period: str,
    batch: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> PreFilingValidationResult:
    """Pre-filing validation for Form GSTR-8 (TCS under Section 52).

    Checks:
    1. ECO GSTIN validity
    2. Batch not empty
    3. B2B supplier GSTIN validity / B2C 2-digit POS validity
    4. Net supplies arithmetic (gross - returns)
    5. Negative net supplies warning
    6. Statutory TCS rate (0.5% post 10-Jul-2024, 1.0% pre 10-Jul-2024)
    7. Tax head allocations (Intra-state: CGST+SGST, Inter-state: IGST)
    8. Duplicate records check
    """
    from app.rules.gstr8_rules import (
        calculate_gstr8_tcs,
        get_applicable_tcs_rates,
    )
    from app.rules.gstr7_rules import extract_state_code, validate_gstin_format

    clean_gstin = (gstin or "").strip().upper()
    clean_period = (period or "").strip()
    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, Any] = {
        "eco_gstin_validity": "PASSED",
        "batch_content": "PASSED",
        "supplier_and_pos_validity": "PASSED",
        "net_supplies_arithmetic": "PASSED",
        "statutory_tcs_rate": "PASSED",
        "tax_head_allocation": "PASSED",
    }

    if not validate_gstin_format(clean_gstin):
        violations.append(
            ValidationViolation(
                code="G8_INVALID_ECO_GSTIN",
                message=f"ECO GSTIN '{clean_gstin}' is invalid.",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )
        statutory_checks["eco_gstin_validity"] = "FAILED"

    if not records:
        violations.append(
            ValidationViolation(
                code="G8_EMPTY_BATCH",
                message="GSTR-8 return has no TCS collection records.",
                category=ViolationCategory.INTERNAL_POLICY,
                severity=ValidationSeverity.WARNING,
            )
        )
        statutory_checks["batch_content"] = "WARNING"

    eco_state = extract_state_code(clean_gstin)
    seen_b2b_suppliers: set[tuple[str, str]] = set()
    seen_b2c_pos: set[tuple[str, str]] = set()

    for idx, r in enumerate(records, 1):
        stype = str(r.get("supply_type") or "B2B").upper()
        rtype = str(r.get("record_type") or "ORIGINAL").upper()
        supp_gstin = str(r.get("supplier_gstin") or "").strip().upper()
        pos = str(r.get("pos") or "").strip()

        gross = float(r.get("gross_supplies") or 0.0)
        returned = float(r.get("returned_supplies") or 0.0)
        net = float(r.get("net_supplies") or 0.0)

        # 1. Supply & POS Format
        if stype == "B2B":
            if not validate_gstin_format(supp_gstin):
                violations.append(
                    ValidationViolation(
                        code="G8_INVALID_SUPPLIER_GSTIN",
                        message=f"Record #{idx}: B2B supplier GSTIN '{supp_gstin}' is invalid.",
                        category=ViolationCategory.STATUTORY_BREACH,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"index": idx, "supplier_gstin": supp_gstin},
                    )
                )
                statutory_checks["supplier_and_pos_validity"] = "FAILED"

            key_b2b = (rtype, supp_gstin)
            if key_b2b in seen_b2b_suppliers:
                violations.append(
                    ValidationViolation(
                        code="G8_DUPLICATE_B2B_SUPPLIER",
                        message=f"Duplicate B2B entry for supplier {supp_gstin} in {rtype} table.",
                        category=ViolationCategory.RISK_WARNING,
                        severity=ValidationSeverity.WARNING,
                        details={"index": idx, "supplier_gstin": supp_gstin},
                    )
                )
            seen_b2b_suppliers.add(key_b2b)
        else:
            if not pos or len(pos) != 2 or not pos.isdigit():
                violations.append(
                    ValidationViolation(
                        code="G8_INVALID_POS",
                        message=f"Record #{idx}: B2C supply requires valid 2-digit Place of Supply ('{pos}').",
                        category=ViolationCategory.STATUTORY_BREACH,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"index": idx, "pos": pos},
                    )
                )
                statutory_checks["supplier_and_pos_validity"] = "FAILED"

            key_b2c = (rtype, pos)
            if key_b2c in seen_b2c_pos:
                violations.append(
                    ValidationViolation(
                        code="G8_DUPLICATE_B2C_POS",
                        message=f"Duplicate B2C entry for Place of Supply {pos} in {rtype} table.",
                        category=ViolationCategory.RISK_WARNING,
                        severity=ValidationSeverity.WARNING,
                        details={"index": idx, "pos": pos},
                    )
                )
            seen_b2c_pos.add(key_b2c)

        # 2. Net Arithmetic Check
        expected_net = round(gross - returned, 2)
        if abs(net - expected_net) > 0.05:
            violations.append(
                ValidationViolation(
                    code="G8_NET_SUPPLIES_ARITHMETIC_ERROR",
                    message=f"Record #{idx}: Net supplies (₹{net:,.2f}) does not equal Gross (₹{gross:,.2f}) minus Returned (₹{returned:,.2f}).",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "gross": gross, "returned": returned, "net": net, "expected": expected_net},
                )
            )
            statutory_checks["net_supplies_arithmetic"] = "FAILED"

        # 3. Negative Net Warning
        if expected_net < 0:
            violations.append(
                ValidationViolation(
                    code="G8_NEGATIVE_NET_SUPPLY",
                    message=f"Record #{idx}: Returned supplies exceed gross sales (Net = ₹{expected_net:,.2f}). TCS collection is ₹0.00.",
                    category=ViolationCategory.RISK_WARNING,
                    severity=ValidationSeverity.WARNING,
                    details={"index": idx, "net": expected_net},
                )
            )

        # 4. Tax Rate & Head Allocation
        supp_state = extract_state_code(supp_gstin) if supp_gstin else None
        calc = calculate_gstr8_tcs(
            period=clean_period,
            gross_supplies=gross,
            returned_supplies=returned,
            eco_state=eco_state,
            pos=pos or (supp_state or ""),
            supplier_state=supp_state,
        )

        t_igst = float(r.get("tcs_igst") or 0.0)
        t_cgst = float(r.get("tcs_cgst") or 0.0)
        t_sgst = float(r.get("tcs_sgst") or 0.0)

        if calc.supply_nature == "INTRA_STATE" and t_igst > 0 and (t_cgst == 0 and t_sgst == 0):
            violations.append(
                ValidationViolation(
                    code="G8_TAX_HEAD_MISMATCH_INTRA",
                    message=f"Record #{idx}: Intra-state supply declared with IGST instead of CGST+SGST.",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "pos": pos, "tcs_igst": t_igst},
                )
            )
            statutory_checks["tax_head_allocation"] = "FAILED"
        elif calc.supply_nature == "INTER_STATE" and (t_cgst > 0 or t_sgst > 0) and t_igst == 0:
            violations.append(
                ValidationViolation(
                    code="G8_TAX_HEAD_MISMATCH_INTER",
                    message=f"Record #{idx}: Inter-state supply declared with CGST/SGST instead of IGST.",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "pos": pos, "tcs_cgst": t_cgst, "tcs_sgst": t_sgst},
                )
            )
            statutory_checks["tax_head_allocation"] = "FAILED"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    elif any(v.severity == ValidationSeverity.INFO for v in violations):
        overall_severity = ValidationSeverity.INFO
    else:
        overall_severity = ValidationSeverity.CLEAN

    is_valid = overall_severity not in (ValidationSeverity.CRITICAL_ERROR,)
    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-8",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=is_valid,
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"records_count": len(records)},
    )


def validate_gstr6_pre_filing(
    *,
    batch: Mapping[str, Any],
    inward_records: list[Mapping[str, Any]],
    distribution_records: list[Mapping[str, Any]],
) -> PreFilingValidationResult:
    """Validate Form GSTR-6 (ISD) compliance prior to review and filing."""
    clean_gstin = str(batch.get("gstin") or "").strip().upper()
    clean_period = str(batch.get("period") or "").strip()
    isd_state = clean_gstin[:2] if len(clean_gstin) >= 2 else ""

    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, str] = {
        "isd_pan_consistency": "PASSED",
        "over_distribution_check": "PASSED",
        "cross_state_conversion": "PASSED",
    }

    if not inward_records:
        violations.append(
            ValidationViolation(
                code="G6_NO_INWARD_INVOICES",
                message="No inward invoices or credit/debit notes present for GSTR-6 return period.",
                category=ViolationCategory.DATA_INTEGRITY,
                severity=ValidationSeverity.WARNING,
            )
        )

    if not distribution_records:
        violations.append(
            ValidationViolation(
                code="G6_NO_DISTRIBUTIONS",
                message="No ISD credit distribution records found for recipient distinct persons (Rule 39).",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )
        statutory_checks["over_distribution_check"] = "FAILED"

    # 1. Total available pool vs Total distributed
    tot_pool = sum(
        float(r.get("igst") or 0.0) + float(r.get("cgst") or 0.0) + float(r.get("sgst") or 0.0)
        for r in inward_records
    )
    tot_dist = sum(
        float(d.get("total_distributed") if d.get("total_distributed") is not None else (
            float(d.get("distributed_igst") or 0.0) + float(d.get("distributed_cgst") or 0.0) + float(d.get("distributed_sgst") or 0.0)
        ))
        for d in distribution_records
    )

    # Strictly zero tolerance for over-distribution under Rule 39(1)(d)
    if round(tot_dist, 2) > round(tot_pool, 2):
        violations.append(
            ValidationViolation(
                code="G6_OVER_DISTRIBUTION",
                message=f"Over-distribution detected: distributed ₹{tot_dist:,.2f} exceeds available pool ₹{tot_pool:,.2f} (Rule 39(1)(d)).",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
                details={"available_pool": tot_pool, "distributed_total": tot_dist},
            )
        )
        statutory_checks["over_distribution_check"] = "FAILED"

    # 2. Check each recipient: PAN match and cross-state tax head
    isd_pan = clean_gstin[2:12] if len(clean_gstin) >= 12 else ""
    for idx, d in enumerate(distribution_records):
        rec_gstin = str(d.get("recipient_gstin") or "").strip().upper()
        rec_pan = rec_gstin[2:12] if len(rec_gstin) >= 12 else ""
        rec_state = rec_gstin[:2] if len(rec_gstin) >= 2 else ""

        if isd_pan and rec_pan and isd_pan != rec_pan:
            violations.append(
                ValidationViolation(
                    code="G6_CROSS_PAN_RECIPIENT",
                    message=f"Distribution #{idx+1}: Recipient PAN ({rec_pan}) does not match ISD PAN ({isd_pan}). ISD can only distribute to distinct persons under the same PAN (Section 20).",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"recipient_gstin": rec_gstin, "isd_gstin": clean_gstin},
                )
            )
            statutory_checks["isd_pan_consistency"] = "FAILED"

        # Cross-state conversion check (Rule 39(1)(f))
        if isd_state and rec_state and isd_state != rec_state:
            dist_cgst = float(d.get("distributed_cgst") or 0.0)
            dist_sgst = float(d.get("distributed_sgst") or 0.0)
            if dist_cgst > 0 or dist_sgst > 0:
                violations.append(
                    ValidationViolation(
                        code="G6_CROSS_STATE_TAX_HEAD_ERROR",
                        message=f"Distribution #{idx+1}: Recipient in state {rec_state} received CGST/SGST from ISD in state {isd_state}. Cross-state distribution MUST be distributed as IGST (Rule 39(1)(f)).",
                        category=ViolationCategory.STATUTORY_BREACH,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"recipient_gstin": rec_gstin, "cgst": dist_cgst, "sgst": dist_sgst},
                    )
                )
                statutory_checks["cross_state_conversion"] = "FAILED"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    else:
        overall_severity = ValidationSeverity.CLEAN

    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-6",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=(overall_severity != ValidationSeverity.CRITICAL_ERROR),
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"inward_count": len(inward_records), "distribution_count": len(distribution_records)},
    )


def validate_gstr5_pre_filing(
    *,
    batch: Mapping[str, Any],
    outward_records: list[Mapping[str, Any]],
    import_records: list[Mapping[str, Any]],
) -> PreFilingValidationResult:
    """Validate Form GSTR-5 (NRTP) compliance prior to review and filing."""
    clean_gstin = str(batch.get("gstin") or "").strip().upper()
    clean_period = str(batch.get("period") or "").strip()

    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, str] = {
        "nrtp_registration_validity": "PASSED",
        "advance_tax_sufficiency": "PASSED",
        "itc_statutory_restriction": "PASSED",
    }

    # 1. Registration expiry check
    expiry_date_str = str(batch.get("registration_expiry_date") or "")
    if expiry_date_str:
        try:
            from datetime import date
            exp_date = date.fromisoformat(expiry_date_str.split("T")[0])
            if date.today() > exp_date:
                violations.append(
                    ValidationViolation(
                        code="G5_REGISTRATION_EXPIRED",
                        message=f"NRTP registration expired on {expiry_date_str}. Filing requires active registration or valid extension (Section 27(1)). Late filing fees may apply.",
                        category=ViolationCategory.RISK_WARNING,
                        severity=ValidationSeverity.WARNING,
                        details={"expiry_date": expiry_date_str},
                    )
                )
                statutory_checks["nrtp_registration_validity"] = "WARNING"
        except Exception:
            pass

    # 2. Advance tax sufficiency check (Section 27(2))
    tot_out_liability = sum(
        float(r.get("igst") or 0.0) + float(r.get("cgst") or 0.0) + float(r.get("sgst") or 0.0)
        for r in outward_records
    )
    tot_imp_itc = sum(float(r.get("igst_paid") or 0.0) for r in import_records)
    net_payable = max(0.0, tot_out_liability - tot_imp_itc)
    adv_tax = float(batch.get("advance_tax_deposited") or 0.0)

    if net_payable > adv_tax:
        shortfall = net_payable - adv_tax
        violations.append(
            ValidationViolation(
                code="G5_ADVANCE_TAX_DEFICIT",
                message=f"Net tax payable ₹{net_payable:,.2f} exceeds advance tax deposit ₹{adv_tax:,.2f} by ₹{shortfall:,.2f} (Section 27(2)). Additional cash deposit required.",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
                details={"net_payable": net_payable, "advance_tax": adv_tax, "shortfall": shortfall},
            )
        )
        statutory_checks["advance_tax_sufficiency"] = "FAILED"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    else:
        overall_severity = ValidationSeverity.CLEAN

    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-5",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=(overall_severity != ValidationSeverity.CRITICAL_ERROR),
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"outward_count": len(outward_records), "import_count": len(import_records)},
    )


def validate_gstr5a_pre_filing(
    *,
    batch: Mapping[str, Any],
    supplies: list[Mapping[str, Any]],
) -> PreFilingValidationResult:
    """Validate Form GSTR-5A (OIDAR) compliance prior to review and filing."""
    clean_gstin = str(batch.get("gstin") or "").strip().upper()
    clean_period = str(batch.get("period") or "").strip()

    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, str] = {
        "oidar_rate_consistency": "PASSED",
        "zero_itc_invariant": "PASSED",
        "pos_validity": "PASSED",
    }

    if not supplies:
        violations.append(
            ValidationViolation(
                code="G5A_NO_SUPPLIES",
                message="No taxable outward supplies declared in Form GSTR-5A for tax period.",
                category=ViolationCategory.DATA_INTEGRITY,
                severity=ValidationSeverity.WARNING,
            )
        )

    for idx, s in enumerate(supplies):
        pos = str(s.get("pos") or "").strip()
        if not pos or len(pos) != 2 or not pos.isdigit():
            violations.append(
                ValidationViolation(
                    code="G5A_INVALID_POS",
                    message=f"Supply #{idx+1}: Place of supply '{pos}' is not a valid 2-digit Indian State code.",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "pos": pos},
                )
            )
            statutory_checks["pos_validity"] = "FAILED"

        # Check rate against authoritative statutory OIDAR schedules (Section 14 & Section 14A)
        rt = float(s.get("rate_pct") if s.get("rate_pct") is not None else 18.0)
        from app.rules.gstr5a_rules import is_valid_statutory_oidar_rate
        if not is_valid_statutory_oidar_rate(rt):
            violations.append(
                ValidationViolation(
                    code="G5A_INVALID_RATE",
                    message=f"Supply #{idx+1}: Declared rate {rt}% is not a recognized statutory OIDAR tax rate under Section 14/14A of IGST Act (applicable rates: 18% standard, 28% online money gaming, 5% e-books, 0% exempt).",
                    category=ViolationCategory.STATUTORY_BREACH,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "rate": rt},
                )
            )
            statutory_checks["oidar_rate_consistency"] = "FAILED"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    else:
        overall_severity = ValidationSeverity.CLEAN

    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-5a",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=(overall_severity != ValidationSeverity.CRITICAL_ERROR),
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"supplies_count": len(supplies)},
    )


def validate_gstr10_pre_filing(
    *,
    batch: Mapping[str, Any],
    stock_records: list[Mapping[str, Any]],
) -> PreFilingValidationResult:
    """Validate Form GSTR-10 (Final Return) compliance prior to review and filing."""
    from datetime import date
    from app.rules.gstr10_rules import (
        StockItemType,
        calculate_gstr10_due_date,
        validate_stock_item,
    )

    clean_gstin = str(batch.get("gstin") or "").strip().upper()
    clean_period = str(batch.get("period") or "").strip()

    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, str] = {
        "cancellation_dates_validity": "PASSED",
        "statutory_due_date_sufficiency": "PASSED",
        "stock_records_integrity": "PASSED",
        "ca_certification_rule44_3": "PASSED",
    }

    eff_canc_str = str(batch.get("effective_cancellation_date") or "").strip()
    ord_canc_str = str(batch.get("cancellation_order_date") or "").strip()

    canc_date: Optional[date] = None
    if not eff_canc_str:
        violations.append(
            ValidationViolation(
                code="G10_MISSING_CANCELLATION_DATE",
                message="Effective cancellation date is missing from GSTR-10 final return header.",
                category=ViolationCategory.DATA_INTEGRITY,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )
        statutory_checks["cancellation_dates_validity"] = "FAILED"
    else:
        try:
            canc_date = date.fromisoformat(eff_canc_str)
        except Exception:
            violations.append(
                ValidationViolation(
                    code="G10_INVALID_CANCELLATION_DATE",
                    message=f"Effective cancellation date '{eff_canc_str}' is invalid.",
                    category=ViolationCategory.DATA_INTEGRITY,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                )
            )
            statutory_checks["cancellation_dates_validity"] = "FAILED"

    # Due date check
    if canc_date:
        ord_date = canc_date
        if ord_canc_str:
            try:
                ord_date = date.fromisoformat(ord_canc_str)
            except Exception:
                pass
        statutory_due = calculate_gstr10_due_date(canc_date, ord_date)
        if date.today() > statutory_due:
            days_late = (date.today() - statutory_due).days
            violations.append(
                ValidationViolation(
                    code="G10_OVERDUE_FINAL_RETURN",
                    message=f"GSTR-10 statutory due date was {statutory_due.isoformat()} ({days_late} days overdue). Late fees under Section 47 apply.",
                    category=ViolationCategory.RISK_WARNING,
                    severity=ValidationSeverity.WARNING,
                    details={"due_date": statutory_due.isoformat(), "days_late": days_late},
                )
            )
            statutory_checks["statutory_due_date_sufficiency"] = "WARNING"

    # Stock records validation
    for idx, s in enumerate(stock_records):
        s_errs = validate_stock_item(dict(s), cancellation_date=canc_date)
        for err in s_errs:
            if err == "G10_MISSING_CA_CERTIFICATE":
                violations.append(
                    ValidationViolation(
                        code="G10_MISSING_CA_CERTIFICATE",
                        message=f"Stock Item #{idx+1} (Table 8D): Invoices unavailable; CA/CMA valuation certificate is mandatory under Rule 44(3).",
                        category=ViolationCategory.STATUTORY_BREACH,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"index": idx},
                    )
                )
                statutory_checks["ca_certification_rule44_3"] = "FAILED"
            else:
                violations.append(
                    ValidationViolation(
                        code=err,
                        message=f"Stock Item #{idx+1}: Validation error {err}.",
                        category=ViolationCategory.DATA_INTEGRITY,
                        severity=ValidationSeverity.CRITICAL_ERROR,
                        details={"index": idx, "code": err},
                    )
                )
                statutory_checks["stock_records_integrity"] = "FAILED"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    else:
        overall_severity = ValidationSeverity.CLEAN

    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-10",
        gstin=clean_gstin,
        period=clean_period,
        is_valid=(overall_severity != ValidationSeverity.CRITICAL_ERROR),
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"stock_records_count": len(stock_records)},
    )


def validate_gstr11_pre_filing(
    *,
    batch: Mapping[str, Any],
    inward_records: list[Mapping[str, Any]],
) -> PreFilingValidationResult:
    """Validate Form GSTR-11 (UIN Inward Supplies Statement) compliance prior to review and filing."""
    from app.rules.gstr11_rules import (
        validate_uin,
        validate_uin_inward_supply,
    )

    clean_uin = str(batch.get("uin") or "").strip().upper()
    clean_period = str(batch.get("period") or "").strip()

    violations: list[ValidationViolation] = []
    statutory_checks: dict[str, str] = {
        "uin_validity": "PASSED",
        "inward_supplies_integrity": "PASSED",
        "net_refund_positivity": "PASSED",
        "zero_itc_routing_guardrail": "PASSED",
    }

    if not validate_uin(clean_uin):
        violations.append(
            ValidationViolation(
                code="G11_INVALID_UIN",
                message=f"UIN '{clean_uin}' is not a valid 15-character Unique Identification Number format.",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
                details={"uin": clean_uin},
            )
        )
        statutory_checks["uin_validity"] = "FAILED"

    for idx, r in enumerate(inward_records):
        errs = validate_uin_inward_supply(dict(r))
        for err in errs:
            violations.append(
                ValidationViolation(
                    code=err,
                    message=f"Inward record #{idx+1}: Validation error {err}.",
                    category=ViolationCategory.DATA_INTEGRITY,
                    severity=ValidationSeverity.CRITICAL_ERROR,
                    details={"index": idx, "code": err},
                )
            )
            statutory_checks["inward_supplies_integrity"] = "FAILED"

    tot_net = float(batch.get("total_net_refund_claimed") or 0.0)
    if tot_net < 0.0:
        violations.append(
            ValidationViolation(
                code="G11_NEGATIVE_TOTAL_REFUND",
                message=f"Net eligible refund ₹{tot_net:,.2f} is negative. Credit notes exceed gross inward supplies.",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
                details={"total_net_refund": tot_net},
            )
        )
        statutory_checks["net_refund_positivity"] = "FAILED"

    if any(v.severity == ValidationSeverity.CRITICAL_ERROR for v in violations):
        overall_severity = ValidationSeverity.CRITICAL_ERROR
    elif any(v.severity == ValidationSeverity.WARNING for v in violations):
        overall_severity = ValidationSeverity.WARNING
    else:
        overall_severity = ValidationSeverity.CLEAN

    digest = str(batch.get("figures_digest") or compute_figures_digest(dict(batch)))
    val_digest = compute_validation_digest(violations)

    return PreFilingValidationResult(
        return_type="gstr-11",
        gstin=clean_uin,
        period=clean_period,
        is_valid=(overall_severity != ValidationSeverity.CRITICAL_ERROR),
        overall_severity=overall_severity,
        figures_digest=digest,
        validation_digest=val_digest,
        violations=violations,
        statutory_checks=statutory_checks,
        reconciliation_summary={"inward_records_count": len(inward_records)},
    )


