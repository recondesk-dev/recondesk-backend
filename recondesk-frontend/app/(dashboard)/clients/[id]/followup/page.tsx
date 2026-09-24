"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
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
  Phone,
  Eye,
} from "lucide-react";

import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { formatINR } from "@/lib/format";
import { useToast } from "@/components/providers/ToastProvider";
import {
  fetchVendorRiskSummaries,
  generateWhatsAppLink,
  generateEmailNotice,
  generateVendorToken,
  updateVendorContact,
  logFollowupDispatch,
  fetchFollowupHistory,
  type VendorRiskSummary,
  type FollowupLog,
} from "@/lib/vendorFollowupApi";

function VendorFollowupHubContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const clientId = String(params.id);
  const rawToken = useAccessToken();
  const token = typeof rawToken === "string" ? rawToken : null;
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const tabParam = searchParams?.get("tab");
  const [activeTab, setActiveTab] = useState<"risk_list" | "audit_log">(() => {
    return tabParam === "audit_log" ? "audit_log" : "risk_list";
  });

  useEffect(() => {
    const p = searchParams?.get("tab");
    if (p === "audit_log" || p === "risk_list") {
      setActiveTab(p);
    }
  }, [searchParams]);
  const [templateType, setTemplateType] = useState<"POLITE_REMINDER" | "RULE37_NOTICE" | "FINAL_ESCALATION">("POLITE_REMINDER");
  const [searchQuery, setSearchQuery] = useState("");

  const [vendors, setVendors] = useState<VendorRiskSummary[]>([]);
  const [historyLogs, setHistoryLogs] = useState<FollowupLog[]>([]);
  const [totalRiskItc, setTotalRiskItc] = useState(0);

  const [selectedVendorForModal, setSelectedVendorForModal] = useState<VendorRiskSummary | null>(null);
  const [emailModalNotice, setEmailModalNotice] = useState<{ subject: string; html: string } | null>(null);

  const [addPhoneModalVendor, setAddPhoneModalVendor] = useState<VendorRiskSummary | null>(null);
  const [newVendorPhone, setNewVendorPhone] = useState("");
  const [newVendorEmail, setNewVendorEmail] = useState("");
  const [savingContact, setSavingContact] = useState(false);

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

  const handleSaveContact = async () => {
    if (!addPhoneModalVendor || !token || !clientId) return;
    if (!newVendorPhone.trim()) {
      toast("Please enter a valid phone number", "error");
      return;
    }
    setSavingContact(true);
    try {
      await updateVendorContact(
        clientId,
        addPhoneModalVendor.supplier_gstin,
        {
          vendor_phone: newVendorPhone.trim(),
          vendor_email: newVendorEmail.trim() || undefined,
        },
        token
      );
      toast(`Contact details saved for ${addPhoneModalVendor.supplier_gstin}`, "success");
      setVendors((prev) =>
        prev.map((item) =>
          item.supplier_gstin === addPhoneModalVendor.supplier_gstin
            ? {
                ...item,
                vendor_phone: newVendorPhone.trim(),
                vendor_email: newVendorEmail.trim() || item.vendor_email,
              }
            : item
        )
      );
      setAddPhoneModalVendor(null);
    } catch (err: any) {
      toast(err?.detail || err?.message || "Failed to save contact information", "error");
    } finally {
      setSavingContact(false);
    }
  };

  const handleWhatsAppDispatch = async (v: VendorRiskSummary) => {
    if (!token || !clientId) return;
    if (!v.vendor_phone || !v.vendor_phone.trim()) {
      setAddPhoneModalVendor(v);
      setNewVendorPhone("");
      setNewVendorEmail(v.vendor_email || "");
      return;
    }

    setActionLoading(`wa-${v.supplier_gstin}`);
    try {
      // 1. Generate tokenized action portal URL
      let portalUrl: string | undefined;
      let actionToken: string | undefined;
      try {
        const tokRes = await generateVendorToken(
          clientId,
          {
            supplier_gstin: v.supplier_gstin,
            supplier_name: v.supplier_name,
            vendor_phone: v.vendor_phone,
            vendor_email: v.vendor_email,
            at_risk_itc_rupees: v.at_risk_itc_rupees,
            template_type: templateType,
            channel: "WHATSAPP",
          },
          token
        );
        portalUrl = tokRes.portal_url;
        actionToken = tokRes.token;
      } catch (tokErr) {
        console.warn("Portal token generation error:", tokErr);
      }

      // 2. Generate WhatsApp payload with portal URL
      const payload = await generateWhatsAppLink(
        clientId,
        {
          supplier_gstin: v.supplier_gstin,
          supplier_name: v.supplier_name,
          vendor_phone: v.vendor_phone,
          at_risk_itc_rupees: v.at_risk_itc_rupees,
          template_type: templateType,
          portal_url: portalUrl,
        },
        token
      );

      // 3. Log dispatch action with token
      await logFollowupDispatch(
        clientId,
        {
          supplier_gstin: v.supplier_gstin,
          supplier_name: v.supplier_name,
          vendor_phone: v.vendor_phone,
          channel: "WHATSAPP",
          template_type: templateType,
          at_risk_itc_rupees: v.at_risk_itc_rupees,
          token: actionToken,
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
      // 1. Generate tokenized action portal URL
      let portalUrl: string | undefined;
      let actionToken: string | undefined;
      try {
        const tokRes = await generateVendorToken(
          clientId,
          {
            supplier_gstin: v.supplier_gstin,
            supplier_name: v.supplier_name,
            vendor_phone: v.vendor_phone,
            vendor_email: v.vendor_email,
            at_risk_itc_rupees: v.at_risk_itc_rupees,
            template_type: templateType,
            channel: "EMAIL",
          },
          token
        );
        portalUrl = tokRes.portal_url;
        actionToken = tokRes.token;
      } catch (tokErr) {
        console.warn("Portal token generation error:", tokErr);
      }

      // 2. Generate email notice with portal URL
      const notice = await generateEmailNotice(
        clientId,
        {
          supplier_gstin: v.supplier_gstin,
          supplier_name: v.supplier_name,
          at_risk_itc_rupees: v.at_risk_itc_rupees,
          template_type: templateType,
          portal_url: portalUrl,
        },
        token
      );

      setSelectedVendorForModal(v);
      setEmailModalNotice({ subject: notice.subject, html: notice.html_body });

      // 3. Log email dispatch event with token
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
          token: actionToken,
        },
        token
      );
      loadData();
    } catch (err: any) {
      toast("Failed to generate email notice payload", "error");
    } finally {
      setActionLoading(null);
    }
  };

  const renderStatusPill = (v: VendorRiskSummary) => {
    if (v.followup_status === "FILING_CONFIRMED" || v.response_action === "ALREADY_FILED") {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-bold text-emerald-700">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          🟢 Confirmed {v.arn_number ? `(${v.arn_number.slice(0, 8)}...)` : ""}
        </span>
      );
    }
    if (v.followup_status === "PROMISED_NEXT_CYCLE" || v.response_action === "PROMISED_NEXT_CYCLE") {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-bold text-amber-700">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          🟡 Promised {v.promised_period ? `(${v.promised_period})` : "Next Cycle"}
        </span>
      );
    }
    if (v.followup_status === "DISPUTED" || v.response_action === "DISPUTED") {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-2.5 py-0.5 text-xs font-bold text-rose-700">
          <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
          🔴 Disputed
        </span>
      );
    }
    if (v.followup_status === "VIEWED" || Boolean(v.viewed_at)) {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-purple-200 bg-purple-50 px-2.5 py-0.5 text-xs font-bold text-purple-700">
          <Eye className="h-3 w-3 text-purple-600" />
          🟣 Viewed
        </span>
      );
    }
    if (
      v.followup_status === "DISPATCHED" ||
      v.followup_status === "SENT" ||
      v.followup_status === "LINK_OPENED" ||
      (v.followup_count && v.followup_count > 0)
    ) {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-bold text-blue-700">
          <Send className="h-3 w-3 text-blue-600" />
          🔵 Dispatched
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-100 px-2.5 py-0.5 text-xs font-bold text-gray-500">
        ⚪ Unsent
      </span>
    );
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
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-base font-bold text-gray-900">{v.supplier_name}</h3>
                          <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs font-bold text-gray-600">
                            {v.supplier_gstin}
                          </span>
                          {renderStatusPill(v)}
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-gray-500">
                          <span>Rule 37 Invoices: <strong>{v.rule37_count}</strong></span>
                          <span>•</span>
                          <span>Rule 37 Tax Risk: <strong className="text-amber-700">{formatINR(v.rule37_at_risk_rupees)}</strong></span>
                          <span>•</span>
                          <span>Follow-ups Sent: <strong>{v.followup_count}</strong></span>
                          {v.vendor_phone ? (
                            <>
                              <span>•</span>
                              <span className="font-mono text-gray-700">📱 {v.vendor_phone}</span>
                            </>
                          ) : (
                            <>
                              <span>•</span>
                              <span className="font-medium text-amber-600">⚠️ No Phone Saved</span>
                            </>
                          )}
                          {v.token && (
                            <>
                              <span>•</span>
                              <a
                                href={`/v/${v.token}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 font-semibold text-indigo-600 hover:text-indigo-800 hover:underline"
                              >
                                Portal Link
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <div className="text-right mr-2">
                        <span className="text-xs uppercase font-bold text-gray-400">Total Exposure</span>
                        <p className="text-lg font-bold text-red-600">{formatINR(v.at_risk_itc_rupees)}</p>
                      </div>

                      {v.vendor_phone && v.vendor_phone.trim() ? (
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
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setAddPhoneModalVendor(v);
                            setNewVendorPhone("");
                            setNewVendorEmail(v.vendor_email || "");
                          }}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-gray-300 bg-gray-100 px-3.5 py-2.5 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-200 hover:border-gray-400"
                        >
                          <Phone className="h-3.5 w-3.5 text-gray-500" />
                          + Add Phone
                        </button>
                      )}

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
                        <td className="px-4 py-3 font-bold text-gray-900">
                          <div>{log.supplier_gstin}</div>
                          {log.supplier_name && <div className="text-xs font-normal text-gray-500">{log.supplier_name}</div>}
                        </td>
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
                          {log.template_type.replace(/_/g, " ")}
                        </td>
                        <td className="px-4 py-3 font-bold text-gray-900">{formatINR(log.at_risk_itc_rupees)}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-col gap-1 items-start">
                            <span
                              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold ${
                                log.status === "FILING_CONFIRMED"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : log.status === "PROMISED_NEXT_CYCLE"
                                  ? "bg-amber-100 text-amber-800"
                                  : log.status === "DISPUTED"
                                  ? "bg-rose-100 text-rose-800"
                                  : log.status === "VIEWED"
                                  ? "bg-purple-100 text-purple-800"
                                  : "bg-slate-100 text-slate-800"
                              }`}
                            >
                              {log.status === "FILING_CONFIRMED"
                                ? `Confirmed ${log.arn_number ? `(ARN: ${log.arn_number})` : ""}`
                                : log.status === "PROMISED_NEXT_CYCLE"
                                ? `Promised (${log.promised_period || "Next Cycle"})`
                                : log.status === "DISPUTED"
                                ? "Disputed"
                                : log.status === "VIEWED"
                                ? "Viewed"
                                : log.status === "LINK_OPENED"
                                ? "Link Opened"
                                : log.status === "NOTICE_GENERATED"
                                ? "Notice Generated"
                                : log.status}
                            </span>
                            {log.token && (
                              <a
                                href={`/v/${log.token}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 font-mono text-[10px] text-indigo-600 hover:underline"
                              >
                                /v/{log.token.slice(0, 8)}...
                                <ExternalLink className="h-2.5 w-2.5" />
                              </a>
                            )}
                          </div>
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

      {/* Add Phone Number Modal */}
      {addPhoneModalVendor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">Add Vendor Contact</h3>
                <p className="text-xs text-gray-500">
                  {addPhoneModalVendor.supplier_name} ({addPhoneModalVendor.supplier_gstin})
                </p>
              </div>
              <button
                type="button"
                onClick={() => setAddPhoneModalVendor(null)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase text-gray-600">WhatsApp Mobile Number *</label>
                <div className="mt-1 flex rounded-lg shadow-sm">
                  <span className="inline-flex items-center rounded-l-lg border border-r-0 border-gray-300 bg-gray-50 px-3 text-sm text-gray-500">
                    +91
                  </span>
                  <input
                    type="tel"
                    placeholder="9876543210"
                    value={newVendorPhone}
                    onChange={(e) => setNewVendorPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
                    className="block w-full flex-1 rounded-none rounded-r-lg border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-900 placeholder:text-gray-400 focus:border-indigo-500 focus:ring-indigo-500"
                  />
                </div>
                <p className="mt-1 text-[11px] text-gray-500">
                  Required for 1-click WhatsApp compliance notice dispatch with reconciliation link.
                </p>
              </div>

              <div>
                <label className="block text-xs font-bold uppercase text-gray-600">Email Address (Optional)</label>
                <input
                  type="email"
                  placeholder="accounts@vendor.com"
                  value={newVendorEmail}
                  onChange={(e) => setNewVendorEmail(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-900 placeholder:text-gray-400 focus:border-indigo-500 focus:ring-indigo-500"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-gray-200 bg-gray-50 px-6 py-4">
              <button
                type="button"
                onClick={() => setAddPhoneModalVendor(null)}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveContact}
                disabled={savingContact || !newVendorPhone.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
              >
                {savingContact ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Save Contact
              </button>
            </div>
          </div>
        </div>
      )}

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

export default function VendorFollowupHubPage() {
  return (
    <Suspense
      fallback={
        <div className="h-64 animate-pulse rounded-2xl bg-gray-100" />
      }
    >
      <VendorFollowupHubContent />
    </Suspense>
  );
}
