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
  Plane,
  Coins,
} from "lucide-react";
import {
  clientsApi,
  gstr5Api,
  ClientGstin,
  Gstr5BatchSummary,
  Gstr5ImportRecord,
  Gstr5OutwardRecord,
  PreFilingValidationResult,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

interface Gstr5WorkbenchProps {
  initialClientGstinId?: string;
  initialPeriod?: string;
}

export default function Gstr5Workbench({
  initialClientGstinId,
  initialPeriod = "2026-07",
}: Gstr5WorkbenchProps) {
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [selectedClientGstinId, setSelectedClientGstinId] = useState<string>(initialClientGstinId || "");
  const [period, setPeriod] = useState<string>(initialPeriod);
  const [activeTab, setActiveTab] = useState<"imports" | "outward" | "nrtp_status">("imports");

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
      ? ["gstr5-batch", selectedClientGstinId, period, token]
      : null,
    () => gstr5Api.getOrCreateBatch(token!, selectedClientGstinId, period)
  );

  const batchId = batchResponse?.batch?.id;

  // Fetch batch details/summary
  const {
    data: summary,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr5BatchSummary>(
    token && batchId ? ["gstr5-details", batchId, token] : null,
    () => gstr5Api.getBatchDetails(token!, batchId!)
  );

  // Import BoE Modal State
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [boeNumber, setBoeNumber] = useState("");
  const [boeDate, setBoeDate] = useState("2026-07-05");
  const [portCode, setPortCode] = useState("INBOM4");
  const [importTxVal, setImportTxVal] = useState<number>(200000);
  const [importIgstPaid, setImportIgstPaid] = useState<number>(36000);
  const [importCessPaid, setImportCessPaid] = useState<number>(0);

  // Outward Supply Modal State
  const [isOutwardModalOpen, setIsOutwardModalOpen] = useState(false);
  const [outwardPos, setOutwardPos] = useState("27");
  const [outwardInvNumber, setOutwardInvNumber] = useState("");
  const [outwardInvDate, setOutwardInvDate] = useState("2026-07-15");
  const [recipientGstin, setRecipientGstin] = useState("");
  const [outwardTxVal, setOutwardTxVal] = useState<number>(150000);
  const [outwardRate, setOutwardRate] = useState<number>(18);
  const [recordType, setRecordType] = useState<"ORIGINAL" | "AMENDMENT">("ORIGINAL");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<PreFilingValidationResult | null>(null);

  const handleAddImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await gstr5Api.addImport(token, batchId, {
        boe_number: boeNumber.trim(),
        boe_date: boeDate,
        port_code: portCode.trim().toUpperCase(),
        taxable_value: importTxVal,
        igst_paid: importIgstPaid,
        cess_paid: importCessPaid,
      });
      setIsImportModalOpen(false);
      setBoeNumber("");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to add import record");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAddOutward = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await gstr5Api.addOutward(token, batchId, {
        pos: outwardPos.trim(),
        invoice_number: outwardInvNumber.trim(),
        invoice_date: outwardInvDate,
        recipient_gstin: recipientGstin.trim().toUpperCase() || undefined,
        taxable_value: outwardTxVal,
        rate_pct: outwardRate,
        record_type: recordType,
      });
      setIsOutwardModalOpen(false);
      setOutwardInvNumber("");
      setRecipientGstin("");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to add outward supply");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteImport = async (importId: string) => {
    if (!token || !batchId) return;
    try {
      await gstr5Api.deleteImport(token, batchId, importId);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to delete record");
    }
  };

  const handleDeleteOutward = async (outwardId: string) => {
    if (!token || !batchId) return;
    try {
      await gstr5Api.deleteOutward(token, batchId, outwardId);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to delete record");
    }
  };

  const handleValidate = async () => {
    if (!token || !batchId) return;
    try {
      const res = await gstr5Api.validate(token, batchId);
      setValidationResult(res);
      setActionStatus(res.is_valid ? "VALIDATION_PASSED" : "VALIDATION_FAILED");
    } catch (err: any) {
      setErrorMessage(err.message || "Validation failed");
    }
  };

  const handlePrepare = async () => {
    if (!token || !batchId) return;
    try {
      await gstr5Api.prepare(token, batchId);
      setActionStatus("PREPARED");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Prepare failed");
    }
  };

  const handleSubmitReview = async () => {
    if (!token || !batchId) return;
    try {
      await gstr5Api.submitReview(token, batchId, "Submitted for CA review");
      setActionStatus("UNDER_REVIEW");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Review submission failed");
    }
  };

  const handleApprove = async () => {
    if (!token || !batchId) return;
    try {
      await gstr5Api.approve(token, batchId, "CA Approved for GSTR-5 filing");
      setActionStatus("APPROVED");
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Approval failed");
    }
  };

  const handleDownloadOfflineJson = async () => {
    if (!token || !batchId) return;
    try {
      const json = await gstr5Api.getOfflineJson(token, batchId);
      const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR5_${batchResponse?.batch?.gstin}_${period}.json`;
      a.click();
    } catch (err: any) {
      setErrorMessage(err.message || "Offline JSON download failed");
    }
  };

  const handleFile = async () => {
    if (!token || !batchId) return;
    try {
      const pan = (batchResponse?.batch?.gstin || "").slice(2, 12);
      const res = await gstr5Api.file(token, batchId, { pan, signing_method: "evc", otp: "123456" });
      setActionStatus(`FILED (ARN: ${res.arn})`);
      mutateSummary();
    } catch (err: any) {
      setErrorMessage(err.message || "Filing failed");
    }
  };

  const batch = summary?.batch || batchResponse?.batch;
  const taxSummary = summary?.tax_summary;
  const nrtpStatus = summary?.nrtp_status;

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Form GSTR-5 — Non-Resident Taxable Persons</h1>
            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300">
              Section 27 & Rule 63
            </span>
          </div>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            NRTP periodic return: BoE import ITC-only restriction, advance tax deposit reconciliation, and 90-day validity tracking.
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
            <span>Gross Tax Liability</span>
            <Coins className="w-4 h-4 text-zinc-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-100">
            ₹{((taxSummary?.gross_tax_liability || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">B2B + B2C Outward supplies</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Eligible BoE Import ITC</span>
            <Plane className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-emerald-600 dark:text-emerald-400">
            ₹{((taxSummary?.eligible_import_itc || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">Restricted to Table 3 imports (Sec 17(5))</div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Advance Tax Deposited</span>
            <ShieldAlert className="w-4 h-4 text-indigo-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-indigo-600 dark:text-indigo-400">
            ₹{((taxSummary?.advance_tax_deposited || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">
            {nrtpStatus?.is_advance_tax_sufficient ? "Sufficient for liabilities" : "Deficit — top-up required"}
          </div>
        </div>

        <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center justify-between text-zinc-500 text-sm font-medium">
            <span>Net Tax Payable</span>
            <CheckCircle2 className="w-4 h-4 text-blue-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-blue-600 dark:text-blue-400">
            ₹{((taxSummary?.net_tax_payable || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-1 text-xs text-zinc-500">
            {nrtpStatus?.statutory_due_date ? `Due: ${nrtpStatus.statutory_due_date}` : "Due 13th"}
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
        <div className="p-3 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-lg text-sm text-blue-700 dark:text-blue-300">
          Governance State: <strong>{actionStatus}</strong>
        </div>
      )}

      {/* Action Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-zinc-50 dark:bg-zinc-800/60 rounded-xl border border-zinc-200 dark:border-zinc-700">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsImportModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add BoE Import (Table 3)
          </button>
          <button
            onClick={() => setIsOutwardModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add Outward Supply (Table 5/6)
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
            <Lock className="w-3.5 h-3.5" /> File GSTR-5
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-zinc-200 dark:border-zinc-800 flex gap-4">
        <button
          onClick={() => setActiveTab("imports")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "imports"
              ? "border-blue-600 text-blue-600 dark:text-blue-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Table 3 BoE Imports ({summary?.table3_imports?.length || 0})
        </button>
        <button
          onClick={() => setActiveTab("outward")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "outward"
              ? "border-blue-600 text-blue-600 dark:text-blue-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Table 5 & 6 Outward Supplies ({((summary?.table5_b2b?.length || 0) + (summary?.table6_b2c?.length || 0))})
        </button>
        <button
          onClick={() => setActiveTab("nrtp_status")}
          className={`pb-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "nrtp_status"
              ? "border-blue-600 text-blue-600 dark:text-blue-400"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          NRTP Statutory Profile & Advance Tax
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === "imports" && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 text-xs font-semibold uppercase">
                <tr>
                  <th className="p-3">BoE Number</th>
                  <th className="p-3">BoE Date</th>
                  <th className="p-3">Port Code</th>
                  <th className="p-3 text-right">Taxable Value</th>
                  <th className="p-3 text-right">IGST Paid (ITC)</th>
                  <th className="p-3 text-right">Cess Paid</th>
                  <th className="p-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 text-zinc-900 dark:text-zinc-100">
                {(summary?.table3_imports || []).map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                    <td className="p-3 font-mono text-xs font-semibold">{r.boe_number}</td>
                    <td className="p-3 text-xs">{r.boe_date}</td>
                    <td className="p-3 font-mono text-xs">{r.port_code}</td>
                    <td className="p-3 text-right">₹{Number(r.taxable_value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="p-3 text-right font-mono text-xs text-emerald-600 dark:text-emerald-400">
                      ₹{Number(r.igst_paid).toFixed(2)}
                    </td>
                    <td className="p-3 text-right font-mono text-xs">₹{Number(r.cess_paid).toFixed(2)}</td>
                    <td className="p-3 text-center">
                      <button
                        onClick={() => handleDeleteImport(r.id)}
                        className="p-1 text-zinc-400 hover:text-red-500 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
                {(!summary?.table3_imports || summary.table3_imports.length === 0) && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-zinc-400 text-sm">
                      No Table 3 Bill of Entry import records found. Click &apos;Add BoE Import&apos; to populate.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "outward" && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 text-xs font-semibold uppercase">
                <tr>
                  <th className="p-3">Type</th>
                  <th className="p-3">Invoice No.</th>
                  <th className="p-3">Date</th>
                  <th className="p-3">POS</th>
                  <th className="p-3">Recipient GSTIN</th>
                  <th className="p-3 text-right">Taxable Val</th>
                  <th className="p-3 text-right">Rate</th>
                  <th className="p-3 text-right">Tax (IGST/CGST/SGST)</th>
                  <th className="p-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 text-zinc-900 dark:text-zinc-100">
                {[...(summary?.table5_b2b || []), ...(summary?.table6_b2c || [])].map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                    <td className="p-3">
                      <span className={`px-2 py-0.5 text-xs rounded-full ${
                        r.recipient_gstin
                          ? "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300"
                          : "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300"
                      }`}>
                        {r.recipient_gstin ? "Table 5 (B2B)" : "Table 6 (B2C)"}
                      </span>
                    </td>
                    <td className="p-3 font-medium">{r.invoice_number}</td>
                    <td className="p-3 text-xs">{r.invoice_date}</td>
                    <td className="p-3 font-semibold">{r.pos}</td>
                    <td className="p-3 font-mono text-xs">{r.recipient_gstin || "Unregistered"}</td>
                    <td className="p-3 text-right">₹{Number(r.taxable_value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                    <td className="p-3 text-right font-mono text-xs">{r.rate_pct}%</td>
                    <td className="p-3 text-right font-mono text-xs text-blue-600 dark:text-blue-400">
                      ₹{(Number(r.igst) + Number(r.cgst) + Number(r.sgst)).toFixed(2)}
                    </td>
                    <td className="p-3 text-center">
                      <button
                        onClick={() => handleDeleteOutward(r.id)}
                        className="p-1 text-zinc-400 hover:text-red-500 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
                {(!summary?.table5_b2b?.length && !summary?.table6_b2c?.length) && (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-zinc-400 text-sm">
                      No outward supplies recorded. Click &apos;Add Outward Supply&apos; to populate.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "nrtp_status" && (
        <div className="p-6 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-4">
          <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">NRTP Statutory Compliance Rules</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div className="p-4 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg border border-zinc-200 dark:border-zinc-700">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Amended Due Date (Notification No. 26/2022-CT):</span>
              <p className="mt-1 text-xs text-zinc-500">
                Rule 63 was amended: Form GSTR-5 is due on the <strong>13th of the succeeding month</strong> (previously 20th), or 7 days post-expiry of registration validity, whichever is earlier.
              </p>
            </div>
            <div className="p-4 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg border border-zinc-200 dark:border-zinc-700">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Strict Inward ITC Restriction (Section 17(5)):</span>
              <p className="mt-1 text-xs text-zinc-500">
                Non-Resident Taxable Persons are statutorily prohibited from claiming input tax credit on domestic goods and services in India. Only IGST paid on goods imported under a Bill of Entry (BoE) is eligible.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Import Modal */}
      {isImportModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-xl p-6 border border-zinc-200 dark:border-zinc-800 shadow-xl space-y-4">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">Add Table 3 Bill of Entry Import</h2>
            <form onSubmit={handleAddImport} className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Bill of Entry Number</label>
                <input
                  type="text"
                  required
                  value={boeNumber}
                  onChange={(e) => setBoeNumber(e.target.value)}
                  placeholder="BOE-998877"
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono uppercase"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">BoE Date</label>
                  <input
                    type="date"
                    required
                    value={boeDate}
                    onChange={(e) => setBoeDate(e.target.value)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Port Code (e.g. INBOM4)</label>
                  <input
                    type="text"
                    required
                    maxLength={10}
                    value={portCode}
                    onChange={(e) => setPortCode(e.target.value)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono uppercase"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Taxable Value (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={importTxVal}
                  onChange={(e) => setImportTxVal(parseFloat(e.target.value) || 0)}
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">IGST Paid (Eligible ITC) (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={importIgstPaid}
                    onChange={(e) => setImportIgstPaid(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Cess Paid (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={importCessPaid}
                    onChange={(e) => setImportCessPaid(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setIsImportModalOpen(false)}
                  className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-sm font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700"
                >
                  {isSubmitting ? "Adding..." : "Add BoE Import"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Outward Modal */}
      {isOutwardModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-xl p-6 border border-zinc-200 dark:border-zinc-800 shadow-xl space-y-4">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">Add Outward Supply</h2>
            <form onSubmit={handleAddOutward} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Invoice Number</label>
                  <input
                    type="text"
                    required
                    value={outwardInvNumber}
                    onChange={(e) => setOutwardInvNumber(e.target.value)}
                    placeholder="INV-100"
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Invoice Date</label>
                  <input
                    type="date"
                    required
                    value={outwardInvDate}
                    onChange={(e) => setOutwardInvDate(e.target.value)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Place of Supply (POS)</label>
                  <input
                    type="text"
                    required
                    maxLength={2}
                    value={outwardPos}
                    onChange={(e) => setOutwardPos(e.target.value)}
                    placeholder="27"
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Rate (%)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={outwardRate}
                    onChange={(e) => setOutwardRate(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Recipient GSTIN (Optional, leave blank for B2C)</label>
                <input
                  type="text"
                  maxLength={15}
                  value={recipientGstin}
                  onChange={(e) => setRecipientGstin(e.target.value)}
                  placeholder="27AABCT1234A1Z5"
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg font-mono uppercase"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">Taxable Value (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={outwardTxVal}
                  onChange={(e) => setOutwardTxVal(parseFloat(e.target.value) || 0)}
                  className="w-full mt-1 px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg"
                />
              </div>
              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setIsOutwardModalOpen(false)}
                  className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  {isSubmitting ? "Adding..." : "Add Outward Supply"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
