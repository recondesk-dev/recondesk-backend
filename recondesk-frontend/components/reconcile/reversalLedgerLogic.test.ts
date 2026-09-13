/**
 * Unit tests for GSTR-3B Table 4 Reversal & Reclaim Ledger frontend domain logic.
 * Run with: ./node_modules/.bin/sucrase-node components/reconcile/reversalLedgerLogic.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  REVERSAL_STATUS_META,
  STATUTORY_REASON_LABELS,
  canAuthorizeReclaim,
  canExecuteReclaim,
  canFulfillCondition,
  generateReclaimIdempotencyKey,
  isReclaimAllowedForTable4Cell,
  paiseToRupees,
  rupeesToPaise,
  validateEvidencePayload,
  validateReclaimAmounts,
  type TaxHeadPaise,
} from "./reversalLedgerLogic";

describe("Reversal & Reclaim Ledger: Status Presentation & Metadata", () => {
  it("renders exact CA-facing labels without ambiguous 'Pending'", () => {
    assert.equal(REVERSAL_STATUS_META.OPEN.label, "Reversal recorded — condition pending");
    assert.equal(
      REVERSAL_STATUS_META.CONDITION_FULFILLED.label,
      "Condition verified — awaiting reclaim authorization"
    );
    assert.equal(REVERSAL_STATUS_META.RECLAIM_AUTHORIZED.label, "Reclaim authorized");
    assert.equal(REVERSAL_STATUS_META.PARTIALLY_RECLAIMED.label, "Partially reclaimed");
    assert.equal(REVERSAL_STATUS_META.FULLY_RECLAIMED.label, "Fully reclaimed");
    assert.equal(REVERSAL_STATUS_META.NON_RECLAIMABLE.label, "Non-reclaimable");
  });

  it("contains complete statutory reason descriptions", () => {
    assert.match(STATUTORY_REASON_LABELS.RULE_37_NON_PAYMENT, /Rule 37/);
    assert.match(STATUTORY_REASON_LABELS.RULE_37A_SUPPLIER_NON_FILING, /Rule 37A/);
    assert.match(STATUTORY_REASON_LABELS.SECTION_16_2_B_NOT_RECEIVED, /Section 16\(2\)\(b\)/);
  });
});

describe("Reversal & Reclaim Ledger: Hard Statutory Boundaries", () => {
  it("strictly prohibits reclaim action for Table 4(D)(2) (Section 16(4) / PoS)", () => {
    assert.equal(isReclaimAllowedForTable4Cell("4D2"), false);
    assert.equal(isReclaimAllowedForTable4Cell("4d2"), false);
  });

  it("strictly prohibits reclaim action for Table 4(B)(1) (Section 17(5) / Rules 38, 42, 43)", () => {
    assert.equal(isReclaimAllowedForTable4Cell("4B1"), false);
    assert.equal(isReclaimAllowedForTable4Cell("4b1"), false);
  });

  it("allows reclaim action only for temporary Table 4(B)(2)", () => {
    assert.equal(isReclaimAllowedForTable4Cell("4B2"), true);
    assert.equal(isReclaimAllowedForTable4Cell("4b2"), true);
  });
});

describe("Reversal & Reclaim Ledger: State Machine Transitions", () => {
  it("canFulfillCondition is true only for OPEN reclaimable records", () => {
    assert.equal(canFulfillCondition({ is_reclaimable: true, status: "OPEN" }), true);
    assert.equal(canFulfillCondition({ is_reclaimable: false, status: "OPEN" }), false);
    assert.equal(canFulfillCondition({ is_reclaimable: true, status: "CONDITION_FULFILLED" }), false);
    assert.equal(canFulfillCondition({ is_reclaimable: true, status: "RECLAIM_AUTHORIZED" }), false);
    assert.equal(canFulfillCondition({ is_reclaimable: true, status: "NON_RECLAIMABLE" }), false);
  });

  it("canAuthorizeReclaim is true only for CONDITION_FULFILLED reclaimable records", () => {
    // Cannot authorize while OPEN
    assert.equal(canAuthorizeReclaim({ is_reclaimable: true, status: "OPEN" }), false);
    // Can authorize once condition is verified
    assert.equal(canAuthorizeReclaim({ is_reclaimable: true, status: "CONDITION_FULFILLED" }), true);
    // Cannot authorize non-reclaimable
    assert.equal(canAuthorizeReclaim({ is_reclaimable: false, status: "CONDITION_FULFILLED" }), false);
  });

  it("canExecuteReclaim is true only for RECLAIM_AUTHORIZED / PARTIALLY_RECLAIMED", () => {
    assert.equal(canExecuteReclaim({ is_reclaimable: true, status: "OPEN" }), false);
    assert.equal(canExecuteReclaim({ is_reclaimable: true, status: "CONDITION_FULFILLED" }), false);
    assert.equal(canExecuteReclaim({ is_reclaimable: true, status: "RECLAIM_AUTHORIZED" }), true);
    assert.equal(canExecuteReclaim({ is_reclaimable: true, status: "PARTIALLY_RECLAIMED" }), true);
    assert.equal(canExecuteReclaim({ is_reclaimable: true, status: "FULLY_RECLAIMED" }), false);
    assert.equal(canExecuteReclaim({ is_reclaimable: false, status: "RECLAIM_AUTHORIZED" }), false);
  });

  it("canExecuteReclaim rejects reclaim into finalized or locked target run", () => {
    const entry = { is_reclaimable: true, status: "RECLAIM_AUTHORIZED" as const };
    // Active unlocked run
    assert.equal(canExecuteReclaim(entry, { is_locked: false, status: "COMPLETED" }), true);
    // Finalized run
    assert.equal(canExecuteReclaim(entry, { is_locked: false, status: "FINAL" }), false);
    // Locked run
    assert.equal(canExecuteReclaim(entry, { is_locked: true, status: "COMPLETED" }), false);
  });
});

describe("Reversal & Reclaim Ledger: Evidence Payload Validation", () => {
  it("validates Rule 37 payment evidence requirements", () => {
    const missingRef = validateEvidencePayload("RULE_37_NON_PAYMENT", {
      payment_reference: "",
      payment_date: "2024-03-01",
    });
    assert.equal(missingRef.isValid, false);
    assert.match(missingRef.errorMessage!, /Payment reference/);

    const missingDate = validateEvidencePayload("RULE_37_NON_PAYMENT", {
      payment_reference: "UTR-12345",
      payment_date: "",
    });
    assert.equal(missingDate.isValid, false);
    assert.match(missingDate.errorMessage!, /Payment date/);

    const valid = validateEvidencePayload("RULE_37_NON_PAYMENT", {
      payment_reference: "UTR-12345",
      payment_date: "2024-03-01",
    });
    assert.equal(valid.isValid, true);
  });

  it("validates Rule 37A supplier filing evidence requirements", () => {
    const missingArn = validateEvidencePayload("RULE_37A_SUPPLIER_NON_FILING", {
      supplier_filing_arn: "",
      supplier_filing_date: "2024-04-10",
    });
    assert.equal(missingArn.isValid, false);
    assert.match(missingArn.errorMessage!, /ARN/);

    const valid = validateEvidencePayload("RULE_37A_SUPPLIER_NON_FILING", {
      supplier_filing_arn: "AA2703240012345",
      supplier_filing_date: "2024-04-10",
    });
    assert.equal(valid.isValid, true);
  });

  it("validates Section 16(2)(b) receipt evidence requirements", () => {
    const missingReceipt = validateEvidencePayload("SECTION_16_2_B_NOT_RECEIVED", {
      receipt_evidence_ref: "",
      receipt_date: "2024-02-15",
    });
    assert.equal(missingReceipt.isValid, false);
    assert.match(missingReceipt.errorMessage!, /Receipt evidence reference/);

    const valid = validateEvidencePayload("SECTION_16_2_B_NOT_RECEIVED", {
      receipt_evidence_ref: "GRN-2024-9988",
      receipt_date: "2024-02-15",
    });
    assert.equal(valid.isValid, true);
  });
});

describe("Reversal & Reclaim Ledger: Tax-Head Balance Validation", () => {
  const available: TaxHeadPaise = {
    igst_paise: 500000, // ₹5,000
    cgst_paise: 250000, // ₹2,500
    sgst_paise: 250000, // ₹2,500
    cess_paise: 0,
  };

  it("accepts valid full reclaim", () => {
    const res = validateReclaimAmounts(available, available);
    assert.equal(res.isValid, true);
  });

  it("accepts valid partial reclaim", () => {
    const requested: TaxHeadPaise = {
      igst_paise: 200000, // ₹2,000
      cgst_paise: 100000,
      sgst_paise: 100000,
      cess_paise: 0,
    };
    const res = validateReclaimAmounts(requested, available);
    assert.equal(res.isValid, true);
  });

  it("rejects zero total reclaim amount", () => {
    const requested: TaxHeadPaise = {
      igst_paise: 0,
      cgst_paise: 0,
      sgst_paise: 0,
      cess_paise: 0,
    };
    const res = validateReclaimAmounts(requested, available);
    assert.equal(res.isValid, false);
    assert.match(res.errorMessage!, /greater than/);
  });

  it("rejects negative amounts", () => {
    const requested: TaxHeadPaise = {
      igst_paise: -100,
      cgst_paise: 0,
      sgst_paise: 0,
      cess_paise: 0,
    };
    const res = validateReclaimAmounts(requested, available);
    assert.equal(res.isValid, false);
    assert.match(res.errorMessage!, /cannot be negative/);
  });

  it("rejects excess reclaim on specific tax heads", () => {
    const excessIgst: TaxHeadPaise = {
      igst_paise: 600000, // exceeds 500000
      cgst_paise: 250000,
      sgst_paise: 250000,
      cess_paise: 0,
    };
    const res1 = validateReclaimAmounts(excessIgst, available);
    assert.equal(res1.isValid, false);
    assert.equal(res1.excessTaxHead, "IGST");
    assert.match(res1.errorMessage!, /IGST exceeds/);

    const excessCess: TaxHeadPaise = {
      igst_paise: 0,
      cgst_paise: 0,
      sgst_paise: 0,
      cess_paise: 5000, // exceeds 0
    };
    const res2 = validateReclaimAmounts(excessCess, available);
    assert.equal(res2.isValid, false);
    assert.equal(res2.excessTaxHead, "Cess");
  });
});

describe("Reversal & Reclaim Ledger: Currency & Key Helpers", () => {
  it("converts paise to rupees and vice versa accurately", () => {
    assert.equal(paiseToRupees(10050), 100.5);
    assert.equal(paiseToRupees(0), 0);
    assert.equal(rupeesToPaise(100.5), 10050);
    assert.equal(rupeesToPaise("100.50"), 10050);
    assert.equal(rupeesToPaise(0), 0);
  });

  it("generates deterministic and unique idempotency key format", () => {
    const key = generateReclaimIdempotencyKey("led-12345678", "run-87654321");
    assert.match(key, /^rcm-led-1234-run-8765-\d+-[a-z0-9]+$/);
  });
});
