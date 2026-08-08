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
    } finally {
      setFinalizing(false);
    }
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
  const seller = invoice.company_profile;
  const buyer = invoice.customer;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Top Bar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-gray-200 pb-4">
        <div>
          <Link
            href={`/einvoicing?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 font-semibold mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Invoices List
          </Link>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-900 font-mono tracking-tight">{invoice.invoice_number}</h1>
            {isDraft ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                <Clock className="w-3.5 h-3.5 text-amber-500" /> DRAFT
              </span>
            ) : isFinalized ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> FINALIZED (LOCKED)
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
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 px-4 py-2 bg-white hover:bg-slate-50 text-slate-700 rounded-xl border border-gray-200 text-xs font-semibold shadow-sm"
          >
            <Printer className="w-4 h-4 text-slate-500" /> Print / PDF
          </button>

          {isDraft && (
            <button
              onClick={() => setShowFinalizeModal(true)}
              className="flex items-center gap-1.5 px-4.5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-xl shadow-md shadow-emerald-600/20 transition-all"
            >
              <Lock className="w-4 h-4" /> Finalize Invoice
            </button>
          )}
        </div>
      </div>

      {/* Lock Notice */}
      {isFinalized && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-4 flex items-start gap-3 text-emerald-900 text-xs shadow-sm">
          <Lock className="w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5" />
          <div className="leading-relaxed">
            <span className="font-bold text-emerald-950">Invoice Record Finalized & Locked:</span> This invoice has been finalized. Line items, rates, and tax calculations are locked against modifications.
          </div>
        </div>
      )}

      {/* Invoice Document Card */}
      <div className="bg-white border border-gray-200/80 rounded-2xl p-8 space-y-8 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-b border-gray-100 pb-6">
          {/* Seller Details */}
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-indigo-600 block mb-2">
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
            <span className="text-xs font-semibold uppercase tracking-wider text-indigo-600 block mb-2">
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
            <span className="font-semibold text-indigo-700 mt-0.5 block">
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
                      <span className="text-purple-700 font-semibold">IGST {line.igst_rate_percent}%: ₹{(line.igst_paise / 100).toFixed(2)}</span>
                    ) : (
                      <span className="text-blue-700 font-semibold">
                        C: {line.cgst_rate_percent}% (₹{(line.cgst_paise / 100).toFixed(2)}) + S: {line.sgst_rate_percent}% (₹{(line.sgst_paise / 100).toFixed(2)})
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-bold text-emerald-600">
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

            <div className="flex justify-between pt-3 border-t border-gray-200 font-bold text-lg text-emerald-600">
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
            <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 mx-auto flex items-center justify-center border border-emerald-100">
              <Lock className="w-6 h-6" />
            </div>

            <h3 className="text-xl font-bold text-slate-900">Finalize Invoice {invoice.invoice_number}?</h3>

            <p className="text-xs text-slate-600 leading-relaxed">
              Finalizing will lock this invoice record against further edits. In Phase 2, this action will submit the invoice to IRP for e-Invoice IRN generation.
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
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-xl shadow-md shadow-emerald-600/20"
              >
                {finalizing ? "Finalizing..." : "Confirm & Finalize"}
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
