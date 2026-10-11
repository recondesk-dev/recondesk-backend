"use client";

import React, { useEffect, useState, use } from "react";
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Fingerprint,
  Calendar,
  Building2,
  FileText,
  UserCheck,
  Loader2,
  Lock,
  ArrowRight,
  Send,
  HelpCircle,
  Info,
} from "lucide-react";
import {
  publicClientReviewApi,
  type ClientPublicReviewData,
} from "@/lib/api";

interface PageProps {
  params: Promise<{
    token: string;
  }>;
}

export default function ClientAuthorizePage({ params }: PageProps) {
  const resolvedParams = use(params);
  const rawToken = resolvedParams.token;

  const [review, setReview] = useState<ClientPublicReviewData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Authorize Form Modal
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false);
  const [signatoryName, setSignatoryName] = useState<string>("");
  const [signatoryDesignation, setSignatoryDesignation] = useState<string>("Director");
  const [signatoryContact, setSignatoryContact] = useState<string>("");
  const [consentAffirmed, setConsentAffirmed] = useState<boolean>(false);

  // Reject Form Modal
  const [showRejectModal, setShowRejectModal] = useState<boolean>(false);
  const [rejectionReason, setRejectionReason] = useState<string>("");

  useEffect(() => {
    if (!rawToken) return;
    async function loadReview() {
      try {
        setLoading(true);
        setError(null);
        const data = await publicClientReviewApi.getReview(rawToken);
        setReview(data);
      } catch (err: any) {
        setError(
          err?.message ||
            "Unable to access return review portal. The link may have expired or been revoked."
        );
      } finally {
        setLoading(false);
      }
    }
    loadReview();
  }, [rawToken]);

  const handleAuthorize = async () => {
    if (!rawToken || !signatoryName.trim() || !signatoryDesignation.trim() || !signatoryContact.trim() || !consentAffirmed) {
      return;
    }
    try {
      setActionLoading(true);
      setError(null);
      const res = await publicClientReviewApi.authorize(rawToken, {
        signatory_name: signatoryName.trim(),
        signatory_designation: signatoryDesignation.trim(),
        signatory_contact: signatoryContact.trim(),
        expected_figures_digest: review?.figures_digest,
      });
      setReview(res);
      setShowAuthModal(false);
    } catch (err: any) {
      setError(err?.message || "Failed to submit authorization.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!rawToken || !rejectionReason.trim()) return;
    try {
      setActionLoading(true);
      setError(null);
      const res = await publicClientReviewApi.reject(rawToken, {
        rejection_reason: rejectionReason.trim(),
        signatory_name: signatoryName.trim() || undefined,
      });
      setReview(res);
      setShowRejectModal(false);
    } catch (err: any) {
      setError(err?.message || "Failed to submit return rejection.");
    } finally {
      setActionLoading(false);
    }
  };

  const formatCurrency = (val: any) => {
    const num = Number(val || 0);
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 2,
    }).format(num);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col items-center justify-center p-4">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
          <p className="text-sm font-medium text-slate-600 dark:text-slate-400">
            Verifying cryptographic token and fetching return summaries...
          </p>
        </div>
      </div>
    );
  }

  if (error && !review) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col items-center justify-center p-4">
        <div className="max-w-md w-full bg-card border border-border rounded-2xl p-6 text-center space-y-4 shadow-lg">
          <div className="mx-auto w-12 h-12 rounded-full bg-rose-100 dark:bg-rose-950/60 flex items-center justify-center text-rose-600 dark:text-rose-400">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <h2 className="text-lg font-semibold text-foreground">Authorization Link Unavailable</h2>
          <p className="text-xs text-muted-foreground leading-relaxed">{error}</p>
          <div className="pt-2">
            <p className="text-[11px] text-muted-foreground">
              Please contact your Chartered Accountant firm to generate a new return review link.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const figures: Record<string, any> = (review?.figures_summary as Record<string, any>) || {};
  const isGstr1 = review?.return_type === "GSTR-1";
  const isGstr3b = review?.return_type === "GSTR-3B";

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-foreground py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Top Branding Header */}
        <header className="flex items-center justify-between border-b border-border pb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center text-primary-foreground font-bold text-lg shadow-sm">
              RD
            </div>
            <div>
              <h1 className="font-bold text-lg leading-tight">ReconDesk Client Portal</h1>
              <p className="text-xs text-muted-foreground">GST Return Review & Client Filing Authorization</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300 text-xs font-medium">
            <Lock className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">256-Bit Cryptographically Sealed</span>
            <span className="sm:hidden">Sealed</span>
          </div>
        </header>

        {error && (
          <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* GSTIN & Period Overview Card */}
        <section className="bg-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <span className="text-[11px] uppercase tracking-wider font-semibold text-muted-foreground">
                Taxpayer GSTIN
              </span>
              <div className="flex items-center gap-2">
                <Building2 className="w-4 h-4 text-muted-foreground" />
                <span className="text-lg font-mono font-bold tracking-tight text-foreground">
                  {review?.gstin}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="text-right">
                <span className="text-[11px] uppercase tracking-wider font-semibold text-muted-foreground">
                  Return Type
                </span>
                <p className="text-base font-bold text-primary">{review?.return_type}</p>
              </div>
              <div className="h-8 w-px bg-border mx-1" />
              <div className="text-left">
                <span className="text-[11px] uppercase tracking-wider font-semibold text-muted-foreground">
                  Filing Period
                </span>
                <div className="flex items-center gap-1.5 text-base font-bold text-foreground">
                  <Calendar className="w-4 h-4 text-muted-foreground" />
                  <span>{review?.period}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Cryptographic SHA-256 fingerprint */}
          {review?.figures_digest && (
            <div className="pt-2 border-t border-border flex items-center gap-2 text-xs font-mono text-muted-foreground overflow-x-auto">
              <Fingerprint className="w-4 h-4 text-primary shrink-0" />
              <span className="truncate">Figures Hash: {review.figures_digest}</span>
            </div>
          )}
        </section>

        {/* Status Receipt Banners */}
        {review?.status === "AUTHORIZED" && (
          <div className="bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-2xl p-6 text-emerald-950 dark:text-emerald-100 shadow-sm space-y-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/60 flex items-center justify-center text-emerald-600 dark:text-emerald-300">
                <CheckCircle2 className="w-6 h-6" />
              </div>
              <div>
                <h3 className="font-bold text-base">Filing Authorization Confirmed</h3>
                <p className="text-xs text-emerald-800 dark:text-emerald-300">
                  You have explicitly approved these return figures for GSTN submission.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs border-t border-emerald-200/60 dark:border-emerald-800/60">
              <div>
                <span className="text-emerald-700/80 dark:text-emerald-400">Signatory:</span>
                <p className="font-semibold text-emerald-950 dark:text-emerald-100 mt-0.5">
                  {review.signatory_name} <span className="text-[10px] text-emerald-700/90 font-normal">(Self-Declared)</span>
                </p>
              </div>
              <div>
                <span className="text-emerald-700/80 dark:text-emerald-400">Capacity / Role:</span>
                <p className="font-semibold text-emerald-950 dark:text-emerald-100 mt-0.5">
                  {review.signatory_designation}
                </p>
              </div>
              <div>
                <span className="text-emerald-700/80 dark:text-emerald-400">Authorized At:</span>
                <p className="font-semibold text-emerald-950 dark:text-emerald-100 mt-0.5">
                  {review.authorized_at ? new Date(review.authorized_at).toLocaleString("en-IN") : "Recorded"}
                </p>
              </div>
            </div>
          </div>
        )}

        {review?.status === "REJECTED" && (
          <div className="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 rounded-2xl p-5 text-rose-950 dark:text-rose-100 shadow-sm space-y-2">
            <div className="flex items-center gap-2 text-rose-700 dark:text-rose-300 font-bold">
              <XCircle className="w-5 h-5" />
              <h3>Return Figures Rejected by Client</h3>
            </div>
            <p className="text-xs text-rose-800 dark:text-rose-200">
              <strong>Rejection Reason:</strong> {review.rejection_reason}
            </p>
            {review.rejected_at && (
              <p className="text-[11px] text-rose-600 dark:text-rose-400">
                Recorded on {new Date(review.rejected_at).toLocaleString("en-IN")}
              </p>
            )}
          </div>
        )}

        {/* Figures Breakdown Summary */}
        <section className="bg-card border border-border rounded-2xl p-5 shadow-sm space-y-5">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <h3 className="font-semibold text-sm flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" />
              <span>Summary Figures for Your Review</span>
            </h3>
            <span className="text-xs text-muted-foreground">All amounts in INR (₹)</span>
          </div>

          {/* GSTR-1 View */}
          {isGstr1 && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="p-3.5 rounded-xl bg-muted/40 border border-border">
                  <span className="text-xs text-muted-foreground">Total Taxable Value</span>
                  <p className="text-lg font-bold text-foreground mt-1">
                    {formatCurrency(figures.total_taxable_value)}
                  </p>
                </div>
                <div className="p-3.5 rounded-xl bg-muted/40 border border-border">
                  <span className="text-xs text-muted-foreground">Total Tax Amount</span>
                  <p className="text-lg font-bold text-primary mt-1">
                    {formatCurrency(figures.total_tax)}
                  </p>
                </div>
                <div className="p-3.5 rounded-xl bg-muted/40 border border-border">
                  <span className="text-xs text-muted-foreground">Total Invoices</span>
                  <p className="text-lg font-bold text-foreground mt-1">
                    {figures.invoice_count || 0}
                  </p>
                </div>
              </div>

              {/* Tax Breakup */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-xs">
                <div className="p-2.5 rounded-lg border border-border bg-background">
                  <span className="text-muted-foreground">IGST</span>
                  <p className="font-semibold mt-0.5">{formatCurrency(figures.igst)}</p>
                </div>
                <div className="p-2.5 rounded-lg border border-border bg-background">
                  <span className="text-muted-foreground">CGST</span>
                  <p className="font-semibold mt-0.5">{formatCurrency(figures.cgst)}</p>
                </div>
                <div className="p-2.5 rounded-lg border border-border bg-background">
                  <span className="text-muted-foreground">SGST</span>
                  <p className="font-semibold mt-0.5">{formatCurrency(figures.sgst)}</p>
                </div>
                <div className="p-2.5 rounded-lg border border-border bg-background">
                  <span className="text-muted-foreground">Cess</span>
                  <p className="font-semibold mt-0.5">{formatCurrency(figures.cess)}</p>
                </div>
              </div>
            </div>
          )}

          {/* GSTR-3B View */}
          {isGstr3b && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="p-3.5 rounded-xl bg-muted/40 border border-border">
                  <span className="text-xs text-muted-foreground">Outward Taxable Value</span>
                  <p className="text-lg font-bold text-foreground mt-1">
                    {formatCurrency(figures.outward_taxable_value)}
                  </p>
                </div>
                <div className="p-3.5 rounded-xl bg-muted/40 border border-border">
                  <span className="text-xs text-muted-foreground">Outward Tax Liability</span>
                  <p className="text-lg font-bold text-foreground mt-1">
                    {formatCurrency(figures.outward_tax)}
                  </p>
                </div>
                <div className="p-3.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800">
                  <span className="text-xs text-emerald-800 dark:text-emerald-300">Eligible ITC Claimed</span>
                  <p className="text-lg font-bold text-emerald-600 dark:text-emerald-400 mt-1">
                    {formatCurrency(figures.eligible_itc)}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                <div className="p-3 rounded-xl border border-border bg-background space-y-1">
                  <span className="text-xs text-muted-foreground">Reverse Charge (RCM) Liability</span>
                  <p className="text-sm font-semibold text-foreground">
                    {formatCurrency(figures.rcm_tax)}
                  </p>
                </div>
                <div className="p-3 rounded-xl border border-border bg-background space-y-1">
                  <span className="text-xs text-muted-foreground">Net Tax Payable (Cash)</span>
                  <p className="text-sm font-bold text-primary">
                    {formatCurrency(figures.net_tax_payable)}
                  </p>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* Action Decision Area (Only when PENDING or VIEWED) */}
        {(review?.status === "PENDING" || review?.status === "VIEWED") && (
          <section className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-4">
            <div className="space-y-1">
              <h3 className="font-semibold text-base text-foreground">
                Authorize Filing or Request Revisions
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                As the authorized signatory for {review.gstin}, your explicit digital consent is required before the CA firm can proceed with GSTN filing.
              </p>
            </div>

            <div className="flex flex-col sm:flex-row items-center gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowAuthModal(true)}
                disabled={actionLoading}
                className="w-full sm:w-auto px-6 py-3 rounded-xl bg-emerald-600 text-white font-semibold text-sm hover:bg-emerald-700 shadow-sm flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>Approve & Authorize Filing</span>
              </button>

              <button
                type="button"
                onClick={() => setShowRejectModal(true)}
                disabled={actionLoading}
                className="w-full sm:w-auto px-5 py-3 rounded-xl border border-border bg-background text-rose-600 dark:text-rose-400 font-semibold text-sm hover:bg-rose-50 dark:hover:bg-rose-950/40 flex items-center justify-center gap-2 transition-colors"
              >
                <XCircle className="w-4 h-4" />
                <span>Reject & Request Corrections</span>
              </button>
            </div>
          </section>
        )}

        {/* Footer */}
        <footer className="text-center text-[11px] text-muted-foreground py-6 space-y-1">
          <p>ReconDesk GST Filing Governance Platform • Certified Audit Trail Engine</p>
          <p>All authorizations are cryptographically bound to exact figures digests and logged with immutable timestamps.</p>
        </footer>
      </div>

      {/* Authorize Modal Form */}
      {showAuthModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center gap-3 text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="w-6 h-6" />
              <h3 className="font-bold text-lg text-foreground">Signatory Authorization (Self-Declaration)</h3>
            </div>

            <p className="text-xs text-muted-foreground leading-relaxed">
              Please enter your legal signatory details and confirm the statutory authorization declaration below. Signatory identity is recorded as self-declared with IP, timestamp, and network audit trail (OTP verification not enabled).
            </p>

            <div className="space-y-3 pt-1">
              <div>
                <label className="block text-xs font-semibold text-foreground mb-1">
                  Full Legal Name of Signatory *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Ramesh Kumar"
                  value={signatoryName}
                  onChange={(e) => setSignatoryName(e.target.value)}
                  className="w-full text-xs bg-background border border-border rounded-lg p-2.5 text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1">
                    Designation / Capacity *
                  </label>
                  <select
                    value={signatoryDesignation}
                    onChange={(e) => setSignatoryDesignation(e.target.value)}
                    className="w-full text-xs bg-background border border-border rounded-lg p-2.5 text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="Director">Director</option>
                    <option value="Managing Director">Managing Director</option>
                    <option value="Partner">Partner</option>
                    <option value="Proprietor">Proprietor</option>
                    <option value="Authorized Signatory">Authorized Signatory</option>
                    <option value="CFO / Finance Controller">CFO / Finance Controller</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1">
                    Phone / Email Contact *
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="+91 98765 43210"
                    value={signatoryContact}
                    onChange={(e) => setSignatoryContact(e.target.value)}
                    className="w-full text-xs bg-background border border-border rounded-lg p-2.5 text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              {/* Statutory Legal Declaration Box */}
              <div className="p-3 rounded-xl bg-muted/40 border border-border text-[11px] text-muted-foreground space-y-1.5 leading-relaxed">
                <span className="font-semibold text-foreground block">
                  Statutory Consent Declaration (v1.0):
                </span>
                <p>
                  &ldquo;{review?.consent_declaration || "I hereby confirm that I have reviewed the return figures, tax liabilities, input tax credits, and net payable amounts presented. I declare that the figures are true, correct, and complete to the best of my knowledge, and I explicitly authorize the CA firm to file this GST return with the GSTN."}&rdquo;
                </p>
              </div>

              {/* Confirmation Checkbox */}
              <label className="flex items-start gap-2.5 pt-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={consentAffirmed}
                  onChange={(e) => setConsentAffirmed(e.target.checked)}
                  className="mt-1 rounded border-border text-primary focus:ring-primary"
                />
                <span className="text-xs text-foreground leading-normal">
                  I confirm that I have verified the figures and hereby grant explicit authorization to file this return with the GSTN.
                </span>
              </label>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-border">
              <button
                type="button"
                onClick={() => setShowAuthModal(false)}
                className="px-4 py-2 rounded-xl border border-border text-xs font-medium hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleAuthorize}
                disabled={!signatoryName.trim() || !signatoryContact.trim() || !consentAffirmed || actionLoading}
                className="px-5 py-2 rounded-xl bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {actionLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                <span>Confirm & Submit Authorization</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reject Modal Form */}
      {showRejectModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-2 text-rose-600 dark:text-rose-400">
              <XCircle className="w-5 h-5" />
              <h3 className="font-bold text-base text-foreground">Reject Return & Request Changes</h3>
            </div>

            <p className="text-xs text-muted-foreground leading-relaxed">
              Please describe the discrepancy or revision required so your CA firm can update the return figures.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-foreground mb-1">
                  Rejection Reason / Required Adjustments *
                </label>
                <textarea
                  rows={4}
                  required
                  placeholder="e.g. Sales register missing invoice INV-2024-089 for ₹1,50,000, please reconcile before filing..."
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  className="w-full text-xs bg-background border border-border rounded-lg p-3 text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-foreground mb-1">
                  Signatory Name (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Ramesh Kumar"
                  value={signatoryName}
                  onChange={(e) => setSignatoryName(e.target.value)}
                  className="w-full text-xs bg-background border border-border rounded-lg p-2.5 text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
              <button
                type="button"
                onClick={() => setShowRejectModal(false)}
                className="px-4 py-2 rounded-xl border border-border text-xs font-medium hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReject}
                disabled={rejectionReason.trim().length < 5 || actionLoading}
                className="px-5 py-2 rounded-xl bg-rose-600 text-white text-xs font-semibold hover:bg-rose-700 transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {actionLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                <span>Submit Rejection</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
