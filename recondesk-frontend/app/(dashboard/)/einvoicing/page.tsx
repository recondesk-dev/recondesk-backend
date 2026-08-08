"use client";

import { useEffect, useState } from "react";
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
  Building,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  clientsApi,
  ClientGstin,
  billingModuleApi,
  BillingInvoice,
} from "@/lib/api";

export default function EInvoicingDashboardPage() {
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
      .listInvoices(token, {
        client_gstin_id: selectedClientId,
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
      {/* Beta / Internal Testing Warning Banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 flex items-start gap-3 text-amber-200">
        <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="text-sm">
          <span className="font-semibold text-amber-300">
            Beta / Internal Testing Mode:
          </span>{" "}
          Invoices created and finalized in this module are internal records for management and testing.
          Direct submission to IRP for legal e-Invoice IRN generation will be activated in Phase 2.
        </div>
      </div>

      {/* Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <FileText className="w-7 h-7 text-indigo-400" />
            E-Invoicing & Billing
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Create internal invoices, manage client company profiles, customers, and item master catalogs.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Client Selector */}
          <div className="flex items-center gap-2 bg-[#161B26] border border-white/10 rounded-lg px-3 py-1.5">
            <Building className="w-4 h-4 text-gray-400" />
            <select
              value={selectedClientId}
              onChange={(e) => setSelectedClientId(e.target.value)}
              className="bg-transparent text-white text-sm focus:outline-none cursor-pointer"
            >
              {clients.length === 0 && <option value="">No Clients Found</option>}
              {clients.map((c) => (
                <option key={c.id} value={c.id} className="bg-[#161B26] text-white">
                  {c.trade_name || c.legal_name || c.gstin} ({c.gstin})
                </option>
              ))}
            </select>
          </div>

          <Link
            href={`/einvoicing/settings?client_gstin_id=${selectedClientId}`}
            className="flex items-center gap-1.5 px-3 py-2 bg-white/5 hover:bg-white/10 text-gray-300 rounded-lg border border-white/10 text-sm font-medium transition-colors"
          >
            <Settings className="w-4 h-4" />
            Master Data
          </Link>

          <Link
            href={`/einvoicing/new?client_gstin_id=${selectedClientId}`}
            className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium shadow-lg shadow-indigo-600/30 transition-all"
          >
            <Plus className="w-4 h-4" />
            Create Invoice
          </Link>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-[#161B26] border border-white/10 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-400 font-medium">Total Invoices</p>
            <p className="text-2xl font-bold text-white mt-1">{invoices.length}</p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
            <FileText className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-[#161B26] border border-white/10 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-400 font-medium">Draft vs Finalized</p>
            <p className="text-xl font-bold text-white mt-1 flex items-center gap-2">
              <span className="text-amber-400 flex items-center gap-1 text-sm font-semibold">
                <Clock className="w-3.5 h-3.5" /> {draftCount} Draft
              </span>
              <span className="text-gray-500">|</span>
              <span className="text-emerald-400 flex items-center gap-1 text-sm font-semibold">
                <CheckCircle className="w-3.5 h-3.5" /> {finalizedCount} Finalized
              </span>
            </p>
          </div>
        </div>

        <div className="bg-[#161B26] border border-white/10 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-400 font-medium">Total Billing Value</p>
            <p className="text-2xl font-bold text-emerald-400 mt-1">
              ₹{(totalAmountPaise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-[#161B26] border border-white/10 rounded-xl p-3">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search invoice # or customer..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg pl-9 pr-3 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Filter className="w-4 h-4 text-gray-400" />
          <span className="text-xs text-gray-400">Status:</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-white/5 border border-white/10 text-white text-xs rounded-lg px-2.5 py-1.5 focus:outline-none cursor-pointer"
          >
            <option value="" className="bg-[#161B26]">All Statuses</option>
            <option value="draft" className="bg-[#161B26]">Draft</option>
            <option value="finalized" className="bg-[#161B26]">Finalized</option>
            <option value="cancelled" className="bg-[#161B26]">Cancelled</option>
          </select>
        </div>
      </div>

      {/* Invoices List Table */}
      <div className="bg-[#161B26] border border-white/10 rounded-xl overflow-hidden shadow-xl">
        {loading ? (
          <div className="p-12 text-center text-gray-400">Loading invoices...</div>
        ) : error ? (
          <div className="p-8 text-center text-red-400">{error}</div>
        ) : filteredInvoices.length === 0 ? (
          <div className="p-12 text-center text-gray-400 space-y-3">
            <FileText className="w-12 h-12 mx-auto text-gray-600 stroke-[1.5]" />
            <p className="text-base font-medium text-gray-300">No invoices found</p>
            <p className="text-xs text-gray-500 max-w-sm mx-auto">
              Get started by configuring master data (Company Profile & Customers), then create your first draft invoice.
            </p>
            <Link
              href={`/einvoicing/new?client_gstin_id=${selectedClientId}`}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-xs font-semibold hover:bg-indigo-500 transition-colors"
            >
              <Plus className="w-4 h-4" /> Create Invoice Now
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-gray-300">
              <thead className="bg-white/5 text-xs text-gray-400 uppercase tracking-wider border-b border-white/10">
                <tr>
                  <th className="px-4 py-3">Invoice #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Customer</th>
                  <th className="px-4 py-3">Supply Type</th>
                  <th className="px-4 py-3 text-right">Taxable</th>
                  <th className="px-4 py-3 text-right">Tax Amount</th>
                  <th className="px-4 py-3 text-right">Total (₹)</th>
                  <th className="px-4 py-3 text-center">Status</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {filteredInvoices.map((inv) => {
                  const isDraft = inv.status === "draft";
                  return (
                    <tr key={inv.id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3 font-semibold text-white">
                        {inv.invoice_number}
                      </td>
                      <td className="px-4 py-3 text-gray-400">{inv.invoice_date}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-200">
                          {inv.customer?.name || "N/A"}
                        </div>
                        {inv.customer?.gstin && (
                          <div className="text-xs text-gray-500 font-mono">
                            {inv.customer.gstin}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {inv.is_interstate ? (
                          <span className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-medium">
                            Interstate (IGST)
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-medium">
                            Intrastate (CGST+SGST)
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        ₹{(inv.subtotal_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-gray-400">
                        ₹{(inv.total_tax_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-semibold text-emerald-400">
                        ₹{(inv.total_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isDraft ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                            <Clock className="w-3 h-3" /> Draft
                          </span>
                        ) : inv.status === "finalized" ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            <CheckCircle className="w-3 h-3" /> Finalized
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20">
                            Cancelled
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/einvoicing/${inv.id}?client_gstin_id=${selectedClientId}`}
                          className="inline-flex items-center gap-1 text-xs font-medium text-indigo-400 hover:text-indigo-300 transition-colors"
                        >
                          View Details <ArrowRight className="w-3.5 h-3.5" />
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
