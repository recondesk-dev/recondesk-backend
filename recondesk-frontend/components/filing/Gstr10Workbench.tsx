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
  Calendar,
  Building,
} from "lucide-react";
import {
  clientsApi,
  gstr10Api,
  ClientGstin,
  Gstr10BatchSummary,
  Gstr10StockRecord,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

interface Gstr10WorkbenchProps {
  initialClientGstinId?: string;
  initialPeriod?: string;
}

export default function Gstr10Workbench({
  initialClientGstinId,
  initialPeriod = "2026-10",
}: Gstr10WorkbenchProps) {
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [selectedClientGstinId, setSelectedClientGstinId] = useState<string>(initialClientGstinId || "");
  const [period, setPeriod] = useState<string>(initialPeriod);
  const [activeTab, setActiveTab] = useState<"stock" | "cancellation" | "tax_settlement">("stock");
  const [stockTypeFilter, setStockTypeFilter] = useState<string>("ALL");

  // Fetch client GSTIN list
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
      ? ["gstr10-batch", selectedClientGstinId, period, token]
      : null,
    () => gstr10Api.getOrCreateBatch(token!, selectedClientGstinId, period)
  );

  const batchId = batchResponse?.batch?.id;

  // Fetch batch details/summary
  const {
    data: summary,
    isLoading: isSummaryLoading,
    mutate: mutateSummary,
  } = useSWR<Gstr10BatchSummary>(
    token && batchId ? ["gstr10-details", batchId, token] : null,
    () => gstr10Api.getBatchDetails(token!, batchId!)
  );

  // Add Stock Modal State
  const [isStockModalOpen, setIsStockModalOpen] = useState(false);
  const [stockItemType, setStockItemType] = useState("8A");
  const [supplierGstin, setSupplierGstin] = useState("27AABCU9603R1ZX");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("2026-09-15");
  const [description, setDescription] = useState("Raw Materials / Components");
  const [uqc, setUqc] = useState("NOS");
  const [quantity, setQuantity] = useState<number>(100);
  const [taxableValue, setTaxableValue] = useState<number>(150000);
  const [taxHead, setTaxHead] = useState<"INTRA" | "INTER">("INTRA");
  const [reverseIgst, setReverseIgst] = useState<number>(0);
  const [reverseCgst, setReverseCgst] = useState<number>(13500);
  const [reverseSgst, setReverseSgst] = useState<number>(13500);
  const [reverseCess, setReverseCess] = useState<number>(0);
  const [caName, setCaName] = useState("");
  const [caMembershipNumber, setCaMembershipNumber] = useState("");

  // Validation & Governance State
  const [validationResult, setValidationResult] = useState<any>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const batch = summary?.batch;
  const stockRecords = summary?.stock_records || [];
  const stockSummary = summary?.stock_summary;

  const filteredRecords = stockRecords.filter((r) => {
    if (stockTypeFilter === "ALL") return true;
    return r.item_type === stockTypeFilter;
  });

  const handleAddStock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !batchId) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      await gstr10Api.addStockRecord(token, batchId, {
        item_type: stockItemType,
        supplier_gstin: stockItemType !== "8D" ? supplierGstin : undefined,
        invoice_number: stockItemType !== "8D" ? invoiceNumber : undefined,
        invoice_date: stockItemType !== "8D" ? invoiceDate : undefined,
        description,
        uqc,
        quantity,
        taxable_value: taxableValue,
        reverse_igst: taxHead === "INTER" ? reverseIgst : 0,
        reverse_cgst: taxHead === "INTRA" ? reverseCgst : 0,
        reverse_sgst: taxHead === "INTRA" ? reverseSgst : 0,
        reverse_cess: reverseCess,
        ca_name: stockItemType === "8D" ? caName : undefined,
        ca_membership_number: stockItemType === "8D" ? caMembershipNumber : undefined,
      });
      setIsStockModalOpen(false);
      setInvoiceNumber("");
      mutateSummary();
      mutateBatch();
      setActionMessage("Closing stock reversal item saved successfully.");
    } catch (err: any) {
      setActionError(err.message || "Failed to add stock item.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteStock = async (recordId: string) => {
    if (!token || !batchId) return;
    if (!confirm("Are you sure you want to delete this stock item?")) return;
    try {
      await gstr10Api.deleteStockRecord(token, batchId, recordId);
      mutateSummary();
      mutateBatch();
      setActionMessage("Stock item removed.");
    } catch (err: any) {
      setActionError(err.message || "Failed to delete stock item.");
    }
  };

  const handleValidate = async () => {
    if (!token || !batchId) return;
    setIsSubmitting(true);
    try {
      const res = await gstr10Api.validate(token, batchId);
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
      await gstr10Api.submitReview(token, batchId);
      mutateSummary();
      mutateBatch();
      setActionMessage("Form GSTR-10 submitted for Checker review.");
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
      await gstr10Api.approve(token, batchId);
      mutateSummary();
      mutateBatch();
      setActionMessage("Form GSTR-10 approved by Checker.");
    } catch (err: any) {
      setActionError(err.message || "Approval failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDownloadOfflineJson = async () => {
    if (!token || !batchId) return;
    try {
      const json = await gstr10Api.getOfflineJson(token, batchId);
      const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `GSTR10_${batch?.gstin || "OFFLINE"}_${period}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setActionMessage("GSTN offline JSON downloaded.");
    } catch (err: any) {
      setActionError(err.message || "Export failed.");
    }
  };

  const handleFile = async () => {
    if (!token || !batchId) return;
    setIsSubmitting(true);
    try {
      const res = await gstr10Api.file(token, batchId, {
        pan: batch?.gstin?.slice(2, 12) || "AABCU9603R",
        signing_method: "evc",
      });
      if (res.status === "UNSUPPORTED_BY_GSTN_API") {
        alert(
          "Notice: GSTR-10 direct filing API is not provided by GSTN. " +
          "Your data is fully validated. Please download the official JSON and upload to the GST Common Portal."
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
            <div className="p-2.5 bg-rose-50 text-rose-600 rounded-xl">
              <Building size={24} />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-gray-900">
                Form GSTR-10 — Final Return Workbench
              </h1>
              <p className="text-xs text-gray-500 mt-0.5">
                Statutory Return under Section 45 & Rule 81 of CGST Act on Cancellation / Surrender of GST Registration
              </p>
            </div>
          </div>
        </div>

        {/* Global Selectors */}
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label className="block text-[11px] font-semibold uppercase text-gray-400">Client GSTIN</label>
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
            {batch?.statutory_due_date ? `Due: ${batch.statutory_due_date}` : "3 Months from Order"}
          </p>
          <p className="mt-1 text-[11px] text-gray-400">
            Section 45 statutory deadline
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200/80 bg-white p-5 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Total Stock Value</span>
          <p className="mt-3 text-2xl font-black text-gray-900 tracking-tight">
            ₹{(stockSummary?.total_taxable_value || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </p>
          <p className="mt-1 text-[11px] text-gray-400">
            {stockRecords.length} items across Table 8A-8D
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200/80 bg-white p-5 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Total ITC Reversal</span>
          <p className="mt-3 text-2xl font-black text-rose-600 tracking-tight">
            ₹{(stockSummary?.total_reversal_liability || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </p>
          <p className="mt-1 text-[11px] text-rose-500 font-medium">
            Rule 44 / Sec 29(5) Liability
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200/80 bg-white p-5 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Figures Digest</span>
          <p className="mt-3 text-xs font-mono text-gray-700 truncate" title={batch?.figures_digest}>
            {batch?.figures_digest?.slice(0, 16)}...
          </p>
          <p className="mt-1 text-[11px] text-gray-400 flex items-center gap-1">
            <Lock size={10} /> SHA-256 bound to approval
          </p>
        </div>
      </div>

      {/* Tabs & Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveTab("stock")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition ${
              activeTab === "stock"
                ? "bg-rose-50 text-rose-600 shadow-sm"
                : "text-gray-500 hover:text-gray-900"
            }`}
          >
            Table 8: Closing Stock Reversals ({stockRecords.length})
          </button>
          <button
            onClick={() => setActiveTab("cancellation")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition ${
              activeTab === "cancellation"
                ? "bg-rose-50 text-rose-600 shadow-sm"
                : "text-gray-500 hover:text-gray-900"
            }`}
          >
            Cancellation Details & Legal Orders
          </button>
          <button
            onClick={() => setActiveTab("tax_settlement")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition ${
              activeTab === "tax_settlement"
                ? "bg-rose-50 text-rose-600 shadow-sm"
                : "text-gray-500 hover:text-gray-900"
            }`}
          >
            Table 9: Tax Liability & Cash Settlement
          </button>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setIsStockModalOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition"
          >
            <Plus size={14} /> Add Stock Item
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
            <Send size={14} /> File GSTR-10
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

      {/* Tab Content: Stock Reversals */}
      {activeTab === "stock" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            {["ALL", "8A", "8B", "8C", "8D"].map((t) => (
              <button
                key={t}
                onClick={() => setStockTypeFilter(t)}
                className={`px-3 py-1 rounded-lg text-xs font-bold border transition ${
                  stockTypeFilter === t
                    ? "bg-gray-900 text-white border-gray-900"
                    : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
                }`}
              >
                {t === "ALL" ? "All Sections" : `Table ${t}`}
              </button>
            ))}
          </div>

          <div className="rounded-2xl border border-gray-200/80 bg-white overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-gray-50 border-b border-gray-200 text-gray-500 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Section</th>
                    <th className="px-4 py-3">Supplier GSTIN</th>
                    <th className="px-4 py-3">Invoice Details</th>
                    <th className="px-4 py-3">Description / UQC</th>
                    <th className="px-4 py-3 text-right">Taxable Value</th>
                    <th className="px-4 py-3 text-right">IGST</th>
                    <th className="px-4 py-3 text-right">CGST</th>
                    <th className="px-4 py-3 text-right">SGST</th>
                    <th className="px-4 py-3 text-right">Total Reversal</th>
                    <th className="px-4 py-3 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filteredRecords.length === 0 ? (
                    <tr>
                      <td colSpan={10} className="px-4 py-12 text-center text-gray-400">
                        No closing stock records declared in Form GSTR-10. Click &quot;Add Stock Item&quot; to declare.
                      </td>
                    </tr>
                  ) : (
                    filteredRecords.map((r) => {
                      const totalRev = (r.reverse_igst || 0) + (r.reverse_cgst || 0) + (r.reverse_sgst || 0) + (r.reverse_cess || 0);
                      return (
                        <tr key={r.id} className="hover:bg-gray-50/50">
                          <td className="px-4 py-3 font-bold text-gray-900">
                            Table {r.item_type}
                          </td>
                          <td className="px-4 py-3 font-mono text-gray-700">
                            {r.supplier_gstin || (r.item_type === "8D" ? "Valuation CA" : "-")}
                          </td>
                          <td className="px-4 py-3 text-gray-700">
                            {r.invoice_number ? (
                              <div>
                                <span className="font-semibold">{r.invoice_number}</span>
                                <span className="text-gray-400 block text-[10px]">{r.invoice_date}</span>
                              </div>
                            ) : (
                              <span className="text-gray-400 italic">No Invoice (Rule 44(3))</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-gray-700">
                            <span className="font-medium">{r.description}</span>
                            <span className="text-gray-400 block text-[10px]">{r.quantity} {r.uqc}</span>
                          </td>
                          <td className="px-4 py-3 text-right font-medium text-gray-900">
                            ₹{r.taxable_value.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-right text-gray-700">
                            ₹{r.reverse_igst.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-right text-gray-700">
                            ₹{r.reverse_cgst.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-right text-gray-700">
                            ₹{r.reverse_sgst.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-right font-bold text-rose-600">
                            ₹{totalRev.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <button
                              onClick={() => handleDeleteStock(r.id)}
                              className="text-gray-400 hover:text-rose-600 p-1"
                              title="Delete Item"
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

      {/* Tab Content: Cancellation & Legal Orders */}
      {activeTab === "cancellation" && (
        <div className="rounded-2xl border border-gray-200/80 bg-white p-6 shadow-sm space-y-6">
          <h2 className="text-base font-bold text-gray-900">GST Registration Cancellation Order Details</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase">Cancellation Order Number</label>
              <input
                type="text"
                disabled
                value={batch?.cancellation_order_number || "ORD/CANC/001"}
                className="mt-1 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase">Cancellation Order Date</label>
              <input
                type="text"
                disabled
                value={batch?.cancellation_order_date || "2026-09-01"}
                className="mt-1 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase">Effective Date of Cancellation</label>
              <input
                type="text"
                disabled
                value={batch?.effective_cancellation_date || "2026-08-31"}
                className="mt-1 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase">Statutory GSTR-10 Due Date</label>
              <input
                type="text"
                disabled
                value={batch?.statutory_due_date || "2026-12-01"}
                className="mt-1 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-bold text-rose-600"
              />
            </div>
          </div>
          <div className="p-4 bg-gray-50 rounded-xl text-xs text-gray-600 space-y-1">
            <p className="font-semibold text-gray-900">Section 45 Statutory Provisions:</p>
            <p>Every registered person whose registration has been cancelled must file Form GSTR-10 within three months of the date of cancellation or date of order of cancellation, whichever is later.</p>
            <p className="text-gray-500">Capital goods ITC is reversed under Rule 44(1)(b) at 5 percentage points per quarter or part thereof from the date of invoice.</p>
          </div>
        </div>
      )}

      {/* Tab Content: Tax Settlement Table 9 */}
      {activeTab === "tax_settlement" && (
        <div className="rounded-2xl border border-gray-200/80 bg-white p-6 shadow-sm space-y-6">
          <h2 className="text-base font-bold text-gray-900">Table 9: Amount of Tax Payable and Paid</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <span className="text-xs text-gray-500 uppercase font-semibold">Total Tax Payable on Stock</span>
              <p className="mt-2 text-2xl font-black text-rose-600">
                ₹{(stockSummary?.total_reversal_liability || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </p>
              <p className="mt-1 text-[11px] text-gray-400">Debit in Credit or Cash Ledger</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <span className="text-xs text-gray-500 uppercase font-semibold">Tax Paid Through Cash</span>
              <p className="mt-2 text-2xl font-black text-gray-900">
                ₹{(batch?.tax_paid_cash || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </p>
              <p className="mt-1 text-[11px] text-gray-400">Electronic Cash Ledger</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <span className="text-xs text-gray-500 uppercase font-semibold">Tax Paid Through Credit</span>
              <p className="mt-2 text-2xl font-black text-gray-900">
                ₹{(batch?.tax_paid_credit || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </p>
              <p className="mt-1 text-[11px] text-gray-400">Electronic Credit Ledger</p>
            </div>
          </div>
        </div>
      )}

      {/* Add Stock Item Modal */}
      {isStockModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-xl space-y-5">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-base font-bold text-gray-900">Add Closing Stock Item (Table 8)</h3>
              <button onClick={() => setIsStockModalOpen(false)} className="text-gray-400 hover:text-gray-600">
                ✕
              </button>
            </div>

            <form onSubmit={handleAddStock} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Table 8 Section</label>
                  <select
                    value={stockItemType}
                    onChange={(e) => setStockItemType(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium"
                  >
                    <option value="8A">Table 8A: Inputs held in stock</option>
                    <option value="8B">Table 8B: Inputs in semi-finished/finished goods</option>
                    <option value="8C">Table 8C: Capital goods or plant & machinery</option>
                    <option value="8D">Table 8D: Stock where invoice is NOT available (CA Valuation)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-600">Supply Type (Head)</label>
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

              {stockItemType !== "8D" ? (
                <div className="grid grid-cols-3 gap-3">
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
                    <label className="block text-xs font-semibold text-gray-600">Invoice Number</label>
                    <input
                      type="text"
                      required
                      value={invoiceNumber}
                      onChange={(e) => setInvoiceNumber(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                      placeholder="INV-001"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-600">Invoice Date</label>
                    <input
                      type="date"
                      required
                      value={invoiceDate}
                      onChange={(e) => setInvoiceDate(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                    />
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3 p-3 bg-amber-50 rounded-xl border border-amber-200">
                  <div>
                    <label className="block text-xs font-semibold text-amber-900">CA / CMA Name (Rule 44(3))</label>
                    <input
                      type="text"
                      required
                      value={caName}
                      onChange={(e) => setCaName(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-1.5 text-xs bg-white"
                      placeholder="CA Rajesh Sharma"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-amber-900">CA Membership Number</label>
                    <input
                      type="text"
                      required
                      value={caMembershipNumber}
                      onChange={(e) => setCaMembershipNumber(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-1.5 text-xs bg-white"
                      placeholder="123456"
                    />
                  </div>
                </div>
              )}

              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs font-semibold text-gray-600">Description of Goods</label>
                  <input
                    type="text"
                    required
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-600">UQC & Quantity</label>
                  <div className="flex gap-1 mt-1">
                    <input
                      type="number"
                      required
                      value={quantity}
                      onChange={(e) => setQuantity(parseFloat(e.target.value) || 0)}
                      className="w-2/3 rounded-lg border border-gray-300 px-2 py-1.5 text-xs"
                    />
                    <input
                      type="text"
                      value={uqc}
                      onChange={(e) => setUqc(e.target.value)}
                      className="w-1/3 rounded-lg border border-gray-300 px-1 py-1.5 text-xs uppercase"
                    />
                  </div>
                </div>
              </div>

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
                        setReverseCgst(Math.round(v * 0.09));
                        setReverseSgst(Math.round(v * 0.09));
                      } else {
                        setReverseIgst(Math.round(v * 0.18));
                      }
                    }}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                  />
                </div>

                {taxHead === "INTRA" ? (
                  <>
                    <div>
                      <label className="block text-xs font-semibold text-gray-600">CGST Reversal (₹)</label>
                      <input
                        type="number"
                        value={reverseCgst}
                        onChange={(e) => setReverseCgst(parseFloat(e.target.value) || 0)}
                        className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-gray-600">SGST Reversal (₹)</label>
                      <input
                        type="number"
                        value={reverseSgst}
                        onChange={(e) => setReverseSgst(parseFloat(e.target.value) || 0)}
                        className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                      />
                    </div>
                  </>
                ) : (
                  <div>
                    <label className="block text-xs font-semibold text-gray-600">IGST Reversal (₹)</label>
                    <input
                      type="number"
                      value={reverseIgst}
                      onChange={(e) => setReverseIgst(parseFloat(e.target.value) || 0)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs"
                    />
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t">
                <button
                  type="button"
                  onClick={() => setIsStockModalOpen(false)}
                  className="px-4 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-lg shadow-sm"
                >
                  Save Stock Item
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
