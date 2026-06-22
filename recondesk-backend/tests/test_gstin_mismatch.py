import pytest
from app.services.reconciliation import resolve_orphans
from app.services.matcher import TOTAL_TOLERANCE_PAISE

def test_gstin_mismatch_resolution():
    # Setup test data where invoice number and amount match, but GSTIN has 1 char difference
    # GSTR-2B GSTIN: 27AAAAA0000A1Z5
    # PR GSTIN:      27AAAAA0000B1Z5 (1 character difference)
    
    missed_itc = [
        {
            "gstr_id": "g1",
            "supplier_gstin": "27AAAAA0000A1Z5",
            "invoice_number_normalized": "INV001",
            "taxable_amount_paise": 10000,
            "total_tax_paise": 1800,
        }
    ]
    
    wrongful_itc_risk = [
        {
            "id": "p1",
            "supplier_gstin": "27AAAAA0000B1Z5",
            "invoice_number_normalized": "INV001",
            "taxable_amount_paise": 10000,
            "total_tax_paise": 1800,
        }
    ]
    
    # Run resolve_orphans
    # matched, missed_itc, wrongful_itc_risk, gstr_by_id, pr_by_id
    matched_final, m_missed, m_wrongful, gstin_mismatch, review_required = resolve_orphans(
        matched=[],
        missed_itc=missed_itc,
        wrongful_itc_risk=wrongful_itc_risk,
        gstr_by_id={"g1": {"supplier_gstin": "27AAAAA0000A1Z5", "invoice_number_normalized": "INV001"}},
        pr_by_id={"p1": {"supplier_gstin": "27AAAAA0000B1Z5", "invoice_number_normalized": "INV001"}},
    )
    
    # Assertions
    assert len(m_missed) == 0, "Missed ITC should be empty (resolved)"
    assert len(m_wrongful) == 0, "Wrongful ITC should be empty (resolved)"
    assert len(gstin_mismatch) == 1, "Should identify exactly 1 GSTIN mismatch"
    assert len(review_required) == 0
    
    mismatch = gstin_mismatch[0]
    assert mismatch["gstr_id"] == "g1"
    assert mismatch["pr_id"] == "p1"
    assert mismatch["gstr_supplier_gstin"] == "27AAAAA0000A1Z5"
    assert mismatch["pr_supplier_gstin"] == "27AAAAA0000B1Z5"
    assert mismatch["reason"] == "GSTIN_MISMATCH"
