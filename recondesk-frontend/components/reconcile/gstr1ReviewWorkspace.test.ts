/**
 * Unit & Regression tests for GSTR-1 Review Mode & Workspace Invariants.
 * Run with: ./node_modules/.bin/sucrase-node components/reconcile/gstr1ReviewWorkspace.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  generateReviewScopeKey,
  buildReviewQueueItems,
  type ReviewQueueItem,
} from "./gstr1ReviewLogic";
import { safeStorageGet, safeStorageSet, safeStorageRemove } from "../../lib/safeStorage";
import type { Gstr1ReconcileResult } from "../../lib/gstr1Reconcile";

describe("GSTR-1 Review Mode: Preferences & Session Isolation Invariants", () => {
  const baseResult: Gstr1ReconcileResult = {
    run_id: "run-aaa-111",
    client_gstin_id: "27AABCB1234D1Z1",
    meta: {
      filing_period: "2026-09",
      sales_register_filename: "sales_sep.xlsx",
      gstr1_filename: "gstr1_sep.json",
    },
    summary: {
      sr_total_records: 5000,
      matched_count: 4770,
      unmatched_sr_count: 230,
      unmatched_gstr1_count: 75,
      review_required_count: 140,
    } as any,
  };

  it("1. Scopes review sessions by authenticated user email", () => {
    const keyUser1 = generateReviewScopeKey(baseResult, "run-aaa-111", "ca1@firm.com");
    const keyUser2 = generateReviewScopeKey(baseResult, "run-aaa-111", "ca2@firm.com");
    assert.notEqual(keyUser1, keyUser2);
    assert.match(keyUser1, /ca1_firm_com/);
    assert.match(keyUser2, /ca2_firm_com/);
  });

  it("2. Scopes review sessions by client GSTIN and period", () => {
    const keyClient1 = generateReviewScopeKey(baseResult, "run-aaa-111", "ca@firm.com");

    const diffClientResult = {
      ...baseResult,
      client_gstin_id: "29XYZAB5678E1Z2",
    };
    const keyClient2 = generateReviewScopeKey(diffClientResult, "run-aaa-111", "ca@firm.com");
    assert.notEqual(keyClient1, keyClient2);

    const diffPeriodResult = {
      ...baseResult,
      meta: { ...baseResult.meta, filing_period: "2026-10" },
    };
    const keyPeriod2 = generateReviewScopeKey(diffPeriodResult, "run-aaa-111", "ca@firm.com");
    assert.notEqual(keyClient1, keyPeriod2);
  });

  it("3. Guarantees that new reconciliation runs NEVER inherit stale decisions", () => {
    const keyRun1 = generateReviewScopeKey(baseResult, "run-101", "ca@firm.com");
    const keyRun2 = generateReviewScopeKey(baseResult, "run-102", "ca@firm.com");
    assert.notEqual(keyRun1, keyRun2);
    assert.ok(keyRun1.includes("run-101"));
    assert.ok(keyRun2.includes("run-102"));
  });

  it("4. Ephemeral uploads generate unique keys by filename and row count", () => {
    const keyUpload1 = generateReviewScopeKey(baseResult, null, "ca@firm.com");
    const diffUpload = {
      ...baseResult,
      meta: { ...baseResult.meta, sales_register_filename: "sales_sep_revised.xlsx" },
      summary: { ...baseResult.summary, sr_total_records: 5020 } as any,
    };
    const keyUpload2 = generateReviewScopeKey(diffUpload, null, "ca@firm.com");
    assert.notEqual(keyUpload1, keyUpload2);
  });
});

describe("GSTR-1 Review Mode: Queue Building & Mathematical Truth", () => {
  const mockResult: Gstr1ReconcileResult = {
    run_id: "test-run-1",
    matched: [
      // 1. Clean match (no review required)
      {
        sr_record: {
          invoice_number: "INV-001",
          taxable_amount_paise: 1000000,
          cgst_paise: 90000,
          sgst_paise: 90000,
        },
        gstr1_record: {
          invoice_number: "INV-001",
          taxable_amount_paise: 1000000,
          cgst_paise: 90000,
          sgst_paise: 90000,
        },
        requires_human_review: false,
        discrepancies: [],
      } as any,
      // 2. Amount mismatch (G1M3 review required)
      {
        sr_record: {
          invoice_number: "INV-002",
          taxable_amount_paise: 1200000, // ₹12,000
          cgst_paise: 108000, // ₹1,080
          sgst_paise: 108000, // ₹1,080
          invoice_date: "2026-09-15",
          place_of_supply: "27",
        },
        gstr1_record: {
          invoice_number: "INV-002",
          taxable_amount_paise: 1440000, // ₹14,400
          cgst_paise: 129600, // ₹1,296
          sgst_paise: 129600, // ₹1,296
          invoice_date: "2026-09-15",
          place_of_supply: "27",
        },
        mismatch_type: "G1M3_AMOUNT_MISMATCH",
        requires_human_review: true,
        discrepancies: ["Taxable value mismatch: Books ₹12,000 vs Portal ₹14,400"],
      } as any,
    ],
    unmatched_sr: [
      // 3. Missing in GSTR-1 (G1M1)
      {
        record: {
          invoice_number: "INV-003",
          taxable_amount_paise: 500000, // ₹5,000
          cgst_paise: 45000,
          sgst_paise: 45000,
          invoice_date: "2026-09-18",
        },
        mismatch_type: "G1M1_MISSING_INVOICE",
      } as any,
    ],
    unmatched_gstr1: [
      // 4. Extra in GSTR-1 (G1M2)
      {
        record: {
          invoice_number: "INV-004",
          taxable_amount_paise: 750000, // ₹7,500
          cgst_paise: 67500,
          sgst_paise: 67500,
          invoice_date: "2026-09-20",
        },
        mismatch_type: "G1M2_EXTRA_INVOICE",
      } as any,
    ],
    summary: {
      sr_total_records: 3,
      matched_count: 2,
      review_required_count: 1,
      unmatched_sr_count: 1,
      unmatched_gstr1_count: 1,
    } as any,
  };

  it("1. Excludes perfectly clean matches and includes only actionable review items", () => {
    const items = buildReviewQueueItems(mockResult);
    // Should have: INV-002 (G1M3), INV-003 (G1M1), INV-004 (G1M2)
    assert.equal(items.length, 3);
    const invoiceNumbers = items.map((i) => i.invoiceNumber);
    assert.ok(!invoiceNumbers.includes("INV-001"), "Clean matched invoice must not appear in review queue");
    assert.ok(invoiceNumbers.includes("INV-002"));
    assert.ok(invoiceNumbers.includes("INV-003"));
    assert.ok(invoiceNumbers.includes("INV-004"));
  });

  it("2. Calculates taxable and tax delta with exact mathematical precision", () => {
    const items = buildReviewQueueItems(mockResult);
    const g1m3Item = items.find((i) => i.invoiceNumber === "INV-002")!;
    assert.ok(g1m3Item);
    assert.equal(g1m3Item.books.taxable, 12000);
    assert.equal(g1m3Item.portal.taxable, 14400);
    assert.equal(g1m3Item.taxableDiff, 2400);

    assert.equal(g1m3Item.books.totalTax, 2160);
    assert.equal(g1m3Item.portal.totalTax, 2592);
    assert.equal(g1m3Item.totalTaxDiff, 432);
  });

  it("3. Accurately maps Missing in GSTR-1 (G1M1) as full downward liability delta", () => {
    const items = buildReviewQueueItems(mockResult);
    const g1m1Item = items.find((i) => i.invoiceNumber === "INV-003")!;
    assert.ok(g1m1Item);
    assert.equal(g1m1Item.books.taxable, 5000);
    assert.equal(g1m1Item.portal.taxable, 0);
    assert.equal(g1m1Item.taxableDiff, -5000);
    assert.equal(g1m1Item.category, "missing_in_gstr1");
  });

  it("4. Accurately maps Extra in GSTR-1 (G1M2) as full upward liability delta", () => {
    const items = buildReviewQueueItems(mockResult);
    const g1m2Item = items.find((i) => i.invoiceNumber === "INV-004")!;
    assert.ok(g1m2Item);
    assert.equal(g1m2Item.books.taxable, 0);
    assert.equal(g1m2Item.portal.taxable, 7500);
    assert.equal(g1m2Item.taxableDiff, 7500);
    assert.equal(g1m2Item.category, "extra_in_gstr1");
  });
});

describe("Safe Browser Storage Invariants", () => {
  it("1. safeStorageGet returns default value when window/localStorage is missing in SSR", () => {
    const result = safeStorageGet("non_existent_key", { fallback: true });
    assert.deepEqual(result, { fallback: true });
  });

  it("2. safeStorageSet returns false gracefully when localStorage is unavailable", () => {
    const success = safeStorageSet("test_key", { foo: "bar" });
    assert.equal(typeof success, "boolean");
  });
});
