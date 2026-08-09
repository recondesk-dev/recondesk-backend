"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle,
  Clock,
  FileText,
  Globe,
  Lock,
  Printer,
  RefreshCw,
  Send,
  XCircle,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { BillingCdn, billingModuleApi } from "@/lib/api";
import { getStateNameByCode } from "@/lib/constants";

function CdnDetailContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const sessionToken = useAccessToken();

  const cdnId = params.id as string;
  const clientGstinId = searchParams.get("client_gstin_id") || "";

  const [cdn, setCdn] = useState<BillingCdn | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [finalizing, setFinalizing] = useState(false);
  const [submittingIrp, setSubmittingIrp] = useState(false);

  const loadCdn = async () => {
    if (!sessionToken || !cdnId || !clientGstinId) return;

    setLoading(true);
    try {
      const data = await billingModuleApi.getCdnDetail(sessionToken, cdnId, clientGstinId);
      setCdn(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load Credit/Debit Note.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCdn();
  }, [sessionToken, cdnId, clientGstinId]);

  const handleFinalize = async () => {
    if (!sessionToken || !cdnId || !clientGstinId) return;
    setFinalizing(true);
    try {
      await billingModuleApi.finalizeCdn(sessionToken, cdnId, clientGstinId);
      await loadCdn();
    } catch (err: any) {
      setError(err.message || "Failed to finalize CDN.");
    } finally {
      setFinalizing(false);
    }
  };

  const handleSubmitToIrp = async () => {
    if (!sessionToken || !cdnId || !clientGstinId) return;
    setSubmittingIrp(true);
    try {
      await billingModuleApi.submitCdnToIrp(sessionToken, cdnId, clientGstinId);
      await loadCdn();
    } catch (err: any) {
      setError(err.message || "IRP Submission Failed.");
    } finally {
      setSubmittingIrp(false);
    }
  };

  if (loading) {
    return (
      <div className="p-12 text-center text-slate-500 flex items-center justify-center gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" /> Loading Credit/Debit Note details...
      </div>
    );
  }

  if (!cdn) {
    return (
      <div className="p-8 text-center text-red-600 bg-red-50 rounded-2xl max-w-xl mx-auto border border-red-200 mt-10">
        <p className="font-bold text-sm">Credit/Debit Note Not Found</p>
        <p className="text-xs mt-1">{error || "Record could not be retrieved."}</p>
        <Link
          href={`/einvoicing?client_gstin_id=${clientGstinId}`}
          className="inline-block mt-4 text-xs font-bold text-indigo-600 underline"
        >
          Return to Invoices List
        </Link>
      </div>
    );
  }

  const isDraft = cdn.status === "draft";
  const isFinalized = cdn.status === "finalized";
  const isIrpRegistered = cdn.irp_status === "irp_registered" || Boolean(cdn.irn);

  const seller = cdn.company_profile;
  const buyer = cdn.customer;
  const origInv = cdn.original_invoice;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Top Bar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-gray-200 pb-4">
        <div>
          <Link
            href={origInv ? `/einvoicing/${origInv.id}?client_gstin_id=${clientGstinId}` : `/einvoicing?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-slate-700 hover:text-black font-semibold mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to {origInv ? `Invoice ${origInv.invoice_number}` : "Invoices"}
          </Link>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-bold text-slate-900 font-mono tracking-tight flex items-center gap-2">
              <FileText className="w-6 h-6 text-purple-600" />
              {cdn.note_number}
            </h1>

            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-bold uppercase tracking-wider bg-purple-100 text-purple-800 border border-purple-300">
              {cdn.note_type === "credit" ? "CREDIT NOTE" : "DEBIT NOTE"}
            </span>

            {isDraft ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                <Clock className="w-3.5 h-3.5 text-amber-500" /> DRAFT
              </span>
            ) : isIrpRegistered ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> IRN REGISTERED
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-300">
                <Lock className="w-3.5 h-3.5 text-slate-500" /> FINALIZED (PENDING IRP)
              </span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3">
          <a
            href={billingModuleApi.downloadCdnPdfUrl(cdn.id, clientGstinId)}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-4 py-2 bg-white hover:bg-slate-50 text-slate-700 rounded-xl border border-gray-200 text-xs font-semibold shadow-sm transition-colors"
          >
            <Printer className="w-4 h-4 text-slate-500" /> Download PDF
          </a>

          {isDraft && (
            <button
              onClick={handleFinalize}
              disabled={finalizing}
              className="flex items-center gap-1.5 px-4.5 py-2 bg-slate-900 hover:bg-black text-white text-xs font-semibold rounded-xl shadow-sm transition-all disabled:opacity-50"
            >
              <Lock className="w-4 h-4" /> {finalizing ? "Finalizing..." : "Finalize Note"}
            </button>
          )}

          {isFinalized && !isIrpRegistered && (
            <button
              onClick={handleSubmitToIrp}
              disabled={submittingIrp}
              className="flex items-center gap-1.5 px-4.5 py-2 bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold rounded-xl shadow-sm transition-all disabled:opacity-50"
            >
              <Send className="w-4 h-4" />
              {submittingIrp ? "Submitting to IRP..." : "Submit to IRP"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-900 p-4 rounded-2xl text-xs font-semibold flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-600 flex-shrink-0" /> {error}
        </div>
      )}

      {/* IRP IRN Registration Header Card */}
      {isIrpRegistered && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-5 space-y-3 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-emerald-900 flex items-center gap-1.5">
              <CheckCircle className="w-4 h-4 text-emerald-600" /> Government IRP Registration Details
            </span>
            <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-100 px-2.5 py-0.5 rounded-md border border-emerald-300">
              {cdn.irp_environment || "TEST"} MODE
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
            <div>
              <p className="text-slate-500 font-medium">IRN (64-Char Hash)</p>
              <p className="font-mono font-bold text-slate-900 break-all select-all text-[11px]">{cdn.irn}</p>
            </div>
            <div>
              <p className="text-slate-500 font-medium">Acknowledgement No</p>
              <p className="font-mono font-bold text-slate-900">{cdn.irn_ack_number || "N/A"}</p>
            </div>
            <div>
              <p className="text-slate-500 font-medium">Acknowledgement Date</p>
              <p className="font-bold text-slate-900">{cdn.irn_ack_date ? new Date(cdn.irn_ack_date).toLocaleString() : "N/A"}</p>
            </div>
          </div>
        </div>
      )}

      {/* Metadata & Reference Block */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-2xl p-5 space-y-3 shadow-sm text-xs">
          <h3 className="font-bold text-slate-900 border-b border-slate-100 pb-2 uppercase tracking-wider text-[11px]">
            Original Invoice Reference
          </h3>
          <p className="text-slate-600"><b>Invoice No:</b> <Link href={`/einvoicing/${origInv?.id}?client_gstin_id=${clientGstinId}`} className="font-mono font-bold text-indigo-600 underline">{origInv?.invoice_number || "N/A"}</Link></p>
          <p className="text-slate-600"><b>Invoice Date:</b> {origInv?.invoice_date || "N/A"}</p>
          <p className="text-slate-600"><b>Reason Code:</b> <span className="font-bold text-slate-900">{cdn.reason}</span></p>
          {cdn.reason_detail && <p className="text-slate-600"><b>Reason Details:</b> {cdn.reason_detail}</p>}
        </div>

        <div className="bg-white border border-gray-200 rounded-2xl p-5 space-y-3 shadow-sm text-xs">
          <h3 className="font-bold text-slate-900 border-b border-slate-100 pb-2 uppercase tracking-wider text-[11px]">
            Document Information
          </h3>
          <p className="text-slate-600"><b>Note Date:</b> {cdn.note_date}</p>
          <p className="text-slate-600"><b>Place of Supply:</b> {getStateNameByCode(origInv?.place_of_supply)} ({origInv?.place_of_supply})</p>
          <p className="text-slate-600"><b>Tax Regime:</b> {origInv?.is_interstate ? "Interstate (IGST)" : "Intrastate (CGST + SGST)"}</p>
        </div>
      </div>

      {/* Line Items Table */}
      <div className="bg-white border border-gray-200 rounded-2xl p-5 space-y-4 shadow-sm">
        <h3 className="font-bold text-slate-900 text-sm border-b border-slate-100 pb-2">
          Line Item Adjustments
        </h3>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-50 text-slate-700 font-bold border-b border-slate-200">
                <th className="p-2.5">#</th>
                <th className="p-2.5">Item Description</th>
                <th className="p-2.5 text-center">HSN/SAC</th>
                <th className="p-2.5 text-center">Qty</th>
                <th className="p-2.5 text-center">UQC</th>
                <th className="p-2.5 text-right">Rate (Rs.)</th>
                <th className="p-2.5 text-right">Taxable (Rs.)</th>
                <th className="p-2.5 text-right">Tax Amount (Rs.)</th>
                <th className="p-2.5 text-right">Total (Rs.)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {cdn.line_items?.map((item, idx) => (
                <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                  <td className="p-2.5 font-bold text-slate-400">{idx + 1}</td>
                  <td className="p-2.5 font-semibold text-slate-900">{item.description}</td>
                  <td className="p-2.5 text-center font-mono text-slate-600">{item.hsn_or_sac_code}</td>
                  <td className="p-2.5 text-center font-bold">{item.quantity}</td>
                  <td className="p-2.5 text-center font-mono text-slate-600">{item.unit}</td>
                  <td className="p-2.5 text-right font-mono">Rs. {(item.rate_paise / 100).toFixed(2)}</td>
                  <td className="p-2.5 text-right font-mono font-semibold">Rs. {(item.taxable_value_paise / 100).toFixed(2)}</td>
                  <td className="p-2.5 text-right font-mono">
                    Rs. {((item.cgst_paise + item.sgst_paise + item.igst_paise) / 100).toFixed(2)}
                  </td>
                  <td className="p-2.5 text-right font-mono font-bold text-purple-900">
                    Rs. {(item.line_total_paise / 100).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Totals Summary */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pt-4 border-t border-slate-100 bg-slate-50 p-4 rounded-xl">
          <div className="text-xs text-slate-500">
            {cdn.notes && <p><b>Notes:</b> {cdn.notes}</p>}
          </div>

          <div className="text-right space-y-1 text-xs">
            <p className="text-slate-600">Subtotal (Taxable): <span className="font-bold text-slate-900 font-mono">Rs. {(cdn.subtotal_paise / 100).toFixed(2)}</span></p>
            <p className="text-slate-600">Total Tax: <span className="font-bold text-slate-900 font-mono">Rs. {(cdn.total_tax_paise / 100).toFixed(2)}</span></p>
            <p className="text-sm font-bold text-purple-900 pt-1">
              Grand Total: <span className="font-mono">Rs. {(cdn.total_paise / 100).toFixed(2)}</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function CdnDetailPage() {
  return (
    <Suspense fallback={<div className="p-12 text-center text-slate-500">Loading Credit/Debit Note...</div>}>
      <CdnDetailContent />
    </Suspense>
  );
}
