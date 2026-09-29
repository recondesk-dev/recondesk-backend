"""Public entry for the bidirectional engine (used by workers and tests)."""
import datetime

from app.services.amendment_handler import build_effective_gstr_records
from app.services.reconciliation import (  # noqa: F401
    ReconState,
    build_wrongful_itc_risk,
    prepass_gstr2b_duplicates,
    prepass_duplicate_ambiguity,
    resolve_orphans,
    process_gstr_records_chunk,
    execute_credit_note_reconciliation,
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
    elif isinstance(gstr_period, str):
        try:
            if len(gstr_period) == 6 and gstr_period.isdigit():
                # MMYYYY format (e.g. 092023)
                month = int(gstr_period[:2])
                year = int(gstr_period[2:])
                gstr_period = datetime.date(year, month, 1)
            else:
                d = datetime.date.fromisoformat(gstr_period)
                gstr_period = datetime.date(d.year, d.month, 1)
        except Exception:
            gstr_period = _infer_gstr_period(effective_gstr)

    pr_index = {}
    for p in pr_records:
        g = str(p.get("supplier_gstin") or "").strip()
        if g:
            pr_index.setdefault(g, []).append(p)
            
    pr_by_invoice = build_pr_by_invoice(pr_index)
    gstr_by_invoice = build_gstr_by_invoice(effective_gstr)
    pr_index_by_period = _build_pr_index_by_period({gstr_period: pr_records})
            
    candidate_indices = build_pr_candidate_indices(pr_index)

    prepass_gstr2b_duplicates(effective_gstr, state)
    prepass_duplicate_ambiguity(effective_gstr, pr_records, state)


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

    # Dedicated bilateral Credit Note (CDNR) & Debit Note reconciliation phase
    execute_credit_note_reconciliation(
        effective_gstr,
        pr_records,
        state,
    )

    execute_phase2_and_3(
        effective_gstr,
        pr_records,
        state,
        candidate_indices,
    )

    # Residual quarantine: any PR note rows that remained unconsumed after matching
    quarantine_pr_notes(state, pr_records)

    return _finalize_reconciliation_result(
        state,
        len(effective_gstr),
        len(pr_records),
        pr_records,
        effective_gstr,
    )

__all__ = [
    "ReconState",
    "build_wrongful_itc_risk",
    "prepass_duplicate_ambiguity",
    "process_gstr_records_chunk",
    "execute_credit_note_reconciliation",
    "run_bidirectional_reconciliation",
    "flag_fuzzy_duplicates_of_linked_prs",
    "flag_fuzzy_pr_peer_duplicates",
    "quarantine_pr_notes",
]
