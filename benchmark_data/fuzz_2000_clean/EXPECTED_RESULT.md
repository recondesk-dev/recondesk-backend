# ReconDesk GSTR-1 Clean Adversarial Benchmark — 2,000 Records

Supplier GSTIN: `27ISKPK1273H1ZF`  
Period: `07-2025`  
Prior Period: `06-2025`  
Seed: `20260911`

## Objective
Rigorous stress-testing of outward supply reconciliation with 2,000 synthetic records and mathematically disjoint, controlled mutations across all GST sections.

## Population Composition
- **Total Sales Register Records**: 2,000
  - B2B Invoices: 1,780 (`INV/25-26/0001` to `INV/25-26/1780`)
  - Credit Notes: 20 (`CN/25-26/0001` to `CN/25-26/0020`)
  - B2CL Large Invoices: 100 (`B2CL/25-26/0001` to `B2CL/25-26/0100`)
  - B2CS Small Invoices: 100 (`B2CS/25-26/0001` to `B2CS/25-26/0100`)
- **GSTR-1 Population**:
  - Clean Control: Exactly mirrors Sales Register (1,780 B2B, 20 CDNR, 100 B2CL, B2CS table aggregate)
  - Prior June GSTR-1: Contains `INV/25-26/BA0001` (Taxable ₹50,000.00, 18% IGST ₹9,000.00)

## Mechanically Derived Mutation Counts
```json
{
  "missing_b2b": 20,
  "duplicate_b2b": 15,
  "extra_b2b_duplicate_representation": 20,
  "b2b_taxable_mismatch": 25,
  "b2b_tax_mismatch": 25,
  "date_mismatch": 15,
  "gstin_mismatch": 15,
  "rate_mismatch": 15,
  "invoice_format_variation": 30,
  "credit_note_missing": 5,
  "credit_note_amount_mismatch": 5,
  "b2cl_taxable_mismatch": 10,
  "b2cs_aggregate_mismatch": 1,
  "valid_b2ba": 1,
  "invalid_b2ba": 1
}
```

## Expected Metric Verifications
- **Missing Records (G1M1)**:
  - 20 missing B2B invoices (`INV/25-26/0101` to `INV/25-26/0120`)
  - 15 unfiled B2B invoices filed under dummy GSTIN `27ZZZPK9999A1ZQ` (`INV/25-26/0221` to `INV/25-26/0235`)
  - 5 missing Credit Notes (`CN/25-26/0001` to `CN/25-26/0005`), flagged with document-aware credit note terminology
  - **Total Missing Records**: **40** (35 invoices + 5 credit notes)

- **Extra in GSTR-1 (G1M2)**:
  - 15 duplicate B2B copies (`INV/25-26/0121` to `INV/25-26/0135`)
  - 20 extra B2B representations (`INV/25-26/0136` to `INV/25-26/0155`)
  - 15 unmatched GSTR-1 invoices under dummy GSTIN `27ZZZPK9999A1ZQ`
  - Zero cross-table collisions (prior `INV/25-26/BA0001` is strictly separated from fresh July invoices)
  - **Total Extra Records**: **50**

- **Amount Mismatches (G1M3)**:
  - 25 B2B taxable mismatches (+₹10,000 each)
  - 25 B2B tax amount mismatches
  - 10 B2CL taxable mismatches (+₹15,000 each)
  - 5 Credit Note taxable mismatches (+₹5,000 each)
  - 1 B2CS aggregate mismatch (+₹1,000 taxable on Table 7)
  - **Total Amount Mismatches**: **66** (65 document-level + 1 aggregate)

- **Rate Mismatches (G1M5)**:
  - Exactly **15** rate swaps (`INV/25-26/0236` to `INV/25-26/0250`)

- **Date Mismatches**:
  - Exactly **15** invoices (`INV/25-26/0206` to `INV/25-26/0220`) shifted by +10 days (outside L1/L2 tolerance, matched at Level 3 with date discrepancy noted)

- **Invoice Format Variations**:
  - Exactly **30** invoices (`INV/25-26/0251` to `INV/25-26/0280`) matched via normalization and multi-tier fuzzy matching with sequential series guard

- **Series Continuity (G1M8)**:
  - **Duplicate Invoices**: Exactly **35** duplicate pairs in GSTR-1 (15 from `duplicate_b2b` + 20 from `extra_b2b`)
  - **Duplicate Message Source**: Accurately reports `"appears 2 times in GSTR-1"`

- **Amendments (G1M11)**:
  - Valid B2BA (`INV/25-26/BA0001`): Successfully verified against June original; only current-period delta (+₹5,000.00 taxable, +₹900.00 IGST) affects aggregation
  - Invalid B2BA (`NONEXIST-999`): Flagged as `G1M_011_UNMATCHED_AMENDMENT` and excluded from turnover

## Financial Totals & Expected Tie-Out Variances
- **Clean Sales Register Baseline**:
  - Taxable Value: ₹187,160,000.00
  - IGST: ₹26,303,160.00
  - CGST: ₹1,421,127.50
  - SGST: ₹1,421,127.50
- **Clean GSTR-3B Baseline**:
  - Reconciles 100% to Clean Sales Register (Zero Variance)
- **Net GSTR-1 Evaluated Liability**:
  - Taxable Value: ₹189,081,000.00
  - IGST: ₹26,494,860.00
  - CGST: ₹1,469,965.00
  - SGST: ₹1,469,965.00
- **Expected Tie-Out Variances**:
  - Taxable Variance: **₹1,921,000.00**
  - IGST Variance: **₹191,700.00**
  - CGST Variance: **₹48,837.50**
  - SGST Variance: **₹48,837.50**
