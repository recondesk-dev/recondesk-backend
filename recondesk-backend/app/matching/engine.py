"""Public entry for the bidirectional engine (used by workers and tests)."""
import datetime

from app.services.reconciliation import (  # noqa: F401
    ReconState,
    build_wrongful_itc_risk,
    prepass_duplicate_ambiguity,
    resolve_orphans,
    process_gstr_records_chunk,
    execute_phase2_and_3,
    flag_fuzzy_duplicates_of_linked_prs,
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
    state = ReconState()
    if gstr_period is None:
        gstr_period = _infer_gstr_period(gstr_records)

    pr_index = {}
    for p in pr_records:
        g = str(p.get("supplier_gstin") or "").strip()
        if g:
            pr_index.setdefault(g, []).append(p)
            
    pr_by_invoice = build_pr_by_invoice(pr_index)
    gstr_by_invoice = build_gstr_by_invoice(gstr_records)
    pr_index_by_period = _build_pr_index_by_period({gstr_period: pr_records})
            
    candidate_indices = build_pr_candidate_indices(pr_index)

    prepass_duplicate_ambiguity(gstr_records, pr_records, state)

    process_gstr_records_chunk(
        gstr_records,
        gstr_period,
        pr_index,
        pr_index_by_period,
        state,
        gstr_by_invoice=gstr_by_invoice,
        pr_by_invoice=pr_by_invoice,
        candidate_indices=candidate_indices,
    )

    execute_phase2_and_3(
        gstr_records,
        pr_records,
        state,
        candidate_indices,
    )

    return _finalize_reconciliation_result(
        state,
        len(gstr_records),
        len(pr_records),
        pr_records,
        gstr_records
    )

__all__ = [
    "ReconState",
    "build_wrongful_itc_risk",
    "prepass_duplicate_ambiguity",
    "process_gstr_records_chunk",
    "run_bidirectional_reconciliation",
    "flag_fuzzy_duplicates_of_linked_prs",
]
