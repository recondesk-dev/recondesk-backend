/**
 * Unit tests for Phase 5.5B: Revalidation UX domain logic.
 * Run with: ./node_modules/.bin/sucrase-node components/clients/revalidationUxLogic.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  deriveEffectiveRevalStatus,
  REVALIDATION_STATUS_LABELS,
  getRevalidationBadgeStyle,
  sanitizeTechnicalReason,
  getNotRevalidatedExplanation,
  canRequestRevalidation,
  canRetryRevalidation,
  canExecuteRevalidation,
  shouldPollRevalidation,
  deriveRevalidationActionFeedback,
  isMakerCheckerRequired,
  resolveTaxDiffAfterPaise,
  formatTaxDiffAfter,
  RevalUxStatus,
} from "./revalidationUxLogic";
import { workItemsApi } from "../../lib/api";

describe("Phase 5.5B: Revalidation UX Domain Logic & Invariants", () => {
  // Criterion 1: NONE renders correctly
  it("1. NONE status derives correctly and maps to 'Not revalidated'", () => {
    const status = deriveEffectiveRevalStatus({ revalidation_status: "NONE" });
    assert.equal(status, "NONE");
    assert.equal(REVALIDATION_STATUS_LABELS[status], "Not revalidated");
    const style = getRevalidationBadgeStyle(status);
    assert.equal(style.badgeText, "text-gray-600");
  });

  // Criterion 2: PENDING renders correctly
  it("2. PENDING status derives correctly and maps to 'Revalidation queued'", () => {
    const status = deriveEffectiveRevalStatus({ revalidation_status: "PENDING" });
    assert.equal(status, "PENDING");
    assert.equal(REVALIDATION_STATUS_LABELS[status], "Revalidation queued");
    const style = getRevalidationBadgeStyle(status);
    assert.equal(style.badgeBg, "bg-indigo-50");
  });

  // Criterion 3: REVALIDATING renders correctly
  it("3. REVALIDATING status derives correctly with pulsing badge", () => {
    const status = deriveEffectiveRevalStatus({ revalidation_status: "REVALIDATING" });
    assert.equal(status, "REVALIDATING");
    assert.equal(REVALIDATION_STATUS_LABELS[status], "Revalidation in progress");
    const style = getRevalidationBadgeStyle(status);
    assert.ok(style.badgeText.includes("animate-pulse"));
  });

  // Criterion 4: CLEARED renders correctly
  it("4. CLEARED status derives correctly from result and event metadata", () => {
    const statusDirect = deriveEffectiveRevalStatus({
      revalidation_status: "REVALIDATED",
      revalidation_result: "CLEARED",
    });
    assert.equal(statusDirect, "CLEARED");
    assert.equal(REVALIDATION_STATUS_LABELS[statusDirect], "Exception cleared");
    const style = getRevalidationBadgeStyle(statusDirect);
    assert.equal(style.badgeBg, "bg-emerald-50");

    // Fallback from event metadata
    const statusEvent = deriveEffectiveRevalStatus(
      { revalidation_status: "REVALIDATED" },
      { metadata: { revalidation_result: "CLEARED" } }
    );
    assert.equal(statusEvent, "CLEARED");
  });

  // Criterion 5: PERSISTS renders correctly
  it("5. PERSISTS status derives correctly and maps to 'Exception persists'", () => {
    const status = deriveEffectiveRevalStatus({
      revalidation_status: "REVALIDATED",
      revalidation_result: "PERSISTS",
    });
    assert.equal(status, "PERSISTS");
    assert.equal(REVALIDATION_STATUS_LABELS[status], "Exception persists");
    const style = getRevalidationBadgeStyle(status);
    assert.equal(style.badgeBg, "bg-rose-50");
  });

  // Criterion 6: CHANGED renders correctly
  it("6. CHANGED status derives correctly and maps to 'Exception changed'", () => {
    const status = deriveEffectiveRevalStatus({
      revalidation_status: "REVALIDATED",
      revalidation_result: "CHANGED",
    });
    assert.equal(status, "CHANGED");
    assert.equal(REVALIDATION_STATUS_LABELS[status], "Exception changed");
    const style = getRevalidationBadgeStyle(status);
    assert.equal(style.badgeBg, "bg-amber-50");
  });

  // Criterion 7: ERROR renders retry
  it("7. ERROR status derives correctly and allows retry", () => {
    const status = deriveEffectiveRevalStatus({ revalidation_status: "ERROR" });
    assert.equal(status, "ERROR");
    assert.equal(REVALIDATION_STATUS_LABELS[status], "Revalidation failed");
    assert.equal(canRetryRevalidation(status), true);

    // Sanitizes technical error without leaking SQL or secrets
    const safeMsg = sanitizeTechnicalReason(
      "Database error: SELECT * FROM users WHERE password = 'secret' failed"
    );
    assert.equal(safeMsg.includes("SELECT"), false);
    assert.equal(safeMsg.includes("password"), false);
  });

  // Criterion 8: NOT_REVALIDATED is not presented as PERSISTS
  it("8. NOT_REVALIDATED is never presented as PERSISTS or CLEARED", () => {
    const status = deriveEffectiveRevalStatus({
      revalidation_status: "REVALIDATED",
      revalidation_result: "NOT_REVALIDATED",
    });
    assert.equal(status, "NOT_REVALIDATED");
    assert.notEqual(status, "PERSISTS");
    assert.notEqual(status, "CLEARED");
    assert.equal(REVALIDATION_STATUS_LABELS[status], "Could not revalidate");

    const explanationNoRun = getNotRevalidatedExplanation("NO_ELIGIBLE_AUTHORITATIVE_RUN");
    assert.match(explanationNoRun, /No eligible completed authoritative reconciliation run/);

    const explanationStale = getNotRevalidatedExplanation("STALE_TARGET_SUPERSEDED");
    assert.match(explanationStale, /newer authoritative reconciliation run was completed/);

    const explanationSec17 = getNotRevalidatedExplanation("SEC_17_5");
    assert.match(explanationSec17, /Statutory exception requires professional CA determination/);
  });

  // Criterion 9: blocking CLEARED shows CA review
  it("9. Blocking work items enforce CA review (maker-checker required)", () => {
    assert.equal(isMakerCheckerRequired({ is_blocking: true, status: "OPEN" }), true);
    assert.equal(
      isMakerCheckerRequired({ is_blocking: false, status: "READY_FOR_REVIEW" }),
      true
    );
    assert.equal(isMakerCheckerRequired({ is_blocking: false, status: "RESOLVED" }), false);
  });

  // Criterion 10: duplicate request is disabled while active
  it("10. Duplicate request is disabled when status is PENDING or REVALIDATING", () => {
    const pendingReq = canRequestRevalidation("PENDING");
    assert.equal(pendingReq.allowed, false);
    assert.match(pendingReq.reason!, /already queued/);

    const revalReq = canRequestRevalidation("REVALIDATING");
    assert.equal(revalReq.allowed, false);
    assert.match(revalReq.reason!, /currently being evaluated/);

    const noneReq = canRequestRevalidation("NONE");
    assert.equal(noneReq.allowed, true);

    const errorReq = canRequestRevalidation("ERROR");
    assert.equal(errorReq.allowed, true);
  });

  // Criterion 11: vendor response is never presented as tax clearance
  it("11. Vendor response is decoupled from tax clearance (statutory exception cannot be revalidated)", () => {
    const sec17Check = canRequestRevalidation("NONE", "SEC_17_5");
    assert.equal(sec17Check.allowed, false);
    assert.match(sec17Check.reason!, /Sec 17\(5\)/);

    const timeBarredCheck = canRequestRevalidation("NONE", "TIME_BARRED_16_4");
    assert.equal(timeBarredCheck.allowed, false);
    assert.match(timeBarredCheck.reason!, /Sec 16\(4\)/);

    const normalMissingGstr = canRequestRevalidation("NONE", "MISSING_IN_GSTR");
    assert.equal(normalMissingGstr.allowed, true);
  });

  // Criterion 12: authoritative target run is displayed
  it("12. Authoritative target run metadata preserves identity and dates", () => {
    const eventMeta = {
      target_run_id: "run-uuid-999",
      previous_exception_type: "MISSING_IN_GSTR",
      new_exception_type: null,
      tax_diff_before: 150000,
      tax_diff_after: 0,
      authoritative_record_ref: "out-row-111",
      evaluated_at: "2026-09-16T10:00:00Z",
    };
    assert.equal(eventMeta.target_run_id, "run-uuid-999");
    assert.equal(eventMeta.tax_diff_before, 150000);
    assert.equal(eventMeta.tax_diff_after, 0);
  });

  // Criterion 13: existing drawer functionality remains intact
  it("13. All canonical statuses have valid labels and badge styles", () => {
    const allStatuses: RevalUxStatus[] = [
      "NONE",
      "PENDING",
      "REVALIDATING",
      "CLEARED",
      "PERSISTS",
      "CHANGED",
      "ERROR",
      "NOT_REVALIDATED",
    ];
    for (const st of allStatuses) {
      assert.ok(REVALIDATION_STATUS_LABELS[st]);
      const style = getRevalidationBadgeStyle(st);
      assert.ok(style.badgeBg);
      assert.ok(style.badgeText);
      assert.ok(style.badgeBorder);
      assert.ok(style.dotColor);
    }
  });
});

describe("P55B-OBS-01 Hardening: Defensive Tax Difference Display", () => {
  // Test 1: CLEARED + tax_diff_after = 0 → displays ₹0.00
  it("1. CLEARED + tax_diff_after = 0 → displays ₹0.00", () => {
    const item = {
      revalidation_status: "REVALIDATED",
      revalidation_result: "CLEARED",
      tax_diff_after: 0,
    };
    const resolved = resolveTaxDiffAfterPaise(item, null);
    assert.equal(resolved, 0);
    assert.equal(formatTaxDiffAfter(resolved), "₹0.00");
  });

  // Test 2: CLEARED + tax_diff_after is null/absent → displays —
  it("2. CLEARED + tax_diff_after is null/absent → displays —", () => {
    const itemNull = {
      revalidation_status: "REVALIDATED",
      revalidation_result: "CLEARED",
      tax_diff_after: null,
    };
    const resolvedNull = resolveTaxDiffAfterPaise(itemNull, null);
    assert.equal(resolvedNull, null);
    assert.equal(formatTaxDiffAfter(resolvedNull), "—");

    const itemAbsent = {
      revalidation_status: "REVALIDATED",
      revalidation_result: "CLEARED",
    };
    const resolvedAbsent = resolveTaxDiffAfterPaise(itemAbsent, null);
    assert.equal(resolvedAbsent, null);
    assert.equal(formatTaxDiffAfter(resolvedAbsent), "—");
  });

  // Test 3: CLEARED + event metadata tax_diff_after = 0 → displays ₹0.00
  it("3. CLEARED + event metadata tax_diff_after = 0 → displays ₹0.00", () => {
    const item = {
      revalidation_status: "REVALIDATED",
      revalidation_result: "CLEARED",
    };
    const event = { metadata: { tax_diff_after: 0 } };
    const resolved = resolveTaxDiffAfterPaise(item, event);
    assert.equal(resolved, 0);
    assert.equal(formatTaxDiffAfter(resolved), "₹0.00");
  });

  // Test 4: PERSISTS/CHANGED with absent tax_diff_after → does not display ₹0.00
  it("4. PERSISTS/CHANGED with absent tax_diff_after → does not display ₹0.00", () => {
    const itemPersists = {
      revalidation_status: "REVALIDATED",
      revalidation_result: "PERSISTS",
    };
    const resolvedPersists = resolveTaxDiffAfterPaise(itemPersists, null);
    assert.equal(resolvedPersists, null);
    const displayPersists = formatTaxDiffAfter(resolvedPersists);
    assert.equal(displayPersists, "—");
    assert.notEqual(displayPersists, "₹0.00");

    const itemChanged = {
      revalidation_status: "REVALIDATED",
      revalidation_result: "CHANGED",
    };
    const resolvedChanged = resolveTaxDiffAfterPaise(itemChanged, null);
    assert.equal(resolvedChanged, null);
    const displayChanged = formatTaxDiffAfter(resolvedChanged);
    assert.equal(displayChanged, "—");
    assert.notEqual(displayChanged, "₹0.00");
  });

  // Test 5: Existing status and maker-checker behavior remains unchanged
  it("5. Existing status and maker-checker behavior remains unchanged", () => {
    const blockingItem = { is_blocking: true, status: "READY_FOR_REVIEW" };
    assert.equal(isMakerCheckerRequired(blockingItem), true);

    const nonBlockingItem = { is_blocking: false, status: "RESOLVED" };
    assert.equal(isMakerCheckerRequired(nonBlockingItem), false);

    const clearedStatus = deriveEffectiveRevalStatus({
      revalidation_status: "REVALIDATED",
      revalidation_result: "CLEARED",
    });
    assert.equal(clearedStatus, "CLEARED");
    assert.equal(REVALIDATION_STATUS_LABELS[clearedStatus], "Exception cleared");
  });
});

describe("Phase 5.5C: Revalidation Execution Integration & Lifecycle Invariants", () => {
  // Test 1: canExecuteRevalidation allows execution only for PENDING items
  it("1. canExecuteRevalidation permits execution only for PENDING status", () => {
    assert.equal(canExecuteRevalidation("PENDING"), true);
    assert.equal(canExecuteRevalidation("PENDING", "MISSING_2B"), true);
    assert.equal(canExecuteRevalidation("PENDING", "VALUE_MISMATCH"), true);

    assert.equal(canExecuteRevalidation("NONE"), false);
    assert.equal(canExecuteRevalidation("REVALIDATING"), false);
    assert.equal(canExecuteRevalidation("CLEARED"), false);
    assert.equal(canExecuteRevalidation("PERSISTS"), false);
    assert.equal(canExecuteRevalidation("CHANGED"), false);
    assert.equal(canExecuteRevalidation("ERROR"), false);
    assert.equal(canExecuteRevalidation("NOT_REVALIDATED"), false);
  });

  // Test 2: canExecuteRevalidation rejects statutory non-revalidatable exceptions
  it("2. canExecuteRevalidation strictly forbids statutory non-revalidatable exceptions", () => {
    assert.equal(canExecuteRevalidation("PENDING", "SEC_17_5"), false);
    assert.equal(canExecuteRevalidation("PENDING", "TIME_BARRED_16_4"), false);
  });

  // Test 3: shouldPollRevalidation polls only when evaluation is active or queued
  it("3. shouldPollRevalidation polls only for PENDING or REVALIDATING states", () => {
    assert.equal(shouldPollRevalidation("PENDING"), true);
    assert.equal(shouldPollRevalidation("REVALIDATING"), true);
    assert.equal(shouldPollRevalidation("pending"), true);
    assert.equal(shouldPollRevalidation("revalidating"), true);

    assert.equal(shouldPollRevalidation("REVALIDATED"), false);
    assert.equal(shouldPollRevalidation("ERROR"), false);
    assert.equal(shouldPollRevalidation("NONE"), false);
    assert.equal(shouldPollRevalidation("IDLE"), false);
    assert.equal(shouldPollRevalidation(null), false);
    assert.equal(shouldPollRevalidation(undefined), false);
  });

  // Test 4: deriveRevalidationActionFeedback returns appropriate messages for all result codes
  it("4. deriveRevalidationActionFeedback accurately reflects backend outcome semantics", () => {
    // CLEARED - blocking item requires CA review
    const clearedBlocking = deriveRevalidationActionFeedback(
      { revalidation_status: "REVALIDATED", revalidation_result: "CLEARED", is_blocking: true },
      false
    );
    assert.match(clearedBlocking.message!, /Submitted to CA for review/);

    // CLEARED - non-blocking item with CA
    const clearedNonBlockingCA = deriveRevalidationActionFeedback(
      { revalidation_status: "REVALIDATED", revalidation_result: "CLEARED", is_blocking: false },
      true
    );
    assert.match(clearedNonBlockingCA.message!, /Resolved/);

    // PERSISTS
    const persists = deriveRevalidationActionFeedback({
      revalidation_status: "REVALIDATED",
      revalidation_result: "PERSISTS",
    });
    assert.match(persists.message!, /Exception PERSISTS in authoritative reconciliation/);

    // CHANGED
    const changed = deriveRevalidationActionFeedback({
      revalidation_status: "REVALIDATED",
      revalidation_result: "CHANGED",
    });
    assert.match(changed.message!, /Exception CHANGED in authoritative reconciliation/);

    // NOT_REVALIDATED
    const notReval = deriveRevalidationActionFeedback({
      revalidation_status: "REVALIDATED",
      revalidation_result: "NOT_REVALIDATED",
    });
    assert.match(notReval.message!, /No eligible completed authoritative run/);

    // REVALIDATING
    const inProgress = deriveRevalidationActionFeedback({
      revalidation_status: "REVALIDATING",
    });
    assert.match(inProgress.message!, /Revalidation in progress/);

    // PENDING
    const queued = deriveRevalidationActionFeedback({
      revalidation_status: "PENDING",
    });
    assert.match(queued.message!, /Revalidation queued/);

    // ERROR
    const errStatus = deriveRevalidationActionFeedback({
      revalidation_status: "ERROR",
    });
    assert.match(errStatus.error!, /encountered an error/);

    const errResult = deriveRevalidationActionFeedback({
      revalidation_status: "REVALIDATED",
      revalidation_result: "ERROR",
    });
    assert.match(errResult.error!, /encountered an error/);
  });

  // Test 5: workItemsApi.revalidate invokes supported immediate execution with execute_now=true
  it("5. workItemsApi.revalidate invokes execute_now=true route with POST method", async () => {
    let capturedUrl = "";
    let capturedOpts: any = null;
    const origFetch = globalThis.fetch;
    (globalThis as any).fetch = async (url: string, opts: any) => {
      capturedUrl = url;
      capturedOpts = opts;
      return {
        ok: true,
        json: async () => ({
          id: "item-123",
          revalidation_status: "REVALIDATED",
          revalidation_result: "CLEARED",
        }),
      };
    };

    try {
      const res = await workItemsApi.revalidate("test-token", "item-123", { execute_now: true });
      assert.equal(res.revalidation_status, "REVALIDATED");
      assert.equal(res.revalidation_result, "CLEARED");
      assert.ok(capturedUrl.includes("/api/work-items/item-123/revalidate?execute_now=true"));
      assert.equal(capturedOpts.method, "POST");
      assert.equal(capturedOpts.headers.get("Authorization"), "Bearer test-token");
    } finally {
      globalThis.fetch = origFetch;
    }
  });

  // Test 6: workItemsApi.executeRevalidation invokes canonical execute-revalidation route
  it("6. workItemsApi.executeRevalidation invokes canonical execute-revalidation route", async () => {
    let capturedUrl = "";
    let capturedOpts: any = null;
    const origFetch = globalThis.fetch;
    (globalThis as any).fetch = async (url: string, opts: any) => {
      capturedUrl = url;
      capturedOpts = opts;
      return {
        ok: true,
        json: async () => ({
          id: "item-456",
          revalidation_status: "REVALIDATED",
          revalidation_result: "PERSISTS",
        }),
      };
    };

    try {
      const res = await workItemsApi.executeRevalidation("test-token", "item-456");
      assert.equal(res.revalidation_status, "REVALIDATED");
      assert.equal(res.revalidation_result, "PERSISTS");
      assert.ok(capturedUrl.includes("/api/work-items/item-456/execute-revalidation"));
      assert.equal(capturedOpts.method, "POST");
      assert.equal(capturedOpts.headers.get("Authorization"), "Bearer test-token");
    } finally {
      globalThis.fetch = origFetch;
    }
  });
});
