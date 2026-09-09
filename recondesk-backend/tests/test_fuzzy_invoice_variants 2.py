import pytest

from app.services.matcher import is_invoice_format_variant, match_gstr_to_pr

def test_is_invoice_format_variant_conservative():
    # True format variants
    assert is_invoice_format_variant("DS-2026-00078", "DS/26/78")
    assert is_invoice_format_variant("INV 001", "INV001")
    assert is_invoice_format_variant("inv_001", "INV001")
    
    # Negative conservative cases
    assert not is_invoice_format_variant("INV1", "INX1")

def test_is_invoice_format_variant_fuzzy_numeric():
    # Should catch variants with completely different (or missing) prefix noise
    assert is_invoice_format_variant("INV-00001-26", "1")
    assert is_invoice_format_variant("INV-00001-26", "INV000001")
    
    # Negatives
    assert not is_invoice_format_variant("123", "456")
    assert not is_invoice_format_variant("INV001", "BILL002")

def test_matcher_l5_fuzzy_format_variant():
    gstr_rec = {
        "id": "1",
        "supplier_gstin": "27ABCDE1234F1Z0",
        "invoice_number": "1",
        "invoice_number_normalized": "1",
        "invoice_date": "2026-04-10",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }
    
    pr_rec = {
        "id": "2",
        "supplier_gstin": "27ABCDE1234F1Z0",
        "invoice_number": "INV-00001-26",
        "invoice_number_normalized": "INV0000126",
        "invoice_date": "2026-04-10",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }

    match_result = match_gstr_to_pr(gstr_rec, [pr_rec])
    
    assert match_result is not None
    assert match_result.matched is True
    # Zero-discrepancy format variants stay on Matched as L2 (non-exact), not L1.
    assert match_result.level == 2
    assert match_result.requires_human_review is False
