"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileCheck2,
  Send,
  History,
  ChevronDown,
  ChevronUp,
  Fingerprint,
  UserCheck,
  Info,
  Loader2,
} from "lucide-react";
import {
  filingApprovalsApi,
  type ReturnApproval,
  type ReturnApprovalStatus,
  type ReturnApprovalAuditEntry,
} from "@/lib/api";
import { isRoleManagerOrAbove, isRoleWriterOrAbove } from "@/lib/auth-profile";

interface MakerCheckerApprovalCardProps {
  token: string | null;
  clientGstinId: string;
  gstin: string;
  period: string;
  returnType: "GSTR-1" | "GSTR-3B" | string;
  currentUserId?: string;
  currentUserRole?: string;
  onApprovalStatusChange?: (approval: ReturnApproval) => void;
  // If figures payload is ready in the parent component
  preparedFigures?: Record<string, unknown> | null;
}

export function MakerCheckerApprovalCard({
  token,
  clientGstinId,
  gstin,
  period,
  returnType,
  currentUserId,
  currentUserRole = "viewer",
  onApprovalStatusChange,
  preparedFigures,
}: MakerCheckerApprovalCardProps) {
  const [approval, setApproval] = useState<ReturnApproval | null>(null);
  const [history, setHistory] = useState<ReturnApprovalAuditEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState<boolean>(false);

  // Modals & Inputs
  const [showRejectModal, setShowRejectModal] = useState<boolean>(false);
  const [rejectionReason, setRejectionReason] = useState<string>("");
  const [submissionNotes, setSubmissionNotes] = useState<string>("");
  const [approvalNotes, setApprovalNotes] = useState<string>("");

  const isManager = isRoleManagerOrAbove(currentUserRole);
  const isWriter = isRoleWriterOrAbove(currentUserRole);

  const fetchApproval = useCallback(async () => {
    if (!token || !clientGstinId || !period) return;
    try {
      setLoading(true);
      setError(null);
      const res = await filingApprovalsApi.getApproval(
        token,
        returnType,
        period,
        clientGstinId
      );
      setApproval(res);
      if (onApprovalStatusChange) {
        onApprovalStatusChange(res);
      }
    } catch (err: any) {
      console.warn("Failed to load maker-checker approval:", err);
      // Fails gracefully to DRAFT view
    } finally {
      setLoading(false);
    }
  }, [token, clientGstinId, period, returnType, onApprovalStatusChange]);

  const fetchHistory = useCallback(async () => {
    if (!token || !clientGstinId || !period) return;
    try {
      const res = await filingApprovalsApi.getHistory(
        token,
        returnType,
        period,
        clientGstinId
      );
      setHistory(res.history || []);
    } catch (err) {
      console.warn("Failed to load approval history:", err);
    }
  }, [token, clientGstinId, period, returnType]);

  useEffect(() => {
    fetchApproval();
  }, [fetchApproval]);

  const handlePrepareAndSubmit = async () => {
    if (!token) return;
    try {
      setActionLoading(true);
      setError(null);
      const payload = preparedFigures || {
        gstin,
        period,
        return_type: returnType,
      };
      const res = await filingApprovalsApi.prepare(token, returnType, period, {
        client_gstin_id: clientGstinId,
        figures_payload: payload,
        notes: submissionNotes,
        submit_for_review: true,
      });
      setApproval(res);
      setSubmissionNotes("");
      if (onApprovalStatusChange) onApprovalStatusChange(res);
      fetchHistory();
    } catch (err: any) {
      const msg = err?.message || err?.detail?.message || "Failed to submit return for review.";
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!token || !approval) return;
    try {
      setActionLoading(true);
      setError(null);
      const res = await filingApprovalsApi.approve(token, returnType, period, {
        client_gstin_id: clientGstinId,
        expected_figures_digest: approval.figures_digest || undefined,
        notes: approvalNotes,
      });
      setApproval(res);
      setApprovalNotes("");
      if (onApprovalStatusChange) onApprovalStatusChange(res);
      fetchHistory();
    } catch (err: any) {
      const msg = err?.message || err?.detail?.message || "Failed to approve return.";
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!token || !rejectionReason.trim()) return;
    try {
      setActionLoading(true);
      setError(null);
      const res = await filingApprovalsApi.reject(token, returnType, period, {
        client_gstin_id: clientGstinId,
        rejection_reason: rejectionReason.trim(),
      });
      setApproval(res);
      setShowRejectModal(false);
      setRejectionReason("");
      if (onApprovalStatusChange) onApprovalStatusChange(res);
      fetchHistory();
    } catch (err: any) {
      const msg = err?.message || err?.detail?.message || "Failed to reject return.";
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  const status: ReturnApprovalStatus = approval?.status || "DRAFT";
  const isSelfPreparer = Boolean(
    currentUserId && approval?.preparer_id && currentUserId === approval.preparer_id
  );

  const getStatusBadge = (st: ReturnApprovalStatus) => {
    switch (st) {
      case "DRAFT":
        return {
          label: "Draft Return",
          bg: "bg-slate-100 text-slate-800 border-slate-200 dark:bg-slate-800 dark:text-slate-200",
          icon: Clock,
          desc: "Draft figures in progress. Not submitted for review.",
        };
      case "PREPARED":
        return {
          label: "Prepared",
          bg: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300",
          icon: FileCheck2,
          desc: "Figures prepared with cryptographic digest. Ready for review submission.",
        };
      case "UNDER_REVIEW":
        return {
          label: "Under Review",
          bg: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300",
          icon: Clock,
          desc: "Maker-Checker review pending. Awaiting Manager or Partner sign-off.",
        };
      case "APPROVED":
        return {
          label: "Approved for Filing",
          bg: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300",
          icon: CheckCircle2,
          desc: "Return approved by CA Partner/Manager. Authorized for GSTN Save & Filing.",
        };
      case "REJECTED":
        return {
          label: "Changes Requested",
          bg: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300",
          icon: XCircle,
          desc: "Reviewer requested changes. See rejection notes below.",
        };
      case "SAVED":
        return {
          label: "Saved to GSTN",
          bg: "bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-300",
          icon: FileCheck2,
          desc: "Figures confirmed and saved with GSTN Sandbox.",
        };
      case "OFFSET_COMPLETE":
        return {
          label: "Offset Complete",
          bg: "bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/40 dark:text-teal-300",
          icon: ShieldCheck,
          desc: "Tax liability successfully discharged via cash/ITC ledger.",
        };
      case "FILED":
        return {
          label: "Statutorily Filed",
          bg: "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-900/50 dark:text-emerald-200",
          icon: ShieldCheck,
          desc: "Return filing completed. Statutory acknowledgment generated.",
        };
      default:
        return {
          label: st,
          bg: "bg-slate-100 text-slate-700 border-slate-200",
          icon: Info,
          desc: "",
        };
    }
  };

  const badge = getStatusBadge(status);
  const BadgeIcon = badge.icon;

  if (loading && !approval) {
    return (
      <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-3 text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <span className="text-sm">Verifying maker-checker governance lifecycle...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200/80 bg-white shadow-sm transition dark:border-slate-800 dark:bg-slate-900">
      {/* Header bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 p-4 dark:border-slate-800/80">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400">
            <UserCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                Maker-Checker Filing Workflow
              </h3>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                Phase 3.2
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Separation of duties & cryptographic figure digest binding
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${badge.bg}`}
          >
            <BadgeIcon className="h-3.5 w-3.5" />
            {badge.label}
          </span>
        </div>
      </div>

      {/* Main Content Body */}
      <div className="p-5 space-y-4">
        {/* Status description */}
        <p className="text-xs text-slate-600 dark:text-slate-300">{badge.desc}</p>

        {/* Error notification */}
        {error && (
          <div className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50/70 p-3 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
            <div>
              <p className="font-medium">Governance Gate Alert</p>
              <p className="mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* Separation of duties warning banner */}
        {isSelfPreparer && status === "UNDER_REVIEW" && (
          <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50/70 p-3 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <div>
              <span className="font-semibold">Separation of Duties Enforced:</span> You prepared
              this return. As Maker, you cannot approve your own submission. A separate Manager or
              Partner must review and approve before filing.
            </div>
          </div>
        )}

        {/* Rejection notice banner if rejected */}
        {status === "REJECTED" && approval?.rejection_reason && (
          <div className="rounded-lg border border-rose-200 bg-rose-50/60 p-3.5 text-xs dark:border-rose-900/50 dark:bg-rose-950/30">
            <div className="flex items-center gap-2 font-semibold text-rose-800 dark:text-rose-300">
              <XCircle className="h-4 w-4 text-rose-600" />
              Rejection Reason from Reviewer
            </div>
            <p className="mt-1 text-slate-700 dark:text-slate-300">
              {approval.rejection_reason}
            </p>
            {approval.rejected_by_name && (
              <p className="mt-2 text-[11px] text-slate-500">
                Rejected by {approval.rejected_by_name} ({approval.rejected_by_role}) on{" "}
                {approval.rejected_at ? new Date(approval.rejected_at).toLocaleString() : "recently"}
              </p>
            )}
          </div>
        )}

        {/* Cryptographic Digest & Metadata Row */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {/* Figures Digest */}
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-800/40">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
              <Fingerprint className="h-3.5 w-3.5 text-primary" />
              Figures SHA-256 Digest
            </div>
            <div className="mt-1 font-mono text-xs text-slate-800 dark:text-slate-200 truncate">
              {approval?.figures_digest ? (
                <span title={approval.figures_digest}>
                  {approval.figures_digest.slice(0, 16)}...{approval.figures_digest.slice(-8)}
                </span>
              ) : (
                <span className="italic text-slate-400">Pending preparation</span>
              )}
            </div>
          </div>

          {/* Actor Sign-offs */}
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-800/40">
            <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
              Governance Sign-offs
            </div>
            <div className="mt-1 text-xs text-slate-700 dark:text-slate-300">
              {approval?.preparer_name ? (
                <span>
                  Prepared by <strong className="font-semibold">{approval.preparer_name}</strong>
                  {approval.approver_name && (
                    <>
                      {" "}
                      • Approved by <strong className="font-semibold">{approval.approver_name}</strong>
                    </>
                  )}
                </span>
              ) : (
                <span className="italic text-slate-400">No submission recorded</span>
              )}
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <button
            type="button"
            onClick={() => {
              if (!showHistory) fetchHistory();
              setShowHistory(!showHistory);
            }}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
          >
            <History className="h-3.5 w-3.5" />
            {showHistory ? "Hide Audit History" : "View Immutable Audit Trail"}
            {showHistory ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>

          <div className="flex items-center gap-2">
            {/* Submit for Review (Preparer / Writer) */}
            {(status === "DRAFT" || status === "PREPARED" || status === "REJECTED") && isWriter && (
              <button
                type="button"
                onClick={handlePrepareAndSubmit}
                disabled={actionLoading}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-xs font-medium text-white shadow-sm hover:bg-primary/90 disabled:opacity-50"
              >
                {actionLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
                Submit for Review
              </button>
            )}

            {/* Reviewer Actions: Approve & Reject (Manager / Partner only, excluding self) */}
            {status === "UNDER_REVIEW" && isManager && (
              <>
                <button
                  type="button"
                  onClick={() => setShowRejectModal(true)}
                  disabled={actionLoading}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-rose-300 bg-white px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:bg-slate-900 dark:text-rose-400 dark:hover:bg-rose-950/50"
                >
                  <XCircle className="h-3.5 w-3.5" />
                  Reject
                </button>

                <button
                  type="button"
                  onClick={handleApprove}
                  disabled={actionLoading || isSelfPreparer}
                  title={
                    isSelfPreparer
                      ? "Separation of duties: Preparers cannot approve their own submission"
                      : "Authorize return for GSTN Save & Filing"
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-2 text-xs font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {actionLoading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  )}
                  Approve Return
                </button>
              </>
            )}
          </div>
        </div>

        {/* Rejection Modal */}
        {showRejectModal && (
          <div className="rounded-lg border border-rose-200 bg-rose-50/80 p-4 dark:border-rose-900/60 dark:bg-rose-950/40">
            <h4 className="text-xs font-semibold text-rose-900 dark:text-rose-200">
              Provide Mandatory Rejection Reason
            </h4>
            <p className="mt-1 text-xs text-rose-700 dark:text-rose-300">
              Specify what discrepancies or issues must be resolved by the preparer.
            </p>
            <textarea
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder="e.g. Sales register B2B invoice count mismatch with Tally vouchers..."
              rows={3}
              className="mt-2.5 w-full rounded-md border border-rose-300 bg-white p-2.5 text-xs text-slate-800 shadow-sm focus:border-rose-500 focus:outline-none dark:border-rose-800 dark:bg-slate-900 dark:text-slate-200"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowRejectModal(false)}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReject}
                disabled={actionLoading || !rejectionReason.trim()}
                className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700 disabled:opacity-50"
              >
                Confirm Rejection
              </button>
            </div>
          </div>
        )}

        {/* Audit History Timeline */}
        {showHistory && (
          <div className="border-t border-slate-100 pt-3 dark:border-slate-800">
            <h4 className="text-xs font-semibold text-slate-900 dark:text-white mb-2">
              Tenant Audit Trail
            </h4>
            {history.length === 0 ? (
              <p className="text-xs text-slate-400 italic">No previous events recorded.</p>
            ) : (
              <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                {history.map((entry) => (
                  <div
                    key={entry.id}
                    className="flex items-start justify-between rounded-lg border border-slate-100 bg-slate-50/60 p-2 text-xs dark:border-slate-800/80 dark:bg-slate-800/40"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-800 dark:text-slate-200">
                          {entry.action}
                        </span>
                        <span className="rounded bg-slate-200 px-1.5 py-0.2 text-[10px] font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-300">
                          {entry.actor_role}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 mt-0.5">
                        By {entry.actor_name} • {new Date(entry.created_at).toLocaleString()}
                      </p>
                      {entry.notes && (
                        <p className="mt-1 text-[11px] text-slate-600 dark:text-slate-300">
                          {entry.notes}
                        </p>
                      )}
                    </div>
                    {entry.figures_digest && (
                      <span className="font-mono text-[10px] text-slate-400 truncate max-w-[80px]">
                        {entry.figures_digest.slice(0, 8)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
