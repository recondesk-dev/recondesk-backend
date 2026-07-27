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
