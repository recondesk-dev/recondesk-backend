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
  ArrowRightLeft,
  Building2,
} from "lucide-react";
import {
  clientsApi,
  gstr6Api,
  ClientGstin,
  Gstr6BatchSummary,
  Gstr6InwardRecord,
  Gstr6DistributionRecord,
  PreFilingValidationResult,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

interface Gstr6WorkbenchProps {
  initialClientGstinId?: string;
  initialPeriod?: string;
}

export default function Gstr6Workbench({
  initialClientGstinId,
  initialPeriod = "2026-07",
}: Gstr6WorkbenchProps) {
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [selectedClientGstinId, setSelectedClientGstinId] = useState<string>(initialClientGstinId || "");
  const [period, setPeriod] = useState<string>(initialPeriod);
  const [activeTab, setActiveTab] = useState<"inward" | "distribution" | "pool">("inward");

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
      ? ["gstr6-batch", selectedClientGstinId, period, token]
      : null,
    () => gstr6Api.getOrCreateBatch(token!, selectedClientGstinId, period)
  );

  const batchId = batchResponse?.batch?.id;

  // Fetch batch details/summary
  const {
    data: summary,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr6BatchSummary>(
    token && batchId ? ["gstr6-details", batchId, token] : null,
    () => gstr6Api.getBatchDetails(token!, batchId!)
  );

  // Inward Record Modal State
  const [isInwardModalOpen, setIsInwardModalOpen] = useState(false);
  const [supplierGstin, setSupplierGstin] = useState("");
  const [inwardInvNumber, setInwardInvNumber] = useState("");
  const [inwardInvDate, setInwardInvDate] = useState("2026-07-10");
  const [inwardTxVal, setInwardTxVal] = useState<number>(100000);
  const [inwardIgst, setInwardIgst] = useState<number>(18000);
  const [inwardCgst, setInwardCgst] = useState<number>(0);
  const [inwardSgst, setInwardSgst] = useState<number>(0);
  const [inwardCess, setInwardCess] = useState<number>(0);
  const [inwardEligible, setInwardEligible] = useState<"ELIGIBLE" | "INELIGIBLE">("ELIGIBLE");

  // Distribution Record Modal State
  const [isDistModalOpen, setIsDistModalOpen] = useState(false);
  const [recipientGstin, setRecipientGstin] = useState("");
  const [recipientState, setRecipientState] = useState("27");
  const [turnoverRatio, setTurnoverRatio] = useState<number>(1.0);
  const [distIgst, setDistIgst] = useState<number>(18000);
  const [distCgst, setDistCgst] = useState<number>(0);
  const [distSgst, setDistSgst] = useState<number>(0);
  const [distCess, setDistCess] = useState<number>(0);
  const [distCategory, setDistCategory] = useState<"ELIGIBLE" | "INELIGIBLE">("ELIGIBLE");
  const [docNumber, setDocNumber] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<PreFilingValidationResult | null>(null);

  const handleAddInward = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await gstr6Api.addInward(token, batchId, {
        supplier_gstin: supplierGstin.trim().toUpperCase(),
        invoice_number: inwardInvNumber.trim(),
        invoice_date: inwardInvDate,
        taxable_value: inwardTxVal,
        igst: inwardIgst,
        cgst: inwardCgst,
        sgst: inwardSgst,
        cess: inwardCess,
        itc_eligible: inwardEligible,
      });
      setIsInwardModalOpen(false);
      setSupplierGstin("");
      setInwardInvNumber("");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to add inward invoice");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAddDistribution = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await gstr6Api.addDistribution(token, batchId, {
        recipient_gstin: recipientGstin.trim().toUpperCase(),
        recipient_state: recipientState.trim(),
        turnover_ratio: turnoverRatio,
        distributed_igst: distIgst,
        distributed_cgst: distCgst,
        distributed_sgst: distSgst,
        distributed_cess: distCess,
        itc_category: distCategory,
        document_number: docNumber.trim() || undefined,
        document_date: "2026-07-31",
      });
      setIsDistModalOpen(false);
      setRecipientGstin("");
      setDocNumber("");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to add distribution record");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteInward = async (inwardId: string) => {
    if (!token || !batchId) return;
    try {
      await gstr6Api.deleteInward(token, batchId, inwardId);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to delete record");
    }
  };

  const handleDeleteDist = async (distId: string) => {
    if (!token || !batchId) return;
    try {
      await gstr6Api.deleteDistribution(token, batchId, distId);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to delete record");
    }
  };

  const handleValidate = async () => {
    if (!token || !batchId) return;
    try {
      const res = await gstr6Api.validate(token, batchId);
      setValidationResult(res);
      setActionStatus(res.is_valid ? "VALIDATION_PASSED" : "VALIDATION_FAILED");
    } catch (err: any) {
      setErrorMessage(err.message || "Validation failed");
    }
  };

  const handlePrepare = async () => {
    if (!token || !batchId) return;
    try {
      await gstr6Api.prepare(token, batchId);
      setActionStatus("PREPARED");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Prepare failed");
    }
  };

  const handleSubmitReview = async () => {
    if (!token || !batchId) return;
    try {
      await gstr6Api.submitReview(token, batchId, "Submitted for CA Maker-Checker review");
      setActionStatus("UNDER_REVIEW");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Review submission failed");
    }
  };

  const handleApprove = async () => {
    if (!token || !batchId) return;
    try {
      await gstr6Api.approve(token, batchId, "CA Approved for GSTR-6 filing");
      setActionStatus("APPROVED");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Approval failed");
    }
  };

  const handleDownloadOfflineJson = async () => {
    if (!token || !batchId) return;
    try {
      const json = await gstr6Api.getOfflineJson(token, batchId);
      const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR6_${batchResponse?.batch?.gstin}_${period}.json`;
      a.click();
    } catch (err: any) {
      setErrorMessage(err.message || "Offline JSON download failed");
    }
  };

  const handleFile = async () => {
    if (!token || !batchId) return;
    try {
      const pan = (batchResponse?.batch?.gstin || "").slice(2, 12);
      const res = await gstr6Api.file(token, batchId, { pan, signing_method: "evc", otp: "123456" });
      setActionStatus(`FILED (ARN: ${res.arn})`);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Filing failed");
    }
  };

  const batch = summary?.batch || batchResponse?.batch;
  const pool = summary?.pool_summary;
  const dist = summary?.distribution_summary;

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Form GSTR-6 — ISD Compliance Workbench</h1>
            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300">
              Rule 39 ISD Distribution
            </span>
          </div>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            Section 20 Input Service Distributor: pool inward invoices and allocate proportional credit to recipient distinct persons without double-counting.
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
            <span>Total Pool Inward ITC</span>
            <Building2 className="w-4 h-4 text-zinc-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-100">
            ₹{((pool?.total_pool_itc || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">Table 3 eligible invoices ({summary?.table3_inward?.length || 0})</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Total Distributed ITC</span>
            <ArrowRightLeft className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-emerald-600 dark:text-emerald-400">
            ₹{((dist?.total_distributed_itc || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">Table 5 recipient lines ({summary?.table5_distribution?.length || 0})</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Ineligible Pool</span>
            <AlertTriangle className="w-4 h-4 text-amber-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-amber-600 dark:text-amber-400">
            ₹{((pool?.total_ineligible_pool || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">Segregated Section 17(5) items</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Filing Status & Governance</span>
            <CheckCircle2 className="w-4 h-4 text-indigo-500" />
          </div>
          <div className="mt-2 text-xl font-bold text-indigo-600 dark:text-indigo-400">
            {batch?.status || "DRAFT"}
          </div>
          <div className="mt-1 text-xs text-zinc-500">
            {batch?.arn ? `ARN: ${batch.arn}` : "Due 13th of succeeding month"}
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
        <div className="p-3 bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-200 dark:border-indigo-800 rounded-lg text-sm text-indigo-700 dark:text-indigo-300">
          Governance State: <strong>{actionStatus}</strong>
        </div>
      )}

      {/* Action Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-zinc-50 dark:bg-zinc-800/60 rounded-xl border border-zinc-200 dark:border-zinc-700">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsInwardModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add Inward Invoice (Table 3)
          </button>
          <button
            onClick={() => setIsDistModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add Distribution (Table 5)
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
            Submit for Review
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
            <Lock className="w-3.5 h-3.5" /> File GSTR-6
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-zinc-200 dark:border-zinc-800 flex gap-4">
        <button
          onClick={() => setActiveTab("inward")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "inward"
              ? "border-indigo-600 text-indigo-600 dark:text-indigo-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Table 3 & 6B Inward Invoices ({summary?.table3_inward?.length || 0})
        </button>
        <button
          onClick={() => setActiveTab("distribution")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "distribution"
              ? "border-indigo-600 text-indigo-600 dark:text-indigo-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Table 5 & 6B Distribution ({summary?.table5_distribution?.length || 0})
        </button>
        <button
          onClick={() => setActiveTab("pool")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "pool"
              ? "border-indigo-600 text-indigo-600 dark:text-indigo-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Credit Pool & Statutory Integrity
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === "inward" && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 text-xs font-semibold uppercase">
                <tr>
                  <th className="p-3">Supplier GSTIN</th>
                  <th className="p-3">Invoice No.</th>
                  <th className="p-3">Date</th>
                  <th className="p-3 text-right">Taxable Val</th>
                  <th className="p-3 text-right">IGST</th>
                  <th className="p-3 text-right">CGST</th>
                  <th className="p-3 text-right">SGST</th>
                  <th className="p-3">Eligibility</th>
                  <th className="p-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 text-zinc-900 dark:text-zinc-100">
                {(summary?.table3_inward || []).map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                    <td className="p-3 font-mono text-xs">{r.supplier_gstin}</td>
                    <td className="p-3 font-medium">{r.invoice_number}</td>
                    <td className="p-3 text-xs">{r.invoice_date}</td>
                    <td className="p-3 text-right">₹{Number(r.taxable_value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="p-3 text-right font-mono text-xs">₹{Number(r.igst).toFixed(2)}</td>
                    <td className="p-3 text-right font-mono text-xs">₹{Number(r.cgst).toFixed(2)}</td>
                    <td className="p-3 text-right font-mono text-xs">₹{Number(r.sgst).toFixed(2)}</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 text-xs rounded-full ${
                        r.itc_eligible === "ELIGIBLE"
                          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                          : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                      }`}>
                        {r.itc_eligible}
                      </span>
                    </td>
                    <td className="p-3 text-center">
                      <button
                        onClick={() => handleDeleteInward(r.id)}
                        className="p-1 text-zinc-400 hover:text-red-500 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
                {(!summary?.table3_inward || summary.table3_inward.length === 0) && (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-zinc-400 text-sm">
                      No Table 3 inward invoices added yet. Click &apos;Add Inward Invoice&apos; to populate.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "distribution" && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 text-xs font-semibold uppercase">
                <tr>
                  <th className="p-3">Recipient GSTIN</th>
                  <th className="p-3">State</th>
                  <th className="p-3 text-right">Ratio</th>
                  <th className="p-3 text-right">Dist IGST</th>
                  <th className="p-3 text-right">Dist CGST</th>
                  <th className="p-3 text-right">Dist SGST</th>
                  <th className="p-3">Category</th>
                  <th className="p-3">ISD Doc No.</th>
                  <th className="p-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 text-zinc-900 dark:text-zinc-100">
                {(summary?.table5_distribution || []).map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                    <td className="p-3 font-mono text-xs">{r.recipient_gstin}</td>
                    <td className="p-3 font-semibold">{r.recipient_state}</td>
                    <td className="p-3 text-right font-mono text-xs">{(Number(r.turnover_ratio) * 100).toFixed(2)}%</td>
                    <td className="p-3 text-right font-mono text-xs text-indigo-600 dark:text-indigo-400">₹{Number(r.distributed_igst).toFixed(2)}</td>
                    <td className="p-3 text-right font-mono text-xs">₹{Number(r.distributed_cgst).toFixed(2)}</td>
                    <td className="p-3 text-right font-mono text-xs">₹{Number(r.distributed_sgst).toFixed(2)}</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 text-xs rounded-full ${
                        r.itc_category === "ELIGIBLE"
                          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                          : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
                      }`}>
                        {r.itc_category}
                      </span>
                    </td>
                    <td className="p-3 text-xs">{r.document_number || "—"}</td>
                    <td className="p-3 text-center">
                      <button
                        onClick={() => handleDeleteDist(r.id)}
                        className="p-1 text-zinc-400 hover:text-red-500 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
                {(!summary?.table5_distribution || summary.table5_distribution.length === 0) && (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-zinc-400 text-sm">
                      No Table 5 distribution entries recorded yet. Click &apos;Add Distribution&apos; to allocate credit.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "pool" && (
        <div className="p-6 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-4">
          <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">ISD Rule 39 Compliance Invariants</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div className="p-4 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg border border-zinc-200 dark:border-zinc-700">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Downstream Flow:</span>
              <p className="mt-1 text-xs text-zinc-500">
                Credit distributed via Form GSTR-6 Table 5 lands directly into recipients&apos; <strong>GSTR-2B Table 4(A)(4)</strong>. The ISD entity itself has 0 outward tax liability and cannot utilize or retain credit.
              </p>
            </div>
            <div className="p-4 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg border border-zinc-200 dark:border-zinc-700">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Cross-State Tax Head Conversion:</span>
              <p className="mt-1 text-xs text-zinc-500">
                Under Rule 39(1)(e) & (f), CGST and SGST distributed to distinct persons located in other States are converted to <strong>IGST</strong>. Intra-state distributions preserve original CGST/SGST heads.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Inward Modal */}
      {isInwardModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-xl p-6 border border-zinc-200 dark:border-zinc-800 shadow-xl space-y-4">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">Add Table 3 Inward Invoice</h2>
            <form onSubmit={handleAddInward} className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Supplier GSTIN</label>
                <input
                  type="text"
                  required
                  maxLength={15}
                  value={supplierGstin}
                  onChange={(e) => setSupplierGstin(e.target.value)}
                  placeholder="27AABCS1429B1Z1"
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono uppercase"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Invoice Number</label>
                  <input
                    type="text"
                    required
                    value={inwardInvNumber}
                    onChange={(e) => setInwardInvNumber(e.target.value)}
                    placeholder="INV-001"
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Invoice Date</label>
                  <input
                    type="date"
                    required
                    value={inwardInvDate}
                    onChange={(e) => setInwardInvDate(e.target.value)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Taxable Value (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={inwardTxVal}
                  onChange={(e) => setInwardTxVal(parseFloat(e.target.value) || 0)}
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">IGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={inwardIgst}
                    onChange={(e) => setInwardIgst(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">CGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={inwardCgst}
                    onChange={(e) => setInwardCgst(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">SGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={inwardSgst}
                    onChange={(e) => setInwardSgst(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Eligibility</label>
                <select
                  value={inwardEligible}
                  onChange={(e) => setInwardEligible(e.target.value as any)}
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                >
                  <option value="ELIGIBLE">ELIGIBLE</option>
                  <option value="INELIGIBLE">INELIGIBLE (Section 17(5))</option>
                </select>
              </div>
              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setIsInwardModalOpen(false)}
                  className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-sm font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
                >
                  {isSubmitting ? "Adding..." : "Add Inward Invoice"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Distribution Modal */}
      {isDistModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-xl p-6 border border-zinc-200 dark:border-zinc-800 shadow-xl space-y-4">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">Add Table 5 Credit Distribution</h2>
            <form onSubmit={handleAddDistribution} className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Recipient GSTIN (Distinct Person)</label>
                <input
                  type="text"
                  required
                  maxLength={15}
                  value={recipientGstin}
                  onChange={(e) => setRecipientGstin(e.target.value)}
                  placeholder="29AABCS1429B1Z3"
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono uppercase"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Recipient State Code</label>
                  <input
                    type="text"
                    required
                    maxLength={2}
                    value={recipientState}
                    onChange={(e) => setRecipientState(e.target.value)}
                    placeholder="29"
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Turnover Ratio (0.0 to 1.0)</label>
                  <input
                    type="number"
                    step="0.0001"
                    min="0"
                    max="1"
                    value={turnoverRatio}
                    onChange={(e) => setTurnoverRatio(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Dist IGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={distIgst}
                    onChange={(e) => setDistIgst(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Dist CGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={distCgst}
                    onChange={(e) => setDistCgst(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Dist SGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={distSgst}
                    onChange={(e) => setDistSgst(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Category</label>
                  <select
                    value={distCategory}
                    onChange={(e) => setDistCategory(e.target.value as any)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                  >
                    <option value="ELIGIBLE">ELIGIBLE</option>
                    <option value="INELIGIBLE">INELIGIBLE</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">ISD Invoice No.</label>
                  <input
                    type="text"
                    value={docNumber}
                    onChange={(e) => setDocNumber(e.target.value)}
                    placeholder="ISD-2026-001"
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setIsDistModalOpen(false)}
                  className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-sm font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700"
                >
                  {isSubmitting ? "Allocating..." : "Allocate Credit"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
