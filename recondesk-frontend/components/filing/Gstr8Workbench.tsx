"use client";

import React, { useState, useEffect } from "react";
import useSWR from "swr";
import {
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  FileJson,
  Download,
  Plus,
  Trash2,
  RefreshCw,
  ShoppingCart,
  Percent,
  Layers,
  HelpCircle,
} from "lucide-react";
import {
  clientsApi,
  gstr8Api,
  ClientGstin,
  Gstr8BatchSummary,
  Gstr8Record,
  PreFilingValidationResult,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

interface Gstr8WorkbenchProps {
  initialClientGstinId?: string;
  initialPeriod?: string;
}

export default function Gstr8Workbench({
  initialClientGstinId,
  initialPeriod = "2026-07",
}: Gstr8WorkbenchProps) {
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [selectedClientGstinId, setSelectedClientGstinId] = useState<string>(initialClientGstinId || "");
  const [period, setPeriod] = useState<string>(initialPeriod);
  const [activeTab, setActiveTab] = useState<"table3_b2b" | "table3_b2c" | "table4" | "exceptions">("table3_b2b");

  // Fetch client GSTIN list
  const { data: clientsData, isLoading: isClientsLoading } = useSWR<ClientGstin[]>(
    token ? ["backend-clients-list", token] : null,
    ([, t]) => clientsApi.list(t as string)
  );

  const clients = clientsData || [];

  useEffect(() => {
    if (clients.length > 0 && !selectedClientGstinId) {
      setSelectedClientGstinId(clients[0].id);
    }
  }, [clients, selectedClientGstinId]);

  // Fetch batch
  const {
    data: batchData,
    isLoading: isBatchLoading,
    mutate: mutateBatch,
  } = useSWR(
    token && selectedClientGstinId && period
      ? ["gstr8-batch", selectedClientGstinId, period, token]
      : null,
    () => gstr8Api.getOrCreateBatch(token!, selectedClientGstinId, period)
  );

  const batchId = batchData?.id;

  // Fetch batch summary
  const {
    data: summary,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr8BatchSummary>(
    token && batchId ? ["gstr8-summary", batchId, token] : null,
    () => gstr8Api.getBatchSummary(token!, batchId!)
  );

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [supplyType, setSupplyType] = useState<"B2B" | "B2C">("B2B");
  const [recordType, setRecordType] = useState<"ORIGINAL" | "AMENDMENT">("ORIGINAL");
  const [supplierGstin, setSupplierGstin] = useState("");
  const [pos, setPos] = useState("");
  const [grossSupplies, setGrossSupplies] = useState<number>(100000);
  const [returnedSupplies, setReturnedSupplies] = useState<number>(5000);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Governance action states
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<PreFilingValidationResult | null>(null);

  const handleAddRecord = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      await gstr8Api.saveRecord(token, batchId, {
        supply_type: supplyType,
        record_type: recordType,
        supplier_gstin: supplyType === "B2B" ? supplierGstin : undefined,
        pos: pos || undefined,
        gross_supplies: grossSupplies,
        returned_supplies: returnedSupplies,
      });
      setIsModalOpen(false);
      setSupplierGstin("");
      setPos("");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err?.message || "Failed to save TCS record");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteRecord = async (recordId: string) => {
    if (!token || !batchId) return;
    if (!confirm("Are you sure you want to remove this TCS record?")) return;
    try {
      await gstr8Api.deleteRecord(token, batchId, recordId);
      mutateSummary();
    } catch (err: any) {
      alert(err?.message || "Failed to delete record");
    }
  };

  const handleValidate = async () => {
    if (!token || !batchId) return;
    try {
      const res = await gstr8Api.validate(token, batchId);
      setValidationResult(res);
      setActionStatus("Validation completed.");
    } catch (err: any) {
      alert(err?.message || "Validation failed");
    }
  };

  const handlePrepare = async () => {
    if (!token || !batchId) return;
    try {
      await gstr8Api.prepare(token, batchId);
      setActionStatus("Return prepared. Ready for Maker-Checker review.");
      mutateSummary();
    } catch (err: any) {
      alert(err?.message || "Prepare failed");
    }
  };

  const handleDownloadOfflineJson = async () => {
    if (!token || !batchId) return;
    try {
      const jsonPayload = await gstr8Api.getOfflineJson(token, batchId);
      const blob = new Blob([JSON.stringify(jsonPayload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR8_${summary?.batch.gstin}_${period}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(err?.message || "Failed to generate JSON");
    }
  };

  const selectedClient = clients.find((c) => c.id === selectedClientGstinId);

  return (
    <div className="space-y-6">
      {/* Header & Client Selector */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-5">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-gray-900 flex items-center gap-2">
            <ShoppingCart className="h-6 w-6 text-purple-600" />
            Form GSTR-8 — E-Commerce TCS Compliance Workbench
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Tax Collected at Source under Section 52: E-Commerce Operator (ECO) supplies reconciliation,
            net taxable supplies calculation, reduced 0.5% statutory rate verification, and GSTN offline JSON export.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">ECO GSTIN</label>
            <select
              value={selectedClientGstinId}
              onChange={(e) => setSelectedClientGstinId(e.target.value)}
              disabled={isClientsLoading}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:outline-none"
            >
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.gstin} ({c.trade_name || c.legal_name || "ECO"})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Return Period</label>
            <input
              type="month"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:outline-none"
            />
          </div>

          <button
            onClick={() => {
              mutateBatch();
              mutateSummary();
            }}
            className="mt-5 p-2 text-gray-500 hover:text-purple-600 rounded-lg border border-gray-200 bg-white"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Statutory Rate Alert & Rate Transition */}
      <div className="rounded-xl border border-purple-200 bg-purple-50/70 p-4 text-sm text-purple-900 flex items-start gap-3">
        <Percent className="h-5 w-5 text-purple-600 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold">Section 52 Statutory TCS Rates:</span> Net Taxable Supplies = Gross Supplies Made − Supplies Returned.
          <div className="mt-1 font-medium text-purple-800">
            Applicable Rate for {period}: <strong>{summary?.applicable_rates.total_pct || 0.5}%</strong> ({summary?.applicable_rates.cgst_pct || 0.25}% CGST + {summary?.applicable_rates.sgst_pct || 0.25}% SGST or {summary?.applicable_rates.igst_pct || 0.5}% IGST).
            <span className="block text-xs text-purple-700 mt-0.5">Reference: {summary?.applicable_rates.reference || "Notification No. 15/2024-Central Tax"}</span>
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Total TCS Liability</div>
          <div className="mt-2 text-2xl font-bold text-gray-900">
            ₹{(summary?.total_tcs_liability || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            IGST: ₹{(summary?.batch.total_tcs_igst || 0).toFixed(2)} | CGST+SGST: ₹{((summary?.batch.total_tcs_cgst || 0) + (summary?.batch.total_tcs_sgst || 0)).toFixed(2)}
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Net Taxable Supplies</div>
          <div className="mt-2 text-2xl font-bold text-gray-900">
            ₹{(summary?.batch.net_taxable_value || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            Gross: ₹{(summary?.batch.gross_supplies_value || 0).toFixed(2)} − Ret: ₹{(summary?.batch.returned_supplies_value || 0).toFixed(2)}
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Deposit Variance</div>
          <div className={`mt-2 text-2xl font-bold ${Math.abs(summary?.deposit_variance || 0) > 0.01 ? "text-amber-600" : "text-emerald-600"}`}>
            ₹{(summary?.deposit_variance || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            Deposited: ₹{(summary?.batch.total_tcs_deposited || 0).toFixed(2)}
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Filing Status</div>
          <div className="mt-2 flex items-center gap-2">
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-50 text-purple-700 border border-purple-200">
              {summary?.batch.status || "DRAFT"}
            </span>
          </div>
          <div className="mt-2 text-[11px] text-gray-400 font-mono truncate" title={summary?.batch.figures_digest}>
            SHA: {summary?.batch.figures_digest?.substring(0, 16) || "None"}...
          </div>
        </div>
      </div>

      {/* Action Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-500"
          >
            <Plus className="h-4 w-4" />
            Add Supply Record
          </button>
          <button
            onClick={handleValidate}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <ShieldAlert className="h-4 w-4 text-purple-600" />
            Pre-Filing Validation
          </button>
          <button
            onClick={handlePrepare}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            Prepare Return
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleDownloadOfflineJson}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <Download className="h-4 w-4 text-gray-600" />
            Export GSTN JSON
          </button>
        </div>
      </div>

      {/* Validation Result Banner */}
      {validationResult && (
        <div className={`rounded-xl border p-4 ${validationResult.is_valid ? "bg-emerald-50 border-emerald-200 text-emerald-900" : "bg-red-50 border-red-200 text-red-900"}`}>
          <div className="flex items-center justify-between">
            <div className="font-semibold">
              Validation Result: {validationResult.overall_severity} ({validationResult.is_valid ? "PASS" : "BLOCKING ERRORS DETECTED"})
            </div>
            <span className="text-xs font-mono">Digest: {validationResult.validation_digest?.substring(0, 16)}...</span>
          </div>
          {validationResult.violations && validationResult.violations.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-xs space-y-1">
              {validationResult.violations.map((v: any, idx: number) => (
                <li key={idx}>
                  <strong className="font-semibold">[{v.code}]</strong> {v.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-6" aria-label="Tabs">
          <button
            onClick={() => setActiveTab("table3_b2b")}
            className={`py-3 px-1 border-b-2 text-sm font-medium ${
              activeTab === "table3_b2b"
                ? "border-purple-600 text-purple-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Table 3: B2B Registered ({summary?.table3_b2b.length || 0})
          </button>
          <button
            onClick={() => setActiveTab("table3_b2c")}
            className={`py-3 px-1 border-b-2 text-sm font-medium ${
              activeTab === "table3_b2c"
                ? "border-purple-600 text-purple-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Table 3: B2C Unregistered ({summary?.table3_b2c.length || 0})
          </button>
          <button
            onClick={() => setActiveTab("table4")}
            className={`py-3 px-1 border-b-2 text-sm font-medium ${
              activeTab === "table4"
                ? "border-purple-600 text-purple-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Table 4: Amendments ({((summary?.table4_b2b.length || 0) + (summary?.table4_b2c.length || 0))})
          </button>
          <button
            onClick={() => setActiveTab("exceptions")}
            className={`py-3 px-1 border-b-2 text-sm font-medium ${
              activeTab === "exceptions"
                ? "border-purple-600 text-purple-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Exceptions ({summary?.exceptions.length || 0})
          </button>
        </nav>
      </div>

      {/* Table Content */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        {activeTab === "table3_b2b" && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Supplier GSTIN</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Gross (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Returned (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Net Supplies (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">IGST (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">CGST (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">SGST (₹)</th>
                  <th className="px-4 py-3 text-center font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {summary?.table3_b2b && summary.table3_b2b.length > 0 ? (
                  summary.table3_b2b.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono font-medium text-gray-900">{r.supplier_gstin}</td>
                      <td className="px-4 py-3 text-right font-mono">{r.gross_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className="px-4 py-3 text-right font-mono text-red-600">{r.returned_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className={`px-4 py-3 text-right font-mono font-semibold ${r.net_supplies < 0 ? "text-amber-600" : "text-gray-900"}`}>
                        {r.net_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-blue-600">{r.tcs_igst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono text-purple-600">{r.tcs_cgst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono text-purple-600">{r.tcs_sgst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleDeleteRecord(r.id)}
                          className="text-gray-400 hover:text-red-600"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                      No Table 3 B2B registered supplier records. Click &quot;Add Supply Record&quot; to add.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === "table3_b2c" && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Place of Supply (POS)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Gross (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Returned (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Net Supplies (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">IGST (₹)</th>
                  <th className="px-4 py-3 text-center font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {summary?.table3_b2c && summary.table3_b2c.length > 0 ? (
                  summary.table3_b2c.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono font-medium text-gray-900">State Code {r.pos}</td>
                      <td className="px-4 py-3 text-right font-mono">{r.gross_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className="px-4 py-3 text-right font-mono text-red-600">{r.returned_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className="px-4 py-3 text-right font-mono font-semibold">{r.net_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className="px-4 py-3 text-right font-mono text-blue-600">{r.tcs_igst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleDeleteRecord(r.id)}
                          className="text-gray-400 hover:text-red-600"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                      No Table 3 B2C unregistered supply records.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === "table4" && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Type</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Original Period</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Supplier GSTIN / POS</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Gross (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Returned (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Net Supplies (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">TCS (₹)</th>
                  <th className="px-4 py-3 text-center font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {[...(summary?.table4_b2b || []), ...(summary?.table4_b2c || [])].map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-semibold text-xs">{r.supply_type}</td>
                    <td className="px-4 py-3 text-gray-600">{r.original_period || "—"}</td>
                    <td className="px-4 py-3 font-mono font-medium text-gray-900">{r.supplier_gstin || `POS ${r.pos}`}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.gross_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="px-4 py-3 text-right font-mono text-red-600">{r.returned_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="px-4 py-3 text-right font-mono font-semibold">{r.net_supplies.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="px-4 py-3 text-right font-mono">{(r.tcs_igst + r.tcs_cgst + r.tcs_sgst).toFixed(2)}</td>
                    <td className="px-4 py-3 text-center">
                      <button
                        onClick={() => handleDeleteRecord(r.id)}
                        className="text-gray-400 hover:text-red-600"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === "exceptions" && (
          <div className="p-4 space-y-3">
            {summary?.exceptions && summary.exceptions.length > 0 ? (
              summary.exceptions.map((ex, idx) => (
                <div key={idx} className="flex items-start gap-3 p-3 rounded-lg border border-amber-200 bg-amber-50/60 text-sm">
                  <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-semibold text-amber-900">[{ex.category}] {ex.supplier_gstin ? `Supplier: ${ex.supplier_gstin}` : `POS: ${ex.pos}`}</div>
                    <div className="text-amber-800 mt-0.5">{ex.reason}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-6 text-gray-500">
                <CheckCircle2 className="h-8 w-8 text-emerald-500 mx-auto mb-2" />
                Zero exceptions detected. Net supplies and TCS rates are aligned.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Add Record Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl space-y-4">
            <h3 className="text-lg font-bold text-gray-900">Add TCS Supply Record (Section 52)</h3>

            {errorMessage && (
              <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{errorMessage}</div>
            )}

            <form onSubmit={handleAddRecord} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700">Supply Type</label>
                  <select
                    value={supplyType}
                    onChange={(e) => setSupplyType(e.target.value as any)}
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                  >
                    <option value="B2B">B2B: Registered Supplier</option>
                    <option value="B2C">B2C: Unregistered Supplies</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-700">Record Type</label>
                  <select
                    value={recordType}
                    onChange={(e) => setRecordType(e.target.value as any)}
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                  >
                    <option value="ORIGINAL">Table 3: Original</option>
                    <option value="AMENDMENT">Table 4: Amendment</option>
                  </select>
                </div>
              </div>

              {supplyType === "B2B" ? (
                <div>
                  <label className="block text-xs font-medium text-gray-700">Supplier GSTIN (15 chars)</label>
                  <input
                    type="text"
                    required
                    maxLength={15}
                    value={supplierGstin}
                    onChange={(e) => setSupplierGstin(e.target.value.toUpperCase())}
                    placeholder="27ABCDE1234F1Z5"
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm font-mono"
                  />
                </div>
              ) : (
                <div>
                  <label className="block text-xs font-medium text-gray-700">Place of Supply (2-digit State Code)</label>
                  <input
                    type="text"
                    required
                    maxLength={2}
                    value={pos}
                    onChange={(e) => setPos(e.target.value)}
                    placeholder="27"
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm font-mono"
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700">Gross Supplies (₹)</label>
                  <input
                    type="number"
                    required
                    min={0}
                    step="0.01"
                    value={grossSupplies}
                    onChange={(e) => setGrossSupplies(parseFloat(e.target.value) || 0)}
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-700">Returned Supplies (₹)</label>
                  <input
                    type="number"
                    required
                    min={0}
                    step="0.01"
                    value={returnedSupplies}
                    onChange={(e) => setReturnedSupplies(parseFloat(e.target.value) || 0)}
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                  />
                </div>
              </div>

              <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-600 flex justify-between">
                <span>Calculated Net Taxable Supplies:</span>
                <span className="font-semibold text-gray-900 font-mono">
                  ₹{(grossSupplies - returnedSupplies).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </span>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-500"
                >
                  {isSubmitting ? "Saving..." : "Save Record"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
