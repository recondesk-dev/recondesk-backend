"use client";

import { Suspense, useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  FileText,
  Plus,
  Trash2,
  ArrowLeft,
  Save,
  Building2,
  Calculator,
  AlertCircle,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  clientsApi,
  ClientGstin,
  billingModuleApi,
  BillingCompanyProfile,
  BillingCustomer,
  BillingItem,
  BillingLineItemInput,
} from "@/lib/api";

import { INDIAN_STATES, getStateNameByCode, GST_UQC_CODES } from "@/lib/constants";

function CreateInvoiceContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = useAccessToken();

  const [clients, setClients] = useState<ClientGstin[]>([]);
  const [clientGstinId, setClientGstinId] = useState<string>(
    searchParams.get("client_gstin_id") || ""
  );

  const [companyProfile, setCompanyProfile] = useState<BillingCompanyProfile | null>(null);
  const [customers, setCustomers] = useState<BillingCustomer[]>([]);
  const [itemCatalog, setItemCatalog] = useState<BillingItem[]>([]);

  const [selectedCustomerId, setSelectedCustomerId] = useState<string>("");
  const [invoiceDate, setInvoiceDate] = useState<string>(
    new Date().toISOString().substring(0, 10)
  );
  const [dueDate, setDueDate] = useState<string>("");
  const [placeOfSupply, setPlaceOfSupply] = useState<string>("27");
  const [notes, setNotes] = useState<string>("");

  const [lineItems, setLineItems] = useState<BillingLineItemInput[]>([
    {
      item_id: undefined,
      description: "Consulting Services",
      hsn_or_sac_code: "9983",
      quantity: 1,
      unit: "NOS",
      rate_paise: 100000,
      discount_percent: 0,
      tax_rate_percent: 18.0,
      cess_paise: 0,
    },
  ]);

  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Load client list
  useEffect(() => {
    if (!token) return;
    clientsApi.list(token).then((data) => {
      setClients(data || []);
      if (!clientGstinId && data && data.length > 0) {
        setClientGstinId(data[0].id);
      }
    });
  }, [token]);

  // Load masters for active client
  useEffect(() => {
    if (!token || !clientGstinId) return;
    Promise.all([
      billingModuleApi.listCompanyProfiles(token, clientGstinId),
      billingModuleApi.listCustomers(token, clientGstinId),
      billingModuleApi.listItems(token, clientGstinId),
    ]).then(([profiles, custs, items]) => {
      if (profiles && profiles.length > 0) {
        setCompanyProfile(profiles[0]);
      }
      setCustomers(custs || []);
      if (custs && custs.length > 0) {
        setSelectedCustomerId(custs[0].id);
        setPlaceOfSupply(custs[0].state_code);
      }
      setItemCatalog(items || []);
    });
  }, [token, clientGstinId]);

  const handleCustomerChange = (custId: string) => {
    setSelectedCustomerId(custId);
    const c = customers.find((cust) => cust.id === custId);
    if (c) {
      setPlaceOfSupply(c.state_code);
    }
  };

  const isInterstate = useMemo(() => {
    const sellerStateCode = companyProfile?.state_code || "27";
    return sellerStateCode.trim() !== placeOfSupply.trim();
  }, [companyProfile, placeOfSupply]);

  const computedLines = useMemo(() => {
    return lineItems.map((line) => {
      const gross = line.rate_paise * line.quantity;
      const discount = Math.round(gross * (line.discount_percent / 100.0));
      const taxable = Math.max(0, gross - discount);

      let cgstRate = 0,
        cgstPaise = 0,
        sgstRate = 0,
        sgstPaise = 0,
        igstRate = 0,
        igstPaise = 0;

      if (isInterstate) {
        igstRate = line.tax_rate_percent;
        igstPaise = Math.round(taxable * (igstRate / 100.0));
      } else {
        cgstRate = Number((line.tax_rate_percent / 2.0).toFixed(2));
        sgstRate = Number((line.tax_rate_percent / 2.0).toFixed(2));
        cgstPaise = Math.round(taxable * (cgstRate / 100.0));
        sgstPaise = Math.round(taxable * (sgstRate / 100.0));
      }

      const cess = line.cess_paise || 0;
      const lineTotal = taxable + cgstPaise + sgstPaise + igstPaise + cess;

      return {
        ...line,
        taxable_value_paise: taxable,
        cgst_rate_percent: cgstRate,
        cgst_paise: cgstPaise,
        sgst_rate_percent: sgstRate,
        sgst_paise: sgstPaise,
        igst_rate_percent: igstRate,
        igst_paise: igstPaise,
        line_total_paise: lineTotal,
      };
    });
  }, [lineItems, isInterstate]);

  const totals = useMemo(() => {
    const subtotal = computedLines.reduce((sum, l) => sum + l.taxable_value_paise, 0);
    const cgst = computedLines.reduce((sum, l) => sum + l.cgst_paise, 0);
    const sgst = computedLines.reduce((sum, l) => sum + l.sgst_paise, 0);
    const igst = computedLines.reduce((sum, l) => sum + l.igst_paise, 0);
    const totalTax = cgst + sgst + igst;
    const grandTotal = computedLines.reduce((sum, l) => sum + l.line_total_paise, 0);

    return { subtotal, cgst, sgst, igst, totalTax, grandTotal };
  }, [computedLines]);

  const addLineItem = () => {
    setLineItems((prev) => [
      ...prev,
      {
        item_id: undefined,
        description: "",
        hsn_or_sac_code: "9983",
        quantity: 1,
        unit: "NOS",
        rate_paise: 0,
        discount_percent: 0,
        tax_rate_percent: 18.0,
        cess_paise: 0,
      },
    ]);
  };

  const removeLineItem = (index: number) => {
    if (lineItems.length <= 1) return;
    setLineItems((prev) => prev.filter((_, i) => i !== index));
  };

  const updateLineItem = (index: number, fields: Partial<BillingLineItemInput>) => {
    setLineItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, ...fields } : item))
    );
  };

  const handleSelectCatalogItem = (index: number, itemId: string) => {
    const catItem = itemCatalog.find((i) => i.id === itemId);
    if (!catItem) return;
    updateLineItem(index, {
      item_id: catItem.id,
      description: catItem.name,
      hsn_or_sac_code: catItem.hsn_or_sac_code,
      unit: catItem.unit,
      rate_paise: catItem.default_rate,
      tax_rate_percent: catItem.default_tax_rate_percent,
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !clientGstinId) return;
    if (!companyProfile) {
      setError("Please configure Company Profile under Master Data before creating invoices.");
      return;
    }
    if (!selectedCustomerId) {
      setError("Please select or add a customer.");
      return;
    }

    setSubmitting(true);
    setError(null);

    const payload = {
      client_gstin_id: clientGstinId,
      company_profile_id: companyProfile.id,
      customer_id: selectedCustomerId,
      invoice_date: invoiceDate,
      due_date: dueDate || undefined,
      place_of_supply: placeOfSupply,
      notes: notes || undefined,
      line_items: lineItems,
    };

    try {
      const created = await billingModuleApi.createInvoice(token, payload);
      router.push(`/einvoicing/${created.id}?client_gstin_id=${clientGstinId}`);
    } catch (err: any) {
      setError(err.detail || "Failed to create invoice");
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <Link
            href={`/einvoicing?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-slate-800 hover:text-black font-semibold mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Invoices
          </Link>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <FileText className="w-6 h-6 text-slate-900" /> Create Draft Invoice
          </h1>
        </div>

        <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-xl px-3.5 py-2 shadow-sm">
          <Building2 className="w-4 h-4 text-slate-400" />
          <span className="text-xs text-slate-500 font-medium">Client:</span>
          <select
            value={clientGstinId}
            onChange={(e) => setClientGstinId(e.target.value)}
            className="bg-transparent text-slate-900 text-sm font-semibold focus:outline-none cursor-pointer"
          >
            {clients.map((c) => (
              <option key={c.id} value={c.id} className="text-slate-900">
                {c.trade_name || c.legal_name || c.gstin} ({c.gstin})
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm flex items-center gap-2 font-medium">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
          {error}
        </div>
      )}

      {!companyProfile && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-amber-900 text-sm flex items-center justify-between font-medium">
          <span>Company Profile not configured for this client yet.</span>
          <Link
            href={`/einvoicing/settings?client_gstin_id=${clientGstinId}`}
            className="px-3.5 py-1.5 bg-amber-600 text-white rounded-lg text-xs font-semibold hover:bg-amber-700 shadow-sm"
          >
            Configure Profile
          </Link>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Invoice Header Details */}
        <div className="bg-white border border-gray-200/80 rounded-2xl p-6 space-y-6 shadow-sm">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Customer / Buyer *</label>
              <div className="flex gap-2">
                <select
                  value={selectedCustomerId}
                  onChange={(e) => handleCustomerChange(e.target.value)}
                  className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 cursor-pointer font-medium"
                  required
                >
                  <option value="">Select Customer</option>
                  {customers.map((cust) => (
                    <option key={cust.id} value={cust.id}>
                      {cust.name} {cust.gstin ? `(${cust.gstin})` : "(B2C)"}
                    </option>
                  ))}
                </select>
                <Link
                  href={`/einvoicing/settings?client_gstin_id=${clientGstinId}`}
                  className="p-2 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-xl border border-gray-200"
                  title="Add Customer in Masters"
                >
                  <Plus className="w-4 h-4" />
                </Link>
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Invoice Date *</label>
              <input
                type="date"
                required
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Due Date (Optional)</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900"
              />
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-slate-50 rounded-xl border border-gray-200/80">
            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Place of Supply (State) *</label>
              <select
                value={placeOfSupply}
                onChange={(e) => setPlaceOfSupply(e.target.value)}
                className="bg-white border border-gray-200 rounded-xl px-3 py-1.5 text-sm text-slate-900 focus:outline-none focus:border-slate-900 cursor-pointer font-medium"
              >
                {INDIAN_STATES.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.name} ({s.code})
                  </option>
                ))}
              </select>
            </div>

            <div className="text-right">
              <span className="text-xs text-slate-500 font-semibold block">Calculated GST Tax Split:</span>
              {isInterstate ? (
                <span className="inline-block mt-1 px-3 py-1 rounded-lg bg-slate-200 text-slate-900 border border-slate-300 text-xs font-bold">
                  INTERSTATE SUPPLY → 100% IGST APPLIED
                </span>
              ) : (
                <span className="inline-block mt-1 px-3 py-1 rounded-lg bg-slate-200 text-slate-900 border border-slate-300 text-xs font-bold">
                  INTRASTATE SUPPLY → 50% CGST + 50% SGST SPLIT APPLIED
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Line Items Table */}
        <div className="bg-white border border-gray-200/80 rounded-2xl p-6 space-y-4 shadow-sm">
          <div className="flex items-center justify-between border-b border-gray-100 pb-3">
            <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Calculator className="w-5 h-5 text-slate-900" /> Line Items Builder
            </h2>
            <button
              type="button"
              onClick={addLineItem}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-900 rounded-xl border border-slate-300 text-xs font-bold transition-colors"
            >
              <Plus className="w-4 h-4" /> Add Row
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-800">
              <thead className="bg-slate-50/80 text-xs font-semibold text-slate-500 uppercase tracking-wider border-b border-gray-200/80">
                <tr>
                  <th className="px-3 py-2 w-1/4">Catalog / Description</th>
                  <th className="px-3 py-2 w-28">HSN/SAC</th>
                  <th className="px-3 py-2 w-20">Qty</th>
                  <th className="px-3 py-2 w-20">Unit</th>
                  <th className="px-3 py-2 w-28">Rate (₹)</th>
                  <th className="px-3 py-2 w-20">Disc %</th>
                  <th className="px-3 py-2 w-24">GST %</th>
                  <th className="px-3 py-2 text-right">Taxable (₹)</th>
                  <th className="px-3 py-2 text-right">Total (₹)</th>
                  <th className="px-2 py-2 w-10"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {lineItems.map((line, idx) => {
                  const comp = computedLines[idx];
                  return (
                    <tr key={idx} className="hover:bg-slate-50/50">
                      <td className="px-3 py-2 space-y-1">
                        {itemCatalog.length > 0 && (
                          <select
                            value={line.item_id || ""}
                            onChange={(e) => handleSelectCatalogItem(idx, e.target.value)}
                            className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2 py-1 text-xs text-slate-700 focus:outline-none mb-1"
                          >
                            <option value="">-- Autocomplete from Catalog --</option>
                            {itemCatalog.map((cat) => (
                              <option key={cat.id} value={cat.id}>
                                {cat.name} ({cat.hsn_or_sac_code}) - ₹{(cat.default_rate / 100).toFixed(2)}
                              </option>
                            ))}
                          </select>
                        )}
                        <input
                          type="text"
                          required
                          placeholder="Description"
                          value={line.description}
                          onChange={(e) => updateLineItem(idx, { description: e.target.value })}
                          className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                        />
                      </td>

                      <td className="px-3 py-2">
                        <input
                          type="text"
                          required
                          placeholder="9983"
                          value={line.hsn_or_sac_code}
                          onChange={(e) => updateLineItem(idx, { hsn_or_sac_code: e.target.value })}
                          className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-slate-900 font-mono focus:outline-none focus:border-slate-900"
                        />
                      </td>

                      <td className="px-3 py-2">
                        <input
                          type="number"
                          step="0.01"
                          min="0.01"
                          required
                          value={line.quantity}
                          onChange={(e) => updateLineItem(idx, { quantity: parseFloat(e.target.value) || 1 })}
                          className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-slate-900 font-mono focus:outline-none focus:border-slate-900"
                        />
                      </td>

                      <td className="px-3 py-2">
                        <select
                          value={line.unit || "NOS"}
                          onChange={(e) => updateLineItem(idx, { unit: e.target.value })}
                          className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-slate-900 font-semibold focus:outline-none cursor-pointer"
                        >
                          {GST_UQC_CODES.map((uqc) => (
                            <option key={uqc.code} value={uqc.code}>
                              {uqc.code} - {uqc.description}
                            </option>
                          ))}
                        </select>
                      </td>

                      <td className="px-3 py-2">
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          required
                          value={line.rate_paise / 100}
                          onChange={(e) =>
                            updateLineItem(idx, { rate_paise: Math.round((parseFloat(e.target.value) || 0) * 100) })
                          }
                          className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-slate-900 font-mono focus:outline-none focus:border-slate-900"
                        />
                      </td>

                      <td className="px-3 py-2">
                        <input
                          type="number"
                          step="0.1"
                          min="0"
                          max="100"
                          value={line.discount_percent}
                          onChange={(e) =>
                            updateLineItem(idx, { discount_percent: parseFloat(e.target.value) || 0 })
                          }
                          className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-slate-900 font-mono focus:outline-none focus:border-slate-900"
                        />
                      </td>

                      <td className="px-3 py-2">
                        <select
                          value={line.tax_rate_percent}
                          onChange={(e) =>
                            updateLineItem(idx, { tax_rate_percent: parseFloat(e.target.value) })
                          }
                          className="w-full bg-slate-50 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-slate-900 font-semibold focus:outline-none cursor-pointer"
                        >
                          <option value={0}>0%</option>
                          <option value={5}>5%</option>
                          <option value={12}>12%</option>
                          <option value={18}>18%</option>
                          <option value={28}>28%</option>
                        </select>
                      </td>

                      <td className="px-3 py-2 text-right font-mono text-xs font-semibold text-slate-800">
                        ₹{(comp.taxable_value_paise / 100).toFixed(2)}
                      </td>

                      <td className="px-3 py-2 text-right font-mono text-xs font-bold text-slate-900">
                        ₹{(comp.line_total_paise / 100).toFixed(2)}
                      </td>

                      <td className="px-2 py-2 text-center">
                        <button
                          type="button"
                          disabled={lineItems.length <= 1}
                          onClick={() => removeLineItem(idx)}
                          className="text-slate-400 hover:text-red-600 disabled:opacity-30"
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

          <div className="flex flex-col sm:flex-row justify-between items-start pt-4 border-t border-gray-100 gap-4">
            <div className="w-full sm:w-1/2">
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Invoice Notes / Terms</label>
              <textarea
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Payment terms, bank transfer details, or note..."
                className="w-full bg-slate-50 border border-gray-200 rounded-xl p-3 text-xs text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
              />
            </div>

            <div className="w-full sm:w-80 bg-slate-50 border border-gray-200/80 rounded-2xl p-4.5 space-y-2 text-sm font-mono">
              <div className="flex justify-between text-slate-700">
                <span>Subtotal (Taxable):</span>
                <span>₹{(totals.subtotal / 100).toFixed(2)}</span>
              </div>

              {!isInterstate ? (
                <>
                  <div className="flex justify-between text-slate-500 text-xs">
                    <span>CGST Total:</span>
                    <span>+ ₹{(totals.cgst / 100).toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between text-slate-500 text-xs">
                    <span>SGST Total:</span>
                    <span>+ ₹{(totals.sgst / 100).toFixed(2)}</span>
                  </div>
                </>
              ) : (
                <div className="flex justify-between text-slate-700 text-xs">
                  <span>IGST Total:</span>
                  <span>+ ₹{(totals.igst / 100).toFixed(2)}</span>
                </div>
              )}

              <div className="flex justify-between pt-2 border-t border-gray-200 font-bold text-base text-slate-900">
                <span>Grand Total:</span>
                <span>₹{(totals.grandTotal / 100).toFixed(2)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Submit Actions */}
        <div className="flex justify-end gap-3.5">
          <Link
            href={`/einvoicing?client_gstin_id=${clientGstinId}`}
            className="px-5 py-2.5 bg-white hover:bg-slate-50 text-slate-700 text-sm font-semibold rounded-xl border border-gray-200 shadow-sm"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={submitting}
            className="flex items-center gap-2 px-6 py-2.5 bg-slate-900 hover:bg-black text-white text-sm font-semibold rounded-xl shadow-sm transition-all"
          >
            <Save className="w-4 h-4" /> {submitting ? "Saving Draft..." : "Save Draft Invoice"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function CreateInvoicePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center p-8 text-sm text-slate-500 font-medium">
          Loading invoice form...
        </div>
      }
    >
      <CreateInvoiceContent />
    </Suspense>
  );
}
