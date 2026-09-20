/**
 * Focused unit tests for REM-01: Review Required Disposition Presentation.
 *
 * Verifies:
 * 1. Effective status calculation (optimistic override -> server hydration fallback).
 * 2. State-aware drawer action buttons logic (pending, acted, ignored).
 * 3. Status pill rendering mapping for Review Required cards.
 * 4. Run finalization locking across drawer controls.
 *
 * Run with: node --test components/reconcile/reviewRequiredPresentation.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

export type DecisionStatus = "pending" | "acted" | "ignored";

export interface MockReconcileRow {
  id: string;
  decision_status: DecisionStatus;
  supplier_gstin?: string;
  invoice_number?: string;
  amount?: number;
}

/**
 * Pure effective-status resolver matching results/page.tsx:
 * localDecisionStatus.get(row.id) ?? row.decision_status
 */
export function resolveEffectiveStatus(
  row: MockReconcileRow,
  localMap: Map<string, DecisionStatus>
): DecisionStatus {
  return localMap.get(row.id) ?? row.decision_status;
}

export interface DrawerButtonConfig {
  status: DecisionStatus;
  isActedConfirmed: boolean;
  isIgnoredConfirmed: boolean;
  canMarkActed: boolean;
  canMarkIgnored: boolean;
  canResetPending: boolean;
  actedLabel: string;
  ignoredLabel: string;
}

/**
 * Derives drawer action button states matching results/page.tsx:6278-6370.
 */
export function getDrawerActionConfig(
  status: DecisionStatus,
  isRunFinalized: boolean
): DrawerButtonConfig {
  if (status === "acted") {
    return {
      status: "acted",
      isActedConfirmed: true,
      isIgnoredConfirmed: false,
      canMarkActed: false, // already acted; active indicator
      canMarkIgnored: !isRunFinalized,
      canResetPending: !isRunFinalized,
      actedLabel: "Acted ✓",
      ignoredLabel: "Mark as Ignored",
    };
  }

  if (status === "ignored") {
    return {
      status: "ignored",
      isActedConfirmed: false,
      isIgnoredConfirmed: true,
      canMarkActed: !isRunFinalized,
      canMarkIgnored: false, // already ignored; active indicator
      canResetPending: !isRunFinalized,
      actedLabel: "Mark as Acted",
      ignoredLabel: "Ignored",
    };
  }

  return {
    status: "pending",
    isActedConfirmed: false,
    isIgnoredConfirmed: false,
    canMarkActed: !isRunFinalized,
    canMarkIgnored: !isRunFinalized,
    canResetPending: false,
    actedLabel: "Mark as Acted",
    ignoredLabel: "Mark as Ignored",
  };
}

/**
 * DecisionStatusPill text mapping matching components/reconcile/ResultsUi.tsx:580
 */
export function getStatusPillText(status: DecisionStatus): string {
  if (status === "acted") return "Done";
  if (status === "ignored") return "Ignored";
  return "Pending";
}

// ---------------------------------------------------------------------------
// Test Suites
// ---------------------------------------------------------------------------

describe("REM-01: Effective Status Resolution for Review Required", () => {
  const row: MockReconcileRow = {
    id: "rr:003e437b-6697-47fe-a07a-3846def231cf",
    decision_status: "pending",
  };

  it("1. Returns hydrated server status when no optimistic override exists", () => {
    const localMap = new Map<string, DecisionStatus>();
    assert.equal(resolveEffectiveStatus(row, localMap), "pending");

    const actedRow: MockReconcileRow = { ...row, decision_status: "acted" };
    assert.equal(resolveEffectiveStatus(actedRow, localMap), "acted");

    const ignoredRow: MockReconcileRow = { ...row, decision_status: "ignored" };
    assert.equal(resolveEffectiveStatus(ignoredRow, localMap), "ignored");
  });

  it("2. Optimistic status immediately overrides server status", () => {
    const localMap = new Map<string, DecisionStatus>([[row.id, "acted"]]);
    assert.equal(resolveEffectiveStatus(row, localMap), "acted");
  });

  it("3. Clearing optimistic status restores server status", () => {
    const localMap = new Map<string, DecisionStatus>([[row.id, "acted"]]);
    assert.equal(resolveEffectiveStatus(row, localMap), "acted");

    localMap.delete(row.id);
    assert.equal(resolveEffectiveStatus(row, localMap), "pending");
  });
});

describe("REM-01: Drawer Action Buttons State-Aware Behavior", () => {
  it("1. Pending record presents both action buttons without reset", () => {
    const cfg = getDrawerActionConfig("pending", false);
    assert.equal(cfg.status, "pending");
    assert.equal(cfg.actedLabel, "Mark as Acted");
    assert.equal(cfg.ignoredLabel, "Mark as Ignored");
    assert.equal(cfg.canMarkActed, true);
    assert.equal(cfg.canMarkIgnored, true);
    assert.equal(cfg.canResetPending, false);
    assert.equal(cfg.isActedConfirmed, false);
    assert.equal(cfg.isIgnoredConfirmed, false);
  });

  it("2. Acted record clearly indicates Acted state and permits switching to Ignored or Reset", () => {
    const cfg = getDrawerActionConfig("acted", false);
    assert.equal(cfg.status, "acted");
    assert.equal(cfg.actedLabel, "Acted ✓");
    assert.equal(cfg.isActedConfirmed, true);
    assert.equal(cfg.canMarkActed, false, "Must not misleadingly show an active 'Mark as Acted' button");
    assert.equal(cfg.canMarkIgnored, true, "Must permit changing to Ignored");
    assert.equal(cfg.canResetPending, true, "Must permit resetting to Pending");
  });

  it("3. Ignored record clearly indicates Ignored state and permits switching to Acted or Reset", () => {
    const cfg = getDrawerActionConfig("ignored", false);
    assert.equal(cfg.status, "ignored");
    assert.equal(cfg.ignoredLabel, "Ignored");
    assert.equal(cfg.isIgnoredConfirmed, true);
    assert.equal(cfg.canMarkIgnored, false, "Must not misleadingly show an active 'Mark as Ignored' button");
    assert.equal(cfg.canMarkActed, true, "Must permit changing to Acted");
    assert.equal(cfg.canResetPending, true, "Must permit resetting to Pending");
  });

  it("4. Finalized runs lock all action and reset buttons", () => {
    const pendingCfg = getDrawerActionConfig("pending", true);
    assert.equal(pendingCfg.canMarkActed, false);
    assert.equal(pendingCfg.canMarkIgnored, false);

    const actedCfg = getDrawerActionConfig("acted", true);
    assert.equal(actedCfg.canMarkIgnored, false);
    assert.equal(actedCfg.canResetPending, false);

    const ignoredCfg = getDrawerActionConfig("ignored", true);
    assert.equal(ignoredCfg.canMarkActed, false);
    assert.equal(ignoredCfg.canResetPending, false);
  });
});

describe("REM-01: Review Required Card Status-Pill Integration", () => {
  it("1. Maps status values to standard DecisionStatusPill texts", () => {
    assert.equal(getStatusPillText("pending"), "Pending");
    assert.equal(getStatusPillText("acted"), "Done");
    assert.equal(getStatusPillText("ignored"), "Ignored");
  });

  it("2. Card status pill reflects effective status for Review Required items", () => {
    const row: MockReconcileRow = {
      id: "rr:003e437b-6697-47fe-a07a-3846def231cf",
      decision_status: "pending",
    };
    const localMap = new Map<string, DecisionStatus>();

    // Initial load: Pending
    assert.equal(getStatusPillText(resolveEffectiveStatus(row, localMap)), "Pending");

    // After user marks as acted: Pill updates to Done
    localMap.set(row.id, "acted");
    assert.equal(getStatusPillText(resolveEffectiveStatus(row, localMap)), "Done");

    // Server re-fetch commits acted: Pill stays Done even without local map
    row.decision_status = "acted";
    localMap.delete(row.id);
    assert.equal(getStatusPillText(resolveEffectiveStatus(row, localMap)), "Done");
  });
});
