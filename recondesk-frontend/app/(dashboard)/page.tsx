"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";

import { FilterBar } from "@/components/dashboard/FilterBar";
import { ClientTable, RetryConfirmModal } from "@/components/dashboard/ClientTable";
import { StatCard } from "@/components/dashboard/StatCard";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { useToast } from "@/components/providers/ToastProvider";
import {
  authApi,
  clientsApi,
  isApiError,
  reconcileRunsApi,
  teamApi,
  type ClientGstin,
  type ReconcileRunListRow,
} from "@/lib/api";
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

  const { data: me, isLoading: meLoading } = useSWR(meKey, ([, , t]) => authApi.me(t), {
    revalidateOnFocus: false,
  });

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
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div className="h-24 animate-pulse rounded-xl bg-[#E5E7EB]" />
          <div className="h-24 animate-pulse rounded-xl bg-[#E5E7EB]" />
        </div>
        <div className="h-40 animate-pulse rounded-xl bg-[#E5E7EB]" />
        <div className="h-72 animate-pulse rounded-xl bg-[#E5E7EB]" />
      </div>
    );
  }

  if (tokenState === false) {
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-8 text-center text-sm text-[var(--text-secondary)]">
        Sign in required to view the dashboard.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {!portfolioLoading && signals.failedClientCount > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          <span>
            <strong>{signals.failedClientCount}</strong> client(s) have failed reconciliations.{" "}
            <button
              type="button"
              className="font-semibold text-[var(--accent)] underline"
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
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <strong>{signals.completeReadyCount}</strong> reconciliation(s) are ready for your review.
          </div>
        )}
      {!portfolioLoading && signals.showAllFinalizedBanner && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-900">
          All clients reconciled for this period 🎉
        </div>
      )}

      <p className="text-sm text-[var(--text-secondary)]">
        Where should you act right now? Open the highest-priority client and start or continue their
        reconciliation.
      </p>

      <div className="grid grid-cols-2 gap-4">
        <StatCard
          label="Needs Attention"
          value={
            portfolioLoading ? "—" : stats ? String(stats.pendingThisMonth) : "—"
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
            portfolioLoading ? "—" : stats ? formatInrCompact(stats.totalItcProtected) : "—"
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
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load data.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--accent)] underline"
            onClick={() => void invalidateDw()}
          >
            Retry
          </button>
        </div>
      )}

      {isEmptyPortfolio && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface)] py-16">
          <svg width="120" height="80" viewBox="0 0 120 80" className="text-[var(--accent-dim)]" aria-hidden>
            <rect x="10" y="20" width="100" height="50" rx="6" fill="currentColor" opacity="0.35" />
            <path d="M40 45h40M60 35v20" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" />
          </svg>
          <p className="mt-4 text-base font-medium text-[var(--text-primary)]">
            Add your first client to start reconciling
          </p>
          <Link
            href="/clients"
            className="mt-4 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white"
          >
            Add Client
          </Link>
        </div>
      )}

      {!isEmptyPortfolio && (
        <>
          {startHereRow && (
            <div>
              <p
                className="mb-2 text-[11px] font-semibold tracking-wide text-[var(--text-secondary)] [font-variant:small-caps]"
              >
                Start here
              </p>
              <div
                className={`flex flex-col gap-4 rounded-xl border-l-4 bg-[var(--surface)] p-5 shadow-md sm:flex-row sm:items-center sm:justify-between ${
                  startHereRow.latestRun?.status === "FAILED"
                    ? "border-l-[var(--danger)]"
                    : "border-l-[var(--accent)]"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p
                    className="truncate text-lg font-semibold text-[var(--text-primary)]"
                    style={{ fontSize: 18, fontWeight: 600 }}
                  >
                    {startHereRow.client.tradeName}
                  </p>
                  <p className="mt-1 font-mono text-sm text-[var(--text-primary)]">
                    {startHereRow.client.gstin}
                  </p>
                </div>
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2 text-sm text-[var(--text-primary)]">
                  {startHereRow.latestRun?.status === "FAILED" ? (
                    <>
                      <span>Failed — needs retry</span>
                      <span className="text-[var(--text-secondary)]">•</span>
                      <StatusBadge status="FAILED" />
                    </>
                  ) : !startHereRow.latestRun ? (
                    <span className="text-[var(--text-secondary)]">No reconciliations yet</span>
                  ) : (
                    <>
                      {startHereRow.latestRun.missedItc != null && (
                        <>
                          <span>{formatMissedSnippet(startHereRow.latestRun.missedItc)}</span>
                          <span className="text-[var(--text-secondary)]">•</span>
                        </>
                      )}
                      <span>{complianceRiskWords(startHereRow.latestRun.complianceRisk)}</span>
                      <span className="text-[var(--text-secondary)]">•</span>
                      <StatusBadge status={startHereRow.latestRun.status} />
                    </>
                  )}
                </div>
                <div className="flex shrink-0 justify-end sm:pl-4">
                  {startHereRow.latestRun?.status === "FAILED" && (
                    <button
                      type="button"
                      className="rounded-lg bg-[var(--danger)] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:opacity-95"
                      onClick={() => setRetryRow(startHereRow)}
                    >
                      Retry Now
                    </button>
                  )}
                  {startHereRow.latestRun?.status === "COMPLETE" && (
                    <button
                      type="button"
                      className="rounded-lg bg-[var(--accent)] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:opacity-95"
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
                      className="cursor-not-allowed rounded-lg bg-[#E5E7EB] px-5 py-2.5 text-sm font-semibold text-[var(--text-secondary)]"
                    >
                      In Progress
                    </button>
                  )}
                  {!startHereRow.latestRun && (
                    <button
                      type="button"
                      className="rounded-lg bg-[var(--accent)] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:opacity-95"
                      onClick={() => router.push(`/clients/${startHereRow.client.id}`)}
                    >
                      Start
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {directoryLoading ? (
            <div className="h-[72px] animate-pulse rounded-xl bg-[#E5E7EB]" aria-hidden />
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
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-8 text-center text-sm text-[var(--text-secondary)]">
                No clients match your filters.{" "}
                <button
                  type="button"
                  className="font-semibold text-[var(--accent)] underline"
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
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
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
        <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-5 py-3 shadow-lg">
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {selectedIds.size} selected
          </span>
          <select
            className="rounded-lg border border-[var(--border)] px-2 py-1.5 text-sm"
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
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
            onClick={() => void onBulkFinalize()}
          >
            Mark Selected as Finalized
          </button>
          <button
            type="button"
            disabled={!canBulkRetry}
            title={!canBulkRetry ? "Select only FAILED rows" : undefined}
            className="rounded-lg border border-[var(--danger)] px-3 py-1.5 text-sm font-semibold text-[var(--danger)] disabled:opacity-40"
            onClick={() => void onBulkRetry()}
          >
            Retry Selected
          </button>
          <button
            type="button"
            className="text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
