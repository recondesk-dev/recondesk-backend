"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  X,
  MessageSquare,
  Mail,
  ExternalLink,
  Copy,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileText,
  Phone,
  Send,
  AlertTriangle,
  Loader2,
  ShieldAlert,
  Download,
  Share2,
  Save,
  Clock,
} from "lucide-react";

import { formatINR } from "@/lib/format";
import { useToast } from "@/components/providers/ToastProvider";
import {
  fetchVendorRiskSummaries,
  generateWhatsAppLink,
  generateEmailNotice,
  generateVendorToken,
  updateVendorContact,
  logFollowupDispatch,
  type VendorRiskSummary,
} from "@/lib/vendorFollowupApi";
import {
  buildFollowupLetterDraft,
  buildFollowupLetterPdfBlob,
  buildInvoiceSnapshot,
  defaultSupplierDisplayName,
  followupPdfFilename,
  type RiskRowForFollowup,
} from "@/lib/supplierFollowupLetter";
import { downloadBlobAsFile } from "@/lib/download";

export interface BatchFollowupRow {
  id: string;
  supplier_gstin: string;
  supplier_name?: string | null;
  trade_name?: string | null;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  decision_what?: string | null;
  decision_why?: string | null;
  decision_next?: string | null;
}

interface BatchVendorFollowupDrawerProps {
  open: boolean;
  onClose: () => void;
  runId: string;
  clientId: string;
  clientName: string;
  clientGstin: string;
  taxPeriod: string;
  rows: BatchFollowupRow[];
  token: string;
}

interface SupplierGroup {
  supplierGstin: string;
  displayName: string;
  invoices: BatchFollowupRow[];
  totalAtRiskRupees: number;
  phone: string;
  email: string;
  savedPhone: string;
  savedEmail: string;
  isSavingContact: boolean;
  portalToken?: string;
  portalUrl?: string;
  dispatchedChannel?: string;
  dispatchedAt?: string;
  isDispatching: boolean;
}

const TEMPLATE_DESCRIPTIONS: Record<string, string> = {
  POLITE_REMINDER: "Friendly reminder requesting supplier to upload missing invoices in their next GSTR-1 return.",
  RULE37_NOTICE: "Formal statutory notice citing Section 16(2) second proviso & Rule 37 (180-day ITC reversal + 18% statutory interest liability).",
  FINAL_ESCALATION: "Critical escalation warning vendor that future invoice disbursements will be withheld until GSTR-1 is filed and reflected in GSTR-2B.",
};

export function BatchVendorFollowupDrawer({
  open,
  onClose,
  runId,
  clientId,
  clientName,
  clientGstin,
  taxPeriod,
  rows,
  token,
}: BatchVendorFollowupDrawerProps) {
  const toast = useToast();

  const [templateType, setTemplateType] = useState<"POLITE_REMINDER" | "RULE37_NOTICE" | "FINAL_ESCALATION">("POLITE_REMINDER");
  const [supplierGroups, setSupplierGroups] = useState<Record<string, SupplierGroup>>({});
  const [expandedGstins, setExpandedGstins] = useState<Set<string>>(new Set());
  const [emailModal, setEmailModal] = useState<{
    supplierGstin: string;
    supplierName: string;
    subject: string;
    htmlBody: string;
    portalUrl?: string;
  } | null>(null);

  const [isBulkGeneratingTokens, setIsBulkGeneratingTokens] = useState(false);
  const [copiedBatchKey, setCopiedBatchKey] = useState(false);

  // Group rows by supplier GSTIN on mount/rows update
  useEffect(() => {
    if (!open || !rows.length) return;

    const groups: Record<string, SupplierGroup> = {};

    rows.forEach((row) => {
      const gstin = (row.supplier_gstin || "UNKNOWN_SUPPLIER").trim().toUpperCase();
      if (!groups[gstin]) {
        const dName =
          row.trade_name?.trim() ||
          row.supplier_name?.trim() ||
          (gstin === "UNKNOWN_SUPPLIER" ? "Unidentified Supplier" : `M/s ${gstin}`);

        groups[gstin] = {
          supplierGstin: gstin,
          displayName: dName,
          invoices: [],
          totalAtRiskRupees: 0,
          phone: "",
          email: "",
          savedPhone: "",
          savedEmail: "",
          isSavingContact: false,
          isDispatching: false,
        };
      }
      groups[gstin].invoices.push(row);
      groups[gstin].totalAtRiskRupees += Number(row.amount || 0);
    });

    // Round total at risk per group
    Object.keys(groups).forEach((g) => {
      groups[g].totalAtRiskRupees = Math.round(groups[g].totalAtRiskRupees * 100) / 100;
    });

    setSupplierGroups(groups);

    // Expand the first supplier by default if small count
    const gstins = Object.keys(groups);
    if (gstins.length <= 3) {
      setExpandedGstins(new Set(gstins));
    } else if (gstins.length > 0) {
      setExpandedGstins(new Set([gstins[0]]));
    }

    // Auto-fetch known vendor contact info if clientId is available
    if (clientId && token) {
      fetchVendorRiskSummaries(clientId, token)
        .then((res) => {
          if (!res?.vendors) return;
          const contactMap: Record<string, { phone: string; email: string; name?: string }> = {};
          res.vendors.forEach((v) => {
            contactMap[v.supplier_gstin.trim().toUpperCase()] = {
              phone: v.vendor_phone || "",
              email: v.vendor_email || "",
              name: v.supplier_name || "",
            };
          });

          setSupplierGroups((prev) => {
            const next = { ...prev };
            Object.keys(next).forEach((gstin) => {
              const matched = contactMap[gstin];
              if (matched) {
                if (matched.phone && !next[gstin].phone) {
                  next[gstin].phone = matched.phone;
                  next[gstin].savedPhone = matched.phone;
                }
                if (matched.email && !next[gstin].email) {
                  next[gstin].email = matched.email;
                  next[gstin].savedEmail = matched.email;
                }
                if (matched.name && next[gstin].displayName.startsWith("M/s ")) {
                  next[gstin].displayName = matched.name;
                }
              }
            });
            return next;
          });
        })
        .catch(() => {
          // silently continue if vendor summary fails
        });
    }
  }, [open, rows, clientId, token]);

  const totalInvoices = rows.length;
  const totalSuppliers = Object.keys(supplierGroups).length;
  const totalAtRiskAll = useMemo(() => {
    return Object.values(supplierGroups).reduce((acc, curr) => acc + curr.totalAtRiskRupees, 0);
  }, [supplierGroups]);

  const toggleExpand = (gstin: string) => {
    setExpandedGstins((prev) => {
      const next = new Set(prev);
      if (next.has(gstin)) next.delete(gstin);
      else next.add(gstin);
      return next;
    });
  };

  const handleContactChange = (gstin: string, field: "phone" | "email", val: string) => {
    setSupplierGroups((prev) => ({
      ...prev,
      [gstin]: {
        ...prev[gstin],
        [field]: val,
      },
    }));
  };

  const handleSaveContact = async (gstin: string) => {
    const group = supplierGroups[gstin];
    if (!group || !clientId || !token) return;

    setSupplierGroups((prev) => ({
      ...prev,
      [gstin]: { ...prev[gstin], isSavingContact: true },
    }));

    try {
      await updateVendorContact(
        clientId,
        gstin,
        {
          vendor_phone: group.phone.trim(),
          vendor_email: group.email.trim(),
        },
        token
      );
      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: {
          ...prev[gstin],
          savedPhone: group.phone.trim(),
          savedEmail: group.email.trim(),
          isSavingContact: false,
        },
      }));
      toast(`Contact details updated for ${group.displayName}`, "success");
    } catch (e: any) {
      toast(e?.message || "Failed to update contact info", "error");
      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: { ...prev[gstin], isSavingContact: false },
      }));
    }
  };

  // 1-Click WhatsApp Direct Link
  const handleSendWhatsApp = async (gstin: string) => {
    const group = supplierGroups[gstin];
    if (!group || !clientId || !token) return;

    setSupplierGroups((prev) => ({
      ...prev,
      [gstin]: { ...prev[gstin], isDispatching: true },
    }));

    try {
      // 1. Generate token first so the message can embed the magic portal URL
      let portalUrl = group.portalUrl;
      let portalToken = group.portalToken;

      if (!portalUrl) {
        try {
          const tokRes = await generateVendorToken(
            clientId,
            {
              supplier_gstin: gstin,
              supplier_name: group.displayName,
              vendor_phone: group.phone.trim(),
              vendor_email: group.email.trim(),
              at_risk_itc_rupees: group.totalAtRiskRupees,
              template_type: templateType,
              channel: "WHATSAPP",
            },
            token
          );
          portalUrl = tokRes.portal_url;
          portalToken = tokRes.token;
        } catch {
          // If token generation fails, proceed with standard whatsapp text
        }
      }

      // 2. Generate WhatsApp payload
      const waRes = await generateWhatsAppLink(
        clientId,
        {
          supplier_gstin: gstin,
          supplier_name: group.displayName,
          vendor_phone: group.phone.trim(),
          at_risk_itc_rupees: group.totalAtRiskRupees,
          template_type: templateType,
          portal_url: portalUrl,
        },
        token
      );

      // 3. Open WhatsApp link in new tab
      if (waRes.whatsapp_url) {
        window.open(waRes.whatsapp_url, "_blank", "noopener,noreferrer");
      }

      // 4. Log follow-up dispatch event
      const invoicesSnapshot = group.invoices.map((inv) => ({
        invoice_number: inv.invoice_number,
        invoice_date: inv.invoice_date,
        tax_amount: inv.amount,
      }));

      await logFollowupDispatch(
        clientId,
        {
          supplier_gstin: gstin,
          supplier_name: group.displayName,
          vendor_phone: group.phone.trim(),
          vendor_email: group.email.trim(),
          channel: "WHATSAPP",
          template_type: templateType,
          at_risk_itc_rupees: group.totalAtRiskRupees,
          message_body: waRes.message_text,
          token: portalToken,
          invoices_snapshot: invoicesSnapshot,
        },
        token
      );

      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: {
          ...prev[gstin],
          portalToken,
          portalUrl,
          dispatchedChannel: "WHATSAPP",
          dispatchedAt: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
          isDispatching: false,
        },
      }));

      toast(`WhatsApp reminder opened for ${group.displayName}`, "success");
    } catch (e: any) {
      toast(e?.message || "Failed to trigger WhatsApp message", "error");
      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: { ...prev[gstin], isDispatching: false },
      }));
    }
  };

  // Email Notice Modal Trigger
  const handleOpenEmailNotice = async (gstin: string) => {
    const group = supplierGroups[gstin];
    if (!group || !clientId || !token) return;

    setSupplierGroups((prev) => ({
      ...prev,
      [gstin]: { ...prev[gstin], isDispatching: true },
    }));

    try {
      // 1. Generate token if not yet present
      let portalUrl = group.portalUrl;
      let portalToken = group.portalToken;

      if (!portalUrl) {
        try {
          const tokRes = await generateVendorToken(
            clientId,
            {
              supplier_gstin: gstin,
              supplier_name: group.displayName,
              vendor_phone: group.phone.trim(),
              vendor_email: group.email.trim(),
              at_risk_itc_rupees: group.totalAtRiskRupees,
              template_type: templateType,
              channel: "EMAIL",
            },
            token
          );
          portalUrl = tokRes.portal_url;
          portalToken = tokRes.token;
        } catch {
          // continue
        }
      }

      // 2. Generate email payload
      const emailRes = await generateEmailNotice(
        clientId,
        {
          supplier_gstin: gstin,
          supplier_name: group.displayName,
          at_risk_itc_rupees: group.totalAtRiskRupees,
          template_type: templateType,
          portal_url: portalUrl,
        },
        token
      );

      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: {
          ...prev[gstin],
          portalToken,
          portalUrl,
          isDispatching: false,
        },
      }));

      setEmailModal({
        supplierGstin: gstin,
        supplierName: group.displayName,
        subject: emailRes.subject,
        htmlBody: emailRes.html_body,
        portalUrl,
      });
    } catch (e: any) {
      toast(e?.message || "Failed to generate email notice", "error");
      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: { ...prev[gstin], isDispatching: false },
      }));
    }
  };

  // Generate & Copy Magic Portal Link
  const handleCopyPortalLink = async (gstin: string) => {
    const group = supplierGroups[gstin];
    if (!group || !clientId || !token) return;

    setSupplierGroups((prev) => ({
      ...prev,
      [gstin]: { ...prev[gstin], isDispatching: true },
    }));

    try {
      let portalUrl = group.portalUrl;
      let portalToken = group.portalToken;

      if (!portalUrl) {
        const tokRes = await generateVendorToken(
          clientId,
          {
            supplier_gstin: gstin,
            supplier_name: group.displayName,
            vendor_phone: group.phone.trim(),
            vendor_email: group.email.trim(),
            at_risk_itc_rupees: group.totalAtRiskRupees,
            template_type: templateType,
            channel: "PORTAL",
          },
          token
        );
        portalUrl = tokRes.portal_url;
        portalToken = tokRes.token;
      }

      if (portalUrl) {
        await navigator.clipboard.writeText(portalUrl);
      }

      // Log dispatch
      await logFollowupDispatch(
        clientId,
        {
          supplier_gstin: gstin,
          supplier_name: group.displayName,
          vendor_phone: group.phone.trim(),
          vendor_email: group.email.trim(),
          channel: "PORTAL",
          template_type: templateType,
          at_risk_itc_rupees: group.totalAtRiskRupees,
          token: portalToken,
        },
        token
      );

      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: {
          ...prev[gstin],
          portalToken,
          portalUrl,
          dispatchedChannel: "PORTAL",
          dispatchedAt: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
          isDispatching: false,
        },
      }));

      toast("Vendor Action Portal link copied to clipboard!", "success");
    } catch (e: any) {
      toast(e?.message || "Failed to generate vendor portal link", "error");
      setSupplierGroups((prev) => ({
        ...prev,
        [gstin]: { ...prev[gstin], isDispatching: false },
      }));
    }
  };

  // Download Formal PDF Letter for a supplier
  const handleDownloadPdfLetter = async (gstin: string) => {
    const group = supplierGroups[gstin];
    if (!group) return;

    try {
      const riskRows: RiskRowForFollowup[] = group.invoices.map((inv) => ({
        id: inv.id,
        supplier_gstin: gstin,
        trade_name: group.displayName,
        invoice_number: inv.invoice_number,
        invoice_date: inv.invoice_date,
        amount: inv.amount,
        decision_what: inv.decision_what || null,
        decision_why: inv.decision_why || null,
        decision_next: inv.decision_next || null,
      }));

      const snapshot = buildInvoiceSnapshot(riskRows);
      const display = defaultSupplierDisplayName(riskRows, group.displayName);
      const letterText = buildFollowupLetterDraft({
        clientName: clientName || "Client",
        clientGstin: clientGstin || "",
        taxPeriod: taxPeriod || "Current Period",
        supplierDisplayName: display,
        supplierGstin: gstin,
        snapshot,
      });

      const blob = await buildFollowupLetterPdfBlob(
        letterText,
        "Generated via ReconDesk Automated Vendor Follow-up Hub."
      );
      const filename = followupPdfFilename(gstin, taxPeriod || "period");
      downloadBlobAsFile(blob, filename);

      toast(`Downloaded follow-up letter for ${group.displayName}`, "success");
    } catch (e: any) {
      toast(e?.message || "Failed to generate PDF letter", "error");
    }
  };

  // Generate All Magic Portal Links in Bulk
  const handleGenerateAllPortalLinks = async () => {
    if (!clientId || !token) return;
    setIsBulkGeneratingTokens(true);

    try {
      const gstins = Object.keys(supplierGroups);
      const rowsSummary: string[] = [
        `ReconDesk Vendor Recovery Links — ${clientName} (${taxPeriod})`,
        `Generated: ${new Date().toLocaleString("en-IN")}`,
        "--------------------------------------------------------------------------------",
        "Supplier Name | GSTIN | Missing Invoices | Total ITC At Risk | Magic Portal URL",
        "--------------------------------------------------------------------------------",
      ];

      const updatedGroups = { ...supplierGroups };

      for (const gstin of gstins) {
        const group = updatedGroups[gstin];
        try {
          let portalUrl = group.portalUrl;
          let portalToken = group.portalToken;

          if (!portalUrl) {
            const tokRes = await generateVendorToken(
              clientId,
              {
                supplier_gstin: gstin,
                supplier_name: group.displayName,
                vendor_phone: group.phone.trim(),
                vendor_email: group.email.trim(),
                at_risk_itc_rupees: group.totalAtRiskRupees,
                template_type: templateType,
                channel: "PORTAL",
              },
              token
            );
            portalUrl = tokRes.portal_url;
            portalToken = tokRes.token;
          }

          updatedGroups[gstin] = {
            ...group,
            portalUrl,
            portalToken,
            dispatchedChannel: "PORTAL",
            dispatchedAt: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
          };

          rowsSummary.push(
            `${group.displayName} | ${gstin} | ${group.invoices.length} invoices | ${formatINR(group.totalAtRiskRupees)} | ${portalUrl}`
          );
        } catch {
          rowsSummary.push(`${group.displayName} | ${gstin} | Token generation failed`);
        }
      }

      setSupplierGroups(updatedGroups);

      // Copy all links table to clipboard
      await navigator.clipboard.writeText(rowsSummary.join("\n"));
      setCopiedBatchKey(true);
      setTimeout(() => setCopiedBatchKey(false), 3000);

      toast(`Generated and copied ${gstins.length} vendor portal links!`, "success");
    } catch (e: any) {
      toast(e?.message || "Failed to generate batch links", "error");
    } finally {
      setIsBulkGeneratingTokens(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/40 backdrop-blur-xs transition-opacity animate-in fade-in duration-200">
      <div className="fixed inset-y-0 right-0 flex max-w-full pl-6 sm:pl-10">
        <div className="w-screen max-w-3xl bg-white shadow-2xl flex flex-col h-full">
          {/* Header */}
          <div className="border-b border-gray-200 bg-[#FAFAFA] px-6 py-4 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-100 text-emerald-800">
                  <MessageSquare className="h-4 w-4" />
                </span>
                <h2 className="text-base font-bold text-gray-900">
                  Batch Vendor Recovery Follow-up
                </h2>
                <span className="rounded-full bg-gray-200 px-2.5 py-0.5 text-xs font-mono font-medium text-gray-700">
                  {taxPeriod}
                </span>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                {clientName} {clientGstin ? `(${clientGstin})` : ""} · Direct recovery actions for Missing in 2B invoices
              </p>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-2 text-gray-400 hover:bg-gray-200 hover:text-gray-700 transition"
              title="Close drawer"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Metric Overview Bar */}
          <div className="grid grid-cols-3 border-b border-gray-100 bg-white px-6 py-3 text-center">
            <div className="border-r border-gray-100 pr-3">
              <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                Invoices Selected
              </span>
              <p className="text-base font-bold text-gray-900">{totalInvoices}</p>
            </div>
            <div className="border-r border-gray-100 px-3">
              <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                Suppliers
              </span>
              <p className="text-base font-bold text-gray-900">{totalSuppliers}</p>
            </div>
            <div className="pl-3">
              <span className="text-[11px] font-semibold text-rose-600 uppercase tracking-wider">
                Total At-Risk ITC
              </span>
              <p className="text-base font-bold text-rose-700 font-mono">
                {formatINR(totalAtRiskAll)}
              </p>
            </div>
          </div>

          {/* Template Selection & Batch Tool Bar */}
          <div className="border-b border-gray-200 bg-[#FCFCFD] px-6 py-3 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-gray-700">Notice Tone:</span>
                <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 text-xs">
                  <button
                    type="button"
                    onClick={() => setTemplateType("POLITE_REMINDER")}
                    className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                      templateType === "POLITE_REMINDER"
                        ? "bg-[#0F172A] text-white"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Polite Reminder
                  </button>
                  <button
                    type="button"
                    onClick={() => setTemplateType("RULE37_NOTICE")}
                    className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                      templateType === "RULE37_NOTICE"
                        ? "bg-[#0F172A] text-white"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Rule 37 Statutory
                  </button>
                  <button
                    type="button"
                    onClick={() => setTemplateType("FINAL_ESCALATION")}
                    className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                      templateType === "FINAL_ESCALATION"
                        ? "bg-rose-700 text-white"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Final Escalation
                  </button>
                </div>
              </div>

              {/* Bulk Portal Generator */}
              <button
                type="button"
                disabled={isBulkGeneratingTokens || totalSuppliers === 0}
                onClick={handleGenerateAllPortalLinks}
                className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 transition"
              >
                {isBulkGeneratingTokens ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : copiedBatchKey ? (
                  <Check className="h-3.5 w-3.5 text-emerald-600" />
                ) : (
                  <Share2 className="h-3.5 w-3.5" />
                )}
                <span>{copiedBatchKey ? "All Links Copied!" : "Copy All Magic Links"}</span>
              </button>
            </div>

            <p className="text-[11px] text-gray-500 italic">
              {TEMPLATE_DESCRIPTIONS[templateType]}
            </p>
          </div>

          {/* Supplier Cards List */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {Object.keys(supplierGroups).length === 0 ? (
              <div className="py-12 text-center text-sm text-gray-500">
                No invoices selected for vendor follow-up.
              </div>
            ) : (
              Object.values(supplierGroups).map((group) => {
                const isExpanded = expandedGstins.has(group.supplierGstin);
                const hasContactUnsaved =
                  group.phone.trim() !== group.savedPhone.trim() ||
                  group.email.trim() !== group.savedEmail.trim();

                return (
                  <div
                    key={group.supplierGstin}
                    className="rounded-xl border border-gray-200 bg-white shadow-xs transition-shadow hover:shadow-sm"
                  >
                    {/* Supplier Header Bar */}
                    <div className="p-4 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-bold text-gray-900">
                            {group.displayName}
                          </h3>
                          <span className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-mono font-medium text-gray-700">
                            {group.supplierGstin}
                          </span>
                        </div>
                        <div className="mt-1 flex items-center gap-3 text-xs text-gray-500">
                          <span>
                            {group.invoices.length} missing invoice{group.invoices.length > 1 ? "s" : ""}
                          </span>
                          <span>·</span>
                          <span className="font-semibold text-rose-700 font-mono">
                            {formatINR(group.totalAtRiskRupees)} at risk
                          </span>
                          {group.dispatchedChannel && (
                            <>
                              <span>·</span>
                              <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.2 rounded-full border border-emerald-200">
                                <CheckCircle2 className="h-3 w-3" />
                                Dispatched ({group.dispatchedChannel}) {group.dispatchedAt ? `at ${group.dispatchedAt}` : ""}
                              </span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Expand / Collapse Invoices Button */}
                      <button
                        type="button"
                        onClick={() => toggleExpand(group.supplierGstin)}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 transition"
                      >
                        <span>{isExpanded ? "Hide Invoices" : "View Invoices"}</span>
                        {isExpanded ? (
                          <ChevronUp className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>

                    {/* Expandable Invoice Table */}
                    {isExpanded && (
                      <div className="bg-[#FAFAFA] px-4 py-3 border-b border-gray-100">
                        <div className="overflow-x-auto max-h-48 border border-gray-200 rounded-lg bg-white">
                          <table className="w-full text-left text-xs">
                            <thead className="bg-gray-50 border-b border-gray-200 text-gray-600">
                              <tr>
                                <th className="px-3 py-2 font-medium">Invoice #</th>
                                <th className="px-3 py-2 font-medium">Date</th>
                                <th className="px-3 py-2 font-medium text-right">Tax Amount</th>
                                <th className="px-3 py-2 font-medium">Status / Action</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                              {group.invoices.map((inv) => (
                                <tr key={inv.id} className="hover:bg-gray-50/50">
                                  <td className="px-3 py-2 font-mono font-medium text-gray-900">
                                    {inv.invoice_number}
                                  </td>
                                  <td className="px-3 py-2 text-gray-600">
                                    {inv.invoice_date || "—"}
                                  </td>
                                  <td className="px-3 py-2 text-right font-mono font-medium text-gray-900">
                                    {formatINR(inv.amount)}
                                  </td>
                                  <td className="px-3 py-2 text-gray-500 truncate max-w-[200px]" title={inv.decision_next || inv.decision_what || "Missing in 2B"}>
                                    {inv.decision_next || inv.decision_what || "Missing in 2B"}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* Contact & Dispatch Action Bar */}
                    <div className="p-4 bg-white space-y-3">
                      {/* Contact Info Inputs */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                        <div className="flex items-center gap-1.5">
                          <span className="text-gray-400">
                            <Phone className="h-3.5 w-3.5" />
                          </span>
                          <input
                            type="text"
                            placeholder="WhatsApp / Mobile (+91...)"
                            value={group.phone}
                            onChange={(e) =>
                              handleContactChange(group.supplierGstin, "phone", e.target.value)
                            }
                            className="w-full rounded-md border border-gray-200 px-2.5 py-1 text-xs placeholder:text-gray-400 focus:border-black focus:outline-hidden"
                          />
                        </div>

                        <div className="flex items-center gap-1.5">
                          <span className="text-gray-400">
                            <Mail className="h-3.5 w-3.5" />
                          </span>
                          <input
                            type="email"
                            placeholder="Vendor Email Address"
                            value={group.email}
                            onChange={(e) =>
                              handleContactChange(group.supplierGstin, "email", e.target.value)
                            }
                            className="w-full rounded-md border border-gray-200 px-2.5 py-1 text-xs placeholder:text-gray-400 focus:border-black focus:outline-hidden"
                          />
                          {hasContactUnsaved && (
                            <button
                              type="button"
                              onClick={() => handleSaveContact(group.supplierGstin)}
                              disabled={group.isSavingContact}
                              className="inline-flex items-center gap-1 rounded-md bg-gray-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-black disabled:opacity-50"
                              title="Save contact info"
                            >
                              {group.isSavingContact ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Save className="h-3 w-3" />
                              )}
                              <span>Save</span>
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Dispatch Action Buttons */}
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        {/* 1. WhatsApp Button */}
                        <button
                          type="button"
                          disabled={group.isDispatching}
                          onClick={() => handleSendWhatsApp(group.supplierGstin)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-100 hover:border-emerald-400 disabled:opacity-50 transition shadow-xs"
                          title="Open WhatsApp with pre-filled missing invoices text"
                        >
                          <MessageSquare className="h-3.5 w-3.5 text-emerald-600" />
                          <span>WhatsApp</span>
                        </button>

                        {/* 2. Email Notice Button */}
                        <button
                          type="button"
                          disabled={group.isDispatching}
                          onClick={() => handleOpenEmailNotice(group.supplierGstin)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-800 hover:bg-blue-100 hover:border-blue-300 disabled:opacity-50 transition shadow-xs"
                          title="Generate and preview formal email notice"
                        >
                          <Mail className="h-3.5 w-3.5 text-blue-600" />
                          <span>Email Notice</span>
                        </button>

                        {/* 3. Magic Portal Link Button */}
                        <button
                          type="button"
                          disabled={group.isDispatching}
                          onClick={() => handleCopyPortalLink(group.supplierGstin)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-800 hover:bg-indigo-100 hover:border-indigo-300 disabled:opacity-50 transition shadow-xs"
                          title="Generate /v/[token] self-service portal link for supplier"
                        >
                          <ExternalLink className="h-3.5 w-3.5 text-indigo-600" />
                          <span>Copy Magic Link</span>
                        </button>

                        {/* 4. PDF Letter Download */}
                        <button
                          type="button"
                          onClick={() => handleDownloadPdfLetter(group.supplierGstin)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50 transition"
                          title="Download formal printable PDF follow-up letter"
                        >
                          <Download className="h-3.5 w-3.5 text-gray-500" />
                          <span>PDF Letter</span>
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Drawer Footer */}
          <div className="border-t border-gray-200 bg-[#FAFAFA] px-6 py-3 flex items-center justify-between">
            <span className="text-xs text-gray-500">
              {totalSuppliers} supplier{totalSuppliers !== 1 ? "s" : ""} selected for follow-up
            </span>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-gray-300 bg-white px-4 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              Done
            </button>
          </div>
        </div>
      </div>

      {/* Email Notice Modal Preview */}
      {emailModal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl flex flex-col max-h-[85vh]">
            <div className="flex items-center justify-between border-b border-gray-200 pb-3 mb-4">
              <div>
                <h3 className="text-base font-bold text-gray-900">
                  Email Notice Preview — {emailModal.supplierName}
                </h3>
                <p className="text-xs text-gray-500 font-mono">{emailModal.supplierGstin}</p>
              </div>
              <button
                onClick={() => setEmailModal(null)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mb-3 space-y-1.5">
              <label className="text-xs font-bold text-gray-700">Subject:</label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={emailModal.subject}
                  className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-800"
                />
                <button
                  type="button"
                  onClick={async () => {
                    await navigator.clipboard.writeText(emailModal.subject);
                    toast("Subject copied to clipboard!", "success");
                  }}
                  className="rounded-lg border border-gray-200 p-2 text-gray-600 hover:bg-gray-100"
                  title="Copy subject"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-4 mb-4">
              <div
                className="text-xs text-gray-800 leading-relaxed font-sans"
                dangerouslySetInnerHTML={{ __html: emailModal.htmlBody }}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-gray-100">
              <div className="text-xs text-gray-500">
                {emailModal.portalUrl ? "Includes tokenized self-service portal link." : ""}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={async () => {
                    await navigator.clipboard.writeText(
                      `${emailModal.subject}\n\n${emailModal.htmlBody.replace(/<[^>]*>?/gm, "")}`
                    );
                    toast("Plain text notice copied to clipboard!", "success");
                  }}
                  className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                >
                  Copy Text
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    await navigator.clipboard.writeText(emailModal.htmlBody);
                    toast("HTML notice copied to clipboard!", "success");
                  }}
                  className="rounded-lg bg-gray-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-black"
                >
                  Copy HTML
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
