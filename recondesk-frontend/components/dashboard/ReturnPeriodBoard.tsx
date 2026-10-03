"use client";

import { useMemo, useState } from "react";
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

function buildPeriodRows(runs: ReconcileRunListRow[]): PeriodRow[] {
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

  for (const run of Array.from(latest.values())) {
    const period = (run.period || "").trim();
    const row = byPeriod.get(period) ?? { open: 0, ready: 0, finalized: 0 };
    row[bucketForStatus(run.status)] += 1;
    byPeriod.set(period, row);
  }

  const rows: PeriodRow[] = [];
  for (const [periodKey, counts] of Array.from(byPeriod.entries())) {
    const due = gstr3bDueDate(periodKey);
    if (!due) continue;
    rows.push({
      periodKey,
      label: formatPeriodLabel(periodKey),
      dueDate: due,
      ...counts,
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

export function ReturnPeriodBoard({
  runs, loading, selectedPeriod, onSelectPeriod,
}: {
  runs: ReconcileRunListRow[];
  loading?: boolean;
  selectedPeriod?: string;
  onSelectPeriod?: (period: string) => void;
}) {
  const now = useMemo(() => new Date(), []);
  const rows = useMemo(() => buildPeriodRows(runs), [runs]);
  const [expanded, setExpanded] = useState(false);
  const openPeriods = rows.filter((r) => r.open + r.ready > 0).length;
  const visibleRows = expanded ? rows : rows.slice(0, 3);

  return (
    <div className="rd-period-panel dashboard-card">
      <div className="rd-period-heading">
        <div>
          <h2>Return periods</h2>
          <p>Each month, one step closer to sign-off.</p>
        </div>
        {!loading && rows.length > 0 && <span className="rd-period-count">{openPeriods > 0 ? `${openPeriods} open` : "All clear"}</span>}
      </div>
      {loading ? (
        <div className="space-y-3" aria-label="Loading return periods">
          {[0, 1].map((i) => <div key={i} className="h-20 animate-pulse rounded-xl bg-gray-100" />)}
        </div>
      ) : rows.length === 0 ? (
        <div className="rd-period-empty">
          <p>No return periods yet</p>
          <span>Your filing months will appear after your first reconciliation.</span>
        </div>
      ) : (
        <>
          <ul className="rd-period-list">
            {visibleRows.map((row) => {
              const due = formatDueChip(row.dueDate, now, row.open + row.ready > 0);
              const selected = selectedPeriod === row.label;
              const content = <>
                <span className="rd-period-row-heading">
                  <span className="rd-period-month">{row.label}</span>
                  <span className="rd-period-due" data-tone={due.tone}>{due.text}</span>
                </span>
                <span className="rd-period-counts">
                  <span><i className="rd-period-dot rd-period-dot-finalized" /> <strong>{row.finalized}</strong> finalized</span>
                  <span><i className="rd-period-dot rd-period-dot-ready" /> <strong>{row.ready}</strong> ready</span>
                  <span><i className="rd-period-dot rd-period-dot-open" /> <strong>{row.open}</strong> open</span>
                </span>
              </>;
              return <li key={row.periodKey}>
                {onSelectPeriod ? (
                  <button type="button" className="rd-period-row" aria-pressed={selected}
                    onClick={() => onSelectPeriod(selected ? "ALL" : row.label)}
                    title={`Filter clients by ${row.label}`}>{content}</button>
                ) : <div className="rd-period-row">{content}</div>}
              </li>;
            })}
          </ul>
          <div className="rd-period-footer">
            {selectedPeriod && selectedPeriod !== "ALL" && onSelectPeriod ? (
              <button type="button" onClick={() => onSelectPeriod("ALL")}>Clear {formatPeriodLabel(selectedPeriod)} filter ×</button>
            ) : <span>Select a month to filter your clients</span>}
            {rows.length > 3 && <button type="button" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>{expanded ? "Show less" : `View all ${rows.length}`}</button>}
          </div>
        </>
      )}
    </div>
  );
}
