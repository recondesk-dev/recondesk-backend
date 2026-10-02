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
  { ssr: false, loading: () => <div className="h-11 animate-pulse rounded-full bg-gray-100" /> }
);

const ClientTable = dynamic(
  () => import("@/components/dashboard/ClientTable").then((mod) => mod.ClientTable),
  { ssr: false }
);

const RetryConfirmModal = dynamic(
  () => import("@/components/dashboard/ClientTable").then((mod) => mod.RetryConfirmModal),
  { ssr: false }
);

const ReturnPeriodBoard = dynamic(
  () =>
    import("@/components/dashboard/ReturnPeriodBoard").then(
      (mod) => mod.ReturnPeriodBoard
    ),
  { ssr: false, loading: () => <div className="h-[340px] animate-pulse rounded-[1.5rem] bg-gray-100" /> }
);

import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import { useToast } from "@/components/providers/ToastProvider";
import {
  clientsApi,
  dashboardApi,
  isApiError,
  reconcileRunsApi,
  teamApi,
  type ClientGstin,
  type DashboardAttentionItem,
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
  ReconciliationStatus,
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

function complianceRiskWords(r: ComplianceRisk | string | null | undefined): string {
  const level = (r ?? "LOW") as ComplianceRisk;
  const map: Record<ComplianceRisk, string> = {
    LOW: "Low risk",
    MEDIUM: "Medium risk",
    HIGH: "High risk",
    CRITICAL: "Critical risk",
  };
  return map[level] ?? "Low risk";
}

const UI_STATUSES = new Set<string>([
  "PENDING",
  "IMPORTING",
  "MATCHING",
  "COMPLETE",
  "FINALIZED",
  "FAILED",
]);

function asUiStatus(raw: string | null | undefined): ReconciliationStatus | null {
  if (!raw) return null;
  const u = raw.trim().toUpperCase();
  return UI_STATUSES.has(u) ? (u as ReconciliationStatus) : null;
}

/** Minimal portfolio row so Needs Attention can open the retry modal. */
function attentionToPortfolioRow(item: DashboardAttentionItem): ClientPortfolioRow {
  const status = asUiStatus(item.status);
  return {
    client: {
      id: item.client_id,
      tradeName: item.trade_name,
      gstin: item.gstin,
      registrationType: "Regular",
      assignedStaffId: "",
      createdAt: "",
    },
    latestRun: item.run_id
      ? {
          id: item.run_id,
          clientId: item.client_id,
          period: item.period || "",
          runNumber: 1,
          status: status ?? "FAILED",
          matchRate: null,
          itcClaimed: null,
          missedItc: item.missed_itc,
          complianceRisk: (item.compliance_risk as ComplianceRisk | null) ?? null,
          errorMessage: null,
          finalizedBy: null,
          finalizedAt: null,
          createdAt: "",
          updatedAt: "",
        }
      : null,
    priorityScore: item.priority_score,
    assignedStaff: {
      id: "unknown",
      name: "Unassigned",
      email: "",
      role: "STAFF",
      avatarInitials: "?",
    },
  };
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

function IconUsers() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M17 20v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 20v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconAlert() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconShield() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6l7-3z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconReview() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconFail() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.5" />
      <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IconTeam() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 10h8M8 14h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
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
  const [density, setDensity] = useState<"comfortable" | "compact">("comfortable");

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
  const summaryKey = authToken ? ([DW, "summary", authToken] as const) : null;

  const {
    data: summary,
    error: summaryError,
    isLoading: summaryLoading,
  } = useSWR(
    summaryKey,
    ([, , t]) => dashboardApi.summary(t),
    { revalidateOnFocus: false }
  );

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
        light: true,
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

  const statsLoading = summaryLoading;
  const portfolioLoading = clientsLoading || runsLoading;
  const directoryLoading = teamLoading || meLoading;
  const loadError = summaryError || clientsError || runsError;

  const totalClients = summary?.total_clients ?? clients?.length ?? 0;
  const pendingThisMonth = summary?.pending_this_month ?? 0;
  const readyForReview = summary?.ready_for_review ?? 0;
  const failedClientCount = summary?.failed_client_count ?? 0;
  const showAllFinalizedBanner = summary?.show_all_finalized_banner ?? false;
  const totalItcProtected = summary?.total_itc_protected ?? 0;
  const itcProtectedHasData = summary?.itc_protected_has_data ?? false;
  const itcAtRiskTotal = summary?.itc_at_risk ?? 0;
  const teamMembersCount = summary?.team_members ?? staff.length;
  const attentionItems = summary?.attention ?? [];

  const rowByClientId = useMemo(() => {
    const m = new Map<string, ClientPortfolioRow>();
    for (const r of baseRows) {
      m.set(r.client.id, r);
    }
    return m;
  }, [baseRows]);

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
      toast("Reconciliation finalized", "success");
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
      toast("Selected reconciliations finalized", "success");
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
      toast("Retry queued for selected reconciliations", "success");
      setSelectedIds(new Set());
      await invalidateDw();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Bulk retry failed", "error");
    }
  };

  const isEmptyPortfolio = !statsLoading && !portfolioLoading && totalClients === 0;

  if (tokenState === null) {
    return (
      <div className="space-y-6">
        <div className="rd-stat-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-[148px] animate-pulse rounded-[1.5rem] bg-white/70" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-[1.4fr_0.8fr]">
          <div className="h-[340px] animate-pulse rounded-[1.5rem] bg-white/70" />
          <div className="h-[340px] animate-pulse rounded-[1.5rem] bg-white/70" />
        </div>
        <div className="h-72 animate-pulse rounded-[1.5rem] bg-white/70" />
      </div>
    );
  }

  if (tokenState === false) {
    return (
      <div className="dashboard-card px-6 py-10 text-center text-sm font-medium text-gray-400">
        Sign in required to view the dashboard.
      </div>
    );
  }

  if (isEmptyPortfolio) {
    return (
      <div className="flex min-h-[calc(100vh-12rem)] flex-col items-center justify-center px-4">
        <div className="dashboard-card mx-auto w-full max-w-[420px] px-8 py-12 text-center">
          <EmptyStateIllustration className="mx-auto text-gray-300" />
          <h2 className="mt-6 text-xl font-semibold text-[var(--ink)]">No clients yet</h2>
          <p className="mt-2 text-sm text-gray-500">
            Add your first client to start reconciling their GSTR-2B
          </p>
          <Link
            href="/clients?add=1"
            className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
          >
            Add First Client
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="rd-dashboard-overview space-y-7">
      <div className="rd-overview-heading">
        <div><span className="rd-eyebrow">YOUR WORKSPACE</span><h1>Portfolio overview</h1><p>Reconciliation, review, and your next action — in one place.</p></div>
        <Link href="/clients?add=1" className="btn-primary inline-flex items-center justify-center gap-2 px-5 text-sm font-semibold text-white"><span aria-hidden="true">+</span> Add client</Link>
      </div>
      {!statsLoading && failedClientCount > 0 && (
        <div className="flex items-center justify-between rounded-[1.25rem] bg-red-50/90 px-5 py-4 text-sm text-red-900">
          <span>
            <strong>{failedClientCount}</strong> client(s) have failed reconciliations.{" "}
            <button
              type="button"
              className="font-semibold text-[var(--ink)] underline decoration-black/30 underline-offset-2"
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
      {!statsLoading && failedClientCount === 0 && readyForReview > 0 && (
          <div className="rounded-[1.25rem] bg-white px-5 py-4 text-sm text-gray-700 shadow-[var(--shadow-soft)]">
            <strong className="font-semibold text-[var(--ink)]">
              {readyForReview}
            </strong>{" "}
            {readyForReview === 1
              ? "reconciliation is ready for your review."
              : "reconciliations are ready for your review."}
          </div>
        )}
      {!statsLoading && showAllFinalizedBanner && (
        <div className="rounded-[1.25rem] bg-[var(--ink)] px-5 py-4 text-sm font-medium text-white">
          All clients reconciled for this period
        </div>
      )}

      <section>
        <div className="mb-4">
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            Quick Stats
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Your portfolio snapshot — act on what needs attention first.
          </p>
        </div>
        <div className="rd-stat-grid">
          <StatCard
            label="Total Clients"
            hint="Firm portfolio — Click to show all"
            icon={<IconUsers />}
            onClick={() => setFilters((f) => ({ ...f, status: "ALL" }))}
            isActive={filters.status === "ALL" && !showReset}
            value={
              statsLoading ? (
                <span className="inline-block h-8 w-14 animate-pulse rounded bg-gray-100" />
              ) : (
                String(totalClients)
              )
            }
            subtitle={`${teamMembersCount} team member${teamMembersCount === 1 ? "" : "s"}`}
          />
          <StatCard
            label="Needs Attention"
            hint="Pending reconciliations — Click to filter"
            icon={<IconAlert />}
            empty={!statsLoading && pendingThisMonth === 0}
            emptyIcon="check"
            emptyCaption="All caught up"
            tone={!statsLoading && pendingThisMonth > 0 ? "emphasis" : "default"}
            trend={!statsLoading && pendingThisMonth > 0 ? "up" : "none"}
            onClick={() =>
              setFilters((f) => ({
                ...f,
                status: f.status === "PENDING" ? "ALL" : "PENDING",
              }))
            }
            isActive={filters.status === "PENDING"}
            value={
              statsLoading ? (
                <span className="inline-block h-8 w-12 animate-pulse rounded bg-white/20" />
              ) : (
                String(pendingThisMonth)
              )
            }
            subtitle="Pending this month"
          />
          <StatCard
            label="Ready for Review"
            hint="Matching complete — Click to filter"
            icon={<IconReview />}
            onClick={() =>
              setFilters((f) => ({
                ...f,
                status: f.status === "COMPLETE" ? "ALL" : "COMPLETE",
              }))
            }
            isActive={filters.status === "COMPLETE"}
            badge={
              !statsLoading && readyForReview > 0 ? (
                <span className="rounded-full bg-emerald-100 text-emerald-800 px-2 py-0.5 text-[10px] font-semibold">
                  Action
                </span>
              ) : undefined
            }
            value={
              statsLoading ? (
                <span className="inline-block h-8 w-12 animate-pulse rounded bg-gray-100" />
              ) : (
                String(readyForReview)
              )
            }
            subtitle="Awaiting CA sign-off"
          />
          <StatCard
            label="ITC Protected"
            hint="Matched ITC from finalized reconciliations"
            icon={<IconShield />}
            empty={!statsLoading && !itcProtectedHasData}
            emptyCaption="No data yet"
            value={
              statsLoading ? (
                <span className="inline-block h-8 w-20 animate-pulse rounded bg-gray-100" />
              ) : (
                formatInrCompact(totalItcProtected)
              )
            }
            fullValue={formatInrFull(totalItcProtected)}
            subtitle="Finalized & audit-ready"
          />
          <StatCard
            label="Missed ITC at Risk"
            hint="Unclaimed ITC — Click to sort table by missed ITC"
            icon={<IconFail />}
            onClick={() => setSort({ key: "missedItc", dir: "desc" })}
            isActive={sort.key === "missedItc"}
            value={
              statsLoading ? (
                <span className="inline-block h-8 w-20 animate-pulse rounded bg-gray-100" />
              ) : (
                formatInrCompact(itcAtRiskTotal)
              )
            }
            fullValue={formatInrFull(itcAtRiskTotal)}
            subtitle="Sort by highest stakes"
          />
          <StatCard
            label="Failed Runs"
            hint="Reconciliation errors — Click to filter"
            icon={<IconFail />}
            empty={!statsLoading && failedClientCount === 0}
            emptyIcon="check"
            emptyCaption="None failed"
            onClick={() =>
              setFilters((f) => ({
                ...f,
                status: f.status === "FAILED" ? "ALL" : "FAILED",
              }))
            }
            isActive={filters.status === "FAILED"}
            badge={
              !statsLoading && failedClientCount > 0 ? (
                <span className="rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-[10px] font-semibold">
                  Fix
                </span>
              ) : undefined
            }
            value={
              statsLoading ? (
                <span className="inline-block h-8 w-10 animate-pulse rounded bg-gray-100" />
              ) : (
                String(failedClientCount)
              )
            }
            subtitle={failedClientCount > 0 ? "Requires retry" : "All engines healthy"}
          />
        </div>
      </section>

      {loadError && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load data.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--ink)] underline"
            onClick={() => void invalidateDw()}
          >
            Retry
          </button>
        </div>
      )}

      <section className="rd-priority-grid">
        <div>
          <ReturnPeriodBoard
            runs={(runs ?? []) as ReconcileRunListRow[]}
            loading={portfolioLoading}
            selectedPeriod={filters.period}
            onSelectPeriod={(p) => setFilters((f) => ({ ...f, period: p }))}
          />
        </div>

        <div className="rd-attention-panel dashboard-card flex flex-col p-6">
          <div className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
                Needs attention
              </h2>
              <p className="mt-1 text-sm text-gray-500">Priority clients to act on next</p>
            </div>
            <Link
              href="/clients"
              className="rounded-full bg-[#F5F5F6] px-3 py-1.5 text-xs font-semibold text-gray-600 transition-colors hover:bg-gray-200/80"
            >
              View all
            </Link>
          </div>

          {statsLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-2xl bg-gray-100" />
              ))}
            </div>
          ) : attentionItems.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center rounded-2xl bg-[#F7F7F8] px-4 py-10 text-center">
              <p className="text-sm font-medium text-gray-700">Nothing waiting</p>
              <p className="mt-1 text-xs text-gray-400">Your portfolio is clear for now</p>
            </div>
          ) : (
            <ul className="flex flex-1 flex-col gap-2.5">
              {attentionItems.map((item) => {
                const status = asUiStatus(item.status);
                return (
                  <li
                    key={item.client_id}
                    className="flex items-center justify-between gap-3 rounded-2xl bg-[#F7F7F8] px-3.5 py-3 transition-colors hover:bg-[#F0F0F0]"
                  >
                    <Link
                      className="rd-attention-client flex min-w-0 flex-1 items-center gap-3"
                      href={`/clients/${item.client_id}`}
                    >
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-xs font-semibold text-[var(--ink)] shadow-sm">
                        {item.trade_name.slice(0, 2).toUpperCase()}
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-[var(--ink)] hover:underline">
                          {item.trade_name}
                        </span>
                        <span className="mt-0.5 block truncate text-xs text-gray-400">
                          {status
                            ? status === "FAILED"
                              ? "Failed — needs retry"
                              : item.missed_itc != null
                                ? formatMissedSnippet(item.missed_itc)
                                : item.period
                            : "No reconciliations yet"}
                          {item.compliance_risk
                            ? ` · ${complianceRiskWords(item.compliance_risk)}`
                            : ""}
                        </span>
                      </div>
                    </Link>

                    <div className="flex shrink-0 items-center gap-2">
                      {status ? (
                        <StatusBadge status={status} />
                      ) : (
                        <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-gray-500">
                          Pending
                        </span>
                      )}

                      {status === "COMPLETE" && item.run_id ? (
                        <button
                          type="button"
                          onClick={() => router.push(`/reconcile/runs/${item.run_id}/results`)}
                          className="rounded-full bg-[var(--ink)] px-3 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90"
                        >
                          Review →
                        </button>
                      ) : status === "FAILED" ? (
                        <button
                          type="button"
                          onClick={() => setRetryRow(attentionToPortfolioRow(item))}
                          className="rounded-full border border-[var(--danger)] bg-transparent px-3 py-1.5 text-xs font-semibold text-[var(--danger)] transition-colors hover:bg-red-50"
                        >
                          Retry
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => router.push(`/clients/${item.client_id}`)}
                          className="rounded-full bg-[var(--ink)] px-3 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90"
                        >
                          Start
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      <section className="rd-client-directory dashboard-card space-y-5 p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
              Manage clients
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Filter, review, and take action across your portfolio
            </p>
          </div>
          <Link
            href="/clients?add=1"
            className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Add client
          </Link>
        </div>

        {directoryLoading ? (
          <div className="h-11 animate-pulse rounded-full bg-gray-100" aria-hidden />
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
            density={density}
            onDensityChange={setDensity}
          />
        )}

        {!portfolioLoading && portfolio && portfolio.total === 0 && showReset && (
          <div className="rounded-2xl bg-[#F7F7F8] px-6 py-10 text-center text-sm text-gray-400">
            No clients match your filters.{" "}
            <button
              type="button"
              className="font-semibold text-[var(--ink)] underline"
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
            density={density}
          />
        )}
      </section>

      {!directoryLoading && staff.length === 0 && (
        <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
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
        <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 flex-wrap items-center gap-3 rounded-full bg-white/90 px-5 py-3 shadow-[var(--shadow-lift)] ring-1 ring-black/[0.06] backdrop-blur-xl">
          <span className="text-sm font-semibold text-[var(--ink)]">
            {selectedIds.size} selected
          </span>
          <select
            className="rounded-full bg-[#F5F5F6] px-3 py-1.5 text-sm font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-black/10"
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
            className="rounded-full bg-[var(--ink)] px-5 py-2 text-sm font-semibold text-white disabled:opacity-40 transition-opacity hover:opacity-90"
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
            className="text-sm font-medium text-gray-400 transition-colors hover:text-gray-700"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
