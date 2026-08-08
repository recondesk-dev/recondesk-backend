"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  FileText,
  Lock,
  CheckCircle,
  Clock,
  ArrowLeft,
  Edit2,
  Building,
  User,
  Printer,
  AlertTriangle,
  Check,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { billingModuleApi, BillingInvoice } from "@/lib/api";

export default function InvoiceDetailPage() {
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
    return <div className="p-12 text-center text-gray-400">Loading invoice details...</div>;
  }

  if (error || !invoice) {
    return (
      <div className="p-12 text-center text-red-400 space-y-4">
        <p>{error || "Invoice not found"}</p>
        <Link
          href={`/einvoicing?client_gstin_id=${clientGstinId}`}
          className="inline-flex items-center gap-2 px-4 py-2 bg-white/10 text-white rounded-lg text-sm"
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
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-white/10 pb-4">
        <div>
          <Link
            href={`/einvoicing?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 font-medium mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Invoices List
          </Link>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white font-mono">{invoice.invoice_number}</h1>
            {isDraft ? (
              <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                <Clock className="w-3.5 h-3.5" /> DRAFT
              </span>
            ) : isFinalized ? (
              <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <CheckCircle className="w-3.5 h-3.5" /> FINALIZED (LOCKED)
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20">
                CANCELLED
              </span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-white/5 hover:bg-white/10 text-gray-300 rounded-lg border border-white/10 text-xs font-medium"
          >
            <Printer className="w-4 h-4" /> Print / PDF
          </button>

          {isDraft && (
            <button
              onClick={() => setShowFinalizeModal(true)}
              className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-lg shadow-lg shadow-emerald-600/30 transition-all"
            >
              <Lock className="w-4 h-4" /> Finalize Invoice
            </button>
          )}
        </div>
      </div>

      {/* Lock Notice for Finalized Invoices */}
      {isFinalized && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 flex items-start gap-3 text-emerald-200 text-xs">
          <Lock className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-bold text-emerald-300">Invoice Record Finalized & Locked:</span> This invoice has been finalized. Line items, quantities, rates, and tax calculations are locked against further edits.
          </div>
        </div>
      )}

      {/* Main Invoice Card Container */}
      <div className="bg-[#161B26] border border-white/10 rounded-2xl p-8 space-y-8 shadow-2xl">
        {/* Invoice Header Details */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-b border-white/10 pb-6">
          {/* Seller / Supplier Details */}
          <div>
            <span className="text-xs uppercase tracking-wider font-semibold text-indigo-400 block mb-2">
              Seller (Billed From)
            </span>
            <h2 className="text-base font-bold text-white">{seller?.legal_name || "N/A"}</h2>
            {seller?.trade_name && <p className="text-xs text-gray-400">{seller.trade_name}</p>}
            <p className="text-xs font-mono text-gray-300 mt-1">GSTIN: {seller?.gstin || "N/A"}</p>
            <p className="text-xs text-gray-400 mt-2 leading-relaxed">
              {seller?.address_line1} {seller?.address_line2}
              <br />
              {seller?.city}, {seller?.state} - {seller?.pincode}
            </p>
          </div>

          {/* Customer / Buyer Details */}
          <div>
            <span className="text-xs uppercase tracking-wider font-semibold text-indigo-400 block mb-2">
              Buyer (Billed To)
            </span>
            <h2 className="text-base font-bold text-white">{buyer?.name || "N/A"}</h2>
            {buyer?.gstin ? (
              <p className="text-xs font-mono text-gray-300 mt-1">GSTIN: {buyer.gstin}</p>
            ) : (
              <p className="text-xs text-gray-400 mt-1">B2C Consumer</p>
            )}
            <p className="text-xs text-gray-400 mt-2 leading-relaxed">
              {buyer?.address_line1} {buyer?.address_line2}
              <br />
              {buyer?.city}, {buyer?.state} - {buyer?.pincode}
            </p>
          </div>
        </div>

        {/* Invoice Metadata Pills */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 bg-white/5 rounded-xl border border-white/10 text-xs">
          <div>
            <span className="text-gray-400 block">Invoice Date</span>
            <span className="font-semibold text-white mt-0.5 block">{invoice.invoice_date}</span>
          </div>
          <div>
            <span className="text-gray-400 block">Due Date</span>
            <span className="font-semibold text-white mt-0.5 block">{invoice.due_date || "N/A"}</span>
          </div>
          <div>
            <span className="text-gray-400 block">Place of Supply</span>
            <span className="font-semibold text-white mt-0.5 block">{invoice.place_of_supply}</span>
          </div>
          <div>
            <span className="text-gray-400 block">Tax Regime</span>
            <span className="font-semibold text-indigo-300 mt-0.5 block">
              {invoice.is_interstate ? "Interstate (IGST)" : "Intrastate (CGST + SGST)"}
            </span>
          </div>
        </div>

        {/* Line Items Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-gray-300">
            <thead className="bg-white/5 text-xs text-gray-400 uppercase tracking-wider border-b border-white/10">
              <tr>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">HSN/SAC</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Rate (₹)</th>
                <th className="px-4 py-3 text-right">Disc %</th>
                <th className="px-4 py-3 text-right">Taxable (₹)</th>
                <th className="px-4 py-3 text-right">Tax Details</th>
                <th className="px-4 py-3 text-right">Total (₹)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {(invoice.line_items || []).map((line) => (
                <tr key={line.id} className="hover:bg-white/[0.01]">
                  <td className="px-4 py-3 font-medium text-white">{line.description}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-400">{line.hsn_or_sac_code}</td>
                  <td className="px-4 py-3 text-right font-mono">{line.quantity} {line.unit}</td>
                  <td className="px-4 py-3 text-right font-mono">₹{(line.rate_paise / 100).toFixed(2)}</td>
                  <td className="px-4 py-3 text-right font-mono text-xs">{line.discount_percent}%</td>
                  <td className="px-4 py-3 text-right font-mono">
                    ₹{(line.taxable_value_paise / 100).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-xs">
                    {invoice.is_interstate ? (
                      <span className="text-purple-300">IGST {line.igst_rate_percent}%: ₹{(line.igst_paise / 100).toFixed(2)}</span>
                    ) : (
                      <span className="text-blue-300">
                        C: {line.cgst_rate_percent}% (₹{(line.cgst_paise / 100).toFixed(2)}) + S: {line.sgst_rate_percent}% (₹{(line.sgst_paise / 100).toFixed(2)})
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-semibold text-emerald-400">
                    ₹{(line.line_total_paise / 100).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Notes & Summary Footer */}
        <div className="flex flex-col sm:flex-row justify-between items-start pt-6 border-t border-white/10 gap-6">
          <div className="w-full sm:w-1/2 space-y-3">
            {invoice.notes && (
              <div>
                <span className="text-xs font-semibold text-gray-400 block mb-1">Notes / Terms:</span>
                <p className="text-xs text-gray-300 bg-white/5 p-3 rounded-lg border border-white/10 whitespace-pre-wrap">
                  {invoice.notes}
                </p>
              </div>
            )}

            {seller?.bank_account_number && (
              <div className="text-xs text-gray-400 bg-white/5 p-3 rounded-lg border border-white/10 space-y-1">
                <span className="font-semibold text-gray-300 block mb-1">Bank Payment Details:</span>
                <p>Bank Name: <span className="text-white">{seller.bank_name}</span></p>
                <p>Account Number: <span className="text-white font-mono">{seller.bank_account_number}</span></p>
                <p>IFSC Code: <span className="text-white font-mono">{seller.bank_ifsc}</span></p>
              </div>
            )}
          </div>

          <div className="w-full sm:w-80 bg-white/5 border border-white/10 rounded-xl p-5 space-y-2 text-sm font-mono">
            <div className="flex justify-between text-gray-300">
              <span>Subtotal (Taxable):</span>
              <span>₹{(invoice.subtotal_paise / 100).toFixed(2)}</span>
            </div>

            <div className="flex justify-between text-gray-400 text-xs">
              <span>Total Tax:</span>
              <span>+ ₹{(invoice.total_tax_paise / 100).toFixed(2)}</span>
            </div>

            <div className="flex justify-between pt-3 border-t border-white/10 font-bold text-lg text-emerald-400">
              <span>Grand Total:</span>
              <span>₹{(invoice.total_paise / 100).toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Modal: Finalize Confirmation */}
      {showFinalizeModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#161B26] border border-white/10 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl text-center">
            <div className="w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 mx-auto flex items-center justify-center">
              <Lock className="w-6 h-6" />
            </div>

            <h3 className="text-xl font-bold text-white">Finalize Invoice {invoice.invoice_number}?</h3>

            <p className="text-xs text-gray-300 leading-relaxed">
              Finalizing will lock this invoice record against any further editing. In Phase 2, this action will submit the invoice to IRP for e-Invoice IRN generation.
            </p>

            <div className="flex justify-center gap-3 pt-4 border-t border-white/10">
              <button
                onClick={() => setShowFinalizeModal(false)}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-semibold rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleFinalize}
                disabled={finalizing}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-lg shadow-lg shadow-emerald-600/30"
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
