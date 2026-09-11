"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import {
  RefreshCw,
  Loader2,
  Info,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Search,
  Calendar,
  Layers,
  Upload,
  ShieldAlert,
  X,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { useToast } from "@/components/providers/ToastProvider";
import { formatINR } from "@/lib/format";
import {
  ConnectGstnModal,
  isGstnConnected,
} from "@/components/clients/ConnectGstnModal";
import {
  clientsApi,
  gstr2aDeltaApi,
  type ClientGstin,
  type Gstr2aDeltaCategory,
  type Gstr2aDeltaItem,
  type Gstr2aDeltaResponse,
  type Gstr2aDeltaSummaryResponse,
} from "@/lib/api";
import { DW } from "@/lib/dashboard-portfolio";

type CategoryFilter = "ALL" | Gstr2aDeltaCategory;

function getDefaultPeriod(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function getStatusBadge(category: string) {
  switch (category) {
    case "LATE_FILED":
      return {
        label: "Late Filed",
        className: "border-amber-200 bg-amber-50 text-amber-800",
      };
    case "FILED_NOT_REFLECTED":
      return {
        label: "Not in 2B",
        className: "border-rose-200 bg-rose-50 text-rose-800",
      };
    case "IN_2B_NOT_2A":
      return {
        label: "Only in 2B",
        className: "border-blue-200 bg-blue-50 text-blue-800",
      };
    case "VALUE_MISMATCH":
      return {
        label: "Value Mismatch",
        className: "border-orange-200 bg-orange-50 text-orange-800",
      };
    case "IN_BOTH":
    default:
      return {
        label: "Matched",
        className: "border-emerald-200 bg-emerald-50 text-emerald-800",
      };
  }
}

export default function Gstr2aDeltaPage() {
  const params = useParams();
  const clientId = String(params.id);
  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const toast = useToast();

  const [period, setPeriod] = useState(getDefaultPeriod);
  const [running, setRunning] = useState(false);
  const [activeCategory, setActiveCategory] = useState<CategoryFilter>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [connectGstnOpen, setConnectGstnOpen] = useState(false);
  const [uploaded2aFileName, setUploaded2aFileName] = useState<string | null>(null);
  const [uploaded2aJson, setUploaded2aJson] = useState<Record<string, any> | null>(null);
  const [uploaded2bFileName, setUploaded2bFileName] = useState<string | null>(null);
  const [uploaded2bJson, setUploaded2bJson] = useState<Record<string, any> | null>(null);

  // Client query to check GSTN connection
  const clientKey = token && clientId ? ["client", token, clientId] : null;
  const { data: rawClient, mutate: mutateClient } = useSWR<ClientGstin | null>(
    clientKey,
    async ([, t, cid]) => {
      try {
        return (await clientsApi.get(t, cid)) as ClientGstin;
      } catch {
        return null;
      }
    },
    { revalidateOnFocus: false }
  );

  const gstnConnected = isGstnConnected(rawClient ?? undefined);

  // Check GSTR-2B availability in ReconDesk database
  const sourcesKey =
    token && clientId && period
      ? [`/api/gstr2a-delta/${clientId}/${period}/sources`, token]
      : null;

  const { data: sourcesData, mutate: mutateSources } = useSWR(
    sourcesKey,
    async ([_, t]) => {
      try {
        return await gstr2aDeltaApi.getSources(t, clientId, period);
      } catch {
        return null;
      }
    },
    { revalidateOnFocus: false }
  );

  const handleFileUpload2A = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".json")) {
      toast("Please select a valid .json file exported from the GST portal", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target?.result as string;
        const parsed = JSON.parse(text);
        setUploaded2aJson(parsed);
        setUploaded2aFileName(file.name);
        toast(`Loaded GSTR-2A (${file.name}) successfully`, "success");
      } catch {
        toast("Failed to parse JSON file. Please ensure it is valid GSTR-2A JSON.", "error");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const handleClear2A = () => {
    setUploaded2aJson(null);
    setUploaded2aFileName(null);
  };

  const handleFileUpload2B = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".json")) {
      toast("Please select a valid .json file exported from the GST portal", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target?.result as string;
        const parsed = JSON.parse(text);
        setUploaded2bJson(parsed);
        setUploaded2bFileName(file.name);
        toast(`Loaded GSTR-2B (${file.name}) successfully`, "success");
      } catch {
        toast("Failed to parse JSON file. Please ensure it is valid GSTR-2B JSON.", "error");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const handleClear2B = () => {
    setUploaded2bJson(null);
    setUploaded2bFileName(null);
  };

  // 1. Fetch Summary on mount / period change
  const summaryKey =
    token && clientId && period
      ? [`/api/gstr2a-delta/${clientId}/${period}/summary`, token]
      : null;

  const {
    data: summaryData,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr2aDeltaSummaryResponse | null>(
    summaryKey,
    async ([_, t]) => {
      try {
        return await gstr2aDeltaApi.getSummary(t, clientId, period);
      } catch (err: any) {
        if (err?.status === 404 || err?.statusCode === 404) {
          return null;
        }
        throw err;
      }
    },
    { revalidateOnFocus: false }
  );

  const summary = summaryData?.summary ?? null;

  // 2. Fetch paginated table results when summary exists
  const resultsKey =
    token && clientId && period && summary
      ? [
          `/api/gstr2a-delta/${clientId}/${period}`,
          token,
          activeCategory,
          debouncedSearch,
          page,
        ]
      : null;

  const {
    data: resultsData,
    isLoading: isResultsLoading,
    mutate: mutateResults,
  } = useSWR<Gstr2aDeltaResponse>(
    resultsKey,
    ([_, t, cat, search, pg]) =>
      gstr2aDeltaApi.getResults(t, clientId, period, {
        category: cat as string,
        search: search as string,
        page: pg as number,
        page_size: 25,
      }),
    { revalidateOnFocus: false, keepPreviousData: true }
  );

  const items = resultsData?.results ?? [];
  const totalRecords = resultsData?.total_records ?? 0;
  const totalPages = Math.ceil(totalRecords / 25) || 1;

  // Toggle row expansion
  const toggleRow = (rowKey: string) => {
    setExpandedRows((prev) => ({
      ...prev,
      [rowKey]: !prev[rowKey],
    }));
  };

  // Run analysis handler
  const handleRunAnalysis = async () => {
    if (!token || !clientId || running) return;

    // Check 2A availability
    if (!uploaded2aJson && !gstnConnected) {
      toast(
        "Please connect your GST portal session via OTP or upload a GSTR-2A JSON file to run analysis.",
        "info"
      );
      setConnectGstnOpen(true);
      return;
    }

    // Check 2B availability
    const has2b =
      Boolean(uploaded2bJson) ||
      Boolean(sourcesData?.has_2b_in_db) ||
      Boolean(gstnConnected);

    if (!has2b) {
      toast(
        "No GSTR-2B data found for this period. Please upload GSTR-2B JSON, connect GST Portal to fetch live, or run 2B reconciliation first.",
        "error"
      );
      return;
    }

    setRunning(true);
    try {
      const res = await gstr2aDeltaApi.run(
        token,
        clientId,
        period,
        undefined,
        uploaded2aJson || undefined,
        uploaded2bJson || undefined
      );
      toast("GSTR-2A vs 2B Delta analysis completed successfully", "success");
      await mutateSummary(
        {
          client_gstin_id: res.client_gstin_id,
          period: res.period,
          cutoff_date: res.cutoff_date,
          reconciled_at: res.reconciled_at,
          summary: res.summary,
        },
        false
      );
      void mutateSources();
      setPage(1);
      await mutateResults();
    } catch (err: any) {
      const msg =
        err?.detail || err?.message || "Failed to run GSTR-2A vs 2B Delta analysis";
      if (
        err?.status === 409 ||
        err?.statusCode === 409 ||
        msg.toLowerCase().includes("gstn not connected") ||
        msg.toLowerCase().includes("otp")
      ) {
        setConnectGstnOpen(true);
      }
      toast(msg, "error");
    } finally {
      setRunning(false);
    }
  };

  // Category filter chips config
  const categoryChips: {
    id: CategoryFilter;
    label: string;
    count?: number;
    isSubset?: boolean;
  }[] = useMemo(() => {
    return [
      { id: "ALL", label: "All", count: summary?.total_records },
      { id: "LATE_FILED", label: "Late Filed", count: summary?.late_filed },
      {
        id: "FILED_NOT_REFLECTED",
        label: "Filed Not Reflected",
        count: summary?.filed_not_reflected,
      },
      {
        id: "IN_2B_NOT_2A",
        label: "In 2B Not 2A",
        count: summary?.in_2b_not_2a,
      },
      {
        id: "VALUE_MISMATCH",
        label: "Value Mismatch",
        count: summary?.value_mismatch,
        isSubset: true,
      },
      { id: "IN_BOTH", label: "Matched", count: summary?.in_both },
    ];
  }, [summary]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-gray-900 sm:text-2xl">
              GSTR-2A vs GSTR-2B Delta
            </h1>
            {summaryData?.reconciled_at && (
              <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                Last run:{" "}
                {new Date(summaryData.reconciled_at).toLocaleString("en-IN", {
                  day: "2-digit",
                  month: "short",
                  year: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Invoices in 2A not reflected in 2B — supplier filing cutoff analysis
          </p>
        </div>

        {/* Controls: GSTN Connect + Upload 2A + 2B Source / Upload 2B + Period + Run */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* GSTN Status / Connect button */}
          {gstnConnected ? (
            <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800 shadow-sm">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </span>
              <span>GST Portal Connected</span>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConnectGstnOpen(true)}
              className="flex items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-2 text-xs font-semibold text-amber-900 shadow-sm transition-colors hover:bg-amber-100"
            >
              <span className="h-2 w-2 rounded-full bg-amber-500" />
              <span>Connect GST Portal (OTP)</span>
            </button>
          )}

          {/* Upload 2A JSON */}
          {uploaded2aFileName ? (
            <div className="flex items-center gap-1.5 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-900 shadow-sm">
              <Upload className="h-3.5 w-3.5 text-blue-600" />
              <span className="max-w-[130px] truncate font-semibold" title={uploaded2aFileName}>
                2A: {uploaded2aFileName}
              </span>
              <button
                type="button"
                onClick={handleClear2A}
                className="ml-0.5 rounded-full p-0.5 text-blue-500 hover:bg-blue-200 hover:text-blue-800 transition-colors"
                title="Remove GSTR-2A file"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <label className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 shadow-sm transition-colors hover:bg-gray-50">
              <Upload className="h-3.5 w-3.5 text-gray-500" />
              <span>Upload 2A JSON</span>
              <input
                type="file"
                accept=".json,application/json"
                onChange={handleFileUpload2A}
                className="hidden"
              />
            </label>
          )}

          {/* GSTR-2B Source / Upload */}
          {uploaded2bFileName ? (
            <div className="flex items-center gap-1.5 rounded-xl border border-purple-200 bg-purple-50 px-3 py-2 text-xs font-medium text-purple-900 shadow-sm">
              <Upload className="h-3.5 w-3.5 text-purple-600" />
              <span className="max-w-[130px] truncate font-semibold" title={uploaded2bFileName}>
                2B: {uploaded2bFileName}
              </span>
              <button
                type="button"
                onClick={handleClear2B}
                className="ml-0.5 rounded-full p-0.5 text-purple-500 hover:bg-purple-200 hover:text-purple-800 transition-colors"
                title="Remove GSTR-2B file"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : sourcesData?.has_2b_in_db ? (
            <div className="flex items-center gap-1.5">
              <div
                className="flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800 shadow-sm cursor-help"
                title={
                  sourcesData.file_name
                    ? `Source: ${sourcesData.file_name} (${
                        sourcesData.source_type === "excel_recon"
                          ? "Excel Recon"
                          : sourcesData.source_type === "portal_json"
                          ? "Portal JSON"
                          : "Recon Run"
                      })${
                        sourcesData.uploaded_at
                          ? ` • Uploaded ${new Date(sourcesData.uploaded_at).toLocaleDateString()}`
                          : ""
                      } • Run #${sourcesData.run_id ? sourcesData.run_id.slice(0, 8) : ""}`
                    : "ReconDesk loaded GSTR-2B records from your latest reconciliation run for this period"
                }
              >
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                <span>2B in DB ({sourcesData.records_2b_count} inv)</span>
              </div>
              <label
                className="flex cursor-pointer items-center gap-1 rounded-xl border border-gray-200 bg-white px-2.5 py-2 text-xs font-medium text-gray-600 shadow-sm transition-colors hover:bg-gray-50 hover:text-gray-900"
                title="Upload an official GSTR-2B JSON file to override the database run"
              >
                <Upload className="h-3 w-3 text-gray-400" />
                <span>Override 2B</span>
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={handleFileUpload2B}
                  className="hidden"
                />
              </label>
            </div>
          ) : (
            <label className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 shadow-sm transition-colors hover:bg-gray-50">
              <Upload className="h-3.5 w-3.5 text-gray-500" />
              <span>Upload 2B JSON</span>
              <input
                type="file"
                accept=".json,application/json"
                onChange={handleFileUpload2B}
                className="hidden"
              />
            </label>
          )}

          {/* Period Selector */}
          <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm">
            <Calendar className="h-4 w-4 text-gray-400" />
            <input
              type="month"
              value={period}
              onChange={(e) => {
                setPeriod(e.target.value);
                setPage(1);
              }}
              className="border-none bg-transparent text-sm font-semibold text-gray-800 outline-none"
            />
          </div>

          {/* Run Analysis Button */}
          <button
            type="button"
            onClick={handleRunAnalysis}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-xl bg-[var(--ink)] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {running ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Running Analysis...</span>
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4" />
                <span>Run Analysis</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Running State Banner */}
      {running && (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-gray-200 bg-white p-12 text-center shadow-sm">
          <Loader2 className="h-8 w-8 animate-spin text-[var(--ink)]" />
          <p className="mt-3 text-sm font-medium text-gray-700">
            {uploaded2aJson
              ? "Parsing uploaded GSTR-2A JSON and running delta analysis..."
              : "Fetching GSTR-2A from GST portal and running delta analysis..."}
          </p>
          <span className="mt-1 text-xs text-gray-400">
            Comparing supplier filing timestamps against the 13th cutoff date
          </span>
        </div>
      )}

      {/* Empty State before first run */}
      {!running && !isSummaryLoading && !summary && (
        <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-gray-100 text-gray-600">
            <Layers className="h-6 w-6 text-gray-600" />
          </div>
          <h3 className="mt-4 text-base font-bold text-gray-900">
            GSTR-2A vs GSTR-2B Delta Analysis
          </h3>
          <p className="mx-auto mt-1 max-w-xl text-sm text-gray-500">
            Identify invoices present in GSTR-2A but missing or deferred in GSTR-2B.
            Detect invoices filed by suppliers after the 13th cutoff so you know exactly which
            ITC can be claimed this month vs next month.
          </p>

          {/* 3 Step Source Architecture */}
          <div className="mx-auto mt-6 grid max-w-3xl grid-cols-1 gap-4 sm:grid-cols-3 text-left">
            {/* Step 1: 2A Source */}
            <div className="flex flex-col justify-between rounded-xl border border-gray-200 bg-gray-50/60 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ink)] text-[10px] font-bold text-white">
                    1
                  </span>
                  <span className="text-xs font-bold uppercase tracking-wider text-gray-700">
                    GSTR-2A Source
                  </span>
                </div>
                <p className="mt-2 text-xs text-gray-500">
                  Real-time reflections of what suppliers have filed in GSTR-1.
                </p>
              </div>
              <div className="mt-4 space-y-2">
                {uploaded2aFileName ? (
                  <div className="flex items-center gap-1 text-xs font-semibold text-blue-700">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    <span className="truncate max-w-[150px]">2A: {uploaded2aFileName}</span>
                    <button
                      type="button"
                      onClick={handleClear2A}
                      className="ml-1 text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ) : (
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100 shadow-sm transition-colors">
                    <Upload className="h-3.5 w-3.5 text-gray-500" />
                    <span>Upload 2A JSON</span>
                    <input
                      type="file"
                      accept=".json,application/json"
                      onChange={handleFileUpload2A}
                      className="hidden"
                    />
                  </label>
                )}
                {gstnConnected ? (
                  <div className="text-[11px] font-medium text-emerald-700">
                    ✓ Portal connected (live fetch ready)
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConnectGstnOpen(true)}
                    className="block text-[11px] font-semibold text-amber-800 underline hover:text-amber-900"
                  >
                    Or connect GST Portal (OTP) →
                  </button>
                )}
              </div>
            </div>

            {/* Step 2: 2B Source */}
            <div className="flex flex-col justify-between rounded-xl border border-gray-200 bg-gray-50/60 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ink)] text-[10px] font-bold text-white">
                    2
                  </span>
                  <span className="text-xs font-bold uppercase tracking-wider text-gray-700">
                    GSTR-2B Source
                  </span>
                </div>
                <p className="mt-2 text-xs text-gray-500">
                  Locked snapshot generated on the 14th containing invoices filed by the 13th.
                </p>
              </div>
              <div className="mt-4 space-y-2">
                {uploaded2bFileName ? (
                  <div className="flex items-center gap-1 text-xs font-semibold text-purple-700">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    <span className="truncate max-w-[150px]">2B: {uploaded2bFileName}</span>
                    <button
                      type="button"
                      onClick={handleClear2B}
                      className="ml-1 text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ) : sourcesData?.has_2b_in_db ? (
                  <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-2.5 py-1 text-xs font-semibold text-emerald-800">
                    ✓ {sourcesData.records_2b_count} records in ReconDesk DB
                  </div>
                ) : (
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100 shadow-sm transition-colors">
                    <Upload className="h-3.5 w-3.5 text-gray-500" />
                    <span>Upload 2B JSON</span>
                    <input
                      type="file"
                      accept=".json,application/json"
                      onChange={handleFileUpload2B}
                      className="hidden"
                    />
                  </label>
                )}
                <div className="text-[11px] text-gray-500">
                  {sourcesData?.has_2b_in_db
                    ? "Auto-loaded from previous recon"
                    : gstnConnected
                    ? "Auto-fetched live via GSTN"
                    : "Upload file or connect portal"}
                </div>
              </div>
            </div>

            {/* Step 3: Delta Analysis */}
            <div className="flex flex-col justify-between rounded-xl border border-gray-200 bg-gray-50/60 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ink)] text-[10px] font-bold text-white">
                    3
                  </span>
                  <span className="text-xs font-bold uppercase tracking-wider text-gray-700">
                    Cutoff Engine
                  </span>
                </div>
                <p className="mt-2 text-xs text-gray-500">
                  Compares filing timestamps against the 13th cutoff date.
                </p>
              </div>
              <div className="mt-4 space-y-1 text-xs text-gray-600">
                <div className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-amber-500" />
                  <span>Late Filed → Next month</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-rose-500" />
                  <span>Missing from 2B → Action</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  <span>Matched clean</span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 flex justify-center">
            <button
              type="button"
              onClick={handleRunAnalysis}
              disabled={running}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--ink)] px-6 py-2.5 text-sm font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" />
              <span>Run Analysis</span>
            </button>
          </div>
        </div>
      )}

      {/* Main Content Area when Summary exists */}
      {!running && summary && (
        <>
          {/* Reconciliation Population Summary Bar */}
          <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-[var(--shadow-soft)]">
            <div className="flex flex-col gap-2 pb-4 border-b border-gray-100 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-[var(--ink)]" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-gray-800">
                  Reconciliation Population Summary
                </h2>
              </div>
              <div className="flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs text-blue-800">
                <Info className="h-3.5 w-3.5 shrink-0 text-blue-600" />
                <span>
                  {summary.subset_note ||
                    `${summary.value_mismatch} of the ${summary.in_both} invoices present in both have value differences. Value Mismatch is a subset of the matched population and is not an additive invoice count.`}
                </span>
              </div>
            </div>

            {/* Population Metric Grid */}
            <div className="grid grid-cols-2 gap-2.5 pt-4 sm:grid-cols-4 lg:grid-cols-8">
              <div className="rounded-xl border border-gray-100 bg-gray-50/70 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                  2A Invoices
                </span>
                <span className="mt-0.5 block font-mono text-base font-bold text-gray-900">
                  {summary.total_2a ??
                    summary.in_both +
                      summary.filed_not_reflected +
                      summary.late_filed}
                </span>
              </div>
              <div className="rounded-xl border border-gray-100 bg-gray-50/70 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                  2B Invoices
                </span>
                <span className="mt-0.5 block font-mono text-base font-bold text-gray-900">
                  {summary.total_2b ??
                    summary.in_both + summary.in_2b_not_2a}
                </span>
              </div>
              <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-indigo-700">
                  Unique Population
                </span>
                <span className="mt-0.5 block font-mono text-base font-bold text-indigo-950">
                  {summary.unique_union_count ?? summary.total_records}
                </span>
              </div>
              <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
                  Present in Both
                </span>
                <span className="mt-0.5 block font-mono text-base font-bold text-emerald-950">
                  {summary.in_both}
                </span>
              </div>
              <div className="rounded-xl border border-rose-100 bg-rose-50/50 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-rose-700">
                  Missing from 2B
                </span>
                <span className="mt-0.5 block font-mono text-base font-bold text-rose-950">
                  {summary.filed_not_reflected}
                </span>
              </div>
              <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-blue-700">
                  In 2B Not 2A
                </span>
                <span className="mt-0.5 block font-mono text-base font-bold text-blue-950">
                  {summary.in_2b_not_2a}
                </span>
              </div>
              <div className="rounded-xl border border-orange-100 bg-orange-50/50 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-orange-700">
                  Value Mismatch
                </span>
                <div className="mt-0.5 flex items-center justify-center gap-1">
                  <span className="font-mono text-base font-bold text-orange-950">
                    {summary.value_mismatch}
                  </span>
                  <span className="rounded bg-orange-200/80 px-1 py-0.2 text-[9px] font-bold text-orange-900">
                    subset
                  </span>
                </div>
              </div>
              <div className="rounded-xl border border-amber-100 bg-amber-50/50 p-2.5 text-center">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-amber-700">
                  Late Filed
                </span>
                <span className="mt-0.5 block font-mono text-base font-bold text-amber-950">
                  {summary.late_filed}
                </span>
              </div>
            </div>
          </div>

          {/* Summary Cards Row (4 Cards) */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {/* Card 1 — ITC Deferred (amber) */}
            <div className="rounded-2xl border border-amber-200 bg-amber-50/50 p-5 shadow-[var(--shadow-soft)]">
              <span className="text-xs font-semibold uppercase tracking-wider text-amber-800">
                Late Filed — Next Month&apos;s 2B
              </span>
              <div className="mt-2 font-mono text-2xl font-bold text-amber-950">
                {formatINR((summary.total_itc_deferred_paise || 0) / 100)}
              </div>
              <div className="mt-1 text-xs font-medium text-amber-700">
                {summary.late_filed}{" "}
                {summary.late_filed === 1 ? "invoice" : "invoices"}
              </div>
            </div>

            {/* Card 2 — Needs Attention (red) */}
            <div className="rounded-2xl border border-rose-200 bg-rose-50/50 p-5 shadow-[var(--shadow-soft)]">
              <span className="text-xs font-semibold uppercase tracking-wider text-rose-800">
                Filed On Time, Missing from 2B
              </span>
              <div className="mt-2 font-mono text-2xl font-bold text-rose-950">
                {formatINR((summary.total_itc_unresolved_paise || 0) / 100)}
              </div>
              <div className="mt-1 text-xs font-medium text-rose-700">
                {summary.filed_not_reflected}{" "}
                {summary.filed_not_reflected === 1 ? "invoice" : "invoices"}
              </div>
            </div>

            {/* Card 3 — Matched Clean (green) */}
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/50 p-5 shadow-[var(--shadow-soft)]">
              <span className="text-xs font-semibold uppercase tracking-wider text-emerald-800">
                Present in Both 2A &amp; 2B
              </span>
              <div className="mt-2 font-mono text-2xl font-bold text-emerald-950">
                {summary.in_both}
              </div>
              <div className="mt-1 text-xs font-medium text-emerald-700">
                ITC available • Incl. {summary.value_mismatch} with value diffs
              </div>
            </div>

            {/* Card 4 — Value Mismatch (orange) */}
            <div className="rounded-2xl border border-orange-200 bg-orange-50/50 p-5 shadow-[var(--shadow-soft)]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-orange-800">
                  Amount Differs Between 2A &amp; 2B
                </span>
                <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-orange-800">
                  Subset of Matched
                </span>
              </div>
              <div className="mt-2 font-mono text-2xl font-bold text-orange-950">
                {summary.value_mismatch}
              </div>
              <div className="mt-1 text-xs font-medium text-orange-700">
                {summary.value_mismatch} of {summary.in_both} present in both have value diffs (use 2B value for ITC)
              </div>
            </div>
          </div>

          {/* Filter Chips & Search Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            {/* Category Filter Chips */}
            <div className="flex flex-wrap items-center gap-1.5">
              {categoryChips.map(({ id, label, count, isSubset }) => {
                const isActive = activeCategory === id;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => {
                      setActiveCategory(id);
                      setPage(1);
                    }}
                    className={
                      isActive
                        ? "rounded-full bg-[var(--ink)] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm"
                        : "rounded-full bg-white px-3.5 py-1.5 text-xs font-medium text-gray-600 shadow-[var(--shadow-soft)] transition-colors hover:bg-gray-50 hover:text-gray-900"
                    }
                  >
                    {label}
                    {count != null && (
                      <span
                        className={`ml-1.5 font-bold ${
                          isActive ? "text-white/80" : "text-gray-400"
                        }`}
                      >
                        ({count}
                        {isSubset ? " subset" : ""})
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Search Input */}
            <div className="relative min-w-[220px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search GSTIN or invoice..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setDebouncedSearch(e.target.value.trim());
                  setPage(1);
                }}
                className="w-full rounded-full border border-gray-200 bg-white py-1.5 pl-8 pr-3 text-xs text-gray-900 placeholder:text-gray-400 shadow-sm focus:border-[var(--ink)] focus:outline-none focus:ring-1 focus:ring-[var(--ink)]"
              />
            </div>
          </div>

          {/* Results Table */}
          <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-left">
                <thead className="bg-gray-50/75">
                  <tr>
                    <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      Supplier GSTIN
                    </th>
                    <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      Invoice No.
                    </th>
                    <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      Invoice Date
                    </th>
                    <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      Filing Date
                    </th>
                    <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      Days Late
                    </th>
                    <th className="px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      ITC at Risk (₹)
                    </th>
                    <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      Next Month 2B
                    </th>
                    <th className="px-4 py-3 text-center text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                      Status
                    </th>
                    <th className="w-10 px-3 py-3" aria-label="Expand" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white text-xs">
                  {isResultsLoading && items.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-12 text-center text-gray-500">
                        <Loader2 className="mx-auto h-6 w-6 animate-spin text-[var(--ink)]" />
                        <span className="mt-2 block text-xs">
                          Loading delta records...
                        </span>
                      </td>
                    </tr>
                  ) : items.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-12 text-center">
                        <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-500" />
                        <h4 className="mt-2 font-semibold text-gray-900">
                          No records found
                        </h4>
                        <p className="mt-1 text-xs text-gray-500">
                          {summary.total_records === 0
                            ? "All invoices matched. No delta found for this period."
                            : "No invoices match the selected filter or search query."}
                        </p>
                      </td>
                    </tr>
                  ) : (
                    items.map((item, idx) => {
                      const rowKey = `${item.invoice_number}_${item.supplier_gstin || idx}`;
                      const isExpanded = !!expandedRows[rowKey];
                      const badge = getStatusBadge(item.category);

                      return (
                        <tr
                          key={rowKey}
                          className="group border-b border-gray-100 hover:bg-gray-50/50"
                        >
                          <td colSpan={9} className="p-0">
                            {/* Summary Row */}
                            <div
                              onClick={() => toggleRow(rowKey)}
                              className="flex cursor-pointer items-center divide-x divide-transparent px-4 py-3 transition-colors group-hover:bg-gray-50/60"
                            >
                              <div className="w-[18%] pr-3">
                                <span className="font-mono font-medium text-gray-900">
                                  {item.supplier_gstin || "—"}
                                </span>
                                {item.supplier_name && (
                                  <div className="truncate text-[11px] text-gray-400">
                                    {item.supplier_name}
                                  </div>
                                )}
                              </div>

                              <div className="w-[16%] px-3 font-semibold text-gray-900">
                                {item.invoice_number}
                              </div>

                              <div className="w-[12%] px-3 text-gray-600">
                                {item.invoice_date || "—"}
                              </div>

                              <div className="w-[12%] px-3 text-gray-600">
                                {item.filing_date || "—"}
                              </div>

                              <div className="w-[10%] px-3">
                                {item.category === "LATE_FILED" &&
                                item.days_late > 0 ? (
                                  <span className="font-semibold text-amber-800">
                                    {item.days_late} d
                                  </span>
                                ) : (
                                  <span className="text-gray-400">—</span>
                                )}
                              </div>

                              <div className="w-[14%] px-3 text-right font-mono font-semibold text-gray-900">
                                {formatINR((item.itc_at_risk_paise || 0) / 100)}
                              </div>

                              <div className="w-[10%] px-3 text-gray-600">
                                {item.category === "LATE_FILED" &&
                                item.next_month_2b ? (
                                  <span className="font-medium text-amber-800">
                                    {item.next_month_2b}
                                  </span>
                                ) : (
                                  <span className="text-gray-400">—</span>
                                )}
                              </div>

                              <div className="w-[12%] px-3 text-center">
                                <span
                                  className={`inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${badge.className}`}
                                >
                                  {badge.label}
                                </span>
                              </div>

                              <div className="w-10 text-right text-gray-400">
                                {isExpanded ? (
                                  <ChevronDown className="h-4 w-4 text-gray-600" />
                                ) : (
                                  <ChevronRight className="h-4 w-4" />
                                )}
                              </div>
                            </div>

                            {/* Expandable Decision & Comparison View */}
                            {isExpanded && (
                              <div className="border-t border-gray-100 bg-gray-50/70 p-4">
                                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                                  {/* Decision Layer output */}
                                  <div className="rounded-xl border border-gray-200 bg-white p-3.5 shadow-sm">
                                    <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                                      Decision Layer Insight
                                    </div>
                                    <div className="space-y-2 text-xs">
                                      <div className="flex items-start gap-2">
                                        <span className="inline-block w-12 shrink-0 font-bold text-gray-700">
                                          WHAT:
                                        </span>
                                        <span className="font-semibold text-gray-900">
                                          {item.decision_what}
                                        </span>
                                      </div>
                                      <div className="flex items-start gap-2">
                                        <span className="inline-block w-12 shrink-0 font-bold text-gray-700">
                                          WHY:
                                        </span>
                                        <span className="text-gray-600 leading-relaxed">
                                          {item.decision_why}
                                        </span>
                                      </div>
                                      <div className="flex items-start gap-2">
                                        <span className="inline-block w-12 shrink-0 font-bold text-emerald-800">
                                          NEXT:
                                        </span>
                                        <span className="font-medium text-emerald-800 leading-relaxed">
                                          {item.decision_next}
                                        </span>
                                      </div>
                                    </div>
                                  </div>

                                  {/* Side-by-Side Comparison Table */}
                                  <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
                                    <div className="bg-gray-50/80 px-3.5 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                                      GSTR-2A vs GSTR-2B Values
                                    </div>
                                    <table className="min-w-full divide-y divide-gray-100 text-xs">
                                      <thead className="bg-gray-50/40 text-gray-500">
                                        <tr>
                                          <th className="px-3.5 py-2 text-left font-medium">
                                            Field
                                          </th>
                                          <th className="px-3.5 py-2 text-right font-medium">
                                            2A Value
                                          </th>
                                          <th className="px-3.5 py-2 text-right font-medium">
                                            2B Value
                                          </th>
                                        </tr>
                                      </thead>
                                      <tbody className="divide-y divide-gray-100 font-mono">
                                        <tr>
                                          <td className="px-3.5 py-2 font-sans text-gray-600">
                                            Taxable Value
                                          </td>
                                          <td className="px-3.5 py-2 text-right text-gray-900">
                                            {item.taxable_value_2a != null
                                              ? formatINR(item.taxable_value_2a)
                                              : "—"}
                                          </td>
                                          <td className="px-3.5 py-2 text-right text-gray-900">
                                            {item.taxable_value_2b != null
                                              ? formatINR(item.taxable_value_2b)
                                              : "—"}
                                          </td>
                                        </tr>
                                        <tr>
                                          <td className="px-3.5 py-2 font-sans text-gray-600">
                                            ITC Amount
                                          </td>
                                          <td className="px-3.5 py-2 text-right text-gray-900">
                                            {item.tax_value_2a != null
                                              ? formatINR(item.tax_value_2a)
                                              : "—"}
                                          </td>
                                          <td className="px-3.5 py-2 text-right text-gray-900">
                                            {item.tax_value_2b != null
                                              ? formatINR(item.tax_value_2b)
                                              : "—"}
                                          </td>
                                        </tr>
                                      </tbody>
                                    </table>
                                  </div>
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {totalRecords > 0 && (
              <div className="flex items-center justify-between border-t border-gray-100 bg-white px-4 py-3 text-xs text-gray-500">
                <div>
                  Showing{" "}
                  <span className="font-semibold text-gray-900">
                    {(page - 1) * 25 + 1}
                  </span>{" "}
                  to{" "}
                  <span className="font-semibold text-gray-900">
                    {Math.min(page * 25, totalRecords)}
                  </span>{" "}
                  of{" "}
                  <span className="font-semibold text-gray-900">
                    {totalRecords}
                  </span>{" "}
                  invoices
                </div>

                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1 font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-40"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                    <span>Previous</span>
                  </button>

                  <span className="px-2 text-gray-600 font-medium">
                    Page {page} of {totalPages}
                  </span>

                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1 font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-40"
                  >
                    <span>Next</span>
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* Connect GSTN Modal */}
      {token && rawClient && (
        <ConnectGstnModal
          open={connectGstnOpen}
          onClose={() => setConnectGstnOpen(false)}
          clientGstinId={clientId}
          defaultGstin={rawClient.gstin || ""}
          authToken={token}
          onSuccess={() => {
            void mutateClient();
            toast("GST Portal session connected successfully! You can now run live analysis.", "success");
          }}
        />
      )}
    </div>
  );
}
