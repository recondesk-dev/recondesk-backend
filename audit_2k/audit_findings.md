# ReconDesk — Forensic Reconciliation Accuracy Audit Report

**Audit Date**: 17 September 2026  
**Auditor**: Senior GST Reconciliation Systems Auditor & Forensic Engineer  
**Scope**: 2,000 Invoices (1,900 GSTR-2B records + 1,900 Purchase Register records)  
**Run ID Audited**: `919dfb98-e56a-49ad-9d57-ee038388628d`  
**Client**: RECONDESK SOLUTIONS PRIVATE LIMITED (`27ISKPK1273H1ZF`, Maharashtra)  
**Tax Period**: May 2026 (FY 2026-27)  
**Audit Status**: Complete Record-by-Record Comparison  

---

## 1. Executive Summary

A forensic, record-by-record comparison was conducted between the synthetic ground truth test dataset (`gstr2b_2000.xlsx`, `purchase_register_2000.xlsx`) and the actual production reconciliation outcomes exported in **`ReconDesk-report (6).xlsx`**.

ReconDesk achieved an overall **98.35% record-level accuracy (1,967 / 2,000 records correctly reconciled)**. The core matching engine demonstrated exceptional precision across exact matches, fuzzy invoice format normalizations, configured amount tolerances, and return-period date tolerances. 

However, the audit identified **two critical engine-level defects** and **one minor test-data construction quirk**:

1. **CRITICAL DEFECT 1 (False Positives in Phase 2 TYPO / GSTIN Fallback)**:
   Two GSTR-2B invoices (`BILL/1877` and `INV/1900`) that had **no counterpart in the Purchase Register** (true Missed ITC) were incorrectly captured by Phase 2 fallbacks and linked to unrelated PR invoices (`BILL/1978` and `INV/1920`) in **Review Required**. This occurred because the fallback allowed a 5% tax tolerance and 75% invoice similarity on sequential invoice numbers without invoking `is_sequential_series_mismatch()`.
2. **HIGH DEFECT 2 (GSTR-2B Parser Supplier Name Overwrite on URP Vendors)**:
   In the GSTR-2B parser's flat-to-portal aggregation (`_alt_group_by_supplier`), grouping flat rows by supplier GSTIN caused all 50 unregistered RCM rows (`URP`, `UNREGISTERED`, `URP/RCM`) to inherit the name of the *first* vendor parsed for that key (e.g. `Lakshmi Transport`). When later invoices under the same key belonged to `Maharashtra Advocates` or `Delhi Roadlines`, the engine detected a vendor name mismatch and routed **31 completely clean, identical URP invoices into Review Required** instead of auto-accepting them as clean L1 matches.
3. **MEDIUM DEFECT 3 (Test Data Boundary Truncation in Synthetic Generator)**:
   In the date discrepancy test block (invoices 1651–1750), two invoices dated 31st May (`PO/1693` and `PO/1750`) were generated with 0 days difference instead of a 1–2 day shift, because the generator clamped generated dates to the month end (`min(31, day + offset)`).

---

## 2. Quantitative Summary Metrics

### Source Data Integrity
- **Total GSTR-2B Rows**: 1,900
- **Total Purchase Register Rows**: 1,900
- **Total Unique Invoices Evaluated**: 2,000
- **True Shared Pairs (1 to 1800)**: 1,800
- **True GSTR-2B-Only Invoices (1801 to 1900 - Missed ITC)**: 100
- **True Purchase Register-Only Invoices (1901 to 2000 - ITC at Risk)**: 100
- **Missing / Invalid GSTINs**: 0
- **Missing / Invalid Dates**: 0
- **Negative Taxable Values**: 0
- **Tax Math Inconsistencies (> ₹0.05)**: 0

### Reconciliation Outcomes Comparison

| Classification Category | Ground Truth Expected | ReconDesk Actual (Report 6) | Discrepancy / Variance |
| :--- | :---: | :---: | :--- |
| **Matched Records (Total)** | **1,660** | **1,679** | **+19** (19 URP clean + 60 round-off accepted) |
| ↳ *Exact Clean (L1)* | 1,200 | 1,379 | +179 (100 date + 60 round-off + 19 URP) |
| ↳ *Fuzzy Invoice Normalization (L2)* | 300 | 300 | 0 (100% exact scenario match) |
| **Review Required** | **140** | **123** | **-17** (90 amount + 31 URP bug + 2 false positives) |
| **Missed ITC (GSTR-2B Only)** | **100** | **98** | **-2** (2 false positives captured into Review) |
| **ITC at Risk (PR Only)** | **100** | **98** | **-2** (2 false positives captured into Review) |
| **Duplicate Entries** | **0** | **0** | 0 |
| **Match Rate %** | **83.0%** | **88.4%** | +5.4% |

### Record-by-Record Accuracy Summary

| Audit Verdict | Record Count | % of Total | Description |
| :--- | :---: | :---: | :--- |
| **CORRECT** | **1,967** | **98.35%** | Correct counterpart identified and correctly classified |
| **FALSE POSITIVE** | **2** | **0.10%** | Unmatched invoices incorrectly cross-matched across vendors |
| **INCORRECT CLASSIFICATION** | **31** | **1.55%** | Clean URP matches routed to Review due to parser name overwrite |
| **AMBIGUOUS MATCHES** | **0** | **0.00%** | None |
| **UNVERIFIABLE RECORDS** | **0** | **0.00%** | None |
| **TOTAL** | **2,000** | **100.00%** | Full Ground Truth Universe |

---

## 3. Financial Impact Analysis

| Metric | Financial Amount | Explanation |
| :--- | :---: | :--- |
| **Taxable Value Incorrectly Matched (False Positives)** | **₹3,61,747.19** | `BILL/1877` (₹1,93,605.09) + `INV/1900` (₹1,68,142.10) |
| **ITC Incorrectly Matched (False Positives)** | **₹62,616.53** | `BILL/1877` (₹54,209.43) + `INV/1900` (₹8,407.10) |
| **Recoverable ITC Understated in Missed ITC** | **₹62,616.53** | GSTR-2B recoverable ITC diverted from Missed ITC to Review |
| **At-Risk ITC Understated in Compliance Risk** | **₹64,568.58** | Ineligible PR ITC (`BILL/1978` + `INV/1920`) diverted to Review |
| **Taxable Value Delayed in Review (URP Bug)** | **₹36,94,036.82** | 31 clean URP invoices forced into human review |
| **ITC Delayed in Review (URP Bug)** | **₹6,19,108.87** | Clean RCM ITC withheld from automatic claim approval |

---

## 4. Special Audits & Scenario Deep Dive

### A. Exact Clean Matches (1–1200)
- **Expected**: 1,200 invoices.
- **Actual**: 1,200 invoices matched at **EXACT 100% confidence**.
- **Result**: **100% Correct**. Zero discrepancies.

### B. Fuzzy Invoice Number Normalization (1201–1500)
- **Expected**: 300 invoices with formatting variations:
  - Leading zeros: `TAX/001204` vs `TAX/1204`
  - Slash vs dash: `INV-1201` vs `INV/1201`
  - Whitespace: `BILL / 1203` vs `BILL/1203`
  - Prefix omission: `PO/1202` vs `1202`
- **Actual**: All 300 invoices matched in **Matched Records** under **FUZZY (80% confidence)**.
- **Result**: **100% Correct**. Rationale drawer accurately reflected normalized identity without leaking false differences.

### C. Amount Mismatch & Rounding Tolerance Audit (1501–1650)
- **Expected**: 150 invoices with intentional taxable value deltas:
  - Small deltas (₹0.20, ₹0.80): 60 invoices.
  - Large deltas (₹1.80, ₹3.50, ₹7.20): 90 invoices.
- **Engine Rules**: Configured with `AMOUNT_TOLERANCE_L1_PAISE = 100` (₹1.00) for clean auto-acceptance.
- **Actual Breakdown**:
  - **₹0.20 diff** (24 invoices): Matched as **EXACT** (Clean auto-accept) ✅
  - **₹0.80 diff** (36 invoices): Matched as **EXACT** (Clean auto-accept) ✅
  - **₹1.80 diff** (31 invoices): Routed to **Review Required** (`taxable amount differs beyond auto-accept threshold`) ✅
  - **₹3.50 diff** (32 invoices): Routed to **Review Required** ✅
  - **₹7.20 diff** (27 invoices): Routed to **Review Required** ✅
- **Result**: **100% Correct**. Engine strictly followed configured business rules (₹1.00 auto-accept boundary).

### D. Date Discrepancy Audit (1651–1750)
- **Expected**: 100 invoices with 1–2 day filing delays within the same return period.
- **Engine Rules**: `DATE_TOLERANCE_L1_DAYS = 3`. Both dates in May 2026.
- **Actual**: All 100 invoices matched in **Matched Records** under **EXACT (100% confidence)**.
- **Result**: **100% Correct**. Same-month variance within 3 days is legitimately accepted without triggering false review flags.

### E. URP / Unregistered Supplier RCM Audit (1751–1800)
- **Expected**: 50 invoices across 3 unregistered vendors (`Lakshmi Transport`, `Maharashtra Advocates`, `Delhi Roadlines`) under `URP`, `UNREGISTERED`, or `URP/RCM`.
- **Actual**:
  - **19 invoices**: Matched cleanly under **EXACT (100%)** ✅
  - **31 invoices**: Erroneously routed to **Review Required** ❌
- **Forensic Root Cause**:
  In [`app/parsers/gstr2b_parser.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/parsers/gstr2b_parser.py) (`_alt_group_by_supplier`), flat rows are aggregated into portal structure keyed by `ctin`. For `URP`, the first row parsed was `Lakshmi Transport`. All subsequent rows under `URP` (including those whose raw Excel row had `Maharashtra Advocates`) had their `supplier_name` set to `Lakshmi Transport`.
  During matching in [`app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py), `l1_vendor_name_ok("Lakshmi Transport", "Maharashtra Advocates")` returned `False`, causing the engine to fail the zero-discrepancy gate and downgrade the pair to Review Required.

### F. Missed ITC & ITC at Risk Cross-Match Audit (1801–2000)
- **Expected**:
  - 100 invoices in GSTR-2B only (`1801` to `1900`) → Missed ITC.
  - 100 invoices in Purchase Register only (`1901` to `2000`) → ITC at Risk.
- **Actual**:
  - 98 invoices in Missed ITC ✅
  - 98 invoices in Compliance Risk ✅
  - **2 False Positive Cross-Matches in Review Required**:
    1. **Pair 1**: `BILL/1877` (2B) matched with `BILL/1978` (PR).
       - Supplier GSTIN: `29X00000009P1ZV` (identical)
       - Tax difference: ₹1,560.96 (within 2.8%, under 5% threshold)
       - Invoice similarity: 0.75 (`BILL1877` vs `BILL1978`)
       - Flaw: `is_sequential_series_mismatch` returned `True`, but Phase 2 `candidates_typo` did not check `is_sequential_series_mismatch`!
    2. **Pair 2**: `INV/1900` (2B) matched with `INV/1920` (PR).
       - Suppliers: `27X00000002P1Z6` vs `33X00000011P1ZC` (unrelated)
       - Tax: ₹8,407.10 vs ₹8,798.19 (4.4% diff, under 5% threshold)
       - Invoice similarity: 0.857
       - Flaw: Phase 2 `candidates_fuzzy_gstin` matched across states on near tax amount and similar invoice digits without verifying PAN equality or vendor name.

---

## 5. Detailed Findings & Defect Register

### FINDING-01 [CRITICAL] — Phase 2 Sequential Series Mismatch Leak in Typo Matching
- **Severity**: CRITICAL
- **Root Cause Location**: Production Code — [`app/services/reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/reconciliation.py#L2074-L2115)
- **Evidence**: GSTR-2B invoice `BILL/1877` matched PR invoice `BILL/1978` in Review Required.
- **Financial Impact**: Understates Missed ITC by ₹54,209.43 and ITC at Risk by ₹55,770.39.
- **Technical Explanation**: In Phase 2 `TYPO_MISMATCH` (lines 2074–2115), candidate search accepts pairs with same GSTIN, tax diff ≤ 5%, and invoice similarity ≥ 0.75. However, it does not call `is_sequential_series_mismatch(g_inv, p_inv)`. Sequential invoices in the same series (e.g. `1877` vs `1978`) that happen to have similar tax amounts are falsely paired.
- **Recommended Action**: Insert `if is_sequential_series_mismatch(g_inv_norm, p_inv_norm, g.get("invoice_number"), p.get("invoice_number")): continue` into Phase 2 `candidates_typo`.

### FINDING-02 [CRITICAL] — Phase 2 Cross-Vendor Fuzzy GSTIN Fallback False Positive
- **Severity**: CRITICAL
- **Root Cause Location**: Production Code — [`app/services/reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/reconciliation.py#L1994-L2072)
- **Evidence**: GSTR-2B invoice `INV/1900` (`27X00000002P1Z6`) matched PR invoice `INV/1920` (`33X00000011P1ZC`).
- **Financial Impact**: Understates Missed ITC by ₹8,407.10 and ITC at Risk by ₹8,798.19.
- **Technical Explanation**: `candidates_fuzzy_gstin` allows near-GSTIN matching, but when fallback indices are searched, unrelated suppliers in different states with coincidental amount proximity (₹8,407 vs ₹8,798) and sequential invoice formatting are linked without requiring PAN equality or vendor name confirmation.
- **Recommended Action**: Enforce `same_pan(gst, p_gst)` or vendor name similarity ≥ 0.70 inside `candidates_fuzzy_gstin`.

### FINDING-03 [HIGH] — GSTR-2B Alt-Schema Parser Overwrites Vendor Name on URP Groups
- **Severity**: HIGH
- **Root Cause Location**: Production Code — [`app/parsers/gstr2b_parser.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/parsers/gstr2b_parser.py#L1791-L1806)
- **Evidence**: 31 out of 50 URP invoices were routed to Review Required with `Vendor: not matched`.
- **Financial Impact**: ₹36.94 Lakhs of taxable value and ₹6.19 Lakhs of valid RCM ITC delayed in human review.
- **Technical Explanation**: `_alt_group_by_supplier` groups rows into `buckets[ctin]`. For URP vendors, `ctin` is `"URP"`, `"UNREGISTERED"`, or `"URP/RCM"`. The parser assigns `buckets[ctin]["trdnm"] = name` only once for the first row. All subsequent invoices for different unregistered entities under that key are stamped with the first entity's name.
- **Recommended Action**: In `_alt_group_by_supplier`, for URP keys (`is_urp_gstin(ctin)`), preserve the per-row party name on the individual invoice object or key the bucket by `(ctin, name)`.

### FINDING-04 [MEDIUM] — Synthetic Test Generator Month-End Date Clamping
- **Severity**: MEDIUM
- **Root Cause Location**: Test Data Generation Script
- **Evidence**: Invoices `PO/1693` and `PO/1750` in the date discrepancy test block had 0 days difference.
- **Technical Explanation**: The test data generator attempted to add an offset to the invoice date, but clamped dates exceeding 31 to 31st May on both sides, inadvertently producing identical dates.
- **Recommended Action**: In future test scripts, shift dates backwards when hitting the end of the month (e.g. `max(1, day - offset)`).

---

## 6. Generated Audit Artifacts

All detailed forensic Excel files have been generated and saved to `/Users/omkarkadam/Documents/ReconDesk/audit_2k/`:

1. **`forensic_audit_summary.xlsx`**: Executive dashboard with high-level KPI cards and reconciliation stats.
2. **`forensic_record_comparison.xlsx`**: Full 2,000-row record-by-record comparison table with 24 required audit columns.
3. **`false_positive_matches.xlsx`**: Granular breakdown of the 2 cross-matched false positive pairs.
4. **`false_negative_matches.xlsx`**: Granular breakdown of the 31 URP invoices misclassified into Review Required.
5. **`amount_mismatch_audit.xlsx`**: Audit of 150 amount mismatch records verifying the ₹1.00 tolerance gate.
6. **`date_discrepancy_audit.xlsx`**: Audit of 100 date discrepancy records verifying the 3-day tolerance gate.
7. **`missed_itc_audit.xlsx`**: Audit of 100 GSTR-2B-only records verifying recoverable ITC.
8. **`itc_at_risk_audit.xlsx`**: Audit of 100 PR-only records verifying Section 16(2)(aa) compliance risk.
9. **`audit_findings.md`**: This full markdown audit report.
