"use client";

import Link from "next/link";
import useSWR from "swr";

import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import {
  reconcileRunsApi,
  type ReconcileRunListRow,
} from "@/lib/api";
import { paiseToRupee } from "@/lib/dashboard-portfolio";
import { formatInrFull } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const RUNS_KEY = "backend-runs-list";

function RunsSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-gray-100 px-4 py-4 last:border-b-0"
          >
            <div className="h-4 w-40 rounded bg-[var(--border)]" />
            <div className="h-4 w-24 rounded bg-[var(--border)]" />
            <div className="h-4 w-20 rounded bg-[var(--border)]" />
            <div className="h-4 w-28 rounded bg-[var(--border)]" />
            <div className="h-4 w-24 rounded bg-[var(--border)]" />
            <div className="ml-auto h-10 w-28 rounded bg-[var(--border)]" />
          </div>
        ))}
      </div>
    </div>
  );
}

function formatRunDate(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

function runListStatus(raw: string): { label: string; className: string } {
  const u = (raw || "").trim().toUpperCase();
  if (u === "FAILED") {
    return {
      label: "Failed",
      className: "bg-red-100 text-red-800",
    };
  }
  if (u === "COMPLETED" || u === "FINAL") {
    return {
      label: "Matched",
      className: "bg-green-100 text-green-800",
    };
  }
  return {
    label: "Processing",
    className: "bg-yellow-100 text-yellow-800",
  };
}

function matchedCountFromRow(row: ReconcileRunListRow): number | null {
  if (typeof row.matched_count === "number" && !Number.isNaN(row.matched_count)) {
    return row.matched_count;
  }
  const rs = row.run_summary;
  if (rs && typeof rs === "object") {
    const v = (rs as Record<string, unknown>).matched_count;
    if (typeof v === "number" && !Number.isNaN(v)) return v;
  }
  return null;
}

function itcAtRiskRupee(row: ReconcileRunListRow): number | null {
  const rs = row.run_summary;
  if (rs && typeof rs === "object") {
    const m = rs as Record<string, unknown>;
    // Same metric as results summary bar "At Risk" (wrongful_risk_total_amount).
    for (const k of ["wrongful_itc", "wrongful_itc_paise", "wrongful_risk_paise"] as const) {
      const v = m[k];
      if (typeof v === "number" && !Number.isNaN(v)) {
        return paiseToRupee(v);
      }
    }
  }
  return paiseToRupee(row.wrongful_itc);
}

export function RunsPageContent() {
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const runsKey = authToken ? ([RUNS_KEY, authToken] as const) : null;

  const {
    data: runs,
    error: runsError,
    isLoading: runsLoading,
    mutate: mutateRuns,
  } = useSWR(
    runsKey,
    ([, t]) => reconcileRunsApi.list(t, { limit: 50 }),
    { keepPreviousData: true }
  );

  const resolvingToken = tokenState === null;
  const showSkeleton = resolvingToken || (!!authToken && runsLoading && !runs);

  const showEmpty =
    !showSkeleton &&
    !runsError &&
    authToken &&
    Array.isArray(runs) &&
    runs.length === 0;

  const totalRuns = runs?.length ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">Runs</h2>
        {!showSkeleton && authToken && !runsError && (
          <span className="rounded-full bg-[#F3F4F6] px-2 py-1 text-xs font-medium text-[var(--text-secondary)]">
            {totalRuns}
          </span>
        )}
      </div>

      {runsError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load runs.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--accent)] underline"
            onClick={() => void mutateRuns()}
          >
            Retry
          </button>
        </div>
      )}

      {!authToken && tokenState === false && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Sign in to load reconciliation runs.
        </div>
      )}

      {showEmpty ? (
        <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] px-6 py-16 text-center">
          <div className="mx-auto w-full max-w-[400px]">
            <EmptyStateIllustration className="mx-auto text-gray-400" />
            <h3 className="mt-4 text-lg font-semibold text-gray-900">
              No reconciliation runs yet
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Start from a client profile.
            </p>
            <Link
              href="/clients"
              className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-lg bg-[var(--accent)] px-5 text-sm font-semibold text-white"
            >
              Go to Clients
            </Link>
          </div>
        </div>
      ) : showSkeleton ? (
        <RunsSkeleton />
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <div className="overflow-x-auto">
            <table className="min-w-[860px] w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[#FAFAFB] text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                  <th className="px-4 py-3">Client</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Matched Records</th>
                  <th className="px-4 py-3">ITC at Risk</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {(runs ?? []).map((row) => {
                  const status = runListStatus(row.status);
                  const matched = matchedCountFromRow(row);
                  const itcRisk = itcAtRiskRupee(row);

                  return (
                    <tr
                      key={row.id}
                      className="border-b border-gray-100 hover:bg-gray-50 last:border-b-0"
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium text-[var(--text-primary)]">
                          {row.trade_name ?? "—"}
                        </div>
                        <div className="mt-0.5 font-mono text-xs text-[var(--text-secondary)]">
                          {row.client_gstin ?? "—"}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${status.className}`}
                        >
                          {status.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-[var(--text-secondary)]">
                        {matched != null ? matched.toLocaleString("en-IN") : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono">
                        {itcRisk != null ? formatInrFull(itcRisk) : "—"}
                      </td>
                      <td className="px-4 py-3 text-[var(--text-secondary)]">
                        {row.created_at ? formatRunDate(row.created_at) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/reconcile/runs/${row.id}/results`}
                          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-[var(--border)] px-4 text-sm font-medium text-[var(--text-primary)] hover:bg-gray-50"
                        >
                          View Results
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
