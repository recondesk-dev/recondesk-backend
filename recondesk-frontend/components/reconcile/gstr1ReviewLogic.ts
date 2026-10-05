/**
 * Pure domain logic and models for GSTR-1 Review Mode.
 * Free of React/JSX dependencies for unit testing and high performance.
 */

import {
  recordAmountRupees,
  recordGstin,
  recordInvoiceNumber,
  mismatchTypeShort,
  type Gstr1ReconcileResult,
} from "../../lib/gstr1Reconcile";

export type DecisionStatus =
  | "unreviewed"
  | "reviewed"
  | "awaiting_clarification"
  | "queued_gstr1a"
  | "corrected_verified";

export interface ReviewDecisionRecord {
  status: DecisionStatus;
  label: string;
  note?: string;
  decidedBy: string;
  decidedAt: string;
}

export interface ReviewQueueItem {
  id: string;
  invoiceNumber: string;
  invoiceDate: string;
  gstin: string;
  recipientName: string;
  category: "review_required" | "missing_in_gstr1" | "extra_in_gstr1" | "compliance_warning";
  categoryLabel: string;
  issueCode: string;
  severity: string;
  what?: string;
  why?: string;
  next?: string;
  discrepancies: string[];
  books: {
    taxable: number;
    igst: number;
    cgst: number;
    sgst: number;
    cess: number;
    totalTax: number;
    invoiceValue: number;
    pos?: string;
  };
  portal: {
    taxable: number;
    igst: number;
    cgst: number;
    sgst: number;
    cess: number;
    totalTax: number;
    invoiceValue: number;
    pos?: string;
  };
  taxableDiff: number;
  totalTaxDiff: number;
}

export function paiseToRupees(p: unknown): number {
  if (typeof p !== "number" || isNaN(p)) return 0;
  return p / 100;
}

export function formatInr(val: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val);
}

export function formatInrPlain(val: number): string {
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val);
}

export function generateReviewScopeKey(
  result: Gstr1ReconcileResult,
  runId?: string | null,
  userEmail?: string | null
): string {
  const sanitize = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_");

  const userKey = sanitize(userEmail || "user");
  const clientKey = sanitize(
    result.client_gstin_id ||
      result.meta?.client_gstin_id ||
      result.parse_diagnostics?.gstr1?.filing_gstin ||
      "unlinked"
  );
  const periodKey = sanitize(
    result.meta?.filing_period || result.tie_out?.ret_period || "period"
  );

  // Run key isolates new uploads from stale runs
  const runKey = runId
    ? sanitize(runId)
    : result.meta?.sales_register_filename
      ? sanitize(`${result.meta.sales_register_filename}_${result.summary?.sr_total_records || 0}`)
      : "ephemeral";

  return `recondesk_rev_${userKey}_${clientKey}_${periodKey}_${runKey}`;
}

export function buildReviewQueueItems(result: Gstr1ReconcileResult): ReviewQueueItem[] {
  const items: ReviewQueueItem[] = [];

  // 1. Review Required (G1M3 / Discrepancies)
  const matched = result.matched || [];
  matched.forEach((row, idx) => {
    const hasDiscrepancy =
      row.requires_human_review ||
      (row.discrepancies && row.discrepancies.length > 0) ||
      row.mismatch_type === "G1M3_AMOUNT_MISMATCH" ||
      row.category === "review_required";

    if (!hasDiscrepancy) return;

    const sr = row.sr_record || {};
    const g1 = row.gstr1_record || {};

    const invNum = recordInvoiceNumber(sr) || recordInvoiceNumber(g1) || `INV-M-${idx + 1}`;
    const gstin = recordGstin(sr) || recordGstin(g1) || "Unregistered";
    const name = String(sr.recipient_name || g1.recipient_name || "").trim();

    const srTaxable = paiseToRupees(sr.taxable_amount_paise);
    const g1Taxable = paiseToRupees(g1.taxable_amount_paise);
    const srIgst = paiseToRupees(sr.igst_paise);
    const g1Igst = paiseToRupees(g1.igst_paise);
    const srCgst = paiseToRupees(sr.cgst_paise);
    const g1Cgst = paiseToRupees(g1.cgst_paise);
    const srSgst = paiseToRupees(sr.sgst_paise);
    const g1Sgst = paiseToRupees(g1.sgst_paise);
    const srTax = paiseToRupees(sr.total_tax_paise) || srIgst + srCgst + srSgst;
    const g1Tax = paiseToRupees(g1.total_tax_paise) || g1Igst + g1Cgst + g1Sgst;
    const srVal = paiseToRupees(sr.invoice_value_paise) || srTaxable + srTax;
    const g1Val = paiseToRupees(g1.invoice_value_paise) || g1Taxable + g1Tax;

    items.push({
      id: `review_req_${invNum}_${gstin}_${idx}`,
      invoiceNumber: invNum,
      invoiceDate: String(sr.invoice_date || g1.invoice_date || "—"),
      gstin,
      recipientName: name,
      category: "review_required",
      categoryLabel: "Review Required",
      issueCode: mismatchTypeShort(row.mismatch_type || "G1M3"),
      severity: String(row.mismatch_severity || "high").toLowerCase(),
      what: row.decision_what || row.review_reason || "Value or tax mismatch between Books and GSTR-1",
      why: row.decision_why || (row.discrepancies?.length ? row.discrepancies.join(" · ") : "Records align under matching rules with field differences."),
      next: row.decision_next || "Verify taxable values and place of supply before filing.",
      discrepancies: row.discrepancies || [],
      books: {
        taxable: srTaxable,
        igst: srIgst,
        cgst: srCgst,
        sgst: srSgst,
        cess: 0,
        totalTax: srTax,
        invoiceValue: srVal,
        pos: String(sr.place_of_supply || sr.pos || "—"),
      },
      portal: {
        taxable: g1Taxable,
        igst: g1Igst,
        cgst: g1Cgst,
        sgst: g1Sgst,
        cess: 0,
        totalTax: g1Tax,
        invoiceValue: g1Val,
        pos: String(g1.place_of_supply || g1.pos || "—"),
      },
      taxableDiff: g1Taxable - srTaxable,
      totalTaxDiff: g1Tax - srTax,
    });
  });

  // 2. Missing in GSTR-1 (G1M1)
  const unmatchedSr = result.unmatched_sr || [];
  unmatchedSr.forEach((row, idx) => {
    const sr = row.record || {};
    const invNum = recordInvoiceNumber(sr) || `INV-SR-${idx + 1}`;
    const gstin = recordGstin(sr) || "Unregistered";
    const name = String(sr.recipient_name || "").trim();

    const srTaxable = recordAmountRupees(sr);
    const srIgst = paiseToRupees(sr.igst_paise);
    const srCgst = paiseToRupees(sr.cgst_paise);
    const srSgst = paiseToRupees(sr.sgst_paise);
    const srTax = paiseToRupees(sr.total_tax_paise) || srIgst + srCgst + srSgst;
    const srVal = paiseToRupees(sr.invoice_value_paise) || srTaxable + srTax;

    items.push({
      id: `missing_sr_${invNum}_${gstin}_${idx}`,
      invoiceNumber: invNum,
      invoiceDate: String(sr.invoice_date || "—"),
      gstin,
      recipientName: name,
      category: "missing_in_gstr1",
      categoryLabel: "Missing in GSTR-1",
      issueCode: "G1M1",
      severity: String(row.mismatch_severity || "critical").toLowerCase(),
      what: row.decision_what || "Invoice recorded in Sales Register but omitted from GSTR-1",
      why: row.decision_why || "Under-reporting risk — outward liability omitted from tax portal filing.",
      next: row.decision_next || "Include in GSTR-1 outward tables or amend via GSTR-1A.",
      discrepancies: ["Missing from portal filing"],
      books: {
        taxable: srTaxable,
        igst: srIgst,
        cgst: srCgst,
        sgst: srSgst,
        cess: 0,
        totalTax: srTax,
        invoiceValue: srVal,
        pos: String(sr.place_of_supply || sr.pos || "—"),
      },
      portal: {
        taxable: 0,
        igst: 0,
        cgst: 0,
        sgst: 0,
        cess: 0,
        totalTax: 0,
        invoiceValue: 0,
        pos: "—",
      },
      taxableDiff: -srTaxable,
      totalTaxDiff: -srTax,
    });
  });

  // 3. Extra in GSTR-1 (G1M2)
  const unmatchedG1 = result.unmatched_gstr1 || [];
  unmatchedG1.forEach((row, idx) => {
    const g1 = row.record || {};
    const invNum = recordInvoiceNumber(g1) || `INV-G1-${idx + 1}`;
    const gstin = recordGstin(g1) || "Unregistered";
    const name = String(g1.recipient_name || "").trim();

    const g1Taxable = recordAmountRupees(g1);
    const g1Igst = paiseToRupees(g1.igst_paise);
    const g1Cgst = paiseToRupees(g1.cgst_paise);
    const g1Sgst = paiseToRupees(g1.sgst_paise);
    const g1Tax = paiseToRupees(g1.total_tax_paise) || g1Igst + g1Cgst + g1Sgst;
    const g1Val = paiseToRupees(g1.invoice_value_paise) || g1Taxable + g1Tax;

    items.push({
      id: `extra_g1_${invNum}_${gstin}_${idx}`,
      invoiceNumber: invNum,
      invoiceDate: String(g1.invoice_date || "—"),
      gstin,
      recipientName: name,
      category: "extra_in_gstr1",
      categoryLabel: "Extra in GSTR-1",
      issueCode: "G1M2",
      severity: String(row.mismatch_severity || "high").toLowerCase(),
      what: row.decision_what || "Invoice filed in GSTR-1 with no matching entry in Sales Register",
      why: row.decision_why || "Excess liability booked on GSTN portal without book entry or cancelled invoice.",
      next: row.decision_next || "Cross-verify credit notes, cancellations, or adjust via GSTR-1A amendment.",
      discrepancies: ["Extra on portal without book entry"],
      books: {
        taxable: 0,
        igst: 0,
        cgst: 0,
        sgst: 0,
        cess: 0,
        totalTax: 0,
        invoiceValue: 0,
        pos: "—",
      },
      portal: {
        taxable: g1Taxable,
        igst: g1Igst,
        cgst: g1Cgst,
        sgst: g1Sgst,
        cess: 0,
        totalTax: g1Tax,
        invoiceValue: g1Val,
        pos: String(g1.place_of_supply || g1.pos || "—"),
      },
      taxableDiff: g1Taxable,
      totalTaxDiff: g1Tax,
    });
  });

  return items;
}
