"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ItcTrendPoint } from "@/lib/types";
import { formatInrAxis, formatInrFull } from "@/lib/format";

function TrendTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: ItcTrendPoint }[];
}) {
  if (!active || !payload?.[0]) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs shadow-md">
      <span className="font-mono font-semibold text-[var(--text-primary)]">
        {formatInrFull(row.missedItc)} missed ITC — {row.period}
      </span>
    </div>
  );
}

export function ItcTrendChart({ data }: { data: ItcTrendPoint[] }) {
  const allZero = data.every((d) => d.missedItc === 0);

  if (allZero) {
    return (
      <div className="flex h-[200px] items-center justify-center rounded-full border border-[var(--border)] bg-[#F0FDF4] text-sm font-medium text-[var(--success)]">
        No missed ITC in the last 6 months ✓
      </div>
    );
  }

  const chartData = data.map((d) => ({
    ...d,
    short: d.period.split(" ")[0],
  }));

  return (
    <div className="h-[200px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="short" tick={{ fontSize: 11, fill: "var(--text-secondary)" }} />
          <YAxis
            tickFormatter={(v) => formatInrAxis(Number(v))}
            tick={{ fontSize: 10, fill: "var(--text-secondary)" }}
            width={56}
          />
          <Tooltip content={<TrendTooltip />} />
          <Bar dataKey="missedItc" fill="#6C63FF" radius={[4, 4, 0, 0]} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
