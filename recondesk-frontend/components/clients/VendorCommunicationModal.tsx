"use client";

import React, { useState, useEffect } from "react";
import {
  X,
  Send,
  MessageSquare,
  Mail,
  Loader2,
  ExternalLink,
  Copy,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { formatINR } from "@/lib/format";
import {
  generateWhatsAppLink,
  generateEmailNotice,
  logFollowupDispatch,
} from "@/lib/vendorFollowupApi";
import { useToast } from "@/components/providers/ToastProvider";

interface VendorCommunicationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDispatched: () => void;
  clientId: string;
  workItemId: string;
  vendorGstin: string;
  vendorName: string;
  vendorPhone?: string;
  vendorEmail?: string;
  atRiskItcRupees: number;
  token: string;
}

type TemplateType =
  | "POLITE_REMINDER"
  | "RULE37_NOTICE"
  | "FINAL_ESCALATION"
  | "MISSING_2B_REQUEST"
  | "VALUE_MISMATCH_VERIFICATION";

export default function VendorCommunicationModal({
  isOpen,
  onClose,
  onDispatched,
  clientId,
  workItemId,
  vendorGstin,
  vendorName,
  vendorPhone = "",
  vendorEmail = "",
  atRiskItcRupees,
  token,
}: VendorCommunicationModalProps) {
  const toast = useToast();
  const [channel, setChannel] = useState<"WHATSAPP" | "EMAIL">("WHATSAPP");
  const [templateType, setTemplateType] = useState<TemplateType>("POLITE_REMINDER");
  const [phone, setPhone] = useState(vendorPhone);
  const [email, setEmail] = useState(vendorEmail);

  const [loadingPreview, setLoadingPreview] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [copied, setCopied] = useState(false);

  // Preview data
  const [waPreview, setWaPreview] = useState<{ message_text: string; whatsapp_url: string } | null>(null);
  const [emailPreview, setEmailPreview] = useState<{ subject: string; html_body: string } | null>(null);

  useEffect(() => {
    setPhone(vendorPhone);
  }, [vendorPhone]);

  useEffect(() => {
    setEmail(vendorEmail);
  }, [vendorEmail]);

  useEffect(() => {
    if (!isOpen) return;
    loadPreview();
  }, [isOpen, channel, templateType, phone, email]);

  const loadPreview = async () => {
    if (!token || !clientId) return;
    setLoadingPreview(true);
    try {
      if (channel === "WHATSAPP") {
        const res = await generateWhatsAppLink(
          clientId,
          {
            supplier_gstin: vendorGstin,
            supplier_name: vendorName,
            vendor_phone: phone,
            at_risk_itc_rupees: atRiskItcRupees,
            template_type: templateType,
          },
          token
        );
        setWaPreview({
          message_text: res.message_text,
          whatsapp_url: res.whatsapp_url,
        });
      } else {
        const res = await generateEmailNotice(
          clientId,
          {
            supplier_gstin: vendorGstin,
            supplier_name: vendorName,
            at_risk_itc_rupees: atRiskItcRupees,
            template_type: templateType,
          },
          token
        );
        setEmailPreview({
          subject: res.subject,
          html_body: res.html_body,
        });
      }
    } catch (err: any) {
      toast(err?.detail || "Failed to generate communication preview", "error");
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleDispatch = async () => {
    if (!token || !clientId) return;
    setDispatching(true);
    try {
      const messageBody =
        channel === "WHATSAPP"
          ? waPreview?.message_text || ""
          : emailPreview?.html_body || "";

      await logFollowupDispatch(
        clientId,
        {
          supplier_gstin: vendorGstin,
          supplier_name: vendorName,
          vendor_phone: phone,
          vendor_email: email,
          channel,
          template_type: templateType,
          at_risk_itc_rupees: atRiskItcRupees,
          work_item_id: workItemId,
          message_body: messageBody,
        },
        token
      );

      if (channel === "WHATSAPP" && waPreview?.whatsapp_url) {
        window.open(waPreview.whatsapp_url, "_blank", "noopener,noreferrer");
      }

      toast(
        channel === "WHATSAPP"
          ? "WhatsApp message link generated & logged to work item timeline."
          : "Email notice logged to work item timeline.",
        "success"
      );
      onDispatched();
      onClose();
    } catch (err: any) {
      toast(err?.detail || "Failed to log dispatch", "error");
    } finally {
      setDispatching(false);
    }
  };

  const handleCopyText = () => {
    const textToCopy =
      channel === "WHATSAPP"
        ? waPreview?.message_text || ""
        : `${emailPreview?.subject || ""}\n\n${emailPreview?.html_body.replace(/<[^>]*>?/gm, "") || ""}`;

    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white rounded-xl shadow-2xl border border-gray-200 w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50/50">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Send className="w-5 h-5 text-indigo-600" />
              Contact Vendor
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {vendorName || vendorGstin} ({vendorGstin}) • Stake:{" "}
              <span className="font-semibold text-gray-700">{formatINR(atRiskItcRupees)}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-5 flex-1">
          {/* Channel Selector */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-600 mb-2">
              Communication Channel
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setChannel("WHATSAPP")}
                className={`flex items-center justify-center gap-2.5 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                  channel === "WHATSAPP"
                    ? "border-emerald-500 bg-emerald-50/50 text-emerald-800 shadow-sm"
                    : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                }`}
              >
                <MessageSquare className="w-4 h-4 text-emerald-600" />
                WhatsApp (1-Click wa.me)
              </button>

              <button
                type="button"
                onClick={() => setChannel("EMAIL")}
                className={`flex items-center justify-center gap-2.5 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                  channel === "EMAIL"
                    ? "border-indigo-500 bg-indigo-50/50 text-indigo-800 shadow-sm"
                    : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                }`}
              >
                <Mail className="w-4 h-4 text-indigo-600" />
                Formal Email Notice
              </button>
            </div>
          </div>

          {/* Template Selector */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-600 mb-2">
              Statutory Notice Template
            </label>
            <select
              value={templateType}
              onChange={(e) => setTemplateType(e.target.value as TemplateType)}
              className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 bg-white text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="POLITE_REMINDER">Polite Reminder (Gentle Reconciliation Follow-up)</option>
              <option value="MISSING_2B_REQUEST">Missing 2B Request (Upload in GSTR-1 for Section 16(2)(aa))</option>
              <option value="VALUE_MISMATCH_VERIFICATION">Value Mismatch Notice (Reconcile Taxable Value & Rate)</option>
              <option value="RULE37_NOTICE">Rule 37 Notice (180-day Overdue Payment Reversal Risk)</option>
              <option value="FINAL_ESCALATION">Final Escalation (Administrative Hold Warning)</option>
            </select>
          </div>

          {/* Recipient Details */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {channel === "WHATSAPP" ? (
              <div className="md:col-span-2">
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Vendor Phone / WhatsApp Number
                </label>
                <input
                  type="text"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="e.g. 9876543210 (10 digits)"
                  className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            ) : (
              <div className="md:col-span-2">
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Vendor Email Address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="e.g. accounts@vendor.com"
                  className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            )}
          </div>

          {/* Message Preview Box */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-gray-600">
                Message Preview
              </label>
              <button
                type="button"
                onClick={handleCopyText}
                className="inline-flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
              >
                {copied ? (
                  <>
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                    <span className="text-emerald-600">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    Copy Content
                  </>
                )}
              </button>
            </div>

            {loadingPreview ? (
              <div className="h-44 border border-gray-200 rounded-lg flex items-center justify-center bg-gray-50 text-gray-400 text-sm">
                <Loader2 className="w-5 h-5 animate-spin mr-2 text-indigo-600" />
                Generating template preview...
              </div>
            ) : channel === "WHATSAPP" ? (
              <div className="border border-emerald-200 bg-emerald-50/30 rounded-lg p-3.5 text-xs font-mono whitespace-pre-wrap text-gray-800 max-h-52 overflow-y-auto leading-relaxed">
                {waPreview?.message_text}
              </div>
            ) : (
              <div className="border border-gray-200 rounded-lg p-3.5 bg-gray-50 max-h-56 overflow-y-auto">
                <div className="text-xs font-semibold text-gray-900 border-b pb-2 mb-2">
                  Subject: {emailPreview?.subject}
                </div>
                <div
                  className="text-xs text-gray-700 leading-relaxed"
                  dangerouslySetInnerHTML={{ __html: emailPreview?.html_body || "" }}
                />
              </div>
            )}
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <span>
              This dispatch will be automatically logged to the Work Item timeline as a{" "}
              <strong>COMMUNICATION_DISPATCHED</strong> event and preserved in vendor follow-up logs.
            </span>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50/50">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleDispatch}
            disabled={dispatching || loadingPreview}
            className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors shadow-sm"
          >
            {dispatching ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Dispatching & Logging...
              </>
            ) : channel === "WHATSAPP" ? (
              <>
                <ExternalLink className="w-4 h-4" />
                Launch WhatsApp & Log
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                Log Email Dispatch
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
