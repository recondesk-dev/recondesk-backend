"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReconcileRunListRow } from "@/lib/api";
import { mapBackendRunStatus } from "@/lib/dashboard-portfolio";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

type ChartPoint = {
  month: string;
  runs: number;
  ready: number;
};

function buildMonthlyActivity(runs: ReconcileRunListRow[]): ChartPoint[] {
  const year = new Date().getFullYear();
  const buckets = MONTHS.map((month) => ({ month, runs: 0, ready: 0 }));

  for (const run of runs) {
    const m = /^(\d{4})-(\d{2})$/.exec((run.period || "").trim());
    if (!m) continue;
    const y = Number(m[1]);
    const mo = Number(m[2]) - 1;
    if (y !== year || mo < 0 || mo > 11) continue;
    buckets[mo].runs += 1;
    const status = mapBackendRunStatus(run.status);
    if (status === "COMPLETE" || status === "FINALIZED") {
      buckets[mo].ready += 1;
    }
  }

  return buckets;
}

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: ChartPoint }[];
}) {
  if (!active || !payload?.[0]) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-full bg-[var(--ink)] px-3.5 py-1.5 text-xs font-semibold text-white shadow-lg">
      {row.runs} runs · {row.ready} ready
    </div>
  );
}

export function PortfolioActivityChart({
  runs,
  loading,
}: {
  runs: ReconcileRunListRow[];
  loading?: boolean;
}) {
  const data = useMemo(() => buildMonthlyActivity(runs), [runs]);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const peak = useMemo(
    () => data.reduce((max, d, i) => (d.runs > (data[max]?.runs ?? -1) ? i : max), 0),
    [data]
  );
  const highlight = hoverIndex ?? peak;
  const highlightValue = data[highlight]?.runs ?? 0;

  if (loading) {
    return <div className="h-[280px] animate-pulse rounded-[1.5rem] bg-gray-100" />;
  }

  return (
    <div className="dashboard-card relative overflow-hidden p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            Reconciliation activity
          </h2>
          <p className="mt-1 text-sm text-gray-500">Runs and ready reviews across {new Date().getFullYear()}</p>
        </div>
        {highlightValue > 0 ? (
          <span className="rounded-full bg-[var(--ink)] px-3 py-1 text-xs font-semibold text-white">
            {highlightValue >= 1000 ? `${(highlightValue / 1000).toFixed(1)}K` : highlightValue}
          </span>
        ) : null}
      </div>
      <div className="h-[240px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 12, right: 4, left: -18, bottom: 0 }}
            barGap={4}
            onMouseMove={(state) => {
              if (state?.activeTooltipIndex != null) {
                setHoverIndex(Number(state.activeTooltipIndex));
              }
            }}
            onMouseLeave={() => setHoverIndex(null)}
          >
            <CartesianGrid strokeDasharray="0" stroke="#F0F0F0" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: "#9CA3AF", fontWeight: 500 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#C0C0C4" }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
            />
            <Tooltip
              cursor={{ fill: "rgba(17,17,17,0.03)", radius: 8 }}
              content={<ChartTooltip />}
            />
            <Bar dataKey="runs" fill="#111111" radius={[8, 8, 8, 8]} maxBarSize={14} />
            <Bar dataKey="ready" fill="#E5E7EB" radius={[8, 8, 8, 8]} maxBarSize={14} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[var(--ink)]" /> Runs posted
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-gray-300" /> Ready / finalized
        </span>
      </div>
    </div>
  );
}
