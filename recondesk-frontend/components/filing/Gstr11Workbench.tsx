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
  FileText,
  Calculator,
  Coins,
  Globe2,
} from "lucide-react";
import {
  clientsApi,
  gstr11Api,
  ClientGstin,
  Gstr11BatchSummary,
  Gstr11InwardRecord,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

interface Gstr11WorkbenchProps {
  initialClientGstinId?: string;
  initialPeriod?: string;
}

export default function Gstr11Workbench({
  initialClientGstinId,
  initialPeriod = "2026-10",
}: Gstr11WorkbenchProps) {
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [selectedClientGstinId, setSelectedClientGstinId] = useState<string>(initialClientGstinId || "");
  const [period, setPeriod] = useState<string>(initialPeriod);
  const [activeTab, setActiveTab] = useState<"inward" | "refund_summary" | "uin_info">("inward");
  const [supplyTypeFilter, setSupplyTypeFilter] = useState<string>("ALL");

  // Fetch client list
  const { data: clientsData } = useSWR<ClientGstin[]>(
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
      ? ["gstr11-batch", selectedClientGstinId, period, token]
      : null,
    () => gstr11Api.getOrCreateBatch(token!, selectedClientGstinId, period)
  );

  const batchId = batchResponse?.batch?.id;

  // Fetch batch details/summary
  const {
    data: summary,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr11BatchSummary>(
    token && batchId ? ["gstr11-details", batchId, token] : null,
    () => gstr11Api.getBatchDetails(token!, batchId!)
  );

  // Add Supply Modal State
  const [isSupplyModalOpen, setIsSupplyModalOpen] = useState(false);
  const [supplyType, setSupplyType] = useState("3A");
  const [supplierGstin, setSupplierGstin] = useState("27AABCU9603R1ZX");
  const [supplierName, setSupplierName] = useState("Official Supply Partner");
  const [docNumber, setDocNumber] = useState("");
  const [docDate, setDocDate] = useState("2026-10-10");
  const [cdnType, setCdnType] = useState<string>("C");
  const [originalInvoiceNumber, setOriginalInvoiceNumber] = useState("");
  const [originalInvoiceDate, setOriginalInvoiceDate] = useState("2026-10-01");
  const [taxableValue, setTaxableValue] = useState<number>(100000);
  const [taxHead, setTaxHead] = useState<"INTRA" | "INTER">("INTRA");
  const [igst, setIgst] = useState<number>(0);
  const [cgst, setCgst] = useState<number>(9000);
  const [sgst, setSgst] = useState<number>(9000);
  const [cess, setCess] = useState<number>(0);
  const [isEligibleForRefund, setIsEligibleForRefund] = useState(true);

  // Validation & Governance State
  const [validationResult, setValidationResult] = useState<any>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const batch = summary?.batch;
  const inwardRecords = summary?.inward_records || [];
  const refundSummary = summary?.refund_summary;

  const filteredRecords = inwardRecords.filter((r) => {
    if (supplyTypeFilter === "ALL") return true;
    return r.supply_type === supplyTypeFilter;
  });

  const handleAddSupply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      await gstr11Api.addInwardSupply(token, batchId, {
        supply_type: supplyType,
        supplier_gstin: supplierGstin,
        supplier_name: supplierName,
        doc_number: docNumber,
        doc_date: docDate,
        cdn_type: supplyType === "3B" ? cdnType : undefined,
        original_invoice_number: supplyType === "3B" ? originalInvoiceNumber : undefined,
        original_invoice_date: supplyType === "3B" ? originalInvoiceDate : undefined,
        taxable_value: taxableValue,
        igst: taxHead === "INTER" ? igst : 0,
        cgst: taxHead === "INTRA" ? cgst : 0,
        sgst: taxHead === "INTRA" ? sgst : 0,
        cess,
        is_eligible_for_refund: isEligibleForRefund,
      });
      setIsSupplyModalOpen(false);
      setDocNumber("");
      mutateSummary();
      mutateBatch();
      setActionMessage("Inward supply record saved successfully.");
    } catch (err: any) {
      setActionError(err.message || "Failed to add inward supply.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteSupply = async (recordId: string) => {
    if (!token || !batchId) return;
    if (!confirm("Are you sure you want to delete this inward supply record?")) return;
    try {
      await gstr11Api.deleteInwardSupply(token, batchId, recordId);
      mutateSummary();
      mutateBatch();
      setActionMessage("Inward record removed.");
    } catch (err: any) {
      setActionError(err.message || "Failed to delete record.");
    }
  };

  const handleValidate = async () => {
    if (!token || !batchId) return;
    setIsSubmitting(true);
    try {
      const res = await gstr11Api.validate(token, batchId);
      setValidationResult(res.validation);
      setActionMessage("Pre-filing statutory validation completed.");
    } catch (err: any) {
      setActionError(err.message || "Validation failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!token || !batchId) return;
    setIsSubmitting(true);
    try {
      await gstr11Api.submitReview(token, batchId);
      mutateSummary();
      mutateBatch();
      setActionMessage("Form GSTR-11 submitted for Checker review.");
    } catch (err: any) {
      setActionError(err.message || "Submit for review failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApprove = async () => {
    if (!token || !batchId) return;
    setIsSubmitting(true);
    try {
      await gstr11Api.approve(token, batchId);
      mutateSummary();
      mutateBatch();
      setActionMessage("Form GSTR-11 approved by Checker.");
    } catch (err: any) {
      setActionError(err.message || "Approval failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDownloadOfflineJson = async () => {
    if (!token || !batchId) return;
    try {
      const json = await gstr11Api.getOfflineJson(token, batchId);
      const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR11_${batch?.uin || "UIN"}_${period}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setActionMessage("GSTN offline JSON downloaded for RFD-10 support.");
    } catch (err: any) {
      setActionError(err.message || "Export failed.");
    }
  };

  const handleFile = async () => {
    if (!token || !batchId) return;
    setIsSubmitting(true);
    try {
      const res = await gstr11Api.file(token, batchId, {
        pan: batch?.uin?.slice(2, 12) || "17USA00001",
        signing_method: "evc",
      });
      if (res.status === "UNSUPPORTED_BY_GSTN_API") {
        alert(
          "Notice: GSTR-11 direct filing API is not provided by GSTN for automated GSP submission. " +
          "Your data is fully validated. Please download the official JSON and upload to the GST Common Portal to substantiate Form GST RFD-10."
        );
        handleDownloadOfflineJson();
      }
    } catch (err: any) {
      setActionError(err.message || "Filing execution failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-5">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-sky-50 text-sky-600 rounded-xl">
              <Globe2 size={24} />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-gray-900">
                Form GSTR-11 — UIN Inward Supplies & Refund Statement
              </h1>
              <p className="text-xs text-gray-500 mt-0.5">
                Statement of Inward Supplies received by Persons having Unique Identity Number (Section 55 & Rule 82)
              </p>
            </div>
          </div>
        </div>

        {/* Global Selectors */}
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label className="block text-[11px] font-semibold uppercase text-gray-400">UIN Entity</label>
            <select
              value={selectedClientGstinId}
              onChange={(e) => setSelectedClientGstinId(e.target.value)}
              className="mt-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm focus:border-brand focus:outline-none"
            >
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.trade_name || c.legal_name} ({c.gstin})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-semibold uppercase text-gray-400">Tax Period</label>
            <input
              type="month"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="mt-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm focus:border-brand focus:outline-none"
            />
          </div>
        </div>
      </div>

      {/* Critical Statutory Safeguard Banner */}
      <div className="p-4 bg-sky-50/70 border border-sky-200 text-sky-950 rounded-2xl text-xs space-y-1">
        <div className="flex items-center gap-2 font-bold text-sky-900">
          <Coins size={16} />
          <span>Statutory Safeguard under Section 55: Cash Refund vs. Business ITC</span>
        </div>
        <p className="text-sky-800 leading-relaxed">
          UIN entities (Embassies, High Commissions, Consulates, UN bodies) do not maintain an Electronic Credit Ledger.
          Inward taxes reported in Form GSTR-11 substantiate cash refund claims filed in <strong>Form GST RFD-10</strong> and are strictly barred from being classified or claimed as business ITC.
        </p>
      </div>

      {/* Banner / Status Messages */}
      {actionMessage && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} />
            <span>{actionMessage}</span>
          </div>
          <button onClick={() => setActionMessage(null)} className="text-emerald-600 hover:underline">
            Dismiss
          </button>
        </div>
      )}

      {actionError && (
        <div className="p-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} />
            <span>{actionError}</span>
          </div>
          <button onClick={() => setActionError(null)} className="text-rose-600 hover:underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Batch Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-gray-200/80 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Filing Status</span>
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
              batch?.status === "APPROVED"
                ? "bg-emerald-100 text-emerald-700"
                : batch?.status === "UNDER_REVIEW"
                ? "bg-amber-100 text-amber-700"
                : "bg-gray-100 text-gray-700"
            }`}>
              {batch?.status || "DRAFT"}
            </span>
          </div>
          <p className="mt-3 text-2xl font-black text-gray-900 tracking-tight">
            {batch?.statutory_due_date ? `Due: ${batch.statutory_due_date}` : "28th of next mo."}
          </p>
          <p className="mt-1 text-[11px] text-gray-400">
            Rule 82 statutory deadline
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200/80 bg-white p-5 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Inward Supplies</span>
          <p className="mt-3 text-2xl font-black text-gray-900 tracking-tight">
            ₹{(refundSummary?.total_inward_taxable || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </p>
          <p className="mt-1 text-[11px] text-gray-400">
            {refundSummary?.invoice_count || 0} Invoices | {refundSummary?.cdn_count || 0} CDNs
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200/80 bg-white p-5 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Eligible Cash Refund</span>
          <p className="mt-3 text-2xl font-black text-sky-600 tracking-tight">
            ₹{(refundSummary?.total_net_refund_claimed || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </p>
          <p className="mt-1 text-[11px] text-sky-500 font-medium">
            Form GST RFD-10 Claim
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200/80 bg-white p-5 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Figures Digest</span>
          <p className="mt-3 text-xs font-mono text-gray-700 truncate" title={batch?.figures_digest}>
            {batch?.figures_digest?.slice(0, 16)}...
          </p>
          <p className="mt-1 text-[11px] text-gray-400 flex items-center gap-1">
            <Lock size={10} /> Cryptographically locked
          </p>
        </div>
      </div>

      {/* Tabs & Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveTab("inward")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition ${
              activeTab === "inward"
                ? "bg-sky-50 text-sky-700 shadow-sm"
                : "text-gray-500 hover:text-gray-900"
            }`}
          >
            Inward Supplies & CDNs ({inwardRecords.length})
          </button>
          <button
            onClick={() => setActiveTab("refund_summary")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition ${
              activeTab === "refund_summary"
                ? "bg-sky-50 text-sky-700 shadow-sm"
                : "text-gray-500 hover:text-gray-900"
            }`}
          >
            Table 4: RFD-10 Refund Summary
          </button>
          <button
            onClick={() => setActiveTab("uin_info")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition ${
              activeTab === "uin_info"
                ? "bg-sky-50 text-sky-700 shadow-sm"
                : "text-gray-500 hover:text-gray-900"
            }`}
          >
            UIN Entity & Embassy Profile
          </button>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setIsSupplyModalOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600 text-white text-xs font-bold hover:bg-sky-700 transition"
          >
            <Plus size={14} /> Add Inward Supply
          </button>

          <button
            onClick={handleValidate}
            disabled={isSubmitting}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-gray-700 text-xs font-bold hover:bg-gray-50 transition"
          >
            <CheckCircle2 size={14} /> Validate
          </button>

          {batch?.status === "DRAFT" && (
            <button
              onClick={handleSubmitReview}
              disabled={isSubmitting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-amber-300 bg-amber-50 text-amber-800 text-xs font-bold hover:bg-amber-100 transition"
            >
              <Send size={14} /> Submit for Review
            </button>
          )}

          {batch?.status === "UNDER_REVIEW" && (
            <button
              onClick={handleApprove}
              disabled={isSubmitting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-emerald-300 bg-emerald-50 text-emerald-800 text-xs font-bold hover:bg-emerald-100 transition"
            >
              <CheckCircle2 size={14} /> Approve Return
            </button>
          )}

          <button
            onClick={handleDownloadOfflineJson}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-gray-700 text-xs font-bold hover:bg-gray-50 transition"
          >
            <FileJson size={14} /> Export GSTN JSON
          </button>

          <button
            onClick={handleFile}
            disabled={isSubmitting}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-900 text-white text-xs font-bold hover:bg-black transition"
          >
            <Send size={14} /> File GSTR-11
          </button>
        </div>
      </div>

      {/* Validation Result Drawer */}
      {validationResult && (
        <div className={`p-4 rounded-2xl border ${
          validationResult.overall_severity === "CLEAN"
            ? "bg-emerald-50 border-emerald-200 text-emerald-900"
            : validationResult.overall_severity === "WARNING"
            ? "bg-amber-50 border-amber-200 text-amber-900"
            : "bg-rose-50 border-rose-200 text-rose-900"
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldAlert size={18} />
              <span className="font-bold text-sm">
                Pre-Filing Validation: {validationResult.overall_severity}
              </span>
            </div>
            <span className="text-xs font-mono">
              Digest: {validationResult.validation_digest?.slice(0, 12)}...
            </span>
          </div>
          {validationResult.violations?.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs list-disc list-inside">
              {validationResult.violations.map((v: any, idx: number) => (
                <li key={idx}>
                  <span className="font-bold">[{v.code}]</span> {v.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Tab Content: Inward Supplies Table */}
      {activeTab === "inward" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            {["ALL", "3A", "3B"].map((t) => (
              <button
                key={t}
                onClick={() => setSupplyTypeFilter(t)}
                className={`px-3 py-1 rounded-lg text-xs font-bold border transition ${
                  supplyTypeFilter === t
                    ? "bg-gray-900 text-white border-gray-900"
                    : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
                }`}
              >
                {t === "ALL" ? "All Supplies" : t === "3A" ? "Table 3A (Invoices)" : "Table 3B (Credit/Debit Notes)"}
              </button>
            ))}
          </div>

          <div className="rounded-2xl border border-gray-200/80 bg-white overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-gray-50 border-b border-gray-200 text-gray-500 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Section</th>
                    <th className="px-4 py-3">Supplier GSTIN / Name</th>
                    <th className="px-4 py-3">Doc Details</th>
                    <th className="px-4 py-3 text-right">Taxable Value</th>
                    <th className="px-4 py-3 text-right">IGST</th>
                    <th className="px-4 py-3 text-right">CGST</th>
                    <th className="px-4 py-3 text-right">SGST</th>
                    <th className="px-4 py-3 text-right">Refund Amount</th>
                    <th className="px-4 py-3 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filteredRecords.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="px-4 py-12 text-center text-gray-400">
                        No inward supply records declared in Form GSTR-11. Click &quot;Add Inward Supply&quot; to add invoices.
                      </td>
                    </tr>
                  ) : (
                    filteredRecords.map((r) => {
                      const multiplier = r.supply_type === "3B" && r.cdn_type === "C" ? -1 : 1;
                      const netTax = multiplier * ((r.igst || 0) + (r.cgst || 0) + (r.sgst || 0) + (r.cess || 0));
                      return (
                        <tr key={r.id} className="hover:bg-gray-50/50">
                          <td className="px-4 py-3 font-bold text-gray-900">
                            {r.supply_type === "3A" ? (
                              <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded-md">Table 3A</span>
                            ) : (
                              <span className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded-md">
                                Table 3B ({r.cdn_type === "C" ? "Credit Note" : "Debit Note"})
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-gray-700">
                            <span className="font-mono font-semibold block">{r.supplier_gstin}</span>
                            <span className="text-gray-400 block text-[10px]">{r.supplier_name || "-"}</span>
                          </td>
                          <td className="px-4 py-3 text-gray-700">
                            <span className="font-semibold">{r.doc_number}</span>
                            <span className="text-gray-400 block text-[10px]">{r.doc_date}</span>
                          </td>
                          <td className="px-4 py-3 text-right font-medium text-gray-900">
                            ₹{r.taxable_value.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-right text-gray-700">
                            ₹{r.igst.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-right text-gray-700">
                            ₹{r.cgst.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-right text-gray-700">
                            ₹{r.sgst.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className={`px-4 py-3 text-right font-bold ${
                            netTax < 0 ? "text-rose-600" : "text-sky-600"
                          }`}>
                            ₹{netTax.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <button
                              onClick={() => handleDeleteSupply(r.id)}
                              className="text-gray-400 hover:text-rose-600 p-1"
                              title="Delete Record"
                            >
                              <Trash2 size={14} />
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab Content: RFD-10 Refund Summary Table 4 */}
      {activeTab === "refund_summary" && (
        <div className="rounded-2xl border border-gray-200/80 bg-white p-6 shadow-sm space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-gray-900">Table 4: Net Tax Refund Claimed for Form GST RFD-10</h2>
            <span className="text-xs bg-sky-50 text-sky-800 font-semibold px-3 py-1 rounded-full">
              Section 55 Direct Cash Refund
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <span className="text-xs text-gray-500 uppercase font-semibold">Net IGST Refund</span>
              <p className="mt-2 text-xl font-bold text-gray-900">
                ₹{(refundSummary?.net_eligible_refund_igst || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </p>
            </div>
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <span className="text-xs text-gray-500 uppercase font-semibold">Net CGST Refund</span>
              <p className="mt-2 text-xl font-bold text-gray-900">
                ₹{(refundSummary?.net_eligible_refund_cgst || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </p>
            </div>
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <span className="text-xs text-gray-500 uppercase font-semibold">Net SGST Refund</span>
              <p className="mt-2 text-xl font-bold text-gray-900">
                ₹{(refundSummary?.net_eligible_refund_sgst || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </p>
            </div>
            <div className="p-4 bg-sky-50 rounded-xl border border-sky-100">
              <span className="text-xs text-sky-700 uppercase font-bold">Total Claimable Refund</span>
              <p className="mt-2 text-xl font-black text-sky-900">
                ₹{(refundSummary?.total_net_refund_claimed || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Tab Content: UIN Profile */}
      {activeTab === "uin_info" && (
        <div className="rounded-2xl border border-gray-200/80 bg-white p-6 shadow-sm space-y-6">
          <h2 className="text-base font-bold text-gray-900">UIN Entity & Diplomatic Registration</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase">Unique Identity Number (UIN)</label>
              <input
                type="text"
                disabled
                value={batch?.uin || "0717USA00001UN1"}
                className="mt-1 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono font-bold text-gray-900"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase">Entity Classification</label>
              <input
                type="text"
                disabled
                value="Embassy / Specialized Agency of UN (Section 55)"
                className="mt-1 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-800"
              />
            </div>
          </div>
        </div>
      )}

      {/* Add Supply Modal */}
      {isSupplyModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-xl space-y-5">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-base font-bold text-gray-900">Add Inward Supply / Credit Note</h3>
              <button onClick={() => setIsSupplyModalOpen(false)} className="text-gray-400 hover:text-gray-600">
                ✕
              </button>
            </div>

            <form onSubmit={handleAddSupply} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Record Type</label>
                  <select
                    value={supplyType}
                    onChange={(e) => setSupplyType(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium"
                  >
                    <option value="3A">Table 3A: Inward Supply Invoice</option>
                    <option value="3B">Table 3B: Credit / Debit Note</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-600">Tax Head Structure</label>
                  <select
                    value={taxHead}
                    onChange={(e) => setTaxHead(e.target.value as any)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium"
                  >
                    <option value="INTRA">Intra-State (CGST + SGST)</option>
                    <option value="INTER">Inter-State (IGST)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Supplier GSTIN</label>
                  <input
                    type="text"
                    required
                    value={supplierGstin}
                    onChange={(e) => setSupplierGstin(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Supplier Name</label>
                  <input
                    type="text"
                    value={supplierName}
                    onChange={(e) => setSupplierName(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Document Number</label>
                  <input
                    type="text"
                    required
                    value={docNumber}
                    onChange={(e) => setDocNumber(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                    placeholder="INV-9901"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Document Date</label>
                  <input
                    type="date"
                    required
                    value={docDate}
                    onChange={(e) => setDocDate(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                  />
                </div>
              </div>

              {supplyType === "3B" && (
                <div className="grid grid-cols-3 gap-3 p-3 bg-purple-50 rounded-xl border border-purple-200">
                  <div>
                    <label className="block text-xs font-semibold text-purple-900">Note Type</label>
                    <select
                      value={cdnType}
                      onChange={(e) => setCdnType(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-purple-300 px-2 py-1 text-xs bg-white"
                    >
                      <option value="C">Credit Note (Reduces Refund)</option>
                      <option value="D">Debit Note (Increases Refund)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-purple-900">Original Invoice No.</label>
                    <input
                      type="text"
                      required
                      value={originalInvoiceNumber}
                      onChange={(e) => setOriginalInvoiceNumber(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-purple-300 px-2 py-1 text-xs bg-white"
                      placeholder="INV-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-purple-900">Original Inv. Date</label>
                    <input
                      type="date"
                      required
                      value={originalInvoiceDate}
                      onChange={(e) => setOriginalInvoiceDate(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-purple-300 px-2 py-1 text-xs bg-white"
                    />
                  </div>
                </div>
              )}

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Taxable Value (₹)</label>
                  <input
                    type="number"
                    required
                    value={taxableValue}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value) || 0;
                      setTaxableValue(v);
                      if (taxHead === "INTRA") {
                        setCgst(Math.round(v * 0.09));
                        setSgst(Math.round(v * 0.09));
                      } else {
                        setIgst(Math.round(v * 0.18));
                      }
                    }}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                  />
                </div>

                {taxHead === "INTRA" ? (
                  <>
                    <div>
                      <label className="block text-xs font-semibold text-gray-600">CGST (₹)</label>
                      <input
                        type="number"
                        value={cgst}
                        onChange={(e) => setCgst(parseFloat(e.target.value) || 0)}
                        className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-gray-600">SGST (₹)</label>
                      <input
                        type="number"
                        value={sgst}
                        onChange={(e) => setSgst(parseFloat(e.target.value) || 0)}
                        className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                      />
                    </div>
                  </>
                ) : (
                  <div>
                    <label className="block text-xs font-semibold text-gray-600">IGST (₹)</label>
                    <input
                      type="number"
                      value={igst}
                      onChange={(e) => setIgst(parseFloat(e.target.value) || 0)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                    />
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 pt-2">
                <input
                  type="checkbox"
                  id="elgRefund"
                  checked={isEligibleForRefund}
                  onChange={(e) => setIsEligibleForRefund(e.target.checked)}
                  className="rounded border-gray-300 text-sky-600 focus:ring-sky-500"
                />
                <label htmlFor="elgRefund" className="text-xs font-medium text-gray-700">
                  Eligible for Cash Refund under Section 55 (Form GST RFD-10)
                </label>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t">
                <button
                  type="button"
                  onClick={() => setIsSupplyModalOpen(false)}
                  className="px-4 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-xs font-bold text-white bg-sky-600 hover:bg-sky-700 rounded-lg shadow-sm"
                >
                  Save Inward Supply
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
