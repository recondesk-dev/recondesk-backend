"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import {
  assignStaffToClients,
  bulkFinalizeCompleteRuns,
  bulkRetryFailedForClients,
  finalizeRun,
  mockFetchers,
  retryFailedRun,
  areAllSelectedComplete,
  areAllSelectedFailed,
} from "@/lib/mock-data";
import type { PortfolioFilters, PortfolioSortKey, SortDirection } from "@/lib/types";
import { StatCard } from "@/components/dashboard/StatCard";
import { FilterBar } from "@/components/dashboard/FilterBar";
import { ClientTable, RetryConfirmModal } from "@/components/dashboard/ClientTable";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { formatInrCompact, formatInrFull } from "@/lib/format";
import type { ClientPortfolioRow } from "@/lib/types";
import type { ComplianceRisk } from "@/lib/types";

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

async function invalidateDashboard() {
  await Promise.all([
    mutate((key) => Array.isArray(key) && key[0] === "/api/portfolio"),
    mutate("/api/dashboard/stats"),
    mutate("/api/dashboard/signals"),
    mutate("/api/dashboard/failures"),
    mutate("/api/clients"),
    mutate("/api/periods"),
  ]);
}

export default function PortfolioDashboardPage() {
  const router = useRouter();
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

  const portfolioQuery = useMemo(
    () => ({
      page,
      limit: PAGE_SIZE,
      filters: filtersWithSearch,
      sort,
    }),
    [page, filtersWithSearch, sort]
  );

  const {
    data: portfolio,
    error: portfolioError,
    isLoading: portfolioLoading,
    mutate: mutatePortfolio,
  } = useSWR(["/api/portfolio", portfolioQuery], ([, q]) => mockFetchers["/api/portfolio"](q));

  const { data: stats } = useSWR("/api/dashboard/stats", mockFetchers["/api/dashboard/stats"]);
  const { data: staff } = useSWR("/api/staff", mockFetchers["/api/staff"]);
  const { data: periods } = useSWR("/api/periods", mockFetchers["/api/periods"]);
  const { data: signals } = useSWR("/api/dashboard/signals", mockFetchers["/api/dashboard/signals"]);

  useEffect(() => {
    setPage(1);
  }, [filtersWithSearch, sort]);

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
    if (!retryRow?.latestRun) return;
    setRetryLoading(true);
    retryFailedRun(retryRow.latestRun.id);
    setRetryRow(null);
    await invalidateDashboard();
    setRetryLoading(false);
  };

  const onFinalizeConfirm = async (row: ClientPortfolioRow) => {
    if (!row.latestRun || row.latestRun.status !== "COMPLETE") return;
    finalizeRun(row.latestRun.id, "Priya Sharma");
    await invalidateDashboard();
  };

  const selectedList = useMemo(() => Array.from(selectedIds), [selectedIds]);
  const canBulkFinalize = areAllSelectedComplete(selectedList);
  const canBulkRetry = areAllSelectedFailed(selectedList);

  const onBulkAssign = async (staffId: string) => {
    assignStaffToClients(selectedList, staffId);
    setSelectedIds(new Set());
    await invalidateDashboard();
  };

  const onBulkFinalize = async () => {
    bulkFinalizeCompleteRuns(selectedList);
    setSelectedIds(new Set());
    await invalidateDashboard();
  };

  const onBulkRetry = async () => {
    bulkRetryFailedForClients(selectedList);
    setSelectedIds(new Set());
    await invalidateDashboard();
  };

  const totalClients = stats?.totalClients ?? 0;
  const isEmptyPortfolio = !portfolioLoading && totalClients === 0;

  const startHereRow = useMemo(() => {
    if (page !== 1 || portfolioLoading || !portfolio?.data?.length) return null;
    return portfolio.data.find((r) => r.latestRun?.status !== "FINALIZED") ?? null;
  }, [page, portfolio, portfolioLoading]);

  return (
    <div className="space-y-6">
      {signals && signals.failedClientCount > 0 && (
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
      {signals &&
        signals.failedClientCount === 0 &&
        signals.completeReadyCount > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <strong>{signals.completeReadyCount}</strong> reconciliation(s) are ready for your review.
          </div>
        )}
      {signals?.showAllFinalizedBanner && (
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
          value={stats ? String(stats.pendingThisMonth) : "—"}
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
          value={stats ? formatInrCompact(stats.totalItcProtected) : "—"}
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

      {portfolioError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load data.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--accent)] underline"
            onClick={() => void mutatePortfolio()}
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

      {!isEmptyPortfolio && staff && periods && (
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

      <RetryConfirmModal
        open={retryRow !== null}
        row={retryRow}
        onClose={() => setRetryRow(null)}
        onConfirm={() => void confirmRetry()}
        loading={retryLoading}
      />

      {selectedIds.size > 0 && staff && (
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
            {staff?.map((s) => (
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
