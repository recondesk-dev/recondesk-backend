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

