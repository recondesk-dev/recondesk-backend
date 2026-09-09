"""Advanced filtered export for reconciliation results (Excel + PDF).

Reuses existing payload loaders and run-bucket record builders from
``reconciliation_api`` / ``reconciliation_outcomes`` — does not re-query
or re-implement matching logic.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import reconciliation_outcomes as ro

# Status labels accepted by the Advanced Export filter API / UI.
STATUS_MATCHED = "MATCHED"
STATUS_MISMATCHED = "MISMATCHED"
STATUS_MISSING = "MISSING"
STATUS_ITC_AT_RISK = "ITC_AT_RISK"
STATUS_DUPLICATE = "DUPLICATE"

ALL_EXPORT_STATUSES = (
    STATUS_MATCHED,
    STATUS_MISMATCHED,
    STATUS_MISSING,
    STATUS_ITC_AT_RISK,
    STATUS_DUPLICATE,
)


@dataclass
class AdvancedExportRow:
    status: str
    client_id: str
    period: str
    itc_eligibility_category: str
    invoice_number: str
    vendor_name: str
    supplier_gstin: str
    invoice_date: str
    taxable_value: float
    itc_amount: float
    decision_what: str
    decision_why: str
    decision_next: str
    match_level: str
    record_id: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdvancedExportBundle:
    rows: list[AdvancedExportRow]
    client_name: str
    client_id: str
    period: str
    run_id: str
    firm_name: str
    generated_by: str
    generated_at: datetime


def _safe_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _paise_to_rupees(paise: Any) -> float:
    if paise is None or paise == "":
        return 0.0
    try:
        return int(paise) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _taxable_from_row(row: dict[str, Any]) -> float:
    for side in ("gstr2b_data", "purchase_register_data"):
        gd = row.get(side)
        if not isinstance(gd, dict):
            continue
        tp = gd.get("taxable_amount_paise")
        if tp is not None and str(tp).strip() != "":
            return _paise_to_rupees(tp)
        for k in ("taxable_amount", "Taxable Amount", "taxable_val", "taxable"):
            if k in gd and gd[k] not in (None, ""):
                return _safe_float(gd[k])
    return 0.0


def _vendor_from_row(row: dict[str, Any]) -> str:
    tn = row.get("trade_name") or row.get("supplier_name")
    if tn:
        return str(tn).strip()
    for side in ("gstr2b_data", "purchase_register_data"):
        gd = row.get(side)
        if not isinstance(gd, dict):
            continue
        for key in (
            "trade_name",
            "Trade Name",
            "supplier_name",
            "Supplier Name",
            "vendor_name",
            "Vendor Name",
        ):
            v = gd.get(key)
            if v:
                return str(v).strip()[:200]
    return ""


def _itc_eligibility_from_row(row: dict[str, Any]) -> str:
    for side in ("purchase_register_data", "gstr2b_data"):
        gd = row.get(side)
        if not isinstance(gd, dict):
            continue
        for key in ("itc_eligibility", "ITC Eligibility", "itc_claimed", "ITC Claimed"):
            v = gd.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


def _normalize_itc_category(raw: str) -> str:
    s = (raw or "").strip()
    return s if s else "(blank)"


def _decision_text(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return s


def _safe_filename_part(s: str) -> str:
    o = re.sub(r"[^\w\-.]+", "_", (s or "").strip())
    return (o[:80] or "client").strip("_") or "client"


def collect_export_rows(
    *,
    sb: Any,
    run_id: str,
    payload: dict[str, Any],
    run_row: dict[str, Any],
    client_name: str,
    firm_name: str = "",
    generated_by: str = "",
    # Lazy import of builders to avoid circular import at module load.
) -> AdvancedExportBundle:
    """Build a flat list of exportable rows for one run using existing builders."""
    # Import inside function: reconciliation_api pulls many deps; keep load light.
    from app.routers.reconciliation_api import (
        _build_matched_pair_records,
        _build_missed_itc_records,
        _build_wrongful_risk_records,
        _notes_count_for_run,
    )

    period = str(run_row.get("period") or "")
    client_id = str(run_row.get("client_gstin_id") or "")
    notes = _notes_count_for_run(sb, run_id)
    outcome_rows = ro.build_outcome_rows(sb, run_id, payload)[0]

    flat: list[AdvancedExportRow] = []

    matched_pairs = _build_matched_pair_records(
        sb,
        rid=run_id,
        payload=payload,
        note_counts=notes,
        precomputed_outcome_rows=outcome_rows,
    )
    for api_row, _orow in matched_pairs:
        flat.append(
            _api_row_to_export(
                api_row,
                status=STATUS_MATCHED,
                client_id=client_id,
                period=period,
            )
        )

    review_pairs = _build_matched_pair_records(
        sb,
        rid=run_id,
        payload=payload,
        note_counts=notes,
        fetch_review_required=True,
        precomputed_outcome_rows=outcome_rows,
    )
    for api_row, _orow in review_pairs:
        flat.append(
            _api_row_to_export(
                api_row,
                status=STATUS_MISMATCHED,
                client_id=client_id,
                period=period,
            )
        )

    # Duplicate-entry outcome rows that may not appear in review_required builder.
    seen_ids = {r.record_id for r in flat}
    for orow in outcome_rows:
        if orow.category != "duplicate_entry":
            continue
        if orow.id in seen_ids:
            continue
        flat.append(
            AdvancedExportRow(
                status=STATUS_DUPLICATE,
                client_id=client_id,
                period=period,
                itc_eligibility_category="(blank)",
                invoice_number=str(orow.invoice_number or ""),
                vendor_name=str(orow.supplier_name or ""),
                supplier_gstin=str(orow.supplier_gstin or ""),
                invoice_date=str(orow.invoice_date or ""),
                taxable_value=0.0,
                itc_amount=_paise_to_rupees(orow.amount) if orow.amount else 0.0,
                decision_what=_decision_text(orow.decision_what),
                decision_why=_decision_text(orow.decision_why),
                decision_next=_decision_text(orow.decision_next),
                match_level="UNMATCHED",
                record_id=orow.id,
                raw=orow.as_dict(),
            )
        )

    missed = _build_missed_itc_records(
        sb,
        rid=run_id,
        payload=payload,
        note_counts=notes,
        source_software="your accounting software",
    )
    for api_row in missed:
        flat.append(
            _api_row_to_export(
                api_row,
                status=STATUS_MISSING,
                client_id=client_id,
                period=period,
            )
        )

    risk = _build_wrongful_risk_records(
        sb, rid=run_id, payload=payload, note_counts=notes
    )
    for api_row in risk:
        flat.append(
            _api_row_to_export(
                api_row,
                status=STATUS_ITC_AT_RISK,
                client_id=client_id,
                period=period,
            )
        )

    return AdvancedExportBundle(
        rows=flat,
        client_name=client_name or "",
        client_id=client_id,
        period=period,
        run_id=run_id,
        firm_name=firm_name or "",
        generated_by=generated_by or "",
        generated_at=datetime.now(timezone.utc),
    )


def _api_row_to_export(
    api_row: dict[str, Any],
    *,
    status: str,
    client_id: str,
    period: str,
) -> AdvancedExportRow:
    itc_raw = _itc_eligibility_from_row(api_row)
    amt = _safe_float(api_row.get("amount"))
    return AdvancedExportRow(
        status=status,
        client_id=client_id,
        period=period,
        itc_eligibility_category=_normalize_itc_category(itc_raw),
        invoice_number=str(api_row.get("invoice_number") or ""),
        vendor_name=_vendor_from_row(api_row),
        supplier_gstin=str(api_row.get("supplier_gstin") or ""),
        invoice_date=str(api_row.get("invoice_date") or ""),
        taxable_value=_taxable_from_row(api_row),
        itc_amount=amt,
        decision_what=_decision_text(api_row.get("decision_what")),
        decision_why=_decision_text(api_row.get("decision_why")),
        decision_next=_decision_text(api_row.get("decision_next")),
        match_level=str(api_row.get("match_level") or ""),
        record_id=str(api_row.get("id") or ""),
        raw=api_row,
    )


def apply_filters(
    bundle: AdvancedExportBundle,
    *,
    statuses: Optional[list[str]] = None,
    client_ids: Optional[list[str]] = None,
    period: Optional[str] = None,
    itc_categories: Optional[list[str]] = None,
) -> list[AdvancedExportRow]:
    """Filter collected rows by the Advanced Export panel criteria."""
    status_set = {
        s.strip().upper() for s in (statuses or []) if s and str(s).strip()
    }
    client_set = {str(c).strip() for c in (client_ids or []) if c and str(c).strip()}
    period_q = (period or "").strip()
    itc_set = {
        _normalize_itc_category(str(c))
        for c in (itc_categories or [])
        if c is not None and str(c).strip() != ""
    }
    # Treat explicit "(blank)" selection as matching blank eligibility.
    if itc_categories:
        for c in itc_categories:
            if str(c).strip().lower() in ("(blank)", "blank", ""):
                itc_set.add("(blank)")

    out: list[AdvancedExportRow] = []
    for row in bundle.rows:
        if status_set and row.status not in status_set:
            continue
        if client_set and row.client_id not in client_set:
            continue
        if period_q:
            row_p = row.period.strip()
            # Soft-match YYYY-MM prefixes so "2026-04" matches "2026-04-01".
            if row_p != period_q and row_p[:7] != period_q[:7]:
                continue
        if itc_set and row.itc_eligibility_category not in itc_set:
            continue
        out.append(row)
    return out


def summarize_rows(rows: list[AdvancedExportRow]) -> dict[str, Any]:
    by_status = Counter(r.status for r in rows)
    by_itc = Counter(r.itc_eligibility_category for r in rows)
    itc_at_risk_total = sum(
        r.itc_amount for r in rows if r.status == STATUS_ITC_AT_RISK
    )
    # Also include MISSING as recoverable ITC context in summary money line.
    missed_itc_total = sum(r.itc_amount for r in rows if r.status == STATUS_MISSING)
    return {
        "total_rows": len(rows),
        "count_by_status": dict(sorted(by_status.items())),
        "count_by_itc_category": dict(sorted(by_itc.items())),
        "total_itc_at_risk": round(itc_at_risk_total, 2),
        "total_missed_itc": round(missed_itc_total, 2),
    }


def available_itc_categories(bundle: AdvancedExportBundle) -> list[str]:
    cats = sorted({r.itc_eligibility_category for r in bundle.rows})
    return cats


def export_filename(bundle: AdvancedExportBundle, ext: str) -> str:
    client = _safe_filename_part(bundle.client_name or bundle.client_id or "client")
    period = _safe_filename_part(bundle.period or "period")
    return f"ReconDesk_Advanced_{client}_{period}.{ext}"
