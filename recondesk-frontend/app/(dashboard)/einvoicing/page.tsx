"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  FileText,
  Plus,
  Settings,
  AlertTriangle,
  Search,
  Filter,
  CheckCircle,
  Clock,
  ArrowRight,
  Building2,
  Send,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  clientsApi,
  ClientGstin,
  billingModuleApi,
  BillingInvoice,
} from "@/lib/api";

function EInvoicingDashboardContent() {
  const router = useRouter();
  const token = useAccessToken();

  const [clients, setClients] = useState<ClientGstin[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [invoices, setInvoices] = useState<BillingInvoice[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState<string>("");

  // Load clients list
  useEffect(() => {
    if (!token) return;
    clientsApi
      .list(token)
      .then((data) => {
        setClients(data || []);
        if (data && data.length > 0) {
          setSelectedClientId((prev) => prev || data[0].id);
        }
      })
      .catch((err) => {
        console.error("Failed to load clients:", err);
      });
  }, [token]);

  // Load invoices for selected client
  useEffect(() => {
    if (!token || !selectedClientId) {
      setInvoices([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    billingModuleApi
      .listInvoices(token, selectedClientId, {
        status: statusFilter || undefined,
      })
      .then((data) => {
        setInvoices(data || []);
      })
      .catch((err) => {
        setError(err.detail || "Failed to load invoices");
      })
      .finally(() => setLoading(false));
  }, [token, selectedClientId, statusFilter]);

  const filteredInvoices = invoices.filter((inv) => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (
      inv.invoice_number.toLowerCase().includes(term) ||
      inv.customer?.name?.toLowerCase().includes(term) ||
      inv.customer?.gstin?.toLowerCase().includes(term)
    );
  });

  const draftCount = invoices.filter((i) => i.status === "draft").length;
  const finalizedCount = invoices.filter((i) => i.status === "finalized").length;
  const totalAmountPaise = invoices.reduce((sum, i) => sum + i.total_paise, 0);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* IRP Integration Verification Notice Banner */}
      <div className="bg-amber-50 border border-amber-200/80 rounded-2xl p-4 flex items-start gap-3.5 text-amber-900 shadow-sm">
        <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
        <div className="text-sm leading-relaxed">
          <span className="font-semibold text-amber-950">
            IRP Integration — Built, Pending Verification:
          </span>{" "}
          IRN generation is implemented against the Government Sandbox API but has not yet been verified end-to-end with a live GSTIN. Use with caution until verification is complete.
        </div>
      </div>

      {/* Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2.5 tracking-tight">
            <FileText className="w-7 h-7 text-slate-900" />
            E-Invoicing & Billing
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Generate client invoices, manage B2B/B2C buyers, and maintain HSN/SAC master catalogs.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Client Selector */}
          <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-xl px-3.5 py-2 shadow-sm">
            <Building2 className="w-4 h-4 text-slate-400" />
            <select
              value={selectedClientId}
              onChange={(e) => setSelectedClientId(e.target.value)}
              className="bg-transparent text-slate-900 font-semibold text-sm focus:outline-none cursor-pointer pr-1"
            >
              {clients.length === 0 && <option value="">No Clients Found</option>}
              {clients.map((c) => (
                <option key={c.id} value={c.id} className="text-slate-900">
                  {c.trade_name || c.legal_name || c.gstin} ({c.gstin})
                </option>
              ))}
            </select>
          </div>

          <Link
            href={`/einvoicing/settings?client_gstin_id=${selectedClientId}`}
            className="flex items-center gap-2 px-4 py-2 bg-white hover:bg-slate-50 text-slate-800 rounded-xl border border-gray-200 text-sm font-semibold shadow-sm transition-all"
          >
            <Settings className="w-4 h-4 text-slate-600" />
            Master Data
          </Link>

          <Link
            href={`/einvoicing/new?client_gstin_id=${selectedClientId}`}
            className="flex items-center justify-center px-4.5 py-2 bg-slate-900 hover:bg-black text-white rounded-xl text-sm font-semibold shadow-sm transition-all"
          >
            Create Invoice
          </Link>
        </div>
      </div>

      {/* Metric Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <div className="bg-white border border-gray-200/80 rounded-2xl p-5 flex items-center justify-between shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Total Invoices</p>
            <p className="text-2xl font-bold text-slate-900 mt-1">{invoices.length}</p>
          </div>
          <div className="w-11 h-11 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-900">
            <FileText className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-white border border-gray-200/80 rounded-2xl p-5 flex items-center justify-between shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Draft vs Finalized</p>
            <p className="text-xl font-bold text-slate-900 mt-1 flex items-center gap-2.5">
              <span className="text-amber-700 flex items-center gap-1.5 text-sm font-semibold">
                <Clock className="w-4 h-4 text-amber-500" /> {draftCount} Draft
              </span>
              <span className="text-slate-300">|</span>
              <span className="text-emerald-700 flex items-center gap-1.5 text-sm font-semibold">
                <CheckCircle className="w-4 h-4 text-emerald-500" /> {finalizedCount} Finalized
              </span>
            </p>
          </div>
        </div>

        <div className="bg-white border border-gray-200/80 rounded-2xl p-5 flex items-center justify-between shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Total Billing Value</p>
            <p className="text-2xl font-bold text-slate-900 mt-1">
              ₹{(totalAmountPaise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      </div>

      {/* Filter & Search Controls */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3.5 bg-white border border-gray-200/80 rounded-2xl p-3.5 shadow-sm">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search invoice # or customer..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-50/80 border border-gray-200 rounded-xl pl-10 pr-3.5 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-slate-900 focus:bg-white transition-all"
          />
        </div>

        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          <Filter className="w-4 h-4 text-slate-400" />
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Status:</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-50/80 border border-gray-200 text-slate-800 text-xs font-semibold rounded-xl px-3 py-2 focus:outline-none focus:border-slate-900 cursor-pointer"
          >
            <option value="">All Statuses</option>
            <option value="draft">Draft</option>
            <option value="finalized">Finalized</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      {/* Invoices Table Container */}
      <div className="bg-white border border-gray-200/80 rounded-2xl overflow-hidden shadow-sm">
        {loading ? (
          <div className="p-12 text-center text-slate-500 font-medium">Loading invoices...</div>
        ) : error ? (
          <div className="p-8 text-center text-red-600 font-medium">{error}</div>
        ) : filteredInvoices.length === 0 ? (
          <div className="p-14 text-center space-y-3.5">
            <div className="w-14 h-14 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto text-slate-400">
              <FileText className="w-7 h-7" />
            </div>
            <p className="text-base font-semibold text-slate-800">No invoices generated yet</p>
            <p className="text-xs text-slate-500 max-w-md mx-auto leading-relaxed">
              Configure your Company Seller Profile and Customer directory under Master Data, then generate internal invoices.
            </p>
            <Link
              href={`/einvoicing/new?client_gstin_id=${selectedClientId}`}
              className="inline-flex items-center justify-center px-4.5 py-2 bg-slate-900 text-white rounded-xl text-xs font-semibold hover:bg-black transition-colors shadow-sm"
            >
              Create First Invoice
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-800">
              <thead className="bg-slate-50/80 text-xs font-semibold text-slate-500 uppercase tracking-wider border-b border-gray-200/80">
                <tr>
                  <th className="px-4 py-3.5">Invoice #</th>
                  <th className="px-4 py-3.5">Date</th>
                  <th className="px-4 py-3.5">Customer</th>
                  <th className="px-4 py-3.5">Supply Type</th>
                  <th className="px-4 py-3.5 text-right">Taxable</th>
                  <th className="px-4 py-3.5 text-right">Tax Amount</th>
                  <th className="px-4 py-3.5 text-right">Total (₹)</th>
                  <th className="px-4 py-3.5 text-center">Status</th>
                  <th className="px-4 py-3.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredInvoices.map((inv) => {
                  const isDraft = inv.status === "draft";
                  return (
                    <tr key={inv.id} className="hover:bg-slate-50/50 transition-colors">
                      <td className="px-4 py-3.5 font-bold text-slate-900 font-mono">
                        {inv.invoice_number}
                      </td>
                      <td className="px-4 py-3.5 text-slate-600">{inv.invoice_date}</td>
                      <td className="px-4 py-3.5">
                        <div className="font-semibold text-slate-900">
                          {inv.customer?.name || "N/A"}
                        </div>
                        {inv.customer?.gstin && (
                          <div className="text-xs text-slate-500 font-mono">
                            {inv.customer.gstin}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-xs">
                        {inv.is_interstate ? (
                          <span className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-800 border border-slate-200 font-bold">
                            Interstate (IGST)
                          </span>
                        ) : (
                          <span className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-800 border border-slate-200 font-bold">
                            Intrastate (CGST+SGST)
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono font-medium text-slate-800">
                        ₹{(inv.subtotal_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono text-slate-500">
                        ₹{(inv.total_tax_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono font-bold text-slate-900">
                        ₹{(inv.total_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3.5 text-center">
                        {inv.irp_status === "irp_registered" || inv.irn ? (
                          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> IRN Registered
                          </span>
                        ) : inv.irp_status === "cancelled" ? (
                          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-red-50 text-red-700 border border-red-200">
                            IRN Cancelled
                          </span>
                        ) : isDraft ? (
                          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                            <Clock className="w-3.5 h-3.5 text-amber-500" /> Draft
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-300">
                            <CheckCircle className="w-3.5 h-3.5 text-slate-500" /> Finalized
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <Link
                          href={`/einvoicing/${inv.id}?client_gstin_id=${selectedClientId}`}
                          className={`inline-flex items-center gap-1 text-xs font-semibold transition-colors underline underline-offset-2 ${
                            inv.status === "finalized" && inv.irp_status !== "irp_registered"
                              ? "text-indigo-600 font-bold hover:text-indigo-800"
                              : "text-slate-900 hover:text-black"
                          }`}
                        >
                          {inv.status === "finalized" && inv.irp_status !== "irp_registered" ? (
                            <>Submit to IRP <Send className="w-3 h-3 ml-0.5" /></>
                          ) : (
                            <>View Details <ArrowRight className="w-3.5 h-3.5" /></>
                          )}
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function EInvoicingDashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center p-8 text-sm text-slate-500 font-medium">
          Loading E-Invoicing dashboard...
        </div>
      }
    >
      <EInvoicingDashboardContent />
    </Suspense>
  );
}
