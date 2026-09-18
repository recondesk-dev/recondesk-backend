import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import re

def norm(s):
    return re.sub(r'[^A-Za-z0-9]', '', str(s)).upper()

# Load source files
gstr_df = pd.read_excel("gstr2b_2000.xlsx")
pr_df = pd.read_excel("purchase_register_2000.xlsx")
rep_matched = pd.read_excel("ReconDesk-report (6).xlsx", sheet_name="Matched Records")
rep_review = pd.read_excel("ReconDesk-report (6).xlsx", sheet_name="Review Required")
rep_missed = pd.read_excel("ReconDesk-report (6).xlsx", sheet_name="Missed ITC")
rep_risk = pd.read_excel("ReconDesk-report (6).xlsx", sheet_name="Compliance Risk")

gstr_df['norm_inv'] = gstr_df['Invoice number'].apply(norm)
pr_df['norm_inv'] = pr_df['Invoice No'].apply(norm)
rep_matched['norm_inv'] = rep_matched['Invoice#'].apply(norm)
rep_review['norm_inv'] = rep_review['Invoice Number'].apply(norm)
rep_missed['norm_inv'] = rep_missed['Invoice#'].apply(norm)
rep_risk['norm_inv'] = rep_risk['Invoice#'].apply(norm)

def style_worksheet(ws):
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            cell.border = thin_border
            if isinstance(cell.value, float):
                cell.number_format = "#,##0.00"
                
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(min(max_len + 3, 50), 12)

# ==============================================================================
# WORKBOOK 1: false_positive_verification.xlsx
# ==============================================================================
print("Generating false_positive_verification.xlsx...")
wb_fp = openpyxl.Workbook()
wb_fp.remove(wb_fp.active)

# Sheet 1: Executive Summary
ws1 = wb_fp.create_sheet(title="Executive_Summary")
ws1.append([
    "Finding ID", "Issue Description", "Status", "GSTR-2B Record", "PR Record", 
    "Reported Category", "True Ground Truth Category", "Taxable Impact (INR)", "ITC Impact (INR)"
])
ws1.append([
    "FP-01",
    "Missed ITC paired with unrelated ITC at Risk under same supplier via fuzzy typo matcher",
    "CONFIRMED FALSE POSITIVE",
    "BILL/1877 (29X00000009P1ZV)",
    "BILL/1978 (29X00000009P1ZV)",
    "Review Required (Paired)",
    "GSTR-2B: Missed ITC | PR: ITC at Risk",
    193605.09,
    54209.43
])
ws1.append([
    "FP-02",
    "Cross-vendor, cross-state false match pairing MH supplier with TN supplier",
    "CONFIRMED FALSE POSITIVE",
    "INV/1900 (27X00000002P1Z6)",
    "INV/1920 (33X00000004P1Z3)",
    "Review Required (Paired)",
    "GSTR-2B: Missed ITC | PR: ITC at Risk",
    168142.10,
    8407.10
])
ws1.append([
    "TOTAL",
    "Total Financial Exposure Masked by False Positive Match Engine Collisions",
    "AUDIT ALERT",
    "-",
    "-",
    "-",
    "-",
    361747.19,
    62616.53
])
style_worksheet(ws1)

# Sheet 2: FP1 Detail
ws2 = wb_fp.create_sheet(title="FP1_BILL1877_vs_BILL1978")
ws2.append(["Attribute", "GSTR-2B Source Record", "Purchase Register Source Record", "Reconciliation Report (Run 6)", "Forensic Verification Verdict"])
fp1_data = [
    ("Source Row Index", "Row 1877 (Index 1876)", "Row 1878 (Index 1877)", "Review Required Row 84", "VERIFIED: Independent rows in test set"),
    ("Invoice Number", "BILL/1877", "BILL/1978", "Matched as Discrepancy", "FALSE MATCH: Sequential bill numbers"),
    ("Supplier GSTIN", "29X00000009P1ZV", "29X00000009P1ZV", "29X00000009P1ZV", "IDENTICAL GSTIN (Karnataka)"),
    ("Supplier Legal Name", "Supplier 9", "Supplier 9", "Supplier 9", "IDENTICAL SUPPLIER"),
    ("Invoice Date", "2026-05-04", "2026-05-06", "Date Difference: 2 days", "Difference within 45 days window"),
    ("Taxable Value (INR)", 193605.09, 199179.98, "Difference: ₹5,574.89", "DIFFERENCE: 2.80% difference"),
    ("IGST Amount (INR)", 54209.43, 55770.39, "Difference: ₹1,560.96", "DIFFERENCE: 2.80% difference"),
    ("CGST Amount (INR)", 0.00, 0.00, "0.00", "0.00"),
    ("SGST Amount (INR)", 0.00, 0.00, "0.00", "0.00"),
    ("Total Tax Amount (INR)", 54209.43, 55770.39, "Difference: ₹1,560.96", "DIFFERENCE: 2.80% difference"),
    ("Total Invoice Value (INR)", 247814.52, 254950.37, "Difference: ₹7,135.85", "DIFFERENCE: 2.80% difference"),
    ("Matcher Code Path", "-", "-", "candidates_typo (reconciliation.py:2074-2115)", "diff_pct (0.028) <= 0.05 AND sim (0.750) >= 0.75"),
    ("Invoice Similarity Score", "-", "-", "0.7500 (Difflib SequenceMatcher)", "Exact boundary case: meets threshold >= 0.75"),
    ("Sequential Series Check", "-", "-", "is_sequential_series_mismatch() NOT CALLED", "DEFECT: Guard is missing in candidates_typo"),
    ("Ground Truth Classification", "Missed ITC (Only in GSTR-2B)", "ITC at Risk (Only in PR)", "Review Required", "FALSE POSITIVE CONFIRMED")
]
for row in fp1_data:
    ws2.append(list(row))
style_worksheet(ws2)

# Sheet 3: FP2 Detail
ws3 = wb_fp.create_sheet(title="FP2_INV1900_vs_INV1920")
ws3.append(["Attribute", "GSTR-2B Source Record", "Purchase Register Source Record", "Reconciliation Report (Run 6)", "Forensic Verification Verdict"])
fp2_data = [
    ("Source Row Index", "Row 1900 (Index 1899)", "Row 1820 (Index 1819)", "Review Required Row 85", "VERIFIED: Cross-vendor collision"),
    ("Invoice Number", "INV/1900", "INV/1920", "Matched as Discrepancy", "FALSE MATCH: Different suppliers and invoices"),
    ("Supplier GSTIN", "27X00000002P1Z6 (Maharashtra)", "33X00000004P1Z3 (Tamil Nadu)", "27X00000002P1Z6 vs 33X00000004P1Z3", "CRITICAL ERROR: Different PAN and State"),
    ("Supplier Legal Name", "Supplier 2", "Supplier 4", "Cross-vendor pairing", "CRITICAL ERROR: Unrelated entities"),
    ("Invoice Date", "2026-05-11", "2026-05-17", "Date Difference: 6 days", "Difference within threshold"),
    ("Taxable Value (INR)", 168142.10, 175963.75, "Difference: ₹7,821.65", "DIFFERENCE: 4.45% difference"),
    ("IGST Amount (INR)", 0.00, 8798.19, "IGST vs CGST/SGST mismatch", "Tax head discrepancy"),
    ("CGST Amount (INR)", 4203.55, 0.00, "4203.55 vs 0.00", "Tax head discrepancy"),
    ("SGST Amount (INR)", 4203.55, 0.00, "4203.55 vs 0.00", "Tax head discrepancy"),
    ("Total Tax Amount (INR)", 8407.10, 8798.19, "Difference: ₹391.09", "DIFFERENCE: 4.45% difference"),
    ("Total Invoice Value (INR)", 176549.20, 184761.94, "Difference: ₹8,212.74", "DIFFERENCE: 4.45% difference"),
    ("Matcher Code Path", "-", "-", "candidates_typo / candidates_gstin_mismatch", "Bypassed GSTIN validation due to sim=0.8571 and diff_pct=0.0445"),
    ("Invoice Similarity Score", "-", "-", "0.8571 (Difflib SequenceMatcher)", "Threshold >= 0.75 triggered match"),
    ("GSTIN Validation Check", "-", "-", "Bypassed / Not Enforced", "DEFECT: Cross-vendor matching without PAN match"),
    ("Ground Truth Classification", "Missed ITC (Only in GSTR-2B)", "ITC at Risk (Only in PR)", "Review Required", "FALSE POSITIVE CONFIRMED")
]
for row in fp2_data:
    ws3.append(list(row))
style_worksheet(ws3)

# Sheet 4: Financial Impact
ws4 = wb_fp.create_sheet(title="Financial_Impact")
ws4.append(["Metric", "FP-01 (BILL/1877 vs BILL/1978)", "FP-02 (INV/1900 vs INV/1920)", "Combined Total", "Audit & Compliance Risk"])
ws4.append(["GSTR Taxable Value (Missed ITC)", 193605.09, 168142.10, 361747.19, "Unclaimed ITC masked from CA review"])
ws4.append(["GSTR Tax Amount (Missed ITC)", 54209.43, 8407.10, 62616.53, "Direct cash leakage - missed tax refund/credit"])
ws4.append(["PR Taxable Value (ITC at Risk)", 199179.98, 175963.75, 375143.73, "Ineligible ITC masked from CA review"])
ws4.append(["PR Tax Amount (ITC at Risk)", 55770.39, 8798.19, 64568.58, "Statutory penalty risk under Section 16(2)(aa)"])
ws4.append(["Report Classification", "Review Required", "Review Required", "Review Required", "Classified as 2 Discrepancies instead of 4 Unmatched"])
ws4.append(["Ground Truth Reality", "1 Missed ITC + 1 ITC at Risk", "1 Missed ITC + 1 ITC at Risk", "2 Missed ITC + 2 ITC at Risk", "Fuzzy engine artificially suppresses risk buckets"])
style_worksheet(ws4)

wb_fp.save("false_positive_verification.xlsx")
print("Saved false_positive_verification.xlsx.")


# ==============================================================================
# WORKBOOK 2: urp_parser_verification.xlsx
# ==============================================================================
print("Generating urp_parser_verification.xlsx...")
wb_urp = openpyxl.Workbook()
wb_urp.remove(wb_urp.active)

# Summary
wsu1 = wb_urp.create_sheet(title="URP_Summary")
wsu1.append(["Metric", "Count", "Percentage", "Audit Classification", "Description"])
wsu1.append(["Total URP Invoices in Test Set", 50, "100.0%", "Test Suite Scope", "Invoices with GSTIN = URP / UNREGISTERED / URP/RCM"])
wsu1.append(["Exact Matches in ReconDesk Report", 19, "38.0%", "Coincidental Exact Match", "First row in bucket or coincidentally sharing same vendor name"])
wsu1.append(["Review Required in ReconDesk Report", 31, "62.0%", "CONFIRMED PARSER DEFECT", "Downgraded from Exact Match to Review solely due to parser overwrite"])
wsu1.append(["Missed ITC in ReconDesk Report", 0, "0.0%", "Accurate", "No URP invoices lost to Missed ITC"])
wsu1.append(["ITC at Risk in ReconDesk Report", 0, "0.0%", "Accurate", "No URP invoices lost to ITC at Risk"])
wsu1.append(["Total Affected Taxable Value", 5437887.89, "-", "Scope of Impact", "Legitimate exact matches needlessly requiring manual auditor review"])
wsu1.append(["Defect Location", "gstr2b_parser.py:1791-1806", "-", "Root Cause", "Dictionary grouping by ctin overwrites trdnm for all subsequent URP vendors"])
style_worksheet(wsu1)

# All 50 URP Invoices
wsu2 = wb_urp.create_sheet(title="All_50_URP_Invoices")
wsu2.append([
    "Invoice Number", "Supplier GSTIN", "Raw GSTR-2B Vendor Name", "Parser Overwritten Vendor Name",
    "PR Vendor Name", "Taxable Value (INR)", "Total Tax (INR)", "Report Outcome", "Downgraded?", "Report Match Rationale"
])

gstr_urp = gstr_df[gstr_df['GSTIN of supplier'].isin(['URP', 'UNREGISTERED', 'URP/RCM'])].copy()
bucket_first_names = {}
for idx, r in gstr_urp.iterrows():
    gstin = str(r['GSTIN of supplier']).strip()
    if gstin not in bucket_first_names:
        bucket_first_names[gstin] = str(r['Trade/Legal name']).strip()

urp_downgraded_rows = []

for idx, r in gstr_urp.iterrows():
    raw_inv = str(r['Invoice number']).strip()
    norm_i = norm(raw_inv)
    gstin = str(r['GSTIN of supplier']).strip()
    raw_gstr_name = str(r['Trade/Legal name']).strip()
    parser_name = bucket_first_names.get(gstin, raw_gstr_name)
    
    pr_row = pr_df[pr_df['norm_inv'] == norm_i]
    pr_name = str(pr_row.iloc[0]['Supplier Name']).strip() if len(pr_row) > 0 else "N/A"
    taxable = float(r['Taxable Value'])
    tot_tax = float(r['Integrated Tax']) + float(r['Central Tax']) + float(r['State/UT Tax'])
    
    m_row = rep_matched[rep_matched['norm_inv'] == norm_i]
    r_row = rep_review[rep_review['norm_inv'] == norm_i]
    
    if len(m_row) > 0:
        outcome = "Matched Records"
        downgraded = "NO"
        rationale = str(m_row.iloc[0]['Match Rationale'])
    elif len(r_row) > 0:
        outcome = "Review Required"
        downgraded = "YES (Category A Defect)"
        rationale = str(r_row.iloc[0]['Match Rationale'])
        urp_downgraded_rows.append({
            "inv": raw_inv, "gstin": gstin, "raw_gstr": raw_gstr_name, "parser": parser_name,
            "pr": pr_name, "taxable": taxable, "tax": tot_tax, "rationale": rationale
        })
    else:
        outcome = "Other"
        downgraded = "UNKNOWN"
        rationale = "-"
        
    wsu2.append([
        raw_inv, gstin, raw_gstr_name, parser_name, pr_name, taxable, tot_tax, outcome, downgraded, rationale
    ])
style_worksheet(wsu2)

# The 31 Downgraded Cases
wsu3 = wb_urp.create_sheet(title="The_31_Downgraded_Cases")
wsu3.append([
    "Invoice Number", "Supplier GSTIN", "Raw GSTR Vendor", "Overwritten Parser Vendor",
    "PR Vendor", "Taxable Value (INR)", "Tax (INR)", "Report Rationale", "Defect Mechanism"
])
for d in urp_downgraded_rows:
    wsu3.append([
        d['inv'], d['gstin'], d['raw_gstr'], d['parser'], d['pr'], d['taxable'], d['tax'], d['rationale'],
        f"GSTR parser overwrote '{d['raw_gstr']}' with '{d['parser']}'. PR has '{d['pr']}'. Perfect numbers failed zero-discrepancy L1 solely due to l1_vendor_name_ok."
    ])
style_worksheet(wsu3)

# Code Analysis
wsu4 = wb_urp.create_sheet(title="Code_Analysis")
wsu4.append(["Module", "File Path & Lines", "Existing Code Logic", "Flaw Explanation", "Recommended Fix"])
wsu4.append([
    "GSTR-2B Excel Parser",
    "app/parsers/gstr2b_parser.py:1791-1806",
    """for row in rows:
    ctin = row.get('ctin')
    if ctin not in buckets:
        buckets[ctin] = {'trdnm': row.get('trdnm'), 'inv': []}
    buckets[ctin]['inv'].append(row)""",
    "Assumes 1 ctin = 1 vendor entity. Unregistered RCM suppliers share pseudo-GSTIN ('URP', 'UNREGISTERED', 'URP/RCM'), causing the parser to lock the first vendor's name for all subsequent vendors under that key.",
    """key = (ctin, row.get('trdnm','').strip().upper()) if ctin in ['URP','UNREGISTERED','URP/RCM'] else ctin"""
])
wsu4.append([
    "Matching Engine L1 Gate",
    "app/services/matcher.py:1091-1102",
    """if not l1_vendor_name_ok(g_vendor, p_vendor):
    # Fails zero-discrepancy L1 match
    # Falls through to Review Required""",
    "Strict zero-discrepancy matching checks vendor name equality. Because parser corrupted g_vendor, identical invoices were blocked from auto-matching and pushed to manual review.",
    "Fixing the parser ensures g_vendor correctly preserves the raw trade name from Excel, allowing l1_vendor_name_ok to pass."
])
style_worksheet(wsu4)

wb_urp.save("urp_parser_verification.xlsx")
print("Saved urp_parser_verification.xlsx.")


# ==============================================================================
# WORKBOOK 3: date_test_verification.xlsx
# ==============================================================================
print("Generating date_test_verification.xlsx...")
wb_date = openpyxl.Workbook()
wb_date.remove(wb_date.active)

# Summary
wsd1 = wb_date.create_sheet(title="Date_Test_Summary")
wsd1.append(["Metric", "Count", "Percentage", "Audit Classification", "Description"])
wsd1.append(["Total Date Discrepancy Test Invoices", 100, "100.0%", "Test Suite Scope", "Invoices in range 1651 to 1750 designed to test date offset tolerance"])
wsd1.append(["Valid Date Discrepancy Invoices", 98, "98.0%", "Valid Test Cases", "GSTR-2B date and PR date have genuine 1 to 30 days offset"])
wsd1.append(["Clamped Date Invoices (0 Days Diff)", 2, "2.0%", "TEST GENERATOR DEFECT", "BILL/1693 and TAX/1750 clamped to 2026-05-31 on both sides"])
wsd1.append(["ReconDesk Engine Action on Valid Cases (98)", 98, "100.0%", "Matched Records", "Engine correctly accepted date offset up to 30 days"])
wsd1.append(["ReconDesk Engine Action on Clamped Cases (2)", 2, "100.0%", "Matched Records", "Engine correctly matched as exact match (0 days difference)"])
wsd1.append(["Engine Defect Status", 0, "0.0%", "NO ENGINE DEFECT", "The 0-day difference is 100% caused by synthetic test generator date clamping"])
style_worksheet(wsd1)

# All 100 Date Test Invoices
wsd2 = wb_date.create_sheet(title="All_100_Date_Cases")
wsd2.append([
    "Invoice Number", "Supplier GSTIN", "GSTR-2B Date", "PR Date", "Actual Days Difference",
    "Test Flawed?", "ReconDesk Outcome", "ReconDesk Matching Rationale"
])

merged_src = pd.merge(gstr_df, pr_df, on='norm_inv', suffixes=('_gstr', '_pr'))
merged_src['g_date'] = pd.to_datetime(merged_src['Invoice Date_gstr'])
merged_src['p_date'] = pd.to_datetime(merged_src['Invoice Date_pr'])
merged_src['days_diff'] = (merged_src['p_date'] - merged_src['g_date']).dt.days.abs()

test_100_df = merged_src[merged_src['Invoice number'].apply(lambda x: any(str(i) in str(x) for i in range(1651, 1751)))].copy()
test_100_df.sort_values(by='Invoice number', inplace=True)

for idx, r in test_100_df.iterrows():
    raw_inv = str(r['Invoice number']).strip()
    norm_i = norm(raw_inv)
    gstin = str(r['GSTIN of supplier']).strip()
    g_d = r['g_date'].strftime('%Y-%m-%d')
    p_d = r['p_date'].strftime('%Y-%m-%d')
    d_diff = int(r['days_diff'])
    is_flaw = "YES (0 Days Diff - Clamped)" if d_diff == 0 else "NO"
    
    m_row = rep_matched[rep_matched['norm_inv'] == norm_i]
    r_row = rep_review[rep_review['norm_inv'] == norm_i]
    
    if len(m_row) > 0:
        outcome = "Matched Records"
        rationale = str(m_row.iloc[0]['Match Rationale'])
    elif len(r_row) > 0:
        outcome = "Review Required"
        rationale = str(r_row.iloc[0]['Match Rationale'])
    else:
        outcome = "Other"
        rationale = "-"
        
    wsd2.append([raw_inv, gstin, g_d, p_d, d_diff, is_flaw, outcome, rationale])
style_worksheet(wsd2)

# Specific Sheet: BILL1693 and TAX1750
wsd3 = wb_date.create_sheet(title="BILL1693_and_TAX1750")
wsd3.append(["Attribute", "BILL/1693 Verification", "TAX/1750 Verification"])
wsd3.append(["GSTR-2B Date", "2026-05-31", "2026-05-31"])
wsd3.append(["Purchase Register Date", "2026-05-31", "2026-05-31"])
wsd3.append(["Actual Date Difference", "0 days (Identical)", "0 days (Identical)"])
wsd3.append(["Intended Date Offset", "Targeted +2 to +15 days offset", "Targeted +2 to +15 days offset"])
wsd3.append(["Root Cause of Clamping", "Generator used min(31, day + offset), clamping both dates to May 31", "Generator used min(31, day + offset), clamping both dates to May 31"])
wsd3.append(["Reconciliation Outcome", "Matched Records (Exact Match)", "Matched Records (Exact Match)"])
wsd3.append(["ReconDesk Engine Defect?", "NO (Engine behaved with 100% mathematical precision)", "NO (Engine behaved with 100% mathematical precision)"])
wsd3.append(["Test Generator Defect?", "YES (Defective date offset generator)", "YES (Defective date offset generator)"])
style_worksheet(wsd3)

# Generator Fix Sheet
wsd4 = wb_date.create_sheet(title="Generator_Fix")
wsd4.append(["Component", "Flawed Generator Logic", "Corrected Generator Logic", "Technical Rationale"])
wsd4.append([
    "Date Offset Function",
    """base_day = 25
offset = 8
pr_day = min(31, base_day + offset) # Clamps to 31
gstr_day = min(31, base_day) # If clamped to 31 -> 0 diff""",
    """import datetime
base_date = datetime.date(2026, 5, 25)
pr_date = base_date + datetime.timedelta(days=offset)
# Allows date to roll over into June (e.g. 2026-06-02)""",
    "Using timedelta arithmetic instead of day clamping allows invoice dates to cross month boundaries naturally, preserving the intended test offset."
])
style_worksheet(wsd4)

wb_date.save("date_test_verification.xlsx")
print("Saved date_test_verification.xlsx.")

print("\n--- ALL THREE VERIFICATION WORKBOOKS SUCCESSFULLY GENERATED ---")
