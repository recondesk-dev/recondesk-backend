"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
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
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { formatINR } from "@/lib/format";
import { downloadBlobAsFile } from "@/lib/download";
import { useToast } from "@/components/providers/ToastProvider";
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

export default function Gstr9WorkspacePage() {
  const params = useParams();
  const clientId = String(params.id);
  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const toast = useToast();

  const [selectedFy, setSelectedFy] = useState("2025-26");
  const [activeTab, setActiveTab] = useState<"summary" | "table4_5" | "table6_7_8" | "table9" | "gstr9c">("summary");

  const [comp, setComp] = useState<Gstr9Computation | null>(null);
  const [g9c, setG9c] = useState<Gstr9cReconciliation | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncDetails, setSyncDetails] = useState<PeriodSyncDetail[] | null>(null);
  const [downloadingG9, setDownloadingG9] = useState(false);
  const [downloadingG9c, setDownloadingG9c] = useState(false);

  // Local state for GSTR-9 Overrides
  const [overrides, setOverrides] = useState<Record<string, number>>({});

  // Local state for GSTR-9C inputs
  const [auditedTurnover, setAuditedTurnover] = useState<number>(0);
  const [auditedItc, setAuditedItc] = useState<number>(0);
  const [auditedTax, setAuditedTax] = useState<number>(0);

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
      })
      .catch((err) => toast("Failed to load GSTR-9 computation", "error"))
      .finally(() => setLoading(false));
  }, [token, clientId, selectedFy, toast]);

  useEffect(() => {
    if (!token || !clientId || activeTab !== "gstr9c") return;

    fetchGstr9cReconciliation(clientId, selectedFy, auditedTurnover, auditedItc, auditedTax, token)
      .then((data) => setG9c(data))
      .catch((err) => console.error("GSTR-9C fetch error:", err));
  }, [token, clientId, selectedFy, activeTab, auditedTurnover, auditedItc, auditedTax]);

  // Track keys modified by user
  const [modifiedKeys, setModifiedKeys] = useState<Set<string>>(new Set());

  const handleOverrideChange = (key: string, val: string) => {
    const num = parseFloat(val) || 0;
    setOverrides((prev) => ({ ...prev, [key]: num }));
    setModifiedKeys((prev) => new Set(prev).add(key));
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
      const gstin = comp?.gstin || "GSTIN";
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
      const gstin = comp?.gstin || "GSTIN";
      downloadBlobAsFile(blob, `gstr9c_${gstin}_${selectedFy.replace("-", "")}.json`);
      toast("Downloaded GSTR-9C JSON payload for DSC signing", "success");
    } catch (err: any) {
      toast("Failed to download GSTR-9C JSON", "error");
    } finally {
      setDownloadingG9c(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

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

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href={`/clients/${clientId}`}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-600 transition hover:bg-gray-200"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">GSTR-9 & GSTR-9C Annual Module</h1>
            <p className="text-sm text-gray-500">
              System computation, CA audit cell overrides & official GSTN portal JSON export
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedFy}
            onChange={(e) => setSelectedFy(e.target.value)}
            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-700 shadow-sm"
          >
            {FY_OPTIONS.map((fy) => (
              <option key={fy} value={fy}>
                FY {fy}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={handleCheckAvailability}
            disabled={checking}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 disabled:opacity-50"
          >
            {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Layers className="h-4 w-4 text-gray-500" />}
            Check Available Data
          </button>

          <button
            type="button"
            onClick={handleLiveFetchPortalApi}
            disabled={syncing}
            className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-purple-700 disabled:opacity-50"
          >
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Fetch 12 Months Live (Portal API)
          </button>

          <button
            type="button"
            onClick={handleSaveOverrides}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save Overrides
          </button>

          <button
            type="button"
            onClick={handleDownloadGstr9Json}
            disabled={downloadingG9}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
          >
            {downloadingG9 ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Download GSTR-9 JSON
          </button>
        </div>
      </div>

      {/* Tabs Bar */}
      <div className="mb-6 border-b border-gray-200 bg-white shadow-sm rounded-t-xl px-4">
        <nav className="-mb-px flex space-x-8">
          {[
            { id: "summary", label: "GSTR-9 Overview" },
            { id: "table4_5", label: "Table 4 & 5 (Outward Supplies)" },
            { id: "table6_7_8", label: "Table 6, 7 & 8 (ITC & Recon)" },
            { id: "table9", label: "Table 9 (Tax Paid)" },
            { id: "gstr9c", label: "GSTR-9C Audit Statement" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600 font-semibold"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* TAB 1: SUMMARY */}
      {activeTab === "summary" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
              <span className="text-xs font-bold uppercase tracking-wider text-gray-500">Taxable Outward (Table 4)</span>
              <p className="mt-2 text-2xl font-bold text-gray-900">{formatINR(t4Total)}</p>
            </div>
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
              <span className="text-xs font-bold uppercase tracking-wider text-gray-500">Exempt Outward (Table 5)</span>
              <p className="mt-2 text-2xl font-bold text-gray-900">{formatINR(t5Total)}</p>
            </div>
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
              <span className="text-xs font-bold uppercase tracking-wider text-green-700">ITC Availed (Table 6)</span>
              <p className="mt-2 text-2xl font-bold text-green-700">{formatINR(t6Total)}</p>
            </div>
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
              <span className="text-xs font-bold uppercase tracking-wider text-amber-700">ITC Reversals (Table 7)</span>
              <p className="mt-2 text-2xl font-bold text-amber-700">{formatINR(t7Total)}</p>
            </div>
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
              <span className="text-xs font-bold uppercase tracking-wider text-indigo-700">2B Table 8A vs 3B Variance</span>
              <p className={`mt-2 text-2xl font-bold ${t8Diff < 0 ? "text-red-600" : "text-gray-900"}`}>
                {formatINR(t8Diff)}
              </p>
            </div>
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
              <span className="text-xs font-bold uppercase tracking-wider text-gray-500">CA Audit Overrides</span>
              <p className="mt-2 text-2xl font-bold text-indigo-600">{comp?.overrides_count || 0} active</p>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: TABLE 4 & 5 (OUTWARD) */}
      {activeTab === "table4_5" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
            <h2 className="text-lg font-bold text-gray-900 mb-4">Table 4: Details of Outward Taxable Supplies</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {[
                { key: "table4.4A_b2c", label: "4A. Supplies made to Unregistered Persons (B2C)" },
                { key: "table4.4B_b2b", label: "4B. Supplies made to Registered Persons (B2B)" },
                { key: "table4.4C_exports_paid", label: "4C. Zero Rated Supplies (Exports) on Tax Payment" },
                { key: "table4.4D_sez_paid", label: "4D. SEZ Supplies on Tax Payment" },
                { key: "table4.4E_deemed_exports", label: "4E. Deemed Exports" },
                { key: "table4.4F_advances", label: "4F. Advances on which tax has been paid" },
                { key: "table4.4G_rcm_inward", label: "4G. Inward supplies liable to RCM" },
              ].map(({ key, label }) => (
                <div key={key} className="flex flex-col gap-1">
                  <label className="text-xs font-semibold text-gray-700">{label}</label>
                  <input
                    type="number"
                    value={overrides[key] ?? 0}
                    onChange={(e) => handleOverrideChange(key, e.target.value)}
                    className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-900 focus:border-indigo-500 focus:ring-indigo-500"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: TABLE 6, 7 & 8 (ITC & RECON) */}
      {activeTab === "table6_7_8" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
            <h2 className="text-lg font-bold text-gray-900 mb-4">Table 8: GSTR-2B vs GSTR-3B Reconciliation</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-lg bg-gray-50 p-4">
                <span className="text-xs text-gray-500 uppercase font-bold">8A. ITC as per GSTR-2B</span>
                <p className="text-xl font-bold text-gray-900 mt-1">{formatINR(t8?.["8A_itc_2b"] || 0)}</p>
              </div>
              <div className="rounded-lg bg-gray-50 p-4">
                <span className="text-xs text-gray-500 uppercase font-bold">8B. ITC as per GSTR-3B</span>
                <p className="text-xl font-bold text-gray-900 mt-1">{formatINR(t8?.["8B_itc_3b"] || 0)}</p>
              </div>
              <div className="rounded-lg bg-indigo-50 p-4">
                <span className="text-xs text-indigo-700 uppercase font-bold">8D. Variance (8A − 8B)</span>
                <p className={`text-xl font-bold mt-1 ${t8Diff < 0 ? "text-red-600" : "text-indigo-900"}`}>
                  {formatINR(t8Diff)}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: TABLE 9 (TAX PAID) */}
      {activeTab === "table9" && (
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
          <h2 className="text-lg font-bold text-gray-900 mb-4">Table 9: Details of Tax Paid (Cash vs Credit)</h2>
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-xs font-bold uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3 text-left">Tax Head</th>
                <th className="px-4 py-3 text-right">Tax Payable (₹)</th>
                <th className="px-4 py-3 text-right">Paid in Cash (₹)</th>
                <th className="px-4 py-3 text-right">Paid via ITC (₹)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white font-semibold">
              <tr>
                <td className="px-4 py-3 text-left">IGST</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.igst_payable || 0)}</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.igst_cash || 0)}</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.igst_itc || 0)}</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-left">CGST</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.cgst_payable || 0)}</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.cgst_cash || 0)}</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.cgst_itc || 0)}</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-left">SGST</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.sgst_payable || 0)}</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.sgst_cash || 0)}</td>
                <td className="px-4 py-3 text-right">{formatINR(t9?.sgst_itc || 0)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* TAB 5: GSTR-9C AUDIT STATEMENT */}
      {activeTab === "gstr9c" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-gray-900">GSTR-9C Audited Financial Statement Reconciliation</h2>
              <button
                type="button"
                onClick={handleDownloadGstr9cJson}
                disabled={downloadingG9c}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
              >
                {downloadingG9c ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Download GSTR-9C JSON (DSC Signing)
              </button>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 mb-6">
              <div>
                <label className="text-xs font-semibold text-gray-700">Audited Gross Turnover (₹)</label>
                <input
                  type="number"
                  value={auditedTurnover}
                  onChange={(e) => setAuditedTurnover(parseFloat(e.target.value) || 0)}
                  className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-900"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700">Audited Net ITC (₹)</label>
                <input
                  type="number"
                  value={auditedItc}
                  onChange={(e) => setAuditedItc(parseFloat(e.target.value) || 0)}
                  className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-900"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700">Audited Tax Payable (₹)</label>
                <input
                  type="number"
                  value={auditedTax}
                  onChange={(e) => setAuditedTax(parseFloat(e.target.value) || 0)}
                  className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-900"
                />
              </div>
            </div>

            {/* Reconciliation Summary Cards */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-lg bg-gray-50 p-4">
                <span className="text-xs text-gray-500 uppercase font-bold">5R. Turnover Variance</span>
                <p className="text-xl font-bold text-gray-900 mt-1">
                  {formatINR(g9c?.part_ii_turnover["5R_unreconciled_turnover_variance"] || 0)}
                </p>
              </div>
              <div className="rounded-lg bg-gray-50 p-4">
                <span className="text-xs text-gray-500 uppercase font-bold">12G. ITC Variance</span>
                <p className="text-xl font-bold text-gray-900 mt-1">
                  {formatINR(g9c?.part_iii_itc["12G_unreconciled_itc_variance"] || 0)}
                </p>
              </div>
              <div className="rounded-lg bg-indigo-50 p-4">
                <span className="text-xs text-indigo-700 uppercase font-bold">Recommended Auditor Tax</span>
                <p className="text-xl font-bold text-indigo-900 mt-1">
                  {formatINR(g9c?.part_v_auditor_recommendation.total_recommended_payment || 0)}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 12-Month Portal Sync Diagnostics Modal */}
      {syncDetails && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">FY {selectedFy} GST Portal Sync Report</h3>
                <p className="text-xs text-gray-500">Per-period diagnostic breakdown for 12 tax periods</p>
              </div>
              <button
                type="button"
                onClick={() => setSyncDetails(null)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[60vh] overflow-y-auto p-6 space-y-3">
              {syncDetails.map((item) => (
                <div
                  key={item.period}
                  className="flex items-center justify-between gap-4 rounded-xl border border-gray-200 bg-gray-50 p-4 transition hover:bg-white hover:shadow-sm"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${
                        item.status === "synced"
                          ? "bg-green-100 text-green-800"
                          : item.status === "missing"
                          ? "bg-red-100 text-red-800"
                          : "bg-amber-100 text-amber-800"
                      }`}
                    >
                      {item.status === "synced"
                        ? "Synced"
                        : item.status === "missing"
                        ? "No Portal Data"
                        : "Partial Sync"}
                    </span>
                    <div>
                      <h4 className="text-sm font-bold text-gray-900">{item.month_label}</h4>
                      <p className="text-xs text-gray-600 mt-0.5">{item.reason}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-xs font-semibold text-gray-500">
                    <span className={item.has_2b ? "text-green-700 font-bold" : "text-gray-400"}>
                      2B {item.has_2b ? "✓" : "✗"}
                    </span>
                    <span>•</span>
                    <span className={item.has_3b ? "text-green-700 font-bold" : "text-gray-400"}>
                      3B {item.has_3b ? "✓" : "✗"}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            <div className="border-t border-gray-200 bg-gray-50 px-6 py-4 flex justify-end">
              <button
                type="button"
                onClick={() => setSyncDetails(null)}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700"
              >
                Close Diagnostic Report
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
