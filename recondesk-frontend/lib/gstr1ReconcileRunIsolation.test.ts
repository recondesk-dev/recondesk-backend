/**
 * Unit tests for GSTR-1 & GSTR-1A run isolation and session state safety.
 * Verifies that stale session storage / prior run IDs cannot leak into or override
 * fresh in-memory reconciliation results.
 *
 * Run with: node --test lib/gstr1ReconcileRunIsolation.test.ts
 */

import assert from "node:assert/strict";
import { describe, it, beforeEach } from "node:test";
import {
  clearGstr1Result,
  loadGstr1Result,
  loadGstr1RunId,
  persistGstr1Result,
  GSTR1_RECONCILE_RUN_ID_KEY,
  type Gstr1ReconcileResult,
} from "./gstr1Reconcile.ts";

// Mock minimal browser window & sessionStorage
const mockStorage = new Map<string, string>();

(globalThis as unknown as { window: unknown }).window = {};
(globalThis as unknown as { sessionStorage: unknown }).sessionStorage = {
  getItem: (k: string) => mockStorage.get(k) ?? null,
  setItem: (k: string, v: string) => mockStorage.set(k, String(v)),
  removeItem: (k: string) => mockStorage.delete(k),
  clear: () => mockStorage.clear(),
};

describe("GSTR-1 Run Isolation & Session Freshness", () => {
  beforeEach(() => {
    mockStorage.clear();
    clearGstr1Result();
  });

  it("prioritizes fresh in-memory run_id over stale sessionStorage run_id", () => {
    // Simulate stale Run 18 in sessionStorage
    mockStorage.set(GSTR1_RECONCILE_RUN_ID_KEY, "run-18-stale-id");

    // Execute Run 19 into in-memory store
    const run19Result: Gstr1ReconcileResult = {
      success: true,
      run_id: "run-19-fresh-id",
      summary: { matched_count: 50, mismatch_count: 5 },
      matched: [],
      mismatches: [],
      tie_out: {},
    };

    persistGstr1Result(run19Result);

    // loadGstr1RunId must return Run 19, not the stale Run 18
    assert.equal(loadGstr1RunId(), "run-19-fresh-id");
    assert.equal(loadGstr1Result()?.run_id, "run-19-fresh-id");
    assert.equal(mockStorage.get(GSTR1_RECONCILE_RUN_ID_KEY), "run-19-fresh-id");
  });

  it("clearGstr1Result purges both in-memory payload and sessionStorage run_id", () => {
    mockStorage.set(GSTR1_RECONCILE_RUN_ID_KEY, "run-18-stale-id");
    persistGstr1Result({
      success: true,
      run_id: "run-18-stale-id",
      summary: {},
      matched: [],
      mismatches: [],
      tie_out: {},
    });

    clearGstr1Result();

    assert.equal(loadGstr1Result(), null);
    assert.equal(loadGstr1RunId(), null);
    assert.equal(mockStorage.get(GSTR1_RECONCILE_RUN_ID_KEY), undefined);
  });

  it("ad-hoc run without run_id does not inherit stale sessionStorage ID", () => {
    mockStorage.set(GSTR1_RECONCILE_RUN_ID_KEY, "run-18-stale-id");

    // Ad-hoc run (no client_gstin_id, run_id is undefined)
    const adHocResult: Gstr1ReconcileResult = {
      success: true,
      summary: { matched_count: 10, mismatch_count: 2 },
      matched: [],
      mismatches: [],
      tie_out: {},
    };

    persistGstr1Result(adHocResult);

    // Stale sessionStorage must be purged by persistGstr1Result
    assert.equal(mockStorage.get(GSTR1_RECONCILE_RUN_ID_KEY), undefined);
    assert.equal(loadGstr1RunId(), null);
    assert.equal(loadGstr1Result(), adHocResult);
  });
});
