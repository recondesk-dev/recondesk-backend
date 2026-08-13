/**
 * Tests for Rule 37 Pending Review logic and endpoint payload builder.
 * Run: npx --yes tsx --test components/reconcile/rule37ReviewLogic.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildResolvePayload,
  formatPartyConfidenceWarning,
  isPendingReviewRow,
  type Rule37ReviewRow,
} from "./rule37ReviewLogic";

describe("Rule 37 Pending Review logic", () => {
  const samplePendingRow: Rule37ReviewRow = {
    id: "r37:pr-100",
    invoice_number: "INV-2026-001",
    supplier_gstin: "27AAACB1234C1Z1",
    amount: 50000.0,
    rule37_action_status: "pending_review",
    rule37_action_id: "act-123",
    rule37_review_metadata: {
      reason: "party_confidence_below_gate",
      party: "ABC Traders",
      supplier_name: "ABC Trdrs Pvt Ltd",
      party_sim: 0.62,
      party_gate_min: 0.82,
      bill_ref_score: 1.0,
      amount_paid: 50000.0,
    },
  };

  it("correctly identifies pending review rows", () => {
    assert.equal(isPendingReviewRow(samplePendingRow), true);
    assert.equal(isPendingReviewRow(samplePendingRow, "resolved"), false);
    assert.equal(isPendingReviewRow(samplePendingRow, "rejected"), false);
  });

  it("formats party confidence warning text for UI callout", () => {
    const text = formatPartyConfidenceWarning(
      samplePendingRow.rule37_review_metadata
    );
    assert.equal(
      text,
      "Party name 'ABC Traders' matched 'ABC Trdrs Pvt Ltd' at 62% confidence — below auto-settle threshold (82%)"
    );
  });

  it("builds correct API payload for approve (resolved)", () => {
    const payload = buildResolvePayload(
      samplePendingRow.rule37_action_id!,
      "resolved"
    );
    assert.equal(payload.url, "/api/tally-sync/review/act-123/resolve");
    assert.equal(payload.method, "POST");
    assert.deepEqual(payload.body, { status: "resolved" });
  });

  it("builds correct API payload for reject (rejected)", () => {
    const payload = buildResolvePayload(
      samplePendingRow.rule37_action_id!,
      "rejected"
    );
    assert.equal(payload.url, "/api/tally-sync/review/act-123/resolve");
    assert.equal(payload.method, "POST");
    assert.deepEqual(payload.body, { status: "rejected" });
  });
});
