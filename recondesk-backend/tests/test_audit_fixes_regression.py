import pytest
from app.services.matcher import is_invoice_format_variant
from app.services.reconciliation import _peer_pr_invoice_clone_ok

def test_leading_digit_prefix_format_variant_rejected():
    """2BONLY/26/00080 vs TYPO/26/00002 must NOT be treated as format variants.
    
    The digit '2' in '2BONLY' is part of the alphanumeric prefix, not an isolated
    invoice serial that can match '00002'.
    """
    assert not is_invoice_format_variant("2BONLY/26/00080", "TYPO/26/00002")
    assert not is_invoice_format_variant("2BONLY2600080", "TYPO2600002")

def test_pr_peer_clone_sequential_invoices_not_duplicate():
    """Sequential unlinked PR invoices must not collapse into Duplicate Entry."""
    ok, _ = _peer_pr_invoice_clone_ok("PRONLY2600092", "PRONLY2600272")
    assert not ok
    
    ok, _ = _peer_pr_invoice_clone_ok("PRONLY2600242", "PRONLY2600272")
    assert not ok

    ok, _ = _peer_pr_invoice_clone_ok("SIM2610047", "SIM2610093")
    assert not ok

def test_pr_peer_clone_true_clones_preserved():
    """Identical invoice numbers, format variants, and mangled prefix clones remain supported."""
    # Exact normalized
    ok, sim = _peer_pr_invoice_clone_ok("INV100", "INV100")
    assert ok and sim == 1.0

    # Format variant
    ok, sim = _peer_pr_invoice_clone_ok("DS-2026-00078", "DS/26/78")
    assert ok and sim == 1.0

    # Mangled prefix typo with identical numeric core
    ok, sim = _peer_pr_invoice_clone_ok("INV455325", "NIV455325")
    assert ok and sim >= 0.75

def test_subsequence_numeric_mismatch_not_format_variant():
    """Digits embedded as subsequences (e.g. RISK0 vs RISK10, INV1 vs INV10) are NOT format variants."""
    assert not is_invoice_format_variant("RISK0", "RISK10")
    assert not is_invoice_format_variant("INV1", "INV10")
    assert not is_invoice_format_variant("INV1", "INV11")
    ok, _ = _peer_pr_invoice_clone_ok("RISK0", "RISK10")
    assert not ok

def test_prefix_abbreviation_format_variant():
    """Prefix abbreviations like FZ/2026/03763 vs F3763 must remain supported."""
    assert is_invoice_format_variant("FZ/2026/03763", "F3763", "FZ/2026/03763", "F3763")
    assert is_invoice_format_variant("FZ20263763", "F3763", "FZ/2026/03763", "F3763")


def test_cross_gstin_cannot_steal_pr_with_same_gstin_candidate():
    """A cross-GSTIN match (GSTIN_MISMATCH) must not steal a PR record if that PR
    has an unconsumed same-GSTIN GSTR counterpart (exact, format variant, or typo match).
    """
    from datetime import date
    from collections import defaultdict
    from app.services.reconciliation import (
        _pr_has_stronger_same_gstin_gstr_candidate,
        execute_phase2_and_3,
        build_pr_candidate_indices,
        ReconState,
    )

    # Supplier A: PR invoice TYPO2600116, GSTR invoice TYPO2600113 (valid typo match)
    gstin_a = "27ABCPD5678G1Z2"
    gstin_b = "27AATCS4521P1Z8"

    pr_a = {
        "id": "pr_a_1",
        "supplier_gstin": gstin_a,
        "invoice_number": "TYPO/26/00116",
        "invoice_number_normalized": "TYPO2600116",
        "invoice_date": date(2026, 8, 10),
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }

    gstr_a = {
        "id": "gstr_a_1",
        "supplier_gstin": gstin_a,
        "invoice_number": "TYPO/26/00113",
        "invoice_number_normalized": "TYPO2600113",
        "invoice_date": date(2026, 8, 16),
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }

    # Supplier B: GSTR invoice TYPO2600116 (happens to share invoice number with PR of Supplier A)
    gstr_b = {
        "id": "gstr_b_1",
        "supplier_gstin": gstin_b,
        "invoice_number": "TYPO/26/00116",
        "invoice_number_normalized": "TYPO2600116",
        "invoice_date": date(2026, 8, 10),
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }

    # Verify helper detects the stronger same-GSTIN partner
    unconsumed_by_gstin = defaultdict(list)
    unconsumed_by_gstin[gstin_a].append(gstr_a)
    unconsumed_by_gstin[gstin_b].append(gstr_b)

    assert _pr_has_stronger_same_gstin_gstr_candidate(pr_a, unconsumed_by_gstin, set())

    # Full pipeline verification:
    # Process gstr_b FIRST (the order that previously caused theft)
    gstr_records = [gstr_b, gstr_a]
    pr_records = [pr_a]

    state = ReconState()
    pr_index = {gstin_a: [pr_a]}
    candidate_indices = build_pr_candidate_indices(pr_index)

    execute_phase2_and_3(gstr_records, pr_records, state, candidate_indices)

    # gstr_b must NOT have stolen pr_a
    # gstr_a should have matched pr_a as TYPO_MISMATCH
    matched_pr_ids = {str(r.get("pr_id")) for r in state.review_required}
    assert "pr_a_1" in matched_pr_ids

    review_match = [r for r in state.review_required if str(r.get("pr_id")) == "pr_a_1"][0]
    assert review_match["gstr_id"] == "gstr_a_1"
    assert review_match["review_reason"] == "TYPO_MISMATCH"
    assert "gstr_b_1" in [str(m.get("gstr_id")) for m in state.missed_itc]


def test_legitimate_cross_gstin_mismatch_preserved():
    """Legitimate GSTIN_MISMATCH continues to work when the PR record has no
    unconsumed same-GSTIN GSTR counterpart.
    """
    from datetime import date
    from app.services.reconciliation import (
        execute_phase2_and_3,
        build_pr_candidate_indices,
        ReconState,
    )

    gstin_gstr = "27AATCS4521P1Z8"
    gstin_pr = "27ABCPD5678G1Z2"

    pr_rec = {
        "id": "pr_1",
        "supplier_gstin": gstin_pr,
        "invoice_number": "INV-2026-9999",
        "invoice_number_normalized": "INV20269999",
        "invoice_date": date(2026, 8, 10),
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }

    gstr_rec = {
        "id": "gstr_1",
        "supplier_gstin": gstin_gstr,
        "invoice_number": "INV-2026-9999",
        "invoice_number_normalized": "INV20269999",
        "invoice_date": date(2026, 8, 10),
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }

    state = ReconState()
    pr_index = {gstin_pr: [pr_rec]}
    candidate_indices = build_pr_candidate_indices(pr_index)

    execute_phase2_and_3([gstr_rec], [pr_rec], state, candidate_indices)

    assert len(state.review_required) == 1
    assert state.review_required[0]["gstr_id"] == "gstr_1"
    assert state.review_required[0]["pr_id"] == "pr_1"
    assert state.review_required[0]["review_reason"] == "GSTIN_MISMATCH"

