/**
 * Pure-logic tests for IMS Action panel state.
 * Run: npx --yes tsx --test components/reconcile/imsActionLogic.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EMPTY_IMS_CONFIRM_STEPS,
  applyWritebackOutcome,
  buildConfirmationSummary,
  canStartImsHold,
  initRowStates,
  isHighConfidenceAccept,
  isOverride,
  overrideCountInSelection,
  resetImsConfirmSteps,
  selectHighConfidenceAccepts,
  submitMode,
  typedCountMatchesExpected,
  uniformSelectedAction,
  writebackOutcomeFromPoll,
  type ImsInvoiceRecommendation,
} from "./imsActionLogic";

const sample = (
  partial: Partial<ImsInvoiceRecommendation> &
    Pick<ImsInvoiceRecommendation, "invoice_id" | "recommended_action" | "confidence_score">
): ImsInvoiceRecommendation => ({
  supplier_gstin: "27AAAAA0000A1Z5",
  invoice_number: "INV-1",
  category: "matched",
  ims_status: "no_action_taken",
  reason_codes: ["MATCHED_IN_BOOKS"],
  human_readable_why: "Matched in books.",
  ...partial,
});

describe("isHighConfidenceAccept / override", () => {
  it("flags high-confidence ACCEPT only", () => {
    assert.equal(
      isHighConfidenceAccept(
        sample({ invoice_id: "a", recommended_action: "accept", confidence_score: 0.92 })
      ),
      true
    );
    assert.equal(
      isHighConfidenceAccept(
        sample({ invoice_id: "b", recommended_action: "accept", confidence_score: 0.7 })
      ),
      false
    );
    assert.equal(
      isHighConfidenceAccept(
        sample({ invoice_id: "c", recommended_action: "hold", confidence_score: 0.99 })
      ),
      false
    );
  });

  it("tracks overrides distinctly from straight confirms", () => {
    assert.equal(isOverride("hold", "accept"), true);
    assert.equal(isOverride("accept", "accept"), false);
    assert.equal(submitMode("hold", "accept"), "override");
    assert.equal(submitMode("accept", "accept"), "confirm_recommendation");
  });
});

describe("selection + bulk summary", () => {
  it("selects all high-confidence ACCEPT rows", () => {
    const invoices = [
      sample({ invoice_id: "1", recommended_action: "accept", confidence_score: 0.95 }),
      sample({ invoice_id: "2", recommended_action: "accept", confidence_score: 0.5 }),
      sample({ invoice_id: "3", recommended_action: "hold", confidence_score: 0.9 }),
    ];
    const rows = selectHighConfidenceAccepts(invoices, initRowStates(invoices));
    assert.equal(rows.get("1")?.selected, true);
    assert.equal(rows.get("2")?.selected, false);
    assert.equal(rows.get("3")?.selected, false);
  });

  it("builds count-based confirmation summary", () => {
    assert.equal(buildConfirmationSummary("accept", 47), "Accepting 47 invoices");
    assert.equal(buildConfirmationSummary("reject", 1), "Rejecting 1 invoice");
    assert.equal(buildConfirmationSummary("hold", 3), "Holding 3 invoices");
  });

  it("requires reviewed + matching typed count before hold", () => {
    assert.equal(
      canStartImsHold({ reviewed: false, typedCount: "5", holdProgressMs: 0 }, 5),
      false
    );
    assert.equal(
      canStartImsHold({ reviewed: true, typedCount: "5", holdProgressMs: 0 }, 5),
      true
    );
    assert.equal(typedCountMatchesExpected("47", 47), true);
    assert.equal(typedCountMatchesExpected("46", 47), false);
  });

  it("rejects mixed bulk actions", () => {
    const invoices = [
      sample({ invoice_id: "1", recommended_action: "accept", confidence_score: 0.9 }),
      sample({ invoice_id: "2", recommended_action: "hold", confidence_score: 0.5 }),
    ];
    const rows = initRowStates(invoices);
    rows.set("1", { ...rows.get("1")!, selected: true, chosenAction: "accept" });
    rows.set("2", { ...rows.get("2")!, selected: true, chosenAction: "reject" });
    const selected = [
      { inv: invoices[0], row: rows.get("1")! },
      { inv: invoices[1], row: rows.get("2")! },
    ];
    assert.equal(uniformSelectedAction(selected), null);
    assert.equal(overrideCountInSelection(selected), 1);
  });
});

describe("writeback pending → confirmed/failed", () => {
  it("maps dual-status poll results", () => {
    assert.equal(
      writebackOutcomeFromPoll({ is_complete: false, has_errors: false }),
      "pending"
    );
    assert.equal(
      writebackOutcomeFromPoll({
        is_complete: true,
        has_errors: false,
        status_cd: "P",
      }),
      "confirmed"
    );
    assert.equal(
      writebackOutcomeFromPoll({
        is_complete: true,
        has_errors: true,
        status_cd: "PE",
      }),
      "failed"
    );
    assert.equal(
      writebackOutcomeFromPoll({
        is_complete: true,
        has_errors: false,
        outcome: "confirmed",
      }),
      "confirmed"
    );
  });

  it("applies pending → confirmed / failed on row state", () => {
    const invoices = [
      sample({ invoice_id: "1", recommended_action: "accept", confidence_score: 0.9 }),
    ];
    let rows = initRowStates(invoices);
    rows = applyWritebackOutcome(rows, ["1"], "pending");
    assert.equal(rows.get("1")?.writeback, "pending");
    rows = applyWritebackOutcome(rows, ["1"], "confirmed");
    assert.equal(rows.get("1")?.writeback, "confirmed");
    assert.equal(rows.get("1")?.selected, false);

    rows = applyWritebackOutcome(initRowStates(invoices), ["1"], "failed", "PE");
    assert.equal(rows.get("1")?.writeback, "failed");
    assert.equal(rows.get("1")?.writebackError, "PE");
  });

  it("resetImsConfirmSteps clears deliberate sequence", () => {
    const mid = { reviewed: true, typedCount: "47", holdProgressMs: 1800 };
    const reset = resetImsConfirmSteps();
    assert.deepEqual(reset, EMPTY_IMS_CONFIRM_STEPS);
    assert.notDeepEqual(reset, mid);
  });
});
