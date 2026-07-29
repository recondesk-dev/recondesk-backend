"use client";

import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";
import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

type ReconcileRow = {
  id: string;
  supplier_gstin: string;
  trade_name?: string | null;
  amount: number;
};

type RunSummary = {
  period: string;
  status?: string;
  status_message?: string | null;
  wrongful_risk_count: number;
  wrongful_risk_total_amount: number;
};

type Paginated<T> = {
  data: T[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
};

type SupplierRiskRow = {
  gstin: string;
  tradeName: string;
  count: number;
  total: number;
  impact: "high" | "medium" | "low";
};

type FetcherKey = readonly [path: string, token: string];

function supplierRiskImpactLabel(
  supplierTotal: number,
  grandTotal: number
): "high" | "medium" | "low" {
  if (grandTotal <= 0) return "low";
  if (supplierTotal >= grandTotal * 0.5) return "high";
  if (supplierTotal >= grandTotal * 0.1) return "medium";
  return "low";
}

function aggregateSuppliersByRisk(
  rows: ReconcileRow[],
  grandTotal: number
): SupplierRiskRow[] {
  const m = new Map<
    string,
    { gstin: string; tradeName: string; count: number; total: number }
  >();
  for (const row of rows) {
    const g = row.supplier_gstin?.trim();
    if (!g) continue;
    const cur = m.get(g) ?? {
      gstin: g,
      tradeName: (row.trade_name && String(row.trade_name).trim()) || "",
      count: 0,
      total: 0,
    };
    if (!cur.tradeName && row.trade_name)
      cur.tradeName = String(row.trade_name).trim();
    cur.count += 1;
    cur.total += row.amount;
    m.set(g, cur);
  }
  return Array.from(m.values())
    .sort((a, b) => b.total - a.total)
    .map((s) => ({
      ...s,
      impact: supplierRiskImpactLabel(s.total, grandTotal),
    }));
}

async function authJsonFetcher<T>([path, token]: FetcherKey): Promise<T> {
  return apiFetch<T>(path, { token });
}

async function fetchAllRiskRows([basePath, token]: FetcherKey): Promise<ReconcileRow[]> {
  const qp = "sort=amount_desc";
  const first = await apiFetch<Paginated<ReconcileRow>>(
    `${basePath}?page=1&limit=200&${qp}`,
    { token }
  );
  const rows = [...first.data];
  for (let page = 2; page <= first.total_pages; page++) {
    const next = await apiFetch<Paginated<ReconcileRow>>(
      `${basePath}?page=${page}&limit=200&${qp}`,
      { token }
    );
    rows.push(...next.data);
  }
  return rows;
}

function ImpactSupplierPill({ level }: { level: "high" | "medium" | "low" }) {
  const cls = {
    high: "bg-red-100 text-red-800",
    medium: "bg-amber-100 text-amber-800",
    low: "bg-gray-200 text-gray-600",
  }[level];
  const label = level === "high" ? "High" : level === "medium" ? "Medium" : "Low";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

export default function VendorIntelligencePage() {
  const params = useParams();
  const runId = typeof params.run_id === "string" ? params.run_id : "";

  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const authReady = Boolean(authToken);

  const summaryKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/reconcile/runs/${runId}/summary`, authToken] as const)
        : null,
    [authReady, runId, authToken]
  );

  const {
    data: summary,
    error: summaryError,
    isLoading: summaryLoading,
  } = useSWR<RunSummary>(summaryKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const riskAllKey = useMemo(() => {
    if (!authReady || !runId || !summary || summary.wrongful_risk_count <= 0)
      return null;
    return [`/api/reconcile/runs/${runId}/risk`, authToken] as const;
  }, [authReady, runId, summary, authToken]);

  const {
    data: riskRows,
    error: riskError,
    isLoading: riskLoading,
  } = useSWR<ReconcileRow[]>(riskAllKey, fetchAllRiskRows, {
    revalidateOnFocus: false,
  });

  const suppliers = useMemo(
    () =>
      aggregateSuppliersByRisk(
        riskRows ?? [],
        summary?.wrongful_risk_total_amount ?? 0
      ),
    [riskRows, summary?.wrongful_risk_total_amount]
  );

  if (tokenState === null) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        Loading session…
      </div>
    );
  }

  if (tokenState === false) {
    return (
      <div className="p-8 text-center text-gray-600">
        Sign in required to view vendor intelligence.
      </div>
    );
  }

  if (!runId) {
    return <div className="p-8 text-gray-600">Invalid run.</div>;
  }

  const loading = summaryLoading || (riskAllKey != null && riskLoading && !riskRows);
  const error = summaryError || riskError;
  const isRunFailed = (summary?.status ?? "").toUpperCase() === "FAILED";
  const runFailMsg = summary?.status_message?.trim()
    ? `This run failed: ${summary.status_message.trim()}`
    : "This run failed.";

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <Link
        href={`/reconcile/runs/${runId}/results`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-700 hover:underline"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to results
      </Link>

      <div>
        <h1 className="text-xl font-semibold text-gray-900">
          Top Suppliers by ITC at Risk — Not in GSTR-2B
        </h1>
        {summary?.period && (
          <p className="mt-1 text-sm text-gray-500">Period: {summary.period}</p>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-600">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading supplier data…
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {isRunFailed
            ? runFailMsg
            : "Failed to load vendor intelligence."}
        </div>
      )}

      {isRunFailed && !error && summary && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {runFailMsg}
        </div>
      )}

      {!loading && !error && !isRunFailed && summary && summary.wrongful_risk_count <= 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-600">
          No ITC at Risk — Not in GSTR-2B for this run.
        </div>
      )}

      {!loading && !error && suppliers.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <p className="mb-3 text-sm text-gray-600">
            {suppliers.length.toLocaleString("en-IN")} supplier
            {suppliers.length === 1 ? "" : "s"} ·{" "}
            {formatINR(summary?.wrongful_risk_total_amount ?? 0)} ITC at Risk — Not in
            GSTR-2B
          </p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b bg-gray-50">
                <tr>
                  <th className="sticky left-0 z-10 bg-gray-50 px-3 py-2">
                    Supplier GSTIN
                  </th>
                  <th className="px-3 py-2">Trade Name</th>
                  <th className="px-3 py-2 text-right">Invoice Count</th>
                  <th className="px-3 py-2 text-right">ITC at Risk — Not in GSTR-2B</th>
                  <th className="px-3 py-2">Impact</th>
                </tr>
              </thead>
              <tbody>
                {suppliers.map((s) => (
                  <tr key={s.gstin} className="border-b border-gray-100">
                    <td className="sticky left-0 z-10 bg-white px-3 py-2 font-mono text-xs">
                      {s.gstin}
                    </td>
                    <td className="max-w-[240px] truncate px-3 py-2 text-gray-700">
                      {s.tradeName || "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {s.count.toLocaleString("en-IN")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {formatINR(s.total)}
                    </td>
                    <td className="px-3 py-2">
                      <ImpactSupplierPill level={s.impact} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && !error && summary && summary.wrongful_risk_count > 0 && suppliers.length === 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
          No supplier risk data available.
        </div>
      )}
    </div>
  );
}
