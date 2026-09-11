"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";

import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import {
  reconcileRunsApi,
  type ReconcileRunListRow,
} from "@/lib/api";
import { paiseToRupee } from "@/lib/dashboard-portfolio";
import { formatInrFull } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const LIST_KEY = "backend-reconciliations-list";

type TypeFilter = "all" | "GSTR-2B" | "GSTR-1";

const TYPE_FILTERS: { id: TypeFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "GSTR-2B", label: "GSTR-2B" },
  { id: "GSTR-1", label: "GSTR-1" },
];

function ReconciliationsSkeleton() {
  return (
    <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-[#F0F0F0] px-5 py-4 last:border-b-0"
          >
            <div className="h-4 w-40 rounded bg-gray-100" />
            <div className="h-4 w-24 rounded bg-gray-100" />
            <div className="h-4 w-20 rounded bg-gray-100" />
            <div className="h-4 w-28 rounded bg-gray-100" />
            <div className="h-4 w-24 rounded bg-gray-100" />
            <div className="ml-auto h-10 w-28 rounded-full bg-gray-100" />
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
      className: "bg-[#FEF2F2] text-[#EF4444]",
    };
  }
  if (u === "COMPLETED" || u === "FINAL") {
    return {
      label: "Matched",
      className: "bg-[var(--ink)] text-white",
    };
  }
  return {
    label: "Processing",
    className: "bg-[#F0F0F0] text-[#4B5563]",
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
    const rupees = m["missed_itc_total_amount"];
    if (typeof rupees === "number" && !Number.isNaN(rupees)) {
      return rupees;
    }
    for (const k of ["missed_itc_paise", "itc_at_risk"] as const) {
      const v = m[k];
      if (typeof v === "number" && !Number.isNaN(v)) {
        return paiseToRupee(v);
      }
    }
  }
  return paiseToRupee(row.itc_at_risk);
}

function displayTypeOf(row: ReconcileRunListRow): string {
  const t = (row.display_type || "").trim();
  return t || "GSTR-2B";
}

export function ReconciliationsPageContent() {
  const tReconciliations = useTranslations("reconciliations");
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");

  const listKey = authToken ? ([LIST_KEY, authToken] as const) : null;

  const {
    data: runs,
    error: runsError,
    isLoading: runsLoading,
    mutate: mutateRuns,
  } = useSWR(
    listKey,
    ([, t]) => reconcileRunsApi.list(t, { limit: 50, light: true }),
    { keepPreviousData: true }
  );

  const resolvingToken = tokenState === null;
  const showSkeleton = resolvingToken || (!!authToken && runsLoading && !runs);

  const showsPurchaseRows = typeFilter === "all" || typeFilter === "GSTR-2B";
  const upcomingEmptyLabel =
    typeFilter === "GSTR-1"
      ? "No GSTR-1 reconciliations yet"
      : null;

  const visibleRows = useMemo(() => {
    if (!showsPurchaseRows) return [];
    const rows = runs ?? [];
    if (typeFilter === "all") return rows;
    return rows.filter((row) => displayTypeOf(row) === "GSTR-2B");
  }, [runs, showsPurchaseRows, typeFilter]);

  const showEmpty =
    !showSkeleton &&
    !runsError &&
    authToken &&
    showsPurchaseRows &&
    Array.isArray(runs) &&
    visibleRows.length === 0;

  const totalCount = showsPurchaseRows ? (runs?.length ?? 0) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
              {tReconciliations("title")}
            </h1>
            {!showSkeleton && authToken && !runsError && showsPurchaseRows && (
              <span className="rounded-full bg-[#F0F0F0] px-2.5 py-1 text-xs font-semibold text-gray-600">
                {totalCount}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-500">
            {tReconciliations("subtitle")}
          </p>
        </div>
      </div>

      <div
        className="flex flex-wrap gap-2"
        role="tablist"
        aria-label="Filter by reconciliation type"
      >
        {TYPE_FILTERS.map(({ id, label }) => {
          const active = typeFilter === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setTypeFilter(id)}
              className={`min-h-[36px] rounded-full px-4 text-sm font-medium transition-colors ${
                active
                  ? "bg-[var(--ink)] text-white"
                  : "bg-[#F0F0F0] text-gray-600 hover:bg-[#E8E8EA]"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {runsError && showsPurchaseRows && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load reconciliations.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--ink)] underline"
            onClick={() => void mutateRuns()}
          >
            Retry
          </button>
        </div>
      )}

      {!authToken && tokenState === false && (
        <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
          Sign in to load reconciliations.
        </div>
      )}

      {upcomingEmptyLabel ? (
        <div className="dashboard-card flex min-h-[320px] flex-col items-center justify-center px-6 py-16 text-center">
          <div className="mx-auto w-full max-w-[400px]">
            <EmptyStateIllustration className="mx-auto text-gray-300" />
            <h3 className="mt-4 text-lg font-semibold text-[var(--ink)]">
              {upcomingEmptyLabel}
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              This type will appear here once its reconciliation flow is available.
            </p>
          </div>
        </div>
      ) : showEmpty ? (
        <div className="dashboard-card flex min-h-[320px] flex-col items-center justify-center px-6 py-16 text-center">
          <div className="mx-auto w-full max-w-[400px]">
            <EmptyStateIllustration className="mx-auto text-gray-300" />
            <h3 className="mt-4 text-lg font-semibold text-[var(--ink)]">
              No reconciliations yet
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Start from a client profile.
            </p>
            <Link
              href="/clients"
              className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              Go to Clients
            </Link>
          </div>
        </div>
      ) : (
        <section className="dashboard-card p-6">
          {showSkeleton ? (
            <ReconciliationsSkeleton />
          ) : (
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-[860px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                      <th className="px-5 py-4">Client</th>
                      <th className="px-4 py-4">Status</th>
                      <th className="px-4 py-4">Matched Records</th>
                      <th className="px-4 py-4">Missed ITC</th>
                      <th className="px-4 py-4">Date</th>
                      <th className="px-5 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row) => {
                      const status = runListStatus(row.status);
                      const matched = matchedCountFromRow(row);
                      const itcRisk = itcAtRiskRupee(row);
                      const typeLabel = displayTypeOf(row);

                      return (
                        <tr
                          key={row.id}
                          className="border-b border-[#F0F0F0] transition-colors hover:bg-[#F7F7F8] last:border-b-0"
                        >
                          <td className="px-5 py-3.5">
                            <div className="font-medium text-[var(--ink)]">
                              {row.trade_name ?? "—"}
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-2">
                              <span className="inline-flex rounded-full bg-[#F0F0F0] px-2 py-0.5 text-[11px] font-semibold tracking-wide text-gray-600">
                                {typeLabel}
                              </span>
                              <span className="font-mono text-xs text-gray-400">
                                {row.client_gstin ?? "—"}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3.5">
                            <span
                              className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${status.className}`}
                            >
                              {status.label}
                            </span>
                          </td>
                          <td className="px-4 py-3.5 font-mono text-gray-500">
                            {matched != null ? matched.toLocaleString("en-IN") : "—"}
                          </td>
                          <td className="px-4 py-3.5 font-mono text-[var(--ink)]">
                            {itcRisk != null ? formatInrFull(itcRisk) : "—"}
                          </td>
                          <td className="px-4 py-3.5 text-gray-500">
                            {row.created_at ? formatRunDate(row.created_at) : "—"}
                          </td>
                          <td className="px-5 py-3.5 text-right">
                            <div className="inline-flex items-center justify-end gap-2">
                              <Link
                                href={`/reconcile/runs/${row.id}/results`}
                                className="inline-flex min-h-[36px] items-center justify-center rounded-full bg-[#F0F0F0] px-3.5 text-xs font-semibold text-[var(--ink)] transition-colors hover:bg-[#E8E8EA]"
                              >
                                View Results
                              </Link>
                              {typeLabel === "GSTR-2B" && (
                                <Link
                                  href={`/reconcile/runs/${row.id}/gstr3b`}
                                  className="inline-flex min-h-[36px] items-center justify-center rounded-full bg-[var(--ink)] px-3.5 text-xs font-semibold text-white transition-opacity hover:opacity-90 whitespace-nowrap"
                                >
                                  GSTR-3B Table 4 →
                                </Link>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
