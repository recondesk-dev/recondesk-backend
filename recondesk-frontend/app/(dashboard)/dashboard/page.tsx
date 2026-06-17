"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";

import dynamic from "next/dynamic";
import { StatCard } from "@/components/dashboard/StatCard";
import { StatusBadge } from "@/components/dashboard/StatusBadge";

const FilterBar = dynamic(
  () => import("@/components/dashboard/FilterBar").then((mod) => mod.FilterBar),
  { ssr: false, loading: () => <div className="h-[72px] animate-pulse rounded-2xl bg-gray-100" /> }
);

const ClientTable = dynamic(
  () => import("@/components/dashboard/ClientTable").then((mod) => mod.ClientTable),
  { ssr: false }
);

const RetryConfirmModal = dynamic(
  () => import("@/components/dashboard/ClientTable").then((mod) => mod.RetryConfirmModal),
  { ssr: false }
);
import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import { useToast } from "@/components/providers/ToastProvider";
import {
  clientsApi,
  isApiError,
  reconcileRunsApi,
  teamApi,
  type ClientGstin,
  type ReconcileRunListRow,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
} from "@/lib/auth-profile";
import {
  DW,
  buildPortfolioRows,
  buildStaffRoster,
  computeDashboardSignals,
  computeDashboardStats,
  derivePeriodLabels,
  paginatePortfolio,
  type PortfolioQuery,
} from "@/lib/dashboard-portfolio";
import { formatInrCompact, formatInrFull } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import type {
  ClientPortfolioRow,
  ComplianceRisk,
  PortfolioFilters,
  PortfolioSortKey,
  SortDirection,
} from "@/lib/types";

const PAGE_SIZE = 20;

const DEFAULT_FILTERS: PortfolioFilters = {
  status: "ALL",
  assignedStaffId: "ALL",
  period: "ALL",
  search: "",
};

function formatMissedSnippet(n: number): string {
  if (n >= 100000) return `${formatInrCompact(n)} missed ITC`;
  return `${formatInrFull(n)} missed ITC`;
}

function complianceRiskWords(r: ComplianceRisk | null | undefined): string {
  const level = r ?? "LOW";
  const map: Record<ComplianceRisk, string> = {
    LOW: "Low risk",
    MEDIUM: "Medium risk",
    HIGH: "High risk",
    CRITICAL: "Critical risk",
  };
  return map[level];
}

function useDebounced<T>(value: T, ms: number): T {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return d;
}

async function invalidateDw(): Promise<void> {
  await mutate((key: unknown) => Array.isArray(key) && key[0] === DW);
}

export default function PortfolioDashboardPage() {
  const router = useRouter();
  const toast = useToast();
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const [filters, setFilters] = useState<PortfolioFilters>(DEFAULT_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const debouncedSearch = useDebounced(searchInput, 200);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: PortfolioSortKey; dir: SortDirection }>({
    key: "priority",
    dir: "desc",
  });
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [retryRow, setRetryRow] = useState<ClientPortfolioRow | null>(null);
  const [retryLoading, setRetryLoading] = useState(false);

  const filtersWithSearch = useMemo(
    () => ({ ...filters, search: debouncedSearch }),
    [filters, debouncedSearch]
  );

  const portfolioQuery = useMemo<PortfolioQuery>(
    () => ({
      page,
      limit: PAGE_SIZE,
      filters: filtersWithSearch,
      sort,
    }),
    [page, filtersWithSearch, sort]
  );

  const clientsKey = authToken ? ([DW, "clients", authToken] as const) : null;
  const runsKey = authToken ? ([DW, "runs", authToken] as const) : null;
  const teamKey = authToken ? ([DW, "team", authToken] as const) : null;
  const meKey = authToken ? ([DW, "me", authToken] as const) : null;

  const {
    data: clients,
    error: clientsError,
    isLoading: clientsLoading,
  } = useSWR(
    clientsKey,
    ([, , t]) => clientsApi.list(t),
    { revalidateOnFocus: false }
  );

  const {
    data: runs,
    error: runsError,
    isLoading: runsLoading,
  } = useSWR(
    runsKey,
    ([, , t]) =>
      reconcileRunsApi.list(t, {
        limit: 500,
      }),
    { revalidateOnFocus: false }
  );

  const { data: teamMembers, isLoading: teamLoading } = useSWR(
    teamKey,
    ([, , t]) => teamApi.list(t),
    { revalidateOnFocus: false }
  );

  const { data: me, isLoading: meLoading } = useSWR(
    meKey,
    ([, , t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  useEffect(() => {
    setPage(1);
  }, [filtersWithSearch, sort]);

  const staff = useMemo(
    () => buildStaffRoster(teamMembers ?? [], me ?? null),
    [teamMembers, me]
  );

  const periods = useMemo(() => derivePeriodLabels(runs ?? []), [runs]);

  const baseRows = useMemo(
    () =>
      buildPortfolioRows(
        (clients ?? []) as ClientGstin[],
        (runs ?? []) as ReconcileRunListRow[],
        staff
      ),
    [clients, runs, staff]
  );

  const portfolio = useMemo(
    () => paginatePortfolio(baseRows, portfolioQuery),
    [baseRows, portfolioQuery]
  );

  const stats = useMemo(
    () =>
      computeDashboardStats(
        clients?.length ?? 0,
        (runs ?? []) as ReconcileRunListRow[],
        staff.length
      ),
    [clients?.length, runs, staff.length]
  );

  const signals = useMemo(() => computeDashboardSignals(baseRows), [baseRows]);

  const rowByClientId = useMemo(() => {
    const m = new Map<string, ClientPortfolioRow>();
    for (const r of baseRows) {
      m.set(r.client.id, r);
    }
    return m;
  }, [baseRows]);

  const portfolioLoading = clientsLoading || runsLoading;
  const directoryLoading = teamLoading || meLoading;
  const loadError = clientsError || runsError;

  const showReset = useMemo(() => {
    return (
      filters.status !== DEFAULT_FILTERS.status ||
      filters.assignedStaffId !== DEFAULT_FILTERS.assignedStaffId ||
      filters.period !== DEFAULT_FILTERS.period ||
      debouncedSearch.length > 0
    );
  }, [filters, debouncedSearch]);

  const onResetFilters = () => {
    setFilters(DEFAULT_FILTERS);
    setSearchInput("");
  };

  const onSortToggle = (key: PortfolioSortKey) => {
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }
    );
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllOnPage = (ids: string[], checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) ids.forEach((id) => next.add(id));
      else ids.forEach((id) => next.delete(id));
      return next;
    });
  };

  const onRetryConfirm = (row: ClientPortfolioRow) => setRetryRow(row);

  const confirmRetry = async () => {
    if (!retryRow?.latestRun || !authToken) return;
    setRetryLoading(true);
    try {
      await reconcileRunsApi.retryFailed(authToken, retryRow.latestRun.id);
      toast("Retry queued", "success");
      setRetryRow(null);
      await invalidateDw();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Retry failed", "error");
    } finally {
      setRetryLoading(false);
    }
  };

  const onFinalizeConfirm = async (row: ClientPortfolioRow) => {
    if (!authToken || !row.latestRun || row.latestRun.status !== "COMPLETE") return;
    try {
      await reconcileRunsApi.finalizeRun(authToken, row.latestRun.id);
      toast("Run finalized", "success");
      await invalidateDw();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Finalization failed", "error");
    }
  };

  const selectedList = useMemo(() => Array.from(selectedIds), [selectedIds]);
  const canBulkFinalize =
    selectedList.length > 0 &&
    selectedList.every((id) => rowByClientId.get(id)?.latestRun?.status === "COMPLETE");
  const canBulkRetry =
    selectedList.length > 0 &&
    selectedList.every((id) => rowByClientId.get(id)?.latestRun?.status === "FAILED");

  const onBulkAssign = async (staffId: string) => {
    if (!authToken) return;
    try {
      await Promise.all(
        selectedList.map((cid) => clientsApi.assign(authToken, cid, staffId))
      );
      toast("Assignments updated", "success");
      setSelectedIds(new Set());
      await invalidateDw();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Assignment failed", "error");
    }
  };

  const onBulkFinalize = async () => {
    if (!authToken) return;
    try {
      for (const cid of selectedList) {
        const run = rowByClientId.get(cid)?.latestRun;
        if (run?.status === "COMPLETE") {
          await reconcileRunsApi.finalizeRun(authToken, run.id);
        }
      }
      toast("Selected runs finalized", "success");
      setSelectedIds(new Set());
      await invalidateDw();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Bulk finalize failed", "error");
    }
  };

  const onBulkRetry = async () => {
    if (!authToken) return;
    try {
      for (const cid of selectedList) {
        const run = rowByClientId.get(cid)?.latestRun;
        if (run?.status === "FAILED") {
          await reconcileRunsApi.retryFailed(authToken, run.id);
        }
      }
      toast("Retry queued for selected runs", "success");
      setSelectedIds(new Set());
      await invalidateDw();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Bulk retry failed", "error");
    }
  };

  const totalClients = stats.totalClients;
  const isEmptyPortfolio = !portfolioLoading && totalClients === 0;

  const startHereRow = useMemo(() => {
    if (page !== 1 || portfolioLoading || !portfolio.data.length) return null;
    return portfolio.data.find((r) => r.latestRun?.status !== "FINALIZED") ?? null;
  }, [page, portfolio, portfolioLoading]);

  if (tokenState === null) {
    return (
      <div className="space-y-8">
        <div className="grid grid-cols-2 gap-6">
          <div className="h-28 animate-pulse rounded-2xl bg-gray-100" />
          <div className="h-28 animate-pulse rounded-2xl bg-gray-100" />
        </div>
        <div className="h-40 animate-pulse rounded-2xl bg-gray-100" />
        <div className="h-72 animate-pulse rounded-2xl bg-gray-100" />
      </div>
    );
  }

  if (tokenState === false) {
    return (
      <div className="rounded-2xl bg-white px-6 py-10 text-center text-sm font-medium text-gray-400 shadow-sm">
        Sign in required to view the dashboard.
      </div>
    );
  }

  if (isEmptyPortfolio) {
    return (
      <div className="flex min-h-[calc(100vh-12rem)] flex-col items-center justify-center px-4">
        <div className="mx-auto w-full max-w-[400px] text-center">
          <EmptyStateIllustration className="mx-auto text-gray-300" />
          <h2 className="mt-6 text-xl font-semibold text-gray-900">No clients yet</h2>
          <p className="mt-2 text-sm text-gray-500">
            Add your first client to start reconciling their GSTR-2B
          </p>
          <Link
            href="/clients?add=1"
            className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-full bg-brand px-6 text-sm font-semibold text-white shadow-sm hover:bg-brand-hover transition-opacity"
          >
            Add First Client
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {!portfolioLoading && signals.failedClientCount > 0 && (
        <div className="flex items-center justify-between rounded-2xl bg-red-50 px-5 py-4 text-sm text-red-900">
          <span>
            <strong>{signals.failedClientCount}</strong> client(s) have failed reconciliations.{" "}
            <button
              type="button"
              className="font-semibold text-brand underline"
              onClick={() => {
                setFilters((f) => ({ ...f, status: "FAILED" }));
                setSearchInput("");
              }}
            >
              Retry now →
            </button>
          </span>
        </div>
      )}
      {!portfolioLoading &&
        signals.failedClientCount === 0 &&
        signals.completeReadyCount > 0 && (
          <div className="rounded-2xl bg-amber-50 px-5 py-4 text-sm text-amber-950">
            <strong>{signals.completeReadyCount}</strong> reconciliation(s) are ready for your review.
          </div>
        )}
      {!portfolioLoading && signals.showAllFinalizedBanner && (
        <div className="rounded-2xl bg-emerald-50 px-5 py-4 text-sm font-medium text-emerald-900">
          All clients reconciled for this period 🎉
        </div>
      )}

      <p className="text-sm text-gray-500">
        Where should you act right now? Open the highest-priority client and start or continue their
        reconciliation.
      </p>

      <div className="grid grid-cols-2 gap-6">
        <StatCard
          label="Needs Attention"
          value={
            portfolioLoading ? (
              <span className="inline-block h-8 w-16 animate-pulse rounded bg-gray-100" />
            ) : stats ? (
              String(stats.pendingThisMonth)
            ) : (
              "—"
            )
          }
          icon={
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M12 8v4l3 3M12 22a10 10 0 110-20 10 10 0 010 20z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          }
        />
        <StatCard
          label="Total ITC Protected"
          value={
            portfolioLoading ? (
              <span className="inline-block h-8 w-28 animate-pulse rounded bg-gray-100" />
            ) : stats ? (
              formatInrCompact(stats.totalItcProtected)
            ) : (
              "—"
            )
          }
          icon={
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M12 2v20M7 7h10M7 12h6M7 17h8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          }
        />
      </div>

      {loadError && (
        <div className="rounded-2xl bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load data.{" "}
          <button
            type="button"
            className="font-semibold text-brand underline"
            onClick={() => void invalidateDw()}
          >
            Retry
          </button>
        </div>
      )}

      {!isEmptyPortfolio && (
        <>
          {portfolioLoading ? (
            <div>
              <div className="mb-3 flex items-center gap-2 animate-pulse">
                <span className="inline-block h-2 w-2 rounded-full bg-gray-200" />
                <p className="text-xs font-semibold uppercase tracking-widest text-gray-300">
                  Start here
                </p>
              </div>
              <div className="flex flex-col gap-4 rounded-2xl bg-white p-6 shadow-md sm:flex-row sm:items-center sm:justify-between animate-pulse">
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="h-5 w-48 bg-gray-100 rounded" />
                  <div className="h-4 w-36 bg-gray-100 rounded" />
                </div>
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <div className="h-4 w-28 bg-gray-100 rounded" />
                  <div className="h-4 w-4 bg-gray-100 rounded-full" />
                  <div className="h-6 w-20 bg-gray-100 rounded-full" />
                </div>
                <div className="flex shrink-0 justify-end sm:pl-4">
                  <div className="h-10 w-28 bg-gray-100 rounded-full" />
                </div>
              </div>
            </div>
          ) : startHereRow ? (
            <div>
              <div className="mb-3 flex items-center gap-2">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    startHereRow.latestRun?.status === "FAILED"
                      ? "bg-[var(--danger)]"
                      : "bg-brand"
                  }`}
                />
                <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">
                  Start here
                </p>
              </div>
              <div className="flex flex-col gap-4 rounded-2xl bg-white p-6 shadow-md sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 flex-1">
                  <p
                    className="truncate text-lg font-semibold text-gray-900"
                    style={{ fontSize: 18, fontWeight: 600 }}
                  >
                    {startHereRow.client.tradeName}
                  </p>
                  <p className="mt-1 font-mono text-sm text-gray-500">
                    {startHereRow.client.gstin}
                  </p>
                </div>
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2 text-sm text-gray-700">
                  {startHereRow.latestRun?.status === "FAILED" ? (
                    <>
                      <span>Failed — needs retry</span>
                      <span className="text-gray-300">•</span>
                      <StatusBadge status="FAILED" />
                    </>
                  ) : !startHereRow.latestRun ? (
                    <span className="text-gray-400">No reconciliations yet</span>
                  ) : (
                    <>
                      {startHereRow.latestRun.missedItc != null && (
                        <>
                          <span>{formatMissedSnippet(startHereRow.latestRun.missedItc)}</span>
                          <span className="text-gray-300">•</span>
                        </>
                      )}
                      <span>{complianceRiskWords(startHereRow.latestRun.complianceRisk)}</span>
                      <span className="text-gray-300">•</span>
                      <StatusBadge status={startHereRow.latestRun.status} />
                    </>
                  )}
                </div>
                <div className="flex shrink-0 justify-end sm:pl-4">
                  {startHereRow.latestRun?.status === "FAILED" && (
                    <button
                      type="button"
                      className="rounded-full bg-[var(--danger)] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity"
                      onClick={() => setRetryRow(startHereRow)}
                    >
                      Retry Now
                    </button>
                  )}
                  {startHereRow.latestRun?.status === "COMPLETE" && (
                    <button
                      type="button"
                      className="rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-hover transition-opacity"
                      onClick={() => router.push(`/clients/${startHereRow.client.id}`)}
                    >
                      Review Now
                    </button>
                  )}
                  {(startHereRow.latestRun?.status === "PENDING" ||
                    startHereRow.latestRun?.status === "IMPORTING" ||
                    startHereRow.latestRun?.status === "MATCHING") && (
                    <button
                      type="button"
                      disabled
                      className="cursor-not-allowed rounded-full bg-gray-100 px-5 py-2.5 text-sm font-semibold text-gray-400"
                    >
                      In Progress
                    </button>
                  )}
                  {!startHereRow.latestRun && (
                    <button
                      type="button"
                      className="rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-hover transition-opacity"
                      onClick={() => router.push(`/clients/${startHereRow.client.id}`)}
                    >
                      Start
                    </button>
                  )}
                </div>
              </div>
            </div>
          ) : null}

          {directoryLoading ? (
            <div className="h-[72px] animate-pulse rounded-2xl bg-gray-100" aria-hidden />
          ) : (
            <FilterBar
              filters={filters}
              onChange={setFilters}
              staff={staff}
              periods={periods}
              searchInput={searchInput}
              onSearchInputChange={setSearchInput}
              showReset={showReset}
              onReset={onResetFilters}
            />
          )}

          {!portfolioLoading &&
            portfolio &&
            portfolio.total === 0 &&
            showReset && (
              <div className="rounded-2xl bg-white px-6 py-10 text-center text-sm text-gray-400 shadow-sm">
                No clients match your filters.{" "}
                <button
                  type="button"
                  className="font-semibold text-brand underline"
                  onClick={onResetFilters}
                >
                  Reset Filters
                </button>
              </div>
            )}

          {(portfolioLoading || (portfolio && portfolio.total > 0)) && (
            <ClientTable
              rows={portfolio?.data ?? []}
              loading={portfolioLoading}
              page={page}
              pageSize={PAGE_SIZE}
              total={portfolio?.total ?? 0}
              onPageChange={setPage}
              sort={sort}
              onSortToggle={onSortToggle}
              selectedIds={selectedIds}
              onToggleSelect={toggleSelect}
              onToggleAllOnPage={toggleAllOnPage}
              onRetryConfirm={onRetryConfirm}
              onFinalizeConfirm={(row) => void onFinalizeConfirm(row)}
            />
          )}
        </>
      )}

      {!isEmptyPortfolio && !directoryLoading && staff.length === 0 && (
        <div className="rounded-2xl bg-amber-50 px-5 py-4 text-sm text-amber-950">
          Team directory is empty — add staff in Settings → Team before using assign filters.
        </div>
      )}

      <RetryConfirmModal
        open={retryRow !== null}
        row={retryRow}
        onClose={() => setRetryRow(null)}
        onConfirm={() => void confirmRetry()}
        loading={retryLoading}
      />

      {selectedIds.size > 0 && staff.length > 0 && (
        <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 flex-wrap items-center gap-3 rounded-2xl border border-white/20 bg-white/80 px-5 py-3.5 shadow-xl backdrop-blur-xl">
          <span className="text-sm font-semibold text-gray-800">
            {selectedIds.size} selected
          </span>
          <select
            className="rounded-xl border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 focus:outline-none"
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) void onBulkAssign(e.target.value);
            }}
          >
            <option value="" disabled>
              Assign to…
            </option>
            {staff.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!canBulkFinalize}
            title={!canBulkFinalize ? "Select only COMPLETE rows" : undefined}
            className="rounded-full bg-brand px-5 py-2 text-sm font-semibold text-white disabled:opacity-40 transition-opacity hover:bg-brand-hover"
            onClick={() => void onBulkFinalize()}
          >
            Mark Selected as Finalized
          </button>
          <button
            type="button"
            disabled={!canBulkRetry}
            title={!canBulkRetry ? "Select only FAILED rows" : undefined}
            className="rounded-full border border-[var(--danger)] px-5 py-2 text-sm font-semibold text-[var(--danger)] disabled:opacity-40 transition-opacity hover:bg-red-50"
            onClick={() => void onBulkRetry()}
          >
            Retry Selected
          </button>
          <button
            type="button"
            className="text-sm font-medium text-gray-400 hover:text-gray-700 transition-colors"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
