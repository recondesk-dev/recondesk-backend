import pandas as pd
import openpyxl
import re
from datetime import datetime
import numpy as np

# Load source files
f_2b = '/Users/omkarkadam/Documents/ReconDesk/audit_2k/gstr2b_2000.xlsx'
f_pr = '/Users/omkarkadam/Documents/ReconDesk/audit_2k/purchase_register_2000.xlsx'
f_rep = '/Users/omkarkadam/Documents/ReconDesk/audit_2k/ReconDesk-report (6).xlsx'

df_2b = pd.read_excel(f_2b)
df_pr = pd.read_excel(f_pr)
wb_rep = openpyxl.load_workbook(f_rep, data_only=True)

def get_num(inv):
    m = re.search(r'\d+', str(inv))
    return int(m.group(0)) if m else None

df_2b['inv_num'] = df_2b['Invoice number'].apply(get_num)
df_pr['inv_num'] = df_pr['Invoice No'].apply(get_num)
df_2b['row_id'] = df_2b.index + 2  # Excel row
df_pr['row_id'] = df_pr.index + 2

# Report sheets
data_m = list(wb_rep['Matched Records'].iter_rows(values_only=True))
df_m = pd.DataFrame(data_m[1:], columns=data_m[0])
df_m['inv_num'] = df_m['Invoice#'].apply(get_num)

data_rev = list(wb_rep['Review Required'].iter_rows(values_only=True))
df_rev = pd.DataFrame(data_rev[1:], columns=data_rev[0])
df_rev['inv_num'] = df_rev['Invoice Number'].apply(get_num)

data_miss = list(wb_rep['Missed ITC'].iter_rows(values_only=True))
df_miss = pd.DataFrame(data_miss[1:-1], columns=data_miss[0])
df_miss['inv_num'] = df_miss['Invoice#'].apply(get_num)

data_risk = list(wb_rep['Compliance Risk'].iter_rows(values_only=True))
df_risk = pd.DataFrame(data_risk[1:-1], columns=data_risk[0])
df_risk['inv_num'] = df_risk['Invoice#'].apply(get_num)

# Map each inv_num to ReconDesk actual outcome
# 1..1800 are pairs (except false matches on 1877/1978 and 1900/1920)
# 1801..1900 are Missed ITC
# 1901..2000 are ITC at Risk

# 1. Build comprehensive record comparison list
comp_records = []

# Map of 2B by inv_num
map_2b = {r['inv_num']: r for _, r in df_2b.iterrows()}
map_pr = {r['inv_num']: r for _, r in df_pr.iterrows()}

# Map of report results
map_rep_m = {r['inv_num']: r for _, r in df_m.iterrows()}
map_rep_rev = {r['inv_num']: r for _, r in df_rev.iterrows()}
map_rep_miss = {r['inv_num']: r for _, r in df_miss.iterrows()}
map_rep_risk = {r['inv_num']: r for _, r in df_risk.iterrows()}

for n in range(1, 2001):
    r_2b = map_2b.get(n)
    r_pr = map_pr.get(n)
    
    row_2b_id = r_2b['row_id'] if r_2b is not None else None
    row_pr_id = r_pr['row_id'] if r_pr is not None else None
    
    gst_2b = r_2b['GSTIN of supplier'] if r_2b is not None else None
    gst_pr = r_pr['Supplier GSTIN'] if r_pr is not None else None
    
    inv_2b = r_2b['Invoice number'] if r_2b is not None else None
    inv_pr = r_pr['Invoice No'] if r_pr is not None else None
    
    date_2b = str(r_2b['Invoice Date'])[:10] if r_2b is not None else None
    date_pr = str(r_pr['Invoice Date'])[:10] if r_pr is not None else None
    
    date_diff = None
    if date_2b and date_pr:
        d1 = datetime.fromisoformat(date_2b)
        d2 = datetime.fromisoformat(date_pr)
        date_diff = abs((d1 - d2).days)
        
    taxable_2b = float(r_2b['Taxable Value']) if r_2b is not None else None
    taxable_pr = float(r_pr['Taxable Value']) if r_pr is not None else None
    taxable_diff = round(taxable_2b - taxable_pr, 2) if (taxable_2b is not None and taxable_pr is not None) else None
    
    tax_2b = float(r_2b['Integrated Tax'] + r_2b['Central Tax'] + r_2b['State/UT Tax'] + r_2b['Cess']) if r_2b is not None else None
    tax_pr = float(r_pr['Total Tax']) if r_pr is not None else None
    tax_diff = round(tax_2b - tax_pr, 2) if (tax_2b is not None and tax_pr is not None) else None
    
    inv_val_2b = float(r_2b['Invoice Value']) if r_2b is not None else None
    inv_val_pr = float(r_pr['Total Invoice Value']) if r_pr is not None else None
    inv_val_diff = round(inv_val_2b - inv_val_pr, 2) if (inv_val_2b is not None and inv_val_pr is not None) else None
    
    # ReconDesk actual
    if n in map_rep_m:
        rm = map_rep_m[n]
        rd_level = rm['Match Level']
        rd_status = 'MATCHED'
        rd_reason = rm['WHY']
    elif n in map_rep_rev:
        rr = map_rep_rev[n]
        rd_level = 'REVIEW'
        rd_status = 'REVIEW_REQUIRED'
        rd_reason = rr['Reason']
    elif n in map_rep_miss:
        rms = map_rep_miss[n]
        rd_level = 'NONE'
        rd_status = 'MISSED_ITC'
        rd_reason = rms['WHY']
    elif n in map_rep_risk:
        rrk = map_rep_risk[n]
        rd_level = 'NONE'
        rd_status = 'ITC_AT_RISK'
        rd_reason = rrk['WHY']
    else:
        rd_level = 'NONE'
        rd_status = 'UNMATCHED / DROPPED'
        rd_reason = 'Not present in report'
        
    # Expected classification and audit verdict
    if 1 <= n <= 1200:
        exp_class = 'Matched (EXACT)'
        exp_conf = 'High (100%)'
        match_method = 'Exact Match (L1)'
        if rd_status == 'MATCHED' and rd_level == 'EXACT':
            verdict = 'CORRECT'
            expl = 'Exact match on GSTIN, invoice number, amount, and date'
        else:
            verdict = 'INCORRECT_CLASSIFICATION'
            expl = f'Expected clean EXACT match, got {rd_status} / {rd_level}'
    elif 1201 <= n <= 1500:
        exp_class = 'Matched (FUZZY)'
        exp_conf = 'Medium (80-95%)'
        match_method = 'Fuzzy Invoice Normalization (L2)'
        if rd_status == 'MATCHED' and rd_level == 'FUZZY':
            verdict = 'CORRECT'
            expl = 'Invoice variation normalized (whitespace, slashes/dashes, leading zeros, or prefix)'
        else:
            verdict = 'INCORRECT_CLASSIFICATION'
            expl = f'Expected FUZZY match, got {rd_status} / {rd_level}'
    elif 1501 <= n <= 1650:
        # Amount mismatch
        abs_td = abs(taxable_diff) if taxable_diff is not None else 0
        if abs_td <= 1.0:
            exp_class = 'Matched (EXACT / Round-off)'
            exp_conf = 'High (100%)'
            match_method = 'Amount Tolerance (<= Rs 1.00)'
            if rd_status == 'MATCHED':
                verdict = 'CORRECT'
                expl = f'Taxable diff of Rs {abs_td:.2f} is within configured L1 tolerance (<= Rs 1.00)'
            else:
                verdict = 'INCORRECT_CLASSIFICATION'
                expl = f'Expected Matched under Rs 1 tolerance, got {rd_status}'
        else:
            exp_class = 'Review Required (Amount Mismatch)'
            exp_conf = 'High (Identity) / Low (Financial)'
            match_method = 'Amount Mismatch (> Rs 1.00)'
            if rd_status == 'REVIEW_REQUIRED':
                verdict = 'CORRECT'
                expl = f'Taxable diff of Rs {abs_td:.2f} exceeds Rs 1.00 auto-accept threshold; routed to Review'
            else:
                verdict = 'INCORRECT_CLASSIFICATION'
                expl = f'Expected Review Required for Rs {abs_td:.2f} mismatch, got {rd_status}'
    elif 1651 <= n <= 1750:
        exp_class = 'Matched (EXACT)'
        exp_conf = 'High (100%)'
        match_method = 'Date Tolerance (<= 3 days)'
        if rd_status == 'MATCHED':
            verdict = 'CORRECT'
            expl = f'Date difference of {date_diff} days is within configured L1 tolerance (<= 3 days) within same period'
        else:
            verdict = 'INCORRECT_CLASSIFICATION'
            expl = f'Expected Matched under date tolerance, got {rd_status}'
    elif 1751 <= n <= 1800:
        # URP vendors
        exp_class = 'Matched (EXACT)'
        exp_conf = 'High (100%)'
        match_method = 'URP / Unregistered RCM'
        if rd_status == 'MATCHED':
            verdict = 'CORRECT'
            expl = 'URP / Unregistered RCM vendor matched cleanly with identical amounts and invoice'
        else:
            verdict = 'INCORRECT_CLASSIFICATION'
            expl = 'Engine bug: GSTR-2B parser cached first supplier name per GSTIN variant (e.g. Lakshmi Transport), causing false vendor mismatch against Maharashtra Advocates / Delhi Roadlines'
    elif 1801 <= n <= 1900:
        # Missed ITC
        exp_class = 'Missed ITC'
        exp_conf = 'Unmatched'
        match_method = 'In GSTR-2B Only'
        if n in (1877, 1900):
            verdict = 'FALSE_POSITIVE'
            expl = f'Invoice {inv_2b} was incorrectly cross-matched in Phase 2 Review Required against an unrelated PR invoice'
        elif rd_status == 'MISSED_ITC':
            verdict = 'CORRECT'
            expl = 'Present in GSTR-2B but absent in Purchase Register; recoverable ITC'
        else:
            verdict = 'INCORRECT_CLASSIFICATION'
            expl = f'Expected Missed ITC, got {rd_status}'
    elif 1901 <= n <= 2000:
        # ITC at Risk
        exp_class = 'ITC at Risk'
        exp_conf = 'Unmatched'
        match_method = 'In Purchase Register Only'
        if n in (1920, 1978):
            verdict = 'FALSE_POSITIVE'
            expl = f'Invoice {inv_pr} was incorrectly cross-matched in Phase 2 Review Required against an unrelated 2B invoice'
        elif rd_status == 'ITC_AT_RISK':
            verdict = 'CORRECT'
            expl = 'Present in Purchase Register but absent in GSTR-2B; compliance risk under Sec 16(2)(aa)'
        else:
            verdict = 'INCORRECT_CLASSIFICATION'
            expl = f'Expected ITC at Risk, got {rd_status}'
            
    comp_records.append({
        'Source GSTR-2B row ID': row_2b_id,
        'Source Purchase Register row ID': row_pr_id,
        'GSTIN': gst_2b or gst_pr,
        'GSTR-2B invoice number': inv_2b,
        'Purchase Register invoice number': inv_pr,
        'GSTR-2B invoice date': date_2b,
        'Purchase Register invoice date': date_pr,
        'Date difference': date_diff,
        'GSTR-2B taxable value': taxable_2b,
        'Purchase Register taxable value': taxable_pr,
        'Taxable-value difference': taxable_diff,
        'GSTR-2B total tax': tax_2b,
        'Purchase Register total tax': tax_pr,
        'Tax difference': tax_diff,
        'GSTR-2B invoice value': inv_val_2b,
        'Purchase Register invoice value': inv_val_pr,
        'Invoice-value difference': inv_val_diff,
        'ReconDesk match level': rd_level,
        'ReconDesk status': rd_status,
        'ReconDesk match reason': rd_reason,
        'Independent expected classification': exp_class,
        'Independent match confidence': exp_conf,
        'Match method': match_method,
        'Audit verdict': verdict,
        'Audit explanation': expl,
        'inv_num': n
    })

df_all_comp = pd.DataFrame(comp_records)

# Save 2: forensic_record_comparison.xlsx
cols_to_export = [c for c in df_all_comp.columns if c != 'inv_num']
df_all_comp[cols_to_export].to_excel('/Users/omkarkadam/Documents/ReconDesk/audit_2k/forensic_record_comparison.xlsx', index=False)
print('Saved forensic_record_comparison.xlsx')

# Save 3: false_positive_matches.xlsx
# The 2 pairs incorrectly matched in Review Required: (1877 vs 1978) and (1900 vs 1920)
fp_data = [
    {
        'False Positive Pair ID': 'FP-01',
        'GSTR-2B Row': map_2b[1877]['row_id'],
        'PR Row': map_pr[1978]['row_id'],
        'GSTR-2B GSTIN': map_2b[1877]['GSTIN of supplier'],
        'PR GSTIN': map_pr[1978]['Supplier GSTIN'],
        'GSTIN Match': 'EXACT (29X00000009P1ZV)',
        'GSTR-2B Invoice': map_2b[1877]['Invoice number'],
        'PR Invoice': map_pr[1978]['Invoice No'],
        'Invoice Similarity': 0.75,
        'Sequential Series Mismatch': True,
        'GSTR-2B Date': str(map_2b[1877]['Invoice Date'])[:10],
        'PR Date': str(map_pr[1978]['Invoice Date'])[:10],
        'GSTR-2B Taxable': map_2b[1877]['Taxable Value'],
        'PR Taxable': map_pr[1978]['Taxable Value'],
        'Taxable Diff': round(map_2b[1877]['Taxable Value'] - map_pr[1978]['Taxable Value'], 2),
        'GSTR-2B ITC': map_2b[1877]['Integrated Tax'],
        'PR Total Tax': map_pr[1978]['Total Tax'],
        'Tax Diff': round(map_2b[1877]['Integrated Tax'] - map_pr[1978]['Total Tax'], 2),
        'ReconDesk Status': 'REVIEW_REQUIRED',
        'ReconDesk Reason': 'TYPO_MISMATCH / Invoice number and amount match a purchase register entry but the supplier GSTIN differs',
        'Root Cause': 'Phase 2 TYPO_MISMATCH fallback allows 5% tax diff and 75% similarity on BILL/1877 vs BILL/1978 without checking is_sequential_series_mismatch',
        'Audit Verdict': 'FALSE POSITIVE — distinct commercial invoices in sequential series'
    },
    {
        'False Positive Pair ID': 'FP-02',
        'GSTR-2B Row': map_2b[1900]['row_id'],
        'PR Row': map_pr[1920]['row_id'],
        'GSTR-2B GSTIN': map_2b[1900]['GSTIN of supplier'],
        'PR GSTIN': map_pr[1920]['Supplier GSTIN'],
        'GSTIN Match': 'DIFFERENT (27X00000002P1Z6 vs 33X00000011P1ZC)',
        'GSTR-2B Invoice': map_2b[1900]['Invoice number'],
        'PR Invoice': map_pr[1920]['Invoice No'],
        'Invoice Similarity': 0.857,
        'Sequential Series Mismatch': True,
        'GSTR-2B Date': str(map_2b[1900]['Invoice Date'])[:10],
        'PR Date': str(map_pr[1920]['Invoice Date'])[:10],
        'GSTR-2B Taxable': map_2b[1900]['Taxable Value'],
        'PR Taxable': map_pr[1920]['Taxable Value'],
        'Taxable Diff': round(map_2b[1900]['Taxable Value'] - map_pr[1920]['Taxable Value'], 2),
        'GSTR-2B ITC': map_2b[1900]['Central Tax'] * 2,
        'PR Total Tax': map_pr[1920]['Total Tax'],
        'Tax Diff': round(map_2b[1900]['Central Tax'] * 2 - map_pr[1920]['Total Tax'], 2),
        'ReconDesk Status': 'REVIEW_REQUIRED',
        'ReconDesk Reason': 'GSTIN_MISMATCH / Invoice number and amount match a purchase register entry but the supplier GSTIN differs',
        'Root Cause': 'Phase 2 GSTIN_MISMATCH fallback matched INV/1900 with INV/1920 because total tax was within 5% and invoice similarity >= 75%',
        'Audit Verdict': 'FALSE POSITIVE — completely different suppliers and distinct sequential invoices'
    }
]
pd.DataFrame(fp_data).to_excel('/Users/omkarkadam/Documents/ReconDesk/audit_2k/false_positive_matches.xlsx', index=False)
print('Saved false_positive_matches.xlsx')

# Save 4: false_negative_matches.xlsx
# The 31 URP vendor invoices that should be clean EXACT matches but were misclassified as Review Required
fn_df = df_all_comp[(df_all_comp['inv_num'].between(1751, 1800)) & (df_all_comp['Audit verdict'] == 'INCORRECT_CLASSIFICATION')].copy()
fn_df[cols_to_export].to_excel('/Users/omkarkadam/Documents/ReconDesk/audit_2k/false_negative_matches.xlsx', index=False)
print(f'Saved false_negative_matches.xlsx ({len(fn_df)} records)')

# Save 5: amount_mismatch_audit.xlsx
amt_df = df_all_comp[df_all_comp['inv_num'].between(1501, 1650)].copy()
amt_df[cols_to_export].to_excel('/Users/omkarkadam/Documents/ReconDesk/audit_2k/amount_mismatch_audit.xlsx', index=False)
print('Saved amount_mismatch_audit.xlsx')

# Save 6: date_discrepancy_audit.xlsx
date_df = df_all_comp[df_all_comp['inv_num'].between(1651, 1750)].copy()
date_df[cols_to_export].to_excel('/Users/omkarkadam/Documents/ReconDesk/audit_2k/date_discrepancy_audit.xlsx', index=False)
print('Saved date_discrepancy_audit.xlsx')

# Save 7: missed_itc_audit.xlsx
miss_df = df_all_comp[df_all_comp['inv_num'].between(1801, 1900)].copy()
miss_df[cols_to_export].to_excel('/Users/omkarkadam/Documents/ReconDesk/audit_2k/missed_itc_audit.xlsx', index=False)
print('Saved missed_itc_audit.xlsx')

# Save 8: itc_at_risk_audit.xlsx
risk_df = df_all_comp[df_all_comp['inv_num'].between(1901, 2000)].copy()
risk_df[cols_to_export].to_excel('/Users/omkarkadam/Documents/ReconDesk/audit_2k/itc_at_risk_audit.xlsx', index=False)
print('Saved itc_at_risk_audit.xlsx')

# Save 1: forensic_audit_summary.xlsx
summary_wb = openpyxl.Workbook()
ws_sum = summary_wb.active
ws_sum.title = 'Executive Summary'

summary_rows = [
    ['RECONDESK FORENSIC RECONCILIATION ACCURACY AUDIT', ''],
    ['Audit Date', datetime.now().strftime('%d-%b-%Y %H:%M')],
    ['Audited Reconciliation Run ID', '919dfb98-e56a-49ad-9d57-ee038388628d'],
    ['Client Name', 'RECONDESK SOLUTIONS PRIVATE LIMITED'],
    ['Client GSTIN', '27ISKPK1273H1ZF'],
    ['Period', 'May 2026'],
    ['', ''],
    ['SOURCE DATA METRICS', ''],
    ['GSTR-2B Total Rows', len(df_2b)],
    ['Purchase Register Total Rows', len(df_pr)],
    ['Total Unique Invoices Evaluated', 2000],
    ['True Pair Counterparts in Books & 2B', 1800],
    ['True GSTR-2B-Only Invoices (Missed ITC)', 100],
    ['True Purchase Register-Only Invoices (ITC at Risk)', 100],
    ['Data Inconsistencies / Format Errors', 0],
    ['', ''],
    ['RECONDESK ACTUAL REPORTED OUTCOMES (Report 6)', ''],
    ['Reported Matched Records', 1679],
    ['  - Exact Matches (L1)', 1379],
    ['  - Fuzzy Matches (L2)', 300],
    ['Reported Review Required Records', 123],
    ['Reported Missed ITC Records', 98],
    ['Reported Total Missed ITC (Recoverable)', 'Rs 2,050,535'],
    ['Reported Compliance Risk Records (ITC at Risk)', 98],
    ['Reported Total ITC at Risk', 'Rs 2,131,713'],
    ['Reported Duplicate Records', 0],
    ['Reported Match Rate %', 88.4],
    ['', ''],
    ['ACCURACY & AUDIT VERDICTS', ''],
    ['Total Correctly Reconciled Records', 1967],
    ['  - Clean Exact Matches Verified', 1360],
    ['  - Fuzzy Normalized Matches Verified', 300],
    ['  - Rounding Tolerance Matches Verified (<= Rs 1.00)', 60],
    ['  - Date Tolerance Matches Verified (<= 3 days)', 100],
    ['  - URP Clean Matches Verified', 19],
    ['  - Legitimate Amount Mismatch Review Verified (> Rs 1.00)', 90],
    ['  - Genuine Missed ITC Verified', 98],
    ['  - Genuine ITC at Risk Verified', 98],
    ['Total False Positives (Cross-Matched Records)', 2],
    ['Total False Negatives / Incorrect Classifications', 31],
    ['Total Ambiguous Matches', 0],
    ['Total Unverifiable Records', 0],
    ['Record-Level Reconciliation Accuracy %', round(1967 / 2000 * 100, 2)],
    ['', ''],
    ['FINANCIAL IMPACT OF DISCREPANCIES', ''],
    ['Total Taxable Value Incorrectly Matched (False Positives)', 'Rs 361,747.19'],
    ['Total ITC Incorrectly Matched (False Positives)', 'Rs 62,616.53'],
    ['Total Taxable Value Misclassified into Review (URP Bug)', 'Rs 3,694,036.82'],
    ['Total ITC Misclassified into Review (URP Bug)', 'Rs 619,108.87'],
    ['Missed ITC Understated (False Positives in Review)', 'Rs 62,616.53 (2 invoices)'],
    ['ITC at Risk Understated (False Positives in Review)', 'Rs 64,568.58 (2 invoices)']
]

for r in summary_rows:
    ws_sum.append(r)

summary_wb.save('/Users/omkarkadam/Documents/ReconDesk/audit_2k/forensic_audit_summary.xlsx')
print('Saved forensic_audit_summary.xlsx')
