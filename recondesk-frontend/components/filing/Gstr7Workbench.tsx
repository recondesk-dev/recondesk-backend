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
  Send,
  Lock,
  Layers,
  HelpCircle,
} from "lucide-react";
import {
  clientsApi,
  gstr7Api,
  ClientGstin,
  Gstr7BatchSummary,
  Gstr7Record,
  PreFilingValidationResult,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

interface Gstr7WorkbenchProps {
  initialClientGstinId?: string;
  initialPeriod?: string;
}

export default function Gstr7Workbench({
  initialClientGstinId,
  initialPeriod = "2026-07",
}: Gstr7WorkbenchProps) {
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [selectedClientGstinId, setSelectedClientGstinId] = useState<string>(initialClientGstinId || "");
  const [period, setPeriod] = useState<string>(initialPeriod);
  const [activeTab, setActiveTab] = useState<"table3" | "table4" | "exceptions">("table3");

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
      ? ["gstr7-batch", selectedClientGstinId, period, token]
      : null,
    () => gstr7Api.getOrCreateBatch(token!, selectedClientGstinId, period)
  );

  const batchId = batchData?.id;

  // Fetch batch summary
  const {
    data: summary,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr7BatchSummary>(
    token && batchId ? ["gstr7-summary", batchId, token] : null,
    () => gstr7Api.getBatchSummary(token!, batchId!)
  );

  // Record modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [recordType, setRecordType] = useState<"ORIGINAL" | "AMENDMENT">("ORIGINAL");
  const [deducteeGstin, setDeducteeGstin] = useState("");
  const [contractNumber, setContractNumber] = useState("");
  const [contractValue, setContractValue] = useState<number>(300000);
  const [paymentRef, setPaymentRef] = useState("");
  const [amountPaid, setAmountPaid] = useState<number>(50000);
  const [pos, setPos] = useState("");
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
      await gstr7Api.saveRecord(token, batchId, {
        record_type: recordType,
        deductee_gstin: deducteeGstin,
        contract_number: contractNumber,
        contract_value: contractValue,
        payment_reference: paymentRef,
        amount_paid: amountPaid,
        pos: pos || undefined,
      });
      setIsModalOpen(false);
      // Reset fields
      setDeducteeGstin("");
      setContractNumber("");
      setPaymentRef("");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err?.message || "Failed to save TDS record");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteRecord = async (recordId: string) => {
    if (!token || !batchId) return;
    if (!confirm("Are you sure you want to remove this TDS record?")) return;
    try {
      await gstr7Api.deleteRecord(token, batchId, recordId);
      mutateSummary();
    } catch (err: any) {
      alert(err?.message || "Failed to delete record");
    }
  };

  const handleValidate = async () => {
    if (!token || !batchId) return;
    try {
      const res = await gstr7Api.validate(token, batchId);
      setValidationResult(res);
      setActionStatus("Validation completed.");
    } catch (err: any) {
      alert(err?.message || "Validation failed");
    }
  };

  const handlePrepare = async () => {
    if (!token || !batchId) return;
    try {
      await gstr7Api.prepare(token, batchId);
      setActionStatus("Return prepared. Ready for Maker-Checker review.");
      mutateSummary();
    } catch (err: any) {
      alert(err?.message || "Prepare failed");
    }
  };

  const handleDownloadOfflineJson = async () => {
    if (!token || !batchId) return;
    try {
      const jsonPayload = await gstr7Api.getOfflineJson(token, batchId);
      const blob = new Blob([JSON.stringify(jsonPayload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR7_${summary?.batch.gstin}_${period}.json`;
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
            <Layers className="h-6 w-6 text-indigo-600" />
            Form GSTR-7 — TDS Compliance & Filing Workbench
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Tax Deducted at Source under Section 51: Deductor reconciliation, contract threshold validation,
            Section 51(1) Proviso verification, and official GSTN offline JSON export.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Deductor GSTIN</label>
            <select
              value={selectedClientGstinId}
              onChange={(e) => setSelectedClientGstinId(e.target.value)}
              disabled={isClientsLoading}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none"
            >
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.gstin} ({c.trade_name || c.legal_name || "Client"})
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
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <button
            onClick={() => {
              mutateBatch();
              mutateSummary();
            }}
            className="mt-5 p-2 text-gray-500 hover:text-indigo-600 rounded-lg border border-gray-200 bg-white"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Statutory Section 51 Advisory Alert */}
      <div className="rounded-xl border border-blue-200 bg-blue-50/70 p-4 text-sm text-blue-900 flex items-start gap-3">
        <HelpCircle className="h-5 w-5 text-blue-600 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold">Section 51 Statutory Rules:</span> TDS at 2% (1% CGST + 1% SGST for intra-state, 2% IGST for inter-state) applies when total value of supply under a contract exceeds <strong>₹2,50,000</strong>.
          <span className="block mt-1 font-medium text-blue-800">
            Proviso Exemption: Under the Proviso to Section 51(1), NO deduction is permitted if the Supplier location and Place of Supply are in the same State, and different from the Deductor&apos;s registered State.
          </span>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Total TDS Liability</div>
          <div className="mt-2 text-2xl font-bold text-gray-900">
            ₹{(summary?.total_tds_liability || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            IGST: ₹{(summary?.batch.total_tds_igst || 0).toFixed(2)} | CGST+SGST: ₹{((summary?.batch.total_tds_cgst || 0) + (summary?.batch.total_tds_sgst || 0)).toFixed(2)}
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Total Amount Paid</div>
          <div className="mt-2 text-2xl font-bold text-gray-900">
            ₹{(summary?.batch.total_amount_paid || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            Across {summary?.batch.total_records || 0} Deductee Records
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Deposit Variance</div>
          <div className={`mt-2 text-2xl font-bold ${Math.abs(summary?.deposit_variance || 0) > 0.01 ? "text-amber-600" : "text-emerald-600"}`}>
            ₹{(summary?.deposit_variance || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            Deposited: ₹{(summary?.batch.total_tds_deposited || 0).toFixed(2)}
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-medium text-gray-500">Filing Status</div>
          <div className="mt-2 flex items-center gap-2">
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
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
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500"
          >
            <Plus className="h-4 w-4" />
            Add TDS Record
          </button>
          <button
            onClick={handleValidate}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <ShieldAlert className="h-4 w-4 text-indigo-600" />
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
            onClick={() => setActiveTab("table3")}
            className={`py-3 px-1 border-b-2 text-sm font-medium ${
              activeTab === "table3"
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Table 3: Details of Tax Deducted ({summary?.table3_original.length || 0})
          </button>
          <button
            onClick={() => setActiveTab("table4")}
            className={`py-3 px-1 border-b-2 text-sm font-medium ${
              activeTab === "table4"
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Table 4: Amendments to Earlier Periods ({summary?.table4_amendments.length || 0})
          </button>
          <button
            onClick={() => setActiveTab("exceptions")}
            className={`py-3 px-1 border-b-2 text-sm font-medium ${
              activeTab === "exceptions"
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Exceptions & Discrepancies ({summary?.exceptions.length || 0})
          </button>
        </nav>
      </div>

      {/* Table Content */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        {activeTab === "table3" && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Deductee GSTIN</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Contract No.</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Contract Val (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Amount Paid (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">IGST (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">CGST (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">SGST (₹)</th>
                  <th className="px-4 py-3 text-center font-medium text-gray-500">Status</th>
                  <th className="px-4 py-3 text-center font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {summary?.table3_original && summary.table3_original.length > 0 ? (
                  summary.table3_original.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono font-medium text-gray-900">{r.deductee_gstin}</td>
                      <td className="px-4 py-3 text-gray-600">{r.contract_number || "—"}</td>
                      <td className="px-4 py-3 text-right font-mono">{r.contract_value.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className="px-4 py-3 text-right font-mono font-semibold">{r.amount_paid.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className="px-4 py-3 text-right font-mono text-blue-600">{r.tds_igst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono text-purple-600">{r.tds_cgst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono text-purple-600">{r.tds_sgst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-center">
                        {r.is_eligible_for_tds ? (
                          <span className="inline-flex px-2 py-0.5 rounded text-xs bg-emerald-50 text-emerald-700">Eligible</span>
                        ) : (
                          <span className="inline-flex px-2 py-0.5 rounded text-xs bg-red-50 text-red-700" title={r.ineligibility_reason}>Exempt / Alert</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleDeleteRecord(r.id)}
                          className="text-gray-400 hover:text-red-600"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-gray-400">
                      No Table 3 original TDS records for this period. Click &quot;Add TDS Record&quot; to begin.
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
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Original Period</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Original GSTIN</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Revised GSTIN</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Amount Paid (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Revised IGST (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Revised CGST (₹)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-500">Revised SGST (₹)</th>
                  <th className="px-4 py-3 text-center font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {summary?.table4_amendments && summary.table4_amendments.length > 0 ? (
                  summary.table4_amendments.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-600">{r.original_period || "—"}</td>
                      <td className="px-4 py-3 font-mono text-gray-500">{r.original_deductee_gstin || r.deductee_gstin}</td>
                      <td className="px-4 py-3 font-mono font-medium text-gray-900">{r.deductee_gstin}</td>
                      <td className="px-4 py-3 text-right font-mono font-semibold">{r.amount_paid.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                      <td className="px-4 py-3 text-right font-mono text-blue-600">{r.tds_igst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono text-purple-600">{r.tds_cgst.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono text-purple-600">{r.tds_sgst.toFixed(2)}</td>
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
                      No Table 4 amendments recorded for this period.
                    </td>
                  </tr>
                )}
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
                    <div className="font-semibold text-amber-900">[{ex.category}] {ex.deductee_gstin ? `GSTIN: ${ex.deductee_gstin}` : ""}</div>
                    <div className="text-amber-800 mt-0.5">{ex.reason}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-6 text-gray-500">
                <CheckCircle2 className="h-8 w-8 text-emerald-500 mx-auto mb-2" />
                Zero statutory exceptions or deposit variances detected. All records are compliant.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Add Record Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl space-y-4">
            <h3 className="text-lg font-bold text-gray-900">Add TDS Record (Section 51)</h3>

            {errorMessage && (
              <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{errorMessage}</div>
            )}

            <form onSubmit={handleAddRecord} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700">Record Type</label>
                <select
                  value={recordType}
                  onChange={(e) => setRecordType(e.target.value as any)}
                  className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                >
                  <option value="ORIGINAL">Table 3: Original TDS Record</option>
                  <option value="AMENDMENT">Table 4: Amendment to Earlier Period</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700">Deductee GSTIN (15 chars)</label>
                <input
                  type="text"
                  required
                  maxLength={15}
                  value={deducteeGstin}
                  onChange={(e) => setDeducteeGstin(e.target.value.toUpperCase())}
                  placeholder="27ABCDE1234F1Z5"
                  className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700">Contract Value (₹)</label>
                  <input
                    type="number"
                    required
                    min={0}
                    step="0.01"
                    value={contractValue}
                    onChange={(e) => setContractValue(parseFloat(e.target.value) || 0)}
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                  />
                  <span className="text-[10px] text-gray-500">Threshold: &gt; ₹2,50,000</span>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-700">Amount Paid (₹)</label>
                  <input
                    type="number"
                    required
                    min={0}
                    step="0.01"
                    value={amountPaid}
                    onChange={(e) => setAmountPaid(parseFloat(e.target.value) || 0)}
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm font-semibold"
                  />
                  <span className="text-[10px] text-gray-500">TDS base amount</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700">Contract / PO Number</label>
                  <input
                    type="text"
                    value={contractNumber}
                    onChange={(e) => setContractNumber(e.target.value)}
                    placeholder="PO-2026-99"
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-700">Payment Voucher Ref</label>
                  <input
                    type="text"
                    value={paymentRef}
                    onChange={(e) => setPaymentRef(e.target.value)}
                    placeholder="VCH-8821"
                    className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm"
                  />
                </div>
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
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
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
