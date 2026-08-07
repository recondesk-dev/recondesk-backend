"use client";

import Link from "next/link";
import { useParams } from "react";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  TrendingUp,
  Layers,
  ExternalLink,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { formatINR } from "@/lib/format";
import { getBatchSummary, type MultiPeriodBatch } from "@/lib/multiPeriodApi";

function periodMonthName(period: string): string {
  const m = period.slice(5, 7);
  const months: Record<string, string> = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
  };
  return `${months[m] || m} ${period.slice(0, 4)}`;
}

export default function MultiPeriodSummaryPage() {
  const params = useParams();
  const clientId = String(params.id);
  const batchId = String(params.batch_id);

  const { token } = useAccessToken();
  const [batch, setBatch] = useState<MultiPeriodBatch | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token || !batchId) return;

    getBatchSummary(batchId, token)
      .then((data) => setBatch(data))
      .catch((err) => console.error("Failed to load batch summary:", err))
      .finally(() => setLoading(false));
  }, [token, batchId]);

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  const summary = batch?.summary || {};
  const totalMatchedRupees = (summary.matched_itc_paise || 0) / 100;
  const totalMissedRupees = (summary.missed_itc_paise || 0) / 100;
  const totalRiskRupees = (summary.wrongful_risk_paise || 0) / 100;
  const totalGstrRupees = (summary.total_gstr_itc_paise || 0) / 100;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href={`/clients/${clientId}/multi-period`}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-600 transition hover:bg-gray-200"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              FY {batch?.financial_year} Annual Reconciliation Rollup
            </h1>
            <p className="text-sm text-gray-500">
              Aggregated ITC summary across 12 periods for client
            </p>
          </div>
        </div>
      </div>

      {/* Overview Stat Cards */}
      <div className="mb-8 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-gray-500">
              Total 2B Available ITC
            </span>
            <FileSpreadsheet className="h-5 w-5 text-indigo-600" />
          </div>
          <p className="mt-3 text-2xl font-bold text-gray-900">
            {formatINR(totalGstrRupees)}
          </p>
        </div>

        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-green-700">
              Total Matched ITC
            </span>
            <CheckCircle2 className="h-5 w-5 text-green-600" />
          </div>
          <p className="mt-3 text-2xl font-bold text-green-700">
            {formatINR(totalMatchedRupees)}
          </p>
        </div>

        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-amber-700">
              Total Missed ITC
            </span>
            <AlertTriangle className="h-5 w-5 text-amber-600" />
          </div>
          <p className="mt-3 text-2xl font-bold text-amber-700">
            {formatINR(totalMissedRupees)}
          </p>
        </div>

        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-red-700">
              ITC at Risk (Not in 2B)
            </span>
            <AlertTriangle className="h-5 w-5 text-red-600" />
          </div>
          <p className="mt-3 text-2xl font-bold text-red-700">
            {formatINR(totalRiskRupees)}
          </p>
        </div>
      </div>

      {/* 12-Month Period Breakdown Table */}
      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
        <div className="border-b border-gray-200 bg-gray-50 px-6 py-4">
          <h2 className="text-base font-bold text-gray-900">
            Monthly Period Breakdown & Single-Run Results
          </h2>
        </div>

        <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
          <thead className="bg-gray-50 text-xs font-bold uppercase text-gray-500">
            <tr>
              <th className="px-6 py-3">Period</th>
              <th className="px-6 py-3">GSTR-2B Source</th>
              <th className="px-6 py-3">PR Source</th>
              <th className="px-6 py-3">Batch Item Status</th>
              <th className="px-6 py-3 text-right">Single-Run Results</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 bg-white">
            {batch?.items.map((item) => (
              <tr key={item.id} className="hover:bg-gray-50/50">
                <td className="px-6 py-4 font-semibold text-gray-900">
                  {periodMonthName(item.period)}
                </td>
                <td className="px-6 py-4 text-xs text-gray-600">
                  {item.gstr2b_source === "auto_fetch" ? "Auto-Fetch (Sandbox)" : item.gstr2b_source || "—"}
                </td>
                <td className="px-6 py-4 text-xs text-gray-600">
                  {item.pr_source === "tally_bridge_existing"
                    ? "Tally Sync"
                    : item.pr_source === "manual_upload"
                    ? "Manual Upload"
                    : item.pr_source || "—"}
                </td>
                <td className="px-6 py-4">
                  <div className="flex flex-col gap-0.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold w-fit ${
                        item.status === "completed"
                          ? "bg-green-50 text-green-700"
                          : item.status === "failed"
                          ? "bg-red-50 text-red-700"
                          : "bg-gray-100 text-gray-700"
                      }`}
                    >
                      {item.status}
                    </span>
                    {item.status === "failed" && item.error_message && (
                      <span className="text-[11px] font-medium text-red-600">
                        {item.error_message}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4 text-right">
                  {item.reconciliation_run_id ? (
                    <Link
                      href={`/reconcile/runs/${item.reconciliation_run_id}/results`}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-900"
                    >
                      View Results <ExternalLink className="h-3 w-3" />
                    </Link>
                  ) : (
                    <span className="text-xs text-gray-400">Not run</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
