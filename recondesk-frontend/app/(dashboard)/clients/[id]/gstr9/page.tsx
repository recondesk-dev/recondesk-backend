"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  Download,
  Save,
  Loader2,
  Edit3,
  Layers,
  ShieldCheck,
  RefreshCw,
  X,
  ChevronRight,
  Calendar,
  ChevronDown,
  LayoutDashboard,
  ArrowUpRight,
  ArrowDownLeft,
  Receipt,
  FileText,
  Info,
  Check,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { formatINR } from "@/lib/format";
import { downloadBlobAsFile } from "@/lib/download";
import { useToast } from "@/components/providers/ToastProvider";
import { clientsApi, type ClientGstin } from "@/lib/api";
import {
  fetchGstr9Computation,
  saveGstr9Overrides,
  fetchGstr9cReconciliation,
  downloadGstr9Json,
  downloadGstr9cJson,
  checkGstr9DataAvailability,
  fetchLiveGstr9PortalApi,
  type Gstr9Computation,
  type Gstr9cReconciliation,
  type AuditOverrideInput,
  type PeriodSyncDetail,
} from "@/lib/gstr9Api";

const FY_OPTIONS = ["2025-26", "2024-25", "2023-24"];

const TABS = [
  { id: "summary", label: "GSTR-9 Overview", icon: LayoutDashboard },
  { id: "table4_5", label: "Table 4 & 5 (Outward Supplies)", icon: ArrowUpRight },
  { id: "table6_7_8", label: "Table 6, 7 & 8 (ITC & Recon)", icon: ArrowDownLeft },
  { id: "table9", label: "Table 9 (Tax Paid)", icon: Receipt },
  { id: "gstr9c", label: "GSTR-9C Audit Statement", icon: ShieldCheck },
] as const;

type TabId = (typeof TABS)[number]["id"];

function Gstr9WorkspaceContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const clientId = String(params.id);
  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const toast = useToast();

  const [client, setClient] = useState<ClientGstin | null>(null);
  const [selectedFy, setSelectedFy] = useState("2025-26");

  const requestedTab = searchParams?.get("tab") as TabId | null;
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    return requestedTab && TABS.some((t) => t.id === requestedTab)
      ? requestedTab
      : "summary";
  });

  useEffect(() => {
    if (requestedTab && TABS.some((t) => t.id === requestedTab)) {
      setActiveTab(requestedTab);
    }
  }, [requestedTab]);

  const [comp, setComp] = useState<Gstr9Computation | null>(null);
  const [g9c, setG9c] = useState<Gstr9cReconciliation | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncDetails, setSyncDetails] = useState<PeriodSyncDetail[] | null>(null);
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [downloadingG9, setDownloadingG9] = useState(false);
  const [downloadingG9c, setDownloadingG9c] = useState(false);

  // Local state for GSTR-9 Overrides
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  // Baseline system computed values (for diff indication)
  const [baselineValues, setBaselineValues] = useState<Record<string, number>>({});
  // Track keys modified by user in this session
  const [modifiedKeys, setModifiedKeys] = useState<Set<string>>(new Set());

  // Local state for GSTR-9C inputs
  const [auditedTurnover, setAuditedTurnover] = useState<number>(0);
  const [auditedItc, setAuditedItc] = useState<number>(0);
  const [auditedTax, setAuditedTax] = useState<number>(0);

  // Fetch client details for header context
  useEffect(() => {
    if (!token || !clientId) return;
    clientsApi
      .get(token, clientId)
      .then((c) => setClient(c))
      .catch((err) => console.error("Client fetch error:", err));
  }, [token, clientId]);

  // Fetch GSTR-9 computation for selected FY
  useEffect(() => {
    if (!token || !clientId) return;
    setLoading(true);

    fetchGstr9Computation(clientId, selectedFy, token)
      .then((data) => {
        setComp(data);
        const initialOverrides: Record<string, number> = {};
        if (data.table4) {
          Object.entries(data.table4).forEach(([k, v]) => {
            initialOverrides[`table4.${k}`] = v;
          });
        }
        if (data.table5) {
          Object.entries(data.table5).forEach(([k, v]) => {
            initialOverrides[`table5.${k}`] = v;
          });
        }
        if (data.table6) {
          Object.entries(data.table6).forEach(([k, v]) => {
            initialOverrides[`table6.${k}`] = v;
          });
        }
        if (data.table7) {
          Object.entries(data.table7).forEach(([k, v]) => {
            initialOverrides[`table7.${k}`] = v;
          });
        }
        setOverrides(initialOverrides);
        setBaselineValues(initialOverrides);
        setModifiedKeys(new Set());
      })
      .catch((err) => toast("Failed to load GSTR-9 computation", "error"))
      .finally(() => setLoading(false));
  }, [token, clientId, selectedFy, toast]);

  // Fetch GSTR-9C reconciliation when tab is active
  useEffect(() => {
    if (!token || !clientId || activeTab !== "gstr9c") return;

    fetchGstr9cReconciliation(clientId, selectedFy, auditedTurnover, auditedItc, auditedTax, token)
      .then((data) => setG9c(data))
      .catch((err) => console.error("GSTR-9C fetch error:", err));
  }, [token, clientId, selectedFy, activeTab, auditedTurnover, auditedItc, auditedTax]);

  const handleOverrideChange = (key: string, val: string) => {
    const num = parseFloat(val) || 0;
    setOverrides((prev) => ({ ...prev, [key]: num }));
    setModifiedKeys((prev) => new Set(prev).add(key));
  };

  const handleResetOverrides = () => {
    setOverrides(baselineValues);
    setModifiedKeys(new Set());
    toast("Reset modified cells to initial values", "info");
  };

  const handleSaveOverrides = async () => {
    if (!token || !clientId) return;
    if (modifiedKeys.size === 0) {
      toast("No cell values were changed", "info");
      return;
    }
    setSaving(true);

    const items: AuditOverrideInput[] = Array.from(modifiedKeys).map((k) => {
      const [table_key, cell_key] = k.split(".");
      return { table_key, cell_key, override_value: overrides[k] ?? 0 };
    });

    try {
      const updated = await saveGstr9Overrides(clientId, selectedFy, items, token);
      setComp(updated);
      setBaselineValues(overrides);
      setModifiedKeys(new Set());
      toast(`Saved ${items.length} CA audit cell override${items.length > 1 ? "s" : ""}`, "success");
    } catch (err: any) {
      toast(err?.detail || "Failed to save overrides", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCheckAvailability = async () => {
    if (!token || !clientId) return;
    setChecking(true);
    try {
      const res = await checkGstr9DataAvailability(clientId, selectedFy, token);
      setComp(res.computation);
      setSyncDetails(res.period_details);
      setShowSyncModal(true);
      toast(`Checked local coverage: ${res.synced_periods_count} of 12 periods available`, "info");
    } catch (err: any) {
      toast(err?.detail || "Failed to check data availability", "error");
    } finally {
      setChecking(false);
    }
  };

  const handleLiveFetchPortalApi = async () => {
    if (!token || !clientId) return;
    setSyncing(true);
    try {
      const res = await fetchLiveGstr9PortalApi(clientId, selectedFy, token);
      setComp(res.computation);
      setSyncDetails(res.period_details);
      setShowSyncModal(true);
      toast(`Live GSTN API Sync: ${res.synced_periods_count} of 12 periods fetched cleanly`, "success");
    } catch (err: any) {
      toast(err?.detail || "Failed to execute live GSTN API fetch", "error");
    } finally {
      setSyncing(false);
    }
  };

  const handleDownloadGstr9Json = async () => {
    if (!token || !clientId) return;
    setDownloadingG9(true);
    try {
      const blob = await downloadGstr9Json(clientId, selectedFy, token);
      const gstin = comp?.gstin || client?.gstin || "GSTIN";
      downloadBlobAsFile(blob, `gstr9_${gstin}_${selectedFy.replace("-", "")}.json`);
      toast("Downloaded GSTR-9 Portal JSON payload", "success");
    } catch (err: any) {
      toast("Failed to download GSTR-9 JSON", "error");
    } finally {
      setDownloadingG9(false);
    }
  };

  const handleDownloadGstr9cJson = async () => {
    if (!token || !clientId) return;
    setDownloadingG9c(true);
    try {
      const blob = await downloadGstr9cJson(clientId, selectedFy, auditedTurnover, auditedItc, auditedTax, token);
      const gstin = comp?.gstin || client?.gstin || "GSTIN";
      downloadBlobAsFile(blob, `gstr9c_${gstin}_${selectedFy.replace("-", "")}.json`);
      toast("Downloaded GSTR-9C JSON payload for DSC signing", "success");
    } catch (err: any) {
      toast("Failed to download GSTR-9C JSON", "error");
    } finally {
      setDownloadingG9c(false);
    }
  };

  const clientTradeName =
    comp?.trade_name || client?.trade_name || client?.legal_name || "Client";
  const clientGstin = comp?.gstin || client?.gstin || "—";
  const schemeType = client?.scheme_type || "regular";

  const t4 = comp?.table4;
  const t5 = comp?.table5;
  const t6 = comp?.table6;
  const t7 = comp?.table7;
  const t8 = comp?.table8;
  const t9 = comp?.table9;

  const t4Total = t4?.["4N_total_taxable"] || 0;
  const t5Total = t5?.["5N_total_exempted"] || 0;
  const t6Total = t6?.["6A_total_3b_itc"] || 0;
  const t7Total = t7?.["7H_total_reversals"] || 0;
  const t8Diff = t8?.["8D_difference"] || 0;
  const t8A2b = t8?.["8A_itc_2b"] || 0;
  const t8B3b = t8?.["8B_itc_3b"] || 0;

  // Detect empty state (no transactions recorded yet for this FY)
  const hasAnyData =
    t4Total > 0 ||
    t5Total > 0 ||
    t6Total > 0 ||
    t7Total > 0 ||
    t8A2b > 0 ||
    t8B3b > 0;

  const syncedCount = useMemo(() => {
    if (!syncDetails) return 0;
    return syncDetails.filter((p) => p.status === "synced").length;
  }, [syncDetails]);

  if (loading) {
    return (
      <div className="flex h-96 flex-col items-center justify-center gap-3">
        <div className="h-9 w-9 animate-spin rounded-full border-4 border-[var(--ink)] border-t-transparent" />
        <p className="text-xs font-semibold text-gray-500">Computing GSTR-9 annual return...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ─── 1. TOP BREADCRUMB & CLIENT IDENTIFICATION HEADER ─── */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200/80 pb-4">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Link href="/clients" className="hover:text-gray-900 transition-colors">
            Clients
          </Link>
          <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
          <Link
            href={`/clients/${clientId}`}
            className="font-semibold text-gray-700 hover:text-gray-900 transition-colors"
          >
            {clientTradeName}
          </Link>
          <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
          <span className="font-semibold text-[var(--ink)]">GSTR-9 Annual Return</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-gray-800 bg-gray-100/90 px-2.5 py-1 rounded-lg border border-gray-200">
            {clientGstin}
          </span>
          <span className="inline-flex items-center rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 border border-emerald-200/60 uppercase tracking-wide">
            {schemeType}
          </span>
        </div>
      </div>

      {/* ─── 2. TITLE & HIERARCHICAL ACTION TOOLBAR ─── */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href={`/clients/${clientId}`}
            title="Back to Client Overview"
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-gray-200 bg-white text-gray-600 transition hover:bg-gray-100 hover:text-gray-900 shadow-sm"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">
              GSTR-9 & GSTR-9C Annual Return Workspace
            </h1>
            <p className="text-xs text-gray-500 sm:text-sm mt-0.5">
              Automated annual return computation, CA cell overrides & official GSTN portal JSON export
            </p>
          </div>
        </div>

        {/* Action Toolbar */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* FY Selector */}
          <div className="relative inline-flex items-center">
            <Calendar className="pointer-events-none absolute left-3 h-3.5 w-3.5 text-gray-400" />
            <select
              value={selectedFy}
              onChange={(e) => setSelectedFy(e.target.value)}
              className="appearance-none rounded-xl border border-gray-200 bg-white py-2 pl-8 pr-8 text-xs font-semibold text-gray-800 shadow-sm transition hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-[var(--ink)]/10"
            >
              {FY_OPTIONS.map((fy) => (
                <option key={fy} value={fy}>
                  FY {fy}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-gray-400" />
          </div>

          {/* Secondary Action: Check Coverage */}
          <button
            type="button"
            onClick={handleCheckAvailability}
            disabled={checking}
            className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 hover:text-gray-900 disabled:opacity-50"
          >
            {checking ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-500" />
            ) : (
              <Layers className="h-3.5 w-3.5 text-gray-500" />
            )}
            <span>Check Coverage</span>
          </button>

          {/* Primary CTA: Fetch Live */}
          <button
            type="button"
            onClick={handleLiveFetchPortalApi}
            disabled={syncing}
            className="inline-flex items-center gap-2 rounded-xl bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-black active:scale-[0.99] disabled:opacity-50"
          >
            {syncing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-white" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5 text-white" />
            )}
            <span>Fetch 12 Months Live</span>
          </button>

          {/* Contextual Action: Save Overrides */}
          <button
            type="button"
            onClick={handleSaveOverrides}
            disabled={saving || modifiedKeys.size === 0}
            className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold shadow-sm transition ${
              modifiedKeys.size > 0
                ? "bg-emerald-600 text-white hover:bg-emerald-700 ring-2 ring-emerald-600/20"
                : "border border-gray-200 bg-gray-50 text-gray-400 cursor-not-allowed"
            }`}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            <span>Save Overrides{modifiedKeys.size > 0 ? ` (${modifiedKeys.size})` : ""}</span>
          </button>

          {/* Export Action: Download JSON */}
          <button
            type="button"
            onClick={handleDownloadGstr9Json}
            disabled={downloadingG9}
            className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 hover:text-gray-900 disabled:opacity-50"
          >
            {downloadingG9 ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-500" />
            ) : (
              <Download className="h-3.5 w-3.5 text-gray-500" />
            )}
            <span>Download GSTR-9 JSON</span>
          </button>
        </div>
      </div>

      {/* ─── 3. SYNC STATUS / EMPTY STATE BANNER ("Wall of Zeroes" Fix) ─── */}
      {!hasAnyData ? (
        <div className="rounded-2xl border border-amber-200/80 bg-amber-50/70 p-4 shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-amber-950">
                No GST transaction data loaded yet for FY {selectedFy}
              </h3>
              <p className="mt-0.5 text-xs text-amber-800/90 leading-relaxed">
                Metric figures currently display ₹0 because monthly returns (GSTR-1, 2B, 3B) haven't been pulled from the GST portal for this financial year yet.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleLiveFetchPortalApi}
            disabled={syncing}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-[var(--ink)] px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-black disabled:opacity-50"
          >
            {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            <span>Fetch from GSTN Portal</span>
          </button>
        </div>
      ) : syncDetails ? (
        <div className="rounded-2xl border border-emerald-200/80 bg-emerald-50/60 px-4 py-3 shadow-sm flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 text-xs font-semibold text-emerald-900">
            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
            <span>
              GST Portal Coverage: {syncedCount} of 12 periods active for FY {selectedFy}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setShowSyncModal(true)}
            className="text-xs font-bold text-emerald-700 underline underline-offset-2 hover:text-emerald-900"
          >
            View Period Breakdown Report
          </button>
        </div>
      ) : null}

      {/* ─── 4. INNER TABS BAR ─── */}
      <div className="border-b border-gray-200/80 bg-white px-2 sm:px-4 rounded-2xl shadow-sm">
        <nav className="-mb-px flex space-x-1 sm:space-x-4 overflow-x-auto no-scrollbar">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 whitespace-nowrap py-3.5 px-3 border-b-2 font-medium text-xs sm:text-sm transition-all ${
                  active
                    ? "border-[var(--ink)] text-[var(--ink)] font-bold"
                    : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
                }`}
              >
                <Icon className={`h-4 w-4 ${active ? "text-[var(--ink)]" : "text-gray-400"}`} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* ─── TAB 1: GSTR-9 OVERVIEW ─── */}
      {activeTab === "summary" && (
        <div className="space-y-6">
          {/* 6 High-Polish Metric Cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* 1. Taxable Outward */}
            <div className="dashboard-card border border-gray-200/70 p-5 transition hover:shadow-md">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                  Taxable Outward (Table 4)
                </span>
                <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[10px] font-semibold text-gray-600">
                  With Tax
                </span>
              </div>
              <p className="mt-2.5 text-2xl font-bold tracking-tight text-gray-900">
                {formatINR(t4Total)}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                B2B, B2C, SEZ & Export supplies liable to tax
              </p>
            </div>

            {/* 2. Exempt Outward */}
            <div className="dashboard-card border border-gray-200/70 p-5 transition hover:shadow-md">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                  Exempt Outward (Table 5)
                </span>
                <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[10px] font-semibold text-gray-600">
                  Zero / Exempt
                </span>
              </div>
              <p className="mt-2.5 text-2xl font-bold tracking-tight text-gray-900">
                {formatINR(t5Total)}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                Exempted, nil-rated & non-GST supplies
              </p>
            </div>

            {/* 3. ITC Availed */}
            <div className="dashboard-card border border-gray-200/70 p-5 transition hover:shadow-md">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                  ITC Availed (Table 6)
                </span>
                <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                  GSTR-3B Auto
                </span>
              </div>
              <p className="mt-2.5 text-2xl font-bold tracking-tight text-gray-900">
                {formatINR(t6Total)}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                Inputs, capital goods & inward RCM credit
              </p>
            </div>

            {/* 4. ITC Reversals */}
            <div className="dashboard-card border border-gray-200/70 p-5 transition hover:shadow-md">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                  ITC Reversals (Table 7)
                </span>
                <span className="rounded-md bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                  Rule 37 / 42 / 43
                </span>
              </div>
              <p className="mt-2.5 text-2xl font-bold tracking-tight text-gray-900">
                {formatINR(t7Total)}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                Blocked credit under Sec 17(5) & other reversals
              </p>
            </div>

            {/* 5. 2B vs 3B Variance */}
            <div className="dashboard-card border border-gray-200/70 p-5 transition hover:shadow-md">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                  2B vs 3B Variance (Table 8D)
                </span>
                <span
                  className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${
                    t8Diff === 0
                      ? "bg-gray-100 text-gray-700"
                      : t8Diff < 0
                      ? "bg-red-50 text-red-700 border border-red-200/60"
                      : "bg-amber-50 text-amber-700 border border-amber-200/60"
                  }`}
                >
                  {t8Diff === 0
                    ? "✓ Balanced"
                    : t8Diff < 0
                    ? "⚠️ Excess 3B Availed"
                    : "ℹ️ Unclaimed Credit"}
                </span>
              </div>
              <p
                className={`mt-2.5 text-2xl font-bold tracking-tight ${
                  t8Diff < 0 ? "text-red-600" : "text-gray-900"
                }`}
              >
                {formatINR(t8Diff)}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                Auto 2B ({formatINR(t8A2b)}) − 3B availed ({formatINR(t8B3b)})
              </p>
            </div>

            {/* 6. CA Audit Overrides */}
            <div className="dashboard-card border border-gray-200/70 p-5 transition hover:shadow-md">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                  CA Audit Cell Overrides
                </span>
                <span className="rounded-md bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700">
                  {comp?.overrides_count || 0} Saved
                </span>
              </div>
              <p className="mt-2.5 text-2xl font-bold tracking-tight text-gray-900">
                {comp?.overrides_count || 0}{" "}
                <span className="text-sm font-normal text-gray-500">active cells</span>
              </p>
              <p className="mt-1 text-xs text-gray-500">
                Manual cell adjustments preserved for portal JSON
              </p>
            </div>
          </div>

          {/* Quick Review Navigation Card */}
          <div className="dashboard-card border border-gray-200/70 p-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-gray-900">Annual Return Audit Workflow</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  Follow the standard statutory audit steps to verify outward supplies, ITC recon, and tax payments.
                </p>
              </div>
              <button
                onClick={() => setActiveTab("table4_5")}
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-black"
              >
                <span>Start Reviewing Table 4 & 5</span>
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-4">
              <div
                onClick={() => setActiveTab("table4_5")}
                className="cursor-pointer rounded-xl border border-gray-200 bg-gray-50/50 p-3.5 transition hover:bg-white hover:shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-800">1. Outward Supplies</span>
                  <ArrowUpRight className="h-4 w-4 text-gray-400" />
                </div>
                <p className="mt-1 text-[11px] text-gray-500">Tables 4 & 5 turnover verification</p>
              </div>

              <div
                onClick={() => setActiveTab("table6_7_8")}
                className="cursor-pointer rounded-xl border border-gray-200 bg-gray-50/50 p-3.5 transition hover:bg-white hover:shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-800">2. ITC & Reconciliation</span>
                  <ArrowDownLeft className="h-4 w-4 text-gray-400" />
                </div>
                <p className="mt-1 text-[11px] text-gray-500">Table 8 2B vs 3B credit audit</p>
              </div>

              <div
                onClick={() => setActiveTab("table9")}
                className="cursor-pointer rounded-xl border border-gray-200 bg-gray-50/50 p-3.5 transition hover:bg-white hover:shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-800">3. Tax Paid Details</span>
                  <Receipt className="h-4 w-4 text-gray-400" />
                </div>
                <p className="mt-1 text-[11px] text-gray-500">Cash vs credit utilization</p>
              </div>

              <div
                onClick={() => setActiveTab("gstr9c")}
                className="cursor-pointer rounded-xl border border-gray-200 bg-gray-50/50 p-3.5 transition hover:bg-white hover:shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-800">4. GSTR-9C Statement</span>
                  <ShieldCheck className="h-4 w-4 text-gray-400" />
                </div>
                <p className="mt-1 text-[11px] text-gray-500">Audited financial reconciliation</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── TAB 2: TABLE 4 & 5 (OUTWARD) ─── */}
      {activeTab === "table4_5" && (
        <div className="space-y-6">
          {/* Modified Notice Bar if changes exist */}
          {modifiedKeys.size > 0 && (
            <div className="flex items-center justify-between rounded-xl bg-amber-50 border border-amber-200 px-4 py-2.5 text-xs text-amber-900">
              <span className="font-semibold">
                You have {modifiedKeys.size} unsaved cell modification{modifiedKeys.size > 1 ? "s" : ""}.
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleResetOverrides}
                  className="rounded-lg px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-amber-100"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={handleSaveOverrides}
                  disabled={saving}
                  className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-700"
                >
                  {saving ? "Saving..." : "Save Overrides"}
                </button>
              </div>
            </div>
          )}

          {/* Table 4: Taxable Outward Supplies */}
          <div className="dashboard-card border border-gray-200/70 p-6">
            <div className="flex items-center justify-between mb-4 border-b border-gray-100 pb-3">
              <div>
                <h2 className="text-base font-bold text-gray-900">
                  Table 4: Details of Outward Taxable Supplies
                </h2>
                <p className="text-xs text-gray-500">
                  Supplies on which tax is payable (derived from GSTR-1 filings with CA override support)
                </p>
              </div>
              <span className="text-xs font-bold text-gray-700 bg-gray-100 px-2.5 py-1 rounded-md">
                Total: {formatINR(t4Total)}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {[
                { key: "table4.4A_b2c", label: "4A. Supplies made to Unregistered Persons (B2C)" },
                { key: "table4.4B_b2b", label: "4B. Supplies made to Registered Persons (B2B)" },
                { key: "table4.4C_exports_paid", label: "4C. Zero Rated Supplies (Exports) on Tax Payment" },
                { key: "table4.4D_sez_paid", label: "4D. SEZ Supplies on Tax Payment" },
                { key: "table4.4E_deemed_exports", label: "4E. Deemed Exports" },
                { key: "table4.4F_advances", label: "4F. Advances on which tax has been paid" },
                { key: "table4.4G_rcm_inward", label: "4G. Inward supplies liable to RCM" },
              ].map(({ key, label }) => {
                const isModified = modifiedKeys.has(key);
                const baseline = baselineValues[key] ?? 0;
                return (
                  <div key={key} className="flex flex-col gap-1.5 rounded-xl border border-gray-200/80 bg-gray-50/40 p-3.5">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-gray-800">{label}</label>
                      {isModified && (
                        <span className="text-[10px] font-bold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                          Modified
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        value={overrides[key] ?? 0}
                        onChange={(e) => handleOverrideChange(key, e.target.value)}
                        className={`w-full rounded-lg border bg-white px-3 py-1.5 text-sm font-semibold text-gray-900 shadow-sm transition focus:outline-none focus:ring-2 ${
                          isModified
                            ? "border-amber-400 focus:ring-amber-200"
                            : "border-gray-300 focus:ring-indigo-100"
                        }`}
                      />
                    </div>
                    <span className="text-[11px] text-gray-400">
                      Baseline computed: {formatINR(baseline)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Table 5: Non-Taxable / Exempt Supplies */}
          <div className="dashboard-card border border-gray-200/70 p-6">
            <div className="flex items-center justify-between mb-4 border-b border-gray-100 pb-3">
              <div>
                <h2 className="text-base font-bold text-gray-900">
                  Table 5: Details of Outward Supplies without Tax
                </h2>
                <p className="text-xs text-gray-500">
                  Zero-rated without payment, exempted, nil-rated, and non-GST outward supplies
                </p>
              </div>
              <span className="text-xs font-bold text-gray-700 bg-gray-100 px-2.5 py-1 rounded-md">
                Total: {formatINR(t5Total)}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {[
                { key: "table5.5A_exports_unpaid", label: "5A. Zero Rated Supplies (Exports) without Payment" },
                { key: "table5.5B_sez_unpaid", label: "5B. Supply to SEZs without Payment of Tax" },
                { key: "table5.5C_rcm_outward", label: "5C. Supplies on which recipient pays tax on RCM" },
                { key: "table5.5D_exempted", label: "5D. Exempted Supplies" },
                { key: "table5.5E_nil_rated", label: "5E. Nil Rated Supplies" },
                { key: "table5.5F_non_gst", label: "5F. Non-GST Supplies (including no-supply)" },
              ].map(({ key, label }) => {
                const isModified = modifiedKeys.has(key);
                const baseline = baselineValues[key] ?? 0;
                return (
                  <div key={key} className="flex flex-col gap-1.5 rounded-xl border border-gray-200/80 bg-gray-50/40 p-3.5">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-gray-800">{label}</label>
                      {isModified && (
                        <span className="text-[10px] font-bold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                          Modified
                        </span>
                      )}
                    </div>
                    <input
                      type="number"
                      value={overrides[key] ?? 0}
                      onChange={(e) => handleOverrideChange(key, e.target.value)}
                      className={`w-full rounded-lg border bg-white px-3 py-1.5 text-sm font-semibold text-gray-900 shadow-sm transition focus:outline-none focus:ring-2 ${
                        isModified
                          ? "border-amber-400 focus:ring-amber-200"
                          : "border-gray-300 focus:ring-indigo-100"
                      }`}
                    />
                    <span className="text-[11px] text-gray-400">
                      Baseline computed: {formatINR(baseline)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ─── TAB 3: TABLE 6, 7 & 8 (ITC & RECON) ─── */}
      {activeTab === "table6_7_8" && (
        <div className="space-y-6">
          {/* Table 8: 2B vs 3B Reconciliation Snapshot */}
          <div className="dashboard-card border border-gray-200/70 p-6">
            <div className="mb-4 border-b border-gray-100 pb-3">
              <h2 className="text-base font-bold text-gray-900">
                Table 8: GSTR-2B vs GSTR-3B Annual Reconciliation
              </h2>
              <p className="text-xs text-gray-500">
                Statutory reconciliation of auto-drafted ITC (Table 8A) against credit availed in GSTR-3B (Table 8B)
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-4">
                <span className="text-xs text-gray-500 uppercase font-semibold">8A. ITC as per GSTR-2B</span>
                <p className="text-xl font-bold text-gray-900 mt-1">{formatINR(t8A2b)}</p>
                <p className="text-[11px] text-gray-400 mt-0.5">Auto-drafted from supplier GSTR-1s</p>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-4">
                <span className="text-xs text-gray-500 uppercase font-semibold">8B. ITC as per GSTR-3B</span>
                <p className="text-xl font-bold text-gray-900 mt-1">{formatINR(t8B3b)}</p>
                <p className="text-[11px] text-gray-400 mt-0.5">Total credit availed across 12 periods</p>
              </div>

              <div
                className={`rounded-xl border p-4 ${
                  t8Diff < 0
                    ? "border-red-200 bg-red-50/50"
                    : "border-emerald-200 bg-emerald-50/50"
                }`}
              >
                <span
                  className={`text-xs uppercase font-semibold ${
                    t8Diff < 0 ? "text-red-700" : "text-emerald-800"
                  }`}
                >
                  8D. Variance [8A − 8B]
                </span>
                <p
                  className={`text-xl font-bold mt-1 ${
                    t8Diff < 0 ? "text-red-700" : "text-emerald-900"
                  }`}
                >
                  {formatINR(t8Diff)}
                </p>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  {t8Diff < 0 ? "Potential tax demand / reversal risk" : "Credit balanced or unavailed"}
                </p>
              </div>
            </div>
          </div>

          {/* Table 6: Details of ITC Availed */}
          <div className="dashboard-card border border-gray-200/70 p-6">
            <div className="flex items-center justify-between mb-4 border-b border-gray-100 pb-3">
              <div>
                <h2 className="text-base font-bold text-gray-900">
                  Table 6: Details of ITC Availed during the Financial Year
                </h2>
                <p className="text-xs text-gray-500">
                  Categorization into Inputs, Capital Goods, Services, and Inward RCM
                </p>
              </div>
              <span className="text-xs font-bold text-gray-700 bg-gray-100 px-2.5 py-1 rounded-md">
                Total 3B ITC: {formatINR(t6Total)}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {[
                { key: "table6.6B_b2b_inputs", label: "6B. Inward supplies (other than imports & RCM)" },
                { key: "table6.6C_rcm_unregistered", label: "6C. Inward supplies from unregistered persons (RCM)" },
                { key: "table6.6D_rcm_registered", label: "6D. Inward supplies from registered persons (RCM)" },
                { key: "table6.6E_import_goods", label: "6E. Import of goods (including SEZ)" },
                { key: "table6.6F_import_services", label: "6F. Import of services (excluding SEZ)" },
              ].map(({ key, label }) => {
                const isModified = modifiedKeys.has(key);
                const baseline = baselineValues[key] ?? 0;
                return (
                  <div key={key} className="flex flex-col gap-1.5 rounded-xl border border-gray-200/80 bg-gray-50/40 p-3.5">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-gray-800">{label}</label>
                      {isModified && (
                        <span className="text-[10px] font-bold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                          Modified
                        </span>
                      )}
                    </div>
                    <input
                      type="number"
                      value={overrides[key] ?? 0}
                      onChange={(e) => handleOverrideChange(key, e.target.value)}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-semibold text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-100"
                    />
                    <span className="text-[11px] text-gray-400">Baseline computed: {formatINR(baseline)}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Table 7: Details of ITC Reversed */}
          <div className="dashboard-card border border-gray-200/70 p-6">
            <div className="flex items-center justify-between mb-4 border-b border-gray-100 pb-3">
              <div>
                <h2 className="text-base font-bold text-gray-900">
                  Table 7: Details of ITC Reversed & Ineligible ITC
                </h2>
                <p className="text-xs text-gray-500">
                  Reversals under statutory rules (Rule 37, 42, 43, and Section 17(5))
                </p>
              </div>
              <span className="text-xs font-bold text-gray-700 bg-gray-100 px-2.5 py-1 rounded-md">
                Total Reversals: {formatINR(t7Total)}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {[
                { key: "table7.7A_rule37", label: "7A. Rule 37 (180 days default)" },
                { key: "table7.7D_sec17_5", label: "7D. Section 17(5) Blocked" },
                { key: "table7.7E_other_reversals", label: "7E. Other Reversals" },
              ].map(({ key, label }) => {
                const isModified = modifiedKeys.has(key);
                const baseline = baselineValues[key] ?? 0;
                return (
                  <div key={key} className="flex flex-col gap-1.5 rounded-xl border border-gray-200/80 bg-gray-50/40 p-3.5">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-gray-800">{label}</label>
                      {isModified && (
                        <span className="text-[10px] font-bold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                          Modified
                        </span>
                      )}
                    </div>
                    <input
                      type="number"
                      value={overrides[key] ?? 0}
                      onChange={(e) => handleOverrideChange(key, e.target.value)}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-semibold text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-100"
                    />
                    <span className="text-[11px] text-gray-400">Baseline: {formatINR(baseline)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ─── TAB 4: TABLE 9 (TAX PAID) ─── */}
      {activeTab === "table9" && (
        <div className="dashboard-card border border-gray-200/70 p-6 space-y-4">
          <div className="border-b border-gray-100 pb-3">
            <h2 className="text-base font-bold text-gray-900">
              Table 9: Details of Tax Paid as Declared in Returns Filed
            </h2>
            <p className="text-xs text-gray-500">
              Breakdown of statutory tax liability paid through cash ledger versus ITC ledger
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-xs font-bold uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3 text-left">Tax Head</th>
                  <th className="px-4 py-3 text-right">Tax Payable (₹)</th>
                  <th className="px-4 py-3 text-right">Paid in Cash (₹)</th>
                  <th className="px-4 py-3 text-right">Paid via ITC (₹)</th>
                  <th className="px-4 py-3 text-right">Total Discharged (₹)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white font-semibold">
                <tr>
                  <td className="px-4 py-3.5 text-left text-gray-800">Integrated Tax (IGST)</td>
                  <td className="px-4 py-3.5 text-right text-gray-900">{formatINR(t9?.igst_payable || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-gray-700">{formatINR(t9?.igst_cash || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-gray-700">{formatINR(t9?.igst_itc || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-emerald-700">
                    {formatINR((t9?.igst_cash || 0) + (t9?.igst_itc || 0))}
                  </td>
                </tr>
                <tr>
                  <td className="px-4 py-3.5 text-left text-gray-800">Central Tax (CGST)</td>
                  <td className="px-4 py-3.5 text-right text-gray-900">{formatINR(t9?.cgst_payable || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-gray-700">{formatINR(t9?.cgst_cash || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-gray-700">{formatINR(t9?.cgst_itc || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-emerald-700">
                    {formatINR((t9?.cgst_cash || 0) + (t9?.cgst_itc || 0))}
                  </td>
                </tr>
                <tr>
                  <td className="px-4 py-3.5 text-left text-gray-800">State Tax (SGST)</td>
                  <td className="px-4 py-3.5 text-right text-gray-900">{formatINR(t9?.sgst_payable || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-gray-700">{formatINR(t9?.sgst_cash || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-gray-700">{formatINR(t9?.sgst_itc || 0)}</td>
                  <td className="px-4 py-3.5 text-right text-emerald-700">
                    {formatINR((t9?.sgst_cash || 0) + (t9?.sgst_itc || 0))}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ─── TAB 5: GSTR-9C AUDIT STATEMENT ─── */}
      {activeTab === "gstr9c" && (
        <div className="space-y-6">
          <div className="dashboard-card border border-gray-200/70 p-6 space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 pb-3">
              <div>
                <h2 className="text-base font-bold text-gray-900">
                  GSTR-9C Audited Financial Statement Reconciliation
                </h2>
                <p className="text-xs text-gray-500">
                  Reconciliation of gross turnover, ITC, and tax liability against audited books of accounts
                </p>
              </div>
              <button
                type="button"
                onClick={handleDownloadGstr9cJson}
                disabled={downloadingG9c}
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--ink)] px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-black disabled:opacity-50"
              >
                {downloadingG9c ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                <span>Download GSTR-9C JSON (DSC Signing)</span>
              </button>
            </div>

            {/* Audited Baseline Inputs */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-gray-200 bg-gray-50/50 p-4">
                <label className="text-xs font-semibold text-gray-800">
                  Audited Gross Turnover (₹)
                </label>
                <input
                  type="number"
                  value={auditedTurnover}
                  onChange={(e) => setAuditedTurnover(parseFloat(e.target.value) || 0)}
                  className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/50 p-4">
                <label className="text-xs font-semibold text-gray-800">
                  Audited Net ITC (₹)
                </label>
                <input
                  type="number"
                  value={auditedItc}
                  onChange={(e) => setAuditedItc(parseFloat(e.target.value) || 0)}
                  className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/50 p-4">
                <label className="text-xs font-semibold text-gray-800">
                  Audited Tax Payable (₹)
                </label>
                <input
                  type="number"
                  value={auditedTax}
                  onChange={(e) => setAuditedTax(parseFloat(e.target.value) || 0)}
                  className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-100"
                />
              </div>
            </div>

            {/* Reconciliation Variances */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <span className="text-xs text-gray-500 uppercase font-semibold">
                  5R. Turnover Variance
                </span>
                <p className="text-xl font-bold text-gray-900 mt-1">
                  {formatINR(g9c?.part_ii_turnover["5R_unreconciled_turnover_variance"] || 0)}
                </p>
                <p className="text-[11px] text-gray-400 mt-0.5">Audited books vs GSTR-9 declared</p>
              </div>

              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <span className="text-xs text-gray-500 uppercase font-semibold">
                  12G. ITC Variance
                </span>
                <p className="text-xl font-bold text-gray-900 mt-1">
                  {formatINR(g9c?.part_iii_itc["12G_unreconciled_itc_variance"] || 0)}
                </p>
                <p className="text-[11px] text-gray-400 mt-0.5">Audited ITC vs GSTR-9 availed</p>
              </div>

              <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4 shadow-sm">
                <span className="text-xs text-indigo-800 uppercase font-semibold">
                  Part V. Recommended Auditor Tax
                </span>
                <p className="text-xl font-bold text-indigo-950 mt-1">
                  {formatINR(g9c?.part_v_auditor_recommendation.total_recommended_payment || 0)}
                </p>
                <p className="text-[11px] text-indigo-700/80 mt-0.5">Additional tax to pay via DRC-03</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── 5. 12-MONTH PORTAL SYNC DIAGNOSTICS MODAL ─── */}
      {showSyncModal && syncDetails && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h3 className="text-base font-bold text-gray-900">
                  FY {selectedFy} GST Portal Sync Report
                </h3>
                <p className="text-xs text-gray-500">
                  Per-period coverage check for 12 monthly tax returns (GSTR-2B & GSTR-3B)
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowSyncModal(false)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[55vh] overflow-y-auto p-6 space-y-2.5">
              {syncDetails.map((item) => (
                <div
                  key={item.period}
                  className="flex items-center justify-between gap-4 rounded-xl border border-gray-200/80 bg-gray-50/50 p-3.5 transition hover:bg-white hover:shadow-sm"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-bold ${
                        item.status === "synced"
                          ? "bg-emerald-100 text-emerald-800"
                          : item.status === "missing"
                          ? "bg-red-100 text-red-800"
                          : "bg-amber-100 text-amber-800"
                      }`}
                    >
                      {item.status === "synced"
                        ? "Synced"
                        : item.status === "missing"
                        ? "Missing"
                        : "Partial"}
                    </span>
                    <div>
                      <h4 className="text-xs font-bold text-gray-900">{item.month_label}</h4>
                      <p className="text-[11px] text-gray-500">{item.reason}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 text-xs font-semibold text-gray-500">
                    <span className={item.has_2b ? "text-emerald-700 font-bold" : "text-gray-400"}>
                      2B {item.has_2b ? "✓" : "✗"}
                    </span>
                    <span className="text-gray-300">•</span>
                    <span className={item.has_3b ? "text-emerald-700 font-bold" : "text-gray-400"}>
                      3B {item.has_3b ? "✓" : "✗"}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            <div className="border-t border-gray-200 bg-gray-50 px-6 py-3.5 flex items-center justify-between">
              <span className="text-xs font-medium text-gray-500">
                {syncedCount} of 12 periods available
              </span>
              <button
                type="button"
                onClick={() => setShowSyncModal(false)}
                className="rounded-xl bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-black"
              >
                Close Report
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Gstr9WorkspacePage() {
  return (
    <Suspense
      fallback={
        <div className="h-64 animate-pulse rounded-2xl bg-gray-100" />
      }
    >
      <Gstr9WorkspaceContent />
    </Suspense>
  );
}
