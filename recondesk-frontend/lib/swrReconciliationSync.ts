import { mutate as swrMutate } from "swr";

export interface RevalidateRunOptions {
  table4?: boolean;
  drilldown?: boolean;
  summary?: boolean;
  outcomes?: boolean;
}

/**
 * Pure predicate to determine whether an SWR cache key belongs to the specified reconciliation run.
 * Ensures targeted cache invalidation without touching other clients or runs.
 */
export function isRunKeyMatch(
  key: unknown,
  runId: string,
  options: RevalidateRunOptions = {}
): boolean {
  if (!key || !runId) return false;
  const {
    table4 = true,
    drilldown = true,
    summary = true,
    outcomes = true,
  } = options;

  // 1. Direct string key
  if (typeof key === "string") {
    if (
      summary &&
      (key.includes(`/api/reconcile/runs/${runId}/summary`) ||
        key.includes(`/api/reconcile/runs/${runId}/confidence-summary`))
    ) {
      return true;
    }
    if (
      outcomes &&
      (key.startsWith(`/api/reconcile/runs/${runId}/`) ||
        key.startsWith(`/api/reconciliation/results/${runId}/`) ||
        key.startsWith(`/api/reconciliations/${runId}/`))
    ) {
      return true;
    }
    return false;
  }

  // 2. Array / Tuple key (e.g. SWR keys like ['table4-workpaper', runId], [url, token])
  if (Array.isArray(key) && key.length > 0) {
    const first = key[0];

    // Table 4 workpaper key: ['table4-workpaper', runId]
    if (table4 && first === "table4-workpaper") {
      return key[1] === runId || !key[1];
    }

    // Table 4 drilldown key: ['table4-drilldown', runId, ...]
    if (drilldown && first === "table4-drilldown") {
      return key[1] === runId || !key[1];
    }

    // Custom run summary tuple: ['run-summary', runId]
    if (summary && first === "run-summary") {
      return key[1] === runId || !key[1];
    }

    // Grouped outcome rows: ['itc-all-grouped', runId, ...] or ['risk-all-grouped', runId, ...]
    if (outcomes && (first === "itc-all-grouped" || first === "risk-all-grouped")) {
      return key[1] === runId || !key[1];
    }

    // Tuple where first element is an API URL string
    if (typeof first === "string") {
      if (
        summary &&
        (first.includes(`/api/reconcile/runs/${runId}/summary`) ||
          first.includes(`/api/reconcile/runs/${runId}/confidence-summary`))
      ) {
        return true;
      }
      if (
        outcomes &&
        (first.startsWith(`/api/reconcile/runs/${runId}/`) ||
          first.startsWith(`/api/reconciliation/results/${runId}/`) ||
          first.startsWith(`/api/reconciliations/${runId}/`))
      ) {
        return true;
      }
    }
  }

  return false;
}

/**
 * Invalidate all SWR cache entries for a given reconciliation run.
 * Guarantees that Table 4, run summary, drilldown, and outcome lists
 * synchronize immediately after bulk updates, dispositions, or settlements.
 */
export async function revalidateReconciliationRun(
  runId: string,
  options: RevalidateRunOptions = {}
): Promise<void> {
  if (!runId) return;
  try {
    await swrMutate(
      (key) => isRunKeyMatch(key, runId, options),
      undefined,
      { revalidate: true }
    );
  } catch (err) {
    console.error("[swrReconciliationSync] Error during run revalidation:", err);
  }
}
