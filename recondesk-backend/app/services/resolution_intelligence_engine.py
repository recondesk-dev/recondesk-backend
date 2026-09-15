"""Resolution Intelligence / Exception Intelligence Engine (Phase 5.4).

Purely deterministic, read-only operational explanation and guidance service.
Synthesizes root cause explanations, concrete evidence points, operational
resolution difficulty, next best actions, and revalidation readiness.

Non-negotiable architectural invariant:
"Phase 5 manages the work. It does not decide the tax."
Zero database mutations.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from supabase import Client

from app.services.normalizer import normalize_gstin

_log = logging.getLogger(__name__)


def _parse_date_safe(d_str: Optional[str]) -> Optional[date]:
    """Parse common date formats safely without throwing exceptions."""
    if not d_str:
        return None
    d_clean = str(d_str).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(d_clean, fmt).date()
        except ValueError:
            pass
    return None


def _calculate_age_days(invoice_date_str: Optional[str], ref_date: Optional[date] = None) -> int:
    """Calculate operational age in days from invoice date to reference date."""
    inv_d = _parse_date_safe(invoice_date_str)
    if not inv_d:
        return 0
    today = ref_date or datetime.now(timezone.utc).date()
    delta = (today - inv_d).days
    return max(0, delta)


def get_work_item_resolution_intelligence(
    sb: Client,
    item: dict[str, Any],
    current_user: dict[str, Any],
) -> dict[str, Any]:
    """Synthesize complete resolution intelligence for an ITC work item.

    Pure read-only operation:
    - No INSERT
    - No UPDATE
    - No DELETE
    - No statutory tax adjudication
    """
    wid = str(item.get("id") or "")
    client_id = str(item.get("client_gstin_id") or "")
    firm_id = str(item.get("firm_owner_id") or "")
    ex_type = str(item.get("exception_type") or "OTHER").strip().upper()
    current_status = str(item.get("status") or "OPEN").strip().upper()
    is_blocking = bool(item.get("is_blocking"))
    vendor_gstin = str(item.get("vendor_gstin") or "").strip().upper()
    vendor_name = str(item.get("vendor_name") or "").strip()
    inv_num = str(item.get("invoice_number") or "").strip()
    inv_date = str(item.get("invoice_date") or "").strip()
    tax_paise = int(item.get("itc_amount_at_stake_paise") or 0)
    tax_rupees = float(item.get("itc_amount_at_stake") or (tax_paise / 100.0))
    reval_status = str(item.get("revalidation_status") or "NONE").upper()
    reval_result = str(item.get("revalidation_result") or "").upper()
    source_version = int(item.get("source_version") or 1)
    carried_forward = bool(item.get("carried_forward_from_id"))
    sla_status = str(item.get("sla_status") or "NO_DUE_DATE").upper()
    due_at = item.get("due_at")
    user_role = str(current_user.get("role") or "staff").lower()
    is_admin = user_role in ("admin", "owner")

    # 1. Fetch precomputed supplier compliance scorecard (read-only)
    summary_data: dict[str, Any] = {}
    if vendor_gstin and firm_id:
        try:
            norm_gstin = normalize_gstin(vendor_gstin)
        except Exception:
            norm_gstin = vendor_gstin

        try:
            res = (
                sb.table("supplier_compliance_summary")
                .select("*")
                .eq("firm_owner_id", firm_id)
                .eq("supplier_gstin_normalized", norm_gstin)
                .limit(1)
                .execute()
            )
            if res.data:
                summary_data = res.data[0]
        except Exception as exc:
            _log.warning("supplier_compliance_summary lookup failed: %s", exc)

    # 2. Fetch follow-up dispatch logs for this work item (read-only)
    followup_logs: list[dict[str, Any]] = []
    if wid:
        try:
            res = (
                sb.table("vendor_followup_logs")
                .select("id, channel, template_type, status, dispatched_at, message_body")
                .eq("work_item_id", wid)
                .order("dispatched_at", desc=True)
                .limit(25)
                .execute()
            )
            followup_logs = res.data or []
        except Exception as exc:
            _log.warning("vendor_followup_logs lookup failed: %s", exc)

    # 3. Analyze work-item timeline events (read-only)
    events: list[dict[str, Any]] = item.get("events") or []
    vendor_responses = [e for e in events if e.get("event_type") == "VENDOR_RESPONSE_RECORDED"]
    latest_response = vendor_responses[-1] if vendor_responses else None
    latest_response_meta = (latest_response.get("metadata") or {}) if latest_response else {}
    latest_response_cat = str(latest_response_meta.get("response_category") or "").upper() if latest_response_meta else None

    reopen_events = [e for e in events if e.get("event_type") == "REOPENED"]
    reval_events = [e for e in events if e.get("event_type") == "REVALIDATION_REQUESTED"]

    # 4. Synthesize Root Cause Explanation & Confidence
    root_cause = _build_root_cause_explanation(
        ex_type=ex_type,
        inv_num=inv_num,
        inv_date=inv_date,
        tax_rupees=tax_rupees,
        vendor_name=vendor_name or vendor_gstin or "Supplier",
        vendor_gstin=vendor_gstin,
        item=item,
        summary_data=summary_data,
    )

    # 5. Compile Concrete Evidence Points
    age_days = _calculate_age_days(inv_date)
    evidence = _compile_evidence_points(
        ex_type=ex_type,
        tax_rupees=tax_rupees,
        age_days=age_days,
        item=item,
        summary_data=summary_data,
        followup_logs=followup_logs,
        latest_response_cat=latest_response_cat,
        latest_response_meta=latest_response_meta,
        reopen_count=len(reopen_events),
        carried_forward=carried_forward,
        source_version=source_version,
    )

    # 6. Compute Operational Resolution Difficulty Score (0-100)
    resolution_difficulty = _compute_resolution_difficulty(
        is_blocking=is_blocking,
        summary_data=summary_data,
        age_days=age_days,
        followup_count=len(followup_logs),
        latest_response_cat=latest_response_cat,
        reopen_count=len(reopen_events),
        reval_result=reval_result,
        sla_status=sla_status,
        current_status=current_status,
    )

    # 7. Recommend Next Best Action
    next_action = _recommend_next_best_action(
        ex_type=ex_type,
        current_status=current_status,
        is_blocking=is_blocking,
        is_admin=is_admin,
        followup_count=len(followup_logs),
        latest_response_cat=latest_response_cat,
        reval_status=reval_status,
        vendor_gstin=vendor_gstin,
    )

    # 8. Formulate Revalidation Guidance
    reval_guidance = _formulate_revalidation_guidance(
        ex_type=ex_type,
        reval_status=reval_status,
        followup_count=len(followup_logs),
        latest_response_cat=latest_response_cat,
    )

    return {
        "work_item_id": wid,
        "exception_type": ex_type,
        "root_cause_explanation": root_cause,
        "evidence": evidence,
        "resolution_difficulty": resolution_difficulty,
        "next_best_action": next_action,
        "revalidation_guidance": reval_guidance,
    }


def _build_root_cause_explanation(
    ex_type: str,
    inv_num: str,
    inv_date: str,
    tax_rupees: float,
    vendor_name: str,
    vendor_gstin: str,
    item: dict[str, Any],
    summary_data: dict[str, Any],
) -> dict[str, str]:
    """Formulate deterministic explanation for what happened and why it likely occurred."""
    what = ""
    likely_reason = ""
    confidence = "HIGH"

    late_filing_rate = float(summary_data.get("late_filing_rate") or 0.0)
    mismatch_rate = float(summary_data.get("mismatch_rate") or 0.0)

    if ex_type == "MISSING_2B":
        what = f"Invoice {inv_num or '—'} (₹{tax_rupees:,.2f} ITC) is booked in the Purchase Register but is missing from GSTR-2B."
        if late_filing_rate >= 0.25:
            likely_reason = (
                f"Supplier '{vendor_name}' has a historical late filing rate of {late_filing_rate * 100:.1f}%. "
                "The invoice was likely omitted from the vendor's periodic GSTR-1 or filed after the monthly cutoff date."
            )
            confidence = "HIGH"
        elif summary_data.get("pr_only_count", 0) > 2:
            likely_reason = (
                f"Supplier '{vendor_name}' has {summary_data.get('pr_only_count')} other unfiled invoices in the firm ledger. "
                "Supplier has an ongoing pattern of missing outward filings."
            )
            confidence = "HIGH"
        else:
            likely_reason = (
                f"Supplier '{vendor_name}' has not uploaded this invoice in their outward GSTR-1/IFF return for this period, "
                "or filed under an alternate client GSTIN."
            )
            confidence = "MEDIUM"

    elif ex_type == "2B_ONLY":
        what = f"Supplier '{vendor_name}' reported invoice {inv_num or '—'} in GSTR-1 (reflected in GSTR-2B), but no matching entry exists in the client's books."
        likely_reason = (
            "Potential unbooked procurement expenditure or valid business purchase invoice not yet entered into the client's accounting software."
        )
        confidence = "HIGH"

    elif ex_type == "SEC_17_5":
        what = f"Input tax credit on invoice {inv_num or '—'} (₹{tax_rupees:,.2f}) is blocked under Section 17(5) of the CGST Act."
        likely_reason = (
            "The procurement belongs to statutorily ineligible categories (such as motor vehicles, employee food/catering, "
            "club memberships, works contract for immovable property, or personal consumption)."
        )
        confidence = "HIGH"

    elif ex_type == "RULE_37":
        what = f"Invoice {inv_num or '—'} is flagged under Rule 37 for unpaid supplier consideration exceeding 180 days."
        likely_reason = (
            "Proviso to Section 16(2) and Rule 37 mandate ITC reversal with 18% interest if the recipient fails to pay "
            f"the supplier within 180 days from the invoice date ({inv_date or 'recorded date'})."
        )
        confidence = "HIGH"

    elif ex_type == "RULE_37A":
        what = f"Invoice {inv_num or '—'} flagged under Rule 37A due to supplier non-filing of GSTR-3B."
        likely_reason = (
            "Rule 37A requires recipient to reverse ITC where the supplier reported the invoice in GSTR-1 but failed to "
            "furnish their corresponding GSTR-3B return by the statutory 30th November deadline."
        )
        confidence = "HIGH"

    elif ex_type == "GSTIN_MISMATCH":
        what = f"Supplier GSTIN recorded in books ({vendor_gstin or '—'}) differs from the supplier GSTIN in GSTR-2B."
        likely_reason = (
            "Commonly occurs when the supplier bills from an alternate state branch GSTIN sharing the same PAN, "
            "or due to a transcription typo in the client's vendor master."
        )
        confidence = "HIGH"

    elif ex_type == "VALUE_MISMATCH":
        igst_val = float(item.get("igst") or 0.0)
        cgst_val = float(item.get("cgst") or 0.0)
        sgst_val = float(item.get("sgst") or 0.0)
        what = f"Tax differential of ₹{tax_rupees:,.2f} exists between Purchase Register and GSTR-2B data."
        if igst_val > 0 and (cgst_val > 0 or sgst_val > 0):
            likely_reason = (
                "Inter-state vs intra-state tax head discrepancy: books reflect IGST whereas GSTR-2B reflects CGST/SGST (or vice-versa)."
            )
            confidence = "HIGH"
        elif mismatch_rate >= 0.20:
            likely_reason = (
                f"Supplier '{vendor_name}' has a {mismatch_rate * 100:.1f}% mismatch rate across firm records; "
                "likely caused by rounding differences, debit/credit note adjustments, or tax rate variations."
            )
            confidence = "HIGH"
        else:
            likely_reason = (
                "Discrepancy in taxable value, differing item tax rates, or post-invoice adjustments between buyer and seller."
            )
            confidence = "MEDIUM"

    elif ex_type == "DUPLICATE":
        what = f"Duplicate invoice entry identified for invoice number {inv_num or '—'}."
        likely_reason = (
            "Same invoice number was entered twice in the client's accounting ledger or filed across multiple tax periods by the supplier."
        )
        confidence = "HIGH"

    elif ex_type == "TIME_BARRED_16_4":
        what = f"Input tax credit on invoice {inv_num or '—'} is barred by limitation under Section 16(4)."
        likely_reason = (
            "Invoice pertains to a previous financial year and was filed past the Section 16(4) statutory deadline (30th November)."
        )
        confidence = "HIGH"

    statutory_context_map = {
        "MISSING_2B": "Section 16(2)(aa) of the CGST Act requires invoice details to be furnished by the supplier in GSTR-1 and communicated to the recipient in GSTR-2B before ITC can be availed.",
        "2B_ONLY": "Section 16(2)(a) requires possession of a valid tax invoice or debit note and corresponding booking in the recipient's books of account.",
        "SEC_17_5": "Section 17(5) of the CGST Act explicitly blocks input tax credit on specified goods and services regardless of business use.",
        "RULE_37": "Second proviso to Section 16(2) and Rule 37 mandate ITC reversal along with 18% interest under Section 50 if consideration is unpaid after 180 days.",
        "RULE_37A": "Rule 37A of the CGST Rules mandates reversal of ITC where the supplier failed to furnish GSTR-3B by the statutory 30th November deadline.",
        "GSTIN_MISMATCH": "Section 16(2)(a) requires the tax invoice to correctly identify the registered recipient and supplier GSTIN.",
        "VALUE_MISMATCH": "Section 16(2) allows ITC only up to the tax actually paid or charged by the supplier under valid tax invoice particulars.",
        "DUPLICATE": "Section 16 allows input tax credit only once per valid invoice or debit note.",
        "TIME_BARRED_16_4": "Section 16(4) of the CGST Act bars claiming ITC after the 30th November following the end of the financial year to which the invoice pertains.",
        "OTHER": "General GST compliance review under Chapter V (Input Tax Credit) of the CGST Act, 2017.",
    }
    statutory_context = statutory_context_map.get(ex_type, statutory_context_map["OTHER"])

    return {
        "what_happened": what,
        "likely_root_cause": likely_reason,
        "likely_reason": likely_reason,
        "statutory_context": statutory_context,
        "confidence_level": confidence,
        "confidence": confidence,
        "confidence_rationale": f"Determined deterministically from authoritative reconciliation outcome and {ex_type} statutory rules.",
    }


def _compile_evidence_points(
    ex_type: str,
    tax_rupees: float,
    age_days: int,
    item: dict[str, Any],
    summary_data: dict[str, Any],
    followup_logs: list[dict[str, Any]],
    latest_response_cat: Optional[str],
    latest_response_meta: dict[str, Any],
    reopen_count: int,
    carried_forward: bool,
    source_version: int,
) -> list[dict[str, str]]:
    """Compile concrete, structured evidence points supporting the explanation."""
    evidence: list[dict[str, str]] = []

    # 1. Financial Impact
    evidence.append({
        "label": "ITC Amount at Stake",
        "value": f"₹{tax_rupees:,.2f}",
        "severity": "HIGH" if tax_rupees >= 50000.0 else ("WARNING" if tax_rupees >= 10000.0 else "INFO"),
    })

    # 2. Tax Head Diffs if available
    igst_val = float(item.get("igst") or 0.0)
    cgst_val = float(item.get("cgst") or 0.0)
    sgst_val = float(item.get("sgst") or 0.0)
    if igst_val > 0 or cgst_val > 0 or sgst_val > 0:
        evidence.append({
            "label": "Tax Heads in Books",
            "value": f"IGST: ₹{igst_val:,.2f} | CGST: ₹{cgst_val:,.2f} | SGST: ₹{sgst_val:,.2f}",
            "severity": "INFO",
        })

    # 3. Operational Aging
    if age_days > 0:
        evidence.append({
            "label": "Invoice Age",
            "value": f"{age_days} days since invoice date",
            "severity": "HIGH" if age_days > 180 else ("WARNING" if age_days > 90 else "INFO"),
        })

    # 4. Supplier Historical Metrics (if precomputed scorecard exists)
    if summary_data:
        late_rate = float(summary_data.get("late_filing_rate") or 0.0)
        risk_tier = str(summary_data.get("risk_tier") or "LOW_RISK")
        mismatch_rate = float(summary_data.get("mismatch_rate") or 0.0)

        evidence.append({
            "label": "Supplier Risk Tier",
            "value": f"{risk_tier} (Score: {summary_data.get('risk_score', 0)}/100)",
            "severity": "HIGH" if risk_tier in ("HIGH_RISK", "CRITICAL_RISK") else "INFO",
        })

        if late_rate > 0:
            evidence.append({
                "label": "Supplier Late Filing Rate",
                "value": f"{late_rate * 100:.1f}% ({summary_data.get('late_filing_count', 0)} late filings)",
                "severity": "WARNING" if late_rate >= 0.20 else "INFO",
            })

        if mismatch_rate > 0:
            evidence.append({
                "label": "Supplier Mismatch Rate",
                "value": f"{mismatch_rate * 100:.1f}% ({summary_data.get('mismatch_invoice_count', 0)} mismatches)",
                "severity": "WARNING" if mismatch_rate >= 0.20 else "INFO",
            })

    # 5. Follow-up History
    if followup_logs:
        last_log = followup_logs[0]
        evidence.append({
            "label": "Previous Follow-Ups",
            "value": f"{len(followup_logs)} attempt(s) (Latest via {last_log.get('channel')})",
            "severity": "INFO",
        })

    # 6. Latest Vendor Response
    if latest_response_cat:
        promised_date = latest_response_meta.get("promised_date")
        evidence.append({
            "label": "Latest Vendor Response",
            "value": f"{latest_response_cat}" + (f" (Promised Date: {promised_date})" if promised_date else ""),
            "severity": "WARNING" if latest_response_cat in ("DISPUTED", "NO_SUCH_INVOICE") else "INFO",
        })

    # 7. Carried Forward / Versioning
    if carried_forward or source_version > 1:
        evidence.append({
            "label": "Carried-Forward Exception",
            "value": f"Recurring across cycles (Source Version: {source_version})",
            "severity": "WARNING",
        })

    # 8. Reopen Count
    if reopen_count > 0:
        evidence.append({
            "label": "Reopened Count",
            "value": f"Reopened {reopen_count} time(s)",
            "severity": "WARNING",
        })

    return evidence


def _compute_resolution_difficulty(
    is_blocking: bool,
    summary_data: dict[str, Any],
    age_days: int,
    followup_count: int,
    latest_response_cat: Optional[str],
    reopen_count: int,
    reval_result: str,
    sla_status: str,
    current_status: str,
) -> dict[str, Any]:
    """Compute deterministic operational resolution difficulty score (0-100).

    Does NOT calculate statutory tax liability. Strictly reflects operational friction.
    """
    disclaimer = (
        "Operational resolution difficulty indicates the expected administrative effort and friction "
        "required to resolve this exception. It is NOT statutory tax audit risk or vendor compliance score."
    )

    if current_status == "RESOLVED":
        return {
            "score": 0,
            "tier": "LOW",
            "factors": [],
            "contributing_factors": ["Work item has been resolved."],
            "disclaimer": disclaimer,
        }

    score = 0
    factors: list[str] = []
    factor_objs: list[dict[str, Any]] = []

    # 1. Blocking Gate Status
    if is_blocking:
        score += 25
        msg = "Blocking exception requiring mandatory CA review and approval."
        factors.append(msg)
        factor_objs.append({"dimension": "STATUTORY_BLOCKER", "impact_points": 25, "rationale": msg})

    # 2. Supplier Compliance Tier
    risk_tier = str(summary_data.get("risk_tier") or summary_data.get("compliance_risk_tier") or "LOW_RISK")
    if risk_tier == "CRITICAL_RISK":
        score += 30
        msg = "Supplier compliance history classified as CRITICAL_RISK tier."
        factors.append(msg)
        factor_objs.append({"dimension": "SUPPLIER_RISK", "impact_points": 30, "rationale": msg})
    elif risk_tier == "HIGH_RISK":
        score += 20
        msg = "Supplier compliance history classified as HIGH_RISK tier."
        factors.append(msg)
        factor_objs.append({"dimension": "SUPPLIER_RISK", "impact_points": 20, "rationale": msg})
    elif risk_tier == "MEDIUM_RISK":
        score += 10
        msg = "Supplier has moderate historical compliance friction."
        factors.append(msg)
        factor_objs.append({"dimension": "SUPPLIER_RISK", "impact_points": 10, "rationale": msg})

    # 3. Operational Aging
    if age_days > 180:
        score += 20
        msg = f"Invoice age ({age_days} days) exceeds 180 days."
        factors.append(msg)
        factor_objs.append({"dimension": "AGING", "impact_points": 20, "rationale": msg})
    elif age_days > 90:
        score += 10
        msg = f"Invoice age ({age_days} days) exceeds 90 days."
        factors.append(msg)
        factor_objs.append({"dimension": "AGING", "impact_points": 10, "rationale": msg})

    # 4. Repeated Follow-up Resistance
    if followup_count >= 3:
        score += 15
        msg = f"Multiple follow-up attempts ({followup_count}) without successful resolution."
        factors.append(msg)
        factor_objs.append({"dimension": "FOLLOWUP_RESISTANCE", "impact_points": 15, "rationale": msg})
    elif followup_count >= 1:
        score += 5
        msg = f"Active outreach underway ({followup_count} follow-up dispatched)."
        factors.append(msg)
        factor_objs.append({"dimension": "FOLLOWUP_OUTREACH", "impact_points": 5, "rationale": msg})

    # 5. Adverse Vendor Response
    if latest_response_cat in ("DISPUTED", "NO_SUCH_INVOICE"):
        score += 20
        msg = f"Vendor disputed or denied the invoice ({latest_response_cat})."
        factors.append(msg)
        factor_objs.append({"dimension": "VENDOR_DISPUTE", "impact_points": 20, "rationale": msg})
    elif latest_response_cat == "WILL_FILE_NEXT_PERIOD":
        score += 5
        msg = "Vendor promised filing in next period; awaiting outward return."
        factors.append(msg)
        factor_objs.append({"dimension": "FUTURE_FILING_DEPENDENCY", "impact_points": 5, "rationale": msg})

    # 6. Reopen History
    if reopen_count >= 1:
        reopen_pts = min(20, reopen_count * 10)
        score += reopen_pts
        msg = f"Work item was previously reopened ({reopen_count} times)."
        factors.append(msg)
        factor_objs.append({"dimension": "REOPEN_HISTORY", "impact_points": reopen_pts, "rationale": msg})

    # 7. Failed Revalidations
    if reval_result in ("EXCEPTION_REMAINED", "STILL_FAILING"):
        score += 15
        msg = "Previous revalidation cycle failed to clear the exception."
        factors.append(msg)
        factor_objs.append({"dimension": "REVALIDATION_FAILURE", "impact_points": 15, "rationale": msg})

    # 8. Operational SLA Status
    if sla_status == "OVERDUE":
        score += 10
        msg = "Operational target resolution date is OVERDUE."
        factors.append(msg)
        factor_objs.append({"dimension": "SLA_OVERDUE", "impact_points": 10, "rationale": msg})
    elif sla_status == "DUE_SOON":
        score += 5
        msg = "Operational target resolution deadline is DUE_SOON."
        factors.append(msg)
        factor_objs.append({"dimension": "SLA_DUE_SOON", "impact_points": 5, "rationale": msg})

    final_score = max(0, min(100, score))

    if final_score <= 25:
        tier = "LOW"
    elif final_score <= 50:
        tier = "MEDIUM"
    elif final_score <= 75:
        tier = "HIGH"
    else:
        tier = "VERY_HIGH"

    if not factors:
        factors.append("Standard operational exception with no adverse friction signals.")
        factor_objs.append({"dimension": "STANDARD", "impact_points": 0, "rationale": "No adverse friction signals."})

    return {
        "score": final_score,
        "tier": tier,
        "factors": factor_objs,
        "contributing_factors": factors,
        "disclaimer": disclaimer,
    }


def _recommend_next_best_action(
    ex_type: str,
    current_status: str,
    is_blocking: bool,
    is_admin: bool,
    followup_count: int,
    latest_response_cat: Optional[str],
    reval_status: str,
    vendor_gstin: str,
) -> dict[str, Any]:
    """Deterministically select next best operational action mapped to existing endpoints."""
    if current_status == "RESOLVED":
        if reval_status != "PENDING" and ex_type != "SEC_17_5":
            return {
                "action_type": "REVALIDATE_INVOICE",
                "action_code": "REVALIDATE_INVOICE",
                "title": "Request Revalidation",
                "label": "Request Revalidation",
                "description": "Exception resolved; queue invoice for re-evaluation in next reconciliation.",
                "urgency": "NORMAL",
                "suggested_modal_or_tab": "REVALIDATE",
                "requires_role": None,
                "prerequisites": ["Item must be in RESOLVED state."],
            }
        return {
            "action_type": "NO_ACTION",
            "action_code": "NO_ACTION",
            "title": "Work Item Resolved",
            "label": "Work Item Resolved",
            "description": "Exception has been resolved. No further operational action required.",
            "urgency": "NORMAL",
            "suggested_modal_or_tab": "DETAILS",
            "requires_role": None,
            "prerequisites": [],
        }

    if reval_status == "PENDING":
        return {
            "action_type": "AWAIT_REVALIDATION",
            "action_code": "AWAIT_REVALIDATION",
            "title": "Awaiting Reconciliation Cycle",
            "label": "Awaiting Reconciliation Cycle",
            "description": "Revalidation request is queued. Run the next periodic reconciliation to revalidate.",
            "urgency": "NORMAL",
            "suggested_modal_or_tab": "DETAILS",
            "requires_role": None,
            "prerequisites": ["Revalidation must be executed during next recon run."],
        }

    if ex_type == "SEC_17_5":
        if is_blocking and not is_admin:
            return {
                "action_type": "SUBMIT_FOR_CA_REVIEW",
                "action_code": "SUBMIT_FOR_CA_REVIEW",
                "title": "Submit 17(5) Reversal for CA Review",
                "label": "Submit 17(5) Reversal for CA Review",
                "description": "Submit blocked credit determination to CA for mandatory review and permanent Table 4(B)(1) sign-off.",
                "urgency": "HIGH",
                "suggested_modal_or_tab": "RESOLVE",
                "requires_role": "admin",
                "prerequisites": ["Review Section 17(5) statutory ineligibility."],
            }
        return {
            "action_type": "DISPOSITION_OR_RESOLVE",
            "action_code": "APPROVE_AND_RESOLVE",
            "title": "Apply Permanent Table 4(B)(1) Reversal",
            "label": "Apply Permanent Table 4(B)(1) Reversal",
            "description": "Confirm Section 17(5) ineligibility and record permanent statutory reversal disposition.",
            "urgency": "HIGH",
            "suggested_modal_or_tab": "RESOLVE",
            "requires_role": None,
            "prerequisites": ["CA sign-off on Table 4(B)(1) reversal."],
        }

    if ex_type == "RULE_37":
        if followup_count == 0:
            return {
                "action_type": "DISPATCH_VENDOR_FOLLOWUP",
                "action_code": "GENERATE_FORMAL_NOTICE",
                "title": "Dispatch Rule 37 Overdue Notice",
                "label": "Dispatch Rule 37 Overdue Notice",
                "description": "Send formal 180-day overdue tax notice with statutory 18% interest warning via email or WhatsApp.",
                "urgency": "HIGH",
                "suggested_modal_or_tab": "COMMUNICATION",
                "requires_role": None,
                "prerequisites": ["Invoice age exceeds 180 days."],
            }
        return {
            "action_type": "RECORD_VENDOR_RESPONSE",
            "action_code": "RECORD_VENDOR_RESPONSE",
            "title": "Verify Payment Voucher / Record Response",
            "label": "Verify Payment Voucher / Record Response",
            "description": "Verify bank payment receipt or record supplier credit note adjustment.",
            "urgency": "NORMAL",
            "suggested_modal_or_tab": "RECORD_RESPONSE",
            "requires_role": None,
            "prerequisites": ["Bank payment voucher or supplier confirmation."],
        }

    if ex_type in ("MISSING_2B", "VALUE_MISMATCH", "GSTIN_MISMATCH"):
        if latest_response_cat in ("INVOICE_AMENDED", "DOCUMENT_PROVIDED"):
            if is_blocking and not is_admin:
                return {
                    "action_type": "SUBMIT_FOR_CA_REVIEW",
                    "action_code": "SUBMIT_FOR_CA_REVIEW",
                    "title": "Submit Vendor Evidence for CA Sign-off",
                    "label": "Submit Vendor Evidence for CA Sign-off",
                    "description": f"Vendor recorded '{latest_response_cat}'. Submit evidence to CA for review before requesting revalidation.",
                    "urgency": "HIGH",
                    "suggested_modal_or_tab": "RESOLVE",
                    "requires_role": "admin",
                    "prerequisites": ["Vendor response recorded with supporting documentation."],
                }
            return {
                "action_type": "DISPOSITION_OR_RESOLVE",
                "action_code": "REQUEST_REVALIDATION",
                "title": "Apply Resolution / Sign-off",
                "label": "Apply Resolution / Sign-off",
                "description": f"Vendor confirmed '{latest_response_cat}'. Review evidence and record structured resolution.",
                "urgency": "HIGH",
                "suggested_modal_or_tab": "RESOLVE",
                "requires_role": None,
                "prerequisites": ["Vendor response recorded with supporting documentation."],
            }
        if followup_count == 0:
            return {
                "action_type": "DISPATCH_VENDOR_FOLLOWUP",
                "action_code": "CONTACT_VENDOR",
                "title": "Dispatch Vendor Follow-up" if ex_type == "MISSING_2B" else "Dispatch Discrepancy Notice",
                "label": "Dispatch Vendor Follow-up" if ex_type == "MISSING_2B" else "Dispatch Discrepancy Notice",
                "description": f"Dispatch pre-formatted notice to supplier ({vendor_gstin or 'vendor'}) requesting GSTR-1 inclusion/amendment.",
                "urgency": "HIGH",
                "suggested_modal_or_tab": "COMMUNICATION",
                "requires_role": None,
                "prerequisites": ["Supplier GSTIN or contact information available."],
            }
        return {
            "action_type": "SCHEDULE_FOLLOWUP",
            "action_code": "SCHEDULE_FOLLOWUP",
            "title": "Schedule Vendor Follow-Up",
            "label": "Schedule Vendor Follow-Up",
            "description": "Set follow-up due date to check the vendor's upcoming GSTR-1 filing.",
            "urgency": "NORMAL",
            "suggested_modal_or_tab": "SCHEDULE_FOLLOWUP",
            "requires_role": None,
            "prerequisites": ["Pending vendor outward filing cycle."],
        }

    if ex_type == "2B_ONLY":
        return {
            "action_type": "RECORD_VENDOR_RESPONSE",
            "action_code": "RECORD_VENDOR_RESPONSE",
            "title": "Review Unbooked Invoice",
            "label": "Review Unbooked Invoice",
            "description": "Check with client procurement team whether purchase invoice should be booked into accounts.",
            "urgency": "NORMAL",
            "suggested_modal_or_tab": "RECORD_RESPONSE",
            "requires_role": None,
            "prerequisites": ["Internal review with client procurement team."],
        }

    if ex_type == "DUPLICATE":
        return {
            "action_type": "DISPOSITION_OR_RESOLVE",
            "action_code": "APPROVE_AND_RESOLVE",
            "title": "Reverse Duplicate Entry",
            "label": "Reverse Duplicate Entry",
            "description": "Identify redundant duplicate voucher in accounting software and resolve duplicate.",
            "urgency": "HIGH",
            "suggested_modal_or_tab": "RESOLVE",
            "requires_role": "admin" if is_blocking else None,
            "prerequisites": ["Confirmation of duplicate accounting entry."],
        }

    return {
        "action_type": "DISPOSITION_OR_RESOLVE" if is_admin else "RECORD_VENDOR_RESPONSE",
        "action_code": "RECORD_VENDOR_RESPONSE",
        "title": "Investigate Exception",
        "label": "Investigate Exception",
        "description": "Review source vouchers and record auditor investigation notes.",
        "urgency": "NORMAL",
        "suggested_modal_or_tab": "DETAILS",
        "requires_role": None,
        "prerequisites": [],
    }


def _formulate_revalidation_guidance(
    ex_type: str,
    reval_status: str,
    followup_count: int,
    latest_response_cat: Optional[str],
) -> dict[str, Any]:
    """Formulate revalidation readiness guidance.

    Does NOT authorize or bypass existing revalidation endpoint.
    """
    if ex_type == "SEC_17_5":
        return {
            "status": "NOT_READY",
            "summary": "Section 17(5) blocked credits cannot be revalidated into eligibility.",
            "prerequisites": [
                {"item": "Statutory eligibility allowed under CGST Act", "satisfied": False},
                {"item": "Supplier GSTR-1 filing update", "satisfied": False},
            ],
            "conditions": [
                "Section 17(5) blocked credits cannot be revalidated into eligibility by supplier filing.",
                "Apply statutory reversal under Table 4(B)(1) rather than requesting revalidation.",
            ],
        }

    if reval_status == "PENDING":
        return {
            "status": "NOT_READY",
            "summary": "Revalidation request is already pending reconciliation execution.",
            "prerequisites": [
                {"item": "Revalidation request registered", "satisfied": True},
                {"item": "Reconciliation cycle executed", "satisfied": False},
            ],
            "conditions": [
                "Revalidation request is already registered.",
                "Work item will be re-evaluated during the next reconciliation execution.",
            ],
        }

    if latest_response_cat in ("INVOICE_AMENDED", "DOCUMENT_PROVIDED"):
        return {
            "status": "READY",
            "summary": f"Vendor provided resolution confirmation ({latest_response_cat}); item is ready for revalidation.",
            "prerequisites": [
                {"item": "Vendor response recorded", "satisfied": True},
                {"item": "Supporting documentation logged", "satisfied": True},
                {"item": "Exception resolved or confirmed", "satisfied": True},
            ],
            "conditions": [
                f"Vendor response recorded as '{latest_response_cat}'.",
                "Operational evidence has been logged; revalidation can be requested through the existing workflow.",
            ],
        }

    if followup_count == 0:
        return {
            "status": "NOT_READY",
            "summary": "No vendor outreach or follow-up has been logged. Revalidating now would produce an identical exception.",
            "prerequisites": [
                {"item": "Vendor follow-up dispatched", "satisfied": False},
                {"item": "Vendor confirmation recorded", "satisfied": False},
            ],
            "conditions": [
                "No vendor outreach or follow-up has been logged.",
                "Revalidating now would produce an identical reconciliation exception.",
            ],
        }

    return {
        "status": "UNKNOWN",
        "summary": "Follow-up was dispatched, but conclusive supplier confirmation is pending.",
        "prerequisites": [
            {"item": "Vendor follow-up dispatched", "satisfied": True},
            {"item": "Supplier outward return updated", "satisfied": False},
        ],
        "conditions": [
            "Follow-up was dispatched, but conclusive supplier confirmation or amendment is pending.",
            "Record vendor confirmation or wait for next GSTR-1 return filing before requesting revalidation.",
        ],
    }

