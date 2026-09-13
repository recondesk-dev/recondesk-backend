"""GSTR-3B Table 4 Workpaper Orchestration Engine.

Orchestration, disposition, and statutory reporting layer on top of the
existing ReconDesk reconciliation outcomes engine.

Adheres strictly to:
- CBIC Circular No. 170/02/2022-GST (Gross 4A, Reversal 4B, Net 4C = 4A - 4B)
- CGST Act Section 16(2), Section 17(5), Rule 37, Rule 37A
- Integer paise arithmetic across all four tax heads (IGST, CGST, SGST, Cess)
- Single authoritative snapshot in public.gstr3b_table4_summaries
- Tamper-evident deterministic SHA-256 audit hashing
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from supabase import Client

import app.services.reconciliation_outcomes as ro
from app.services.reconciliation_outcomes import RULE37_CONCERNS, OutcomeRow

_log = logging.getLogger(__name__)

DISCLAIMER_TEXT = (
    "Figures compiled from finalized reconciliation decisions, recorded dispositions "
    "and verified adjustments. Prepared as a workpaper for CA/taxpayer review prior to portal submission."
)
WORKPAPER_TITLE = "Finalized GSTR-3B Table 4 Workpaper"


# ---------------------------------------------------------------------------
# Paise & Tax Head Helpers
# ---------------------------------------------------------------------------

def paise_to_rupees(paise: int | float) -> float:
    """Convert integer paise to rounded rupees (2 decimal places)."""
    return round(float(paise) / 100.0, 2)


def rupees_to_paise(rupees: float | int) -> int:
    """Convert rupees to integer paise."""
    return int(round(float(rupees or 0) * 100))


@dataclass
class TaxHeadsPaise:
    igst: int = 0
    cgst: int = 0
    sgst: int = 0
    cess: int = 0
    count: int = 0

    def add(self, igst: int, cgst: int, sgst: int, cess: int, count_delta: int = 1) -> None:
        self.igst += int(igst)
        self.cgst += int(cgst)
        self.sgst += int(sgst)
        self.cess += int(cess)
        self.count += count_delta

    def to_dict(self) -> dict[str, Any]:
        tot_paise = self.igst + self.cgst + self.sgst + self.cess
        return {
            "igst": paise_to_rupees(self.igst),
            "cgst": paise_to_rupees(self.cgst),
            "sgst": paise_to_rupees(self.sgst),
            "cess": paise_to_rupees(self.cess),
            "total_tax": paise_to_rupees(tot_paise),
            "count": self.count,
            "igst_paise": self.igst,
            "cgst_paise": self.cgst,
            "sgst_paise": self.sgst,
            "cess_paise": self.cess,
            "total_tax_paise": tot_paise,
        }


def extract_tax_heads_paise(rd: dict[str, Any]) -> tuple[int, int, int, int]:
    """Sum line item paise else invoice-level paise on the record dictionary."""
    items = rd.get("items")
    if isinstance(items, list) and items:
        igst = cgst = sgst = cess = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            igst += int(item.get("igst_paise") or 0)
            cgst += int(item.get("cgst_paise") or 0)
            sgst += int(item.get("sgst_paise") or 0)
            cess += int(item.get("cess_paise") or 0)
        return igst, cgst, sgst, cess

    # Fallback to record-level keys (supporting both paise and float fallbacks)
    igst = int(rd.get("igst_paise") or 0)
    cgst = int(rd.get("cgst_paise") or 0)
    sgst = int(rd.get("sgst_paise") or 0)
    cess = int(rd.get("cess_paise") or 0)

    if igst == 0 and cgst == 0 and sgst == 0 and cess == 0:
        if rd.get("igst") is not None:
            igst = rupees_to_paise(rd.get("igst") or 0)
        if rd.get("cgst") is not None:
            cgst = rupees_to_paise(rd.get("cgst") or 0)
        if rd.get("sgst") is not None:
            sgst = rupees_to_paise(rd.get("sgst") or 0)
        if rd.get("cess") is not None:
            cess = rupees_to_paise(rd.get("cess") or 0)

    return igst, cgst, sgst, cess


def is_credit_note(rd: dict[str, Any], outcome: Optional[OutcomeRow] = None) -> bool:
    """Check whether a transaction is a Credit Note (which reduces eligible ITC)."""
    if outcome and getattr(outcome, "is_credit_note", False):
        return True
    doc_type = str(rd.get("doc_type") or rd.get("document_type") or rd.get("inv_typ") or "").strip().upper()
    return doc_type in ("CREDIT_NOTE", "CR", "CDNR", "CDNRA", "C")


def is_section_16_4_or_pos_restricted(
    r: OutcomeRow,
    g_rd: dict[str, Any],
    p_rd: dict[str, Any],
    disposition: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Check if an invoice is ineligible under Section 16(4) or PoS restrictions.

    Circular 170/02/2022 Para 4.3 rule:
    Such details are for information only and must be reported in Table 4(D)(2).
    They must NEVER enter Table 4(A) or Table 4(B).
    """
    # 1. Check CA explicit disposition
    if disposition:
        disp_type = str(disposition.get("exception_type") or "").upper()
        disp_val = str(disposition.get("disposition") or "").upper()
        table4_eff = str(disposition.get("table4_effect") or "").upper()
        if table4_eff == "4D2" or disp_val in (
            "CONFIRMED_TIME_BARRED",
            "CONFIRMED_POS_RESTRICTED",
            "INELIGIBLE_16_4",
            "INELIGIBLE_POS",
        ):
            return True, disp_val
        if disp_type in ("TIME_BARRED_16_4", "POS_RESTRICTED", "SECTION_16_4", "POS_MISMATCH"):
            return True, disp_type

    # 2. Check GSTR-2B raw data flags (itcavl == 'N' and reason text)
    itcavl = str(g_rd.get("itcavl") or "").strip().upper()
    rsn = str(g_rd.get("rsn") or "").strip().lower()
    if itcavl == "N":
        if any(k in rsn for k in ("16(4)", "16 (4)", "time barred", "time-barred", "limitation")):
            return True, "TIME_BARRED_16_4"
        if any(k in rsn for k in ("pos", "place of supply", "different state")):
            return True, "POS_RESTRICTED"

    # 3. Check outcome row attributes
    if getattr(r, "itc_available", True) is False and r.itc_reason:
        r_rsn = r.itc_reason.lower()
        if any(k in r_rsn for k in ("16(4)", "16 (4)", "time barred", "time-barred")):
            return True, "TIME_BARRED_16_4"
        if any(k in r_rsn for k in ("pos", "place of supply")):
            return True, "POS_RESTRICTED"

    return False, ""


def load_reclaim_events_for_run(sb: Client, run_id: str) -> list[dict[str, Any]]:
    """Load active reclaim events executed in this reconciliation run."""
    try:
        res = (
            sb.table("gstr3b_reclaim_events")
            .select("*")
            .eq("reclaim_run_id", run_id)
            .execute()
        )
        return res.data or []
    except Exception:
        _log.warning("load_reclaim_events_for_run failed for run_id=%s", run_id, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Database Ingestion & Dispositions
# ---------------------------------------------------------------------------

def load_exception_dispositions(sb: Client, run_id: str) -> dict[str, dict[str, Any]]:
    """Load all recorded CA exception dispositions for run_id.

    Keyed by f"{record_id}:{exception_type}".
    """
    try:
        res = (
            sb.table("reconciliation_exception_dispositions")
            .select("*")
            .eq("run_id", run_id)
            .execute()
        )
        out: dict[str, dict[str, Any]] = {}
        for r in res.data or []:
            if isinstance(r, dict):
                rec_id = str(r.get("record_id") or "")
                ex_type = str(r.get("exception_type") or "")
                out[f"{rec_id}:{ex_type}"] = r
                out[rec_id] = r  # allow direct lookup by record_id as well
        return out
    except Exception:
        _log.warning("load_exception_dispositions failed for run_id=%s", run_id, exc_info=True)
        return {}


def load_table4_adjustments(sb: Client, run_id: str) -> list[dict[str, Any]]:
    """Load active (non-deleted) external adjustments for run_id."""
    try:
        res = (
            sb.table("gstr3b_table4_adjustments")
            .select("*")
            .eq("run_id", run_id)
            .eq("is_deleted", False)
            .execute()
        )
        return res.data or []
    except Exception:
        _log.warning("load_table4_adjustments failed for run_id=%s", run_id, exc_info=True)
        return []


def load_rule37_settlements(sb: Client, run_id: str) -> set[str]:
    """Load settled record identifiers from rule37_actions and rule37_resolutions."""
    settled: set[str] = set()
    try:
        r1 = sb.table("rule37_actions").select("record_hash, status").eq("run_id", run_id).execute()
        for row in r1.data or []:
            st = str(row.get("status") or "").upper()
            if st in ("SETTLED", "REVERSED", "PAID_ELIGIBLE", "EXCLUDED"):
                settled.add(str(row.get("record_hash") or ""))
    except Exception:
        pass

    try:
        r2 = sb.table("rule37_resolutions").select("invoice_result_id").eq("run_id", run_id).execute()
        for row in r2.data or []:
            if row.get("invoice_result_id"):
                settled.add(str(row.get("invoice_result_id")))
    except Exception:
        pass

    return settled


# ---------------------------------------------------------------------------
# Qualified Finalization Gate
# ---------------------------------------------------------------------------

def check_finalization_blocking_exceptions(
    sb: Client,
    run_id: str,
    *,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Validate whether every ITC-affecting exception has an explicit disposition.

    Returns:
    {
      "can_finalize": bool,
      "unresolved_blocking_exceptions": int,
      "blocking_summary": list[str],
      "blocking_records": list[dict[str, Any]]
    }
    """
    p = payload or ro.load_payload(sb, run_id) or {}
    all_outcomes = ro.build_outcome_rows(sb, run_id, p)[0]
    dispositions = load_exception_dispositions(sb, run_id)
    r37_settled = load_rule37_settlements(sb, run_id)

    blocking_records: list[dict[str, Any]] = []
    blocking_summary: list[str] = []

    for r in all_outcomes:
        rec_id = r.id

        # 1. Section 17(5) Blocked Credit Signal
        is_sec175_signal = (
            r.category == "blocked_credit"
            or bool(r.blocked_credit_flag)
            or (r.itc_reason and any(k in r.itc_reason.lower() for k in ("17(5)", "17 (5)", "blocked", "sec 17")))
        )
        if is_sec175_signal:
            disp = dispositions.get(f"{rec_id}:SEC_17_5") or dispositions.get(rec_id)
            if not disp or str(disp.get("disposition", "")).upper() not in (
                "CONFIRMED_BLOCKED",
                "STATUTORY_EXCEPTION",
                "ELIGIBLE",
                "INELIGIBLE",
            ):
                blocking_records.append({
                    "record_id": rec_id,
                    "exception_type": "SEC_17_5",
                    "supplier_name": r.supplier_name,
                    "supplier_gstin": r.supplier_gstin,
                    "invoice_number": r.invoice_number,
                    "amount": paise_to_rupees(r.amount or 0),
                    "reason": "Section 17(5) signal requires CA confirmation (CONFIRMED_BLOCKED or STATUTORY_EXCEPTION).",
                })

        # 2. Rule 37 180-day Concern
        is_r37_concern = (
            r.category == "rule37_warnings"
            or bool(r.rule37_flag)
            or (str(r.match_status).upper() in RULE37_CONCERNS)
        ) and not (r.match_status == "RULE37A" or r.rule37a_flag)

        if is_r37_concern:
            disp = dispositions.get(f"{rec_id}:RULE_37") or dispositions.get(rec_id)
            disp_code = str(disp.get("disposition", "")).upper() if disp else ""
            is_disp_settled = disp_code in ("REVERSED", "PAID_ELIGIBLE", "SETTLED", "DISPUTED")
            is_legacy_settled = rec_id in r37_settled or (r.matched_pr_id and r.matched_pr_id in r37_settled)

            if not (is_disp_settled or is_legacy_settled):
                blocking_records.append({
                    "record_id": rec_id,
                    "exception_type": "RULE_37",
                    "supplier_name": r.supplier_name,
                    "supplier_gstin": r.supplier_gstin,
                    "invoice_number": r.invoice_number,
                    "amount": paise_to_rupees(r.amount or 0),
                    "reason": "Unpaid > 180 days (Rule 37) requires disposition (REVERSED or PAID_ELIGIBLE).",
                })

        # Note: PR-only records do not block finalization; they remain in Missed ITC and are excluded from current 4A.
        # Note: Non-ITC warnings (scorecards, trade-name differences, current FY Rule 37A warnings before Nov 30) do not block.

    # Group blocking summary for UI presentation
    sec175_count = sum(1 for b in blocking_records if b["exception_type"] == "SEC_17_5")
    r37_count = sum(1 for b in blocking_records if b["exception_type"] == "RULE_37")

    if sec175_count > 0:
        blocking_summary.append(f"{sec175_count} Section 17(5) invoice(s) require confirmation")
    if r37_count > 0:
        blocking_summary.append(f"{r37_count} Rule 37 invoice(s) require payment/reversal resolution")

    can_finalize = len(blocking_records) == 0

    return {
        "can_finalize": can_finalize,
        "unresolved_blocking_exceptions": len(blocking_records),
        "blocking_summary": blocking_summary,
        "blocking_records": blocking_records,
    }


# ---------------------------------------------------------------------------
# Core Table 4 Compilation Logic
# ---------------------------------------------------------------------------

def compile_gstr3b_table4(
    sb: Client,
    run_id: str,
    *,
    payload: Optional[dict[str, Any]] = None,
    is_finalized: bool = False,
) -> dict[str, Any]:
    """Pure aggregation and orchestration layer to compile GSTR-3B Table 4 Workpaper.

    Does NOT re-match invoices. Reuses existing outcomes from reconciliation_outcomes.py,
    recorded exception dispositions, and verified external adjustments.
    """
    # 1. Fetch Run Metadata
    run_row = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status, is_locked, finalized_at, finalized_by, client_gstins(gstin, trade_name, legal_name)")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not run_row.data:
        raise ValueError(f"Reconciliation run not found: {run_id}")
    r0 = run_row.data[0]
    client_gstin_id = str(r0.get("client_gstin_id") or "")
    tax_period = str(r0.get("period") or "")
    cg_data = r0.get("client_gstins") or {}
    client_gstin = str(cg_data.get("gstin") or "")

    # If finalized and snapshot exists in gstr3b_table4_summaries, load authoritative copy
    if is_finalized or str(r0.get("status", "")).upper() == "FINAL":
        existing_summary = (
            sb.table("gstr3b_table4_summaries")
            .select("*")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
        )
        if existing_summary.data and existing_summary.data[0].get("status") == "FINALIZED":
            snap = existing_summary.data[0]
            return _format_table4_response(
                snap=snap,
                run_id=run_id,
                client_gstin=client_gstin,
                tax_period=tax_period,
                is_locked=True,
                status="FINALIZED",
                finalized_at=snap.get("finalized_at") or r0.get("finalized_at"),
                finalized_by=snap.get("finalized_by") or r0.get("finalized_by"),
                can_finalize=True,
                unresolved_blocking=0,
                blocking_summary=[],
                blocking_records=[],
            )

    # 2. Load Existing Reconciliation Outcomes & Underlying Maps
    p = payload or ro.load_payload(sb, run_id) or {}
    all_outcomes = ro.build_outcome_rows(sb, run_id, p)[0]
    gstr_db = ro.load_gstr_map(sb, run_id)
    pr_db = ro.load_pr_map(sb, run_id)
    dispositions = load_exception_dispositions(sb, run_id)
    adjustments = load_table4_adjustments(sb, run_id)

    # 3. Initialize Accumulators in Integer Paise
    t4a1 = TaxHeadsPaise()  # Import of Goods
    t4a2 = TaxHeadsPaise()  # Import of Services
    t4a3 = TaxHeadsPaise()  # Domestic Inward RCM
    t4a4 = TaxHeadsPaise()  # ISD
    t4a5 = TaxHeadsPaise()  # All Other ITC (Domestic B2B gross)

    t4b1 = TaxHeadsPaise()  # Rules 38, 42, 43 and Section 17(5)
    t4b2 = TaxHeadsPaise()  # Others (Rule 37, Rule 37A reversals)

    t4d1 = TaxHeadsPaise()  # Reclaimed ITC
    t4d2 = TaxHeadsPaise()  # Ineligible under Sec 16(4) / POS restrictions

    contributing_record_ids: list[str] = []

    # 4. Process Outcomes & Dispositions
    for r in all_outcomes:
        rec_id = r.id
        # Duplicate entries (extra PR bookings) must never enter Table 4
        if rec_id.startswith("de:") or r.category == "duplicate_entry":
            continue

        pid = r.matched_pr_id or ""
        gid = rec_id.removeprefix("pm:").removeprefix("gstr:") if (rec_id.startswith("pm:") or rec_id.startswith("gstr:")) else ""

        # Extract record data
        g_entry = gstr_db.get(gid) or {}
        g_rd = g_entry.get("record_data") if isinstance(g_entry.get("record_data"), dict) else {}
        p_entry = pr_db.get(pid) or {}
        p_rd = p_entry.get("record_data") if isinstance(p_entry.get("record_data"), dict) else {}

        # Resolve tax heads in paise
        igst_p, cgst_p, sgst_p, cess_p = 0, 0, 0, 0
        if g_rd:
            igst_p, cgst_p, sgst_p, cess_p = extract_tax_heads_paise(g_rd)
        elif p_rd:
            igst_p, cgst_p, sgst_p, cess_p = extract_tax_heads_paise(p_rd)
        elif r.amount:
            # Fallback if neither full record has line items
            amt_p = int(r.amount)
            # Default to IGST if heads not broken down
            igst_p = amt_p

        # Determine Sign: Credit Notes reduce eligible ITC (Circular 170)
        cn = is_credit_note(g_rd or p_rd, r)
        sign = -1 if cn else 1
        sig_igst = sign * igst_p
        sig_cgst = sign * cgst_p
        sig_sgst = sign * sgst_p
        sig_cess = sign * cess_p

        # Document/Transaction Type classification
        g_doctype = str(g_rd.get("doc_type") or g_rd.get("document_type") or "").strip().upper()
        p_doctype = str(p_rd.get("doc_type") or p_rd.get("document_type") or "").strip().upper()
        is_rcm = str(g_rd.get("reverse_charge") or p_rd.get("reverse_charge") or "").strip().upper() in ("Y", "YES", "TRUE")

        # Check Dispositions
        disp_175 = dispositions.get(f"{rec_id}:SEC_17_5") or dispositions.get(rec_id)
        disp_r37 = dispositions.get(f"{rec_id}:RULE_37") or dispositions.get(rec_id)
        disp_r37a = dispositions.get(f"{rec_id}:RULE_37A") or dispositions.get(rec_id)
        disp_2b = dispositions.get(f"{rec_id}:TWO_B_ONLY") or dispositions.get(rec_id)
        disp_162b = (
            dispositions.get(f"{rec_id}:SECTION_16_2_B")
            or dispositions.get(f"{rec_id}:GOODS_NOT_RECEIVED")
            or dispositions.get(rec_id)
        )
        disp_4d2 = (
            dispositions.get(f"{rec_id}:TIME_BARRED_16_4")
            or dispositions.get(f"{rec_id}:POS_RESTRICTED")
            or dispositions.get(f"{rec_id}:SECTION_16_4")
            or dispositions.get(f"{rec_id}:POS_MISMATCH")
            or dispositions.get(rec_id)
        )

        # -------------------------------------------------------------
        # Row Allocation Logic
        # -------------------------------------------------------------

        # CASE 0: Section 16(4) Time-Barred & Place of Supply (PoS) Restricted -> 4D2 ONLY
        # Circular 170/02/2022 Para 4.3 rule:
        # Such details are for information only and must be reported in Table 4(D)(2).
        # They must NEVER enter Table 4(A) or Table 4(B)!
        is_4d2_restricted, reason_4d2 = is_section_16_4_or_pos_restricted(r, g_rd, p_rd, disp_4d2)
        if is_4d2_restricted:
            t4d2.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
            contributing_record_ids.append(rec_id)
            continue

        # CASE 1: Import of Goods -> 4A1
        if g_doctype in ("IMPG", "IMPGSEZ") or p_doctype in ("IMPG", "IMPGSEZ", "IMPORT_GOODS"):
            t4a1.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
            contributing_record_ids.append(rec_id)
            continue

        # CASE 2: Input Service Distributor (ISD) -> 4A4
        if g_doctype == "ISD" or p_doctype == "ISD":
            t4a4.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
            contributing_record_ids.append(rec_id)
            continue

        # CASE 3: Domestic Inward RCM -> 4A3
        if is_rcm and (p_rd or r.category == "matched"):
            t4a3.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
            contributing_record_ids.append(rec_id)
            continue

        # CASE 4: PR-Only (Missed ITC) -> Not included in current 4A (Section 16(2)(aa))
        if rec_id.startswith("pr:") or r.category == "missed_itc":
            # Retained in Missed ITC; does not enter Table 4
            continue

        # CASE 5: 2B-Only (Unbooked / Unverified)
        if rec_id.startswith("gstr:") or (not pid and not rec_id.startswith("pm:")):
            # Only enters 4A5 if explicitly BOOKED_AND_VERIFIED by CA
            if disp_2b and str(disp_2b.get("disposition", "")).upper() == "BOOKED_AND_VERIFIED":
                t4a5.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
                contributing_record_ids.append(rec_id)
            elif disp_2b and str(disp_2b.get("disposition", "")).upper() == "SECTION_16_2_B_REVERSED":
                # Explicit CA statutory disposition: gross in 4A5, temporary reversal in 4B2
                t4a5.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
                t4b2.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
                contributing_record_ids.append(rec_id)
            # Other dispositions (HELD_GOODS_NOT_RECEIVED, REJECTED_WRONG_GSTIN, etc.) are excluded from Table 4
            continue

        # CASE 6: Matched Domestic Invoices (Standard B2B, B2BA, CDNR, CDNRA)
        # Circular 170 Rule: Gross eligible credit enters Table 4A5
        is_sec175 = (
            r.category == "blocked_credit"
            or bool(r.blocked_credit_flag)
            or (r.itc_reason and any(k in r.itc_reason.lower() for k in ("17(5)", "17 (5)", "blocked", "sec 17")))
        )
        is_disp_175_blocked = bool(
            disp_175
            and (
                str(disp_175.get("table4_effect", "")).upper() == "4B1"
                or str(disp_175.get("disposition", "")).upper() in ("CONFIRMED_BLOCKED", "INELIGIBLE")
            )
            and str(disp_175.get("disposition", "")).upper() != "STATUTORY_EXCEPTION"
        )
        is_sec175_confirmed = is_disp_175_blocked or (
            is_sec175 and (not disp_175 or str(disp_175.get("disposition", "")).upper() != "STATUTORY_EXCEPTION")
        )

        is_r37 = (
            r.category == "rule37_warnings"
            or bool(r.rule37_flag)
            or (str(r.match_status).upper() in RULE37_CONCERNS)
        ) and not (r.match_status == "RULE37A" or r.rule37a_flag)

        is_disp_r37_reversed = bool(
            disp_r37
            and str(disp_r37.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED")
            and (
                str(disp_r37.get("table4_effect", "")).upper() == "4B2"
                or str(disp_r37.get("exception_type", "")).upper() == "RULE_37"
            )
        )
        is_r37_reversed = is_disp_r37_reversed or (
            is_r37 and bool(disp_r37 and str(disp_r37.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED"))
        )

        is_r37a = (r.match_status == "RULE37A" or r.rule37a_flag)
        is_r37a_reversed = is_r37a and (
            disp_r37a and str(disp_r37a.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED", "RULE_37A_VERIFIED", "CONFIRMED_NON_FILER")
        )

        is_162b_reversed = bool(
            disp_162b
            and str(disp_162b.get("disposition", "")).upper() in (
                "REVERSED", "SECTION_16_2_B_REVERSED", "CONFIRMED_NOT_RECEIVED"
            )
        )

        # Gross amount ALWAYS goes to 4A5 (No deduction from 4A!)
        t4a5.add(sig_igst, sig_cgst, sig_sgst, sig_cess)
        contributing_record_ids.append(rec_id)

        # Reversals are SEPARATELY added to 4B
        if is_sec175_confirmed:
            t4b1.add(sig_igst, sig_cgst, sig_sgst, sig_cess)

        if is_r37_reversed or is_r37a_reversed or is_162b_reversed:
            t4b2.add(sig_igst, sig_cgst, sig_sgst, sig_cess)

    # 5. Process Active Reclaim Events (Circular 170 Para 4.3: Added to 4A5 AND 4D1)
    reclaim_events = load_reclaim_events_for_run(sb, run_id)
    contributing_reclaim_ids: list[str] = []
    reclaim_hashes: list[str] = []
    for ev in reclaim_events:
        ev_type = str(ev.get("event_type") or "RECLAIM").upper()
        mult = 1 if ev_type == "RECLAIM" else -1
        r_igst = mult * int(ev.get("reclaimed_igst_paise") or 0)
        r_cgst = mult * int(ev.get("reclaimed_cgst_paise") or 0)
        r_sgst = mult * int(ev.get("reclaimed_sgst_paise") or 0)
        r_cess = mult * int(ev.get("reclaimed_cess_paise") or 0)

        t4a5.add(r_igst, r_cgst, r_sgst, r_cess)
        t4d1.add(r_igst, r_cgst, r_sgst, r_cess)
        ev_id = str(ev.get("id"))
        contributing_reclaim_ids.append(ev_id)
        reclaim_hashes.append(f"{ev_id}:{r_igst}:{r_cgst}:{r_sgst}:{r_cess}")

    # 6. Process External Adjustments (Rules 42/43/38, RCM, Manual Reversals)
    adjustment_hashes: list[str] = []
    for adj in adjustments:
        row_id = str(adj.get("row_id") or "").upper()
        adj_type = str(adj.get("adjustment_type") or "ADDITION").upper()
        multiplier = 1 if adj_type == "ADDITION" else -1

        a_igst = multiplier * int(adj.get("igst_paise") or 0)
        a_cgst = multiplier * int(adj.get("cgst_paise") or 0)
        a_sgst = multiplier * int(adj.get("sgst_paise") or 0)
        a_cess = multiplier * int(adj.get("cess_paise") or 0)

        adj_key = f"{adj.get('id')}:{row_id}:{a_igst}:{a_cgst}:{a_sgst}:{a_cess}"
        adjustment_hashes.append(adj_key)

        if row_id == "4A1":
            t4a1.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4A2":
            t4a2.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4A3":
            t4a3.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4A4":
            t4a4.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4A5":
            t4a5.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4B1":
            t4b1.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4B2":
            t4b2.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4D1":
            t4d1.add(a_igst, a_cgst, a_sgst, a_cess)
        elif row_id == "4D2":
            t4d2.add(a_igst, a_cgst, a_sgst, a_cess)

    # 6. Compute Totals & Net 4C (4C = 4A - 4B)
    t4a_total = TaxHeadsPaise(
        igst=t4a1.igst + t4a2.igst + t4a3.igst + t4a4.igst + t4a5.igst,
        cgst=t4a1.cgst + t4a2.cgst + t4a3.cgst + t4a4.cgst + t4a5.cgst,
        sgst=t4a1.sgst + t4a2.sgst + t4a3.sgst + t4a4.sgst + t4a5.sgst,
        cess=t4a1.cess + t4a2.cess + t4a3.cess + t4a4.cess + t4a5.cess,
        count=t4a1.count + t4a2.count + t4a3.count + t4a4.count + t4a5.count,
    )

    t4b_total = TaxHeadsPaise(
        igst=t4b1.igst + t4b2.igst,
        cgst=t4b1.cgst + t4b2.cgst,
        sgst=t4b1.sgst + t4b2.sgst,
        cess=t4b1.cess + t4b2.cess,
        count=t4b1.count + t4b2.count,
    )

    # 4C Net ITC Available: Strictly 4A - 4B
    t4c_igst = t4a_total.igst - t4b_total.igst
    t4c_cgst = t4a_total.cgst - t4b_total.cgst
    t4c_sgst = t4a_total.sgst - t4b_total.sgst
    t4c_cess = t4a_total.cess - t4b_total.cess
    t4c_total_tax = t4c_igst + t4c_cgst + t4c_sgst + t4c_cess

    t4c_dict = {
        "igst": paise_to_rupees(t4c_igst),
        "cgst": paise_to_rupees(t4c_cgst),
        "sgst": paise_to_rupees(t4c_sgst),
        "cess": paise_to_rupees(t4c_cess),
        "total_tax": paise_to_rupees(t4c_total_tax),
        "igst_paise": t4c_igst,
        "cgst_paise": t4c_cgst,
        "sgst_paise": t4c_sgst,
        "cess_paise": t4c_cess,
        "total_tax_paise": t4c_total_tax,
    }

    # 7. Generate Tamper-Evident Deterministic SHA-256 Audit Hash
    sorted_recs = sorted(contributing_record_ids)
    sorted_adjs = sorted(adjustment_hashes)
    canonical_payload = (
        f"{run_id}|{client_gstin_id}|{tax_period}|"
        f"{','.join(sorted_recs)}|{','.join(sorted_adjs)}|"
        f"{t4c_igst}:{t4c_cgst}:{t4c_sgst}:{t4c_cess}"
    )
    audit_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    # 8. Evaluate Finalization Gate
    gate = check_finalization_blocking_exceptions(sb, run_id, payload=p)

    compiled_snapshot = {
        "table_4a1": t4a1.to_dict(),
        "table_4a2": t4a2.to_dict(),
        "table_4a3": t4a3.to_dict(),
        "table_4a4": t4a4.to_dict(),
        "table_4a5": t4a5.to_dict(),
        "table_4a_total": t4a_total.to_dict(),
        "table_4b1": t4b1.to_dict(),
        "table_4b2": t4b2.to_dict(),
        "table_4b_total": t4b_total.to_dict(),
        "table_4c": t4c_dict,
        "table_4d1": t4d1.to_dict(),
        "table_4d2": t4d2.to_dict(),
        "audit_hash": audit_hash,
        "source_state_digest": audit_hash,
        "contributing_outcome_ids": contributing_record_ids,
        "contributing_disposition_ids": list(dispositions.keys()),
        "contributing_adjustment_ids": [str(a.get("id")) for a in adjustments if a.get("id")],
        "contributing_reclaim_ids": contributing_reclaim_ids,
    }

    return _format_table4_response(
        snap=compiled_snapshot,
        run_id=run_id,
        client_gstin=client_gstin,
        tax_period=tax_period,
        is_locked=bool(r0.get("is_locked")),
        status="FINALIZED" if is_finalized else "PROVISIONAL",
        finalized_at=r0.get("finalized_at"),
        finalized_by=r0.get("finalized_by"),
        can_finalize=gate["can_finalize"],
        unresolved_blocking=gate["unresolved_blocking_exceptions"],
        blocking_summary=gate["blocking_summary"],
        blocking_records=gate.get("blocking_records", []),
    )


def _format_table4_response(
    snap: dict[str, Any],
    run_id: str,
    client_gstin: str,
    tax_period: str,
    is_locked: bool,
    status: str,
    finalized_at: Optional[str],
    finalized_by: Optional[str],
    can_finalize: bool,
    unresolved_blocking: int,
    blocking_summary: list[str],
    *,
    version: int = 1,
    blocking_records: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "client_gstin": client_gstin,
        "tax_period": tax_period,
        "status": status,
        "is_locked": is_locked,
        "finalized_at": finalized_at,
        "finalized_by": finalized_by,
        "version": snap.get("version") or version,
        "audit_hash": snap.get("audit_hash") or "",
        "source_state_digest": snap.get("source_state_digest") or snap.get("audit_hash") or "",
        "workpaper_title": WORKPAPER_TITLE,
        "disclaimer": DISCLAIMER_TEXT,
        "table_4": {
            "section_4a": {
                "row_4a1_import_goods": snap.get("table_4a1"),
                "row_4a2_import_services": snap.get("table_4a2"),
                "row_4a3_inward_rcm": snap.get("table_4a3"),
                "row_4a4_isd": snap.get("table_4a4"),
                "row_4a5_all_other_itc": snap.get("table_4a5"),
                "total_4a": snap.get("table_4a_total"),
            },
            "section_4b": {
                "row_4b1_rule38_42_43_sec175": snap.get("table_4b1"),
                "row_4b2_others_rule37_37a": snap.get("table_4b2"),
                "total_4b": snap.get("table_4b_total"),
            },
            "section_4c_net_itc": snap.get("table_4c"),
            "section_4d": {
                "row_4d1_reclaimed": snap.get("table_4d1"),
                "row_4d2_ineligible_16_4_pos": snap.get("table_4d2"),
            },
        },
        "gate_audit": {
            "can_finalize": can_finalize,
            "unresolved_blocking_exceptions": unresolved_blocking,
            "blocking_summary": blocking_summary,
            "blocking_records": blocking_records if blocking_records is not None else [],
        },
        "contributing_outcome_ids": snap.get("contributing_outcome_ids") or [],
        "contributing_disposition_ids": snap.get("contributing_disposition_ids") or [],
        "contributing_adjustment_ids": snap.get("contributing_adjustment_ids") or [],
        "contributing_reclaim_ids": snap.get("contributing_reclaim_ids") or [],
    }


# ---------------------------------------------------------------------------
# Finalization Execution
# ---------------------------------------------------------------------------

def compile_and_save_final_table4_snapshot(
    sb: Client,
    run_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Execute finalization for Table 4: validate gate, compile, and persist authoritative snapshot.

    Persists versioned immutable snapshot into public.gstr3b_table4_summaries, superseding
    any prior version for this run, while sealing source state digest and payload.
    Raises ValueError if blocking exceptions exist.
    """
    gate = check_finalization_blocking_exceptions(sb, run_id)
    if not gate["can_finalize"]:
        msg = f"Cannot finalize: {gate['unresolved_blocking_exceptions']} exception(s) require disposition."
        if gate["blocking_summary"]:
            msg += f" ({'; '.join(gate['blocking_summary'])})"
        raise ValueError(msg)

    # Compile authoritative result
    res = compile_gstr3b_table4(sb, run_id, is_finalized=False)
    t4 = res["table_4"]
    sec4a = t4["section_4a"]
    sec4b = t4["section_4b"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Get client_gstin_id and period
    r_info = sb.table("reconciliation_run").select("client_gstin_id, period").eq("id", run_id).limit(1).execute()
    client_gstin_id = r_info.data[0].get("client_gstin_id") if r_info.data else None
    period = r_info.data[0].get("period") if r_info.data else res["tax_period"]

    # Determine next snapshot version and supersede previous active snapshots
    existing_summaries = (
        sb.table("gstr3b_table4_summaries")
        .select("id, version, is_current")
        .eq("run_id", run_id)
        .order("version", desc=True)
        .execute()
    )
    max_version = 0
    if existing_summaries.data:
        max_version = max(int(row.get("version") or 0) for row in existing_summaries.data)
        for row in existing_summaries.data:
            if row.get("is_current"):
                sb.table("gstr3b_table4_summaries").update({
                    "is_current": False,
                    "superseded_at": now_iso,
                    "superseded_by": user_id,
                }).eq("id", row["id"]).execute()

    new_version = max_version + 1

    contributing_outcomes = res.get("contributing_outcome_ids") or []
    contributing_disps = res.get("contributing_disposition_ids") or []
    contributing_adjs = res.get("contributing_adjustment_ids") or []
    contributing_reclaims = res.get("contributing_reclaim_ids") or []

    record = {
        "run_id": run_id,
        "client_gstin_id": client_gstin_id,
        "tax_period": period,
        "version": new_version,
        "is_current": True,
        "status": "FINALIZED",
        "table_4a1": sec4a["row_4a1_import_goods"],
        "table_4a2": sec4a["row_4a2_import_services"],
        "table_4a3": sec4a["row_4a3_inward_rcm"],
        "table_4a4": sec4a["row_4a4_isd"],
        "table_4a5": sec4a["row_4a5_all_other_itc"],
        "table_4a_total": sec4a["total_4a"],
        "table_4b1": sec4b["row_4b1_rule38_42_43_sec175"],
        "table_4b2": sec4b["row_4b2_others_rule37_37a"],
        "table_4b_total": sec4b["total_4b"],
        "table_4c": t4["section_4c_net_itc"],
        "table_4d1": t4["section_4d"]["row_4d1_reclaimed"],
        "table_4d2": t4["section_4d"]["row_4d2_ineligible_16_4_pos"],
        "audit_hash": res["audit_hash"],
        "source_state_digest": res["audit_hash"],
        "snapshot_payload": res,
        "contributing_outcome_ids": contributing_outcomes,
        "contributing_disposition_ids": contributing_disps,
        "contributing_adjustment_ids": contributing_adjs,
        "contributing_reclaim_ids": contributing_reclaims,
        "finalized_at": now_iso,
        "finalized_by": user_id,
        "updated_at": now_iso,
    }

    insert_res = sb.table("gstr3b_table4_summaries").insert(record).execute()
    summary_id = insert_res.data[0].get("id") if insert_res.data else None

    # Link summary_id onto reconciliation_run
    if summary_id:
        sb.table("reconciliation_run").update({
            "table4_summary_id": summary_id,
        }).eq("id", run_id).execute()

    # Auto-register 4(B)(2) temporary reversals into the General Reversal & Reclaim Ledger
    try:
        from app.services.gstr3b_reversal_ledger import register_table4_reversals_to_ledger
        register_table4_reversals_to_ledger(sb, run_id, user_id)
    except Exception as e:
        _log.warning("Could not auto-register 4B2 reversals to ledger for run %s: %s", run_id, e)

    res["status"] = "FINALIZED"
    res["is_locked"] = True
    res["finalized_at"] = now_iso
    res["finalized_by"] = user_id
    res["version"] = new_version
    return res


# ---------------------------------------------------------------------------
# Drilldown Generator
# ---------------------------------------------------------------------------

def get_table4_drilldown(
    sb: Client,
    run_id: str,
    row_id: str,
    *,
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
) -> dict[str, Any]:
    """Provide paginated, verifiable invoice-level evidence for any Table 4 cell."""
    row_id_clean = row_id.upper().strip()
    p = ro.load_payload(sb, run_id) or {}
    all_outcomes = ro.build_outcome_rows(sb, run_id, p)[0]
    gstr_db = ro.load_gstr_map(sb, run_id)
    pr_db = ro.load_pr_map(sb, run_id)
    dispositions = load_exception_dispositions(sb, run_id)
    adjustments = load_table4_adjustments(sb, run_id)

    matching_items: list[dict[str, Any]] = []

    # First, collect any manual adjustments matching this row_id
    for adj in adjustments:
        if str(adj.get("row_id") or "").upper() == row_id_clean:
            matching_items.append({
                "id": str(adj.get("id")),
                "type": "ADJUSTMENT",
                "supplier_gstin": "EXTERNAL ADJUSTMENT",
                "supplier_name": str(adj.get("statutory_category") or "Manual Adjustment"),
                "invoice_number": str(adj.get("reference_doc") or "JV"),
                "invoice_date": str(adj.get("created_at") or "")[:10],
                "taxable_value": 0.0,
                "igst": paise_to_rupees(adj.get("igst_paise") or 0),
                "cgst": paise_to_rupees(adj.get("cgst_paise") or 0),
                "sgst": paise_to_rupees(adj.get("sgst_paise") or 0),
                "cess": paise_to_rupees(adj.get("cess_paise") or 0),
                "total_tax": paise_to_rupees(
                    (adj.get("igst_paise") or 0)
                    + (adj.get("cgst_paise") or 0)
                    + (adj.get("sgst_paise") or 0)
                    + (adj.get("cess_paise") or 0)
                ),
                "doc_type": "ADJUSTMENT",
                "statutory_reason": str(adj.get("reason") or ""),
                "disposition": "EXTERNAL_VERIFIED",
                "source": "Manual Entry / CA Workpaper",
            })

    # Second, collect active reclaim events (Circular 170: dual-posted to 4A5 and 4D1)
    if row_id_clean in ("4D1", "4A5"):
        reclaim_events = load_reclaim_events_for_run(sb, run_id)
        for ev in reclaim_events:
            ev_type = str(ev.get("event_type") or "RECLAIM").upper()
            mult = 1 if ev_type == "RECLAIM" else -1
            r_igst = mult * int(ev.get("reclaimed_igst_paise") or 0)
            r_cgst = mult * int(ev.get("reclaimed_cgst_paise") or 0)
            r_sgst = mult * int(ev.get("reclaimed_sgst_paise") or 0)
            r_cess = mult * int(ev.get("reclaimed_cess_paise") or 0)
            matching_items.append({
                "id": str(ev.get("id")),
                "type": "RECLAIM",
                "supplier_gstin": str(ev.get("supplier_gstin") or "RECLAIM"),
                "supplier_name": f"Reclaim ({ev.get('statutory_reason') or 'Reversal Ledger'})",
                "invoice_number": str(ev.get("document_number") or ev.get("reference_doc") or "RECLAIM"),
                "invoice_date": str(ev.get("evidence_document_date") or ev.get("created_at") or "")[:10],
                "taxable_value": 0.0,
                "igst": paise_to_rupees(r_igst),
                "cgst": paise_to_rupees(r_cgst),
                "sgst": paise_to_rupees(r_sgst),
                "cess": paise_to_rupees(r_cess),
                "total_tax": paise_to_rupees(r_igst + r_cgst + r_sgst + r_cess),
                "doc_type": "RECLAIM",
                "statutory_reason": str(ev.get("reclaim_notes") or ev.get("statutory_evidence_type") or "Statutory Reclaim under Circular 170 Para 4.3"),
                "disposition": "AUTHORIZED_RECLAIM",
                "source": "Reversal & Reclaim Ledger",
            })

    # Third, scan outcome records
    for r in all_outcomes:
        rec_id = r.id
        # Duplicate entries (extra PR bookings) must never enter Table 4
        if rec_id.startswith("de:") or r.category == "duplicate_entry":
            continue

        pid = r.matched_pr_id or ""
        gid = rec_id.removeprefix("pm:").removeprefix("gstr:") if (rec_id.startswith("pm:") or rec_id.startswith("gstr:")) else ""

        g_entry = gstr_db.get(gid) or {}
        g_rd = g_entry.get("record_data") if isinstance(g_entry.get("record_data"), dict) else {}
        p_entry = pr_db.get(pid) or {}
        p_rd = p_entry.get("record_data") if isinstance(p_entry.get("record_data"), dict) else {}

        igst_p, cgst_p, sgst_p, cess_p = extract_tax_heads_paise(g_rd or p_rd)
        cn = is_credit_note(g_rd or p_rd, r)
        sign = -1 if cn else 1
        sig_igst = sign * igst_p
        sig_cgst = sign * cgst_p
        sig_sgst = sign * sgst_p
        sig_cess = sign * cess_p

        g_doctype = str(g_rd.get("doc_type") or g_rd.get("document_type") or "").strip().upper()
        p_doctype = str(p_rd.get("doc_type") or p_rd.get("document_type") or "").strip().upper()
        is_rcm = str(g_rd.get("reverse_charge") or p_rd.get("reverse_charge") or "").strip().upper() in ("Y", "YES", "TRUE")

        disp_175 = dispositions.get(f"{rec_id}:SEC_17_5") or dispositions.get(rec_id)
        disp_r37 = dispositions.get(f"{rec_id}:RULE_37") or dispositions.get(rec_id)
        disp_r37a = dispositions.get(f"{rec_id}:RULE_37A") or dispositions.get(rec_id)
        disp_2b = dispositions.get(f"{rec_id}:TWO_B_ONLY") or dispositions.get(rec_id)
        disp_162b = (
            dispositions.get(f"{rec_id}:SECTION_16_2_B")
            or dispositions.get(f"{rec_id}:GOODS_NOT_RECEIVED")
            or dispositions.get(rec_id)
        )
        disp_4d2 = (
            dispositions.get(f"{rec_id}:TIME_BARRED_16_4")
            or dispositions.get(f"{rec_id}:POS_RESTRICTED")
            or dispositions.get(f"{rec_id}:SECTION_16_4")
            or dispositions.get(f"{rec_id}:POS_MISMATCH")
            or dispositions.get(rec_id)
        )

        # 4D2 Boundary: Ineligible under Section 16(4) / PoS restriction
        is_4d2_restricted, reason_4d2 = is_section_16_4_or_pos_restricted(r, g_rd, p_rd, disp_4d2)
        if is_4d2_restricted:
            if row_id_clean == "4D2":
                matching_items.append({
                    "id": rec_id,
                    "type": "INVOICE",
                    "supplier_gstin": r.supplier_gstin,
                    "supplier_name": r.supplier_name,
                    "invoice_number": r.invoice_number,
                    "invoice_date": str(r.invoice_date or "")[:10],
                    "taxable_value": paise_to_rupees(g_rd.get("taxable_value_paise") or p_rd.get("taxable_value_paise") or 0),
                    "igst": paise_to_rupees(sig_igst),
                    "cgst": paise_to_rupees(sig_cgst),
                    "sgst": paise_to_rupees(sig_sgst),
                    "cess": paise_to_rupees(sig_cess),
                    "total_tax": paise_to_rupees(sig_igst + sig_cgst + sig_sgst + sig_cess),
                    "doc_type": "CREDIT_NOTE" if cn else "INVOICE",
                    "statutory_reason": f"Ineligible under {reason_4d2} (Table 4D2 info-only per Circular 170 Para 4.3)",
                    "disposition": reason_4d2,
                    "source": "GSTR-2B ∩ Purchase Register",
                })
            continue  # Crucial: 4D2 records NEVER enter 4A, 4B, or 4C

        is_sec175 = (
            r.category == "blocked_credit"
            or bool(r.blocked_credit_flag)
            or (r.itc_reason and any(k in r.itc_reason.lower() for k in ("17(5)", "17 (5)", "blocked", "sec 17")))
        )
        is_disp_175_blocked = bool(
            disp_175
            and (
                str(disp_175.get("table4_effect", "")).upper() == "4B1"
                or str(disp_175.get("disposition", "")).upper() in ("CONFIRMED_BLOCKED", "INELIGIBLE")
            )
            and str(disp_175.get("disposition", "")).upper() != "STATUTORY_EXCEPTION"
        )
        is_sec175_confirmed = is_disp_175_blocked or (
            is_sec175 and (not disp_175 or str(disp_175.get("disposition", "")).upper() != "STATUTORY_EXCEPTION")
        )
        is_r37 = (
            r.category == "rule37_warnings" or bool(r.rule37_flag) or str(r.match_status).upper() in RULE37_CONCERNS
        ) and not (r.match_status == "RULE37A" or r.rule37a_flag)
        is_disp_r37_reversed = bool(
            disp_r37
            and str(disp_r37.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED")
            and (
                str(disp_r37.get("table4_effect", "")).upper() == "4B2"
                or str(disp_r37.get("exception_type", "")).upper() == "RULE_37"
            )
        )
        is_r37_reversed = is_disp_r37_reversed or (
            is_r37 and bool(disp_r37 and str(disp_r37.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED"))
        )
        is_r37a = (r.match_status == "RULE37A" or r.rule37a_flag)
        is_r37a_reversed = is_r37a and bool(disp_r37a and str(disp_r37a.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED", "RULE_37A_VERIFIED", "CONFIRMED_NON_FILER"))
        is_162b_reversed = bool(
            disp_162b
            and str(disp_162b.get("disposition", "")).upper() in (
                "REVERSED", "SECTION_16_2_B_REVERSED", "CONFIRMED_NOT_RECEIVED"
            )
        )

        belongs_to_row = False
        stat_reason = ""
        disp_label = "STANDARD_MATCHED"

        if row_id_clean == "4A1" and (g_doctype in ("IMPG", "IMPGSEZ") or p_doctype in ("IMPG", "IMPGSEZ", "IMPORT_GOODS")):
            belongs_to_row = True
            stat_reason = "Bill of Entry / Import of Goods under Section 16(2)"
        elif row_id_clean == "4A3" and is_rcm and (p_rd or r.category == "matched"):
            belongs_to_row = True
            stat_reason = "Domestic Inward Supply liable to Reverse Charge under Section 9(3)"
        elif row_id_clean == "4A4" and (g_doctype == "ISD" or p_doctype == "ISD"):
            belongs_to_row = True
            stat_reason = "Input Service Distributor document under Section 20"
        elif row_id_clean == "4A5":
            # Exclude PR-only and unbooked 2B-only
            if not rec_id.startswith("pr:") and r.category != "missed_itc":
                if rec_id.startswith("gstr:") or (not pid and not rec_id.startswith("pm:")):
                    if disp_2b and str(disp_2b.get("disposition", "")).upper() == "BOOKED_AND_VERIFIED":
                        belongs_to_row = True
                        stat_reason = "2B Inward Booked & Verified by CA"
                        disp_label = "BOOKED_AND_VERIFIED"
                    elif disp_2b and str(disp_2b.get("disposition", "")).upper() == "SECTION_16_2_B_REVERSED":
                        belongs_to_row = True
                        stat_reason = "2B Inward Gross Claimed; reversed in 4B2 under Section 16(2)(b)"
                        disp_label = "SECTION_16_2_B_REVERSED"
                else:
                    belongs_to_row = True
                    stat_reason = "Domestic Inward Supply eligible under Section 16(2)"
                    if is_sec175_confirmed:
                        stat_reason += " (Gross claimed; reversed in 4B1 per Circular 170)"
                    elif is_r37_reversed or is_r37a_reversed or is_162b_reversed:
                        stat_reason += " (Gross claimed; reversed in 4B2 per Circular 170)"
        elif row_id_clean == "4B1" and is_sec175_confirmed:
            belongs_to_row = True
            stat_reason = r.itc_reason or "Blocked Credit under Section 17(5)"
            disp_label = "CONFIRMED_BLOCKED"
        elif row_id_clean == "4B2":
            if is_r37_reversed:
                belongs_to_row = True
                stat_reason = "Reversal under Rule 37 (180 days)"
                disp_label = "REVERSAL_CONFIRMED"
            elif is_r37a_reversed:
                belongs_to_row = True
                stat_reason = "Reversal under Rule 37A (Supplier non-filer)"
                disp_label = "REVERSAL_CONFIRMED"
            elif is_162b_reversed:
                belongs_to_row = True
                stat_reason = "Reversal under Section 16(2)(b) (Goods/services not received)"
                disp_label = "SECTION_16_2_B_REVERSED"
            elif (rec_id.startswith("gstr:") or (not pid and not rec_id.startswith("pm:"))) and (
                disp_2b and str(disp_2b.get("disposition", "")).upper() == "SECTION_16_2_B_REVERSED"
            ):
                belongs_to_row = True
                stat_reason = "2B Inward Temporary Reversal under Section 16(2)(b)"
                disp_label = "SECTION_16_2_B_REVERSED"

        if belongs_to_row:
            matching_items.append({
                "id": rec_id,
                "type": "INVOICE",
                "supplier_gstin": r.supplier_gstin,
                "supplier_name": r.supplier_name,
                "invoice_number": r.invoice_number,
                "invoice_date": str(r.invoice_date or "")[:10],
                "taxable_value": paise_to_rupees(g_rd.get("taxable_value_paise") or p_rd.get("taxable_value_paise") or 0),
                "igst": paise_to_rupees(sig_igst),
                "cgst": paise_to_rupees(sig_cgst),
                "sgst": paise_to_rupees(sig_sgst),
                "cess": paise_to_rupees(sig_cess),
                "total_tax": paise_to_rupees(sig_igst + sig_cgst + sig_sgst + sig_cess),
                "doc_type": "CREDIT_NOTE" if cn else "INVOICE",
                "statutory_reason": stat_reason,
                "disposition": disp_label,
                "source": "GSTR-2B ∩ Purchase Register",
            })

    # Apply optional text search
    if search:
        s = search.lower().strip()
        matching_items = [
            m for m in matching_items
            if s in str(m.get("supplier_gstin", "")).lower()
            or s in str(m.get("supplier_name", "")).lower()
            or s in str(m.get("invoice_number", "")).lower()
        ]

    # Paginate
    total_records = len(matching_items)
    page_idx = max(1, page)
    start_idx = (page_idx - 1) * limit
    end_idx = start_idx + limit
    paginated = matching_items[start_idx:end_idx]

    # Sum totals
    tot_igst = sum(x["igst"] for x in matching_items)
    tot_cgst = sum(x["cgst"] for x in matching_items)
    tot_sgst = sum(x["sgst"] for x in matching_items)
    tot_cess = sum(x["cess"] for x in matching_items)

    return {
        "row_id": row_id_clean,
        "total_records": total_records,
        "page": page_idx,
        "limit": limit,
        "totals": {
            "igst": round(tot_igst, 2),
            "cgst": round(tot_cgst, 2),
            "sgst": round(tot_sgst, 2),
            "cess": round(tot_cess, 2),
            "total_tax": round(tot_igst + tot_cgst + tot_sgst + tot_cess, 2),
        },
        "records": paginated,
    }
