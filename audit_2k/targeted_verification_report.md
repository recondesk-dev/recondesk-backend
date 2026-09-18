# ReconDesk Forensic Audit: Targeted Technical Verification Report

**Audit Subject**: ReconDesk Reconciliation Engine — 2,000-Invoice Stress Test  
**Run ID**: `919dfb98-e56a-49ad-9d57-ee038388628d`  
**Report File**: `ReconDesk-report (6).xlsx`  
**Date**: September 18, 2026  
**Auditor**: Senior GST Systems Forensic Auditor & Reconciliation Engineer  
**Status**: Completed — Strict Audit Only (No Production Changes Deployed)

---

## 1. Executive Summary & Verification Matrix

This forensic verification was initiated to independently confirm or refute four specific critical issues identified during the 2,000-invoice audit of ReconDesk's reconciliation engine.

| Finding ID | Area / Scope | Reported Issue | Verification Status | Defect Classification | Financial / Record Scope |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VERIF-01** | Matching Engine | `BILL/1877` paired with `BILL/1978` (Missed ITC falsely matched to ITC at Risk under same supplier) | **CONFIRMED** | **Engine Defect** (`candidates_typo` missing sequential series guard) | ₹1,93,605.09 Taxable<br>₹54,209.43 ITC |
| **VERIF-02** | Matching Engine | `INV/1900` paired with `INV/1920` (Cross-vendor, cross-state false match pairing MH with TN) | **CONFIRMED** | **Engine Defect** (Fuzzy candidate loop allows cross-PAN match) | ₹1,68,142.10 Taxable<br>₹8,407.10 ITC |
| **VERIF-03** | Ingestion Parser | 31 URP invoices downgraded from Exact Match to Review Required | **CONFIRMED** | **Parser Defect (Category A)** (`ctin` dictionary key collision in `gstr2b_parser.py`) | 31 Records<br>₹54,37,887.89 Taxable |
| **VERIF-04** | Test Generator | Date test cases with 0 days difference instead of intended offset | **CONFIRMED** | **Test Suite Generator Defect** (`min(31, day + offset)` clamped to May 31) | 2 Records (`BILL/1693` & `TAX/1750`) |

---

## 2. Forensic Investigation: False Positive Matches (VERIF-01 & VERIF-02)

### 2.1 False Positive #1: `BILL/1877` (GSTR-2B) ↔ `BILL/1978` (PR)

#### Record Comparison:
| Field | GSTR-2B Source (Row 1877) | Purchase Register Source (Row 1878) | Report 6 Outcome (Review Required Row 84) |
| :--- | :--- | :--- | :--- |
| **Invoice Number** | `BILL/1877` | `BILL/1978` | Paired together as a single discrepancy |
| **Supplier GSTIN** | `29X00000009P1ZV` | `29X00000009P1ZV` | Matched (Karnataka Supplier 9) |
| **Supplier Name** | Supplier 9 | Supplier 9 | Matched |
| **Invoice Date** | 2026-05-04 | 2026-05-06 | 2 days difference |
| **Taxable Value** | ₹1,93,605.09 | ₹1,99,179.98 | Difference: ₹5,574.89 (2.80%) |
| **IGST Amount** | ₹54,209.43 | ₹55,770.39 | Difference: ₹1,560.96 (2.80%) |
| **Total Tax** | ₹54,209.43 | ₹55,770.39 | Difference: ₹1,560.96 (2.80%) |
| **Total Invoice Value** | ₹247,814.52 | ₹254,950.37 | Difference: ₹7,135.85 (2.80%) |
| **Ground Truth Category** | **Missed ITC (2B Only)** | **ITC at Risk (PR Only)** | **Review Required (Discrepancy Match)** |

#### Code Execution Path & Root Cause:
1. **Module**: `recondesk-backend/app/services/reconciliation.py` inside `execute_phase2_and_3` → `candidates_typo` (lines 2074–2115).
2. **Evaluation Metrics**:
   - `diff_pct = abs(54209.43 - 55770.39) / max(54209.43, 55770.39) = 0.02798` (2.80%). The candidate condition `diff_pct <= 0.05` (5%) evaluates to **TRUE**.
   - `date_diff = abs(2026-05-06 - 2026-05-04) = 2 days`. The condition `date_diff <= 45` evaluates to **TRUE**.
   - `sim = difflib.SequenceMatcher(None, "BILL1877", "BILL1978").ratio() = 6/8 = 0.7500`. The condition `sim >= 0.75` evaluates to **TRUE**.
3. **Missing Guard**:
   In `reconciliation.py`, helper function `is_sequential_series_mismatch("BILL1877", "BILL1978")` returns `True` because the trailing digits represent distinct serial numbers (1877 vs 1978). However, `candidates_typo` **does not invoke this guard**.
4. **Conclusion**:
   The engine incorrectly married a genuine unclaimed supplier invoice (`BILL/1877`) with a completely separate supplier invoice recorded in accounting (`BILL/1978`).

---

### 2.2 False Positive #2: `INV/1900` (GSTR-2B) ↔ `INV/1920` (PR)

#### Record Comparison:
| Field | GSTR-2B Source (Row 1900) | Purchase Register Source (Row 1820) | Report 6 Outcome (Review Required Row 85) |
| :--- | :--- | :--- | :--- |
| **Invoice Number** | `INV/1900` | `INV/1920` | Paired together as a single discrepancy |
| **Supplier GSTIN** | `27X00000002P1Z6` (Maharashtra) | `33X00000004P1Z3` (Tamil Nadu) | Cross-state mismatch (27 vs 33) |
| **Supplier Name** | Supplier 2 | Supplier 4 | Unrelated entities |
| **Invoice Date** | 2026-05-11 | 2026-05-17 | 6 days difference |
| **Taxable Value** | ₹1,68,142.10 | ₹1,75,963.75 | Difference: ₹7,821.65 (4.45%) |
| **Tax Head** | CGST ₹4,203.55 + SGST ₹4,203.55 | IGST ₹8,798.19 | Intrastate vs Interstate mismatch |
| **Total Tax** | ₹8,407.10 | ₹8,798.19 | Difference: ₹391.09 (4.45%) |
| **Total Invoice Value** | ₹176,549.20 | ₹184,761.94 | Difference: ₹8,212.74 (4.45%) |
| **Ground Truth Category** | **Missed ITC (2B Only)** | **ITC at Risk (PR Only)** | **Review Required (Discrepancy Match)** |

#### Code Execution Path & Root Cause:
1. **Module**: `reconciliation.py` Phase 2 candidate matching (`candidates_typo` / `candidates_gstin_mismatch`).
2. **Evaluation Metrics**:
   - `sim = SequenceMatcher(None, "INV1900", "INV1920").ratio() = 6/7 = 0.8571` (≥ 0.75).
   - `diff_pct = abs(8407.10 - 8798.19) / 8798.19 = 0.0445` (4.45% ≤ 5.0%).
   - `date_diff = 6 days` (≤ 45 days).
3. **Flaw Mechanism**:
   When cross-GSTIN candidate generation is attempted, the engine checks whether the invoice numbers look similar and the tax difference is under 5%. However, it does not enforce **PAN equality** (`gstin1[2:12] == gstin2[2:12]`). As a result, two completely unrelated businesses in different states were matched.

---

### 2.3 Financial & Statutory Impact of False Positives

| Component | FP-01 (`BILL/1877` vs `1978`) | FP-02 (`INV/1900` vs `1920`) | Combined Impact | Statutory Implication |
| :--- | :--- | :--- | :--- | :--- |
| **GSTR-2B Taxable Value** | ₹1,93,605.09 | ₹1,68,142.10 | **₹3,61,747.19** | **Cash Leakage**: Genuine missed ITC is hidden from the CA/tax team. |
| **GSTR-2B Tax / ITC Amount** | ₹54,209.43 | ₹8,407.10 | **₹62,616.53** | Direct loss of claimable input tax credit. |
| **PR Taxable Value** | ₹1,99,179.98 | ₹1,75,963.75 | **₹375,143.73** | Ineligible purchase masked as an invoice typo. |
| **PR Tax / Ineligible ITC** | ₹55,770.39 | ₹8,798.19 | **₹64,568.58** | **Section 16(2)(aa) Risk**: Incurring interest @ 18% p.a. + 24% penalty. |

> **Statutory Takeaway for CA**: By misclassifying these 4 independent invoices as 2 "Review Required" discrepancy pairs, the system artificially suppresses the **Missed ITC** count by 2 and the **ITC at Risk** count by 2.

---

## 3. Forensic Investigation: URP Ingestion Parser Defect (VERIF-03)

### 3.1 Verification Summary
- **Total URP Records in Test Suite**: 50 invoices (GSTIN = `URP`, `UNREGISTERED`, or `URP/RCM`).
- **Reconciliation Engine Report Outcome**:
  - **Matched Records (Exact Match)**: 19 invoices (38.0%)
  - **Review Required**: 31 invoices (62.0%)
- **Taxable Value Downgraded**: **₹54,37,887.89**
- **Tax Value Downgraded**: **₹3,98,241.12**
- **Classification**: **CONFIRMED GENUINE PARSER DEFECT (Category A)**

### 3.2 Root Cause Analysis: Dictionary Key Collision in Parser
In `recondesk-backend/app/parsers/gstr2b_parser.py` (lines 1791–1806), flat Excel rows are grouped by `ctin` into supplier buckets:

```python
# app/parsers/gstr2b_parser.py:1791-1806
buckets = {}
for row in rows:
    ctin = row.get("ctin")
    if ctin not in buckets:
        buckets[ctin] = {
            "trdnm": row.get("trdnm"),  # <-- LOCKED ON FIRST ROW
            "inv": []
        }
    buckets[ctin]["inv"].append(row)
```

Because unregistered suppliers subject to Reverse Charge Mechanism (RCM) share pseudo-GSTIN identifiers (`URP`, `UNREGISTERED`, `URP/RCM`), the parser assumes that **1 `ctin` equals 1 legal entity**.
- The first URP invoice processed locked `trdnm` to `"Lakshmi Transport"`.
- All subsequent 47 distinct URP vendors (e.g., `"City Cleaners"`, `"Apex Courier"`, `"National Security"`) had their trade names **overwritten with `"Lakshmi Transport"`**.

### 3.3 Downstream Effect in Reconciliation Engine
During reconciliation in `app/services/matcher.py`:
- Invoices had identical invoice numbers, identical dates, and identical amounts between GSTR-2B and PR.
- However, zero-discrepancy Level 1 matching enforces:
  ```python
  if not l1_vendor_name_ok(g_vendor, p_vendor):
      # Fails exact match -> Downgraded to Review Required
  ```
- Because `g_vendor` was corrupted by the parser to `"Lakshmi Transport"` while `p_vendor` was the true vendor name (`"City Cleaners"`), `l1_vendor_name_ok` failed.
- The 31 invoices were pushed into **Review Required** with the rationale:
  `"GSTIN: exact | Invoice#: exact | Amount: exact | Date: exact | Vendor: not matched"`.

---

## 4. Forensic Investigation: Date Discrepancy Test Suite (VERIF-04)

### 4.1 Verification Summary
- **Target Invoices**: `BILL/1693` and `TAX/1750` in the 100-invoice date tolerance test suite (range 1651–1750).
- **GSTR-2B Date**: `2026-05-31`
- **Purchase Register Date**: `2026-05-31`
- **Actual Date Difference in Excel**: **0 days (Identical)**
- **Reconciliation Engine Outcome**: **Matched Records (Exact Match)**
- **Classification**: **CONFIRMED TEST SUITE GENERATOR DEFECT (Engine is 100% Correct)**

### 4.2 Why the Clamping Occurred in Synthetic Data Generation
The synthetic test generator script utilized calendar day arithmetic with a month-end clamp:
```python
# Flawed generator logic:
pr_day = min(31, base_day + offset)
gstr_day = min(31, base_day)
```
When `base_day` was near the end of May (e.g., May 28 or May 31) and an offset was added, `min(31, day + offset)` clamped both the GSTR date and the PR date to day 31 (`2026-05-31`), collapsing the intended date difference to **zero**.

The ReconDesk matching engine behaved with 100% mathematical accuracy: given two identical dates (`2026-05-31`), it matched them as an Exact Match.

---

## 5. Artifact Deliverables Summary

The following three forensic verification Excel workbooks have been generated and validated in `audit_2k/`:

1. **`false_positive_verification.xlsx`**:
   - `Executive_Summary`: Status, ground truth categories, and financial exposure.
   - `FP1_BILL1877_vs_BILL1978`: Record-by-record comparison, similarity ratios (0.7500), and code path analysis.
   - `FP2_INV1900_vs_INV1920`: Cross-vendor comparison, state code mismatch (27 MH vs 33 TN), and tax head analysis.
   - `Financial_Impact`: Detailed tax breakdown of the ₹3,61,747.19 taxable and ₹62,616.53 ITC masked by the engine.

2. **`urp_parser_verification.xlsx`**:
   - `URP_Summary`: Overall statistics (50 total, 19 matched, 31 downgraded).
   - `All_50_URP_Invoices`: Complete audit trail of all 50 URP records including raw GSTR names, overwritten parser names, and report rationales.
   - `The_31_Downgraded_Cases`: Specific forensic detail on the 31 downgraded records totaling ₹54.37L taxable value.
   - `Code_Analysis`: Side-by-side inspection of `gstr2b_parser.py` and `matcher.py`.

3. **`date_test_verification.xlsx`**:
   - `Date_Test_Summary`: Analysis of all 100 date test cases (98 valid, 2 clamped).
   - `All_100_Date_Cases`: Full list showing intended offsets, actual offsets, and report matching results.
   - `BILL1693_and_TAX1750`: Direct proof showing identical `2026-05-31` dates.
   - `Generator_Fix`: Corrected code implementation using `datetime.timedelta`.

---

## 6. Auditor's Formal Recommendations

*(For implementation after audit sign-off; no production changes made during audit)*

1. **Fix `candidates_typo` Guard**:
   In `reconciliation.py:2074-2115`, invoke `is_sequential_series_mismatch(g_inv, p_inv)` before admitting any candidate into the typo pool. If sequential numbers differ, reject the match.
2. **Enforce PAN Equality on Fuzzy Candidate Matching**:
   In cross-GSTIN candidate loops, mandate `g_gstin[2:12] == p_gstin[2:12]`. Never allow cross-vendor matching between completely different PANs.
3. **Fix URP Ingestion Bucketing**:
   In `gstr2b_parser.py:1791-1806`, group by `(ctin, trdnm)` when `ctin` is `URP`, `UNREGISTERED`, or `URP/RCM` to prevent trade name overwriting.
