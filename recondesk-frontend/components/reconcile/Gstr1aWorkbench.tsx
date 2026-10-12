"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Download,
  FileCheck,
  FileSpreadsheet,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  XCircle,
} from "lucide-react";

import {
  gstr1aApi,
  type Gstr1aBatch,
  type Gstr1aItem,
  type Gstr1aLiabilityImpact,
} from "@/lib/api";

interface Gstr1aWorkbenchProps {
  clientGstinId: string;
  gstin: string;
  period: string;
  token: string;
  userRole?: string;
  backHref?: string;
  onRefresh?: () => void;
}

export function Gstr1aWorkbench({
  clientGstinId,
  gstin,
  period,
  token,
  userRole = "manager",
  backHref = "/reconcile/gstr1/results",
  onRefresh,
}: Gstr1aWorkbenchProps) {
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const [batch, setBatch] = useState<Gstr1aBatch | null>(null);
  const [items, setItems] = useState<Gstr1aItem[]>([]);
  const [approval, setApproval] = useState<any | null>(null);
  const [clientAuth, setClientAuth] = useState<any | null>(null);
  const [liabilityImpact, setLiabilityImpact] = useState<Gstr1aLiabilityImpact | null>(null);
  const [windowInfo, setWindowInfo] = useState<any | null>(null);

  // Modal states
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [activeDiffItem, setActiveDiffItem] = useState<Gstr1aItem | null>(null);

  // Form states
  const [formTableName, setFormTableName] = useState("4A");
  const [formActionType, setFormActionType] = useState<"ADDITION" | "AMENDMENT">("ADDITION");
  const [formOrigInv, setFormOrigInv] = useState("");
  const [formOrigDate, setFormOrigDate] = useState("");
  const [formAmenInv, setFormAmenInv] = useState("");
  const [formAmenDate, setFormAmenDate] = useState("");
  const [formRecipGstin, setFormRecipGstin] = useState("");
  const [formPos, setFormPos] = useState("");
  const [formTxVal, setFormTxVal] = useState("");
  const [formIgst, setFormIgst] = useState("");
  const [formCgst, setFormCgst] = useState("");
  const [formSgst, setFormSgst] = useState("");
  const [formNote, setFormNote] = useState("");

  const loadData = useCallback(async () => {
    if (!token || !clientGstinId || !period) return;
    setLoading(true);
    setError(null);
    try {
      const [winRes, batchRes, impactRes] = await Promise.all([
        gstr1aApi.getWindow(token, clientGstinId, period).catch(() => null),
        gstr1aApi.getBatch(token, clientGstinId, period).catch(() => null),
        gstr1aApi.getLiabilityImpact(token, clientGstinId, period).catch(() => null),
      ]);

      if (winRes?.window) setWindowInfo(winRes.window);
      if (batchRes) {
        setBatch(batchRes.batch);
        setItems(batchRes.items || []);
        setApproval(batchRes.approval);
        setClientAuth(batchRes.client_authorization);
      }
      if (impactRes) setLiabilityImpact(impactRes);
    } catch (err: any) {
      setError(err?.message || "Failed to load GSTR-1A workbench data");
    } finally {
      setLoading(false);
    }
  }, [token, clientGstinId, period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Handle Add Item
  const handleAddItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setActionBusy(true);
    setError(null);
    try {
      const amended_payload: Record<string, unknown> = {
        taxable_value: parseFloat(formTxVal) || 0,
        igst: parseFloat(formIgst) || 0,
        cgst: parseFloat(formCgst) || 0,
        sgst: parseFloat(formSgst) || 0,
        cess: 0,
        inum: formAmenInv || formOrigInv,
        idt: formAmenDate || formOrigDate,
      };

      const original_payload: Record<string, unknown> =
        formActionType === "AMENDMENT"
          ? {
              taxable_value: 0,
              igst: 0,
              cgst: 0,
              sgst: 0,
              inum: formOrigInv,
              idt: formOrigDate,
            }
          : {};

      await gstr1aApi.addItem(token, clientGstinId, period, {
        table_name: formTableName,
        action_type: formActionType,
        original_invoice_number: formOrigInv || undefined,
        original_invoice_date: formOrigDate || undefined,
        amended_invoice_number: formAmenInv || undefined,
        amended_invoice_date: formAmenDate || undefined,
        recipient_gstin: formRecipGstin || undefined,
        pos: formPos || undefined,
        original_payload,
        amended_payload,
        source_note: formNote || undefined,
        skip_window_check: false,
      });

      setSuccessMsg("Amendment item added successfully. GSTR-3B suggestions updated.");
      setAddModalOpen(false);
      // Reset form
      setFormOrigInv("");
      setFormAmenInv("");
      setFormTxVal("");
      setFormIgst("");
      setFormCgst("");
      setFormSgst("");
      setFormNote("");
      await loadData();
    } catch (err: any) {
      setError(err?.message || "Failed to add amendment item");
    } finally {
      setActionBusy(false);
    }
  };

  // Handle Delete Item
  const handleDeleteItem = async (itemId: string) => {
    if (!confirm("Remove this amendment item from GSTR-1A?")) return;
    setActionBusy(true);
    setError(null);
    try {
      await gstr1aApi.deleteItem(token, clientGstinId, period, itemId);
      setSuccessMsg("Item removed and GSTR-3B approximations refreshed.");
      await loadData();
    } catch (err: any) {
      setError(err?.message || "Failed to delete item");
    } finally {
      setActionBusy(false);
    }
  };

  // Handle JSON Export
  const handleExportJson = async () => {
    setActionBusy(true);
    try {
      const res = await gstr1aApi.exportJson(token, clientGstinId, period);
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(res.payload, null, 2));
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", res.filename || `GSTR1A_${gstin}_${period}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
      setSuccessMsg("Downloaded official GSTN offline JSON format.");
    } catch (err: any) {
      setError(err?.message || "Failed to export JSON");
    } finally {
      setActionBusy(false);
    }
  };

  // Handle Maker-Checker Prepare
  const handlePrepare = async () => {
    setActionBusy(true);
    setError(null);
    try {
      await gstr1aApi.prepare(token, clientGstinId, period, "Prepared for review via workbench");
      setSuccessMsg("GSTR-1A prepared and figures digest calculated.");
      await loadData();
    } catch (err: any) {
      setError(err?.message || "Failed to prepare return");
    } finally {
      setActionBusy(false);
    }
  };

  // Handle Maker-Checker Submit
  const handleSubmitReview = async () => {
    setActionBusy(true);
    setError(null);
    try {
      await gstr1aApi.submitReview(token, clientGstinId, period, "Submitted for Manager review");
      setSuccessMsg("Return submitted for review.");
      await loadData();
    } catch (err: any) {
      setError(err?.message || "Failed to submit for review");
    } finally {
      setActionBusy(false);
    }
  };

  // Handle Maker-Checker Approve
  const handleApprove = async () => {
    setActionBusy(true);
    setError(null);
    try {
      await gstr1aApi.approve(token, clientGstinId, period, "Approved by Manager");
      setSuccessMsg("GSTR-1A approved. Ready for Save or Client Consent.");
      await loadData();
    } catch (err: any) {
      setError(err?.message || "Failed to approve return (separation of duties enforced)");
    } finally {
      setActionBusy(false);
    }
  };

  const isWindowOpen = windowInfo?.status === "open";
  const isWindowClosed = windowInfo?.status === "window_closed";
  const isOverdue = Boolean(
    windowInfo?.is_overdue ?? (windowInfo?.days_remaining !== null && windowInfo?.days_remaining !== undefined && windowInfo.days_remaining < 0)
  );

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-gray-500" />
        <span className="ml-2 text-[14px] text-gray-500">Loading GSTR-1A Workbench…</span>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b pb-5">
        <div>
          <div className="flex items-center gap-2">
            <Link
              href={backHref}
              className="inline-flex items-center text-xs text-gray-500 hover:text-gray-900 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5 mr-1" /> Back
            </Link>
            <span className="text-gray-300">/</span>
            <span className="text-xs font-medium text-gray-500">Form GSTR-1A</span>
          </div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-gray-900">
            GSTR-1A Amendment Intelligence & Workbench
          </h1>
          <p className="mt-0.5 text-xs text-gray-500">
            GSTIN: <span className="font-mono font-medium text-gray-700">{gstin}</span> · Period:{" "}
            <span className="font-semibold text-gray-700">{period}</span>
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleExportJson}
            disabled={actionBusy || items.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" /> Export Official JSON
          </button>
          <button
            type="button"
            onClick={() => setAddModalOpen(true)}
            disabled={actionBusy || isWindowClosed}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" /> Add Invoice / Amendment
          </button>
        </div>
      </div>

      {/* Notifications */}
      {error && (
        <div className="flex items-center gap-3 rounded-lg bg-red-50 p-4 text-xs text-red-700 border border-red-200">
          <AlertTriangle className="h-4 w-4 shrink-0 text-red-500" />
          <span>{error}</span>
        </div>
      )}
      {successMsg && (
        <div className="flex items-center gap-3 rounded-lg bg-emerald-50 p-4 text-xs text-emerald-800 border border-emerald-200">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Window Status Banner */}
      <div
        className={`rounded-xl p-4 border ${
          isWindowClosed
            ? "bg-red-50/60 border-red-200 text-red-900"
            : isWindowOpen
              ? isOverdue
                ? "bg-amber-50/70 border-amber-300 text-amber-950"
                : "bg-indigo-50/60 border-indigo-200 text-indigo-950"
              : "bg-amber-50/60 border-amber-200 text-amber-900"
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-start gap-3">
            <Clock className="h-5 w-5 mt-0.5 shrink-0 opacity-80" />
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-sm">
                  Rule 59(1A) Window:{" "}
                  <span className="uppercase tracking-wide font-mono">
                    {windowInfo?.status?.replace("_", " ") || "UNKNOWN"}
                  </span>
                </span>
                {isWindowOpen && windowInfo?.days_remaining !== null && (
                  isOverdue ? (
                    <span className="inline-flex rounded-full bg-amber-200 px-2 py-0.5 text-[11px] font-bold text-amber-900">
                      GSTR-3B Overdue (Open until 3B Filing)
                    </span>
                  ) : (
                    <span className="inline-flex rounded-full bg-indigo-200/80 px-2 py-0.5 text-[11px] font-bold text-indigo-800">
                      {windowInfo?.days_remaining} Days Remaining
                    </span>
                  )
                )}
              </div>
              <p className="mt-1 text-xs opacity-90">
                {windowInfo?.note ||
                  (isWindowClosed
                    ? "GSTR-3B already filed; GSTR-1A is permanently locked for this tax period."
                    : isOverdue
                      ? "Standard GSTR-3B due date has elapsed, but GSTR-1A remains open under Rule 59(1A) until Form GSTR-3B is filed."
                      : "Available between GSTR-1 filing and GSTR-3B filing. Adjustments auto-flow into Table 3.1.")}
              </p>
            </div>
          </div>
          {windowInfo?.gstr3b_due_date && (
            <div className="text-right shrink-0">
              <span className="text-[11px] text-gray-500 block">Standard 3B Due Date</span>
              <span className="font-mono text-xs font-semibold">{windowInfo.gstr3b_due_date}</span>
            </div>
          )}
        </div>
      </div>


      {/* Outward Liability Impact Card (Table 3.1) */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm md:col-span-1">
          <span className="text-[11px] font-medium text-gray-500 block uppercase tracking-wider">
            Total Additions
          </span>
          <span className="text-2xl font-bold text-gray-900 mt-1 block">
            {batch?.total_additions || 0}
          </span>
          <span className="text-xs text-gray-400 mt-0.5 block">
            Amendments: {batch?.total_amendments || 0}
          </span>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm md:col-span-1">
          <span className="text-[11px] font-medium text-gray-500 block uppercase tracking-wider">
            Δ Taxable Value
          </span>
          <span className="text-xl font-bold font-mono text-gray-900 mt-1 block">
            ₹{(liabilityImpact?.delta_taxable_value || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </span>
          <span className="text-xs text-indigo-600 font-medium mt-0.5 block">Flows to 3.1(a)</span>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm md:col-span-1">
          <span className="text-[11px] font-medium text-gray-500 block uppercase tracking-wider">
            Δ IGST Liability
          </span>
          <span className="text-xl font-bold font-mono text-gray-900 mt-1 block">
            ₹{(liabilityImpact?.delta_igst || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </span>
          <span className="text-xs text-gray-500 mt-0.5 block">Integrated tax</span>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm md:col-span-1">
          <span className="text-[11px] font-medium text-gray-500 block uppercase tracking-wider">
            Δ CGST + SGST
          </span>
          <span className="text-xl font-bold font-mono text-gray-900 mt-1 block">
            ₹{((liabilityImpact?.delta_cgst || 0) + (liabilityImpact?.delta_sgst || 0)).toLocaleString("en-IN", {
              minimumFractionDigits: 2,
            })}
          </span>
          <span className="text-xs text-gray-500 mt-0.5 block">
            ₹{(liabilityImpact?.delta_cgst || 0).toFixed(2)} each
          </span>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm md:col-span-1">
          <span className="text-[11px] font-medium text-gray-500 block uppercase tracking-wider">
            Approval Status
          </span>
          <div className="mt-1 flex items-center gap-1.5">
            <span
              className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                batch?.status === "APPROVED"
                  ? "bg-emerald-100 text-emerald-800"
                  : batch?.status === "UNDER_REVIEW"
                    ? "bg-amber-100 text-amber-800"
                    : "bg-gray-100 text-gray-800"
              }`}
            >
              {batch?.status || "DRAFT"}
            </span>
          </div>
          <span className="text-[10px] text-gray-400 mt-1 block truncate" title={batch?.figures_digest}>
            Hash: {batch?.figures_digest?.substring(0, 10)}…
          </span>
        </div>
      </div>

      {/* Governance & Action Ribbon */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 bg-gray-50/50 p-4">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-indigo-600" />
          <span className="text-xs font-semibold text-gray-800">
            Maker-Checker Governance (Phase 3.2 Gate)
          </span>
          <span className="text-xs text-gray-500">
            · Digest-bound separation of duties enforced
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {batch?.status === "DRAFT" && (
            <button
              type="button"
              onClick={handlePrepare}
              disabled={actionBusy || items.length === 0}
              className="inline-flex items-center gap-1 rounded-md bg-white border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
            >
              <FileCheck className="h-3.5 w-3.5" /> Prepare Return
            </button>
          )}

          {batch?.status === "PREPARED" && (
            <button
              type="button"
              onClick={handleSubmitReview}
              disabled={actionBusy}
              className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
            >
              <Send className="h-3.5 w-3.5" /> Submit for Review
            </button>
          )}

          {batch?.status === "UNDER_REVIEW" && (
            <button
              type="button"
              onClick={handleApprove}
              disabled={actionBusy}
              className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-500 disabled:opacity-50"
            >
              <CheckCircle2 className="h-3.5 w-3.5" /> Approve Return (Manager)
            </button>
          )}

          <button
            type="button"
            onClick={loadData}
            disabled={actionBusy}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white p-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
            title="Refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Amendment Items Table */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">
            Invoice Additions & Amendments ({items.length})
          </h2>
          <span className="text-xs text-gray-500">
            Tables 4, 5, 6, 9A, 9B CDNR, 10
          </span>
        </div>

        {items.length === 0 ? (
          <div className="p-8 text-center text-xs text-gray-500">
            No invoice additions or amendments in this GSTR-1A batch yet. Click &quot;Add Invoice / Amendment&quot; to begin.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-left text-xs">
              <thead className="bg-gray-50 text-gray-500 font-medium">
                <tr>
                  <th className="px-4 py-3">Table</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Invoice Details</th>
                  <th className="px-4 py-3">Recipient GSTIN / POS</th>
                  <th className="px-4 py-3 text-right">Δ Taxable Val</th>
                  <th className="px-4 py-3 text-right">Δ Tax (IGST+C+S)</th>
                  <th className="px-4 py-3 text-center">Diff</th>
                  <th className="px-4 py-3 text-center">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 text-gray-800">
                {items.map((it) => (
                  <tr key={it.id} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3 font-semibold font-mono text-indigo-700">
                      {it.table_name}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          it.action_type === "ADDITION"
                            ? "bg-blue-50 text-blue-700 border border-blue-200"
                            : "bg-purple-50 text-purple-700 border border-purple-200"
                        }`}
                      >
                        {it.action_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      {it.action_type === "AMENDMENT" ? (
                        <div>
                          <span className="line-through text-gray-400 mr-1.5">
                            {it.original_invoice_number || "—"}
                          </span>
                          <span className="font-semibold text-gray-900">
                            {it.amended_invoice_number || it.original_invoice_number}
                          </span>
                        </div>
                      ) : (
                        <span className="font-semibold text-gray-900">
                          {it.amended_invoice_number || "—"}
                        </span>
                      )}
                      <div className="text-[11px] text-gray-400">
                        {it.amended_invoice_date || it.original_invoice_date || ""}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      {it.recipient_gstin || "B2C / Unreg"}
                      {it.pos && <span className="ml-1 text-gray-400">({it.pos})</span>}
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-medium">
                      ₹{it.delta_taxable_value?.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-semibold">
                      ₹{(it.delta_igst + it.delta_cgst + it.delta_sgst).toLocaleString("en-IN", {
                        minimumFractionDigits: 2,
                      })}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <button
                        type="button"
                        onClick={() => setActiveDiffItem(it)}
                        className="text-xs text-indigo-600 hover:text-indigo-900 underline font-medium"
                      >
                        View Diff
                      </button>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <button
                        type="button"
                        onClick={() => handleDeleteItem(it.id)}
                        disabled={actionBusy || isWindowClosed}
                        className="text-gray-400 hover:text-red-600 disabled:opacity-40 transition-colors"
                        title="Delete"
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
      </div>

      {/* Side-by-side Diff Modal */}
      {activeDiffItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-w-2xl w-full bg-white rounded-xl shadow-xl overflow-hidden border">
            <div className="border-b px-6 py-4 flex items-center justify-between">
              <h3 className="font-semibold text-sm text-gray-900">
                Original vs Amended Invoice Comparison ({activeDiffItem.table_name})
              </h3>
              <button
                type="button"
                onClick={() => setActiveDiffItem(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4 bg-gray-50 p-4 rounded-lg border text-xs">
                <div>
                  <span className="text-gray-500 font-medium block">Original Value / Payload</span>
                  <pre className="mt-2 text-[11px] font-mono text-gray-700 overflow-x-auto whitespace-pre-wrap">
                    {JSON.stringify(activeDiffItem.original_payload, null, 2)}
                  </pre>
                </div>
                <div>
                  <span className="text-indigo-600 font-semibold block">Amended Value / Payload</span>
                  <pre className="mt-2 text-[11px] font-mono text-gray-800 overflow-x-auto whitespace-pre-wrap">
                    {JSON.stringify(activeDiffItem.amended_payload, null, 2)}
                  </pre>
                </div>
              </div>

              <div>
                <h4 className="text-xs font-semibold text-gray-800 mb-2">Field-Level Modifications</h4>
                <div className="space-y-1.5">
                  {Object.entries(activeDiffItem.diff_summary || {}).map(([key, val]) => (
                    <div key={key} className="flex items-center justify-between text-xs border-b py-1">
                      <span className="font-medium text-gray-600">{key}</span>
                      <div className="font-mono">
                        <span className="line-through text-red-500 mr-2">
                          {String(val.original ?? "—")}
                        </span>
                        <span className="text-emerald-700 font-semibold">
                          {String(val.amended ?? "—")}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="border-t px-6 py-3 bg-gray-50 flex justify-end">
              <button
                type="button"
                onClick={() => setActiveDiffItem(null)}
                className="rounded-lg bg-gray-900 text-white px-4 py-1.5 text-xs font-medium"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add / Amend Modal */}
      {addModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <form
            onSubmit={handleAddItem}
            className="max-w-lg w-full bg-white rounded-xl shadow-xl overflow-hidden border"
          >
            <div className="border-b px-6 py-4 flex items-center justify-between">
              <h3 className="font-semibold text-sm text-gray-900">
                Add Invoice or Amendment to GSTR-1A
              </h3>
              <button
                type="button"
                onClick={() => setAddModalOpen(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>

            <div className="p-6 space-y-4 max-h-[75vh] overflow-y-auto text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-gray-700 mb-1">Target Table</label>
                  <select
                    value={formTableName}
                    onChange={(e) => setFormTableName(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs"
                  >
                    <option value="4A">Table 4A (B2B Regular)</option>
                    <option value="5">Table 5 (B2CL Large)</option>
                    <option value="6A">Table 6A (Exports)</option>
                    <option value="9A_B2B">Table 9A (B2B Amendment)</option>
                    <option value="9B_CDNR">Table 9B (Credit / Debit Note)</option>
                    <option value="10">Table 10 (B2CS Amendment)</option>
                  </select>
                </div>
                <div>
                  <label className="block font-medium text-gray-700 mb-1">Action Type</label>
                  <select
                    value={formActionType}
                    onChange={(e) => setFormActionType(e.target.value as any)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs"
                  >
                    <option value="ADDITION">ADDITION</option>
                    <option value="AMENDMENT">AMENDMENT</option>
                  </select>
                </div>
              </div>

              {formActionType === "AMENDMENT" && (
                <div className="grid grid-cols-2 gap-3 bg-gray-50 p-3 rounded-lg border">
                  <div>
                    <label className="block font-medium text-gray-700 mb-1">Original Inv Number</label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. INV-001"
                      value={formOrigInv}
                      onChange={(e) => setFormOrigInv(e.target.value)}
                      className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-gray-700 mb-1">Original Inv Date</label>
                    <input
                      type="date"
                      value={formOrigDate}
                      onChange={(e) => setFormOrigDate(e.target.value)}
                      className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                    />
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-gray-700 mb-1">Invoice Number</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. INV-001-A"
                    value={formAmenInv}
                    onChange={(e) => setFormAmenInv(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block font-medium text-gray-700 mb-1">Invoice Date</label>
                  <input
                    type="date"
                    required
                    value={formAmenDate}
                    onChange={(e) => setFormAmenDate(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-gray-700 mb-1">Recipient GSTIN</label>
                  <input
                    type="text"
                    placeholder="27A..."
                    value={formRecipGstin}
                    onChange={(e) => setFormRecipGstin(e.target.value.toUpperCase())}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block font-medium text-gray-700 mb-1">Place of Supply (POS)</label>
                  <input
                    type="text"
                    placeholder="e.g. 27"
                    value={formPos}
                    onChange={(e) => setFormPos(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-gray-700 mb-1">Taxable Value (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    placeholder="0.00"
                    value={formTxVal}
                    onChange={(e) => setFormTxVal(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block font-medium text-gray-700 mb-1">IGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    value={formIgst}
                    onChange={(e) => setFormIgst(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-gray-700 mb-1">CGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    value={formCgst}
                    onChange={(e) => setFormCgst(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block font-medium text-gray-700 mb-1">SGST (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    value={formSgst}
                    onChange={(e) => setFormSgst(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2 text-xs font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block font-medium text-gray-700 mb-1">Amendment Notes / Statutory Reason</label>
                <textarea
                  rows={2}
                  placeholder="Reason for mid-month correction..."
                  value={formNote}
                  onChange={(e) => setFormNote(e.target.value)}
                  className="w-full rounded-md border border-gray-300 p-2 text-xs"
                />
              </div>
            </div>

            <div className="border-t px-6 py-3 bg-gray-50 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setAddModalOpen(false)}
                className="rounded-lg border px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={actionBusy}
                className="rounded-lg bg-indigo-600 text-white px-4 py-1.5 text-xs font-semibold hover:bg-indigo-500 disabled:opacity-50"
              >
                {actionBusy ? "Saving…" : "Add to GSTR-1A"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
