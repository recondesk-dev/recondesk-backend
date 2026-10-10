"use client";

import Link from "next/link";
import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import {
  ConnectGstnModal,
  isGstnConnected,
} from "@/components/clients/ConnectGstnModal";

import { ItcTrendChart } from "@/components/dashboard/ItcTrendChart";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Avatar } from "@/components/ui/Avatar";
import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import {
  clientsApi,
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
  buildRunRowsForClient,
  buildStaffRoster,
  clientGstinToClient,
  staffForAssignee,
} from "@/lib/dashboard-portfolio";
import { formatInrFull } from "@/lib/format";
import { listGstr1Runs } from "@/lib/gstr1Reconcile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import type { ItcTrendPoint, ReconciliationRun } from "@/lib/types";

const HISTORY_PAGE = 10;

function CardSkeleton() {
  return (
    <div className="dashboard-card animate-pulse space-y-3 p-6">
      <div className="h-4 w-48 rounded-full bg-gray-100" />
      <div className="h-4 w-64 rounded-full bg-gray-100" />
      <div className="h-4 w-40 rounded-full bg-gray-100" />
    </div>
  );
}

function HistorySkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-10 animate-pulse rounded-2xl bg-gray-100" />
      ))}
    </div>
  );
}

function missedCell(run: ReconciliationRun) {
  if (run.missedItc == null) {
    return <span className="text-gray-400">—</span>;
  }
  if (run.missedItc === 0) {
    return <span className="font-mono font-bold text-[var(--success)]">₹0</span>;
  }
  return (
    <span className="font-mono font-semibold text-[var(--success)]">
      {formatInrFull(run.missedItc)}
    </span>
  );
}

function itcTrendFromRuns(runsNewestFirst: ReconciliationRun[]): ItcTrendPoint[] {
  const asc = [...runsNewestFirst].sort(
    (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
  );
  return asc.map((r) => ({
    period: r.period,
    missedItc: r.missedItc ?? 0,
  }));
}

function ClientDetailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("return_to");
  const params = useParams();
  const id = params?.id as string;
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const clientKey =
    authToken && id ? ([DW, "client-detail", authToken, id] as const) : null;
  const runsKey =
    authToken && id ? ([DW, "runs-detail", authToken, id] as const) : null;
  const teamKey = authToken ? ([DW, "team-detail", authToken] as const) : null;
  const meKey = authToken ? ([DW, "me-detail", authToken] as const) : null;

  const {
    data: rawClient,
    error: clientError,
    isLoading: cLoad,
    mutate: mutateClient,
  } = useSWR(clientKey, ([, , t, cid]) => clientsApi.get(t, cid), {
    revalidateOnFocus: false,
  });

  const {
    data: runRows,
    error: runsError,
    isLoading: rLoad,
  } = useSWR(
    runsKey,
    ([, , t, cid]) =>
      reconcileRunsApi.list(t, { client_gstin_id: cid, limit: 200, light: true }),
    { revalidateOnFocus: false }
  );

  const { data: teamMembers } = useSWR(teamKey, ([, , t]) => teamApi.list(t), {
    revalidateOnFocus: false,
  });

  const { data: me } = useSWR(
    meKey,
    ([, , t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const staff = useMemo(
    () => buildStaffRoster(teamMembers ?? [], me ?? null),
    [teamMembers, me]
  );

  const client = useMemo(() => {
    if (!rawClient) return null;
    return clientGstinToClient(rawClient as ClientGstin);
  }, [rawClient]);

  const sortedRuns = useMemo(
    () =>
      id && runRows
        ? buildRunRowsForClient(runRows as ReconcileRunListRow[], id)
        : [],
    [runRows, id]
  );

  const assigned = useMemo(
    () => (client ? staffForAssignee(staff, client.assignedStaffId) : undefined),
    [staff, client]
  );

  const trendData =
    sortedRuns.length >= 3 ? itcTrendFromRuns(sortedRuns) : null;

  const [histPage, setHistPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [connectGstnOpen, setConnectGstnOpen] = useState(false);
  const [latestGstr1RunId, setLatestGstr1RunId] = useState<string | null>(null);

  const gstnConnected = isGstnConnected(rawClient as ClientGstin | undefined);

  const latest = sortedRuns[0] ?? null;

  const runInProgress = sortedRuns.some(
    (r) => r.status === "IMPORTING" || r.status === "MATCHING"
  );

  const startDisabled = runInProgress;
  const startTitle = runInProgress ? "Run in progress" : undefined;

  const reconcileNewHref = id ? `/reconcile/${id}/new` : "";
  const gstr1NewHref = id
    ? `/reconcile/gstr1/new?client_gstin_id=${encodeURIComponent(id)}`
    : "/reconcile/gstr1/new";

  // Source of truth: persisted GSTR-1 runs (not session storage).
  useEffect(() => {
    if (!authToken || !id) {
      setLatestGstr1RunId(null);
      return;
    }
    let cancelled = false;
    void listGstr1Runs(authToken, {
      client_gstin_id: id,
      limit: 1,
      status: "COMPLETED",
    })
      .then((rows) => {
        if (!cancelled) {
          setLatestGstr1RunId(rows[0]?.id ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) setLatestGstr1RunId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [authToken, id]);

  const histTotal = sortedRuns.length;
  const histPages = Math.max(1, Math.ceil(histTotal / HISTORY_PAGE));
  const histSafe = Math.min(histPage, histPages);
  const histSlice = sortedRuns.slice((histSafe - 1) * HISTORY_PAGE, histSafe * HISTORY_PAGE);

  const toggleExpand = (runId: string) => {
    setExpanded((prev) => {
      const n = new Set(prev);
      if (n.has(runId)) n.delete(runId);
      else n.add(runId);
      return n;
    });
  };

  if (tokenState === null) {
    return (
      <div className="space-y-6">
        <CardSkeleton />
        <div className="h-[200px] animate-pulse rounded-[1.5rem] bg-gray-100" />
        <div className="dashboard-card overflow-hidden">
          <HistorySkeleton />
        </div>
      </div>
    );
  }

  if (tokenState === false) {
    return (
      <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
        Sign in required to view this client.
      </div>
    );
  }

  return (
    <div className="space-y-6" id="top">
      {returnTo ? (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-[1.25rem] border border-blue-200 bg-blue-50/80 p-4 text-sm text-blue-900 shadow-[var(--shadow-soft)]">
          <div>
            <p className="font-semibold text-blue-950">Active Reconciliation Wizard in Progress</p>
            <p className="mt-0.5 text-xs text-blue-800">
              You navigated here to connect GSTN or manage client settings. Your wizard progress is saved.
            </p>
          </div>
          <Link
            href={returnTo}
            className="shrink-0 inline-flex items-center gap-1 rounded-full bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm hover:opacity-90 transition-opacity"
          >
            ← Return to Wizard
          </Link>
        </div>
      ) : null}

      {clientError && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load client details.
        </div>
      )}

      {cLoad || !client ? (
        <CardSkeleton />
      ) : (
        <div className="dashboard-card flex flex-wrap items-start justify-between gap-4 p-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="font-mono text-[var(--ink)]">{client.gstin}</span>
              {gstnConnected ? (
                <span className="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                  GSTN connected ✓
                </span>
              ) : (
                <span className="inline-flex items-center rounded-full bg-[#F5F5F6] px-2.5 py-0.5 text-xs font-medium text-gray-500">
                  GSTN not connected
                </span>
              )}
              <span className="text-gray-300">|</span>
              <span className="text-lg font-semibold tracking-tight text-[var(--ink)]">
                {client.tradeName}
              </span>
            </div>
            <p className="text-sm text-gray-500">
              Registration:{" "}
              <strong className="font-semibold text-[var(--ink)]">
                {client.registrationType}
              </strong>
            </p>
            {assigned && (
              <div className="flex items-center gap-2">
                <Avatar initials={assigned.avatarInitials} size="sm" />
                <span className="text-sm text-gray-700">{assigned.name}</span>
              </div>
            )}
            <Link
              href="/clients"
              className="text-sm font-semibold text-[var(--ink)] underline"
            >
              Edit Client
            </Link>
          </div>
          <div className="relative z-10 flex w-full max-w-3xl flex-col items-stretch gap-3 sm:items-end">
            {!gstnConnected && authToken && (
              <button
                type="button"
                onClick={() => setConnectGstnOpen(true)}
                className="inline-flex items-center justify-center self-end rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-semibold text-[var(--ink)] transition-colors hover:bg-gray-200/70"
              >
                Connect GSTN
              </button>
            )}
            <div className="w-full">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-gray-400 sm:text-right">
                Workflows & Reconciliations
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <Link
                  href={id ? `/clients/${id}/command-center` : "#"}
                  title="ITC Command Center — Statutory countdowns, executive KPIs & work items"
                  className="flex flex-col items-start gap-1 rounded-[1.25rem] border border-black bg-black px-4 py-3 text-left transition-opacity hover:opacity-90 shadow-sm"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-sm font-semibold text-white">
                      ITC Command Center
                    </span>
                  </div>
                  <span className="text-[11px] font-medium leading-snug text-white/80">
                    Statutory countdowns, Table 4 position & audit queue
                  </span>
                </Link>
                {startDisabled || !reconcileNewHref ? (
                  <button
                    type="button"
                    disabled
                    title={startTitle}
                    className="flex cursor-not-allowed flex-col items-start gap-1 rounded-[1.25rem] bg-[var(--ink)] px-4 py-3 text-left opacity-50"
                  >
                    <span className="text-sm font-semibold text-white">
                      GSTR-2B Reconciliation
                    </span>
                    <span className="text-[11px] font-medium leading-snug text-white/70">
                      Purchase Register vs GSTR-2B — ITC matching and eligibility
                    </span>
                  </button>
                ) : (
                  <Link
                    href={reconcileNewHref}
                    title={startTitle}
                    className="flex flex-col items-start gap-1 rounded-[1.25rem] bg-[var(--ink)] px-4 py-3 text-left transition-opacity hover:opacity-90"
                  >
                    <span className="text-sm font-semibold text-white">
                      GSTR-2B Reconciliation
                    </span>
                    <span className="text-[11px] font-medium leading-snug text-white/70">
                      Purchase Register vs GSTR-2B — ITC matching and eligibility
                    </span>
                  </Link>
                )}
                <Link
                  href={`/clients/${id}/multi-period`}
                  title="Annual Purchase Reconciliation — 12-Month Batch"
                  className="flex flex-col items-start gap-1 rounded-[1.25rem] bg-[var(--ink)] px-4 py-3 text-left transition-opacity hover:opacity-90"
                >
                  <span className="text-sm font-semibold text-white">
                    Annual Purchase Reconciliation
                  </span>
                  <span className="text-[11px] font-medium leading-snug text-white/70">
                    12-Month Batch — Auto 2B & Tally Bridge sync
                  </span>
                </Link>
                <Link
                  href={gstr1NewHref}
                  title="Sales Register ↔ GSTR-1 matching & Table 3.1 tax tie-out"
                  className="flex flex-col items-start gap-1 rounded-[1.25rem] bg-[var(--ink)] px-4 py-3 text-left transition-opacity hover:opacity-90"
                >
                  <span className="text-sm font-semibold text-white">
                    GSTR-1 Reconciliation
                  </span>
                  <span className="text-[11px] font-medium leading-snug text-white/70">
                    Sales Register ↔ GSTR-1 matching & outward tax tie-out
                  </span>
                </Link>
                <Link
                  href={id ? `/clients/${id}/gstr9c` : "#"}
                  title="Annual 2B vs 3B ITC variance and GSTR-9/9C support"
                  className="flex flex-col items-start gap-1 rounded-[1.25rem] bg-[var(--ink)] px-4 py-3 text-left transition-opacity hover:opacity-90"
                >
                  <span className="text-sm font-semibold text-white">
                    Annual ITC Reconciliation
                  </span>
                  <span className="text-[11px] font-medium leading-snug text-white/70">
                    Annual 2B vs 3B ITC variance and GSTR-9/9C support
                  </span>
                </Link>
                <Link
                  href={id ? `/clients/${id}/gstr2a-delta` : "#"}
                  title="Supplier filing cutoff analysis & deferred ITC"
                  className="flex flex-col items-start gap-1 rounded-[1.25rem] bg-[var(--ink)] px-4 py-3 text-left transition-opacity hover:opacity-90"
                >
                  <span className="text-sm font-semibold text-white">
                    2A vs 2B Timing Analysis
                  </span>
                  <span className="text-[11px] font-medium leading-snug text-white/70">
                    Supplier filing cutoff analysis & deferred ITC
                  </span>
                </Link>
                <Link
                  href={id ? `/filing/gstr-4?client_id=${id}` : "/filing/gstr-4"}
                  title="Composition Scheme Annual Return & CMP-08"
                  className="flex flex-col items-start gap-1 rounded-[1.25rem] bg-[var(--ink)] px-4 py-3 text-left transition-opacity hover:opacity-90"
                >
                  <span className="text-sm font-semibold text-white">
                    GSTR-4 & CMP-08 Composition
                  </span>
                  <span className="text-[11px] font-medium leading-snug text-white/70">
                    Composition Scheme Annual Return — rate calc & CMP-08 tie-out
                  </span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      )}

      {authToken && client && (
        <ConnectGstnModal
          open={connectGstnOpen}
          onClose={() => setConnectGstnOpen(false)}
          clientGstinId={id}
          defaultGstin={client.gstin}
          authToken={authToken}
          onSuccess={() => {
            void mutateClient();
            if (clientKey) void mutate(clientKey);
            if (returnTo) {
              router.push(returnTo);
            }
          }}
        />
      )}

      {latest?.status === "FAILED" && latest.errorMessage && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-900">
          Last GSTR-2B reconciliation failed. {latest.errorMessage}{" "}
          <Link href="#history" className="font-semibold text-[var(--ink)] underline">
            Retry →
          </Link>
        </div>
      )}
      {(latest?.status === "COMPLETE" || latest?.status === "FINALIZED") && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm font-medium text-amber-950">
          <span>
            GSTR-2B results {latest.status === "COMPLETE" ? "ready for review" : "finalized"} ({latest.period}).
          </span>
          <div className="flex items-center gap-2.5">
            <Link
              href={`/reconcile/runs/${latest.id}/results`}
              className="font-semibold text-[var(--ink)] underline hover:opacity-80 text-xs sm:text-sm"
            >
              Review Results →
            </Link>
            <span className="text-gray-300">|</span>
            <Link
              href={`/reconcile/runs/${latest.id}/gstr3b`}
              className="inline-flex items-center gap-1 rounded-full bg-[var(--ink)] px-3.5 py-1.5 text-xs font-semibold text-white hover:opacity-90 whitespace-nowrap"
            >
              GSTR-3B Table 4 →
            </Link>
          </div>
        </div>
      )}
      {latestGstr1RunId && (
        <Link
          href={`/reconcile/gstr1/results?run_id=${encodeURIComponent(latestGstr1RunId)}`}
          className="block rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm font-medium text-amber-950 transition-colors hover:bg-amber-100/80"
        >
          GSTR-1 results ready. Review and finalize →
        </Link>
      )}

      <section className="dashboard-card p-6">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            ITC trend (missed)
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Missed ITC across recent reconciliations for this client
          </p>
        </div>
        <div className="mt-4">
          {rLoad ? (
            <div className="h-[200px] animate-pulse rounded-2xl bg-gray-100" />
          ) : sortedRuns.length < 3 ? (
            <div className="flex h-[160px] items-center justify-center rounded-2xl bg-[#F7F7F8] px-4 text-center text-sm text-gray-500">
              ITC trend available after 3+ reconciliations
            </div>
          ) : trendData ? (
            <ItcTrendChart data={trendData} />
          ) : null}
        </div>
      </section>

      <section id="history" className="dashboard-card space-y-5 p-6">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            Reconciliation history
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Past reconciliations for this GSTIN — expand failed rows for error details
          </p>
        </div>
        {runsError && (
          <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
            Could not load reconciliation history.
          </div>
        )}
        {rLoad ? (
          <HistorySkeleton />
        ) : sortedRuns.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl bg-[#F7F7F8] px-6 py-14 text-center">
            <div className="mx-auto w-full max-w-[400px]">
              <EmptyStateIllustration className="mx-auto text-gray-300" />
              <h3 className="mt-4 text-lg font-semibold text-[var(--ink)]">
                No reconciliations yet
              </h3>
              <p className="mt-1 text-sm text-gray-500">
                Start a reconciliation to see results here
              </p>
              <Link
                href={reconcileNewHref}
                className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
              >
                Start Reconciliation
              </Link>
            </div>
          </div>
        ) : (
          <>
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-[960px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                      <th className="px-5 py-4">Period</th>
                      <th className="px-4 py-4">Run #</th>
                      <th className="px-4 py-4">Status</th>
                      <th className="px-4 py-4">Match Rate</th>
                      <th className="px-4 py-4">ITC Claimed</th>
                      <th className="px-4 py-4">Missed ITC</th>
                      <th className="px-4 py-4">Finalized By</th>
                      <th className="px-5 py-4">Date</th>
                      <th className="px-5 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {histSlice.map((run) => {
                      const fin = run.status === "FINALIZED";
                      const fail = run.status === "FAILED";
                      return (
                        <Fragment key={run.id}>
                          <tr
                            className={`border-b border-[#F0F0F0] transition-colors last:border-b-0 hover:bg-[#F7F7F8] ${
                              fin ? "border-l-4 border-l-[var(--ink)]" : ""
                            } ${fail ? "cursor-pointer border-l-4 border-l-[var(--danger)]" : ""}`}
                            onClick={() => fail && toggleExpand(run.id)}
                          >
                            <td className="px-5 py-3.5 font-medium text-[var(--ink)]">
                              {run.period}
                            </td>
                            <td className="px-4 py-3.5 font-mono text-gray-600">
                              {run.runNumber}
                            </td>
                            <td className="px-4 py-3.5">
                              <StatusBadge status={run.status} finalizedLock={fin} />
                            </td>
                            <td className="px-4 py-3.5 font-mono text-gray-500">
                              {run.matchRate != null ? `${run.matchRate}%` : "—"}
                            </td>
                            <td className="px-4 py-3.5 font-mono text-gray-700">
                              {run.itcClaimed != null ? formatInrFull(run.itcClaimed) : "—"}
                            </td>
                            <td className="px-4 py-3.5">{missedCell(run)}</td>
                            <td className="px-4 py-3.5 text-gray-600">
                              {run.finalizedBy ?? "—"}
                            </td>
                            <td className="px-5 py-3.5 text-gray-400">
                              {new Date(run.createdAt).toLocaleString("en-IN")}
                            </td>
                            <td className="px-5 py-3.5 text-right">
                              <div className="inline-flex items-center justify-end gap-2">
                                <Link
                                  href={`/reconcile/runs/${run.id}/results`}
                                  className="rounded-full bg-[#F0F0F0] px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-200"
                                >
                                  Results
                                </Link>
                                <Link
                                  href={`/reconcile/runs/${run.id}/gstr3b`}
                                  className="inline-flex items-center gap-1 rounded-full bg-[var(--ink)] px-3 py-1 text-xs font-semibold text-white hover:opacity-90 whitespace-nowrap"
                                >
                                  GSTR-3B Table 4 →
                                </Link>
                              </div>
                            </td>
                          </tr>
                          {fail && expanded.has(run.id) && run.errorMessage && (
                            <tr className="bg-red-50">
                              <td colSpan={9} className="px-5 py-2.5 text-xs text-[var(--danger)]">
                                {run.errorMessage}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="flex items-center justify-between text-sm text-gray-500">
              <span>
                Page {histSafe} / {histPages}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={histSafe <= 1}
                  className="rounded-full bg-[#F5F5F6] px-4 py-1.5 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-gray-200/70 disabled:opacity-40"
                  onClick={() => setHistPage((p) => Math.max(1, p - 1))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={histSafe >= histPages}
                  className="rounded-full bg-[#F5F5F6] px-4 py-1.5 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-gray-200/70 disabled:opacity-40"
                  onClick={() => setHistPage((p) => Math.min(histPages, p + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

export default function ClientDetailPage() {
  return (
    <Suspense fallback={<CardSkeleton />}>
      <ClientDetailContent />
    </Suspense>
  );
}
