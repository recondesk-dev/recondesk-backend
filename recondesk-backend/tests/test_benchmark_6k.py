import pytest
from datetime import date
from app.services.reconciliation import process_gstr_records_chunk, ReconState
from app.services.matcher import normalize_invoice

def _gstr(id_, inv_num, inv_date, tax=1000):
    return {
        "id": id_,
        "supplier_gstin": "27AABCU9603R1ZX",
        "invoice_number": inv_num,
        "invoice_number_normalized": normalize_invoice(inv_num),
        "invoice_date": date.fromisoformat(inv_date),
        "taxable_amount_paise": tax * 100,
        "total_tax_paise": int(tax * 100 * 0.18),
        "cgst_paise": int(tax * 100 * 0.09),
        "sgst_paise": int(tax * 100 * 0.09),
        "igst_paise": 0,
    }

def _pr(id_, inv_num, inv_date, tax=1000):
    return {
        "id": id_,
        "supplier_gstin": "27AABCU9603R1ZX",
        "invoice_number": inv_num,
        "invoice_number_normalized": normalize_invoice(inv_num),
        "invoice_date": date.fromisoformat(inv_date),
        "taxable_amount_paise": tax * 100,
        "total_tax_paise": int(tax * 100 * 0.18),
        "cgst_paise": int(tax * 100 * 0.09),
        "sgst_paise": int(tax * 100 * 0.09),
        "igst_paise": 0,
    }

def test_6k_benchmark_classification():
    gstr_records = []
    pr_records = []
    
    # 1. Clean Matched: 4,200
    for i in range(4200):
        gstr_records.append(_gstr(f"g_clean_{i}", f"INV{i}", "2024-03-15", 1000))
        pr_records.append(_pr(f"p_clean_{i}", f"INV{i}", "2024-03-15", 1000))
        
    # 2. Review Required (Typo / Level 4): 675
    for i in range(675):
        gstr_records.append(_gstr(f"g_rr_typo_{i}", f"TYPO{i}", "2024-03-15", 2000))
        pr_records.append(_pr(f"p_rr_typo_{i}", f"TYPO{i}-A", "2024-03-15", 2000))
        
    # 3. Review Required (Amount Mismatch / Level 2 or 3): 675
    for i in range(675):
        gstr_records.append(_gstr(f"g_rr_amt_{i}", f"AMT{i}", "2024-03-15", 3000))
        pr_records.append(_pr(f"p_rr_amt_{i}", f"AMT{i}", "2024-03-15", 3005)) # Rs 5 diff
        
    # 4. Missed ITC / GSTR-only: 450
    for i in range(450):
        gstr_records.append(_gstr(f"g_missed_{i}", f"MISS{i}", "2024-03-15", 4000))
        
    # 5. ITC at Risk / PR-only: 450
    for i in range(450):
        pr_records.append(_pr(f"p_risk_{i}", f"RISK{i}", "2024-03-15", 5000))
        
    assert len(gstr_records) == 6000
    assert len(pr_records) == 6000
    
    state = ReconState()
    pr_index = {}
    for p in pr_records:
        gstin = p["supplier_gstin"]
        if gstin not in pr_index: pr_index[gstin] = []
        pr_index[gstin].append(p)
        
    gstr_by_invoice = {}
    for g in gstr_records:
        inv = g["invoice_number_normalized"]
        if inv not in gstr_by_invoice: gstr_by_invoice[inv] = []
        gstr_by_invoice[inv].append(g)

    pr_by_invoice = {}
    for p in pr_records:
        gstin = p["supplier_gstin"]
        if gstin not in pr_by_invoice: pr_by_invoice[gstin] = {}
        inv = p["invoice_number_normalized"]
        pr_by_invoice[gstin][inv] = p
        
    period = date(2024, 3, 1)
    pr_index_by_period = {period: pr_index}
    
    process_gstr_records_chunk(
        gstr_records=gstr_records,
        effective_gstr_period=period,
        pr_index=pr_index,
        pr_index_by_period=pr_index_by_period,
        state=state,
        gstr_by_invoice=gstr_by_invoice,
        pr_by_invoice=pr_by_invoice
    )
    
    print(f"Clean Matched: {len(state.clean_matched)}")
    print(f"Review Required: {len(state.review_required)}")
    print(f"Missed ITC: {len(state.missed_itc)}")
    print(f"ITC at Risk: {len(pr_records) - len(state.consumed_pr_ids)}")
    
    assert len(state.clean_matched) == 4200
    assert len(state.review_required) == 1350
    assert len(state.missed_itc) == 450
    assert len(pr_records) - len(state.consumed_pr_ids) == 450
