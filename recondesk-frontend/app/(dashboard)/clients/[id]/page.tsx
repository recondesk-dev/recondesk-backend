"use client";

import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import useSWR from "swr";
import { useParams } from "next/navigation";

import { ItcTrendChart } from "@/components/dashboard/ItcTrendChart";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Avatar } from "@/components/ui/Avatar";
import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import {
  authApi,
  clientsApi,
  reconcileRunsApi,
  teamApi,
  type ClientGstin,
  type ReconcileRunListRow,
} from "@/lib/api";
import {
  DW,
  buildRunRowsForClient,
  buildStaffRoster,
  clientGstinToClient,
  staffForAssignee,
} from "@/lib/dashboard-portfolio";
import { formatInrFull } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import type { ItcTrendPoint, ReconciliationRun } from "@/lib/types";

const HISTORY_PAGE = 10;

function CardSkeleton() {
  return (
    <div className="animate-pulse space-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
      <div className="h-4 w-48 rounded bg-[#E5E7EB]" />
      <div className="h-4 w-64 rounded bg-[#E5E7EB]" />
      <div className="h-4 w-40 rounded bg-[#E5E7EB]" />
    </div>
  );
}

function HistorySkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-10 animate-pulse rounded bg-[#E5E7EB]" />
      ))}
    </div>
  );
}

function missedCell(run: ReconciliationRun) {
  if (run.missedItc == null) {
    return <span className="text-[var(--text-secondary)]">—</span>;
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

export default function ClientDetailPage() {
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
      reconcileRunsApi.list(t, { client_gstin_id: cid, limit: 200 }),
    { revalidateOnFocus: false }
  );

  const { data: teamMembers } = useSWR(teamKey, ([, , t]) => teamApi.list(t), {
    revalidateOnFocus: false,
  });

  const { data: me } = useSWR(meKey, ([, , t]) => authApi.me(t), {
    revalidateOnFocus: false,
  });

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

  const latest = sortedRuns[0] ?? null;

  const runInProgress = sortedRuns.some(
    (r) => r.status === "IMPORTING" || r.status === "MATCHING"
  );

  const completeTooFresh =
    latest?.status === "COMPLETE" &&
    Date.now() - new Date(latest.updatedAt).getTime() < 24 * 60 * 60 * 1000;

  const startDisabled = runInProgress || completeTooFresh;
  const startTitle = runInProgress
    ? "Run in progress"
    : completeTooFresh
      ? "No change since last run"
      : undefined;

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
      <div className="space-y-8">
        <CardSkeleton />
        <div className="h-[200px] animate-pulse rounded-lg bg-[#E5E7EB]" />
        <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <HistorySkeleton />
        </div>
      </div>
    );
  }

  if (tokenState === false) {
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-8 text-center text-sm text-[var(--text-secondary)]">
        Sign in required to view this client.
      </div>
    );
  }

  return (
    <div className="space-y-8" id="top">
      {clientError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load client details.
        </div>
      )}

      {cLoad || !client ? (
        <CardSkeleton />
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="font-mono text-[var(--text-primary)]">{client.gstin}</span>
              <span className="text-[var(--text-secondary)]">|</span>
              <span className="text-lg font-semibold text-[var(--text-primary)]">
                {client.tradeName}
              </span>
            </div>
            <p className="text-sm text-[var(--text-secondary)]">
              Registration: <strong className="text-[var(--text-primary)]">{client.registrationType}</strong>
            </p>
            {assigned && (
              <div className="flex items-center gap-2">
                <Avatar initials={assigned.avatarInitials} size="sm" />
                <span className="text-sm">{assigned.name}</span>
              </div>
            )}
            <Link href="/clients" className="text-sm font-medium text-[var(--accent)] hover:underline">
              Edit Client
            </Link>
          </div>
          <div className="flex flex-col items-end gap-2">
            <button
              type="button"
              disabled={startDisabled}
              title={startTitle}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              Start New Reconciliation
            </button>
          </div>
        </div>
      )}

      {latest?.status === "FAILED" && latest.errorMessage && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          Last reconciliation failed. {latest.errorMessage}{" "}
          <Link href="#history" className="font-semibold text-[var(--accent)] underline">
            Retry →
          </Link>
        </div>
      )}
      {latest?.status === "COMPLETE" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Results ready. Review and finalize →
        </div>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">ITC trend (missed)</h2>
        {rLoad ? (
          <div className="h-[200px] animate-pulse rounded-lg bg-[#E5E7EB]" />
        ) : sortedRuns.length < 3 ? (
          <p className="text-sm text-[var(--text-secondary)]">
            ITC trend available after 3+ reconciliations
          </p>
        ) : trendData ? (
          <ItcTrendChart data={trendData} />
        ) : null}
      </section>

      <section id="history">
        <h2 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">Reconciliation history</h2>
        {runsError && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            Could not load reconciliation history.
          </div>
        )}
        <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          {rLoad ? (
            <HistorySkeleton />
          ) : sortedRuns.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
              <div className="mx-auto w-full max-w-[400px]">
                <EmptyStateIllustration className="mx-auto text-gray-400" />
                <h3 className="mt-4 text-lg font-semibold text-gray-900">
                  No reconciliations yet
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  Start a reconciliation to see results here
                </p>
                <Link
                  href={`/reconcile/${id}/new`}
                  className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-lg bg-[var(--accent)] px-5 text-sm font-semibold text-white"
                >
                  Start Reconciliation
                </Link>
              </div>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-[960px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] bg-[#FAFAFB] text-xs font-semibold uppercase text-[var(--text-secondary)]">
                      <th className="px-3 py-3">Period</th>
                      <th className="px-3 py-3">Run #</th>
                      <th className="px-3 py-3">Status</th>
                      <th className="px-3 py-3">Match Rate</th>
                      <th className="px-3 py-3">ITC Claimed</th>
                      <th className="px-3 py-3">Missed ITC</th>
                      <th className="px-3 py-3">Finalized By</th>
                      <th className="px-3 py-3">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {histSlice.map((run) => {
                      const fin = run.status === "FINALIZED";
                      const fail = run.status === "FAILED";
                      const border = fin
                        ? "border-l-4 border-l-[var(--accent)]"
                        : fail
                          ? "border-l-4 border-l-[var(--danger)]"
                          : "";
                      return (
                        <Fragment key={run.id}>
                          <tr
                            className={`border-b border-[var(--border)] ${border} ${
                              fail ? "cursor-pointer" : ""
                            }`}
                            onClick={() => fail && toggleExpand(run.id)}
                          >
                            <td className="px-3 py-3">{run.period}</td>
                            <td className="px-3 py-3 font-mono">{run.runNumber}</td>
                            <td className="px-3 py-3">
                              <StatusBadge status={run.status} finalizedLock={fin} />
                            </td>
                            <td className="px-3 py-3 font-mono text-[var(--text-secondary)]">
                              {run.matchRate != null ? `${run.matchRate}%` : "—"}
                            </td>
                            <td className="px-3 py-3 font-mono">
                              {run.itcClaimed != null ? formatInrFull(run.itcClaimed) : "—"}
                            </td>
                            <td className="px-3 py-3">{missedCell(run)}</td>
                            <td className="px-3 py-3">{run.finalizedBy ?? "—"}</td>
                            <td className="px-3 py-3 text-[var(--text-secondary)]">
                              {new Date(run.createdAt).toLocaleString("en-IN")}
                            </td>
                          </tr>
                          {fail && expanded.has(run.id) && run.errorMessage && (
                            <tr className="bg-red-50">
                              <td colSpan={8} className="px-3 py-2 text-xs text-[var(--danger)]">
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
              <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-3 text-sm text-[var(--text-secondary)]">
                <span>
                  Page {histSafe} / {histPages}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={histSafe <= 1}
                    className="rounded border border-[var(--border)] px-3 py-1 disabled:opacity-40"
                    onClick={() => setHistPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    disabled={histSafe >= histPages}
                    className="rounded border border-[var(--border)] px-3 py-1 disabled:opacity-40"
                    onClick={() => setHistPage((p) => Math.min(histPages, p + 1))}
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
