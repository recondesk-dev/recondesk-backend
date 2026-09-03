"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  Layers,
  ExternalLink,
  Download,
  Loader2,
  Check,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { formatINR } from "@/lib/format";
import { downloadBlobAsFile } from "@/lib/download";
import { getBatchSummary, downloadBatchExcelExport, type MultiPeriodBatch } from "@/lib/multiPeriodApi";

function periodMonthName(period: string): string {
  const m = period.slice(5, 7);
  const months: Record<string, string> = {
    "01": "Jan",
    "02": "Feb",
    "03": "Mar",
    "04": "Apr",
    "05": "May",
    "06": "Jun",
    "07": "Jul",
    "08": "Aug",
    "09": "Sep",
    "10": "Oct",
    "11": "Nov",
    "12": "Dec",
  };
  return `${months[m] || m} ${period.slice(0, 4)}`;
}

export default function MultiPeriodSummaryPage() {
  const params = useParams();
  const clientId = String(params.id);
  const batchId = String(params.batch_id);

  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const [batch, setBatch] = useState<MultiPeriodBatch | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!token || !batchId) return;

    getBatchSummary(batchId, token)
      .then((data) => setBatch(data))
      .catch((err) => console.error("Failed to load batch summary:", err))
      .finally(() => setLoading(false));
  }, [token, batchId]);

  const handleExportExcel = async () => {
    if (!token || !batchId) return;
    setExporting(true);
    try {
      const blob = await downloadBatchExcelExport(batchId, token);
      const fy = batch?.financial_year || "FY";
      downloadBlobAsFile(blob, `recondesk_annual_recon_${fy}_${batchId.slice(0, 8)}.xlsx`);
    } catch (err) {
      console.error("Failed to export Excel workbook:", err);
    } finally {
      setExporting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-96 flex-col items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400 mb-3" />
        <p className="text-sm font-medium text-gray-500">Loading FY reconciliation summary...</p>
      </div>
    );
  }

  const summary = batch?.summary || {};
  const totalMatchedRupees = (summary.matched_itc_paise || 0) / 100;
  const totalMissedRupees = (summary.missed_itc_paise || 0) / 100;
  const totalRiskRupees = (summary.wrongful_risk_paise || 0) / 100;
  const totalGstrRupees = (summary.total_gstr_itc_paise || 0) / 100;

  return (
    <div className="mx-auto max-w-6xl px-4 py-4 space-y-6 sm:px-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Link
            href={`/clients/${clientId}/multi-period`}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-white border border-gray-200 text-gray-600 transition hover:bg-gray-50 hover:text-black shadow-sm"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-[var(--ink)] sm:text-2xl">
                FY {batch?.financial_year} Annual Reconciliation Rollup
              </h1>
              <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                12-Period Audit
              </span>
            </div>
            <p className="text-xs text-gray-500 sm:text-sm">
              Aggregated ITC summary and sequential period breakdown
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={handleExportExcel}
          disabled={exporting}
          className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-black disabled:opacity-50"
        >
          {exporting ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Exporting...</span>
            </>
          ) : (
            <>
              <Download className="h-3.5 w-3.5" />
              <span>Export FY Workbook (Excel)</span>
            </>
          )}
        </button>
      </div>

      {/* Overview Stat Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-5 shadow-[var(--shadow-soft)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">
              Total 2B Available ITC
            </span>
            <FileSpreadsheet className="h-4 w-4 text-gray-400" />
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight text-[var(--ink)]">
            {formatINR(totalGstrRupees)}
          </p>
        </div>

        <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-5 shadow-[var(--shadow-soft)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
              Total Matched ITC
            </span>
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight text-emerald-700">
            {formatINR(totalMatchedRupees)}
          </p>
        </div>

        <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-5 shadow-[var(--shadow-soft)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-amber-700">
              Total Missed ITC
            </span>
            <AlertTriangle className="h-4 w-4 text-amber-600" />
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight text-amber-700">
            {formatINR(totalMissedRupees)}
          </p>
        </div>

        <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-5 shadow-[var(--shadow-soft)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-red-700">
              ITC at Risk (Not in 2B)
            </span>
            <AlertTriangle className="h-4 w-4 text-red-600" />
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight text-red-700">
            {formatINR(totalRiskRupees)}
          </p>
        </div>
      </div>

      {/* 12-Month Period Breakdown Table */}
      <div className="rounded-[1.25rem] border border-gray-200/80 bg-white shadow-[var(--shadow-soft)] overflow-hidden">
        <div className="border-b border-gray-100 bg-[#F8FAFC] px-6 py-4">
          <h2 className="text-sm font-bold text-[var(--ink)] sm:text-base">
            Monthly Period Breakdown & Single-Run Results
          </h2>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100 text-left text-xs sm:text-sm">
            <thead className="bg-[#F8FAFC] text-[11px] font-bold uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-6 py-3.5">Period</th>
                <th className="px-6 py-3.5">GSTR-2B Source</th>
                <th className="px-6 py-3.5">PR Source</th>
                <th className="px-6 py-3.5">Batch Item Status</th>
                <th className="px-6 py-3.5 text-right">Single-Run Results</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {batch?.items.map((item) => (
                <tr key={item.id} className="hover:bg-gray-50/50 transition-colors">
                  <td className="px-6 py-4 font-semibold text-[var(--ink)]">
                    {periodMonthName(item.period)}
                  </td>
                  <td className="px-6 py-4 text-xs text-gray-600">
                    {item.gstr2b_source === "auto_fetch" ? (
                      <span className="font-medium text-gray-800">Auto-Fetch (Sandbox)</span>
                    ) : (
                      item.gstr2b_source || "—"
                    )}
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
                            ? "bg-emerald-50 text-emerald-700"
                            : item.status === "failed"
                            ? "bg-red-50 text-red-700"
                            : "bg-gray-100 text-gray-700"
                        }`}
                      >
                        {item.status}
                      </span>
                      {item.status === "failed" && item.error_message && (
                        <span className="text-[11px] text-red-600">
                          {item.error_message}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right">
                    {item.reconciliation_run_id ? (
                      <Link
                        href={`/reconcile/runs/${item.reconciliation_run_id}/results`}
                        className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--ink)] hover:underline"
                      >
                        <span>View Results</span>
                        <ExternalLink className="h-3 w-3" />
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
    </div>
  );
}
