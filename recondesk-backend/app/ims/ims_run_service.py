"""Assemble Phase 1 recommendations from a reconcile run.

Uses outcome rows + stored ``ims_status`` on GSTR matcher rows. Optionally
enriches ``writeback_payload`` from a live IMS fetch when GSTN is connected.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.ims.ims_recommendation import (
    InvoiceRecommendationInput,
    RecommendationBatch,
    recommend_batch,
    unavailable,
)
from app.services import reconciliation_outcomes as ro
from app.services.ims_overlay import (
    DEFAULT_IMS_STATUS,
    fetch_ims_invoices,
    ims_composite_key,
)
from app.services.sandbox_gst_client import IMSInvoice, SandboxClientError

_log = logging.getLogger(__name__)

_SECTION_MAP = {
    "B2B": "b2b",
    "B2BA": "b2ba",
    "CN": "cn",
    "CNA": "cna",
    "DN": "dn",
    "DNA": "dna",
    "ECOM": "ecom",
    "ECOMA": "ecoma",
}


def build_recommendations_for_run(
    sb,
    *,
    run_id: str,
    run_row: dict[str, Any],
    access_token: str | None = None,
    buyer_gstin: str | None = None,
) -> RecommendationBatch:
    """Load payload → outcome rows → recommendations.

    Missing payload → ``available=False`` (not a confirmed zero).
    """
    payload = ro.load_payload(sb, run_id)
    if not payload:
        return unavailable("no_reconcile_payload", run_id=run_id)

    period = str(run_row.get("period") or "")
    gstin = (buyer_gstin or "").strip().upper() or None

    outcome_rows, _cc, _stats = ro.build_outcome_rows(sb, run_id, payload)
    gstr_m = ro.load_gstr_map(sb, run_id)
    r37_by_pr, r37_by_pair, blocked_by_pair = _compliance_indexes(payload)

    # Prefer live IMS invoices for writeback payloads when token present.
    ims_by_key: dict[tuple[str, str], IMSInvoice] = {}
    source = "reconcile_ims_overlay"
    if access_token and gstin:
        try:
            invoices = fetch_ims_invoices(access_token, gstin)
            for inv in invoices:
                key = ims_composite_key(inv.supplier_gstin, inv.invoice_number)
                if key[0] and key[1]:
                    ims_by_key[key] = inv
            source = "live_ims_plus_reconcile"
        except SandboxClientError as exc:
            _log.warning("IMS live fetch failed for recommendations: %s", exc)
        except Exception as exc:
            _log.warning("IMS live fetch unexpected error: %s", exc)

    inputs: list[InvoiceRecommendationInput] = []
    seen: set[str] = set()

    for row in outcome_rows:
        category = (row.category or "").strip().lower()
        # Skip PR-only wrongful risk for IMS write queue — no supplier IMS doc.
        if category == "wrongful_risk":
            continue

        gst = (row.supplier_gstin or row.gstr_supplier_gstin or "").strip().upper()
        inum = (row.invoice_number or "").strip()
        if not gst or not inum:
            continue

        key = ims_composite_key(gst, inum)
        dedupe = f"{key[0]}|{key[1]}|{category}"
        if dedupe in seen:
            continue
        seen.add(dedupe)

        ims_status = DEFAULT_IMS_STATUS
        writeback: dict[str, Any] | None = None
        section = "b2b"
        blocked = False

        live = ims_by_key.get(key)
        if live is not None:
            ims_status = live.ims_status or DEFAULT_IMS_STATUS
            writeback = _writeback_from_ims(live)
            section = _SECTION_MAP.get(live.section.upper(), live.section.lower() or "b2b")
            blocked = bool(live.is_pending_action_blocked)
        else:
            # Fall back to stored overlay on GSTR matcher / record_data.
            ims_status = _ims_from_gstr_maps(gstr_m, row, key)
            writeback = _writeback_from_gstr_maps(gstr_m, row, key, gst, inum, period)
            if getattr(row, "is_credit_note", False):
                section = "cdnr"

        r37 = _lookup_rule37(row, gst, inum, r37_by_pr, r37_by_pair)
        bc = _lookup_blocked(row, gst, inum, blocked_by_pair)
        days_remaining = None
        r37_status = None
        if isinstance(r37, dict):
            raw_days = r37.get("days_remaining")
            if raw_days is not None and str(raw_days).strip() != "":
                try:
                    days_remaining = int(raw_days)
                except (TypeError, ValueError):
                    days_remaining = None
            st = r37.get("status")
            r37_status = str(st).strip() if st is not None else None

        bc_category = None
        bc_reason = None
        if isinstance(bc, dict):
            cat = bc.get("category")
            reason = bc.get("reason")
            bc_category = str(cat).strip() if cat else None
            bc_reason = str(reason).strip() if reason else None

        inputs.append(
            InvoiceRecommendationInput(
                invoice_id=row.id,
                supplier_gstin=gst,
                invoice_number=inum,
                category=category,
                ims_status=ims_status,
                match_status=row.match_status or "",
                match_confidence=row.match_confidence,
                total_tax_diff_paise=int(row.total_tax_diff_paise or 0),
                taxable_value_diff_paise=int(row.taxable_value_diff or 0),
                amount_paise=row.amount,
                invoice_date=row.invoice_date,
                supplier_name=row.supplier_name,
                is_pending_action_blocked=blocked,
                section=section,
                writeback_payload=writeback,
                rule37_flag=bool(row.rule37_flag),
                rule37a_flag=bool(getattr(row, "rule37a_flag", False)),
                blocked_credit_flag=bool(row.blocked_credit_flag),
                rule37_days_remaining=days_remaining,
                rule37_status=r37_status,
                blocked_credit_category=bc_category,
                blocked_credit_reason=bc_reason,
                pr_supplier_gstin=row.pr_supplier_gstin,
                gstr_supplier_gstin=row.gstr_supplier_gstin,
                review_reason=getattr(row, "normalized_reason", None) or getattr(row, "match_status", None),
            )
        )

    batch = recommend_batch(
        inputs,
        run_id=run_id,
        period=period or None,
        gstin=gstin,
        source=source,
    )
    return batch


def _ims_from_gstr_maps(
    gstr_m: dict[str, Any],
    row: Any,
    key: tuple[str, str],
) -> str:
    # Outcome id prefixes: pm:{gstr_id}, mi:{gstr_id}, …
    rid = str(getattr(row, "id", "") or "")
    gstr_id = ""
    if ":" in rid:
        gstr_id = rid.split(":", 1)[1]
    cell = gstr_m.get(gstr_id) if gstr_id else None
    if isinstance(cell, dict):
        matcher = cell.get("matcher") or {}
        rd = cell.get("record_data") or {}
        for src in (matcher, rd):
            if isinstance(src, dict):
                st = str(src.get("ims_status") or "").strip().lower()
                if st:
                    return st
    # Scan map by composite key as last resort
    for cell in (gstr_m or {}).values():
        if not isinstance(cell, dict):
            continue
        matcher = cell.get("matcher") or {}
        if not isinstance(matcher, dict):
            continue
        k = ims_composite_key(
            matcher.get("supplier_gstin"),
            matcher.get("invoice_number")
            or matcher.get("invoice_number_normalized"),
        )
        if k == key:
            st = str(matcher.get("ims_status") or "").strip().lower()
            if st:
                return st
    return DEFAULT_IMS_STATUS


def _writeback_from_ims(inv: IMSInvoice) -> dict[str, Any]:
    raw = dict(inv.raw) if isinstance(inv.raw, dict) else {}
    # Ensure canonical fields even if raw is sparse
    raw.setdefault("stin", inv.supplier_gstin)
    raw.setdefault("inum", inv.invoice_number)
    raw.setdefault("idt", inv.invoice_date)
    raw.setdefault("txval", inv.taxable_value)
    raw.setdefault("val", inv.invoice_value)
    raw.setdefault("iamt", inv.igst)
    raw.setdefault("camt", inv.cgst)
    raw.setdefault("samt", inv.sgst)
    raw.setdefault("cess", inv.cess)
    raw.setdefault("pos", inv.pos)
    raw.setdefault("rtnprd", inv.return_period)
    raw.setdefault("srcform", inv.source_form or "R1")
    if "prev_status" not in raw:
        raw["prev_status"] = raw.get("action") or "N"
    return raw


def _find_gstr_cell(
    gstr_m: dict[str, Any],
    row: Any,
    key: tuple[str, str],
) -> dict[str, Any] | None:
    rid = str(getattr(row, "id", "") or "")
    gstr_id = ""
    if ":" in rid:
        gstr_id = rid.split(":", 1)[1]
    cell = gstr_m.get(gstr_id) if gstr_id else None
    if isinstance(cell, dict):
        return cell
    for c in (gstr_m or {}).values():
        if not isinstance(c, dict):
            continue
        matcher = c.get("matcher") or {}
        if not isinstance(matcher, dict):
            continue
        k = ims_composite_key(
            matcher.get("supplier_gstin"),
            matcher.get("invoice_number") or matcher.get("invoice_number_normalized"),
        )
        if k == key:
            return c
    return None


def _writeback_from_gstr_maps(
    gstr_m: dict[str, Any],
    row: Any,
    key: tuple[str, str],
    gst: str,
    inum: str,
    period: str,
) -> dict[str, Any]:
    cell = _find_gstr_cell(gstr_m, row, key)
    rd = cell.get("record_data") or {} if isinstance(cell, dict) else {}
    matcher = cell.get("matcher") or {} if isinstance(cell, dict) else {}

    txval = rd.get("txval")
    if txval is None:
        tp = matcher.get("taxable_value_paise")
        txval = round(float(tp) / 100.0, 2) if tp is not None else 0.0
    else:
        try:
            txval = round(float(txval), 2)
        except (TypeError, ValueError):
            txval = 0.0

    iamt = rd.get("iamt")
    if iamt is None:
        ip = matcher.get("igst_paise")
        iamt = round(float(ip) / 100.0, 2) if ip is not None else 0.0
    else:
        try:
            iamt = round(float(iamt), 2)
        except (TypeError, ValueError):
            iamt = 0.0

    camt = rd.get("camt")
    if camt is None:
        cp = matcher.get("cgst_paise")
        camt = round(float(cp) / 100.0, 2) if cp is not None else 0.0
    else:
        try:
            camt = round(float(camt), 2)
        except (TypeError, ValueError):
            camt = 0.0

    samt = rd.get("samt")
    if samt is None:
        sp = matcher.get("sgst_paise")
        samt = round(float(sp) / 100.0, 2) if sp is not None else 0.0
    else:
        try:
            samt = round(float(samt), 2)
        except (TypeError, ValueError):
            samt = 0.0

    cess = rd.get("cess") or rd.get("csamt")
    if cess is None:
        csp = matcher.get("cess_paise")
        cess = round(float(csp) / 100.0, 2) if csp is not None else 0.0
    else:
        try:
            cess = round(float(cess), 2)
        except (TypeError, ValueError):
            cess = 0.0

    tot_tax = round(iamt + camt + samt + cess, 2)
    val = rd.get("val")
    if val is None:
        vp = matcher.get("invoice_value_paise")
        val = round(float(vp) / 100.0, 2) if vp is not None else round(txval + tot_tax, 2)
    else:
        try:
            val = round(float(val), 2)
        except (TypeError, ValueError):
            val = round(txval + tot_tax, 2)

    idt = str(rd.get("idt") or getattr(row, "invoice_date", "") or matcher.get("invoice_date") or "").strip()
    pos = str(rd.get("pos") or matcher.get("pos") or "27").strip()
    rchrg = "Y" if (rd.get("rchrg") in ("Y", True) or matcher.get("is_rcm") or getattr(row, "is_rcm", False)) else "N"
    inv_typ = str(rd.get("inv_typ") or "R")

    return {
        "stin": gst,
        "inum": inum,
        "idt": idt,
        "val": val,
        "txval": txval,
        "iamt": iamt,
        "camt": camt,
        "samt": samt,
        "cess": cess,
        "pos": pos,
        "rchrg": rchrg,
        "inv_typ": inv_typ,
        "rtnprd": period,
        "srcform": "R1",
        "prev_status": "N",
    }



def _compliance_indexes(
    payload: dict[str, Any],
) -> tuple[dict[str, dict], dict[tuple[str, str], dict], dict[tuple[str, str], dict]]:
    """Index Rule 37 / 17(5) compliance rows for enrichment.

    ``OutcomeRow`` only carries boolean flags; day-counts and 17(5) categories
    live on ``payload["compliance"]`` and are joined here (no OutcomeRow change).
    """
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    r37_list = list(comp.get("rule37") or [])
    r37_by_pr: dict[str, dict] = {
        str(x.get("pr_id")): x
        for x in r37_list
        if isinstance(x, dict) and x.get("pr_id") is not None
    }
    r37_by_pair: dict[tuple[str, str], dict] = {}
    for x in r37_list:
        if not isinstance(x, dict):
            continue
        pair = (
            str(x.get("supplier_gstin") or "").strip().upper(),
            str(x.get("invoice_number") or "").strip(),
        )
        if pair[0] and pair[1]:
            r37_by_pair[pair] = x

    s175 = list(comp.get("section_17_5") or comp.get("section_175") or [])
    blocked_by_pair: dict[tuple[str, str], dict] = {}
    for x in s175:
        if not isinstance(x, dict):
            continue
        pair = (
            str(x.get("supplier_gstin") or "").strip().upper(),
            str(x.get("invoice_number") or "").strip(),
        )
        if pair[0]:
            blocked_by_pair[pair] = x
    return r37_by_pr, r37_by_pair, blocked_by_pair


def _lookup_rule37(
    row: Any,
    gst: str,
    inum: str,
    r37_by_pr: dict[str, dict],
    r37_by_pair: dict[tuple[str, str], dict],
) -> dict | None:
    rid = str(getattr(row, "id", "") or "")
    if rid.startswith("r37:"):
        hit = r37_by_pr.get(rid.split(":", 1)[1])
        if hit is not None:
            return hit
    mpid = getattr(row, "matched_pr_id", None)
    if mpid:
        hit = r37_by_pr.get(str(mpid))
        if hit is not None:
            return hit
    return r37_by_pair.get((gst, inum))


def _lookup_blocked(
    row: Any,
    gst: str,
    inum: str,
    blocked_by_pair: dict[tuple[str, str], dict],
) -> dict | None:
    hit = blocked_by_pair.get((gst, inum))
    if hit is not None:
        return hit
    # Also try PR / GSTR GSTINs from the outcome when supplier_gstin was blended.
    for alt in (
        getattr(row, "gstr_supplier_gstin", None),
        getattr(row, "pr_supplier_gstin", None),
    ):
        alt_g = str(alt or "").strip().upper()
        if alt_g and alt_g != gst:
            hit = blocked_by_pair.get((alt_g, inum))
            if hit is not None:
                return hit
    return None
