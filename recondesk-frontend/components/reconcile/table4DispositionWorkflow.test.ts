/**
 * Unit tests for Phase 4B: Exception -> Table 4 CA Disposition Workflow.
 * Run with: ./node_modules/.bin/sucrase-node components/reconcile/table4DispositionWorkflow.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Table4BlockingRecordItem } from "./Table4DispositionModal";

// Domain logic helpers replicating the workflow invariants in results/page.tsx & Table4DispositionModal.tsx

export function deriveTable4Effect(disposition: string): "4B1" | "4B2" | "4A5" | "EXCLUDED" {
  const d = disposition.toUpperCase().trim();
  if (d === "CONFIRMED_BLOCKED" || d === "INELIGIBLE") {
    return "4B1";
  }
  if (d === "REVERSED" || d === "REVERSAL_CONFIRMED") {
    return "4B2";
  }
  if (d === "HELD_GOODS_NOT_RECEIVED" || d === "HOLD" || d === "REJECTED_WRONG_GSTIN") {
    return "EXCLUDED";
  }
  return "4A5";
}

export function validateDispositionSubmission(payload: {
  record_id: string;
  exception_type: string;
  disposition: string;
  reason: string;
}): { valid: boolean; error?: string } {
  if (!payload.record_id || !payload.record_id.trim()) {
    return { valid: false, error: "Record identifier is required." };
  }
  if (!payload.exception_type || !payload.exception_type.trim()) {
    return { valid: false, error: "Exception type is required." };
  }
  if (!payload.reason || payload.reason.trim().length < 5) {
    return { valid: false, error: "Please provide a disposition explanation (minimum 5 characters)." };
  }
  return { valid: true };
}

export function isDispositionActionAllowed(run: {
  status?: string;
  is_locked?: boolean;
}): boolean {
  if (run.is_locked) return false;
  const s = String(run.status || "").toUpperCase();
  if (s === "FINAL" || s === "FINALIZED") return false;
  return true;
}

export function matchBlockingRecord(
  blockingRecords: Table4BlockingRecordItem[],
  invoiceNumber?: string,
  rowId?: string,
  supplierGstin?: string
): Table4BlockingRecordItem | null {
  return (
    blockingRecords.find((b) => {
      if (rowId && b.record_id === rowId) return true;
      if (supplierGstin && invoiceNumber && b.supplier_gstin && b.invoice_number) {
        return (
          b.supplier_gstin.trim().toUpperCase() === supplierGstin.trim().toUpperCase() &&
          b.invoice_number.trim().toLowerCase() === invoiceNumber.trim().toLowerCase()
        );
      }
      if (!supplierGstin && invoiceNumber && b.invoice_number) {
        return b.invoice_number.trim().toLowerCase() === invoiceNumber.trim().toLowerCase();
      }
      return false;
    }) || null
  );
}

export function getExpectedRevalidationKeys(runId: string): string[] {
  return [
    `/api/reconcile/runs/${runId}/section17`,
    `/api/reconcile/runs/${runId}/rule37`,
    `/api/reconcile/runs/${runId}/summary`,
    `table4-workpaper:${runId}`,
  ];
}

// ---------------------------------------------------------------------------
// Test Suites
// ---------------------------------------------------------------------------

describe("Phase 4B: Section 17(5) Exception -> Table 4 Disposition Workflow", () => {
  const sampleBlockingList: Table4BlockingRecordItem[] = [
    {
      record_id: "pm:001659f6-0270-44a7-807c-256e5f8f751f",
      exception_type: "SEC_17_5",
      supplier_name: "Bharat Petroleum",
      invoice_number: "INV20265180314",
      amount: 56382.3,
      reason: "Section 17(5) signal requires CA confirmation.",
    },
  ];

  it("identifies matching blocking record by invoice number or row id", () => {
    const match = matchBlockingRecord(sampleBlockingList, "INV20265180314", "s175:INV20265180314");
    assert.ok(match);
    assert.equal(match.record_id, "pm:001659f6-0270-44a7-807c-256e5f8f751f");
    assert.equal(match.exception_type, "SEC_17_5");
  });

  it("accurately matches via composite (supplier_gstin, invoice_number) and prevents cross-supplier collision", () => {
    const multiVendorList: Table4BlockingRecordItem[] = [
      {
        record_id: "rec-supplier-a",
        exception_type: "SEC_17_5",
        supplier_gstin: "27AAAAA0000A1Z5",
        invoice_number: "INV-COMMON-01",
        amount: 1000,
      },
      {
        record_id: "rec-supplier-b",
        exception_type: "SEC_17_5",
        supplier_gstin: "27BBBBB1111B2Z6",
        invoice_number: "INV-COMMON-01",
        amount: 2000,
      },
    ];

    const matchA = matchBlockingRecord(multiVendorList, "INV-COMMON-01", undefined, "27AAAAA0000A1Z5");
    assert.ok(matchA);
    assert.equal(matchA.record_id, "rec-supplier-a");

    const matchB = matchBlockingRecord(multiVendorList, "INV-COMMON-01", undefined, "27BBBBB1111B2Z6");
    assert.ok(matchB);
    assert.equal(matchB.record_id, "rec-supplier-b");

    const matchC = matchBlockingRecord(multiVendorList, "INV-COMMON-01", undefined, "27CCCCC2222C3Z7");
    assert.equal(matchC, null);
  });

  it("maps CONFIRMED_BLOCKED to Table 4(B)(1) ineligible reversal", () => {
    const effect = deriveTable4Effect("CONFIRMED_BLOCKED");
    assert.equal(effect, "4B1");
  });

  it("maps STATUTORY_EXCEPTION to Table 4(A)(5) eligible claim", () => {
    const effect = deriveTable4Effect("STATUTORY_EXCEPTION");
    assert.equal(effect, "4A5");
  });

  it("validates that reason explanation is at least 5 characters", () => {
    const invalid = validateDispositionSubmission({
      record_id: "pm:001",
      exception_type: "SEC_17_5",
      disposition: "CONFIRMED_BLOCKED",
      reason: "bad",
    });
    assert.equal(invalid.valid, false);
    assert.match(invalid.error!, /minimum 5 characters/);

    const valid = validateDispositionSubmission({
      record_id: "pm:001",
      exception_type: "SEC_17_5",
      disposition: "CONFIRMED_BLOCKED",
      reason: "Executive transport expense restricted under Sec 17(5)(a)",
    });
    assert.equal(valid.valid, true);
  });
});

describe("Phase 4B: Rule 37 Exception -> Table 4 Disposition Workflow", () => {
  const sampleBlockingList: Table4BlockingRecordItem[] = [
    {
      record_id: "pm:04196364-1e0f-439a-9e6a-252eb2abbe37",
      exception_type: "RULE_37",
      supplier_name: "Vendor Services Ltd",
      invoice_number: "INV20267990285",
      amount: 20345.5,
      reason: "Unpaid > 180 days requires disposition.",
    },
  ];

  it("identifies matching blocking record for Rule 37", () => {
    const match = matchBlockingRecord(sampleBlockingList, "INV20267990285");
    assert.ok(match);
    assert.equal(match.record_id, "pm:04196364-1e0f-439a-9e6a-252eb2abbe37");
    assert.equal(match.exception_type, "RULE_37");
  });

  it("maps REVERSED to Table 4(B)(2) temporary reversal ledger", () => {
    const effect = deriveTable4Effect("REVERSED");
    assert.equal(effect, "4B2");
  });

  it("maps PAID_ELIGIBLE to Table 4(A)(5) remaining eligible in gross credit", () => {
    const effect = deriveTable4Effect("PAID_ELIGIBLE");
    assert.equal(effect, "4A5");
  });
});

describe("Phase 4B: Finalized Run Immutability & Gate Protection", () => {
  it("prohibits disposition actions when run status is FINAL", () => {
    assert.equal(isDispositionActionAllowed({ status: "FINAL", is_locked: false }), false);
    assert.equal(isDispositionActionAllowed({ status: "final", is_locked: false }), false);
  });

  it("prohibits disposition actions when run is locked", () => {
    assert.equal(isDispositionActionAllowed({ status: "COMPLETED", is_locked: true }), false);
  });

  it("allows disposition actions only on unlocked provisional/completed runs", () => {
    assert.equal(isDispositionActionAllowed({ status: "COMPLETED", is_locked: false }), true);
    assert.equal(isDispositionActionAllowed({ status: "PROVISIONAL", is_locked: false }), true);
  });

  it("defines comprehensive SWR revalidation keys across results and Table 4 workpaper", () => {
    const keys = getExpectedRevalidationKeys("test-run-123");
    assert.ok(keys.includes("/api/reconcile/runs/test-run-123/section17"));
    assert.ok(keys.includes("/api/reconcile/runs/test-run-123/rule37"));
    assert.ok(keys.includes("/api/reconcile/runs/test-run-123/summary"));
    assert.ok(keys.includes("table4-workpaper:test-run-123"));
  });
});
