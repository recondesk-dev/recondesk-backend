"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  Filter,
  HelpCircle,
  Loader2,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import useSWR from "swr";

import { NoticeDefenseModal } from "@/components/notices/NoticeDefenseModal";
import { clientsApi, type ClientGstin } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  downloadDefenseExcel,
  listClientNotices,
  updateNoticeStatus,
  type SavedNoticeRecord,
} from "@/lib/noticeDefenseApi";

export default function ClientNoticesPage() {
  const params = useParams();
  const clientId = params?.id as string;
  const tokenState = useAccessToken();
  const authToken = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const [modalOpen, setModalOpen] = useState(false);
  const [selectedNoticeForView, setSelectedNoticeForView] = useState<SavedNoticeRecord | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("ALL");

  // Fetch client details
  const { data: client, isLoading: clientLoading } = useSWR<ClientGstin>(
    clientId && authToken ? ["client", clientId] : null,
    () => clientsApi.get(authToken!, clientId)
  );

  // Fetch client notices
  const {
    data: noticesData,
    isLoading: noticesLoading,
    mutate: mutateNotices,
  } = useSWR(clientId && authToken ? ["client-notices", clientId] : null, () =>
    listClientNotices(clientId, authToken!)
  );

  const notices: SavedNoticeRecord[] = noticesData?.notices || [];

  const filteredNotices = notices.filter((n) => {
    const matchesSearch =
      n.notice_reference.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.tax_period.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (n.issuing_authority || "").toLowerCase().includes(searchQuery.toLowerCase());

    const matchesType = typeFilter === "ALL" || n.notice_type === typeFilter;
    return matchesSearch && matchesType;
  });

  // Summary Metrics
  const totalNotices = notices.length;
  const totalDemand = notices.reduce((acc, curr) => acc + (Number(curr.alleged_tax_demand) || 0), 0);
  const fullyReconciledCount = notices.filter(
    (n) => n.defense_summary?.reconciliation_status === "FULLY_RECONCILED"
  ).length;
  const pendingCount = notices.filter((n) => n.status !== "CLOSED").length;

  const clientName = client?.trade_name || client?.legal_name || "Taxpayer";
  const clientGstin = client?.gstin || "";

  async function handleStatusChange(noticeId: string, newStatus: string) {
    try {
      await updateNoticeStatus(noticeId, newStatus, authToken || undefined);
      mutateNotices();
    } catch (err) {
      console.error("Failed to update status", err);
    }
  }

  if (tokenState === false) {
    return (
      <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
        Sign in required to view Notice Defense & Workpapers.
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-6 animate-in fade-in duration-150">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-500 mb-1">
            <Link href="/clients" className="hover:text-indigo-600 transition-colors">
              Clients
            </Link>
            <span>/</span>
            <Link href={`/clients/${clientId}`} className="hover:text-indigo-600 transition-colors">
              {clientName}
            </Link>
            <span>/</span>
            <span className="text-slate-800 font-bold">Notice Defense & Workpapers</span>
          </div>
          <h1 className="text-2xl font-black text-slate-900 tracking-tight flex items-center gap-2.5">
            GST Department Notice Defense Hub
            <span className="text-xs px-2.5 py-0.5 rounded-full font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
              Rule 88D / 88C & Sec 61
            </span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-0.5">
            Auto-link DRC-01C, ASMT-10, and DRC-01 notices to reconciliation runs to mathematically refute departmental demands.
          </p>
        </div>

        <button
          onClick={() => {
            setSelectedNoticeForView(null);
            setModalOpen(true);
          }}
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-md shadow-indigo-100 transition-all hover:scale-[1.02]"
        >
          <Plus className="w-4 h-4" />
          <span>Defend & Reconcile Notice</span>
        </button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <span className="text-slate-500 text-xs font-medium block mb-1">Total Notices</span>
          <div className="text-2xl font-bold font-mono text-slate-900">{totalNotices}</div>
          <span className="text-[11px] text-slate-400 mt-1 block">Inbound Department Actions</span>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <span className="text-slate-500 text-xs font-medium block mb-1">100% Fully Reconciled</span>
          <div className="text-2xl font-bold font-mono text-emerald-600">{fullyReconciledCount}</div>
          <span className="text-[11px] text-emerald-600 font-medium mt-1 block">Zero Unexplained Gap</span>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <span className="text-slate-500 text-xs font-medium block mb-1">Open / Under Action</span>
          <div className="text-2xl font-bold font-mono text-indigo-600">{pendingCount}</div>
          <span className="text-[11px] text-slate-400 mt-1 block">Awaiting Portal Submission</span>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <span className="text-slate-500 text-xs font-medium block mb-1">Total Alleged Exposure</span>
          <div className="text-2xl font-bold font-mono text-rose-600">{formatINR(totalDemand)}</div>
          <span className="text-[11px] text-slate-400 mt-1 block">Department Discrepancy Total</span>
        </div>
      </div>

      {/* Filters & Search */}
      <div className="flex flex-col md:flex-row items-center justify-between gap-3 bg-slate-50 p-3 rounded-xl border border-slate-200">
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            className="w-full text-xs rounded-lg border border-slate-300 bg-white pl-9 pr-3 py-2 text-slate-800 placeholder-slate-400 focus:ring-2 focus:ring-indigo-500"
            placeholder="Search DIN, Tax Period, Authority..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto">
          <Filter className="w-4 h-4 text-slate-400" />
          <select
            className="text-xs rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-700 font-medium focus:ring-2 focus:ring-indigo-500"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="ALL">All Notice Types</option>
            <option value="DRC-01C">Form GST DRC-01C (Rule 88D)</option>
            <option value="ASMT-10">Form GST ASMT-10 (Sec 61)</option>
            <option value="DRC-01B">Form GST DRC-01B (Rule 88C)</option>
            <option value="DRC-01">Form GST DRC-01 (SCN)</option>
          </select>
        </div>
      </div>

      {/* Notices Table */}
      {noticesLoading ? (
        <div className="py-20 flex flex-col items-center justify-center text-slate-400 bg-white rounded-2xl border border-slate-200 shadow-sm">
          <Loader2 className="w-8 h-8 animate-spin mb-3 text-indigo-600" />
          <p className="text-xs font-semibold">Loading notices and defense workpapers...</p>
        </div>
      ) : filteredNotices.length === 0 ? (
        <div className="py-16 text-center bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center mx-auto shadow-sm">
            <ShieldCheck className="w-7 h-7" />
          </div>
          <div>
            <h3 className="text-base font-bold text-slate-900">No GST Notices on Record</h3>
            <p className="text-xs text-slate-500 max-w-md mx-auto mt-1">
              When the GST department issues Form GST DRC-01C, ASMT-10, or DRC-01B for this client,
              upload the notice PDF here to auto-link with reconciliation data and draft the statutory defense.
            </p>
          </div>
          <button
            onClick={() => {
              setSelectedNoticeForView(null);
              setModalOpen(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-md shadow-indigo-100 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Defend First Notice</span>
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-xs text-left border-collapse">
            <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200 uppercase text-[10px]">
              <tr>
                <th className="p-3.5">Notice Reference / DIN</th>
                <th className="p-3.5">Form Type</th>
                <th className="p-3.5">Tax Period</th>
                <th className="p-3.5">Notice Date</th>
                <th className="p-3.5 text-right">Alleged Demand (₹)</th>
                <th className="p-3.5 text-center">Reconciliation Status</th>
                <th className="p-3.5 text-center">Status</th>
                <th className="p-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredNotices.map((n) => {
                const isFullyReconciled =
                  n.defense_summary?.reconciliation_status === "FULLY_RECONCILED";

                return (
                  <tr key={n.id} className="hover:bg-slate-50/70 transition-colors">
                    <td className="p-3.5">
                      <div className="font-mono font-bold text-slate-900">{n.notice_reference}</div>
                      <div className="text-[11px] text-slate-400 truncate max-w-[200px]">
                        {n.issuing_authority || "GST Department"}
                      </div>
                    </td>

                    <td className="p-3.5">
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-full font-bold text-[10px] ${
                          n.notice_type === "DRC-01C"
                            ? "bg-purple-50 text-purple-700 border border-purple-200"
                            : n.notice_type === "ASMT-10"
                            ? "bg-blue-50 text-blue-700 border border-blue-200"
                            : n.notice_type === "DRC-01B"
                            ? "bg-amber-50 text-amber-700 border border-amber-200"
                            : "bg-slate-100 text-slate-700 border border-slate-200"
                        }`}
                      >
                        {n.notice_type}
                      </span>
                    </td>

                    <td className="p-3.5 font-mono text-slate-700">{n.tax_period || "—"}</td>

                    <td className="p-3.5 text-slate-600">
                      <div>{n.issue_date || "—"}</div>
                      {n.reply_due_date && (
                        <div className="text-[10px] font-semibold text-rose-600 flex items-center gap-1 mt-0.5">
                          <Clock className="w-3 h-3" /> Due: {n.reply_due_date}
                        </div>
                      )}
                    </td>

                    <td className="p-3.5 text-right font-mono font-bold text-slate-900">
                      {formatINR(n.alleged_tax_demand)}
                    </td>

                    <td className="p-3.5 text-center">
                      {isFullyReconciled ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <CheckCircle2 className="w-3 h-3" /> 100% Reconciled
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
                          {n.defense_summary?.reconciled_pct || 0}% Explained
                        </span>
                      )}
                    </td>

                    <td className="p-3.5 text-center">
                      <select
                        value={n.status}
                        onChange={(e) => handleStatusChange(n.id, e.target.value)}
                        className="text-[11px] font-bold rounded-lg border border-slate-200 bg-white px-2 py-1 text-slate-700 focus:ring-1 focus:ring-indigo-500"
                      >
                        <option value="DEFENSE_READY">Defense Ready</option>
                        <option value="REPLY_SUBMITTED">Reply Submitted</option>
                        <option value="CLOSED">Closed / Dropped</option>
                      </select>
                    </td>

                    <td className="p-3.5 text-right space-x-2">
                      <button
                        onClick={() => downloadDefenseExcel(n, authToken || undefined)}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-emerald-700 hover:bg-emerald-50 transition-colors"
                        title="Download Excel Annexure"
                      >
                        <FileSpreadsheet className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Guided Defense Modal */}
      <NoticeDefenseModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        clientId={clientId}
        clientName={clientName}
        clientGstin={clientGstin}
        onSaved={() => mutateNotices()}
      />
    </div>
  );
}
