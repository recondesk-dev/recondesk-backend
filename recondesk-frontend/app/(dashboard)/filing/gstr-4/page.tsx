"use client";

import React, { useState, useEffect, Suspense } from "react";
import useSWR from "swr";
import { useSearchParams } from "next/navigation";
import {
  Calculator,
  Save,
  AlertTriangle,
  CheckCircle2,
  FileJson,
  Edit3,
  RefreshCw,
  Clock,
  ShieldAlert,
  TrendingUp,
  Percent,
  Layers,
  Lock,
} from "lucide-react";
import { clientsApi, gstr4Api, ClientGstin, Gstr4ComputationResponse, Cmp08Record } from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const COMPOSITION_CATEGORIES = [
  { id: "trader", name: "Trader / Manufacturer", rateLabel: "1.0% (0.5% CGST + 0.5% SGST)", desc: "Taxpayers selling goods under Section 10(1)" },
  { id: "restaurant", name: "Restaurant Services", rateLabel: "5.0% (2.5% CGST + 2.5% SGST)", desc: "Restaurant & catering services under Section 10(1)" },
  { id: "service", name: "Service Provider / Other", rateLabel: "6.0% (3.0% CGST + 3.0% SGST)", desc: "Mixed or service suppliers under Notification 2/2019" },
];

const FINANCIAL_YEARS = ["2025-26", "2024-25", "2023-24"];

function Gstr4WorkbenchContent() {
  const token = useAccessToken();
  const searchParams = useSearchParams();
  const initialClientId = searchParams.get("client_id") || searchParams.get("client_gstin_id") || "";

  const [clientId, setClientId] = useState<string>(initialClientId);
  const [financialYear, setFinancialYear] = useState<string>("2025-26");
  const [category, setCategory] = useState<string>("trader");
  const [activeTab, setActiveTab] = useState<"table4" | "table5" | "table6" | "table8" | "overrides">("table6");

  // Fetch client GSTIN list using auth token
  const { data: clientsData, isLoading: isClientsLoading, error: clientsError } = useSWR<ClientGstin[]>(
    token ? ["backend-clients-list", token] : null,
    ([, t]) => clientsApi.list(t as string)
  );

  const clients = clientsData || [];

  // Auto-select client if query param or list changes
  useEffect(() => {
    if (clients.length > 0) {
      if (initialClientId && clients.some((c) => c.id === initialClientId)) {
        setClientId(initialClientId);
      } else if (!clientId || !clients.some((c) => c.id === clientId)) {
        setClientId(clients[0].id);
      }
    }
  }, [clients, initialClientId, clientId]);

  // State for CA Overrides editing
  const [overrideDrafts, setOverrideDrafts] = useState<
    Record<string, { table_key: string; cell_key: string; system_value: number; override_value: number; notes: string }>
  >({});
  const [isSavingOverrides, setIsSavingOverrides] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);

  // State for CMP-08 Edit Modal
  const [isCmp08ModalOpen, setIsCmp08ModalOpen] = useState(false);
  const [cmp08Drafts, setCmp08Drafts] = useState<Cmp08Record[]>([]);
  const [isSavingCmp08, setIsSavingCmp08] = useState(false);

  // Fetch GSTR-4 computation using SWR with auth token
  const {
    data: comp,
    error,
    isLoading: isCompLoading,
    mutate,
  } = useSWR<Gstr4ComputationResponse>(
    token && clientId ? ["gstr4-comp", clientId, financialYear, category, token] : null,
    ([, cid, fy, cat, t]) => gstr4Api.getComputation(t as string, cid as string, fy as string, cat as string)
  );

  // Populate CMP-08 modal drafts when data loads
  useEffect(() => {
    if (comp?.tables?.table5) {
      const t5 = comp.tables.table5;
      setCmp08Drafts([t5.q1, t5.q2, t5.q3, t5.q4]);
    }
  }, [comp]);

  const handleCellOverrideChange = (tableKey: string, cellKey: string, sysVal: number, rawVal: string, notes: string = "") => {
    const overrideVal = parseFloat(rawVal) || 0.0;
    const key = `${tableKey}.${cellKey}`;
    setOverrideDrafts((prev) => ({
      ...prev,
      [key]: {
        table_key: tableKey,
        cell_key: cellKey,
        system_value: sysVal,
        override_value: overrideVal,
        notes: notes || prev[key]?.notes || "",
      },
    }));
  };

  const handleSaveOverrides = async () => {
    if (!clientId || typeof token !== "string") return;
    setIsSavingOverrides(true);
    setSaveStatus(null);
    try {
      const overridesList = Object.values(overrideDrafts);
      await gstr4Api.saveOverrides(token, clientId, financialYear, overridesList);
      setSaveStatus("CA Audit overrides saved successfully!");
      setOverrideDrafts({});
      await mutate();
    } catch (err: any) {
      setSaveStatus(`Error saving overrides: ${err?.message || err}`);
    } finally {
      setIsSavingOverrides(false);
    }
  };

  const handleSaveCmp08Modal = async () => {
    if (!clientId || typeof token !== "string") return;
    setIsSavingCmp08(true);
    try {
      await gstr4Api.saveCmp08(token, clientId, financialYear, cmp08Drafts);
      setIsCmp08ModalOpen(false);
      await mutate();
    } catch (err: any) {
      alert(`Failed to save CMP-08 records: ${err?.message || err}`);
    } finally {
      setIsSavingCmp08(false);
    }
  };

  const isGstr4FilingEnabled = process.env.NEXT_PUBLIC_GSTR4_FILING_ENABLED === "true";

  const handleDownloadJson = async () => {
    if (!clientId || typeof token !== "string") return;
    if (!isGstr4FilingEnabled) {
      alert("HTTP 503 GSTR4_FILING_DISABLED: Form GSTR-4 JSON export is currently disabled. End-to-end GSTN Offline Utility validation has not been completed.");
      return;
    }
    try {
      const blob = await gstr4Api.downloadJson(token, clientId, financialYear, category);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR4_${comp?.gstin || "CLIENT"}_${financialYear.replace("-", "_")}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(`Failed to download GSTR-4 JSON: ${err?.message || err}`);
    }
  };

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(val || 0);
  };

  return (
    <div className="min-h-screen p-6 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Top Header & Navigation Banner */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white border border-gray-200/80 rounded-2xl p-6 shadow-sm">
          <div>
            <div className="flex items-center gap-3">
              <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-700">
                <Calculator size={24} />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-[var(--ink)] flex items-center gap-2">
                  GSTR-4 Composition Annual Return
                  <span className="px-2.5 py-0.5 text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200 rounded-full">
                    Form GSTR-4
                  </span>
                </h1>
                <p className="text-sm text-gray-500 mt-0.5">
                  Annual Return for Composition Taxpayers (Sec 10 & Notfn 2/2019-CT(R))
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={handleDownloadJson}
              disabled={!clientId || !isGstr4FilingEnabled}
              title={!isGstr4FilingEnabled ? "Disabled: GSTR4_FILING_ENABLED = false" : "Export Portal JSON"}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-xl transition shadow-sm ${
                !isGstr4FilingEnabled
                  ? "bg-gray-100 border border-gray-300 text-gray-400 cursor-not-allowed"
                  : "bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white cursor-pointer"
              }`}
            >
              {!isGstr4FilingEnabled ? <Lock size={16} /> : <FileJson size={16} />}
              Export Portal JSON {!isGstr4FilingEnabled && "(Disabled)"}
            </button>
            <button
              onClick={() => mutate()}
              className="flex items-center gap-2 px-3 py-2.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-xl border border-gray-200 transition cursor-pointer"
            >
              <RefreshCw size={16} className={isCompLoading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* GSTR-4 Feature Gate / CA Preview Notice */}
        <div className="bg-amber-50/80 border border-amber-200/80 rounded-2xl p-4 flex items-start gap-3 text-amber-900 shadow-sm">
          <div className="p-1.5 bg-amber-100 rounded-lg text-amber-700 mt-0.5 shrink-0">
            <AlertTriangle size={18} />
          </div>
          <div className="text-sm">
            <div className="font-semibold flex items-center gap-2 text-amber-950">
              <span>CA PREVIEW & BETA STAGING MODE</span>
              <span className="px-2 py-0.5 bg-amber-200 text-amber-900 rounded-full text-[10px] font-bold uppercase tracking-wide">
                GSTR4_FILING_ENABLED = FALSE
              </span>
            </div>
            <p className="mt-0.5 text-amber-800 text-xs leading-relaxed">
              Form GSTR-4 Annual Return module is currently in <strong>CA Beta Preview</strong>. Exported JSON files must be validated using the official <strong>GSTN GSTR-4 Offline Utility</strong> or GST Portal trial upload before submitting live filings.
            </p>
          </div>
        </div>

        {/* Configuration Controls Bar */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-white border border-gray-200/80 rounded-2xl p-5 shadow-sm">
          {/* Client Selection */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Select Client GSTIN
            </label>
            {isClientsLoading ? (
              <div className="h-10 bg-gray-100 animate-pulse rounded-xl" />
            ) : (
              <select
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                className="w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-900 focus:outline-none focus:border-emerald-600 focus:bg-white transition"
              >
                {clients.length === 0 ? (
                  <option value="">No clients found</option>
                ) : (
                  clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {(c as any).trade_name || (c as any).legal_name || c.gstin} ({c.gstin})
                    </option>
                  ))
                )}
              </select>
            )}
            {clientsError && <p className="mt-1 text-xs text-red-600">Failed to load clients list.</p>}
          </div>

          {/* Financial Year Selection */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Financial Year
            </label>
            <select
              value={financialYear}
              onChange={(e) => setFinancialYear(e.target.value)}
              className="w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-900 focus:outline-none focus:border-emerald-600 focus:bg-white transition"
            >
              {FINANCIAL_YEARS.map((fy) => (
                <option key={fy} value={fy}>
                  FY {fy}
                </option>
              ))}
            </select>
          </div>

          {/* Composition Category */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Composition Category & Tax Rate
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-900 focus:outline-none focus:border-emerald-600 focus:bg-white transition"
            >
              {COMPOSITION_CATEGORIES.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.name} — {cat.rateLabel}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Warning & Discrepancy Alerts */}
        {comp?.warnings && comp.warnings.length > 0 && (
          <div className="space-y-3">
            {comp.warnings.map((w, i) => (
              <div
                key={i}
                className={`p-4 rounded-xl border flex items-start gap-3 ${
                  w.severity === "WARNING"
                    ? "bg-amber-50 border-amber-200 text-amber-800"
                    : "bg-blue-50 border-blue-200 text-blue-800"
                }`}
              >
                <AlertTriangle size={20} className="mt-0.5 flex-shrink-0 text-amber-600" />
                <div className="text-sm">
                  <span className="font-semibold mr-2">[{w.code}]</span>
                  {w.message}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* KPI Summary Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-white border border-gray-200/80 rounded-2xl p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-gray-500 text-xs font-semibold uppercase tracking-wider">
              <span>Annual Outward Turnover</span>
              <TrendingUp size={16} className="text-emerald-600" />
            </div>
            <div className="text-2xl font-bold text-gray-900 mt-3">
              {formatCurrency(comp?.kpi_summary?.outward_turnover || 0)}
            </div>
            <div className="text-xs text-gray-500 mt-1">Sum of CMP-08 Q1..Q4 Outward Sales</div>
          </div>

          <div className="bg-white border border-gray-200/80 rounded-2xl p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-gray-500 text-xs font-semibold uppercase tracking-wider">
              <span>Calculated Tax Liability</span>
              <Percent size={16} className="text-blue-600" />
            </div>
            <div className="text-2xl font-bold text-gray-900 mt-3">
              {formatCurrency(comp?.kpi_summary?.total_tax_payable || 0)}
            </div>
            <div className="text-xs text-blue-600 font-medium mt-1">
              Rate: {comp?.tables?.table6?.rate_percentages?.total_rate || 1}% Total Tax
            </div>
          </div>

          <div className="bg-white border border-gray-200/80 rounded-2xl p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-gray-500 text-xs font-semibold uppercase tracking-wider">
              <span>CMP-08 Tax Paid</span>
              <CheckCircle2 size={16} className="text-purple-600" />
            </div>
            <div className="text-2xl font-bold text-gray-900 mt-3">
              {formatCurrency(comp?.kpi_summary?.cmp08_tax_paid || 0)}
            </div>
            <div className="text-xs text-purple-600 mt-1">Paid in quarterly statements</div>
          </div>

          <div className="bg-white border border-gray-200/80 rounded-2xl p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-gray-500 text-xs font-semibold uppercase tracking-wider">
              <span>Balance Cash Payable</span>
              <ShieldAlert size={16} className={comp?.kpi_summary?.balance_cash_payable ? "text-amber-600" : "text-emerald-600"} />
            </div>
            <div className={`text-2xl font-bold mt-3 ${comp?.kpi_summary?.balance_cash_payable ? "text-amber-600" : "text-emerald-600"}`}>
              {formatCurrency(comp?.kpi_summary?.balance_cash_payable || 0)}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {comp?.kpi_summary?.balance_cash_payable ? "Shortfall payable in cash ledger" : "Fully reconciled"}
            </div>
          </div>
        </div>

        {/* Workbench Tab Navigation */}
        <div className="bg-white border border-gray-200/80 rounded-2xl p-2 shadow-sm flex flex-wrap gap-2">
          <button
            onClick={() => setActiveTab("table6")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold transition cursor-pointer ${
              activeTab === "table6" ? "bg-emerald-600 text-white shadow-sm" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            }`}
          >
            <Percent size={15} />
            Table 6: Tax Payable Calculation
          </button>

          <button
            onClick={() => setActiveTab("table5")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold transition cursor-pointer ${
              activeTab === "table5" ? "bg-emerald-600 text-white shadow-sm" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            }`}
          >
            <Layers size={15} />
            Table 5: CMP-08 Quarterly Summary
          </button>

          <button
            onClick={() => setActiveTab("table4")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold transition cursor-pointer ${
              activeTab === "table4" ? "bg-emerald-600 text-white shadow-sm" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            }`}
          >
            <Calculator size={15} />
            Table 4: Inward Supplies
          </button>

          <button
            onClick={() => setActiveTab("table8")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold transition cursor-pointer ${
              activeTab === "table8" ? "bg-emerald-600 text-white shadow-sm" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            }`}
          >
            <Clock size={15} />
            Table 8: Differential Tax & Late Fee
          </button>

          <button
            onClick={() => setActiveTab("overrides")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold transition cursor-pointer ${
              activeTab === "overrides" ? "bg-emerald-600 text-white shadow-sm" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            }`}
          >
            <Edit3 size={15} />
            CA Audit Cell Overrides
          </button>
        </div>

        {/* Tab Contents */}
        {isCompLoading ? (
          <div className="bg-white border border-gray-200/80 rounded-2xl p-12 text-center text-gray-500">
            <RefreshCw size={28} className="animate-spin mx-auto text-emerald-600 mb-3" />
            Computing Form GSTR-4 annual return figures...
          </div>
        ) : error ? (
          <div className="bg-red-50 border border-red-200 text-red-700 p-6 rounded-2xl text-center text-sm font-medium">
            Failed to compute GSTR-4: {error.message || String(error)}
          </div>
        ) : comp ? (
          <div className="bg-white border border-gray-200/80 rounded-2xl p-6 shadow-sm space-y-6">
            {/* Table 6: Rate-Wise Tax Payable */}
            {activeTab === "table6" && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                    Table 6: Tax Payable on Outward Supplies & Inward Reverse Charge
                  </h3>
                  <p className="text-xs text-gray-500 mt-1">
                    Rate-wise breakup of turnover and composition tax payable ({comp.tables.table6.category_label})
                  </p>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-gray-800 border-collapse">
                    <thead>
                      <tr className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500 font-semibold">
                        <th className="p-3">Supply Type</th>
                        <th className="p-3">Taxable Turnover (₹)</th>
                        <th className="p-3">CGST Rate</th>
                        <th className="p-3">CGST (₹)</th>
                        <th className="p-3">SGST Rate</th>
                        <th className="p-3">SGST (₹)</th>
                        <th className="p-3 text-right">Total Tax (₹)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      <tr className="hover:bg-gray-50/50">
                        <td className="p-3 font-semibold text-gray-900">Outward Supplies (Composition Rate)</td>
                        <td className="p-3 font-mono font-medium">
                          {formatCurrency(comp.tables.table6.outward_supplies.turnover.effective_value)}
                        </td>
                        <td className="p-3">{comp.tables.table6.rate_percentages.cgst_rate}%</td>
                        <td className="p-3 font-mono">
                          {formatCurrency(comp.tables.table6.outward_supplies.cgst.effective_value)}
                        </td>
                        <td className="p-3">{comp.tables.table6.rate_percentages.sgst_rate}%</td>
                        <td className="p-3 font-mono">
                          {formatCurrency(comp.tables.table6.outward_supplies.sgst.effective_value)}
                        </td>
                        <td className="p-3 text-right font-mono font-bold text-emerald-600">
                          {formatCurrency(comp.tables.table6.outward_supplies.tax_total.effective_value)}
                        </td>
                      </tr>

                      <tr className="hover:bg-gray-50/50">
                        <td className="p-3 font-semibold text-gray-900">Inward Reverse Charge Supplies (RCM)</td>
                        <td className="p-3 font-mono font-medium">
                          {formatCurrency(comp.tables.table6.inward_rcm_supplies.taxable_value.effective_value)}
                        </td>
                        <td className="p-3" colSpan={4}>
                          Slab Rates (5%, 12%, 18%, 28%)
                        </td>
                        <td className="p-3 text-right font-mono font-bold text-emerald-600">
                          {formatCurrency(comp.tables.table6.inward_rcm_supplies.tax_total.effective_value)}
                        </td>
                      </tr>

                      <tr className="bg-emerald-50 font-bold border-t border-emerald-200 text-gray-900">
                        <td className="p-3.5">TOTAL ANNUAL TAX PAYABLE</td>
                        <td className="p-3.5 font-mono">
                          {formatCurrency(
                            comp.tables.table6.outward_supplies.turnover.effective_value +
                              comp.tables.table6.inward_rcm_supplies.taxable_value.effective_value
                          )}
                        </td>
                        <td className="p-3.5" colSpan={4}></td>
                        <td className="p-3.5 text-right font-mono text-lg text-emerald-700">
                          {formatCurrency(comp.kpi_summary.total_tax_payable)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Table 5: CMP-08 Quarterly Summary */}
            {activeTab === "table5" && (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-bold text-gray-900">Table 5: Summary of Self-Assessed Tax Paid (CMP-08)</h3>
                    <p className="text-xs text-gray-500 mt-1">
                      Quarterly statement records aggregated for Q1, Q2, Q3, and Q4
                    </p>
                  </div>
                  <button
                    onClick={() => setIsCmp08ModalOpen(true)}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-xl transition cursor-pointer shadow-sm"
                  >
                    <Edit3 size={14} />
                    Edit Quarterly CMP-08 Figures
                  </button>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-gray-800 border-collapse">
                    <thead>
                      <tr className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500 font-semibold">
                        <th className="p-3">Quarter</th>
                        <th className="p-3">Outward Taxable (₹)</th>
                        <th className="p-3">Outward Tax (₹)</th>
                        <th className="p-3">RCM Taxable (₹)</th>
                        <th className="p-3">RCM Tax (₹)</th>
                        <th className="p-3">Interest (₹)</th>
                        <th className="p-3 text-right">Total Tax Paid (₹)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {[comp.tables.table5.q1, comp.tables.table5.q2, comp.tables.table5.q3, comp.tables.table5.q4].map((q) => (
                        <tr key={q.quarter} className="hover:bg-gray-50/50">
                          <td className="p-3 font-bold text-gray-900">{q.quarter}</td>
                          <td className="p-3 font-mono">{formatCurrency(q.outward_taxable)}</td>
                          <td className="p-3 font-mono">{formatCurrency(q.outward_tax)}</td>
                          <td className="p-3 font-mono">{formatCurrency(q.rcm_taxable)}</td>
                          <td className="p-3 font-mono">{formatCurrency(q.rcm_tax)}</td>
                          <td className="p-3 font-mono">{formatCurrency(q.interest)}</td>
                          <td className="p-3 text-right font-mono font-bold text-purple-700">
                            {formatCurrency(q.outward_tax + q.rcm_tax)}
                          </td>
                        </tr>
                      ))}
                      <tr className="bg-purple-50 font-bold border-t border-purple-200 text-gray-900">
                        <td className="p-3.5">TOTAL CMP-08 PAID</td>
                        <td className="p-3.5 font-mono">{formatCurrency(comp.tables.table5.outward_taxable.effective_value)}</td>
                        <td className="p-3.5 font-mono">{formatCurrency(comp.tables.table5.outward_tax.effective_value)}</td>
                        <td className="p-3.5 font-mono">{formatCurrency(comp.tables.table5.rcm_taxable.effective_value)}</td>
                        <td className="p-3.5 font-mono">{formatCurrency(comp.tables.table5.rcm_tax.effective_value)}</td>
                        <td className="p-3.5 font-mono">{formatCurrency(comp.tables.table5.interest.effective_value)}</td>
                        <td className="p-3.5 text-right font-mono text-lg text-purple-700">
                          {formatCurrency(comp.kpi_summary.cmp08_tax_paid)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Table 4: Inward Supplies */}
            {activeTab === "table4" && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">Table 4: Inward Supplies on which Tax is Payable</h3>
                  <p className="text-xs text-gray-500 mt-1">
                    Inward purchases from registered/unregistered suppliers and imports
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-4 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                    <div className="text-xs font-bold text-emerald-700 uppercase">4A. Registered Suppliers (Non-RCM)</div>
                    <div className="text-xl font-bold text-gray-900">
                      {formatCurrency(comp.tables.table4["4A_registered_non_rcm"].taxable_value.effective_value)}
                    </div>
                    <div className="text-xs text-gray-500">Normal inward purchases from registered dealers</div>
                  </div>

                  <div className="p-4 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                    <div className="text-xs font-bold text-blue-700 uppercase">4B. Registered Suppliers (Attracting RCM)</div>
                    <div className="text-xl font-bold text-gray-900">
                      {formatCurrency(comp.tables.table4["4B_registered_rcm"].taxable_value.effective_value)}
                    </div>
                    <div className="text-xs text-gray-500">RCM inward supplies from registered suppliers</div>
                  </div>

                  <div className="p-4 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                    <div className="text-xs font-bold text-purple-700 uppercase">4C. Unregistered Suppliers (RCM)</div>
                    <div className="text-xl font-bold text-gray-900">
                      {formatCurrency(comp.tables.table4["4C_unregistered_rcm"].taxable_value.effective_value)}
                    </div>
                    <div className="text-xs text-gray-500">Supplies received from unregistered entities</div>
                  </div>

                  <div className="p-4 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                    <div className="text-xs font-bold text-amber-700 uppercase">4D. Import of Services</div>
                    <div className="text-xl font-bold text-gray-900">
                      {formatCurrency(comp.tables.table4["4D_import_services"].taxable_value.effective_value)}
                    </div>
                    <div className="text-xs text-gray-500">Cross-border service imports under reverse charge</div>
                  </div>
                </div>
              </div>
            )}

            {/* Table 8: Differential Tax & Late Fee */}
            {activeTab === "table8" && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">Table 8: Tax, Interest, and Late Fee Payable & Paid</h3>
                  <p className="text-xs text-gray-500 mt-1">Reconciliation between Annual Liability and CMP-08 Paid amounts</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                    <span className="text-xs font-semibold text-gray-500 uppercase">Annual Tax Liability (Table 6)</span>
                    <div className="text-2xl font-bold text-gray-900">{formatCurrency(comp.tables.table8.tax_payable.effective_value)}</div>
                  </div>

                  <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                    <span className="text-xs font-semibold text-gray-500 uppercase">CMP-08 Tax Paid (Table 5)</span>
                    <div className="text-2xl font-bold text-purple-700">
                      {formatCurrency(comp.tables.table8.cmp08_tax_paid.effective_value)}
                    </div>
                  </div>

                  <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                    <span className="text-xs font-semibold text-gray-500 uppercase">Balance Tax Payable in Cash</span>
                    <div className={`text-2xl font-bold ${comp.tables.table8.balance_tax_payable.effective_value > 0 ? "text-amber-600" : "text-emerald-600"}`}>
                      {formatCurrency(comp.tables.table8.balance_tax_payable.effective_value)}
                    </div>
                  </div>
                </div>

                <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl space-y-3">
                  <div className="text-sm font-bold text-gray-900 flex items-center justify-between">
                    <span>Filing Timeline & Late Fee Status</span>
                    <span className="text-xs text-gray-500 font-mono">Due Date: {comp.tables.table8.due_date}</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs text-gray-700 pt-2">
                    <div>
                      <span className="text-gray-500">Days Delay Past Due Date:</span>
                      <span className="font-bold text-gray-900 ml-2">{comp.tables.table8.days_late} Days</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Estimated Late Fee Payable:</span>
                      <span className="font-bold text-amber-600 ml-2">
                        {formatCurrency(comp.tables.table8.late_fee_payable.effective_value)}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 5: CA Audit Cell Overrides */}
            {activeTab === "overrides" && (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                      CA Audit Cell Overrides
                      <span className="px-2.5 py-0.5 text-xs bg-blue-100 text-blue-800 border border-blue-200 rounded-full font-semibold">
                        Audit Trail Active
                      </span>
                    </h3>
                    <p className="text-xs text-gray-500 mt-1">
                      Override system calculated values cell-by-cell with mandatory CA observation notes
                    </p>
                  </div>

                  <button
                    onClick={handleSaveOverrides}
                    disabled={isSavingOverrides}
                    className="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-xl transition cursor-pointer disabled:opacity-50 shadow-sm"
                  >
                    <Save size={15} />
                    {isSavingOverrides ? "Saving..." : "Save Audit Overrides"}
                  </button>
                </div>

                {saveStatus && (
                  <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded-xl font-medium">
                    {saveStatus}
                  </div>
                )}

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-gray-800 border-collapse">
                    <thead>
                      <tr className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500 font-semibold">
                        <th className="p-3">Table & Cell Identifier</th>
                        <th className="p-3">System Computed Value</th>
                        <th className="p-3">CA Override Value</th>
                        <th className="p-3">Audit Observation Notes</th>
                        <th className="p-3 text-right">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {/* Table 5 Outward Taxable */}
                      <tr className="hover:bg-gray-50/50">
                        <td className="p-3">
                          <div className="font-bold text-gray-900">Table 5: Outward Taxable Turnover</div>
                          <div className="text-xs font-mono text-gray-500">table5.outward_taxable</div>
                        </td>
                        <td className="p-3 font-mono">{formatCurrency(comp.tables.table5.outward_taxable.system_value)}</td>
                        <td className="p-3">
                          <input
                            type="number"
                            step="0.01"
                            defaultValue={comp.tables.table5.outward_taxable.effective_value}
                            onChange={(e) =>
                              handleCellOverrideChange("table5", "outward_taxable", comp.tables.table5.outward_taxable.system_value, e.target.value)
                            }
                            className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5 font-mono text-xs text-gray-900 w-36 focus:outline-none focus:border-emerald-600 focus:bg-white"
                          />
                        </td>
                        <td className="p-3">
                          <input
                            type="text"
                            placeholder="Add CA audit observation note..."
                            defaultValue={comp.tables.table5.outward_taxable.notes}
                            onChange={(e) =>
                              handleCellOverrideChange(
                                "table5",
                                "outward_taxable",
                                comp.tables.table5.outward_taxable.system_value,
                                String(overrideDrafts["table5.outward_taxable"]?.override_value ?? comp.tables.table5.outward_taxable.effective_value),
                                e.target.value
                              )
                            }
                            className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-900 w-full focus:outline-none focus:border-emerald-600 focus:bg-white"
                          />
                        </td>
                        <td className="p-3 text-right">
                          {comp.tables.table5.outward_taxable.is_overridden ? (
                            <span className="px-2 py-1 text-xs bg-amber-100 text-amber-800 rounded font-semibold">Overridden</span>
                          ) : (
                            <span className="px-2 py-1 text-xs bg-gray-100 text-gray-500 rounded">System</span>
                          )}
                        </td>
                      </tr>

                      {/* Table 5 RCM Taxable */}
                      <tr className="hover:bg-gray-50/50">
                        <td className="p-3">
                          <div className="font-bold text-gray-900">Table 5: Inward RCM Taxable Turnover</div>
                          <div className="text-xs font-mono text-gray-500">table5.rcm_taxable</div>
                        </td>
                        <td className="p-3 font-mono">{formatCurrency(comp.tables.table5.rcm_taxable.system_value)}</td>
                        <td className="p-3">
                          <input
                            type="number"
                            step="0.01"
                            defaultValue={comp.tables.table5.rcm_taxable.effective_value}
                            onChange={(e) =>
                              handleCellOverrideChange("table5", "rcm_taxable", comp.tables.table5.rcm_taxable.system_value, e.target.value)
                            }
                            className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5 font-mono text-xs text-gray-900 w-36 focus:outline-none focus:border-emerald-600 focus:bg-white"
                          />
                        </td>
                        <td className="p-3">
                          <input
                            type="text"
                            placeholder="Add CA audit observation note..."
                            defaultValue={comp.tables.table5.rcm_taxable.notes}
                            onChange={(e) =>
                              handleCellOverrideChange(
                                "table5",
                                "rcm_taxable",
                                comp.tables.table5.rcm_taxable.system_value,
                                String(overrideDrafts["table5.rcm_taxable"]?.override_value ?? comp.tables.table5.rcm_taxable.effective_value),
                                e.target.value
                              )
                            }
                            className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-900 w-full focus:outline-none focus:border-emerald-600 focus:bg-white"
                          />
                        </td>
                        <td className="p-3 text-right">
                          {comp.tables.table5.rcm_taxable.is_overridden ? (
                            <span className="px-2 py-1 text-xs bg-amber-100 text-amber-800 rounded font-semibold">Overridden</span>
                          ) : (
                            <span className="px-2 py-1 text-xs bg-gray-100 text-gray-500 rounded">System</span>
                          )}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* Edit CMP-08 Modal */}
      {isCmp08ModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-gray-200 rounded-2xl max-w-4xl w-full p-6 space-y-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-100 pb-4">
              <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                <Edit3 size={18} className="text-blue-600" />
                Edit Quarterly CMP-08 Summary Records
              </h3>
              <button onClick={() => setIsCmp08ModalOpen(false)} className="text-gray-400 hover:text-gray-700">
                ✕
              </button>
            </div>

            <div className="overflow-x-auto space-y-4">
              <table className="w-full text-left text-xs text-gray-800">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 uppercase text-gray-500 font-semibold">
                    <th className="p-2">Quarter</th>
                    <th className="p-2">Outward Taxable (₹)</th>
                    <th className="p-2">Outward Tax (₹)</th>
                    <th className="p-2">RCM Taxable (₹)</th>
                    <th className="p-2">RCM Tax (₹)</th>
                    <th className="p-2">Interest (₹)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {cmp08Drafts.map((row, index) => (
                    <tr key={row.quarter}>
                      <td className="p-2 font-bold text-gray-900">{row.quarter}</td>
                      <td className="p-2">
                        <input
                          type="number"
                          value={row.outward_taxable}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const next = [...cmp08Drafts];
                            next[index] = { ...next[index], outward_taxable: val };
                            setCmp08Drafts(next);
                          }}
                          className="w-full bg-gray-50 border border-gray-200 rounded px-2 py-1 font-mono text-xs text-gray-900 focus:bg-white focus:border-emerald-600"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          value={row.outward_tax}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const next = [...cmp08Drafts];
                            next[index] = { ...next[index], outward_tax: val };
                            setCmp08Drafts(next);
                          }}
                          className="w-full bg-gray-50 border border-gray-200 rounded px-2 py-1 font-mono text-xs text-gray-900 focus:bg-white focus:border-emerald-600"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          value={row.rcm_taxable}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const next = [...cmp08Drafts];
                            next[index] = { ...next[index], rcm_taxable: val };
                            setCmp08Drafts(next);
                          }}
                          className="w-full bg-gray-50 border border-gray-200 rounded px-2 py-1 font-mono text-xs text-gray-900 focus:bg-white focus:border-emerald-600"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          value={row.rcm_tax}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const next = [...cmp08Drafts];
                            next[index] = { ...next[index], rcm_tax: val };
                            setCmp08Drafts(next);
                          }}
                          className="w-full bg-gray-50 border border-gray-200 rounded px-2 py-1 font-mono text-xs text-gray-900 focus:bg-white focus:border-emerald-600"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          value={row.interest}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const next = [...cmp08Drafts];
                            next[index] = { ...next[index], interest: val };
                            setCmp08Drafts(next);
                          }}
                          className="w-full bg-gray-50 border border-gray-200 rounded px-2 py-1 font-mono text-xs text-gray-900 focus:bg-white focus:border-emerald-600"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-100">
              <button
                onClick={() => setIsCmp08ModalOpen(false)}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-xl"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveCmp08Modal}
                disabled={isSavingCmp08}
                className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-xl transition disabled:opacity-50 shadow-sm"
              >
                {isSavingCmp08 ? "Saving..." : "Save Quarterly Figures"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Gstr4AnnualReturnPage() {
  return (
    <Suspense fallback={<div className="p-12 text-center text-sm text-gray-500">Loading GSTR-4 Workbench...</div>}>
      <Gstr4WorkbenchContent />
    </Suspense>
  );
}
