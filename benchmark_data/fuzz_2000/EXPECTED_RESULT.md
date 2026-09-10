# ReconDesk GSTR-1 Fuzz Test — 2,000 invoices

Supplier GSTIN: `27ISKPK1273H1ZF`  
Period: `07-2025`  
Seed: `20260910`

## Objective
Stress-test reconciliation with 2,000 synthetic outward invoices and deliberate, disjoint corruptions.

## Expected behavior
- Missing B2B: detect as G1M1 / missing from GSTR-1.
- Extra B2B representations: detect as extra-in-GSTR-1; never consume a second Sales Register row.
- Taxable mismatch: match identity but flag amount/taxable mismatch.
- Tax mismatch: flag tax amount mismatch without inventing missing invoices.
- Date mismatch: do not silently treat materially different dates as exact.
- GSTIN mismatch: flag supplier/recipient identity mismatch.
- Rate mismatch: flag tax-rate mismatch.
- Duplicate B2B: never produce two clean matches from one Sales Register invoice.
- Invoice format variation: attempt normalization; if normalized safely, report normalized match rather than exact match.
- B2CL mismatch: compare invoice-level B2CL values.
- B2CS aggregate mismatch: compare aggregate values; do not falsely mark every underlying B2CS Sales Register invoice as missing.
- Credit-note missing/amount mismatch: use credit-note terminology and economic sign handling.
- Valid B2BA: find original in June and use only amendment delta in current-period aggregation.
- Invalid B2BA: flag missing original and do not add its amount to current-period turnover.
- 3B tie-out: report actual GSTR-1 vs 3B variance; never mark clean when totals differ.

## Mutation counts
{
  "missing_b2b": 20,
  "extra_b2b_duplicate_representation": 20,
  "b2b_taxable_mismatch": 25,
  "b2b_tax_mismatch": 25,
  "date_mismatch": 15,
  "gstin_mismatch": 15,
  "rate_mismatch": 15,
  "duplicate_b2b": 15,
  "invoice_format_variation": 30,
  "b2cl_taxable_mismatch": 10,
  "b2cs_aggregate_mismatch": 1,
  "credit_note_missing": 5,
  "credit_note_amount_mismatch": 5,
  "valid_b2ba": 1,
  "invalid_b2ba": 1
}

## Important
This is a fuzz/adversarial benchmark, not a claim that every mutation represents a legally valid filing scenario. It is designed to test the engine's defensive behavior. GST invoice/GSTR-1 structures include invoice number, date, recipient GSTIN, taxable value, tax rate and tax amounts; GSTR-1 also contains B2B, B2CL, B2CS, credit/debit note, export, amendment and HSN sections.
