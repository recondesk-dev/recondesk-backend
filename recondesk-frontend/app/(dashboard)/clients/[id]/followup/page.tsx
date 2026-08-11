"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  AlertTriangle,
  Send,
  MessageSquare,
  Mail,
  Copy,
  CheckCircle2,
  Clock,
  ShieldAlert,
  Loader2,
  RefreshCw,
  X,
  ExternalLink,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { formatINR } from "@/lib/format";
import { useToast } from "@/components/providers/ToastProvider";
import {
  fetchVendorRiskSummaries,
  generateWhatsAppLink,
  generateEmailNotice,
  logFollowupDispatch,
  fetchFollowupHistory,
  type VendorRiskSummary,
  type FollowupLog,
} from "@/lib/vendorFollowupApi";

export default function VendorFollowupHubPage() {
  const params = useParams();
  const clientId = String(params.id);
  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"risk_list" | "audit_log">("risk_list");
  const [templateType, setTemplateType] = useState<"POLITE_REMINDER" | "RULE37_NOTICE" | "FINAL_ESCALATION">("POLITE_REMINDER");
  const [searchQuery, setSearchQuery] = useState("");

  const [vendors, setVendors] = useState<VendorRiskSummary[]>([]);
  const [historyLogs, setHistoryLogs] = useState<FollowupLog[]>([]);
  const [totalRiskItc, setTotalRiskItc] = useState(0);

  const [selectedVendorForModal, setSelectedVendorForModal] = useState<VendorRiskSummary | null>(null);
  const [emailModalNotice, setEmailModalNotice] = useState<{ subject: string; html: string } | null>(null);

  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !clientId) return;
    loadData();
  }, [token, clientId]);

  const loadData = async () => {
    if (!token || !clientId) return;
    setLoading(true);
    try {
      const summaryRes = await fetchVendorRiskSummaries(clientId, token);
      setVendors(summaryRes.vendors);
      setTotalRiskItc(summaryRes.total_at_risk_itc_rupees);

      const histRes = await fetchFollowupHistory(clientId, token);
      setHistoryLogs(histRes.logs);
    } catch (err: any) {
      toast(err?.detail || "Failed to load vendor risk summaries", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleWhatsAppDispatch = async (v: VendorRiskSummary) => {
    if (!token || !clientId) return;
    setActionLoading(`wa-${v.supplier_gstin}`);
    try {
      const payload = await generateWhatsAppLink(
        clientId,
        {
          supplier_gstin: v.supplier_gstin,
          supplier_name: v.supplier_name,
          vendor_phone: v.vendor_phone,
          at_risk_itc_rupees: v.at_risk_itc_rupees,
          template_type: templateType,
        },
        token
      );

      // Log dispatch action
      await logFollowupDispatch(
        clientId,
        {
          supplier_gstin: v.supplier_gstin,
          supplier_name: v.supplier_name,
          vendor_phone: v.vendor_phone,
          channel: "WHATSAPP",
          template_type: templateType,
          at_risk_itc_rupees: v.at_risk_itc_rupees,
        },
        token
      );

      // Open WhatsApp link in new tab
      window.open(payload.whatsapp_url, "_blank");
      toast(`Logged WhatsApp follow-up for ${v.supplier_gstin}`, "success");
      loadData();
    } catch (err: any) {
      toast("Failed to generate WhatsApp follow-up link", "error");
    } finally {
      setActionLoading(null);
    }
  };

  const handleOpenEmailModal = async (v: VendorRiskSummary) => {
    if (!token || !clientId) return;
    setActionLoading(`email-${v.supplier_gstin}`);
    try {
      const notice = await generateEmailNotice(
        clientId,
        {
          supplier_gstin: v.supplier_gstin,
          supplier_name: v.supplier_name,
          at_risk_itc_rupees: v.at_risk_itc_rupees,
          template_type: templateType,
        },
        token
      );

      setSelectedVendorForModal(v);
      setEmailModalNotice({ subject: notice.subject, html: notice.html_body });

      // Log email dispatch event
      await logFollowupDispatch(
        clientId,
        {
          supplier_gstin: v.supplier_gstin,
          supplier_name: v.supplier_name,
          vendor_phone: v.vendor_phone,
          vendor_email: v.vendor_email,
          channel: "EMAIL",
          template_type: templateType,
          at_risk_itc_rupees: v.at_risk_itc_rupees,
        },
        token
      );
    } catch (err: any) {
      toast("Failed to generate email notice payload", "error");
    } finally {
      setActionLoading(null);
    }
  };

  const handleCopyEmailBody = () => {
    if (!emailModalNotice) return;
    navigator.clipboard.writeText(emailModalNotice.html);
    toast("Copied HTML email notice to clipboard", "success");
  };

  const filteredVendors = vendors.filter(
    (v) =>
      v.supplier_gstin.toLowerCase().includes(searchQuery.toLowerCase()) ||
      v.supplier_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href={`/clients/${clientId}`}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-600 transition hover:bg-gray-200"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Automated Vendor Follow-up Hub</h1>
            <p className="text-sm text-gray-500">
              1-Click WhatsApp & Email compliance follow-ups for unfiled GSTR-1 & Rule 37 tax risk
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={loadData}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4 text-gray-500" />
          Refresh Summaries
        </button>
      </div>

      {/* Summary Stat Cards */}
      <div className="mb-8 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">High Risk Vendors</span>
            <div className="rounded-xl bg-red-50 p-2 text-red-600">
              <ShieldAlert className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-gray-900">{vendors.length}</p>
          <p className="mt-1 text-xs text-gray-500">Vendors with unfiled returns or Rule 37 risk</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">Total ITC at Risk</span>
            <div className="rounded-xl bg-amber-50 p-2 text-amber-600">
              <AlertTriangle className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-amber-600">{formatINR(totalRiskItc)}</p>
          <p className="mt-1 text-xs text-gray-500">Total unmatched & 180-day overdue ITC exposure</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">Follow-ups Dispatched</span>
            <div className="rounded-xl bg-indigo-50 p-2 text-indigo-600">
              <Send className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-gray-900">{historyLogs.length}</p>
          <p className="mt-1 text-xs text-gray-500">Total WhatsApp & Email notices sent</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">Response Rate</span>
            <div className="rounded-xl bg-emerald-50 p-2 text-emerald-600">
              <CheckCircle2 className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-emerald-600">
            {vendors.length > 0 ? `${Math.round((historyLogs.length / vendors.length) * 100)}%` : "100%"}
          </p>
          <p className="mt-1 text-xs text-gray-500">Vendors contacted vs total risk list</p>
        </div>
      </div>

      {/* Main Container Card */}
      <div className="rounded-2xl border border-gray-200 bg-white shadow-sm">
        {/* Navigation Bar & Controls */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("risk_list")}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                activeTab === "risk_list" ? "bg-indigo-50 text-indigo-700" : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              High-Risk Vendors ({vendors.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("audit_log")}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                activeTab === "audit_log" ? "bg-indigo-50 text-indigo-700" : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              Follow-up Audit Trail ({historyLogs.length})
            </button>
          </div>

          {activeTab === "risk_list" && (
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold text-gray-500">Template Category:</span>
              <select
                value={templateType}
                onChange={(e: any) => setTemplateType(e.target.value)}
                className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-bold text-gray-800 shadow-sm"
              >
                <option value="POLITE_REMINDER">📋 Gentle GSTR-1 Reminder</option>
                <option value="RULE37_NOTICE">⚠️ Rule 37 Overdue Tax Risk (180 Days)</option>
                <option value="FINAL_ESCALATION">🚨 Final Legal Notice & Payment Hold</option>
              </select>
            </div>
          )}
        </div>

        {/* Tab 1: High Risk Vendors List */}
        {activeTab === "risk_list" && (
          <div>
            <div className="border-b border-gray-100 px-6 py-3 bg-gray-50">
              <input
                type="text"
                placeholder="Search vendor by GSTIN or trade name..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-900 shadow-sm placeholder:text-gray-400"
              />
            </div>

            {filteredVendors.length === 0 ? (
              <div className="p-12 text-center">
                <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" />
                <h3 className="mt-2 text-base font-bold text-gray-900">No High-Risk Vendors Found</h3>
                <p className="mt-1 text-sm text-gray-500">All supplier invoices are fully reconciled with GSTR-2B!</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-200">
                {filteredVendors.map((v) => (
                  <div
                    key={v.supplier_gstin}
                    className="flex flex-wrap items-center justify-between gap-4 p-6 transition hover:bg-gray-50/80"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-100 text-red-700 font-bold">
                        {v.risk_score}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-base font-bold text-gray-900">{v.supplier_name}</h3>
                          <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs font-bold text-gray-600">
                            {v.supplier_gstin}
                          </span>
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-4 text-xs text-gray-500">
                          <span>Rule 37 Invoices: <strong>{v.rule37_count}</strong></span>
                          <span>•</span>
                          <span>Rule 37 Tax Risk: <strong className="text-amber-700">{formatINR(v.rule37_at_risk_rupees)}</strong></span>
                          <span>•</span>
                          <span>Follow-ups Sent: <strong>{v.followup_count}</strong></span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <div className="text-right mr-2">
                        <span className="text-xs uppercase font-bold text-gray-400">Total Exposure</span>
                        <p className="text-lg font-bold text-red-600">{formatINR(v.at_risk_itc_rupees)}</p>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleWhatsAppDispatch(v)}
                        disabled={actionLoading === `wa-${v.supplier_gstin}`}
                        className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
                      >
                        {actionLoading === `wa-${v.supplier_gstin}` ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <MessageSquare className="h-4 w-4" />
                        )}
                        WhatsApp Notice
                      </button>

                      <button
                        type="button"
                        onClick={() => handleOpenEmailModal(v)}
                        disabled={actionLoading === `email-${v.supplier_gstin}`}
                        className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
                      >
                        {actionLoading === `email-${v.supplier_gstin}` ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Mail className="h-4 w-4" />
                        )}
                        Email Notice
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Follow-up Audit Trail */}
        {activeTab === "audit_log" && (
          <div className="p-6">
            {historyLogs.length === 0 ? (
              <div className="p-8 text-center text-gray-500 text-sm">
                No follow-up dispatch history recorded yet. Send your first WhatsApp or Email notice!
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm text-gray-600">
                  <thead className="bg-gray-50 text-xs uppercase font-bold text-gray-500">
                    <tr>
                      <th className="px-4 py-3">Dispatched At</th>
                      <th className="px-4 py-3">Supplier GSTIN</th>
                      <th className="px-4 py-3">Channel</th>
                      <th className="px-4 py-3">Template</th>
                      <th className="px-4 py-3">ITC Amount</th>
                      <th className="px-4 py-3">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {historyLogs.map((log) => (
                      <tr key={log.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-mono text-xs">
                          {new Date(log.dispatched_at).toLocaleString("en-IN")}
                        </td>
                        <td className="px-4 py-3 font-bold text-gray-900">{log.supplier_gstin}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold ${
                              log.channel === "WHATSAPP"
                                ? "bg-emerald-100 text-emerald-800"
                                : "bg-indigo-100 text-indigo-800"
                            }`}
                          >
                            {log.channel}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs font-semibold text-gray-700">
                          {log.template_type.replace("_", " ")}
                        </td>
                        <td className="px-4 py-3 font-bold text-gray-900">{formatINR(log.at_risk_itc_rupees)}</td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-bold text-slate-800">
                            {log.status === "LINK_OPENED"
                              ? "Link Opened"
                              : log.status === "NOTICE_GENERATED"
                              ? "Notice Generated"
                              : log.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Email Notice Modal */}
      {selectedVendorForModal && emailModalNotice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">Email Notice — {selectedVendorForModal.supplier_gstin}</h3>
                <p className="text-xs text-gray-500">Generated formal HTML vendor compliance letter</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedVendorForModal(null);
                  setEmailModalNotice(null);
                }}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[55vh] overflow-y-auto p-6 space-y-4">
              <div>
                <label className="text-xs font-bold text-gray-500 uppercase">Subject</label>
                <input
                  type="text"
                  readOnly
                  value={emailModalNotice.subject}
                  className="mt-1 w-full rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm font-semibold text-gray-900"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-gray-500 uppercase">Formatted HTML Notice Body</label>
                <div
                  className="mt-1 rounded-xl border border-gray-200 p-4 bg-gray-50 text-sm"
                  dangerouslySetInnerHTML={{ __html: emailModalNotice.html }}
                />
              </div>
            </div>

            <div className="border-t border-gray-200 bg-gray-50 px-6 py-4 flex justify-between items-center">
              <span className="text-xs font-medium text-emerald-700">✓ Follow-up event logged in audit trail</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleCopyEmailBody}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50"
                >
                  <Copy className="h-4 w-4 text-gray-500" />
                  Copy HTML Text
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedVendorForModal(null);
                    setEmailModalNotice(null);
                  }}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
