"use client";

import { useEffect, useState } from "react";
import {
  ShieldCheck,
  CheckCircle2,
  Clock,
  AlertTriangle,
  FileText,
  UploadCloud,
  ChevronRight,
  ExternalLink,
  Printer,
  XCircle,
  Loader2,
  FileCheck,
  Building2,
  Hash,
  HelpCircle,
} from "lucide-react";

import { Logo } from "@/components/ui/Logo";
import { formatINR } from "@/lib/format";
import {
  fetchVendorPortalData,
  submitVendorPortalResponse,
  uploadVendorPortalFile,
  type VendorPortalInfo,
  type VendorPortalInvoice,
} from "@/lib/vendorFollowupApi";

type ResponseAction = "ALREADY_FILED" | "PROMISED_NEXT_CYCLE" | "DISPUTED";

// Standard GSTN 18-character ARN regex: AA + 2 digit state code + 14 alphanumeric
const ARN_REGEX = /^AA[0-9]{2}[A-Za-z0-9]{14}$/;

export default function VendorResponsePortalClient({ token }: { token: string }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [portalData, setPortalData] = useState<VendorPortalInfo | null>(null);

  // Form state
  const [selectedAction, setSelectedAction] = useState<ResponseAction>("ALREADY_FILED");
  const [arnNumber, setArnNumber] = useState("");
  const [filingPeriod, setFilingPeriod] = useState("August 2026");
  const [promisedPeriod, setPromisedPeriod] = useState("September 2026");
  const [disputeReason, setDisputeReason] = useState("");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadKey, setUploadKey] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Submission result state
  const [submissionSuccess, setSubmissionSuccess] = useState(false);
  const [submissionResult, setSubmissionResult] = useState<{
    referenceId: string;
    token?: string;
    respondedAt: string;
    action: string;
    arn?: string | null;
    period?: string | null;
    disputeReason?: string | null;
    attachmentFilename?: string | null;
    attachmentKey?: string | null;
  } | null>(null);

  useEffect(() => {
    if (!token) return;
    loadPortalData();
  }, [token]);

  const loadPortalData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchVendorPortalData(token);
      setPortalData(data);
      if (data.status === "FILING_CONFIRMED" || data.status === "PROMISED_NEXT_CYCLE" || data.status === "DISPUTED") {
        setSubmissionSuccess(true);
        setSubmissionResult({
          referenceId: data.id,
          token: data.token || token,
          respondedAt: data.responded_at || new Date().toISOString(),
          action: data.response_action || data.status,
          arn: data.arn_number,
          period: data.promised_period,
          disputeReason: data.dispute_reason,
          attachmentKey: data.attachment_key,
        });
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load vendor clarification portal.");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 10 * 1024 * 1024) {
      alert("File size exceeds 10 MB limit.");
      return;
    }

    setUploadedFile(file);
    setIsUploading(true);
    try {
      const res = await uploadVendorPortalFile(token, file);
      setUploadKey(res.attachment_key);
    } catch (err: any) {
      alert(err?.message || "File upload failed. You can still submit without an attachment.");
    } finally {
      setIsUploading(false);
    }
  };

  const isArnValid = ARN_REGEX.test(arnNumber.trim().toUpperCase());

  const canSubmit = () => {
    if (isSubmitting) return false;
    if (selectedAction === "ALREADY_FILED") {
      return isArnValid && filingPeriod.trim().length > 0;
    }
    if (selectedAction === "PROMISED_NEXT_CYCLE") {
      return promisedPeriod.trim().length > 0;
    }
    if (selectedAction === "DISPUTED") {
      return disputeReason.trim().length >= 5;
    }
    return false;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit()) return;

    setIsSubmitting(true);
    try {
      const payload: {
        action: ResponseAction;
        arn_number?: string;
        promised_period?: string;
        dispute_reason?: string;
        attachment_key?: string;
      } = {
        action: selectedAction,
        attachment_key: uploadKey || undefined,
      };

      if (selectedAction === "ALREADY_FILED") {
        payload.arn_number = arnNumber.trim().toUpperCase();
        payload.promised_period = filingPeriod;
      } else if (selectedAction === "PROMISED_NEXT_CYCLE") {
        payload.promised_period = promisedPeriod;
      } else if (selectedAction === "DISPUTED") {
        payload.dispute_reason = disputeReason.trim();
      }

      const res = await submitVendorPortalResponse(token, payload);
      setSubmissionSuccess(true);
      setSubmissionResult({
        referenceId: res.reference_id,
        token: res.token || token,
        respondedAt: res.responded_at,
        action: res.response_action,
        arn: res.arn_number,
        period: res.promised_period,
        disputeReason: res.dispute_reason || (selectedAction === "DISPUTED" ? disputeReason.trim() : undefined),
        attachmentFilename: uploadedFile?.name,
        attachmentKey: res.attachment_key,
      });
    } catch (err: any) {
      alert(err?.message || "Failed to submit response. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
        <p className="mt-4 text-sm font-semibold text-gray-600">Verifying secure vendor link...</p>
      </div>
    );
  }

  if (error || !portalData) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4 py-12">
        <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-lg">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-50 text-amber-600">
            <AlertTriangle className="h-8 w-8" />
          </div>
          <h2 className="mt-4 text-xl font-bold text-gray-900">Link Unavailable or Expired</h2>
          <p className="mt-2 text-sm text-gray-600">
            {error || "This vendor follow-up link is no longer active. Verification links are valid for 45 days."}
          </p>
          <div className="mt-6 border-t border-gray-100 pt-4">
            <p className="text-xs text-gray-500">
              Please contact your customer&#39;s finance desk to request an updated verification link.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 antialiased selection:bg-indigo-500 selection:text-white pb-16">
      {/* Top Banner Navigation */}
      <header className="border-b border-gray-200 bg-white px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <div className="flex items-center gap-3">
            <Logo height={24} />
            <span className="hidden sm:inline-block text-xs font-semibold uppercase tracking-wider text-gray-400">
              | GST Reconciliation &amp; ITC Desk
            </span>
          </div>
          <div className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">
            <ShieldCheck className="h-4 w-4" />
            <span>Secure 256-bit Encrypted</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 pt-8 sm:px-6">
        {/* Buyer & Supplier Context Header Card */}
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-100 pb-5">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-indigo-600">
                Statutory Clarification Request
              </span>
              <h1 className="mt-1 text-2xl font-extrabold text-gray-900">
                GST Invoice Reconciliation
              </h1>
              <p className="mt-1 text-sm text-gray-600">
                Clarification requested by{" "}
                <strong className="text-gray-900">{portalData.client_name}</strong> regarding
                unmatched GSTR-2B or Rule 37 compliance.
              </p>
            </div>

            <div className="rounded-xl bg-red-50 px-4 py-3 text-right">
              <span className="text-xs font-bold uppercase tracking-wider text-red-600">
                At-Risk Input Tax Credit
              </span>
              <p className="text-2xl font-extrabold text-red-700">
                {formatINR(portalData.at_risk_itc_rupees)}
              </p>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="rounded-xl bg-gray-50 p-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                Buyer (Client)
              </span>
              <p className="mt-1 font-bold text-gray-900">{portalData.client_name}</p>
              <p className="mt-0.5 font-mono text-xs font-semibold text-gray-600">
                GSTIN: {portalData.client_gstin || "—"}
              </p>
            </div>

            <div className="rounded-xl bg-gray-50 p-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                Supplier (You)
              </span>
              <p className="mt-1 font-bold text-gray-900">{portalData.supplier_name}</p>
              <p className="mt-0.5 font-mono text-xs font-semibold text-gray-600">
                GSTIN: {portalData.supplier_gstin}
              </p>
            </div>
          </div>
        </div>

        {/* Section: Pending Invoices Table */}
        <div className="mt-6 rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="border-b border-gray-200 bg-gray-50/70 px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-indigo-600" />
              <h2 className="text-base font-bold text-gray-900">
                Flagged Invoices ({portalData.invoices.length})
              </h2>
            </div>
            <span className="text-xs text-gray-500">
              Booked in Buyer&#39;s Purchase Register
            </span>
          </div>

          {portalData.invoices.length === 0 ? (
            <div className="p-8 text-center text-sm text-gray-500">
              Consolidated pending ITC compliance review for supplier {portalData.supplier_gstin}.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-gray-600">
                <thead className="bg-gray-50 text-xs font-bold uppercase text-gray-500">
                  <tr>
                    <th className="px-6 py-3">Invoice Number</th>
                    <th className="px-6 py-3">Invoice Date</th>
                    <th className="px-6 py-3">Taxable Value</th>
                    <th className="px-6 py-3">Tax / ITC Amount</th>
                    <th className="px-6 py-3">Status / Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {portalData.invoices.map((inv, idx) => (
                    <tr key={idx} className="hover:bg-gray-50/80">
                      <td className="px-6 py-3.5 font-mono font-bold text-gray-900">
                        {inv.invoice_number}
                      </td>
                      <td className="px-6 py-3.5 text-xs text-gray-600">
                        {inv.invoice_date || "—"}
                      </td>
                      <td className="px-6 py-3.5 font-medium text-gray-900">
                        {formatINR(inv.taxable_value)}
                      </td>
                      <td className="px-6 py-3.5 font-bold text-red-600">
                        {formatINR(inv.tax_amount)}
                      </td>
                      <td className="px-6 py-3.5">
                        <span className="inline-flex items-center rounded-md bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800 border border-amber-200">
                          {inv.reason}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* State A: Submission Success / Already Responded */}
        {submissionSuccess && submissionResult && (
          <div className="mt-8 rounded-2xl border border-emerald-300 bg-white p-6 sm:p-8 shadow-md">
            <div className="flex items-start justify-between gap-4 border-b border-gray-200 pb-5">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-600 text-white shadow-md">
                  <CheckCircle2 className="h-7 w-7" />
                </div>
                <div>
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-0.5 text-xs font-bold text-emerald-800">
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Statutory Acknowledgment Certificate
                  </span>
                  <h3 className="mt-1.5 text-xl font-extrabold text-gray-900">
                    Vendor Response Recorded &amp; Certified
                  </h3>
                  <p className="mt-1 text-xs sm:text-sm text-gray-600">
                    This formal electronic response has been recorded into the GST compliance audit trail for{" "}
                    <strong>{portalData.client_name}</strong>.
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => window.print()}
                className="hidden sm:inline-flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-xs font-bold text-gray-700 shadow-sm hover:bg-gray-50 transition print:hidden"
              >
                <Printer className="h-4 w-4 text-gray-500" />
                Print / Save PDF
              </button>
            </div>

            {/* Certificate Body */}
            <div className="mt-6 space-y-5">
              {/* Reference & Timestamp Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 rounded-xl bg-slate-50 p-4 border border-slate-200 text-xs">
                <div>
                  <span className="font-semibold text-gray-500 uppercase tracking-wider block text-[11px]">
                    Reference ID
                  </span>
                  <span className="font-mono font-bold text-gray-800 break-all">
                    {submissionResult.referenceId}
                  </span>
                </div>
                <div>
                  <span className="font-semibold text-gray-500 uppercase tracking-wider block text-[11px]">
                    Security Token
                  </span>
                  <span className="font-mono font-bold text-indigo-700 break-all">
                    {submissionResult.token || token}
                  </span>
                </div>
                <div>
                  <span className="font-semibold text-gray-500 uppercase tracking-wider block text-[11px]">
                    Recorded Timestamp
                  </span>
                  <span className="font-semibold text-gray-800">
                    {new Date(submissionResult.respondedAt).toLocaleString("en-IN", {
                      dateStyle: "medium",
                      timeStyle: "medium",
                    })}
                  </span>
                </div>
              </div>

              {/* Resolution Action Summary */}
              <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
                <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                  <span className="text-xs font-bold uppercase tracking-wider text-gray-500">
                    Selected Resolution
                  </span>
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-extrabold ${
                      submissionResult.action === "ALREADY_FILED"
                        ? "bg-emerald-100 text-emerald-800"
                        : submissionResult.action === "PROMISED_NEXT_CYCLE"
                        ? "bg-amber-100 text-amber-800"
                        : "bg-rose-100 text-rose-800"
                    }`}
                  >
                    {submissionResult.action === "ALREADY_FILED"
                      ? "✓ Already Filed in GSTR-1"
                      : submissionResult.action === "PROMISED_NEXT_CYCLE"
                      ? "⏳ Will File in Next Return Cycle"
                      : "✕ Invoice Canceled / Not Ours"}
                  </span>
                </div>

                {/* Submissions Detail */}
                {submissionResult.action === "ALREADY_FILED" && (
                  <div className="rounded-xl bg-emerald-50/60 p-4 border border-emerald-200 space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-xs font-bold text-emerald-900 uppercase">
                        GSTN Application Reference Number (ARN)
                      </span>
                      <span className="text-[11px] font-semibold text-emerald-700">
                        18-Character Verified
                      </span>
                    </div>
                    <div className="font-mono text-base font-extrabold text-emerald-900 bg-white px-3.5 py-2 rounded-lg border border-emerald-300 tracking-wider">
                      {submissionResult.arn || "ARN Recorded"}
                    </div>
                    <p className="text-xs text-emerald-800">
                      The supplier has legally affirmed that these invoices were included under the verified ARN above.
                    </p>
                  </div>
                )}

                {submissionResult.action === "PROMISED_NEXT_CYCLE" && (
                  <div className="rounded-xl bg-amber-50/60 p-4 border border-amber-200 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-amber-900 uppercase">
                        Committed Return Cycle
                      </span>
                      <span className="text-[11px] font-semibold text-amber-700">
                        Scheduled for Tracking
                      </span>
                    </div>
                    <div className="text-base font-extrabold text-amber-950 bg-white px-3.5 py-2 rounded-lg border border-amber-300">
                      {submissionResult.period || "Next Return Cycle"}
                    </div>
                    <p className="text-xs text-amber-800">
                      The supplier has formally undertaken to file and reflect these invoices in GSTR-1 by the statutory deadline for the cycle indicated.
                    </p>
                  </div>
                )}

                {submissionResult.action === "DISPUTED" && (
                  <div className="rounded-xl bg-rose-50/60 p-4 border border-rose-200 space-y-2">
                    <span className="text-xs font-bold text-rose-900 uppercase">
                      Supplier Dispute Statement (Verbatim)
                    </span>
                    <blockquote className="italic text-sm text-rose-950 bg-white px-4 py-3 rounded-lg border border-rose-300">
                      &ldquo;{submissionResult.disputeReason || "Invoice canceled / goods rejected / not recognized."}&rdquo;
                    </blockquote>
                    <p className="text-xs text-rose-800">
                      This formal statement serves as supplier declaration that the transaction is disputed, allowing the buyer to review purchase register entries.
                    </p>
                  </div>
                )}

                {/* Attachment note */}
                {(submissionResult.attachmentFilename || submissionResult.attachmentKey) && (
                  <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3.5 py-2 border border-gray-200 text-xs text-gray-700">
                    <FileText className="h-4 w-4 text-indigo-600 shrink-0" />
                    <span>Attached Document:</span>
                    <strong className="font-mono text-gray-900">
                      {submissionResult.attachmentFilename || submissionResult.attachmentKey}
                    </strong>
                    <span className="text-emerald-700 font-semibold">(Uploaded &amp; Archived)</span>
                  </div>
                )}
              </div>

              {/* Covered Scope */}
              <div className="rounded-xl border border-gray-200 bg-slate-50/70 p-4 text-xs space-y-2">
                <div className="flex justify-between items-center font-bold text-gray-800">
                  <span>Scope of Acknowledgment:</span>
                  <span>{portalData.invoices.length} Invoice(s) — Total ITC {formatINR(portalData.at_risk_itc_rupees)}</span>
                </div>
                <div className="text-gray-600">
                  Buyer: <strong>{portalData.client_name}</strong> ({portalData.client_gstin || "—"}) | Supplier: <strong>{portalData.supplier_name}</strong> ({portalData.supplier_gstin})
                </div>
              </div>

              {/* Statutory Non-Repudiation Footer */}
              <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 p-4 text-xs text-indigo-900 space-y-1">
                <div className="flex items-center gap-1.5 font-bold">
                  <ShieldCheck className="h-4 w-4 text-indigo-700 shrink-0" />
                  <span>Statutory Non-Repudiation Notice</span>
                </div>
                <p className="text-[11px] leading-relaxed text-indigo-800">
                  This electronic acknowledgment was generated upon verified submission and constitutes supplier communication under Section 16(2)(c) and Rule 37 of the Central Goods and Services Tax (CGST) Act, 2017. Both buyer and supplier may produce this certificate as evidence during GST audit, scrutiny, or show-cause notice proceedings.
                </p>
              </div>

              {/* Print Button (Mobile & Desktop) */}
              <div className="pt-2 flex justify-end print:hidden">
                <button
                  type="button"
                  onClick={() => window.print()}
                  className="inline-flex items-center gap-2 rounded-xl bg-gray-900 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-black transition"
                >
                  <Printer className="h-4 w-4" />
                  Print / Save Acknowledgment (PDF)
                </button>
              </div>
            </div>
          </div>
        )}

        {/* State B: Active Response Form */}
        {!submissionSuccess && (
          <form onSubmit={handleSubmit} className="mt-8 space-y-6">
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <h2 className="text-base font-bold text-gray-900">
                Select Resolution Status
              </h2>
              <p className="mt-1 text-xs text-gray-500">
                Please indicate the correct status for these invoices so your customer can claim ITC
                without tax liability notices.
              </p>

              {/* 3 Radio Card Options */}
              <div className="mt-5 space-y-3.5">
                {/* Option 1: Already Filed */}
                <label
                  onClick={() => setSelectedAction("ALREADY_FILED")}
                  className={`block cursor-pointer rounded-2xl border p-4 transition ${
                    selectedAction === "ALREADY_FILED"
                      ? "border-indigo-600 bg-indigo-50/40 ring-2 ring-indigo-600/20"
                      : "border-gray-200 hover:border-gray-300 bg-white"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="radio"
                      name="responseAction"
                      checked={selectedAction === "ALREADY_FILED"}
                      onChange={() => setSelectedAction("ALREADY_FILED")}
                      className="mt-1 h-4 w-4 text-indigo-600 focus:ring-indigo-500"
                    />
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-bold text-gray-900">
                          ✓ Already Filed in GSTR-1
                        </span>
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-800">
                          Recommended
                        </span>
                      </div>
                      <p className="mt-0.5 text-xs text-gray-500">
                        Invoices have been furnished in our GSTR-1 return.
                      </p>

                      {selectedAction === "ALREADY_FILED" && (
                        <div className="mt-4 space-y-3 rounded-xl border border-indigo-100 bg-white p-4">
                          <div>
                            <div className="flex items-center justify-between">
                              <label className="text-xs font-bold text-gray-700">
                                18-Character Filing ARN <span className="text-red-500">*</span>
                              </label>
                              {arnNumber && (
                                <span
                                  className={`text-xs font-semibold ${
                                    isArnValid ? "text-emerald-600" : "text-amber-600"
                                  }`}
                                >
                                  {isArnValid
                                    ? "✓ Valid 18-character ARN"
                                    : `${arnNumber.length}/18 chars`}
                                </span>
                              )}
                            </div>
                            <input
                              type="text"
                              maxLength={18}
                              placeholder="e.g. AA2708260012345678"
                              value={arnNumber}
                              onChange={(e) => setArnNumber(e.target.value.toUpperCase())}
                              className="mt-1.5 w-full rounded-lg border border-gray-300 px-3.5 py-2 font-mono text-sm font-bold uppercase tracking-wider text-gray-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                            />
                            <p className="mt-1 text-xs text-gray-500">
                              Standard GSTN format: AA followed by 2-digit state code and 14 alphanumerics.
                            </p>
                          </div>

                          <div>
                            <label className="text-xs font-bold text-gray-700">
                              Return Filing Period
                            </label>
                            <select
                              value={filingPeriod}
                              onChange={(e) => setFilingPeriod(e.target.value)}
                              className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-gray-800 focus:border-indigo-500"
                            >
                              <option value="August 2026">August 2026</option>
                              <option value="July 2026">July 2026</option>
                              <option value="June 2026">June 2026</option>
                              <option value="May 2026">May 2026</option>
                              <option value="Earlier Cycle">Earlier Return Cycle</option>
                            </select>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </label>

                {/* Option 2: Will File in Next Return */}
                <label
                  onClick={() => setSelectedAction("PROMISED_NEXT_CYCLE")}
                  className={`block cursor-pointer rounded-2xl border p-4 transition ${
                    selectedAction === "PROMISED_NEXT_CYCLE"
                      ? "border-indigo-600 bg-indigo-50/40 ring-2 ring-indigo-600/20"
                      : "border-gray-200 hover:border-gray-300 bg-white"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="radio"
                      name="responseAction"
                      checked={selectedAction === "PROMISED_NEXT_CYCLE"}
                      onChange={() => setSelectedAction("PROMISED_NEXT_CYCLE")}
                      className="mt-1 h-4 w-4 text-indigo-600 focus:ring-indigo-500"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-bold text-gray-900">
                        ⏳ Will File in Upcoming Return Cycle
                      </span>
                      <p className="mt-0.5 text-xs text-gray-500">
                        Invoices missed GSTR-1 cut-off; scheduled for inclusion in upcoming return.
                      </p>

                      {selectedAction === "PROMISED_NEXT_CYCLE" && (
                        <div className="mt-4 rounded-xl border border-indigo-100 bg-white p-4">
                          <label className="text-xs font-bold text-gray-700">
                            Target Filing Cycle <span className="text-red-500">*</span>
                          </label>
                          <select
                            value={promisedPeriod}
                            onChange={(e) => setPromisedPeriod(e.target.value)}
                            className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-gray-800 focus:border-indigo-500"
                          >
                            <option value="September 2026">September 2026</option>
                            <option value="October 2026">October 2026</option>
                            <option value="November 2026">November 2026</option>
                            <option value="December 2026">December 2026</option>
                          </select>
                          <p className="mt-2 text-xs text-indigo-700 bg-indigo-50 p-2.5 rounded-lg">
                            ℹ️ The buyer will hold payment escalation until this cycle and expect invoices in their GSTR-2B.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </label>

                {/* Option 3: Invoice Canceled / Not Ours */}
                <label
                  onClick={() => setSelectedAction("DISPUTED")}
                  className={`block cursor-pointer rounded-2xl border p-4 transition ${
                    selectedAction === "DISPUTED"
                      ? "border-red-600 bg-red-50/30 ring-2 ring-red-600/20"
                      : "border-gray-200 hover:border-gray-300 bg-white"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="radio"
                      name="responseAction"
                      checked={selectedAction === "DISPUTED"}
                      onChange={() => setSelectedAction("DISPUTED")}
                      className="mt-1 h-4 w-4 text-red-600 focus:ring-red-500"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-bold text-gray-900">
                        ✕ Invoice Canceled / Not Ours
                      </span>
                      <p className="mt-0.5 text-xs text-gray-500">
                        Invoice is disputed, cancelled prior to dispatch, or erroneously attributed.
                      </p>

                      {selectedAction === "DISPUTED" && (
                        <div className="mt-4 rounded-xl border border-red-100 bg-white p-4">
                          <label className="text-xs font-bold text-gray-700">
                            Reason for Dispute <span className="text-red-500">*</span>
                          </label>
                          <textarea
                            rows={3}
                            placeholder="e.g. Order was cancelled before delivery; or duplicate invoice number entered in buyer's ERP..."
                            value={disputeReason}
                            onChange={(e) => setDisputeReason(e.target.value)}
                            className="mt-1.5 w-full rounded-lg border border-gray-300 p-2.5 text-xs text-gray-900 focus:border-red-500 focus:ring-1 focus:ring-red-500"
                          />
                          <p className="mt-1 text-xs text-gray-500">
                            Please explain clearly so the buyer&#39;s audit team can remove or adjust the record.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </label>
              </div>

              {/* Optional File Attachment */}
              <div className="mt-6 border-t border-gray-100 pt-5">
                <label className="text-xs font-bold text-gray-700 block">
                  Upload Invoice or Credit Note Copy (Optional)
                </label>
                <div className="mt-2 flex items-center gap-3">
                  <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-2.5 text-xs font-semibold text-gray-700 hover:bg-gray-100 transition">
                    {isUploading ? (
                      <Loader2 className="h-4 w-4 animate-spin text-indigo-600" />
                    ) : (
                      <UploadCloud className="h-4 w-4 text-gray-500" />
                    )}
                    <span>{uploadedFile ? uploadedFile.name : "Choose PDF / Image (Max 10 MB)"}</span>
                    <input
                      type="file"
                      accept=".pdf,image/png,image/jpeg"
                      onChange={handleFileUpload}
                      className="hidden"
                    />
                  </label>
                  {uploadKey && (
                    <span className="text-xs font-semibold text-emerald-600">
                      ✓ Attached successfully
                    </span>
                  )}
                </div>
              </div>

              {/* Submit Button */}
              <div className="mt-8 border-t border-gray-100 pt-5 flex items-center justify-between">
                <span className="text-xs text-gray-500">
                  {selectedAction === "ALREADY_FILED" && !isArnValid && (
                    <span className="text-amber-600 font-medium">
                      Enter a valid 18-character ARN to proceed
                    </span>
                  )}
                </span>

                <button
                  type="submit"
                  disabled={!canSubmit()}
                  className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 text-sm font-bold text-white shadow-md transition hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Submitting Response...</span>
                    </>
                  ) : (
                    <>
                      <span>Confirm &amp; Submit Response</span>
                      <ChevronRight className="h-4 w-4" />
                    </>
                  )}
                </button>
              </div>
            </div>
          </form>
        )}

        {/* Statutory Compliance Footer (Mandatory Legal Disclosure) */}
        <footer className="mt-12 text-center text-xs text-gray-500 space-y-2 border-t border-gray-200 pt-6">
          <p className="font-semibold text-gray-600">
            Access time recorded for GST reconciliation documentation under CGST Act, 2017.
          </p>
          <p>
            DPDP Act 2023 Compliant: No personal browsing data or device IP addresses are stored.
          </p>
          <p className="text-gray-400">
            Powered by ReconDesk Automated Tax &amp; ITC Reconciliation Platform
          </p>
        </footer>
      </main>
    </div>
  );
}
