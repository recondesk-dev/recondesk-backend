"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";

import {
  filterDropdownClass,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import {
  gstr9cItcApi,
  type Gstr9cItcFyRollup,
  type Gstr9cItcMonthRow,
  type Gstr9cItcMonthStatus,
} from "@/lib/api";
import { formatINR } from "@/lib/format";

function defaultFyLabel(today = new Date()): string {
  const year = today.getFullYear();
  const month = today.getMonth() + 1;
  const start = month >= 4 ? year : year - 1;
  const endYy = String((start + 1) % 100).padStart(2, "0");
  return `${start}-${endYy}`;
}

function fyOptions(around = defaultFyLabel()): string[] {
  const start = Number(around.slice(0, 4));
  if (!Number.isFinite(start)) return [around];
  const opts: string[] = [];
  for (let y = start + 1; y >= start - 4; y -= 1) {
    const endYy = String((y + 1) % 100).padStart(2, "0");
    opts.push(`${y}-${endYy}`);
  }
  return opts;
}

function moneyCell(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return formatINR(value);
}

function statusLabel(status: Gstr9cItcMonthStatus): string {
  if (status === "both") return "2B + 3B";
  if (status === "run_only") return "2B only";
  return "Missing";
}

function statusClass(status: Gstr9cItcMonthStatus): string {
  if (status === "both") {
    return "bg-emerald-50 text-emerald-800";
  }
  if (status === "run_only") {
    return "bg-amber-50 text-amber-900";
  }
  return "bg-red-50 text-red-800";
}

function PanelSkeleton() {
  return (
    <div className={`${sectionContainerClass} animate-pulse space-y-4 p-6`}>
      <div className="h-5 w-64 rounded-full bg-gray-100" />
      <div className="h-10 w-40 rounded-full bg-gray-100" />
      <div className="h-28 w-full rounded-2xl bg-gray-100" />
      <div className="h-64 w-full rounded-2xl bg-gray-100" />
    </div>
  );
}

function IncompleteBanner({ data }: { data: Gstr9cItcFyRollup }) {
  if (data.is_complete) return null;
  return (
    <div
      role="status"
      className="rounded-[1.25rem] border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-950"
    >
      <p className="font-semibold tracking-tight">Incomplete financial year</p>
      <p className="mt-1 text-amber-900/90">
        {data.months_with_both} of 12 months have both a GSTR-2B reconciliation
        and a GSTR-3B upload
        {data.months_run_only > 0
          ? ` · ${data.months_run_only} month${data.months_run_only === 1 ? "" : "s"} with 2B only`
          : ""}
        {data.months_missing > 0
          ? ` · ${data.months_missing} month${data.months_missing === 1 ? "" : "s"} fully missing`
          : ""}
        . Annual variance is not a complete-year figure.
      </p>
    </div>
  );
}

function VarianceTotal({ data }: { data: Gstr9cItcFyRollup }) {
  const { totals, variance_available } = data;
  if (!variance_available) {
    return (
      <div className="rounded-[1.25rem] bg-[#F7F7F8] px-5 py-4">
        <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
          Annual variance (matched 2B − 3B claimed)
        </p>
        <p className="mt-2 text-lg font-semibold tracking-tight text-[var(--ink)]">
          No variance available
          <span className="ml-2 text-sm font-medium text-gray-500">
            ({totals.partial_label})
          </span>
        </p>
        <p className="mt-1 text-sm text-gray-500">
          Upload GSTR-3B against monthly purchase reconciliations to compute
          variance for those months. Uses clean-matched 2B ITC only — not all
          GSTR-2B available (see GSTR-3B tab for that net difference).
        </p>
      </div>
    );
  }

  const caveatClass = data.is_complete
    ? "text-gray-500"
    : "font-semibold text-amber-800";

  return (
    <div
      className={
        data.is_complete
          ? "rounded-[1.25rem] bg-[#F7F7F8] px-5 py-4"
          : "rounded-[1.25rem] border border-amber-200 bg-amber-50/60 px-5 py-4"
      }
    >
      <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
        Annual variance (matched 2B − 3B claimed)
      </p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-[var(--ink)]">
        {moneyCell(totals.variance_rupees)}
        <span className={`ml-2 text-sm ${caveatClass}`}>
          ({totals.partial_label})
        </span>
      </p>
      <p className="mt-1 text-sm text-gray-500">
        On months in variance: clean-matched {moneyCell(totals.variance_matched_itc_rupees)}{" "}
        vs claimed {moneyCell(totals.variance_claimed_itc_rupees)}. Differs from the GSTR-3B
        tab&apos;s net difference (all 2B available − claimed).
      </p>
    </div>
  );
}

function MonthRow({ row }: { row: Gstr9cItcMonthRow }) {
  const flagged = row.status !== "both";
  return (
    <tr
      className={`border-b border-[#F0F0F0] last:border-b-0 ${
        flagged ? "bg-amber-50/40" : ""
      }`}
    >
      <td className="px-5 py-3.5 font-medium text-[var(--ink)]">
        {row.month_label}
        <span className="ml-2 font-mono text-xs text-gray-400">{row.period}</span>
      </td>
      <td className="px-4 py-3.5">
        <span
          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${statusClass(
            row.status
          )}`}
        >
          {statusLabel(row.status)}
        </span>
      </td>
      <td className="px-4 py-3.5 font-mono text-gray-700">
        {moneyCell(row.matched_itc_rupees)}
      </td>
      <td className="px-4 py-3.5 font-mono text-gray-700">
        {moneyCell(row.claimed_itc_rupees)}
      </td>
      <td className="px-4 py-3.5 font-mono text-gray-700">
        {row.included_in_variance ? moneyCell(row.variance_rupees) : "—"}
      </td>
      <td className="px-5 py-3.5 text-sm text-gray-500">
        {row.run_id ? (
          <Link
            href={`/reconcile/runs/${row.run_id}/results`}
            className="font-medium text-[var(--ink)] underline"
          >
            Open run
          </Link>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

export function Gstr9cItcFyRollupPanel({
  clientId,
  authToken,
}: {
  clientId: string;
  authToken: string;
}) {
  const [fy, setFy] = useState(() => defaultFyLabel());
  const options = useMemo(() => fyOptions(fy), [fy]);

  const swrKey =
    clientId && authToken
      ? (["gstr9c-itc-fy", clientId, authToken, fy] as const)
      : null;

  const { data, error, isLoading, mutate, isValidating } = useSWR(
    swrKey,
    ([, cid, token, fyLabel]) => gstr9cItcApi.fyRollup(token, cid, fyLabel),
    {
      revalidateOnFocus: true,
      revalidateOnMount: true,
      dedupingInterval: 5_000,
    }
  );

  if (isLoading && !data) {
    return <PanelSkeleton />;
  }

  if (error) {
    return (
      <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
        Could not load GSTR-9C ITC FY rollup.
      </div>
    );
  }

  if (!data) {
    return <PanelSkeleton />;
  }

  return (
    <div className="space-y-5">
      <div className={`${sectionContainerClass} space-y-4 p-6`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
              GSTR-9C (ITC) — FY Rollup
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-gray-500">
              {data.disclaimer}
            </p>
            {(data.trade_name || data.gstin) && (
              <p className="mt-2 text-sm text-gray-600">
                {data.trade_name ? (
                  <span className="font-semibold text-[var(--ink)]">
                    {data.trade_name}
                  </span>
                ) : null}
                {data.trade_name && data.gstin ? (
                  <span className="text-gray-300"> · </span>
                ) : null}
                {data.gstin ? (
                  <span className="font-mono text-[var(--ink)]">{data.gstin}</span>
                ) : null}
              </p>
            )}
          </div>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
              Financial year
            </span>
            <div className="flex items-center gap-2">
              <select
                className={filterDropdownClass}
                value={fy}
                onChange={(e) => setFy(e.target.value)}
              >
                {options.map((opt) => (
                  <option key={opt} value={opt}>
                    FY {opt}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void mutate()}
                disabled={isValidating}
                className="rounded-full border border-[var(--border)] px-3 py-2 text-xs font-medium text-[var(--ink)] hover:bg-[#F7F7F8] disabled:opacity-50"
              >
                {isValidating ? "Refreshing…" : "Refresh"}
              </button>
            </div>
          </label>
        </div>

        <IncompleteBanner data={data} />

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-[1.25rem] bg-[#F7F7F8] px-5 py-4">
            <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
              Matched ITC (2B runs)
            </p>
            <p className="mt-2 text-xl font-semibold tracking-tight text-[var(--ink)]">
              {moneyCell(data.totals.matched_itc_rupees)}
            </p>
            <p className="mt-1 text-xs text-gray-500">
              Sum across {data.months_with_run} month
              {data.months_with_run === 1 ? "" : "s"} with a recon run
            </p>
          </div>
          <div className="rounded-[1.25rem] bg-[#F7F7F8] px-5 py-4">
            <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
              Claimed ITC (3B uploads)
            </p>
            <p className="mt-2 text-xl font-semibold tracking-tight text-[var(--ink)]">
              {moneyCell(data.totals.claimed_itc_rupees)}
            </p>
            <p className="mt-1 text-xs text-gray-500">
              Sum across months with a GSTR-3B upload
            </p>
          </div>
          <VarianceTotal data={data} />
        </div>
      </div>

      <div className={`${sectionContainerClass} overflow-hidden`}>
        <div className="border-b border-[#F0F0F0] px-6 py-4">
          <h2 className="text-base font-semibold tracking-tight text-[var(--ink)]">
            Monthly breakdown
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Gaps are flagged — missing months are never treated as zero for
            variance. Monthly variance = clean-matched 2B ITC − 3B claimed (not
            all GSTR-2B available).
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-[880px] w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                <th className="px-5 py-4">Month</th>
                <th className="px-4 py-4">Coverage</th>
                <th className="px-4 py-4">Matched ITC (2B)</th>
                <th className="px-4 py-4">Claimed ITC (3B)</th>
                <th className="px-4 py-4">
                  Variance
                  <span className="mt-0.5 block normal-case tracking-normal text-gray-400 font-normal">
                    matched − claimed
                  </span>
                </th>
                <th className="px-5 py-4">Run</th>
              </tr>
            </thead>
            <tbody>
              {data.months.map((row) => (
                <MonthRow key={row.period} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
