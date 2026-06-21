import pytest
import pytest
from datetime import date
from app.services.rule37_tracker import check_rule_37_compliance, build_payment_records_from_pr, OK

def test_partial_payment_no_date_is_proportional_obsolete():
    pr_rows = [{
        "id": "pr1",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }]
    pr_raw = {
        "pr1": {
            "payment_status": "partial",
            "amount_paid_paise": 59000,
            "payment_date": None
        }
    }
    
    payments = build_payment_records_from_pr(pr_rows, pr_raw)
    assert len(payments) == 1
    assert payments[0]["amount_paise"] == 59000
    assert payments[0]["payment_date"] is None
    
    # 59000 is exactly 50% of 118000 (100000 + 18000)
    # ITC at risk should be 50% of 18000 = 9000
    
    pr_records = [{
        "id": "pr1",
        "invoice_value_paise": 118000,
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "supplier_gstin": "27AAAAA0000A1Z5",
        "invoice_number_normalized": "INV01",
        "invoice_date": "2023-01-01"
    }]
    
    res = check_rule_37_compliance(pr_records, payments, today=date(2024, 2, 1))
    
    assert res[0]["unpaid_paise"] == 59000
    assert res[0]["itc_at_risk_paise"] == 9000
