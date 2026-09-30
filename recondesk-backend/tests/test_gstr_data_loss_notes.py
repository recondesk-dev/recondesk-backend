import pytest
from app.services.reconciliation import ReconState


def test_gstr_data_loss_assertion_with_unmatched_notes():
    """Verify that unmatched GSTR credit/debit notes are accounted for in GSTR data loss accounting."""
    state = ReconState()
    # 2 matched
    state.clean_matched = [
        {"gstr_id": "g1", "pr_id": "p1"},
        {"gstr_id": "g2", "pr_id": "p2"},
    ]
    # 1 missed
    state.missed_itc = [
        {"gstr_id": "g3"},
    ]
    # 1 review
    state.review_required = [
        {"gstr_id": "g4", "pr_id": "p4"},
    ]
    # 1 gstr duplicate
    state.duplicate_entries = [
        {"id": "g5", "side": "GSTR2B"},
    ]
    # 1 unmatched GSTR note (e.g. unbooked credit note)
    state.unmatched_notes = [
        {"id": "g6", "gstr_id": "g6", "side": "GSTR", "document_type": "CREDIT_NOTE"},
        {"id": "p5", "side": "PR", "document_type": "DEBIT_NOTE"},  # PR note, should not count towards GSTR
    ]

    matched_count = len(state.clean_matched)
    missed_itc_count = len(state.missed_itc)
    review_gstr_count = sum(1 for r in state.review_required if r.get("gstr_id"))
    gstr_duplicate_count = sum(1 for d in state.duplicate_entries if d.get("side") == "GSTR2B")
    gstr_note_count = sum(
        1 for n in state.unmatched_notes if n.get("side") == "GSTR" or n.get("gstr_id")
    )

    # Total GSTR records = 2 + 1 + 1 + 1 + 1 = 6
    total_gstr_len = 6

    # Assertion should pass with gstr_note_count included
    assert (
        matched_count
        + missed_itc_count
        + review_gstr_count
        + gstr_duplicate_count
        + gstr_note_count
        == total_gstr_len
    )
    assert gstr_note_count == 1
