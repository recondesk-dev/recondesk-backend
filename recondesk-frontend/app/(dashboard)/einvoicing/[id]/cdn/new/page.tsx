"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle,
  FileText,
  HelpCircle,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  BillingCustomer,
  BillingInvoice,
  BillingLineItemInput,
  CdnReasonCode,
  billingModuleApi,
} from "@/lib/api";
import { GST_UQC_CODES, getStateNameByCode } from "@/lib/constants";

function CdnFormContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const sessionToken = useAccessToken();

  const originalInvoiceId = params.id as string;
  const clientGstinId = searchParams.get("client_gstin_id") || "";
  const initialNoteType = (searchParams.get("note_type") as "credit" | "debit") || "credit";

  const [invoice, setInvoice] = useState<BillingInvoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [noteType, setNoteType] = useState<"credit" | "debit">(initialNoteType);
  const [reason, setReason] = useState<CdnReasonCode>("1-Sales Return");
  const [reasonDetail, setReasonDetail] = useState("");
  const [noteDate, setNoteDate] = useState(new Date().toISOString().split("T")[0]);
  const [notes, setNotes] = useState("");

  const [lineItems, setLineItems] = useState<BillingLineItemInput[]>([]);

  useEffect(() => {
    if (!sessionToken || !originalInvoiceId || !clientGstinId) return;

    setLoading(true);
    billingModuleApi
      .getInvoiceDetail(sessionToken, originalInvoiceId, clientGstinId)
      .then((inv) => {
        setInvoice(inv);
        if (inv.line_items && inv.line_items.length > 0) {
          setLineItems(
            inv.line_items.map((item) => ({
              item_id: item.item_id,
              description: item.description,
              hsn_or_sac_code: item.hsn_or_sac_code,
              quantity: item.quantity,
              unit: item.unit || "NOS",
              rate_paise: item.rate_paise,
              discount_percent: item.discount_percent || 0,
              tax_rate_percent: item.igst_rate_percent || (item.cgst_rate_percent + item.sgst_rate_percent) || 18,
              cess_paise: item.cess_paise || 0,
            }))
          );
        }
      })
      .catch((err) => setError(err.message || "Failed to load original invoice."))
      .finally(() => setLoading(false));
  }, [sessionToken, originalInvoiceId, clientGstinId]);

  const updateLineItem = (index: number, key: keyof BillingLineItemInput, value: any) => {
    setLineItems((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [key]: value };
      return next;
    });
  };

  const removeLineItem = (index: number) => {
    setLineItems((prev) => prev.filter((_, i) => i !== index));
  };

  const addLineItem = () => {
    setLineItems((prev) => [
      ...prev,
      {
        description: "",
        hsn_or_sac_code: "",
        quantity: 1,
        unit: "NOS",
        rate_paise: 0,
        discount_percent: 0,
        tax_rate_percent: 18,
      },
    ]);
  };

  // Tax breakdown calculation for display
  const isInterstate = invoice?.is_interstate ?? false;
  let subtotalPaise = 0;
  let totalTaxPaise = 0;

  lineItems.forEach((item) => {
    const gross = Math.round(item.quantity * item.rate_paise);
    const disc = Math.round(gross * ((item.discount_percent || 0) / 100));
    const taxable = Math.max(0, gross - disc);
    const tax = Math.round(taxable * ((item.tax_rate_percent || 0) / 100));

    subtotalPaise += taxable;
    totalTaxPaise += tax;
  });
  const grandTotalPaise = subtotalPaise + totalTaxPaise;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionToken || !clientGstinId || !originalInvoiceId) return;

    if (lineItems.length === 0) {
      setError("Please add at least one line item to the Credit/Debit note.");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const created = await billingModuleApi.createCdn(sessionToken, {
        client_gstin_id: clientGstinId,
        original_invoice_id: originalInvoiceId,
        note_type: noteType,
        reason,
        reason_detail: reasonDetail || undefined,
        note_date: noteDate,
        notes: notes || undefined,
        line_items: lineItems,
      });

      router.push(`/einvoicing/cdn/${created.id}?client_gstin_id=${clientGstinId}`);
    } catch (err: any) {
      setError(err.message || "Failed to create Credit/Debit Note.");
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="p-12 text-center text-slate-500 flex items-center justify-center gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" /> Loading invoice details...
      </div>
    );
  }

  if (!invoice) {
    return (
      <div className="p-8 text-center text-red-600 bg-red-50 rounded-2xl max-w-xl mx-auto border border-red-200 mt-10">
        <p className="font-bold text-sm">Invoice Not Found</p>
        <p className="text-xs mt-1">{error || "Could not retrieve original invoice record."}</p>
        <Link
          href={`/einvoicing?client_gstin_id=${clientGstinId}`}
          className="inline-block mt-4 text-xs font-bold text-indigo-600 underline"
        >
          Return to Invoices List
        </Link>
      </div>
    );
  }

  const seller = invoice.company_profile;
  const buyer = invoice.customer;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex items-center justify-between border-b border-gray-200 pb-4">
        <div>
          <Link
            href={`/einvoicing/${invoice.id}?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-slate-600 hover:text-black font-semibold mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Invoice {invoice.invoice_number}
          </Link>
          <h1 className="text-2xl font-bold text-slate-900 font-mono tracking-tight flex items-center gap-2">
            <FileText className="w-6 h-6 text-purple-600" />
            Issue {noteType === "credit" ? "Credit Note" : "Debit Note"}
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Linked to Original Invoice: <span className="font-bold text-slate-900">{invoice.invoice_number}</span> (IRN: {invoice.irn?.substring(0, 16)}...)
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-900 p-4 rounded-2xl text-xs font-semibold">
          ⚠️ {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Note Type & Reason Selection */}
        <div className="bg-white border border-gray-200 rounded-2xl p-5 space-y-4 shadow-sm">
          <h2 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">
            1. Document Classification & Reason
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Document Type *</label>
              <select
                value={noteType}
                onChange={(e) => setNoteType(e.target.value as "credit" | "debit")}
                className="w-full text-xs p-2.5 rounded-xl border border-gray-300 bg-white font-semibold text-slate-900 focus:ring-2 focus:ring-purple-500"
              >
                <option value="credit">Credit Note (CRN)</option>
                <option value="debit">Debit Note (DBN)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Reason Code (IRP Standard) *</label>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value as CdnReasonCode)}
                className="w-full text-xs p-2.5 rounded-xl border border-gray-300 bg-white font-semibold text-slate-900 focus:ring-2 focus:ring-purple-500"
              >
                <option value="1-Sales Return">1 - Sales Return</option>
                <option value="2-Post Sale Discount">2 - Post Sale Discount</option>
                <option value="3-Deficiency in Service">3 - Deficiency in Service</option>
                <option value="4-Correction in Invoice">4 - Correction in Invoice</option>
                <option value="5-Change in POS">5 - Change in POS</option>
                <option value="6-Finalization of Provisional Assessment">6 - Finalization of Provisional Assessment</option>
                <option value="7-Others">7 - Others</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Document Date *</label>
              <input
                type="date"
                value={noteDate}
                onChange={(e) => setNoteDate(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-gray-300 bg-white font-semibold text-slate-900 focus:ring-2 focus:ring-purple-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Reason Remarks / Explanation</label>
            <input
              type="text"
              value={reasonDetail}
              onChange={(e) => setReasonDetail(e.target.value)}
              placeholder="e.g. Returned 2 defective units from batch B-102"
              className="w-full text-xs p-2.5 rounded-xl border border-gray-300 bg-white text-slate-900 focus:ring-2 focus:ring-purple-500"
            />
          </div>
        </div>

        {/* Readonly Parties Information */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 space-y-1.5 text-xs text-slate-700">
            <h3 className="font-bold text-slate-900 text-xs uppercase tracking-wider mb-2">Seller / Supplier</h3>
            <p className="font-bold text-sm text-slate-900">{seller?.legal_name || "N/A"}</p>
            <p><b>GSTIN:</b> {seller?.gstin || "N/A"}</p>
            <p><b>Address:</b> {seller?.address_line1}, {seller?.city}, {seller?.state_code}</p>
          </div>

          <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 space-y-1.5 text-xs text-slate-700">
            <h3 className="font-bold text-slate-900 text-xs uppercase tracking-wider mb-2">Buyer / Recipient</h3>
            <p className="font-bold text-sm text-slate-900">{buyer?.name || "N/A"}</p>
            <p><b>GSTIN:</b> {buyer?.gstin || "URP"}</p>
            <p><b>Address:</b> {buyer?.address_line1}, {buyer?.city}, {buyer?.state_code}</p>
          </div>
        </div>

        {/* Line Items Table Adjustment */}
        <div className="bg-white border border-gray-200 rounded-2xl p-5 space-y-4 shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2">
            <h2 className="text-sm font-bold text-slate-900">
              2. Adjust Line Items & Quantities
            </h2>
            <button
              type="button"
              onClick={addLineItem}
              className="inline-flex items-center gap-1 text-xs font-semibold text-purple-700 hover:text-purple-900"
            >
              <Plus className="w-3.5 h-3.5" /> Add Extra Item
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-slate-50 text-slate-700 font-bold border-b border-slate-200">
                  <th className="p-2.5">Item Description</th>
                  <th className="p-2.5 w-24">HSN</th>
                  <th className="p-2.5 w-20 text-center">Qty</th>
                  <th className="p-2.5 w-24">UQC</th>
                  <th className="p-2.5 w-28 text-right">Rate (Rs.)</th>
                  <th className="p-2.5 w-20 text-center">GST %</th>
                  <th className="p-2.5 w-32 text-right">Taxable (Rs.)</th>
                  <th className="p-2.5 w-12 text-center"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {lineItems.map((item, idx) => {
                  const gross = Math.round(item.quantity * item.rate_paise);
                  const disc = Math.round(gross * ((item.discount_percent || 0) / 100));
                  const taxableRs = Math.max(0, gross - disc) / 100.0;

                  return (
                    <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                      <td className="p-2">
                        <input
                          type="text"
                          value={item.description}
                          onChange={(e) => updateLineItem(idx, "description", e.target.value)}
                          className="w-full text-xs p-2 rounded-lg border border-slate-200 bg-white font-medium"
                          required
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="text"
                          value={item.hsn_or_sac_code}
                          onChange={(e) => updateLineItem(idx, "hsn_or_sac_code", e.target.value)}
                          className="w-full text-xs p-2 rounded-lg border border-slate-200 bg-white font-mono text-center"
                          required
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          step="0.01"
                          min="0.01"
                          value={item.quantity}
                          onChange={(e) => updateLineItem(idx, "quantity", parseFloat(e.target.value) || 0)}
                          className="w-full text-xs p-2 rounded-lg border border-slate-200 bg-white text-center font-bold"
                          required
                        />
                      </td>
                      <td className="p-2">
                        <select
                          value={item.unit}
                          onChange={(e) => updateLineItem(idx, "unit", e.target.value)}
                          className="w-full text-xs p-2 rounded-lg border border-slate-200 bg-white font-mono"
                        >
                          {GST_UQC_CODES.map((u) => (
                            <option key={u.code} value={u.code}>
                              {u.code}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          step="0.01"
                          value={item.rate_paise / 100.0}
                          onChange={(e) => updateLineItem(idx, "rate_paise", Math.round((parseFloat(e.target.value) || 0) * 100))}
                          className="w-full text-xs p-2 rounded-lg border border-slate-200 bg-white text-right font-mono font-medium"
                          required
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          step="0.5"
                          value={item.tax_rate_percent}
                          onChange={(e) => updateLineItem(idx, "tax_rate_percent", parseFloat(e.target.value) || 0)}
                          className="w-full text-xs p-2 rounded-lg border border-slate-200 bg-white text-center font-mono"
                          required
                        />
                      </td>
                      <td className="p-2 text-right font-mono font-bold text-slate-900">
                        Rs. {taxableRs.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="p-2 text-center">
                        <button
                          type="button"
                          onClick={() => removeLineItem(idx)}
                          className="text-red-500 hover:text-red-700 p-1"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Totals Summary */}
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pt-4 border-t border-slate-100 bg-slate-50/50 p-4 rounded-xl">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Additional Notes</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                placeholder="Internal references or notes..."
                className="w-full md:w-96 text-xs p-2 rounded-xl border border-slate-200 bg-white"
              />
            </div>

            <div className="text-right space-y-1 text-xs">
              <p className="text-slate-600">Subtotal (Taxable): <span className="font-bold text-slate-900 font-mono">Rs. {(subtotalPaise / 100).toFixed(2)}</span></p>
              <p className="text-slate-600">Total Tax ({isInterstate ? "IGST" : "CGST + SGST"}): <span className="font-bold text-slate-900 font-mono">Rs. {(totalTaxPaise / 100).toFixed(2)}</span></p>
              <p className="text-sm font-bold text-purple-900 pt-1">
                Note Total: <span className="font-mono">Rs. {(grandTotalPaise / 100).toFixed(2)}</span>
              </p>
            </div>
          </div>
        </div>

        {/* Submit Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Link
            href={`/einvoicing/${invoice.id}?client_gstin_id=${clientGstinId}`}
            className="px-5 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2.5 bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold rounded-xl shadow-md transition-all disabled:opacity-50"
          >
            {submitting ? "Creating Draft Note..." : "Save Draft Credit/Debit Note"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function NewCdnPage() {
  return (
    <Suspense fallback={<div className="p-12 text-center text-slate-500">Loading form...</div>}>
      <CdnFormContent />
    </Suspense>
  );
}
