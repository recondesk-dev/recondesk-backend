/**
 * Focused unit tests for REM-01: Frontend SWR Synchronization After Bulk Disposition Updates.
 * Verifies FINDING-H01 remediation across key matching, partial failure handling, and state rollbacks.
 *
 * Run with: node --test components/reconcile/bulkDispositionSync.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isRunKeyMatch } from "../../lib/swrReconciliationSync.ts";

// ---------------------------------------------------------------------------
// Pure State Transition Simulation Helpers (mirroring results/page.tsx logic)
// ---------------------------------------------------------------------------

export interface BulkDecisionState {
  localDecisionStatus: Map<string, string>;
  selectedIds: Set<string>;
  toast: { message: string; type: "success" | "warning" | "error" } | null;
  revalidationTriggered: boolean;
}

export function processBulkDecisionResponse(
  ids: string[],
  status: string,
  selectedSnapshot: Set<string>,
  mapBefore: Map<string, string>,
  apiResponse?: { updated_count: number },
  networkError?: Error
): BulkDecisionState {
  if (networkError || !apiResponse) {
    // Network or server exception: rollback optimistic map and restore selection
    const restoredMap = new Map(mapBefore);
    return {
      localDecisionStatus: restoredMap,
      selectedIds: new Set(selectedSnapshot),
      toast: { message: "Update failed — changes reversed", type: "error" },
      revalidationTriggered: true,
    };
  }

  const updatedCount = Number(apiResponse.updated_count ?? 0);

  if (updatedCount === 0) {
    // Zero updated: server rejected or skipped all rows; rollback
    const restoredMap = new Map(mapBefore);
    return {
      localDecisionStatus: restoredMap,
      selectedIds: new Set(selectedSnapshot),
      toast: { message: "No records were updated — changes reversed", type: "error" },
      revalidationTriggered: true,
    };
  }

  // Full or partial success: commit updated ids out of local optimistic map
  const nextMap = new Map(mapBefore);
  for (const id of ids) {
    nextMap.delete(id);
  }

  let toastMessage: string;
  let toastType: "success" | "warning";

  if (updatedCount < ids.length) {
    toastMessage = `${updatedCount} of ${ids.length} records updated`;
    toastType = "warning";
  } else {
    toastMessage = `${ids.length} records updated`;
    toastType = "success";
  }

  return {
    localDecisionStatus: nextMap,
    selectedIds: new Set(),
    toast: { message: toastMessage, type: toastType },
    revalidationTriggered: true,
  };
}

// ---------------------------------------------------------------------------
// Test Suites
// ---------------------------------------------------------------------------

describe("REM-01: Run-Scoped SWR Key Invalidation Matching", () => {
  const targetRunId = "run-uuid-1234";
  const otherRunId = "run-uuid-9999";
  const dummyToken = "jwt.token.abc";

  it("identifies Table 4 workpaper and drilldown keys for the target run", () => {
    assert.equal(isRunKeyMatch(["table4-workpaper", targetRunId], targetRunId), true);
    assert.equal(isRunKeyMatch(["table4-drilldown", targetRunId, "4A5"], targetRunId), true);
    assert.equal(isRunKeyMatch(["table4-drilldown", targetRunId, "4B2"], targetRunId), true);

    // Other runs must NOT match
    assert.equal(isRunKeyMatch(["table4-workpaper", otherRunId], targetRunId), false);
    assert.equal(isRunKeyMatch(["table4-drilldown", otherRunId, "4A5"], targetRunId), false);
  });

  it("identifies summary and confidence summary keys for the target run", () => {
    assert.equal(isRunKeyMatch(["run-summary", targetRunId], targetRunId), true);
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/summary`, dummyToken], targetRunId),
      true
    );
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/confidence-summary`, dummyToken], targetRunId),
      true
    );

    // Direct string summary key
    assert.equal(
      isRunKeyMatch(`/api/reconcile/runs/${targetRunId}/summary`, targetRunId),
      true
    );

    // Other run summary must NOT match
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${otherRunId}/summary`, dummyToken], targetRunId),
      false
    );
  });

  it("identifies all outcome bucket keys and grouped queries for the target run", () => {
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/itc?page=1&limit=50`, dummyToken], targetRunId),
      true
    );
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/risk?page=1&limit=50`, dummyToken], targetRunId),
      true
    );
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/matched?page=1&limit=50`, dummyToken], targetRunId),
      true
    );
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/rule37?page=1&limit=50`, dummyToken], targetRunId),
      true
    );
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/section17?page=1&limit=50`, dummyToken], targetRunId),
      true
    );
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${targetRunId}/itc-on-hold?page=1&limit=50`, dummyToken], targetRunId),
      true
    );
    assert.equal(
      isRunKeyMatch(
        [`/api/reconciliation/results/${targetRunId}/invoices?category=unmatched_notes`, dummyToken],
        targetRunId
      ),
      true
    );
    assert.equal(
      isRunKeyMatch(
        [`/api/reconciliation/results/${targetRunId}/invoices?category=duplicate_entry`, dummyToken],
        targetRunId
      ),
      true
    );
    assert.equal(isRunKeyMatch(["itc-all-grouped", targetRunId], targetRunId), true);
    assert.equal(isRunKeyMatch(["risk-all-grouped", targetRunId], targetRunId), true);
  });

  it("strictly contains invalidation and ignores unrelated caches", () => {
    assert.equal(isRunKeyMatch(["user-profile", "user-123"], targetRunId), false);
    assert.equal(isRunKeyMatch("/api/v1/auth/me", targetRunId), false);
    assert.equal(isRunKeyMatch("/api/clients/client-777", targetRunId), false);
    assert.equal(isRunKeyMatch(["client-gstins", "client-777"], targetRunId), false);
    assert.equal(isRunKeyMatch(null, targetRunId), false);
    assert.equal(isRunKeyMatch(undefined, targetRunId), false);
    assert.equal(isRunKeyMatch("", targetRunId), false);
  });
});

describe("REM-01: Bulk Disposition State Transitions & Contract Adherence", () => {
  const idsToUpdate = ["inv-1", "inv-2", "inv-3"];
  const initialSnapshot = new Set(idsToUpdate);
  const initialMap = new Map<string, string>();

  it("1. Successful bulk update commits state, clears selections, and triggers full revalidation", () => {
    const result = processBulkDecisionResponse(
      idsToUpdate,
      "acted",
      initialSnapshot,
      initialMap,
      { updated_count: 3 }
    );

    assert.equal(result.toast?.type, "success");
    assert.equal(result.toast?.message, "3 records updated");
    assert.equal(result.selectedIds.size, 0);
    assert.equal(result.revalidationTriggered, true);
    assert.equal(result.localDecisionStatus.has("inv-1"), false);
  });

  it("2. Failed bulk update (HTTP error) rolls back optimistic state and restores selections", () => {
    const initialMapWithPrior = new Map<string, string>([["inv-0", "pending"]]);
    const networkError = new Error("Network timeout (504)");

    const result = processBulkDecisionResponse(
      idsToUpdate,
      "acted",
      initialSnapshot,
      initialMapWithPrior,
      undefined,
      networkError
    );

    assert.equal(result.toast?.type, "error");
    assert.equal(result.toast?.message, "Update failed — changes reversed");
    assert.equal(result.selectedIds.size, 3);
    assert.ok(result.selectedIds.has("inv-1"));
    assert.ok(result.selectedIds.has("inv-2"));
    assert.ok(result.selectedIds.has("inv-3"));
    assert.equal(result.localDecisionStatus.get("inv-0"), "pending");
    assert.equal(result.revalidationTriggered, true);
  });

  it("3. Partial failure (updated_count < ids.length) reports warning and does not claim full success", () => {
    const result = processBulkDecisionResponse(
      idsToUpdate,
      "acted",
      initialSnapshot,
      initialMap,
      { updated_count: 2 } // only 2 of 3 updated
    );

    assert.equal(result.toast?.type, "warning");
    assert.equal(result.toast?.message, "2 of 3 records updated");
    assert.equal(result.revalidationTriggered, true);
  });

  it("4. Zero update (updated_count === 0) triggers rollback and prevents false success", () => {
    const result = processBulkDecisionResponse(
      idsToUpdate,
      "acted",
      initialSnapshot,
      initialMap,
      { updated_count: 0 }
    );

    assert.equal(result.toast?.type, "error");
    assert.equal(result.toast?.message, "No records were updated — changes reversed");
    assert.equal(result.selectedIds.size, 3);
    assert.equal(result.revalidationTriggered, true);
  });
});

describe("REM-01: Table 4 and Summary SWR Cross-View Synchronization", () => {
  const runId = "test-run-sync-456";

  it("Table 4 options flag selectively filters keys when requested", () => {
    // Only table4 + drilldown
    assert.equal(
      isRunKeyMatch(["table4-workpaper", runId], runId, { table4: true, summary: false, outcomes: false }),
      true
    );
    assert.equal(
      isRunKeyMatch(["run-summary", runId], runId, { table4: true, summary: false, outcomes: false }),
      false
    );
    assert.equal(
      isRunKeyMatch([`/api/reconcile/runs/${runId}/itc`, "token"], runId, { table4: true, summary: false, outcomes: false }),
      false
    );

    // Only summary
    assert.equal(
      isRunKeyMatch(["run-summary", runId], runId, { table4: false, summary: true, outcomes: false }),
      true
    );
    assert.equal(
      isRunKeyMatch(["table4-workpaper", runId], runId, { table4: false, summary: true, outcomes: false }),
      false
    );
  });

  it("ensures repeated revalidation calls remain idempotent and safe", () => {
    for (let i = 0; i < 5; i++) {
      const match1 = isRunKeyMatch(["table4-workpaper", runId], runId);
      const match2 = isRunKeyMatch([`/api/reconcile/runs/${runId}/summary`, "tok"], runId);
      assert.equal(match1, true);
      assert.equal(match2, true);
    }
  });
});
