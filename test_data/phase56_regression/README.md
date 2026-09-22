# ReconDesk Phase 5.6 Regression Test Dataset

## 1. Overview & Objective

This controlled regression-test dataset validates the **Phase 5.6 reconciliation engine hardening**, specifically addressing:
1. **Invoice vs. Credit Note Disambiguation**: Ensuring ordinary invoices with prefix `CRN-` (`CRN-8814`) are not misclassified as credit notes, while genuine credit notes (`CRN-8812`) reconcile seamlessly without sign conflicts.
2. **False-Positive Prevention (FP-01 Sequential Series Guard)**: Preventing distinct sequential invoices from the same supplier (`BILL/1877` vs. `BILL/1978`) from falsely matching under fuzzy OCR/typo thresholds.
3. **False-Positive Prevention (FP-02 Cross-Vendor Identity Gate)**: Preventing cross-supplier, cross-state fuzzy matches (`INV/1900` MH vs. `INV/1920` TN) across different legal entities.
4. **URP Parser Integrity & Vendor Isolation**: Guaranteeing that unregistered / URP invoices (`URP-101`, `URP-102`, `URP-103`) retain distinct supplier identities without collapsing into a single vendor block or overwriting trade names.
5. **Credit Note Typo Isolation**: Verifying that a single-digit credit note variant (`CRN-8813`) does not falsely match an existing credit note (`CRN-8812`), remaining in ITC at Risk (or routing to Review Required under head-to-head evaluation).

All data in this suite is **strictly synthetic**, using validated check-digit GSTINs and realistic statutory GST values for the return period **May 2026 (`2026-05`)**.

---

## 2. Dataset Files & Formats

The dataset is provided in both Excel (`.xlsx`) and interchange formats (`.csv` / `.json`):

| File Path | Format | Sheets / Content | Description |
| :--- | :--- | :--- | :--- |
| `test_data/phase56_regression/purchase_register_phase56.xlsx` | Excel (`.xlsx`) | Sheet: `Purchases` | Canonical 9-record Purchase Register workbook. Contains Title block (Rows 1–3) and Table headers (Row 4). |
| `test_data/phase56_regression/purchase_register_phase56.csv` | CSV (`.csv`) | Standard CSV | Flat export of the 9 PR records with standard ReconDesk headers. |
| `test_data/phase56_regression/gstr2b_phase56.xlsx` | Excel (`.xlsx`) | Sheets: `B2B`, `B2B-CDNR` | Canonical 7-record GSTR-2B portal export. 6 regular invoices in `B2B`, 1 credit note in `B2B-CDNR`. |
| `test_data/phase56_regression/gstr2b_phase56.json` | JSON (`.json`) | GSTN GSTR-2B v1.0 | Official GST portal schema JSON payload with nested `b2b` and `cdnr` document structures. |
| `test_data/phase56_regression/manifest.json` | JSON (`.json`) | Machine-Readable Metadata | Complete JSON manifest containing metadata, schema definitions, and expected outcomes for each case. |

---

## 3. Entity & Period Specifications

- **Buyer / Client GSTIN**: `27ISKPK1273H1ZF` (Maharashtra, State Code 27)
- **Buyer Legal / Trade Name**: `RECONDESK`
- **Filing Return Period**: `052026` (`May 2026` / `2026-05`)
- **Dedicated Test Suppliers**:
  1. `27TESTS0001A1Z7` — **Alpha Test Solutions Pvt Ltd** (Maharashtra, State 27)
  2. `27TESTS0002B1Z4` — **Beta Engineering Works** (Maharashtra, State 27)
  3. `33TESTS0004D1Z5` — **Delta Southern Components** (Tamil Nadu, State 33)
  4. `URP` — **City Logistics & Courier** (Unregistered Provider)
  5. `URP` — **Lakshmi Transport Services** (Unregistered Provider)
  6. `URP` — **National Security Guard Services** (Unregistered Provider)

---

## 4. Ground Truth Reconciliation Matrix

When both files are imported and reconciled together under filing period `May 2026`, the engine produces the following exact results:

### Summary Statistics
- **Total Purchase Register Records**: 9
- **Total GSTR-2B Records**: 7
- **Matched Records (Clean Match)**: 4 (100% precision)
- **Review Required Records**: 0 (0 false discrepancies)
- **Missed ITC Records (GSTR-2B Only)**: 3
- **ITC at Risk Records (PR Only)**: 5
- **Duplicate Entry Count**: 0
- **Sanity Check Status**: `PASSED`

### Case-by-Case Breakdown

| Case / Control ID | Document Number | Doc Type | Supplier GSTIN | Supplier Name | In PR? | In 2B? | Taxable (PR) | Taxable (2B) | Expected Outcome | Engine Protection / Rationale |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| **CTRL-01** | `INV-5601` | `INVOICE` | `27TESTS0001A1Z7` | Alpha Test Solutions Pvt Ltd | Yes | Yes | ₹1,00,000.00 | ₹1,00,000.00 | **Clean Match** (Level 1) | Baseline exact compliant invoice match. |
| **CASE-01** | `CRN-8812` | `CREDIT_NOTE` | `27TESTS0001A1Z7` | Alpha Test Solutions Pvt Ltd | Yes | Yes | -₹50,000.00 | ₹50,000.00 | **Clean Match** (Level 1 Credit Note) | Genuine credit note in PR (negative taxable) matches GSTR-2B CDNR credit note without sign conflict. |
| **CASE-02** | `CRN-8813` | `CREDIT_NOTE` | `27TESTS0001A1Z7` | Alpha Test Solutions Pvt Ltd | Yes | No | -₹52,000.00 | — | **ITC at Risk** (PR Only) | Single-digit variant of `CRN-8812`. Does not match `CRN-8812`. (In head-to-head test without `CRN-8812` in PR, routes to Review Required `TYPO_MISMATCH`). |
| **CASE-03** | `CRN-8814` | `INVOICE` | `27TESTS0001A1Z7` | Alpha Test Solutions Pvt Ltd | Yes | Yes | ₹50,000.00 | ₹50,000.00 | **Clean Match** (Level 1 Invoice) | Delimiter-aware detection: Ordinary invoice with `CRN-` prefix and positive amount is recognized as `INVOICE` and matched cleanly. |
| **CASE-04A** | `URP-101` | `INVOICE` | `URP` | City Logistics & Courier | Yes | Yes | ₹10,000.00 | ₹10,000.00 | **Clean Match** (Level 1 URP) | Unregistered supplier invoice matches under deterministic `(ctin, supplier_name)` identity preservation. |
| **CASE-04B** | `URP-102` | `INVOICE` | `URP` | Lakshmi Transport Services | Yes | No | ₹15,000.00 | — | **ITC at Risk** (PR Only) | Unregistered supplier invoice in PR only. Retains distinct vendor identity without collision. |
| **CASE-04C** | `URP-103` | `INVOICE` | `URP` | National Security Guard Services | No | Yes | — | ₹20,000.00 | **Missed ITC** (2B Only) | Unregistered supplier invoice in GSTR-2B only. Retains distinct vendor identity without name-overwriting. |
| **CASE-05** | `CRN-UNMATCHED-01`| `CREDIT_NOTE` | `27TESTS0001A1Z7` | Alpha Test Solutions Pvt Ltd | Yes | No | -₹25,000.00 | — | **ITC at Risk** (PR Only) | Deliberately unfiled credit note. Stays in ITC at Risk and preserves `doc_type: CREDIT_NOTE`. |
| **CTRL-02** | `BILL/1877` (2B)<br>`BILL/1978` (PR) | `INVOICE` | `27TESTS0001A1Z7` | Alpha Test Solutions Pvt Ltd | Yes | Yes | ₹1,99,179.98 | ₹1,93,605.09 | **FP-01 Guarded**<br>(2B → Missed ITC<br>PR → ITC at Risk) | Mismatched sequential invoices in same series (sim=0.75, tax diff=2.8%). Blocked from fuzzy match by `is_sequential_series_mismatch`. |
| **CTRL-03** | `INV/1900` (2B)<br>`INV/1920` (PR) | `INVOICE` | 2B: `27TESTS0002B1Z4`<br>PR: `33TESTS0004D1Z5` | 2B: Beta Engineering<br>PR: Delta Southern | Yes | Yes | ₹1,75,963.75 | ₹168,142.10 | **FP-02 Guarded**<br>(2B → Missed ITC<br>PR → ITC at Risk) | Cross-supplier, cross-state invoices (MH vs TN). Blocked from fuzzy match by `supplier_identity_compatible`. |

---

## 5. Schema & Header Specifications

### Purchase Register Sheet: `Purchases`
The Purchase Register parser accepts third-party, ERP, and Tally exports.
- **Row 1**: Metadata Title Block (e.g. `GSTIN of Recipient: 27ISKPK1273H1ZF`, `Legal Name: RECONDESK`, `Filing Period: May 2026`)
- **Rows 2–3**: Blank or header spacing
- **Row 4**: Table Column Headers:
  - `Date`: Voucher / transaction date (`DD-MM-YYYY`)
  - `Particulars`: Supplier / Party trade name
  - `Voucher Type`: Document classification (`Purchase` for invoices, `Credit Note` for notes)
  - `Vch No.`: Accounting voucher serial number
  - `Supplier Invoice No.`: Supplier's invoice or credit note reference number
  - `Supplier Invoice Date`: Invoice issuance date (`DD-MM-YYYY`)
  - `Supplier GSTIN`: Supplier GST identification number or `URP`
  - `Taxable Amount`: Net taxable amount (positive for invoices, **negative** for credit notes)
  - `Integrated Tax`: IGST amount
  - `Central Tax`: CGST amount
  - `State Tax`: SGST amount
  - `Total Amount`: Gross invoice value including taxes

### GSTR-2B Workbook: Sheets `B2B` & `B2B-CDNR`
Follows the official GST portal Excel export convention.
- **Row 1**: Title Block (e.g. `GSTIN of recipient: 27ISKPK1273H1ZF`, `Legal Name: RECONDESK`, `Return Period: May 2026`)
- **Rows 2–3**: Blank rows
- **Row 4**: Column Headers:
  - **Sheet `B2B`**: `GSTIN of supplier`, `Trade/Legal name`, `Invoice number`, `Invoice type`, `Invoice Date`, `Invoice Value`, `Place of supply`, `Reverse Charge`, `Rate (%)`, `Taxable Value`, `Integrated Tax`, `Central Tax`, `State/UT Tax`, `Cess`
  - **Sheet `B2B-CDNR`**: `GSTIN of supplier`, `Trade/Legal name`, `Note Number`, `Note Type`, `Note Date`, `Note Value`, `Place of supply`, `Reverse Charge`, `Rate (%)`, `Taxable Value`, `Integrated Tax`, `Central Tax`, `State/UT Tax`, `Cess`

---

## 6. How to Run Reconciliation Verification

### Option A: Using the Python Pipeline Script
Run the automated end-to-end verification script from the repository root:

```bash
python3 -c "
import io
from datetime import date
from app.parsers.purchase_register_parser import parse_purchase_register
from app.parsers.gstr2b_excel import load_gstr2b_upload_payload
from app.parsers.gstr2b_parser import parse_gstr2b
from app.services.reconciliation_record_adapter import gstr_db_row_to_matcher_row, pr_db_row_to_matcher_row
from app.matching.engine import run_bidirectional_reconciliation

with open('test_data/phase56_regression/purchase_register_phase56.xlsx', 'rb') as f:
    pr_parsed = parse_purchase_register(f.read(), 'purchase_register_phase56.xlsx')

with open('test_data/phase56_regression/gstr2b_phase56.xlsx', 'rb') as f:
    gstr_payload = load_gstr2b_upload_payload(f.read(), 'gstr2b_phase56.xlsx')
    gstr_parsed = parse_gstr2b(gstr_payload)

pr_matcher = [pr_db_row_to_matcher_row({'id': f'pr_{i}', 'record_data': r}) for i, r in enumerate(pr_parsed['records'])]
gstr_matcher = [gstr_db_row_to_matcher_row({'id': f'gstr_{i}', 'record_data': r}) for i, r in enumerate(gstr_parsed['records'])]

res = run_bidirectional_reconciliation(gstr_matcher, pr_matcher, gstr_period=date(2026, 5, 1))

print('Matched Count:', res['stats']['matched_count'])
print('Review Required Count:', res['stats']['review_required_count'])
print('Missed ITC Count:', res['stats']['missed_itc_count'])
print('ITC at Risk Count:', res['stats']['wrongful_risk_count'])
assert res['stats']['matched_count'] == 4
assert res['stats']['review_required_count'] == 0
assert res['stats']['missed_itc_count'] == 3
assert res['stats']['wrongful_risk_count'] == 5
print('100% Phase 5.6 Regression Verification Passed!')
"
```

### Option B: Using the Web UI
1. Navigate to **ReconDesk Dashboard** -> **Reconcile**.
2. Select Client with GSTIN `27ISKPK1273H1ZF` (`RECONDESK`).
3. Select Filing Period: `May 2026`.
4. Upload Purchase Register: `test_data/phase56_regression/purchase_register_phase56.xlsx`.
5. Upload GSTR-2B: `test_data/phase56_regression/gstr2b_phase56.xlsx` (or `.json`).
6. Click **Run Reconciliation** and review the generated reports.
