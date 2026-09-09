"""Compose all GSTR-1 filing mappers into one period result.

Eligibility audit (primary Save lanes — mutually exclusive)
-----------------------------------------------------------
HSN is intentionally **parallel** (summary of taxable primary lanes), not a
competing primary lane. DOC_ISSUE is period-level from Save counts.

| Primary lane | Eligibility (first match wins) |
|--------------|--------------------------------|
| **CDNR / CDNUR** | ``invoice_type ∈ {CREDIT_NOTE, DEBIT_NOTE}`` — registered → CDNR Save/review; unregistered → CDNUR Save / B2CS-net / export-review |
| **NIL** | Nil-class via ``resolve_nil_amount_column_from_sr_raw`` ≠ ``not_nil_class`` |
| **AT/TXPD** | ``ADVANCES`` type or advance raw keywords → envelope external only |
| **B2B** | ``invoice_type == B2B`` + valid GSTIN; also peels ``EXPORT``+GSTIN+SEZ/DE → B2B review |
| **EXP** | Export-like (``EXPORT`` / POS 96–97 / shipping / export raw) and **not** CN/DN/NIL/ADVANCES; SEZ+GSTIN → B2B review peel (not EXP Save) |
| **B2CS / B2CL** | ``_is_b2c_candidate`` (B2C* or non-non-B2C without valid GSTIN) |
| **unclassified** | Anything left → orchestrator ``pending_review`` (``unclassified_sr_row``) — closes the leak |

Overlap notes
-------------
- EXPORT+GSTIN+SEZ: B2B peels to review; EXP input excludes those claimed rows
  so the same SR line is never dual-pended.
- CREDIT_NOTE never enters NIL or EXP Save.
- NIL_RATED never enters HSN.
- B2B/B2C/EXPORT/CN/DN may also feed HSN (dual reporting by design; primary
  disposition ignores HSN pending/external so exclusive accounting holds).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.filing.gstr1_external_input import FilingDataGaps, NeedsExternalInput
from app.filing.gstr1_filing_mapper import (
    PendingReviewInvoice,
    apply_b2cs_netting,
    map_sales_register_to_gstr1_at_txpd,
    map_sales_register_to_gstr1_b2b,
    map_sales_register_to_gstr1_b2cl,
    map_sales_register_to_gstr1_b2cs,
    map_sales_register_to_gstr1_cdnr,
    map_sales_register_to_gstr1_cdnur,
    map_sales_register_to_gstr1_doc_issue,
    map_sales_register_to_gstr1_exp,
    map_sales_register_to_gstr1_hsn,
    map_sales_register_to_gstr1_nil,
    resolve_nil_amount_column_from_sr_raw,
    _counterparty_gstin_ok,
    _coalesce_str,
    _gstn_finalize_amounts,
    _is_advances_class_row,
    _is_b2c_candidate,
    _looks_like_exp_invoice,
    _looks_like_sez_or_deemed,
)


DISPOSITION_SAVED = "saved"
DISPOSITION_PENDING = "pending_review"
DISPOSITION_EXTERNAL = "external_input"
DISPOSITION_SKIPPED = "skipped"


@dataclass
class FilingReadiness:
    """Whether the period can be Saved / Filed on GSTN right now."""

    can_save: bool
    can_file: bool
    save_blockers: list[str] = field(default_factory=list)
    file_blockers: list[str] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class RowAccounting:
    """Primary-lane disposition counts (mutually exclusive, sum == total_rows)."""

    total_rows: int = 0
    saved: int = 0
    pending_review: int = 0
    external_input: int = 0
    skipped: int = 0
    by_lane: dict[str, int] = field(default_factory=dict)
    dispositions: list[str] = field(default_factory=list)  # parallel to records

    @property
    def sums_to_total(self) -> bool:
        return (
            self.saved
            + self.pending_review
            + self.external_input
            + self.skipped
        ) == self.total_rows


@dataclass
class Gstr1FilingMapResult:
    """One coherent filing-period result from all table mappers."""

    save_payload: dict[str, Any] = field(default_factory=dict)
    pending_review: list[PendingReviewInvoice] = field(default_factory=list)
    external_input_gaps: FilingDataGaps = field(default_factory=FilingDataGaps)
    filing_readiness: FilingReadiness = field(
        default_factory=lambda: FilingReadiness(can_save=False, can_file=False)
    )
    row_accounting: RowAccounting = field(default_factory=RowAccounting)
    filer_state: str = ""
    filing_period: str = ""

    @property
    def pending_count(self) -> int:
        return len(self.pending_review)


def map_sales_register_to_gstr1(
    records: list[dict[str, Any]],
    *,
    filer_state: str,
    filing_period: str,
) -> Gstr1FilingMapResult:
    """Run all GSTR-1 mappers in hand-off order; return one consolidated result.

    Order: B2B → B2CS → B2CL → CDNR → CDNUR → B2CS-netting → EXP → HSN → NIL
    → AT/TXPD → DOC_ISSUE (from outward Save counts).
    """
    rows = [r for r in records if isinstance(r, dict)]
    result = Gstr1FilingMapResult(
        filer_state=filer_state,
        filing_period=filing_period,
    )

    # --- Primary invoice / note tables (hand-off chain) ---
    b2b = map_sales_register_to_gstr1_b2b(rows)
    b2cs = map_sales_register_to_gstr1_b2cs(
        rows, filer_state=filer_state, filing_period=filing_period,
    )
    b2cl = map_sales_register_to_gstr1_b2cl(
        b2cs.b2cl_candidates, filer_state=filer_state,
    )
    cdnr = map_sales_register_to_gstr1_cdnr(rows, filer_state=filer_state)
    cdnur = map_sales_register_to_gstr1_cdnur(
        cdnr.cdnur_candidates,
        filer_state=filer_state,
        filing_period=filing_period,
    )
    b2cs_netted = apply_b2cs_netting(
        b2cs.b2cs, cdnur.b2cs_net_candidates, filer_state=filer_state,
    )

    # EXP must not re-claim rows B2B already peeled (SEZ/DE → B2B review).
    b2b_claimed_ids = {id(p.record) for p in b2b.pending_review}
    exp_rows = [r for r in rows if id(r) not in b2b_claimed_ids]
    exp = map_sales_register_to_gstr1_exp(exp_rows)

    # --- Summary / envelope tables ---
    hsn = map_sales_register_to_gstr1_hsn(rows, filing_period=filing_period)
    nil = map_sales_register_to_gstr1_nil(
        rows, filer_state=filer_state, filing_period=filing_period,
    )
    at_txpd = map_sales_register_to_gstr1_at_txpd(
        rows, filing_period=filing_period,
    )

    b2b_count = b2b.save_invoice_count
    b2cs_bucket_count = len(b2cs_netted.b2cs)
    b2cl_count = b2cl.save_invoice_count
    cdnr_count = cdnr.save_note_count
    cdnur_count = cdnur.save_note_count
    exp_count = exp.save_invoice_count

    doc_issue = map_sales_register_to_gstr1_doc_issue(
        filing_period=filing_period,
        b2b_save_count=b2b_count,
        b2cs_save_count=b2cs_bucket_count,
        b2cl_save_count=b2cl_count,
        cdnr_save_count=cdnr_count,
        cdnur_save_count=cdnur_count,
        exp_save_count=exp_count,
    )

    # Primary pending (drives exclusive row accounting). HSN pending is
    # parallel — same row may Save on B2B and still need HSN review.
    primary_pending: list[PendingReviewInvoice] = []
    primary_pending.extend(b2b.pending_review)
    primary_pending.extend(b2cs.pending_review)
    primary_pending.extend(b2cl.pending_review)
    primary_pending.extend(cdnr.pending_review)
    primary_pending.extend(cdnur.pending_review)
    primary_pending.extend(b2cs_netted.pending_review)
    primary_pending.extend(exp.pending_review)
    primary_pending.extend(nil.pending_review)

    # --- Row accounting (primary lane, exclusive) ---
    accounting, unclassified = _account_primary_rows(
        rows,
        primary_pending=primary_pending,
        b2cl_candidates=b2cs.b2cl_candidates,
        cdnur_candidates=cdnr.cdnur_candidates,
        b2cs_net_candidates=cdnur.b2cs_net_candidates,
        nil_blocked=nil.needs_external_input is not None,
        nil_saved=bool(nil.nil and nil.save_row_count > 0),
        at_blocked=bool(at_txpd.needs_external_input),
    )

    # Flat pending for UX: primary + HSN + orchestrator unclassified
    pending: list[PendingReviewInvoice] = list(primary_pending)
    pending.extend(hsn.pending_review)
    pending.extend(unclassified)

    # --- External gaps ---
    gaps = FilingDataGaps()
    if hsn.needs_external_input is not None:
        gaps.add(hsn.needs_external_input)
    if nil.needs_external_input is not None:
        gaps.add(nil.needs_external_input)
    if doc_issue.needs_external_input is not None:
        gaps.add(doc_issue.needs_external_input)
    for g in at_txpd.needs_external_input:
        gaps.add(g)

    # --- Save payload (omit empty / blocked sections) ---
    payload: dict[str, Any] = {}
    if b2b.b2b:
        payload["b2b"] = b2b.b2b
    if b2cs_netted.b2cs:
        payload["b2cs"] = b2cs_netted.b2cs
    if b2cl.b2cl:
        payload["b2cl"] = b2cl.b2cl
    if cdnr.cdnr:
        payload["cdnr"] = cdnr.cdnr
    if cdnur.cdnur:
        payload["cdnur"] = cdnur.cdnur
    if exp.exp:
        payload["exp"] = exp.exp
    if hsn.needs_external_input is None and hsn.save_row_count > 0:
        payload["hsn"] = hsn.hsn
    if nil.needs_external_input is None and nil.nil is not None:
        payload["nil"] = nil.nil
    # doc_issue / at / txpd: never invent — omitted when external

    result.save_payload = _gstn_finalize_amounts(payload)
    result.pending_review = pending
    result.external_input_gaps = gaps
    result.row_accounting = accounting
    result.filing_readiness = _compute_filing_readiness(
        payload=result.save_payload,
        gaps=gaps,
        b2b_count=b2b_count,
        pending_count=len(pending),
    )
    return result


def _gstin_ok(rec: dict[str, Any]) -> bool:
    """Checksum-valid counterparty GSTIN (not format-regex alone)."""
    return _counterparty_gstin_ok(rec)


def _primary_lane(rec: dict[str, Any]) -> str:
    """First-match primary lane for exclusive row accounting."""
    derived = str(rec.get("invoice_type") or "").strip().upper()
    gstin_ok = _gstin_ok(rec)
    type_raw = _coalesce_str(rec.get("invoice_type_raw"))
    export_raw = _coalesce_str(rec.get("export_type_raw"), rec.get("export_type"))

    if derived in {"CREDIT_NOTE", "DEBIT_NOTE"}:
        return "cdn"
    _col, nil_reason = resolve_nil_amount_column_from_sr_raw(
        invoice_type=derived, invoice_type_raw=type_raw,
    )
    if nil_reason != "not_nil_class":
        return "nil"
    if _is_advances_class_row(rec):
        return "advances"
    if derived == "B2B" and gstin_ok:
        return "b2b"
    if derived == "EXPORT" and gstin_ok and _looks_like_sez_or_deemed(
        type_raw, export_raw,
    ):
        return "b2b"  # SEZ peel owned by B2B review lane
    if derived not in {
        "CREDIT_NOTE", "DEBIT_NOTE", "NIL_RATED", "ADVANCES", "HSN_SUMMARY",
    } and _looks_like_exp_invoice(rec):
        if gstin_ok and _looks_like_sez_or_deemed(type_raw, export_raw):
            return "b2b"
        return "exp"
    if _is_b2c_candidate(rec):
        return "b2cs"
    if derived == "B2B":
        return "b2b"  # invalid GSTIN → skipped_non_b2b
    return "unclassified"


def _account_primary_rows(
    rows: list[dict[str, Any]],
    *,
    primary_pending: list[PendingReviewInvoice],
    b2cl_candidates: list[dict[str, Any]],
    cdnur_candidates: list[dict[str, Any]],
    b2cs_net_candidates: list[Any],
    nil_blocked: bool,
    nil_saved: bool,
    at_blocked: bool,
) -> tuple[RowAccounting, list[PendingReviewInvoice]]:
    pending_ids = {id(p.record) for p in primary_pending}
    b2cl_ids = {id(r) for r in b2cl_candidates}
    cdnur_ids = {id(r) for r in cdnur_candidates}
    net_ids = {id(c.record) for c in b2cs_net_candidates}

    accounting = RowAccounting(total_rows=len(rows))
    unclassified_pending: list[PendingReviewInvoice] = []

    for rec in rows:
        rid = id(rec)
        lane = _primary_lane(rec)
        accounting.by_lane[lane] = accounting.by_lane.get(lane, 0) + 1
        derived = str(rec.get("invoice_type") or "").strip().upper()

        if rid in pending_ids:
            disp = DISPOSITION_PENDING
        elif lane == "nil":
            if nil_blocked:
                disp = DISPOSITION_EXTERNAL
            elif nil_saved:
                disp = DISPOSITION_SAVED
            else:
                # Omitted nil (ambiguous-only period, or all field holds)
                disp = DISPOSITION_SKIPPED
        elif lane == "advances":
            disp = DISPOSITION_EXTERNAL if at_blocked else DISPOSITION_SKIPPED
        elif lane == "unclassified":
            unclassified_pending.append(
                PendingReviewInvoice(
                    record=rec,
                    proposed_inv_typ=None,
                    reason="unclassified_sr_row",
                    suggested_table="orchestrator",
                )
            )
            disp = DISPOSITION_PENDING
        elif lane == "b2b":
            if derived == "B2B" and _gstin_ok(rec):
                disp = DISPOSITION_SAVED
            elif derived == "EXPORT":
                # Should already be in pending_ids via B2B peel
                disp = DISPOSITION_PENDING
            else:
                # B2B label without valid GSTIN → mapper skipped_non_b2b
                disp = DISPOSITION_SKIPPED
        elif lane == "cdn":
            if rid in cdnur_ids:
                if rid in net_ids:
                    disp = DISPOSITION_SAVED
                else:
                    disp = DISPOSITION_SAVED  # CDNUR Save
            else:
                disp = DISPOSITION_SAVED  # CDNR Save
        elif lane == "b2cs":
            disp = DISPOSITION_SAVED  # B2CS aggregate or B2CL Save
            if rid in b2cl_ids:
                disp = DISPOSITION_SAVED
        elif lane == "exp":
            disp = DISPOSITION_SAVED
        else:
            disp = DISPOSITION_SKIPPED

        if rid in pending_ids:
            disp = DISPOSITION_PENDING

        accounting.dispositions.append(disp)
        if disp == DISPOSITION_SAVED:
            accounting.saved += 1
        elif disp == DISPOSITION_PENDING:
            accounting.pending_review += 1
        elif disp == DISPOSITION_EXTERNAL:
            accounting.external_input += 1
        else:
            accounting.skipped += 1

    return accounting, unclassified_pending


def _compute_filing_readiness(
    *,
    payload: dict[str, Any],
    gaps: FilingDataGaps,
    b2b_count: int,
    pending_count: int,
) -> FilingReadiness:
    gap_tables = gaps.tables_blocked()
    has_outward = any(
        k in payload for k in ("b2b", "b2cs", "b2cl", "cdnr", "cdnur", "exp")
    )

    save_blockers: list[str] = []
    # Save is allowed with omitted HSN/DOC/AT/NIL. Pending review does not
    # block Save of clear rows.
    can_save = True

    file_blockers: list[str] = []
    advisory: list[str] = []

    if has_outward and "doc_issue" in gap_tables:
        file_blockers.append(
            "Table 13 (Documents Issued) missing — GSTN blocks File when "
            "B2B/B2C supplies exist (May 2025+)."
        )
    if b2b_count > 0 and "hsn" in gap_tables:
        file_blockers.append(
            "Table 12 HSN B2B missing — GSTN blocks File when B2B supplies "
            "exist and HSN B2B tab is empty."
        )
    if "nil" in gap_tables:
        advisory.append(
            "Table 8 NIL incomplete (lump nil/exempt/non-GST) — advisory; "
            "does not hard-block File."
        )
    if "at" in gap_tables or "txpd" in gap_tables:
        advisory.append(
            "Table 11 AT/TXPD needs an advances schedule — advisory unless "
            "you have advances to report."
        )
    if pending_count:
        advisory.append(
            f"{pending_count} row(s) in pending_review — excluded from Save; "
            "resolve before they belong in the filed return."
        )
    if not has_outward and not payload:
        advisory.append("No outward Save sections produced for this period.")

    can_file = can_save and not file_blockers and has_outward

    if can_file:
        summary = "Save-able and File-able (no hard GSTN Table 12/13 blockers)."
    elif can_save and file_blockers:
        summary = (
            "Save-able now (omit HSN/DOC from payload), but not File-able "
            "until hard-mandatory gaps close: "
            + "; ".join(file_blockers)
        )
    elif can_save:
        summary = "Save-able; no outward supplies to File yet."
    else:
        summary = "Not Save-able: " + "; ".join(save_blockers)

    return FilingReadiness(
        can_save=can_save,
        can_file=can_file,
        save_blockers=save_blockers,
        file_blockers=file_blockers,
        advisory=advisory,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# API serialization (readiness / save responses)
# ---------------------------------------------------------------------------

_PENDING_CONTEXT_KEYS = (
    "row_number",
    "invoice_number",
    "invoice_number_raw",
    "invoice_number_normalized",
    "invoice_date",
    "gstin",
    "place_of_supply",
    "invoice_type",
    "invoice_type_raw",
    "export_type_raw",
    "note_type",
    "note_type_raw",
    "taxable_amount_paise",
    "igst_paise",
    "cgst_paise",
    "sgst_paise",
    "cess_paise",
    "total_tax_paise",
    "total_amount_paise",
    "tax_rate",
)


def _decision_needed_for_pending(item: PendingReviewInvoice) -> str:
    """What the CA must choose — worded for UI grouping, not GSTN codes alone."""
    table = (item.suggested_table or "").lower()
    reason = (item.reason or "").lower()
    if table in ("cdnr", "cdnur") or "ntty" in reason:
        return "ntty"
    if table == "exp" or "exp_typ" in reason:
        return "exp_typ"
    if "unclassified" in reason or table in ("", "unclassified"):
        return "table_classification"
    return "inv_typ"


def serialize_pending_review_item(item: PendingReviewInvoice) -> dict[str, Any]:
    rec = item.record if isinstance(item.record, dict) else {}
    context = {k: rec.get(k) for k in _PENDING_CONTEXT_KEYS if k in rec}
    return {
        "suggested_table": item.suggested_table,
        "reason": item.reason,
        "proposed_inv_typ": item.proposed_inv_typ,
        "decision_needed": _decision_needed_for_pending(item),
        "context": context,
    }


def serialize_external_input_gap(gap: NeedsExternalInput) -> dict[str, Any]:
    return {
        "table": gap.table,
        "filing_period": gap.filing_period,
        "reason": gap.reason,
        "message": gap.message,
        "missing_fields": list(gap.missing_fields),
        # Hard-blocks File when Table 12 HSN-B2B or Table 13 DOC are missing
        # with outward supplies; NIL/AT/TXPD stay advisory in readiness.
        "blocks_file": gap.table in ("hsn", "doc_issue"),
    }


def serialize_filing_readiness(fr: FilingReadiness) -> dict[str, Any]:
    return {
        "can_save": fr.can_save,
        "can_file": fr.can_file,
        "summary": fr.summary,
        "save_blockers": list(fr.save_blockers),
        "file_blockers": list(fr.file_blockers),
        "advisory": list(fr.advisory),
    }


def serialize_gstr1_readiness(mapped: Gstr1FilingMapResult) -> dict[str, Any]:
    """Full readiness payload for the CA pre-Save review UI."""
    gaps = [
        serialize_external_input_gap(g)
        for g in mapped.external_input_gaps.needs_external_input
    ]
    pending = [serialize_pending_review_item(p) for p in mapped.pending_review]
    by_table: dict[str, list[dict[str, Any]]] = {}
    for p in pending:
        by_table.setdefault(p["suggested_table"] or "unclassified", []).append(p)

    return {
        "filing_period": mapped.filing_period,
        "filer_state": mapped.filer_state,
        "filing_readiness": serialize_filing_readiness(mapped.filing_readiness),
        "pending_review": pending,
        "pending_review_by_table": by_table,
        "pending_review_count": len(pending),
        "external_input_gaps": gaps,
        "external_input_tables": sorted(
            mapped.external_input_gaps.tables_blocked()
        ),
        "save_section_keys": sorted(mapped.save_payload.keys()),
        "row_accounting": {
            "total_rows": mapped.row_accounting.total_rows,
            "saved": mapped.row_accounting.saved,
            "pending_review": mapped.row_accounting.pending_review,
            "external_input": mapped.row_accounting.external_input,
            "skipped": mapped.row_accounting.skipped,
            "by_lane": dict(mapped.row_accounting.by_lane),
        },
    }
