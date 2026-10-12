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
  Globe,
  Percent,
} from "lucide-react";
import {
  clientsApi,
  gstr5aApi,
  ClientGstin,
  Gstr5aBatchSummary,
  Gstr5aRecord,
  PreFilingValidationResult,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

interface Gstr5aWorkbenchProps {
  initialClientGstinId?: string;
  initialPeriod?: string;
}

export default function Gstr5aWorkbench({
  initialClientGstinId,
  initialPeriod = "2026-07",
}: Gstr5aWorkbenchProps) {
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [selectedClientGstinId, setSelectedClientGstinId] = useState<string>(initialClientGstinId || "");
  const [period, setPeriod] = useState<string>(initialPeriod);
  const [activeTab, setActiveTab] = useState<"table5" | "table5a" | "oidar_profile">("table5");

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
    data: batchResponse,
    isLoading: isBatchLoading,
    mutate: mutateBatch,
  } = useSWR(
    token && selectedClientGstinId && period
      ? ["gstr5a-batch", selectedClientGstinId, period, token]
      : null,
    () => gstr5aApi.getOrCreateBatch(token!, selectedClientGstinId, period)
  );

  const batchId = batchResponse?.batch?.id;

  // Fetch batch details/summary
  const {
    data: summary,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr5aBatchSummary>(
    token && batchId ? ["gstr5a-details", batchId, token] : null,
    () => gstr5aApi.getBatchDetails(token!, batchId!)
  );

  // Supply Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [recordType, setRecordType] = useState<"ORIGINAL" | "AMENDMENT">("ORIGINAL");
  const [pos, setPos] = useState("27");
  const [taxableValue, setTaxableValue] = useState<number>(500000);
  const [ratePct, setRatePct] = useState<number>(18.0);
  const [cess, setCess] = useState<number>(0);
  const [origPeriod, setOrigPeriod] = useState("");
  const [origPos, setOrigPos] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<PreFilingValidationResult | null>(null);

  const handleAddRecord = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await gstr5aApi.addRecord(token, batchId, {
        record_type: recordType,
        pos: pos.trim(),
        taxable_value: taxableValue,
        rate_pct: ratePct,
        cess: cess,
        original_period: recordType === "AMENDMENT" ? origPeriod.trim() : undefined,
        original_pos: recordType === "AMENDMENT" ? origPos.trim() : undefined,
      });
      setIsModalOpen(false);
      setTaxableValue(500000);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to add OIDAR supply record");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteRecord = async (recId: string) => {
    if (!token || !batchId) return;
    try {
      await gstr5aApi.deleteRecord(token, batchId, recId);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to delete record");
    }
  };

  const handleValidate = async () => {
    if (!token || !batchId) return;
    try {
      const res = await gstr5aApi.validate(token, batchId);
      setValidationResult(res);
      setActionStatus(res.is_valid ? "VALIDATION_PASSED" : "VALIDATION_FAILED");
    } catch (err: any) {
      setErrorMessage(err.message || "Validation failed");
    }
  };

  const handlePrepare = async () => {
    if (!token || !batchId) return;
    try {
      await gstr5aApi.prepare(token, batchId);
      setActionStatus("PREPARED");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Prepare failed");
    }
  };

  const handleSubmitReview = async () => {
    if (!token || !batchId) return;
    try {
      await gstr5aApi.submitReview(token, batchId, "Submitted for CA review");
      setActionStatus("UNDER_REVIEW");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Review submission failed");
    }
  };

  const handleApprove = async () => {
    if (!token || !batchId) return;
    try {
      await gstr5aApi.approve(token, batchId, "CA Approved for GSTR-5A filing");
      setActionStatus("APPROVED");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Approval failed");
    }
  };

  const handleDownloadOfflineJson = async () => {
    if (!token || !batchId) return;
    try {
      const json = await gstr5aApi.getOfflineJson(token, batchId);
      const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR5A_${batchResponse?.batch?.gstin}_${period}.json`;
      a.click();
    } catch (err: any) {
      setErrorMessage(err.message || "Offline JSON download failed");
    }
  };

  const handleFile = async () => {
    if (!token || !batchId) return;
    try {
      const pan = (batchResponse?.batch?.gstin || "").slice(2, 12);
      const res = await gstr5aApi.file(token, batchId, { pan, signing_method: "evc", otp: "123456" });
      setActionStatus(`FILED (ARN: ${res.arn})`);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Filing failed");
    }
  };

  const batch = summary?.batch || batchResponse?.batch;
  const taxSummary = summary?.tax_summary;

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Form GSTR-5A — OIDAR Overseas Compliance</h1>
            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300">
              Section 14 IGST Act
            </span>
          </div>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            Online Information Database Access and Retrieval: B2C digital supplies to non-taxable online recipients in India at uniform 18% IGST. Zero ITC invariant.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedClientGstinId}
            onChange={(e) => setSelectedClientGstinId(e.target.value)}
            className="px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg text-zinc-900 dark:text-zinc-100"
          >
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.legal_name || c.trade_name} ({c.gstin})
              </option>
            ))}
          </select>

          <input
            type="text"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            placeholder="YYYY-MM"
            className="w-28 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg text-zinc-900 dark:text-zinc-100 font-mono"
          />
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Total Taxable Value</span>
            <Globe className="w-4 h-4 text-zinc-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-100">
            ₹{((taxSummary?.total_taxable_value || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">Cross-border supplies to India</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Total 18% IGST</span>
            <Percent className="w-4 h-4 text-violet-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-violet-600 dark:text-violet-400">
            ₹{((taxSummary?.total_igst || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">Uniform IGST head (Rule 64)</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Input Tax Credit (ITC)</span>
            <ShieldAlert className="w-4 h-4 text-amber-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-amber-600 dark:text-amber-400">
            ₹0.00
          </div>
          <div className="mt-1 text-xs text-zinc-500">Zero ITC invariant in India</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Net Tax Payable</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-emerald-600 dark:text-emerald-400">
            ₹{((taxSummary?.net_tax_payable || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">
            {batch?.arn ? `ARN: ${batch.arn}` : "Due 20th of succeeding month"}
          </div>
        </div>
      </div>

      {/* Action Banner & Status */}
      {errorMessage && (
        <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-300 flex items-center justify-between">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)} className="text-xs font-semibold underline">Dismiss</button>
        </div>
      )}

      {actionStatus && (
        <div className="p-3 bg-violet-50 dark:bg-violet-950/40 border border-violet-200 dark:border-violet-800 rounded-lg text-sm text-violet-700 dark:text-violet-300">
          Governance State: <strong>{actionStatus}</strong>
        </div>
      )}

      {/* Action Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-zinc-50 dark:bg-zinc-800/60 rounded-xl border border-zinc-200 dark:border-zinc-700">
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setRecordType("ORIGINAL"); setIsModalOpen(true); }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-violet-600 text-white rounded-lg hover:bg-violet-700 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add Table 5 Supply
          </button>
          <button
            onClick={() => { setRecordType("AMENDMENT"); setIsModalOpen(true); }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add Table 5A Amendment
          </button>
          <button
            onClick={handleValidate}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200 rounded-lg hover:bg-zinc-300"
          >
            <ShieldAlert className="w-3.5 h-3.5" /> Validate
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handlePrepare}
            className="px-3 py-1.5 text-xs font-medium bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200 rounded-lg hover:bg-zinc-300"
          >
            Prepare Return
          </button>
          <button
            onClick={handleSubmitReview}
            className="px-3 py-1.5 text-xs font-medium bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200 rounded-lg hover:bg-zinc-300"
          >
            Submit Review
          </button>
          <button
            onClick={handleApprove}
            className="px-3 py-1.5 text-xs font-medium bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200 rounded-lg hover:bg-zinc-300"
          >
            CA Approve
          </button>
          <button
            onClick={handleDownloadOfflineJson}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200 rounded-lg hover:bg-zinc-300"
          >
            <Download className="w-3.5 h-3.5" /> Offline JSON
          </button>
          <button
            onClick={handleFile}
            className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 shadow-sm"
          >
            <Lock className="w-3.5 h-3.5" /> File GSTR-5A
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-zinc-200 dark:border-zinc-800 flex gap-4">
        <button
          onClick={() => setActiveTab("table5")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "table5"
              ? "border-violet-600 text-violet-600 dark:text-violet-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Table 5 Supplies ({summary?.table5_supplies?.length || 0})
        </button>
        <button
          onClick={() => setActiveTab("table5a")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "table5a"
              ? "border-violet-600 text-violet-600 dark:text-violet-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Table 5A Amendments ({summary?.table5a_amendments?.length || 0})
        </button>
        <button
          onClick={() => setActiveTab("oidar_profile")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "oidar_profile"
              ? "border-violet-600 text-violet-600 dark:text-violet-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Statutory Framework & OIDAR Rules
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === "table5" && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 text-xs font-semibold uppercase">
                <tr>
                  <th className="p-3">POS (State)</th>
                  <th className="p-3 text-right">Taxable Value (₹)</th>
                  <th className="p-3 text-right">Rate (%)</th>
                  <th className="p-3 text-right">IGST (₹)</th>
                  <th className="p-3 text-right">Cess (₹)</th>
                  <th className="p-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 text-zinc-900 dark:text-zinc-100">
                {(summary?.table5_supplies || []).map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                    <td className="p-3 font-semibold font-mono text-xs">{r.pos}</td>
                    <td className="p-3 text-right">₹{Number(r.taxable_value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="p-3 text-right font-mono text-xs">{r.rate_pct}%</td>
                    <td className="p-3 text-right font-mono text-xs text-violet-600 dark:text-violet-400">
                      ₹{Number(r.igst).toFixed(2)}
                    </td>
                    <td className="p-3 text-right font-mono text-xs">₹{Number(r.cess).toFixed(2)}</td>
                    <td className="p-3 text-center">
                      <button
                        onClick={() => handleDeleteRecord(r.id)}
                        className="p-1 text-zinc-400 hover:text-red-500 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
                {(!summary?.table5_supplies || summary.table5_supplies.length === 0) && (
                  <tr>
                    <td colSpan={6} className="p-8 text-center text-zinc-400 text-sm">
                      No Table 5 supply entries recorded yet. Click &apos;Add Table 5 Supply&apos; to populate.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "table5a" && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 text-xs font-semibold uppercase">
                <tr>
                  <th className="p-3">Orig Period</th>
                  <th className="p-3">Orig POS</th>
                  <th className="p-3">New POS</th>
                  <th className="p-3 text-right">Taxable Value</th>
                  <th className="p-3 text-right">Rate</th>
                  <th className="p-3 text-right">Amended IGST</th>
                  <th className="p-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 text-zinc-900 dark:text-zinc-100">
                {(summary?.table5a_amendments || []).map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                    <td className="p-3 font-mono text-xs">{r.original_period || "—"}</td>
                    <td className="p-3 font-mono text-xs">{r.original_pos || r.pos}</td>
                    <td className="p-3 font-semibold font-mono text-xs">{r.pos}</td>
                    <td className="p-3 text-right">₹{Number(r.taxable_value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="p-3 text-right font-mono text-xs">{r.rate_pct}%</td>
                    <td className="p-3 text-right font-mono text-xs text-violet-600 dark:text-violet-400">
                      ₹{Number(r.igst).toFixed(2)}
                    </td>
                    <td className="p-3 text-center">
                      <button
                        onClick={() => handleDeleteRecord(r.id)}
                        className="p-1 text-zinc-400 hover:text-red-500 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
                {(!summary?.table5a_amendments || summary.table5a_amendments.length === 0) && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-zinc-400 text-sm">
                      No Table 5A amendments recorded for this tax period.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "oidar_profile" && (
        <div className="p-6 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-4">
          <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">OIDAR Statutory Compliance Invariants</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div className="p-4 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg border border-zinc-200 dark:border-zinc-700">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Single Tax Head (18% IGST):</span>
              <p className="mt-1 text-xs text-zinc-500">
                Under Section 14 of the IGST Act, cross-border digital services provided from outside India to non-taxable online recipients (consumers) in India are deemed inter-State supplies subject exclusively to Integrated Goods and Services Tax (IGST) at 18%.
              </p>
            </div>
            <div className="p-4 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg border border-zinc-200 dark:border-zinc-700">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Zero ITC Invariant:</span>
              <p className="mt-1 text-xs text-zinc-500">
                Overseas OIDAR service providers cannot claim Input Tax Credit under Indian GST law. All collections must be remitted in full via cash/electronic ledger without ITC offset.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-xl p-6 border border-zinc-200 dark:border-zinc-800 shadow-xl space-y-4">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
              {recordType === "ORIGINAL" ? "Add Table 5 Outward Supply" : "Add Table 5A Amendment"}
            </h2>
            <form onSubmit={handleAddRecord} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Place of Supply (State Code)</label>
                  <input
                    type="text"
                    required
                    maxLength={2}
                    value={pos}
                    onChange={(e) => setPos(e.target.value)}
                    placeholder="27"
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Rate (%)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={ratePct}
                    onChange={(e) => setRatePct(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Taxable Value (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={taxableValue}
                  onChange={(e) => setTaxableValue(parseFloat(e.target.value) || 0)}
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Cess (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  value={cess}
                  onChange={(e) => setCess(parseFloat(e.target.value) || 0)}
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                />
              </div>

              {recordType === "AMENDMENT" && (
                <div className="grid grid-cols-2 gap-3 pt-1 border-t border-zinc-200 dark:border-zinc-800">
                  <div>
                    <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Original Tax Period</label>
                    <input
                      type="text"
                      required
                      value={origPeriod}
                      onChange={(e) => setOrigPeriod(e.target.value)}
                      placeholder="2026-06"
                      className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Original POS Code</label>
                    <input
                      type="text"
                      required
                      maxLength={2}
                      value={origPos}
                      onChange={(e) => setOrigPos(e.target.value)}
                      placeholder="27"
                      className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                    />
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-sm font-semibold bg-violet-600 text-white rounded-lg hover:bg-violet-700"
                >
                  {isSubmitting ? "Adding..." : "Add Entry"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
