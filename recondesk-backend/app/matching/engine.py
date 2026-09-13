"""Public entry for the bidirectional engine (used by workers and tests)."""
import datetime

from app.services.amendment_handler import build_effective_gstr_records
from app.services.reconciliation import (  # noqa: F401
    ReconState,
    build_wrongful_itc_risk,
    prepass_duplicate_ambiguity,
    resolve_orphans,
    process_gstr_records_chunk,
    execute_phase2_and_3,
    flag_fuzzy_duplicates_of_linked_prs,
    flag_fuzzy_pr_peer_duplicates,
    quarantine_pr_notes,
    _finalize_reconciliation_result,
    build_pr_candidate_indices,
    build_pr_by_invoice,
    build_gstr_by_invoice,
    _build_pr_index_by_period,
    _infer_gstr_period
)

def run_bidirectional_reconciliation(
    gstr_records: list[dict],
    pr_records: list[dict],
    gstr_period: datetime.date | None = None,
) -> dict:
    """Wrapper that runs the full 3-phase matching engine for testing and legacy scripts."""
    # Resolve GSTR-2B amendments into effective records
    amendment_res = build_effective_gstr_records(gstr_records)
    effective_gstr = amendment_res.effective_records

    state = ReconState()
    if gstr_period is None:
        gstr_period = _infer_gstr_period(effective_gstr)

    # Quarantine credit/debit note rows before any invoice matching.
    invoice_prs = quarantine_pr_notes(state, pr_records)

    pr_index = {}
    for p in invoice_prs:
        g = str(p.get("supplier_gstin") or "").strip()
        if g:
            pr_index.setdefault(g, []).append(p)
            
    pr_by_invoice = build_pr_by_invoice(pr_index)
    gstr_by_invoice = build_gstr_by_invoice(effective_gstr)
    pr_index_by_period = _build_pr_index_by_period({gstr_period: invoice_prs})
            
    candidate_indices = build_pr_candidate_indices(pr_index)

    prepass_duplicate_ambiguity(effective_gstr, invoice_prs, state)

    process_gstr_records_chunk(
        effective_gstr,
        gstr_period,
        pr_index,
        pr_index_by_period,
        state,
        gstr_by_invoice=gstr_by_invoice,
        pr_by_invoice=pr_by_invoice,
        candidate_indices=candidate_indices,
    )

    execute_phase2_and_3(
        effective_gstr,
        invoice_prs,
        state,
        candidate_indices,
    )

    return _finalize_reconciliation_result(
        state,
        len(effective_gstr),
        len(pr_records),
        # Pass full PR list so finalize can still see quarantined ids as consumed
        # (already in state.consumed_pr_ids) and not double-count them as risk.
        # Invoice-only list is enough for wrongful risk since notes are consumed.
        invoice_prs,
        effective_gstr
    )

__all__ = [
    "ReconState",
    "build_wrongful_itc_risk",
    "prepass_duplicate_ambiguity",
    "process_gstr_records_chunk",
    "run_bidirectional_reconciliation",
    "flag_fuzzy_duplicates_of_linked_prs",
    "flag_fuzzy_pr_peer_duplicates",
    "quarantine_pr_notes",
]
