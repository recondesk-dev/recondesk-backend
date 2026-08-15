"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  FileText,
  Lock,
  CheckCircle,
  Clock,
  ArrowLeft,
  Printer,
  Globe,
  QrCode,
  Send,
  AlertTriangle,
  Copy,
  Check,
  XCircle,
  ShieldAlert,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { billingModuleApi, BillingInvoice } from "@/lib/api";

function InvoiceDetailContent() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = useAccessToken();

  const invoiceId = params?.id as string;
  const clientGstinId = searchParams.get("client_gstin_id") || "";

  const [invoice, setInvoice] = useState<BillingInvoice | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [finalizing, setFinalizing] = useState<boolean>(false);
  const [showFinalizeModal, setShowFinalizeModal] = useState<boolean>(false);

  const [submittingIrp, setSubmittingIrp] = useState<boolean>(false);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  const [cancellingIrn, setCancellingIrn] = useState<boolean>(false);
  const [showCancelModal, setShowCancelModal] = useState<boolean>(false);
  const [cancelReason, setCancelReason] = useState<string>("2");
  const [cancelRemarks, setCancelRemarks] = useState<string>("Data entry error in invoice header");

  const [copiedIrn, setCopiedIrn] = useState<boolean>(false);

  useEffect(() => {
    if (!token || !invoiceId || !clientGstinId) return;
    setLoading(true);
    billingModuleApi
      .getInvoice(token, invoiceId, clientGstinId)
      .then((data) => setInvoice(data))
      .catch((err) => setError(err.detail || "Failed to load invoice"))
      .finally(() => setLoading(false));
  }, [token, invoiceId, clientGstinId]);

  const handleFinalize = async () => {
    if (!token || !invoiceId || !clientGstinId) return;
    setFinalizing(true);
    try {
      const updated = await billingModuleApi.finalizeInvoice(token, invoiceId, clientGstinId);
      setInvoice(updated);
      setShowFinalizeModal(false);
    } catch (err: any) {
      alert(err.detail || "Failed to finalize invoice");
    }
    setFinalizing(false);
  };

  const handleSubmitToIrp = async () => {
    if (!token || !invoiceId || !clientGstinId) return;
    const confirmed = window.confirm(
      "IRP Integration Notice — Pending Verification:\n\n" +
      "IRN generation is implemented in Test Mode but has not yet been verified end-to-end with a live GSTIN. Use with caution.\n\n" +
      "Do you wish to proceed with submitting this invoice to the IRP portal in Test Mode?"
    );
    if (!confirmed) return;

    setSubmittingIrp(true);
    setValidationErrors([]);
    try {
      const updated = await billingModuleApi.submitToIrp(token, invoiceId, clientGstinId);
      setInvoice(updated);
    } catch (err: any) {
      const raw = err?.rawDetail || err?.detail;
      if (raw && typeof raw === "object" && Array.isArray(raw.errors)) {
        setValidationErrors(raw.errors);
      } else if (Array.isArray(err?.errors)) {
        setValidationErrors(err.errors);
      } else if (typeof err?.detail === "string" && err.detail.includes("; ")) {
        setValidationErrors(err.detail.split("; "));
      } else {
        setValidationErrors([err?.detail || err?.message || "Failed to submit invoice to IRP portal"]);
      }
    }
    setSubmittingIrp(false);
  };

  const handleCancelIrn = async () => {
    if (!token || !invoiceId || !clientGstinId) return;
    if (!cancelRemarks.trim()) {
      alert("Please enter a cancellation remark.");
      return;
    }
    setCancellingIrn(true);
    try {
      const updated = await billingModuleApi.cancelIrn(
        token,
        invoiceId,
        clientGstinId,
        cancelReason,
        cancelRemarks.trim()
      );
      setInvoice(updated);
      setShowCancelModal(false);
    } catch (err: any) {
      alert(err.detail || "Failed to cancel IRN on IRP");
    }
    setCancellingIrn(false);
  };

  const handleCopyIrn = () => {
    if (!invoice?.irn) return;
    navigator.clipboard.writeText(invoice.irn);
    setCopiedIrn(true);
    setTimeout(() => setCopiedIrn(false), 2000);
  };

  if (loading) {
    return <div className="p-12 text-center text-slate-500 font-medium">Loading invoice details...</div>;
  }

  if (error || !invoice) {
    return (
      <div className="p-12 text-center text-red-600 space-y-4">
        <p className="font-semibold">{error || "Invoice not found"}</p>
        <Link
          href={`/einvoicing?client_gstin_id=${clientGstinId}`}
          className="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-800 rounded-xl text-sm font-semibold hover:bg-slate-200 border border-gray-200"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Invoices
        </Link>
      </div>
    );
  }

  const isDraft = invoice.status === "draft";
  const isFinalized = invoice.status === "finalized";
  const irpStatus = invoice.irp_status || "not_submitted";
  const isIrpRegistered = irpStatus === "irp_registered" || !!invoice.irn;
  const isIrpCancelled = irpStatus === "cancelled";
  const irpEnv = invoice.irp_environment || "test";

  const seller = invoice.company_profile;
  const buyer = invoice.customer;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Top Bar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-gray-200 pb-4">
        <div>
          <Link
            href={`/einvoicing?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-slate-800 hover:text-black font-semibold mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Invoices List
          </Link>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-bold text-slate-900 font-mono tracking-tight">{invoice.invoice_number}</h1>

            {/* Environment Badge */}
            <span
              className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-bold uppercase tracking-wider ${
                irpEnv === "test"
                  ? "bg-amber-100 text-amber-800 border border-amber-300"
                  : "bg-indigo-100 text-indigo-800 border border-indigo-300"
              }`}
            >
              <Globe className="w-3 h-3" /> {irpEnv === "test" ? "TEST MODE" : "PRODUCTION"}
            </span>

            {/* Status Pills */}
            {isDraft ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                <Clock className="w-3.5 h-3.5 text-amber-500" /> DRAFT
              </span>
            ) : isIrpRegistered ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> IRN REGISTERED
              </span>
            ) : isIrpCancelled ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-red-50 text-red-700 border border-red-200">
                <XCircle className="w-3.5 h-3.5 text-red-500" /> IRN CANCELLED
              </span>
            ) : isFinalized ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-300">
                <Lock className="w-3.5 h-3.5 text-slate-500" /> FINALIZED (NOT SUBMITTED)
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-red-50 text-red-700 border border-red-200">
                CANCELLED
              </span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3">
          <a
            href={billingModuleApi.downloadInvoicePdfUrl(invoice.id, clientGstinId)}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-4 py-2 bg-white hover:bg-slate-50 text-slate-700 rounded-xl border border-gray-200 text-xs font-semibold shadow-sm transition-colors"
          >
            <Printer className="w-4 h-4 text-slate-500" /> Download PDF
          </a>

          {isDraft && (
            <button
              onClick={() => setShowFinalizeModal(true)}
              className="flex items-center gap-1.5 px-4.5 py-2 bg-slate-900 hover:bg-black text-white text-xs font-semibold rounded-xl shadow-sm transition-all"
            >
              <Lock className="w-4 h-4" /> Finalize Invoice
            </button>
          )}

          {isFinalized && !isIrpRegistered && !isIrpCancelled && (
            <button
              onClick={handleSubmitToIrp}
              disabled={submittingIrp}
              className="flex items-center gap-1.5 px-4.5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-xl shadow-sm transition-all disabled:opacity-50"
            >
              <Send className="w-4 h-4" />
              {submittingIrp ? "Submitting to IRP..." : "Submit to IRP"}
            </button>
          )}

          {isIrpRegistered && !isIrpCancelled && (
            <>
              <Link
                href={`/einvoicing/${invoice.id}/cdn/new?client_gstin_id=${clientGstinId}&note_type=credit`}
                className="flex items-center gap-1.5 px-4 py-2 bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 text-xs font-semibold rounded-xl shadow-sm transition-all"
              >
                <FileText className="w-4 h-4 text-purple-600" /> Issue Credit Note
              </Link>
              <button
                onClick={() => setShowCancelModal(true)}
                className="flex items-center gap-1.5 px-4 py-2 bg-red-50 hover:bg-red-100 text-red-700 border border-red-200 text-xs font-semibold rounded-xl shadow-sm transition-all"
              >
                <XCircle className="w-4 h-4 text-red-600" /> Cancel IRN
              </button>
            </>
          )}
        </div>
      </div>

      {/* Validation Errors Drawer / Alert */}
      {validationErrors.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-4 space-y-2 text-xs text-red-900 shadow-sm">
          <div className="flex items-center gap-2 font-bold text-red-800 text-sm">
            <AlertTriangle className="w-4 h-4 text-red-600" /> Pre-Submission Validation Errors
          </div>
          <p className="text-red-700">Please resolve the following issues before submitting this invoice to IRP:</p>
          <ul className="list-disc pl-5 space-y-1 font-medium text-red-800">
            {validationErrors.map((err, idx) => (
              <li key={idx}>{err}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Persisted IRP Submission Rejection Error Card */}
      {invoice?.irp_error_detail && validationErrors.length === 0 && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-4 space-y-2 text-xs text-red-900 shadow-sm">
          <div className="flex items-center gap-2 font-bold text-red-800 text-sm">
            <AlertTriangle className="w-4 h-4 text-red-600 flex-shrink-0" /> IRP Portal Rejection Detail
          </div>
          <p className="text-red-700">The last IRP submission for this invoice was rejected with the following government response:</p>
          <div className="font-mono text-red-950 bg-red-100/70 p-3 rounded-xl border border-red-200/80 whitespace-pre-wrap break-words text-[11px] leading-relaxed">
            {invoice.irp_error_detail}
          </div>
        </div>
      )}

      {/* Active IRN Card (when Registered) */}
      {isIrpRegistered && (
        <div className="bg-emerald-950 text-white rounded-2xl p-6 space-y-5 shadow-md border border-emerald-800">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-emerald-800 pb-4">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-emerald-400" />
              <div>
                <h3 className="text-base font-bold text-white tracking-wide">Government e-Invoice (IRN Registered)</h3>
                <p className="text-xs text-emerald-300">Official Invoice Reference Number generated on IRP</p>
              </div>
            </div>

            <span className="px-3 py-1 bg-emerald-900/80 text-emerald-300 text-xs font-mono font-semibold rounded-lg border border-emerald-700/60 self-start sm:self-auto">
              Ack No: {invoice.irn_ack_number || "N/A"}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-center">
            {/* IRN Details */}
            <div className="md:col-span-2 space-y-3">
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400 block mb-1">
                  Invoice Reference Number (IRN)
                </span>
                <div className="flex items-center gap-2 bg-emerald-900/60 p-2.5 rounded-xl border border-emerald-800 font-mono text-xs text-emerald-100 break-all select-all">
                  <span className="flex-1">{invoice.irn}</span>
                  <button
                    onClick={handleCopyIrn}
                    className="p-1.5 hover:bg-emerald-800 rounded-lg text-emerald-300 hover:text-white transition-colors"
                    title="Copy IRN"
                  >
                    {copiedIrn ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <span className="text-emerald-400 font-medium block">Ack Date & Time</span>
                  <span className="font-mono text-emerald-100 mt-0.5 block">{invoice.irn_ack_date || "N/A"}</span>
                </div>
                <div>
                  <span className="text-emerald-400 font-medium block">IRP Portal Environment</span>
                  <span className="font-mono uppercase text-emerald-100 mt-0.5 block">{irpEnv}</span>
                </div>
              </div>
            </div>

            {/* QR Code Graphic Display */}
            <div className="flex flex-col items-center justify-center p-3 bg-white text-slate-900 rounded-xl shadow-inner border border-emerald-800 text-center">
              {invoice.irn_qr_code ? (
                <div className="w-28 h-28 bg-slate-100 flex items-center justify-center rounded-lg border border-slate-200 p-1">
                  {/* Signed QR Representation */}
                  <div className="w-full h-full bg-slate-900 rounded flex flex-col items-center justify-center p-2 text-white text-[9px] font-mono leading-tight">
                    <QrCode className="w-12 h-12 text-emerald-400 mb-1" />
                    <span>IRP QR SIGNED</span>
                  </div>
                </div>
              ) : (
                <div className="w-28 h-28 bg-slate-100 flex items-center justify-center rounded-lg border border-slate-200">
                  <QrCode className="w-12 h-12 text-slate-400" />
                </div>
              )}
              <span className="text-[10px] font-semibold text-slate-600 mt-2">Official Signed QR Code</span>
            </div>
          </div>
        </div>
      )}

      {/* Lock Notice */}
      {isFinalized && !isIrpRegistered && (
        <div className="bg-slate-100 border border-slate-200 rounded-2xl p-4 flex items-start gap-3 text-slate-900 text-xs shadow-sm">
          <Lock className="w-4 h-4 text-slate-700 flex-shrink-0 mt-0.5" />
          <div className="leading-relaxed">
            <span className="font-bold text-slate-950">Invoice Record Finalized & Locked:</span> This invoice has been finalized internally. Line items and rates are locked. Click <span className="font-semibold text-indigo-600">"Submit to IRP"</span> above to generate government IRN.
          </div>
        </div>
      )}

      {/* Invoice Document Card */}
      <div className="bg-white border border-gray-200/80 rounded-2xl p-8 space-y-8 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-b border-gray-100 pb-6">
          {/* Seller Details */}
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-2">
              Seller (Billed From)
            </span>
            <h2 className="text-base font-bold text-slate-900">{seller?.legal_name || "N/A"}</h2>
            {seller?.trade_name && <p className="text-xs text-slate-500 mt-0.5">{seller.trade_name}</p>}
            <p className="text-xs font-mono text-slate-700 font-semibold mt-1">GSTIN: {seller?.gstin || "N/A"}</p>
            <p className="text-xs text-slate-600 mt-2 leading-relaxed">
              {seller?.address_line1} {seller?.address_line2}
              <br />
              {seller?.city}, {seller?.state} - {seller?.pincode}
            </p>
          </div>

          {/* Customer Details */}
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-2">
              Buyer (Billed To)
            </span>
            <h2 className="text-base font-bold text-slate-900">{buyer?.name || "N/A"}</h2>
            {buyer?.gstin ? (
              <p className="text-xs font-mono text-slate-700 font-semibold mt-1">GSTIN: {buyer.gstin}</p>
            ) : (
              <p className="text-xs text-slate-500 mt-1">B2C Consumer</p>
            )}
            <p className="text-xs text-slate-600 mt-2 leading-relaxed">
              {buyer?.address_line1} {buyer?.address_line2}
              <br />
              {buyer?.city}, {buyer?.state} - {buyer?.pincode}
            </p>
          </div>
        </div>

        {/* Metadata Pills */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 bg-slate-50 rounded-xl border border-gray-200/80 text-xs">
          <div>
            <span className="text-slate-500 font-medium block">Invoice Date</span>
            <span className="font-semibold text-slate-900 mt-0.5 block">{invoice.invoice_date}</span>
          </div>
          <div>
            <span className="text-slate-500 font-medium block">Due Date</span>
            <span className="font-semibold text-slate-900 mt-0.5 block">{invoice.due_date || "N/A"}</span>
          </div>
          <div>
            <span className="text-slate-500 font-medium block">Place of Supply</span>
            <span className="font-semibold text-slate-900 mt-0.5 block">{invoice.place_of_supply}</span>
          </div>
          <div>
            <span className="text-slate-500 font-medium block">Tax Regime</span>
            <span className="font-semibold text-slate-900 mt-0.5 block">
              {invoice.is_interstate ? "Interstate (IGST)" : "Intrastate (CGST + SGST)"}
            </span>
          </div>
        </div>

        {/* Line Items Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-800">
            <thead className="bg-slate-50/80 text-xs font-semibold text-slate-500 uppercase tracking-wider border-b border-gray-200/80">
              <tr>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">HSN/SAC</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Rate (₹)</th>
                <th className="px-4 py-3 text-right">Disc %</th>
                <th className="px-4 py-3 text-right">Taxable (₹)</th>
                <th className="px-4 py-3 text-right">Tax Breakdown</th>
                <th className="px-4 py-3 text-right">Total (₹)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(invoice.line_items || []).map((line) => (
                <tr key={line.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3 font-semibold text-slate-900">{line.description}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{line.hsn_or_sac_code}</td>
                  <td className="px-4 py-3 text-right font-mono">{line.quantity} {line.unit}</td>
                  <td className="px-4 py-3 text-right font-mono">₹{(line.rate_paise / 100).toFixed(2)}</td>
                  <td className="px-4 py-3 text-right font-mono text-xs">{line.discount_percent}%</td>
                  <td className="px-4 py-3 text-right font-mono font-medium">
                    ₹{(line.taxable_value_paise / 100).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-xs">
                    {invoice.is_interstate ? (
                      <span className="text-slate-800 font-semibold">IGST {line.igst_rate_percent}%: ₹{(line.igst_paise / 100).toFixed(2)}</span>
                    ) : (
                      <span className="text-slate-800 font-semibold">
                        C: {line.cgst_rate_percent}% (₹{(line.cgst_paise / 100).toFixed(2)}) + S: {line.sgst_rate_percent}% (₹{(line.sgst_paise / 100).toFixed(2)})
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-bold text-slate-900">
                    ₹{(line.line_total_paise / 100).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer Notes & Summary */}
        <div className="flex flex-col sm:flex-row justify-between items-start pt-6 border-t border-gray-100 gap-6">
          <div className="w-full sm:w-1/2 space-y-3">
            {invoice.notes && (
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Notes / Terms:</span>
                <p className="text-xs text-slate-700 bg-slate-50 p-3.5 rounded-xl border border-gray-200/80 whitespace-pre-wrap leading-relaxed">
                  {invoice.notes}
                </p>
              </div>
            )}

            {seller?.bank_account_number && (
              <div className="text-xs text-slate-600 bg-slate-50 p-3.5 rounded-xl border border-gray-200/80 space-y-1">
                <span className="font-semibold text-slate-800 block mb-1 uppercase tracking-wider">Bank Details for Payment:</span>
                <p>Bank Name: <span className="text-slate-900 font-semibold">{seller.bank_name}</span></p>
                <p>Account Number: <span className="text-slate-900 font-mono font-semibold">{seller.bank_account_number}</span></p>
                <p>IFSC Code: <span className="text-slate-900 font-mono font-semibold">{seller.bank_ifsc}</span></p>
              </div>
            )}
          </div>

          <div className="w-full sm:w-80 bg-slate-50 border border-gray-200/80 rounded-2xl p-5 space-y-2 text-sm font-mono">
            <div className="flex justify-between text-slate-700">
              <span>Subtotal (Taxable):</span>
              <span>₹{(invoice.subtotal_paise / 100).toFixed(2)}</span>
            </div>

            <div className="flex justify-between text-slate-500 text-xs">
              <span>Total Tax:</span>
              <span>+ ₹{(invoice.total_tax_paise / 100).toFixed(2)}</span>
            </div>

            <div className="flex justify-between pt-3 border-t border-gray-200 font-bold text-lg text-slate-900">
              <span>Grand Total:</span>
              <span>₹{(invoice.total_paise / 100).toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Modal: Finalize Confirmation */}
      {showFinalizeModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white border border-gray-200 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl text-center">
            <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-900 mx-auto flex items-center justify-center border border-slate-200">
              <Lock className="w-6 h-6" />
            </div>

            <h3 className="text-xl font-bold text-slate-900">Finalize Invoice {invoice.invoice_number}?</h3>

            <p className="text-xs text-slate-600 leading-relaxed">
              Finalizing will lock this invoice record against further edits. Once finalized, you can submit the invoice to the IRP portal to generate government IRN.
            </p>

            <div className="flex justify-center gap-3 pt-4 border-t border-gray-100">
              <button
                onClick={() => setShowFinalizeModal(false)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl"
              >
                Cancel
              </button>
              <button
                onClick={handleFinalize}
                disabled={finalizing}
                className="px-5 py-2 bg-slate-900 hover:bg-black text-white text-xs font-semibold rounded-xl shadow-sm"
              >
                {finalizing ? "Finalizing..." : "Confirm & Finalize"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Cancel IRN Confirmation */}
      {showCancelModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white border border-gray-200 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl text-left">
            <div className="w-12 h-12 rounded-2xl bg-red-50 text-red-600 mx-auto flex items-center justify-center border border-red-200">
              <ShieldAlert className="w-6 h-6" />
            </div>

            <div className="text-center">
              <h3 className="text-xl font-bold text-slate-900">Cancel IRN on IRP Portal?</h3>
              <p className="text-xs text-slate-600 mt-1">
                Invoice <span className="font-mono font-bold text-slate-900">{invoice.invoice_number}</span> (IRN: {invoice.irn?.substring(0, 12)}...)
              </p>
            </div>

            <div className="bg-red-50 p-3 rounded-xl border border-red-200 text-xs text-red-900 leading-relaxed space-y-1">
              <span className="font-bold flex items-center gap-1.5 text-red-800">
                <AlertTriangle className="w-4 h-4 text-red-600 flex-shrink-0" /> IRN Cancellation Warning:
              </span>
              <p>
                This action cancels the registered IRN directly on the Government IRP portal. IRP rules restrict cancellation to within 24 hours of generation. After 24 hours, you must issue a Credit Note instead.
              </p>
            </div>

            {error && (
              <div className="bg-amber-50 border border-amber-300 p-3 rounded-xl text-xs text-amber-900 space-y-2">
                <div className="font-bold flex items-center gap-1.5 text-amber-800">
                  <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" /> IRN Cancellation Notice
                </div>
                <p className="leading-normal">{error}</p>
                <div className="pt-1">
                  <Link
                    href={`/einvoicing/${invoice.id}/cdn/new?client_gstin_id=${clientGstinId}&note_type=credit`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white rounded-lg font-semibold text-xs shadow-sm transition-colors"
                  >
                    <FileText className="w-3.5 h-3.5" /> Issue Credit Note Instead →
                  </Link>
                </div>
              </div>
            )}

            <div className="space-y-3 pt-2">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Reason for Cancellation</label>
                <select
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  className="w-full text-xs p-2.5 rounded-xl border border-gray-300 bg-white font-medium text-slate-800 focus:ring-2 focus:ring-red-500"
                >
                  <option value="1">1 - Duplicate Invoice</option>
                  <option value="2">2 - Data Entry Error</option>
                  <option value="3">3 - Order Cancelled</option>
                  <option value="4">4 - Other Reason</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Cancellation Remarks</label>
                <textarea
                  value={cancelRemarks}
                  onChange={(e) => setCancelRemarks(e.target.value)}
                  rows={2}
                  placeholder="Provide detailed cancellation remark..."
                  className="w-full text-xs p-2.5 rounded-xl border border-gray-300 bg-white font-medium text-slate-800 focus:ring-2 focus:ring-red-500"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t border-gray-100">
              <button
                onClick={() => setShowCancelModal(false)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl"
              >
                Go Back
              </button>
              <button
                onClick={handleCancelIrn}
                disabled={cancellingIrn}
                className="px-5 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-xl shadow-sm disabled:opacity-50"
              >
                {cancellingIrn ? "Cancelling IRN..." : "Confirm & Cancel IRN"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function InvoiceDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center p-8 text-sm text-slate-500 font-medium">
          Loading invoice details...
        </div>
      }
    >
      <InvoiceDetailContent />
    </Suspense>
  );
}
