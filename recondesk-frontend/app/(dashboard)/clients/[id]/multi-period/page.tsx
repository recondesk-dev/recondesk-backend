"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
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
  Download,
  Plus,
  RefreshCw,
  FileSpreadsheet,
  Check,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { useToast } from "@/components/providers/ToastProvider";
import { formatINR } from "@/lib/format";
import { downloadBlobAsFile } from "@/lib/download";
import {
  createMultiPeriodBatch,
  triggerGstr2bAutofetch,
  uploadManualPr,
  triggerBatchRun,
  getMultiPeriodBatch,
  listMultiPeriodBatches,
  downloadBatchExcelExport,
  type MultiPeriodBatch,
  type MultiPeriodBatchItem,
} from "@/lib/multiPeriodApi";

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

export default function MultiPeriodWizardPage() {
  const params = useParams();
  const router = useRouter();
  const clientId = String(params.id);
  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const tokenLoading = rawToken === null;
  const toast = useToast();

  const availableFys = useMemo(() => fyOptions(), []);
  const [selectedFy, setSelectedFy] = useState(availableFys[0] || "2025-26");

  const [batches, setBatches] = useState<MultiPeriodBatch[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(true);
  const [batch, setBatch] = useState<MultiPeriodBatch | null>(null);
  const [isCreatingNew, setIsCreatingNew] = useState(false);

  const [loading, setLoading] = useState(false);
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [uploadingPeriod, setUploadingPeriod] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3>(1);

  // Load existing batches for this client on mount
  const loadClientBatches = useCallback(async () => {
    if (!token || !clientId) return;
    try {
      setBatchesLoading(true);
      const res = await listMultiPeriodBatches(clientId, token);
      const batchList = res?.batches || [];
      setBatches(batchList);

      if (batchList.length > 0) {
        // Look for any active batch first, else select the newest one
        const activeBatch = batchList.find(
          (b) => b.status === "fetching" || b.status === "running" || b.status === "pending"
        );
        const targetBatch = activeBatch || batchList[0];
        
        // Fetch full batch with item details
        const fullBatch = await getMultiPeriodBatch(targetBatch.id, token);
        setBatch(fullBatch);

        // Determine appropriate step based on progress
        const all2BReady = fullBatch.items.every(
          (i) => Boolean(i.gstr2b_file_path) || i.status === "uploaded"
        );
        const allPrReady = fullBatch.items.every(
          (i) => i.pr_source && i.pr_source !== "missing"
        );

        if (fullBatch.status === "running" || fullBatch.status === "completed") {
          setCurrentStep(3);
        } else if (all2BReady && !allPrReady) {
          setCurrentStep(2);
        } else if (all2BReady && allPrReady) {
          setCurrentStep(3);
        } else {
          setCurrentStep(1);
        }
      } else {
        setBatch(null);
        setIsCreatingNew(true);
      }
    } catch (err) {
      console.error("Failed to load client batches:", err);
    } finally {
      setBatchesLoading(false);
    }
  }, [token, clientId]);

  useEffect(() => {
    loadClientBatches();
  }, [loadClientBatches]);

  // Poll batch status when actively fetching or running
  useEffect(() => {
    if (!token || !batch?.id) return;
    if (batch.status !== "fetching" && batch.status !== "running") return;

    const interval = setInterval(async () => {
      try {
        const updated = await getMultiPeriodBatch(batch.id, token);
        setBatch(updated);
        setBatches((prev) =>
          prev.map((b) => (b.id === updated.id ? { ...b, ...updated } : b))
        );

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

  const handleSelectBatch = async (targetBatchId: string) => {
    if (!token) return;
    setLoading(true);
    try {
      const fullBatch = await getMultiPeriodBatch(targetBatchId, token);
      setBatch(fullBatch);
      setIsCreatingNew(false);
      if (fullBatch.status === "running" || fullBatch.status === "completed") {
        setCurrentStep(3);
      } else {
        setCurrentStep(1);
      }
    } catch (err: any) {
      toast(err?.detail || "Failed to load batch", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateBatch = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const newBatch = await createMultiPeriodBatch(clientId, selectedFy, token);
      setBatch(newBatch);
      setBatches((prev) => [newBatch, ...prev]);
      setIsCreatingNew(false);
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
      setBatches((prev) =>
        prev.map((b) => (b.id === updated.id ? { ...b, ...updated } : b))
      );
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
      setBatches((prev) =>
        prev.map((b) => (b.id === updated.id ? { ...b, ...updated } : b))
      );
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
      setBatches((prev) =>
        prev.map((b) => (b.id === updated.id ? { ...b, ...updated } : b))
      );
      setCurrentStep(3);
      toast("Started batch reconciliation across all periods", "info");
    } catch (err: any) {
      toast(err?.detail || "Failed to run batch reconciliation", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleExportExcel = async (batchId: string, fy: string) => {
    if (!token) return;
    setExportingId(batchId);
    try {
      const blob = await downloadBatchExcelExport(batchId, token);
      downloadBlobAsFile(blob, `recondesk_annual_recon_${fy}_${batchId.slice(0, 8)}.xlsx`);
      toast("Annual workbook downloaded successfully", "success");
    } catch (err) {
      toast("Failed to download Excel export", "error");
    } finally {
      setExportingId(null);
    }
  };

  // Step readiness calculations
  const all2bReady = useMemo(() => {
    if (!batch?.items?.length) return false;
    return batch.items.every(
      (i) => Boolean(i.gstr2b_file_path) || i.status === "uploaded" || i.status === "completed"
    );
  }, [batch?.items]);

  const allPrReady = useMemo(() => {
    if (!batch?.items?.length) return false;
    return batch.items.every(
      (item) => item.pr_source && item.pr_source !== "missing"
    );
  }, [batch?.items]);

  const completedCount = batch?.items.filter((i) => i.status === "completed").length || 0;
  const progressPct = batch?.items.length
    ? Math.round((completedCount / batch.items.length) * 100)
    : 0;

  if (batchesLoading) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12 flex flex-col items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400 mb-3" />
        <p className="text-sm font-medium text-gray-500">Loading Annual Reconciliation workspace...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-4 space-y-6 sm:px-6">
      {/* Header & Back Link */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Link
            href={`/clients/${clientId}`}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-white border border-gray-200 text-gray-600 transition hover:bg-gray-50 hover:text-black shadow-sm"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-[var(--ink)] sm:text-2xl">
                Annual Multi-Period Reconciliation
              </h1>
              {batch && !isCreatingNew && (
                <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-semibold text-gray-800">
                  FY {batch.financial_year}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 sm:text-sm">
              Reconcile up to 12 tax periods in a unified sequential audit flow
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {batch && !isCreatingNew && (
            <>
              <button
                type="button"
                onClick={() => handleExportExcel(batch.id, batch.financial_year)}
                disabled={exportingId === batch.id}
                className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3.5 py-2 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 hover:text-black disabled:opacity-50"
              >
                {exportingId === batch.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Export Excel
              </button>

              <Link
                href={`/clients/${clientId}/multi-period/${batch.id}/summary`}
                className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3.5 py-2 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 hover:text-black"
              >
                <span>View FY Rollup</span>
                <ChevronRight className="h-3.5 w-3.5" />
              </Link>
            </>
          )}

          {!isCreatingNew && batches.length > 0 && (
            <button
              onClick={() => setIsCreatingNew(true)}
              className="inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-black"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>New Annual Batch</span>
            </button>
          )}

          {isCreatingNew && batches.length > 0 && (
            <button
              onClick={() => setIsCreatingNew(false)}
              className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3.5 py-2 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50"
            >
              <span>Back to Current Batch</span>
            </button>
          )}
        </div>
      </div>

      {/* NEW BATCH CREATION CARD */}
      {(isCreatingNew || !batch) && (
        <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-6 shadow-[var(--shadow-soft)] sm:p-8">
          <div className="mx-auto max-w-md text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gray-100 text-gray-800">
              <Layers className="h-6 w-6" />
            </div>
            <h2 className="text-lg font-bold text-[var(--ink)] sm:text-xl">
              Start Annual Reconciliation Batch
            </h2>
            <p className="mt-1.5 text-xs text-gray-500 sm:text-sm">
              Select the Financial Year to auto-create 12 period slots (Apr–Mar).
            </p>

            <div className="mt-6 space-y-4">
              <div className="text-left">
                <label className="block text-xs font-semibold uppercase tracking-wider text-gray-600">
                  Financial Year
                </label>
                <select
                  value={selectedFy}
                  onChange={(e) => setSelectedFy(e.target.value)}
                  className="mt-1.5 block w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm font-medium text-gray-900 shadow-sm focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                >
                  {availableFys.map((fy) => (
                    <option key={fy} value={fy}>
                      FY {fy}
                    </option>
                  ))}
                </select>
              </div>

              <button
                onClick={handleCreateBatch}
                disabled={loading || tokenLoading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--ink)] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-black disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4 fill-current" />
                )}
                Create 12-Month Batch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ACTIVE BATCH WIZARD WORKSPACE */}
      {batch && !isCreatingNew && (
        <div className="space-y-6">
          {/* Step Indicator Bar */}
          <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-2.5 shadow-[var(--shadow-soft)]">
            <div className="grid grid-cols-3 gap-2 text-center text-xs font-semibold sm:text-sm">
              {/* STEP 1 TAB */}
              <button
                type="button"
                onClick={() => setCurrentStep(1)}
                className={`flex items-center justify-center gap-2 rounded-xl py-2.5 px-3 transition-all ${
                  currentStep === 1
                    ? "bg-gray-100 text-[var(--ink)] font-bold shadow-xs"
                    : "text-gray-500 hover:bg-gray-50 hover:text-gray-800"
                }`}
              >
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${
                    all2bReady
                      ? "bg-emerald-600 text-white"
                      : currentStep === 1
                      ? "bg-[var(--ink)] text-white"
                      : "bg-gray-200 text-gray-600"
                  }`}
                >
                  {all2bReady ? <Check className="h-3 w-3 stroke-[3]" /> : "1"}
                </span>
                <span className="truncate">1. GSTR-2B Auto-Fetch</span>
              </button>

              {/* STEP 2 TAB */}
              <button
                type="button"
                onClick={() => setCurrentStep(2)}
                className={`flex items-center justify-center gap-2 rounded-xl py-2.5 px-3 transition-all ${
                  currentStep === 2
                    ? "bg-gray-100 text-[var(--ink)] font-bold shadow-xs"
                    : "text-gray-500 hover:bg-gray-50 hover:text-gray-800"
                }`}
              >
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${
                    allPrReady
                      ? "bg-emerald-600 text-white"
                      : currentStep === 2
                      ? "bg-[var(--ink)] text-white"
                      : "bg-gray-200 text-gray-600"
                  }`}
                >
                  {allPrReady ? <Check className="h-3 w-3 stroke-[3]" /> : "2"}
                </span>
                <span className="truncate">2. PR Availability & Upload</span>
              </button>

              {/* STEP 3 TAB */}
              <button
                type="button"
                onClick={() => setCurrentStep(3)}
                className={`flex items-center justify-center gap-2 rounded-xl py-2.5 px-3 transition-all ${
                  currentStep === 3
                    ? "bg-gray-100 text-[var(--ink)] font-bold shadow-xs"
                    : "text-gray-500 hover:bg-gray-50 hover:text-gray-800"
                }`}
              >
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${
                    batch.status === "completed"
                      ? "bg-emerald-600 text-white"
                      : currentStep === 3
                      ? "bg-[var(--ink)] text-white"
                      : "bg-gray-200 text-gray-600"
                  }`}
                >
                  {batch.status === "completed" ? (
                    <Check className="h-3 w-3 stroke-[3]" />
                  ) : (
                    "3"
                  )}
                </span>
                <span className="truncate">3. Batch Run & Progress</span>
              </button>
            </div>
          </div>

          {/* STEP 1 CONTENT: GSTR-2B AUTO FETCH */}
          {currentStep === 1 && (
            <div className="space-y-6">
              <div className="flex flex-col gap-4 rounded-[1.25rem] border border-gray-200/80 bg-white p-6 shadow-[var(--shadow-soft)] sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-base font-bold text-[var(--ink)] sm:text-lg">
                    Step 1: GSTR-2B Auto-Fetch (Sandbox GSTN API)
                  </h3>
                  <p className="mt-1 text-xs text-gray-500 sm:text-sm">
                    Auto-fetch official GSTR-2B returns across all 12 months using connected GSTN authentication.
                  </p>
                </div>
                <button
                  onClick={handleStartAutoFetch}
                  disabled={loading || batch.status === "fetching"}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--ink)] px-5 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-black disabled:opacity-50"
                >
                  {batch.status === "fetching" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Fetching 12 Months...</span>
                    </>
                  ) : (
                    <>
                      <CloudDownload className="h-4 w-4" />
                      <span>Fetch All 12 Months</span>
                    </>
                  )}
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 md:grid-cols-4">
                {batch.items.map((item) => {
                  const isReady = Boolean(item.gstr2b_file_path) || item.status === "uploaded" || item.status === "completed";
                  const isFetching = item.status === "fetching";
                  const isFailed = item.status === "failed";

                  return (
                    <div
                      key={item.id}
                      className="flex flex-col justify-between rounded-xl border border-gray-200/80 bg-white p-4 shadow-xs"
                    >
                      <div>
                        <span className="text-[10px] font-bold tracking-wider text-gray-400 uppercase">
                          PERIOD
                        </span>
                        <p className="text-sm font-bold text-[var(--ink)]">
                          {periodMonthName(item.period)}
                        </p>
                      </div>

                      <div className="mt-3 flex items-center justify-between border-t border-gray-100 pt-2.5">
                        <span className="text-[11px] font-medium text-gray-500">GSTR-2B:</span>
                        {isReady ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                            <CheckCircle2 className="h-3 w-3" /> Ready
                          </span>
                        ) : isFetching ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
                            <Loader2 className="h-3 w-3 animate-spin" /> Fetching
                          </span>
                        ) : isFailed ? (
                          <span
                            title={item.error_message || "Failed to fetch"}
                            className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-700"
                          >
                            <AlertCircle className="h-3 w-3" /> Failed
                          </span>
                        ) : (
                          <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                            Pending
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="flex justify-end pt-2">
                <button
                  onClick={() => setCurrentStep(2)}
                  className="inline-flex items-center gap-2 rounded-xl bg-[var(--ink)] px-5 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-black"
                >
                  <span>Proceed to Step 2: PR Check</span>
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* STEP 2 CONTENT: PR AVAILABILITY CHECK & MANUAL FALLBACK */}
          {currentStep === 2 && (
            <div className="space-y-6">
              <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-6 shadow-[var(--shadow-soft)]">
                <h3 className="text-base font-bold text-[var(--ink)] sm:text-lg">
                  Step 2: Purchase Register Availability & Fallback
                </h3>
                <p className="mt-1 text-xs text-gray-500 sm:text-sm">
                  Periods with Tally Bridge sync or prior client uploads are automatically linked. Upload manual Excel/CSV purchase registers for missing months.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
                {batch.items.map((item) => {
                  const isReady = item.pr_source && item.pr_source !== "missing";
                  const isUploading = uploadingPeriod === item.period;

                  return (
                    <div
                      key={item.id}
                      className={`flex flex-col justify-between rounded-xl p-4.5 border transition-all ${
                        isReady
                          ? "bg-white border-gray-200/80 shadow-xs"
                          : "bg-amber-50/40 border-amber-200"
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-bold text-[var(--ink)]">
                            {periodMonthName(item.period)}
                          </p>
                          {isReady ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                              <CheckCircle2 className="h-3 w-3" />
                              {item.pr_source === "tally_bridge_existing"
                                ? "Tally Sync"
                                : item.pr_source === "already_uploaded"
                                ? "Existing PR"
                                : "Uploaded"}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100/70 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                              <AlertCircle className="h-3 w-3" /> Missing PR
                            </span>
                          )}
                        </div>

                        {item.error_message && (
                          <p className="mt-2 text-[11px] text-red-600">{item.error_message}</p>
                        )}
                      </div>

                      <div className="mt-4 pt-3 border-t border-gray-100">
                        {isReady ? (
                          <p className="text-xs text-gray-500">
                            PR data connected and verified for reconciliation.
                          </p>
                        ) : (
                          <label className="flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-dashed border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-800 hover:bg-amber-50/50 transition">
                            {isUploading ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Upload className="h-3.5 w-3.5" />
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

              <div className="flex justify-between pt-2">
                <button
                  onClick={() => setCurrentStep(1)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  <span>Back to Step 1</span>
                </button>

                <button
                  onClick={handleRunBatch}
                  disabled={loading || batch.status === "running"}
                  className="inline-flex items-center gap-2 rounded-xl bg-[var(--ink)] px-6 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-black disabled:opacity-50"
                >
                  {batch.status === "running" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Running Batch...</span>
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 fill-current" />
                      <span>Run Batch Reconciliation</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* STEP 3 CONTENT: BATCH RUN PROGRESS & MONITORING */}
          {currentStep === 3 && (
            <div className="space-y-6">
              <div className="rounded-[1.25rem] border border-gray-200/80 bg-white p-6 shadow-[var(--shadow-soft)]">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="text-base font-bold text-[var(--ink)] sm:text-lg">
                      Step 3: Batch Reconciliation Progress
                    </h3>
                    <p className="mt-1 text-xs text-gray-500 sm:text-sm">
                      Sequential chronological reconciliation across FY {batch.financial_year}
                    </p>
                  </div>
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider ${
                      batch.status === "completed"
                        ? "bg-emerald-50 text-emerald-800"
                        : batch.status === "running"
                        ? "bg-blue-50 text-blue-800"
                        : batch.status === "failed"
                        ? "bg-red-50 text-red-800"
                        : "bg-gray-100 text-gray-700"
                    }`}
                  >
                    {batch.status === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
                    Status: {batch.status}
                  </span>
                </div>

                {/* Progress Bar */}
                <div className="mt-5">
                  <div className="flex items-center justify-between text-xs font-semibold text-gray-600 mb-1.5">
                    <span>Overall Batch Progress</span>
                    <span>{progressPct}% ({completedCount}/12 periods completed)</span>
                  </div>
                  <div className="h-2.5 w-full overflow-hidden rounded-full bg-gray-100">
                    <div
                      className="h-full bg-[var(--ink)] transition-all duration-500"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Items List Table */}
              <div className="rounded-[1.25rem] border border-gray-200/80 bg-white shadow-[var(--shadow-soft)] overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
                  <thead className="bg-[#F8FAFC] text-[11px] font-bold uppercase tracking-wider text-gray-500">
                    <tr>
                      <th className="px-6 py-3.5">Period</th>
                      <th className="px-6 py-3.5">GSTR-2B</th>
                      <th className="px-6 py-3.5">Purchase Register</th>
                      <th className="px-6 py-3.5">Status</th>
                      <th className="px-6 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {batch.items.map((item) => (
                      <tr key={item.id} className="hover:bg-gray-50/60 transition-colors">
                        <td className="px-6 py-4 font-semibold text-[var(--ink)]">
                          {periodMonthName(item.period)}
                        </td>
                        <td className="px-6 py-4 text-xs text-gray-600">
                          {item.gstr2b_file_path ? (
                            <span className="inline-flex items-center gap-1 text-emerald-700 font-medium">
                              <Check className="h-3.5 w-3.5" /> Ready
                            </span>
                          ) : (
                            <span className="text-gray-400">Missing</span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-xs text-gray-600">
                          {item.pr_source && item.pr_source !== "missing" ? (
                            <span className="font-medium text-gray-800">
                              {item.pr_source === "tally_bridge_existing"
                                ? "Tally Sync"
                                : item.pr_source === "already_uploaded"
                                ? "Existing PR"
                                : "Uploaded"}
                            </span>
                          ) : (
                            <span className="text-amber-700 font-medium">Missing</span>
                          )}
                        </td>
                        <td className="px-6 py-4">
                          {item.status === "completed" ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                              <CheckCircle2 className="h-3 w-3" /> Completed
                            </span>
                          ) : item.status === "running" ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                              <Loader2 className="h-3 w-3 animate-spin" /> Running
                            </span>
                          ) : item.status === "failed" ? (
                            <div className="flex flex-col gap-0.5">
                              <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-700 w-fit">
                                <AlertCircle className="h-3 w-3" /> Failed
                              </span>
                              {item.error_message && (
                                <span className="text-[11px] text-red-600">
                                  {item.error_message}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
                              Pending
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-right">
                          {item.reconciliation_run_id && (
                            <Link
                              href={`/reconcile/runs/${item.reconciliation_run_id}/results`}
                              className="text-xs font-semibold text-[var(--ink)] hover:underline"
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
        </div>
      )}

      {/* ANNUAL BATCHES HISTORY TABLE */}
      {batches.length > 0 && (
        <div className="mt-8 rounded-[1.25rem] border border-gray-200/80 bg-white shadow-[var(--shadow-soft)] overflow-hidden">
          <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--ink)] sm:text-base">
                Annual Reconciliation Batches ({batches.length})
              </h3>
              <p className="text-xs text-gray-500">
                Prior and current 12-month reconciliation runs for this client
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100 text-left text-xs sm:text-sm">
              <thead className="bg-[#F8FAFC] text-[11px] font-bold uppercase tracking-wider text-gray-500">
                <tr>
                  <th className="px-6 py-3.5">Financial Year</th>
                  <th className="px-6 py-3.5">Created Date</th>
                  <th className="px-6 py-3.5">Status</th>
                  <th className="px-6 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {batches.map((b) => {
                  const isSelected = batch?.id === b.id && !isCreatingNew;

                  return (
                    <tr
                      key={b.id}
                      className={`transition-colors ${
                        isSelected ? "bg-gray-50/80" : "hover:bg-gray-50/50"
                      }`}
                    >
                      <td className="px-6 py-4 font-bold text-[var(--ink)]">
                        FY {b.financial_year}
                        {isSelected && (
                          <span className="ml-2 rounded-full bg-[var(--ink)] px-2 py-0.5 text-[10px] font-semibold text-white">
                            Active
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-gray-500 text-xs">
                        {new Date(b.created_at).toLocaleDateString("en-IN", {
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })}
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${
                            b.status === "completed"
                              ? "bg-emerald-50 text-emerald-700"
                              : b.status === "running" || b.status === "fetching"
                              ? "bg-blue-50 text-blue-700"
                              : b.status === "failed" || b.status === "partially_failed"
                              ? "bg-red-50 text-red-700"
                              : "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {(b.status === "running" || b.status === "fetching") && (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          )}
                          {b.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => handleExportExcel(b.id, b.financial_year)}
                            disabled={exportingId === b.id}
                            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 shadow-xs hover:bg-gray-50 disabled:opacity-50"
                            title="Download multi-sheet XLSX"
                          >
                            {exportingId === b.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Download className="h-3 w-3" />
                            )}
                            <span>Excel</span>
                          </button>

                          <Link
                            href={`/clients/${clientId}/multi-period/${b.id}/summary`}
                            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 shadow-xs hover:bg-gray-50"
                          >
                            <span>Summary</span>
                          </Link>

                          {!isSelected && (
                            <button
                              type="button"
                              onClick={() => handleSelectBatch(b.id)}
                              className="inline-flex items-center gap-1 rounded-lg bg-[var(--ink)] px-2.5 py-1 text-xs font-semibold text-white shadow-xs hover:bg-black"
                            >
                              <span>Open</span>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
