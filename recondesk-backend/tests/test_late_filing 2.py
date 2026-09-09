import pytest
from datetime import date
from app.services.late_filing_tracker import check_late_filing

def test_late_filing_tracker():
    matched_records = [
        {
            "gstr_id": "g1",
            "pr_id": "p1",
            "supplier_gstin": "27AAAAA0000A1Z5",
            "invoice_number_normalized": "INV001",
            "taxable_amount_paise": 10000,
            "igst_paise": 1800,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
        {
            "gstr_id": "g2",
            "pr_id": "p2",
            "supplier_gstin": "27BBBBB0000B1Z5",
            "invoice_number_normalized": "INV002",
            "taxable_amount_paise": 20000,
            "igst_paise": 3600,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
    ]

    gstr_raw_by_id = {
        "g1": {
            "supprd": "042026",
            "supfildt": "15-05-2026",  # Late! Due date is May 11
        },
        "g2": {
            "supprd": "042026",
            "supfildt": "10-05-2026",  # On-time! Due date is May 11
        }
    }

    claim_period = "2026-04"

    results = check_late_filing(matched_records, gstr_raw_by_id, claim_period)

    assert len(results) == 1
    
    # Check late filed supplier
    assert results[0]["gstr_id"] == "g1"
    assert results[0]["status"] == "LATE_FILING"
    assert results[0]["amount_paise"] == 10000
    assert results[0]["itc_at_risk_paise"] == 1800
