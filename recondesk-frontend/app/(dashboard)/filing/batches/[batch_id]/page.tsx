"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ArrowLeft, AlertCircle, CheckCircle2, Clock, ExternalLink, KeyRound, Loader2, RefreshCw, Send } from "lucide-react";
import useSWR from "swr";

import {
  SectionHeader,
  pageContentClass,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import {
  filingApi,
  isApiError,
  type FilingBatch,
  type FilingBatchItem,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function BatchDetailPageContent() {
  const params = useParams();
  const batchId = String(params.batch_id || "");
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const [otpPanMap, setOtpPanMap] = useState<Record<string, { pan: string; otp: string }>>({});
  const [activeOtpItemId, setActiveOtpItemId] = useState<string | null>(null);
  const [otpSending, setOtpSending] = useState<Record<string, boolean>>({});
  const [fileSubmitting, setFileSubmitting] = useState<Record<string, boolean>>({});
  const [actionError, setActionError] = useState<string | null>(null);

  const batchKey = token && batchId ? (["filing-batch-detail", batchId, token] as const) : null;
  const { data: batch, mutate: mutateBatch, isLoading } = useSWR(
    batchKey,
    ([, id, t]) => filingApi.getBatch(t, id),
    { refreshInterval: 4000 }
  );

  const handleRetryBatch = async () => {
    if (!token || !batchId) return;
    try {
      await filingApi.retryBatch(token, batchId);
      mutateBatch();
    } catch (err) {
      setActionError(isApiError(err) ? err.detail : "Retry failed");
    }
  };

  const handleSendEvcOtp = async (item: FilingBatchItem, pan: string) => {
    if (!token || !pan.trim() || !batch) return;
    setOtpSending((prev) => ({ ...prev, [item.id]: true }));
    setActionError(null);
    try {
      await filingApi.evcOtp(token, batch.period, {
        pan: pan.trim().toUpperCase(),
        run_id: item.filing_run_id || undefined,
      });
      alert(`EVC OTP sent to Authorized Signatory for ${item.gstin}`);
    } catch (err) {
      setActionError(isApiError(err) ? err.detail : "Failed to generate EVC OTP");
    } finally {
      setOtpSending((prev) => ({ ...prev, [item.id]: false }));
    }
  };

  const handleFileGstr1 = async (item: FilingBatchItem) => {
    if (!token || !batch) return;
    const entry = otpPanMap[item.id];
    if (!entry || !entry.pan.trim() || !entry.otp.trim()) {
      setActionError("Please enter both Authorized Signatory PAN and 6-digit EVC OTP.");
      return;
    }
    setFileSubmitting((prev) => ({ ...prev, [item.id]: true }));
    setActionError(null);
    try {
      await filingApi.file(token, batch.period, {
        pan: entry.pan.trim().toUpperCase(),
        otp: entry.otp.trim(),
        run_id: item.filing_run_id || undefined,
      });
      setActiveOtpItemId(null);
      mutateBatch();
    } catch (err) {
      setActionError(isApiError(err) ? err.detail : "Filing failed");
    } finally {
      setFileSubmitting((prev) => ({ ...prev, [item.id]: false }));
    }
  };

  if (tokenState === null || isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading batch details…
      </div>
    );
  }

  if (!batch) {
    return (
      <div className="mx-auto max-w-lg px-8 py-16 text-center">
        <h1 className="text-xl font-semibold text-[var(--ink)]">Batch not found</h1>
        <Link
          href="/filing/batches"
          className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-5 py-2 text-xs font-semibold text-white"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Return to Batches
        </Link>
      </div>
    );
  }

  const items = batch.items || [];

  return (
    <div className={pageContentClass}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href="/filing/batches"
            className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-white text-gray-500 shadow-sm hover:text-[var(--ink)]"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
              Batch: Period {batch.period}
            </h1>
            <p className="text-xs text-gray-500 font-mono">
              ID: {batch.id} · GSTR-1 Bulk Filing
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => mutateBatch()}
            className="inline-flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-[13px] font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh Status
          </button>

          {(batch.failed_count > 0 || batch.status === "in_progress") ? (
            <button
              type="button"
              onClick={handleRetryBatch}
              className="inline-flex items-center gap-1.5 rounded-full bg-amber-600 px-4 py-2 text-[13px] font-semibold text-white shadow hover:bg-amber-700"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Retry Failed Items
            </button>
          ) : null}
        </div>
      </div>

      {actionError ? (
        <div className="mb-4 rounded-xl bg-red-50 p-3 text-xs text-red-600 border border-red-100 flex items-center justify-between">
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} className="text-red-400 font-bold">✕</button>
        </div>
      ) : null}

      {/* Summary Cards */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">Total GSTINs</div>
          <div className="mt-1 text-2xl font-bold text-[var(--ink)]">{batch.total_count}</div>
        </div>
        <div className="rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-600">Saved</div>
          <div className="mt-1 text-2xl font-bold text-emerald-600">{batch.saved_count || 0}</div>
        </div>
        <div className="rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-purple-600">EVC Pending</div>
          <div className="mt-1 text-2xl font-bold text-purple-600">{batch.evc_pending_count || 0}</div>
        </div>
        <div className="rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-blue-600">Filed</div>
          <div className="mt-1 text-2xl font-bold text-blue-600">{batch.filed_count || 0}</div>
        </div>
        <div className="rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-600">Needs Review</div>
          <div className="mt-1 text-2xl font-bold text-amber-600">{batch.needs_review_count || 0}</div>
        </div>
        <div className="rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-red-600">Failed</div>
          <div className="mt-1 text-2xl font-bold text-red-600">{batch.failed_count || 0}</div>
        </div>
      </div>

      {/* Multi-GSTIN Item Status Table */}
      <section className={sectionContainerClass}>
        <SectionHeader title="GSTIN Batch Progress & Review Queue" dotColor="#111111" />

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="border-b border-gray-100 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                <th className="pb-3 pl-2">Client / GSTIN</th>
                <th className="pb-3">Status</th>
                <th className="pb-3">Run ID</th>
                <th className="pb-3">Notes / Error Detail</th>
                <th className="pb-3 pr-2 text-right">Action / Entry Point</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 font-medium">
              {items.map((item: FilingBatchItem) => {
                const clientName = item.client_gstins?.trade_name || item.client_gstins?.legal_name || "Client";
                const isOtpActive = activeOtpItemId === item.id;
                const otpForm = otpPanMap[item.id] || { pan: item.gstin.slice(2, 12), otp: "" };

                return (
                  <tr key={item.id} className="hover:bg-gray-50/50">
                    <td className="py-3.5 pl-2">
                      <div className="font-semibold text-[var(--ink)]">{clientName}</div>
                      <div className="text-[11px] font-mono text-gray-400">{item.gstin}</div>
                    </td>
                    <td className="py-3.5">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ${
                          item.status === "filed"
                            ? "bg-blue-50 text-blue-700"
                            : item.status === "evc_pending"
                            ? "bg-purple-50 text-purple-700"
                            : item.status === "saved" || item.status === "proceeded"
                            ? "bg-emerald-50 text-emerald-700"
                            : item.status === "needs_review"
                            ? "bg-amber-50 text-amber-700 font-bold"
                            : item.status === "in_progress" || item.status === "pending"
                            ? "bg-gray-100 text-gray-700"
                            : "bg-red-50 text-red-700"
                        }`}
                      >
                        {item.status === "in_progress" || item.status === "pending" ? (
                          <Clock className="h-3 w-3 animate-pulse" />
                        ) : item.status === "evc_pending" ? (
                          <KeyRound className="h-3 w-3" />
                        ) : item.status === "filed" ? (
                          <CheckCircle2 className="h-3 w-3" />
                        ) : item.status === "needs_review" || item.status === "failed" ? (
                          <AlertCircle className="h-3 w-3" />
                        ) : null}
                        {item.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="py-3.5 font-mono text-[11px] text-gray-400">
                      {item.filing_run_id ? item.filing_run_id.slice(0, 8) + "…" : "—"}
                    </td>
                    <td className="py-3.5 max-w-xs truncate text-[12px] text-gray-500">
                      {item.error_detail || (item.status === "evc_pending" ? "Proceeded to file. Pending EVC OTP." : "—")}
                    </td>
                    <td className="py-3.5 pr-2 text-right">
                      {item.status === "needs_review" ? (
                        <Link
                          href={`/filing/gstr-1/${batch.period}?client_gstin_id=${item.client_gstin_id}`}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--ink)] underline hover:opacity-80"
                        >
                          Review Mismatches <ExternalLink className="h-3 w-3" />
                        </Link>
                      ) : item.status === "evc_pending" || item.status === "saved" || item.status === "proceeded" ? (
                        <div>
                          {!isOtpActive ? (
                            <button
                              type="button"
                              onClick={() => setActiveOtpItemId(item.id)}
                              className="inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:opacity-90"
                            >
                              <KeyRound className="h-3.5 w-3.5" /> Submit EVC OTP
                            </button>
                          ) : (
                            <div className="inline-block bg-gray-50 p-3 rounded-xl border text-left space-y-2 w-72">
                              <div className="text-[11px] font-semibold text-gray-700">Submit EVC OTP for {item.gstin}</div>
                              <div className="grid grid-cols-2 gap-2">
                                <div>
                                  <label className="text-[10px] text-gray-400 uppercase font-semibold">PAN</label>
                                  <input
                                    type="text"
                                    maxLength={10}
                                    value={otpForm.pan}
                                    onChange={(e) =>
                                      setOtpPanMap({
                                        ...otpPanMap,
                                        [item.id]: { ...otpForm, pan: e.target.value.toUpperCase() },
                                      })
                                    }
                                    className="w-full h-8 px-2 text-xs rounded border uppercase font-mono"
                                  />
                                </div>
                                <div>
                                  <label className="text-[10px] text-gray-400 uppercase font-semibold">EVC OTP</label>
                                  <input
                                    type="text"
                                    maxLength={6}
                                    placeholder="123456"
                                    value={otpForm.otp}
                                    onChange={(e) =>
                                      setOtpPanMap({
                                        ...otpPanMap,
                                        [item.id]: { ...otpForm, otp: e.target.value },
                                      })
                                    }
                                    className="w-full h-8 px-2 text-xs rounded border font-mono"
                                  />
                                </div>
                              </div>

                              <div className="flex items-center justify-between pt-1">
                                <button
                                  type="button"
                                  disabled={otpSending[item.id]}
                                  onClick={() => handleSendEvcOtp(item, otpForm.pan)}
                                  className="text-[11px] text-purple-700 font-semibold underline hover:opacity-80"
                                >
                                  {otpSending[item.id] ? "Sending…" : "Resend OTP"}
                                </button>

                                <div className="flex items-center gap-1">
                                  <button
                                    type="button"
                                    onClick={() => setActiveOtpItemId(null)}
                                    className="px-2 py-1 text-[11px] font-semibold text-gray-500 hover:bg-gray-200 rounded"
                                  >
                                    Cancel
                                  </button>
                                  <button
                                    type="button"
                                    disabled={fileSubmitting[item.id]}
                                    onClick={() => handleFileGstr1(item)}
                                    className="inline-flex items-center gap-1 px-3 py-1 bg-emerald-600 text-white rounded text-[11px] font-semibold hover:bg-emerald-700 disabled:opacity-40"
                                  >
                                    {fileSubmitting[item.id] ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />} File
                                  </button>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      ) : item.status === "filed" ? (
                        <span className="text-xs font-semibold text-emerald-600">Filed Successfully ✓</span>
                      ) : (
                        <Link
                          href={`/filing/gstr-1/${batch.period}?client_gstin_id=${item.client_gstin_id}`}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-gray-500 hover:text-[var(--ink)]"
                        >
                          Manual Retry <ExternalLink className="h-3 w-3" />
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default function BatchDetailPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-xs text-gray-400">Loading batch…</div>}>
      <BatchDetailPageContent />
    </Suspense>
  );
}
