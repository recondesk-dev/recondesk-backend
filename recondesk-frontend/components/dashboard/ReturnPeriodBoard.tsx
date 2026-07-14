"use client";

import { useMemo } from "react";
import type { ReconcileRunListRow } from "@/lib/api";
import {
  formatPeriodLabel,
  mapBackendRunStatus,
} from "@/lib/dashboard-portfolio";

type Bucket = "open" | "ready" | "finalized";

type PeriodRow = {
  periodKey: string;
  label: string;
  dueDate: Date;
  open: number;
  ready: number;
  finalized: number;
  clients: number;
  openDays: number;
};

function parsePeriod(period: string): { y: number; m: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec((period || "").trim());
  if (!match) return null;
  const y = Number(match[1]);
  const m = Number(match[2]);
  if (!y || m < 1 || m > 12) return null;
  return { y, m };
}

/** Monthly GSTR-3B due: 20th of the month after the return period. */
function gstr3bDueDate(periodKey: string): Date | null {
  const p = parsePeriod(periodKey);
  if (!p) return null;
  return new Date(p.y, p.m, 20);
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function daysBetween(from: Date, to: Date): number {
  const ms = startOfDay(to).getTime() - startOfDay(from).getTime();
  return Math.round(ms / 86_400_000);
}

function bucketForStatus(raw: string): Bucket {
  const status = mapBackendRunStatus(raw);
  if (status === "FINALIZED") return "finalized";
  if (status === "COMPLETE") return "ready";
  return "open";
}

function buildPeriodRows(runs: ReconcileRunListRow[], now: Date): PeriodRow[] {
  const latest = new Map<string, ReconcileRunListRow>();
  for (const run of runs) {
    const period = (run.period || "").trim();
    if (!parsePeriod(period)) continue;
    const key = `${run.client_gstin_id}|${period}`;
    const prev = latest.get(key);
    if (!prev || new Date(run.created_at) > new Date(prev.created_at)) {
      latest.set(key, run);
    }
  }

  const byPeriod = new Map<
    string,
    { open: number; ready: number; finalized: number }
  >();

  for (const run of latest.values()) {
    const period = (run.period || "").trim();
    const row = byPeriod.get(period) ?? { open: 0, ready: 0, finalized: 0 };
    row[bucketForStatus(run.status)] += 1;
    byPeriod.set(period, row);
  }

  const rows: PeriodRow[] = [];
  for (const [periodKey, counts] of byPeriod) {
    const due = gstr3bDueDate(periodKey);
    if (!due) continue;
    const clients = counts.open + counts.ready + counts.finalized;
    const periodEnd = (() => {
      const p = parsePeriod(periodKey)!;
      return new Date(p.y, p.m, 0);
    })();
    rows.push({
      periodKey,
      label: formatPeriodLabel(periodKey),
      dueDate: due,
      ...counts,
      clients,
      openDays: counts.open > 0 ? Math.max(0, daysBetween(periodEnd, now)) : 0,
    });
  }

  rows.sort((a, b) => {
    const aOpen = a.open + a.ready;
    const bOpen = b.open + b.ready;
    if (aOpen > 0 && bOpen === 0) return -1;
    if (bOpen > 0 && aOpen === 0) return 1;
    return b.periodKey.localeCompare(a.periodKey);
  });

  return rows.slice(0, 6);
}

function formatDueChip(due: Date, now: Date, hasWork: boolean): {
  text: string;
  tone: "urgent" | "soon" | "ok" | "muted";
} {
  const delta = daysBetween(now, due);
  if (!hasWork) {
    return { text: `3B due ${formatShortDate(due)}`, tone: "muted" };
  }
  if (delta < 0) {
    const n = Math.abs(delta);
    return {
      text: n === 1 ? "1 day past 3B due" : `${n} days past 3B due`,
      tone: "urgent",
    };
  }
  if (delta === 0) return { text: "3B due today", tone: "urgent" };
  if (delta <= 7) {
    return {
      text: delta === 1 ? "3B due tomorrow" : `3B due in ${delta} days`,
      tone: "soon",
    };
  }
  return { text: `3B due ${formatShortDate(due)}`, tone: "ok" };
}

function formatShortDate(d: Date): string {
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function chipClass(tone: "urgent" | "soon" | "ok" | "muted"): string {
  switch (tone) {
    case "urgent":
      return "bg-[#111111] text-white";
    case "soon":
      return "bg-[#F5F5F6] text-[var(--ink)] ring-1 ring-black/10";
    case "ok":
      return "bg-[#F5F5F6] text-gray-600";
    default:
      return "bg-[#F7F7F8] text-gray-400";
  }
}

export function ReturnPeriodBoard({
  runs,
  loading,
}: {
  runs: ReconcileRunListRow[];
  loading?: boolean;
}) {
  const now = useMemo(() => new Date(), []);
  const rows = useMemo(() => buildPeriodRows(runs, now), [runs, now]);
  const openPeriods = rows.filter((r) => r.open + r.ready > 0).length;
  const urgent = rows.find((r) => {
    if (r.open + r.ready === 0) return false;
    return daysBetween(now, r.dueDate) <= 7;
  });

  if (loading) {
    return <div className="h-[280px] animate-pulse rounded-[1.5rem] bg-gray-100" />;
  }

  return (
    <div className="dashboard-card relative overflow-hidden p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            Return periods
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Open filing months vs GSTR-3B — not a trend line
          </p>
        </div>
        {openPeriods > 0 ? (
          <span className="rounded-full bg-[var(--ink)] px-3 py-1 text-xs font-semibold text-white">
            {openPeriods} open
          </span>
        ) : rows.length > 0 ? (
          <span className="rounded-full bg-[#F5F5F6] px-3 py-1 text-xs font-semibold text-gray-500">
            Clear
          </span>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <div className="flex h-[220px] flex-col items-center justify-center rounded-2xl bg-[#F7F7F8] px-6 text-center">
          <p className="text-sm font-medium text-gray-700">No return periods yet</p>
          <p className="mt-1 max-w-xs text-xs text-gray-400">
            Once you post reconciliations, each tax month shows here with how close
            you are to the 3B due date.
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {urgent ? (
            <p className="mb-3 text-xs text-gray-500">
              Next pressure point:{" "}
              <span className="font-semibold text-[var(--ink)]">{urgent.label}</span>
              {" · "}
              {
                formatDueChip(
                  urgent.dueDate,
                  now,
                  urgent.open + urgent.ready > 0
                ).text
              }
            </p>
          ) : null}

          <ul className="space-y-2">
            {rows.map((row) => {
              const hasWork = row.open + row.ready > 0;
              const due = formatDueChip(row.dueDate, now, hasWork);
              const total = Math.max(row.clients, 1);
              const finalizedPct = (row.finalized / total) * 100;
              const readyPct = (row.ready / total) * 100;
              const openPct = (row.open / total) * 100;

              return (
                <li
                  key={row.periodKey}
                  className={`rounded-2xl px-4 py-3.5 transition-colors ${
                    hasWork && due.tone === "urgent"
                      ? "bg-[#111111] text-white"
                      : "bg-[#F7F7F8]"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p
                        className={`text-sm font-semibold tracking-tight ${
                          hasWork && due.tone === "urgent"
                            ? "text-white"
                            : "text-[var(--ink)]"
                        }`}
                      >
                        {row.label}
                      </p>
                      <p
                        className={`mt-0.5 text-xs ${
                          hasWork && due.tone === "urgent"
                            ? "text-white/65"
                            : "text-gray-400"
                        }`}
                      >
                        {row.clients}{" "}
                        {row.clients === 1 ? "client" : "clients"}
                        {row.open > 0
                          ? ` · open ${row.openDays}d past period end`
                          : row.ready > 0
                            ? " · review before filing"
                            : " · ready to file"}
                      </p>
                    </div>
                    <span
                      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                        hasWork && due.tone === "urgent"
                          ? "bg-white/15 text-white"
                          : chipClass(due.tone)
                      }`}
                    >
                      {due.text}
                    </span>
                  </div>

                  <div
                    className={`mt-3 flex h-2 overflow-hidden rounded-full ${
                      hasWork && due.tone === "urgent"
                        ? "bg-white/15"
                        : "bg-white"
                    }`}
                  >
                    {finalizedPct > 0 ? (
                      <span
                        className={
                          hasWork && due.tone === "urgent"
                            ? "bg-white"
                            : "bg-[var(--ink)]"
                        }
                        style={{ width: `${finalizedPct}%` }}
                      />
                    ) : null}
                    {readyPct > 0 ? (
                      <span
                        className={
                          hasWork && due.tone === "urgent"
                            ? "bg-white/55"
                            : "bg-gray-400"
                        }
                        style={{ width: `${readyPct}%` }}
                      />
                    ) : null}
                    {openPct > 0 ? (
                      <span
                        className={
                          hasWork && due.tone === "urgent"
                            ? "bg-white/25"
                            : "bg-gray-200"
                        }
                        style={{ width: `${openPct}%` }}
                      />
                    ) : null}
                  </div>

                  <div
                    className={`mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] ${
                      hasWork && due.tone === "urgent"
                        ? "text-white/70"
                        : "text-gray-500"
                    }`}
                  >
                    <span>{row.finalized} filed</span>
                    <span>{row.ready} ready</span>
                    <span>{row.open} still open</span>
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-gray-400">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--ink)]" /> Filed
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-gray-400" /> Ready for review
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-gray-200 ring-1 ring-gray-300" />{" "}
              Still open
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
