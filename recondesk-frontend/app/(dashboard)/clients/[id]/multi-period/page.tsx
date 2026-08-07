"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Upload,
  Play,
  CloudDownload,
  Calendar,
  Layers,
  ChevronRight,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { useToast } from "@/components/providers/ToastProvider";
import { formatINR } from "@/lib/format";
import {
  createMultiPeriodBatch,
  triggerGstr2bAutofetch,
  uploadManualPr,
  triggerBatchRun,
  getMultiPeriodBatch,
  type MultiPeriodBatch,
  type MultiPeriodBatchItem,
} from "@/lib/multiPeriodApi";

const FY_OPTIONS = ["2025-26", "2024-25", "2023-24"];

function periodMonthName(period: string): string {
  const m = period.slice(5, 7);
  const months: Record<string, string> = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
  };
  return `${months[m] || m} ${period.slice(0, 4)}`;
}

export default function MultiPeriodWizardPage() {
  const params = useParams();
  const router = useRouter();
  const clientId = String(params.id);
  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const tokenLoading = rawToken === null;
  const toast = useToast();

  const [selectedFy, setSelectedFy] = useState("2025-26");
  const [batch, setBatch] = useState<MultiPeriodBatch | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploadingPeriod, setUploadingPeriod] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3>(1);

  // Poll batch status when fetching or running
  useEffect(() => {
    if (!token || !batch?.id) return;
    if (batch.status !== "fetching" && batch.status !== "running") return;

    const interval = setInterval(async () => {
      try {
        const updated = await getMultiPeriodBatch(batch.id, token);
        setBatch(updated);
        if (updated.status === "completed") {
          toast("Annual reconciliation batch completed!", "success");
          router.push(`/clients/${clientId}/multi-period/${updated.id}/summary`);
        }
      } catch (err) {
        console.error("Batch poll failed:", err);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [token, batch?.id, batch?.status, clientId, router, toast]);

  const handleCreateBatch = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const newBatch = await createMultiPeriodBatch(clientId, selectedFy, token);
      setBatch(newBatch);
      setCurrentStep(1);
      toast(`Created multi-period batch for FY ${selectedFy}`, "success");
    } catch (err: any) {
      toast(err?.detail || "Failed to create batch", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleStartAutoFetch = async () => {
    if (!token || !batch) return;
    setLoading(true);
    try {
      await triggerGstr2bAutofetch(batch.id, token);
      const updated = await getMultiPeriodBatch(batch.id, token);
      setBatch(updated);
      toast("Started GSTR-2B auto-fetch for 12 months", "info");
    } catch (err: any) {
      toast(err?.detail || "Failed to start auto-fetch", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (period: string, file: File) => {
    if (!token || !batch) return;
    setUploadingPeriod(period);
    try {
      const updated = await uploadManualPr(batch.id, period, file, token);
      setBatch(updated);
      toast(`Uploaded Purchase Register for ${periodMonthName(period)}`, "success");
    } catch (err: any) {
      toast(err?.detail || "Failed to upload PR file", "error");
    } finally {
      setUploadingPeriod(null);
    }
  };

  const handleRunBatch = async () => {
    if (!token || !batch) return;
    setLoading(true);
    try {
      await triggerBatchRun(batch.id, token);
      const updated = await getMultiPeriodBatch(batch.id, token);
      setBatch(updated);
      setCurrentStep(3);
      toast("Started batch reconciliation across all periods", "info");
    } catch (err: any) {
      toast(err?.detail || "Failed to run batch reconciliation", "error");
    } finally {
      setLoading(false);
    }
  };

  const allPrReady = batch?.items.every(
    (item) => item.pr_source && item.pr_source !== "missing"
  );

  const completedCount = batch?.items.filter((i) => i.status === "completed").length || 0;
  const failedCount = batch?.items.filter((i) => i.status === "failed").length || 0;
  const progressPct = batch?.items.length
    ? Math.round((completedCount / batch.items.length) * 100)
    : 0;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header & Back Link */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href={`/clients/${clientId}`}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-600 transition hover:bg-gray-200"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Annual Multi-Period Reconciliation</h1>
            <p className="text-sm text-gray-500">Reconcile up to 12 tax periods in a single unified flow</p>
          </div>
        </div>

        {batch && (
          <Link
            href={`/clients/${clientId}/multi-period/${batch.id}/summary`}
            className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-gray-200 hover:bg-gray-50"
          >
            View FY Summary <ChevronRight className="h-4 w-4" />
          </Link>
        )}
      </div>

      {/* Step Indicator Bar */}
      <div className="mb-8 rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-100">
        <div className="grid grid-cols-3 gap-4 text-center">
          <div
            onClick={() => setCurrentStep(1)}
            className={`cursor-pointer rounded-lg p-3 transition ${
              currentStep === 1 ? "bg-indigo-50 text-indigo-700 font-semibold" : "text-gray-500 hover:bg-gray-50"
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs text-white">1</span>
              <span>1. GSTR-2B Auto-Fetch</span>
            </div>
          </div>
          <div
            onClick={() => setCurrentStep(2)}
            className={`cursor-pointer rounded-lg p-3 transition ${
              currentStep === 2 ? "bg-indigo-50 text-indigo-700 font-semibold" : "text-gray-500 hover:bg-gray-50"
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs text-white">2</span>
              <span>2. PR Availability & Upload</span>
            </div>
          </div>
          <div
            onClick={() => setCurrentStep(3)}
            className={`cursor-pointer rounded-lg p-3 transition ${
              currentStep === 3 ? "bg-indigo-50 text-indigo-700 font-semibold" : "text-gray-500 hover:bg-gray-50"
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs text-white">3</span>
              <span>3. Batch Run & Progress</span>
            </div>
          </div>
        </div>
      </div>

      {/* Initial FY Batch Creation Card */}
      {!batch && (
        <div className="mb-8 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-gray-200">
          <div className="mx-auto max-w-md text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
              <Layers className="h-6 w-6" />
            </div>
            <h2 className="text-xl font-bold text-gray-900">Start Annual Reconciliation Batch</h2>
            <p className="mt-1 text-sm text-gray-500">
              Select the Financial Year to auto-create 12 period slots (Apr–Mar).
            </p>

            <div className="mt-6 space-y-4">
              <div>
                <label className="block text-left text-xs font-semibold text-gray-700">Financial Year</label>
                <select
                  value={selectedFy}
                  onChange={(e) => setSelectedFy(e.target.value)}
                  className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                >
                  {FY_OPTIONS.map((fy) => (
                    <option key={fy} value={fy}>
                      FY {fy}
                    </option>
                  ))}
                </select>
              </div>

              <button
                onClick={handleCreateBatch}
                disabled={loading || tokenLoading}
                className="w-full inline-flex justify-center items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Create 12-Month Batch
              </button>
            </div>
          </div>
        </div>
      )}

      {batch && (
        <>
          {/* STEP 1: GSTR-2B AUTO FETCH */}
          {currentStep === 1 && (
            <div className="space-y-6">
              <div className="flex items-center justify-between rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">Step 1: GSTR-2B Auto-Fetch (Sandbox API)</h3>
                  <p className="text-sm text-gray-500">
                    Auto-fetch GSTR-2B JSON returns across all 12 months using connected Sandbox GSTN auth.
                  </p>
                </div>
                <button
                  onClick={handleStartAutoFetch}
                  disabled={loading || batch.status === "fetching"}
                  className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
                >
                  {batch.status === "fetching" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Fetching 12 Months...
                    </>
                  ) : (
                    <>
                      <CloudDownload className="h-4 w-4" /> Fetch All 12 Months
                    </>
                  )}
                </button>
              </div>

              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
                {batch.items.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-col justify-between rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-200"
                  >
                    <div>
                      <span className="text-xs font-bold text-gray-400">PERIOD</span>
                      <p className="text-base font-bold text-gray-900">{periodMonthName(item.period)}</p>
                    </div>

                    <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-3">
                      <span className="text-xs font-semibold text-gray-500">GSTR-2B:</span>
                      {item.gstr2b_file_path || item.status === "uploaded" ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700">
                          <CheckCircle2 className="h-3 w-3" /> Ready
                        </span>
                      ) : item.status === "fetching" ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">
                          <Loader2 className="h-3 w-3 animate-spin" /> Fetching
                        </span>
                      ) : item.status === "failed" ? (
                        <div className="flex flex-col items-end gap-1">
                          <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">
                            <AlertCircle className="h-3 w-3" /> Failed
                          </span>
                          {item.error_message && (
                            <span className="text-[10px] text-right font-medium text-red-600 max-w-[140px] leading-tight">
                              {item.error_message}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                          Pending
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex justify-end pt-4">
                <button
                  onClick={() => setCurrentStep(2)}
                  className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500"
                >
                  Proceed to Step 2: PR Check <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* STEP 2: PR AVAILABILITY CHECK & MANUAL FALLBACK */}
          {currentStep === 2 && (
            <div className="space-y-6">
              <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
                <h3 className="text-lg font-bold text-gray-900">Step 2: Purchase Register Availability & Fallback</h3>
                <p className="mt-1 text-sm text-gray-500">
                  Periods with Tally Bridge sync or prior uploads are auto-detected. Upload manual PR files for missing months.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {batch.items.map((item) => {
                  const isReady = item.pr_source && item.pr_source !== "missing";
                  const isUploading = uploadingPeriod === item.period;

                  return (
                    <div
                      key={item.id}
                      className={`flex flex-col justify-between rounded-xl p-5 shadow-sm ring-1 ${
                        isReady ? "bg-white ring-gray-200" : "bg-amber-50/50 ring-amber-200"
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between">
                          <p className="text-base font-bold text-gray-900">{periodMonthName(item.period)}</p>
                          {isReady ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-800">
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              {item.pr_source === "tally_bridge_existing"
                                ? "Tally Sync"
                                : item.pr_source === "already_uploaded"
                                ? "Existing PR"
                                : "Uploaded"}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800">
                              <AlertCircle className="h-3.5 w-3.5" /> Missing PR
                            </span>
                          )}
                        </div>

                        {item.error_message && (
                          <p className="mt-2 text-xs text-red-600">{item.error_message}</p>
                        )}
                      </div>

                      <div className="mt-4 pt-4 border-t border-gray-100">
                        {isReady ? (
                          <p className="text-xs text-gray-500">PR data connected and ready for reconciliation.</p>
                        ) : (
                          <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-700 hover:bg-amber-50">
                            {isUploading ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Upload className="h-4 w-4" />
                            )}
                            Upload PR (.xlsx, .csv)
                            <input
                              type="file"
                              accept=".xlsx,.xls,.csv"
                              className="hidden"
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleFileUpload(item.period, file);
                              }}
                            />
                          </label>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="flex justify-between pt-4">
                <button
                  onClick={() => setCurrentStep(1)}
                  className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-gray-200 hover:bg-gray-50"
                >
                  <ArrowLeft className="h-4 w-4" /> Back to Step 1
                </button>

                <button
                  onClick={handleRunBatch}
                  disabled={loading || batch.status === "running"}
                  className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
                >
                  {batch.status === "running" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Running Batch...
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4" /> Run Batch Reconciliation
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* STEP 3: BATCH RUN PROGRESS & MONITORING */}
          {currentStep === 3 && (
            <div className="space-y-6">
              <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-bold text-gray-900">
                      Step 3: Batch Reconciliation Progress
                    </h3>
                    <p className="text-sm text-gray-500">
                      Sequential chronological reconciliation across FY {batch.financial_year}
                    </p>
                  </div>
                  <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-indigo-700">
                    Status: {batch.status}
                  </span>
                </div>

                {/* Progress Bar */}
                <div className="mt-6">
                  <div className="flex items-center justify-between text-xs font-semibold text-gray-600 mb-1">
                    <span>Overall Batch Progress</span>
                    <span>{progressPct}% ({completedCount}/12 periods completed)</span>
                  </div>
                  <div className="h-3 w-full overflow-hidden rounded-full bg-gray-100">
                    <div
                      className="h-full bg-indigo-600 transition-all duration-500"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Items List */}
              <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
                  <thead className="bg-gray-50 text-xs font-bold uppercase text-gray-500">
                    <tr>
                      <th className="px-6 py-3">Period</th>
                      <th className="px-6 py-3">GSTR-2B</th>
                      <th className="px-6 py-3">Purchase Register</th>
                      <th className="px-6 py-3">Status</th>
                      <th className="px-6 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {batch.items.map((item) => (
                      <tr key={item.id} className="hover:bg-gray-50/50">
                        <td className="px-6 py-4 font-semibold text-gray-900">
                          {periodMonthName(item.period)}
                        </td>
                        <td className="px-6 py-4 text-xs text-gray-600">
                          {item.gstr2b_file_path ? "Ready (R2)" : "Missing"}
                        </td>
                        <td className="px-6 py-4 text-xs text-gray-600">
                          {item.pr_source || "Missing"}
                        </td>
                        <td className="px-6 py-4">
                          {item.status === "completed" ? (
                            <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-semibold text-green-700">
                              <CheckCircle2 className="h-3.5 w-3.5" /> Completed
                            </span>
                          ) : item.status === "running" ? (
                            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Running
                            </span>
                          ) : item.status === "failed" ? (
                            <div className="flex flex-col gap-0.5">
                              <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-700 w-fit">
                                <AlertCircle className="h-3.5 w-3.5" /> Failed
                              </span>
                              {item.error_message && (
                                <span className="text-[11px] font-medium text-red-600">
                                  {item.error_message}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
                              Pending
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-right">
                          {item.reconciliation_run_id && (
                            <Link
                              href={`/reconcile/runs/${item.reconciliation_run_id}/results`}
                              className="text-xs font-semibold text-indigo-600 hover:text-indigo-900"
                            >
                              View Results →
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
