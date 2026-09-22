# Phase 5.7 REM-04 Audit: Automated Bilateral Credit Note (CDNR) Matching Phase

**Author**: Senior Software Engineer / Auditor  
**Date**: September 22, 2026  
**Status**: AUDITED & PLANNED  
**Scope**: `recondesk-backend/app/services/reconciliation.py`, `recondesk-backend/app/matching/engine.py`, `recondesk-backend/app/worker/reconciliation_task.py`, `recondesk-backend/app/services/reconciliation_record_adapter.py`, `recondesk-backend/tests/test_cdn_reconciliation.py`

---

## 1. Executive Summary & Problem Statement

In **Phase 5.7 Audit [FINDING-M01]**, an audit of the core reconciliation engine identified that Credit Notes (CDNR) and Debit Notes in the Purchase Register and GSTR-2B are quarantined from primary invoice matching to prevent distorting net match rates. However:
1. **Lack of Automated Bilateral CDNR Pairing**:
   While basic exact-invoice-number credit note matches can occur in Phase 1 if the PR row has an identical `invoice_number_normalized`, ERP purchase registers often store credit notes with:
   - `note_number` (the actual Credit Note number, e.g. `CN-2023-01`)
   - `invoice_number` / `original_invoice_number` (the reference to the original invoice, e.g. `INV-1001`)
   GSTR-2B CDNR records store the credit note number in `nt_num` / `invoice_number` and the original invoice in `oinum` / `original_invoice_number`.
2. **Current Defect**:
   Because primary matching only compares `invoice_number_normalized` against `invoice_number_normalized`:
   - GSTR `nt_num` fails to match PR `invoice_number` (which points to the original invoice).
   - PR credit notes fail to match and drop into `state.unmatched_notes`.
   - GSTR credit notes fail to match and drop into `state.missed_itc` (with `requires_reversal=True`).
3. **CA Workflow Impact**:
   Chartered Accountants and tax teams must manually review and verify every credit note in the "Unmatched Notes" tab instead of having automated bilateral pairing within statutory ₹1 tolerance.

---

## 2. Technical Architecture & Design

### 2.1 New Dedicated Matching Phase: `execute_credit_note_reconciliation`
We introduce a dedicated bilateral Credit Note Reconciliation Phase that executes after Phase 1 and before residual quarantine:

```
[Phase 1: Strict Clean Invoice Matching]
                   ↓
[Dedicated Phase: Bilateral Credit Note (CDNR) Matching]  <-- (NEW REM-04)
  1. Exact Note Number Match (GSTR nt_num == PR note_number)
  2. Cross Note-to-Original-Invoice Match (GSTR oinum == PR invoice_number)
  3. Format-Variant / Alphanumeric Stripped Note Match
  4. Directional Semantic & Magnitude Amount Verification (<= ₹1.00 tolerance)
                   ↓
[Phase 2 & 3: Review Resolution & Financial Buckets]
                   ↓
[Residual Quarantine: Truly Unmatched PR Notes -> unmatched_notes]
```

### 2.2 Matching Pathways in `execute_credit_note_reconciliation`

For any unconsumed GSTR note (`_is_note_document(g)`) and unconsumed PR note (`is_pr_note_quarantine(p) or _is_note_document(p)`):
1. **GSTIN Alignment**: Must belong to the exact same supplier GSTIN.
2. **Identifier Cross-Referencing**:
   - **Pathway A (Exact Note Number)**:
     `normalize_invoice(g_note_number) == normalize_invoice(p_note_number)`
   - **Pathway B (GSTR Note Number == PR Invoice Number)**:
     `normalize_invoice(g_note_number) == normalize_invoice(p_inv_number)`
   - **Pathway C (GSTR Original Invoice == PR Invoice Number)**:
     `g_orig_inv` is present and `normalize_invoice(g_orig_inv) == normalize_invoice(p_inv_number)`
   - **Pathway D (Format-Variant Stripped Note Number)**:
     Prefix-stripped comparison (ignoring "CN", "CRN", "DN", "DBN", leading zeros) under identical supplier GSTIN and matching amount.
3. **Financial Validation**:
   - Total tax / taxable value match within ₹1 tolerance (`TOTAL_TOLERANCE_PAISE = 100`) using magnitude comparison (`abs(abs(g_amt) - abs(p_amt)) <= tolerance`).
   - Semantic directional compatibility (`are_document_types_compatible` / `validate_note_pairing_semantics`).
4. **Resolution**:
   - Appended to `state.clean_matched` with `doc_type = "CREDIT_NOTE"` (or `"DEBIT_NOTE"`), `is_credit_note = True`, `match_level = 1` or `2`.
   - Added to `state.consumed_gstr_ids` and `state.consumed_pr_ids`.
   - Prevented from entering `state.unmatched_notes` and `state.missed_itc`.

---

## 3. Preservation of Critical Statutory Invariants

1. **Bucket Exclusivity Invariant**:
   `matched_count + missed_itc_count + review_gstr_count == total_gstr`
   Consuming the GSTR note during credit note reconciliation increases `matched_count` by 1 and prevents it from entering `missed_itc_count`, preserving exact arithmetic equality.
2. **Residual Quarantine Integrity**:
   Genuinely unmatched PR notes (e.g. supplier never uploaded CDNR to GSTR-1) continue to be safely quarantined to `state.unmatched_notes` and never leak into `wrongful_itc_risk`.
3. **Unmatched GSTR Notes**:
   GSTR credit notes without PR counterpart continue to land in `missed_itc` flagged with `requires_reversal = True` for audit follow-up.
4. **Zero Database Migrations**:
   All operations leverage existing schema columns in `reconciliation_run` and outcome models.

---

## 4. Audit Verdict
**PROCEED TO IMPLEMENTATION PLAN**. The dedicated phase cleanly solves [FINDING-M01] without altering primary invoice match rates or breaking statutory invariants.
