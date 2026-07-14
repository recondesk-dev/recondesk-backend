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
    <div className="rounded-full bg-[var(--ink)] px-3.5 py-1.5 text-xs font-semibold text-white shadow-lg">
      {formatInrFull(row.missedItc)} missed · {row.period}
    </div>
  );
}

export function ItcTrendChart({ data }: { data: ItcTrendPoint[] }) {
  const allZero = data.every((d) => d.missedItc === 0);

  if (allZero) {
    return (
      <div className="flex h-[200px] items-center justify-center rounded-2xl bg-[#F0FDF4] text-sm font-medium text-[var(--success)]">
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
          <CartesianGrid strokeDasharray="0" stroke="#F0F0F0" vertical={false} />
          <XAxis
            dataKey="short"
            tick={{ fontSize: 11, fill: "#9CA3AF", fontWeight: 500 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v) => formatInrAxis(Number(v))}
            tick={{ fontSize: 10, fill: "#C0C0C4" }}
            axisLine={false}
            tickLine={false}
            width={56}
          />
          <Tooltip
            cursor={{ fill: "rgba(17,17,17,0.03)", radius: 8 }}
            content={<TrendTooltip />}
          />
          <Bar
            dataKey="missedItc"
            fill="#111111"
            radius={[8, 8, 8, 8]}
            maxBarSize={28}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
