"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Link2,
  Copy,
  Check,
  History,
  ChevronDown,
  ChevronUp,
  Fingerprint,
  UserCheck,
  ExternalLink,
  Ban,
  RefreshCw,
  Loader2,
} from "lucide-react";
import {
  clientAuthorizationsApi,
  type ClientFilingAuthorization,
  type ClientAuthAuditEntry,
  type ClientAuthStatus,
} from "@/lib/api";
import { isRoleManagerOrAbove, isRoleWriterOrAbove } from "@/lib/auth-profile";

interface ClientAuthorizationCardProps {
  token: string | null;
  clientGstinId: string;
  gstin: string;
  period: string;
  returnType: "GSTR-1" | "GSTR-3B" | string;
  currentUserRole?: string;
  preparedFigures?: Record<string, unknown> | null;
  onAuthorizationStatusChange?: (auth: ClientFilingAuthorization | null) => void;
}

export function ClientAuthorizationCard({
  token,
  clientGstinId,
  gstin,
  period,
  returnType,
  currentUserRole = "viewer",
  preparedFigures,
  onAuthorizationStatusChange,
}: ClientAuthorizationCardProps) {
  const [auth, setAuth] = useState<ClientFilingAuthorization | null>(null);
  const [history, setHistory] = useState<ClientAuthAuditEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);
  const [showHistory, setShowHistory] = useState<boolean>(false);

  // Link Generation State
  const [generatedReviewUrl, setGeneratedReviewUrl] = useState<string | null>(null);
  const [expiresInHours, setExpiresInHours] = useState<number>(48);

  // Revoke Modal
  const [showRevokeModal, setShowRevokeModal] = useState<boolean>(false);
  const [revocationReason, setRevocationReason] = useState<string>("");

  const isManager = isRoleManagerOrAbove(currentUserRole);
  const isWriter = isRoleWriterOrAbove(currentUserRole);

  const fetchStatus = useCallback(async () => {
    if (!token || !clientGstinId || !period) return;
    try {
      setLoading(true);
      setError(null);
      const res = await clientAuthorizationsApi.getStatus(
        token,
        clientGstinId,
        period,
        returnType
      );
      setAuth(res.authorization);
      if (onAuthorizationStatusChange) {
        onAuthorizationStatusChange(res.authorization);
      }
    } catch (err: any) {
      console.warn("Failed to load client authorization status:", err);
    } finally {
      setLoading(false);
    }
  }, [token, clientGstinId, period, returnType, onAuthorizationStatusChange]);

  const fetchHistory = useCallback(async (authId: string) => {
    if (!token || !authId) return;
    try {
      const res = await clientAuthorizationsApi.getHistory(token, authId);
      setHistory(res.history || []);
    } catch (err) {
      console.warn("Failed to load authorization history:", err);
    }
  }, [token]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    if (auth?.id && showHistory) {
      fetchHistory(auth.id);
    }
  }, [auth?.id, showHistory, fetchHistory]);

  const handleCreateRequest = async () => {
    if (!token) return;
    try {
      setActionLoading(true);
      setError(null);
      const payload = preparedFigures || {
        gstin,
        period,
        return_type: returnType,
      };

      const res = await clientAuthorizationsApi.createRequest(token, {
        client_gstin_id: clientGstinId,
        gstin,
        period,
        return_type: returnType,
        figures_payload: payload,
        expires_in_hours: expiresInHours,
      });

      setAuth(res.authorization);
      if (onAuthorizationStatusChange) {
        onAuthorizationStatusChange(res.authorization);
      }

      // Construct absolute or relative link
      const reviewUrl = typeof window !== "undefined"
        ? `${window.location.origin}${res.review_path}`
        : res.review_path;
      setGeneratedReviewUrl(reviewUrl);
    } catch (err: any) {
      setError(err?.message || "Failed to generate client review link.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRevoke = async () => {
    if (!token || !auth?.id || !revocationReason.trim()) return;
    try {
      setActionLoading(true);
      setError(null);
      const res = await clientAuthorizationsApi.revoke(
        token,
        auth.id,
        revocationReason.trim()
      );
      setAuth(res.authorization);
      setShowRevokeModal(false);
      setRevocationReason("");
      setGeneratedReviewUrl(null);
      if (onAuthorizationStatusChange) {
        onAuthorizationStatusChange(res.authorization);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to revoke client authorization.");
    } finally {
      setActionLoading(false);
    }
  };

  const copyToClipboard = (url: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const getStatusBadge = (status?: ClientAuthStatus | string) => {
    switch (status) {
      case "AUTHORIZED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
            <CheckCircle2 className="w-3.5 h-3.5" /> Client Authorized
          </span>
        );
      case "VIEWED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border border-amber-300 dark:border-amber-800">
            <Clock className="w-3.5 h-3.5" /> Viewed by Client
          </span>
        );
      case "PENDING":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 border border-blue-300 dark:border-blue-800">
            <Clock className="w-3.5 h-3.5" /> Review Link Sent
          </span>
        );
      case "REJECTED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300 border border-rose-300 dark:border-rose-800">
            <XCircle className="w-3.5 h-3.5" /> Client Rejected
          </span>
        );
      case "REVOKED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-300 dark:border-slate-700">
            <Ban className="w-3.5 h-3.5" /> Revoked by CA
          </span>
        );
      case "EXPIRED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300 border border-orange-300 dark:border-orange-800">
            <AlertTriangle className="w-3.5 h-3.5" /> Expired
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">
            Not Requested
          </span>
        );
    }
  };

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 animate-pulse">
        <div className="h-5 bg-muted rounded w-1/3 mb-2" />
        <div className="h-4 bg-muted rounded w-2/3" />
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card text-card-foreground shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 sm:p-5 border-b border-border bg-muted/20 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10 text-primary">
            <UserCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-base tracking-tight">
                Client Review & Filing Authorization
              </h3>
              <span className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground font-mono">
                Phase 3.3 Gate
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Secure, tokenized client consent capture prior to GSTN return submission
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {getStatusBadge(auth?.status)}
          <button
            type="button"
            onClick={fetchStatus}
            disabled={actionLoading}
            className="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title="Refresh status"
          >
            <RefreshCw className={`w-4 h-4 ${actionLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="p-4 sm:p-5 space-y-4">
        {error && (
          <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Status Highlights */}
        {auth?.status === "AUTHORIZED" && (
          <div className="p-4 rounded-xl bg-emerald-50/60 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 space-y-2">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2 text-emerald-900 dark:text-emerald-200 font-semibold text-sm">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                <span>Explicit Client Authorization Active</span>
              </div>
              {auth.authorized_at && (
                <span className="text-xs text-emerald-700 dark:text-emerald-400">
                  Authorized on {new Date(auth.authorized_at).toLocaleString("en-IN")}
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs pt-1 text-slate-700 dark:text-slate-300">
              <div>
                <span className="text-muted-foreground">Signatory:</span>{" "}
                <strong className="text-foreground">{auth.signatory_name || "N/A"} (Self-Declared)</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Designation:</span>{" "}
                <strong className="text-foreground">{auth.signatory_designation || "N/A"}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Contact:</span>{" "}
                <strong className="text-foreground">{auth.signatory_contact || "N/A"}</strong>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-[11px] text-emerald-800 dark:text-emerald-300 pt-0.5">
              <span className="px-2 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/40 border border-emerald-300 dark:border-emerald-700 font-medium">
                Identity: Self-Declared Signatory
              </span>
              <span className="text-muted-foreground text-[10px]">
                (Digital Affirmation v1.0 • Client IP & User-Agent logged • OTP not enabled)
              </span>
            </div>

            {auth.figures_digest && (
              <div className="text-[11px] font-mono text-emerald-800 dark:text-emerald-300 bg-emerald-100/60 dark:bg-emerald-900/40 px-2.5 py-1 rounded flex items-center gap-1.5 overflow-x-auto">
                <Fingerprint className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">Bound Digest: {auth.figures_digest}</span>
              </div>
            )}
          </div>
        )}

        {auth?.status === "REJECTED" && (
          <div className="p-4 rounded-xl bg-rose-50/60 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800 space-y-1.5 text-xs text-rose-900 dark:text-rose-200">
            <div className="flex items-center gap-2 font-semibold text-sm text-rose-800 dark:text-rose-300">
              <XCircle className="w-4 h-4" />
              <span>Return Rejected by Client</span>
            </div>
            <p className="mt-1">
              <strong>Reason:</strong> {auth.rejection_reason || "No detailed reason provided."}
            </p>
            {auth.rejected_at && (
              <p className="text-[11px] text-muted-foreground">
                Rejected at {new Date(auth.rejected_at).toLocaleString("en-IN")}
              </p>
            )}
          </div>
        )}

        {auth?.status === "REVOKED" && (
          <div className="p-4 rounded-xl bg-slate-100 dark:bg-slate-800/60 border border-slate-300 dark:border-slate-700 space-y-1 text-xs text-slate-800 dark:text-slate-300">
            <div className="flex items-center gap-2 font-medium">
              <Ban className="w-4 h-4 text-slate-500" />
              <span>Authorization Request Revoked by CA Firm</span>
            </div>
            <p>
              <strong>Reason:</strong> {auth.revocation_reason || "Revoked prior to submission."}
            </p>
          </div>
        )}

        {auth?.status === "EXPIRED" && (
          <div className="p-4 rounded-xl bg-orange-50/60 dark:bg-orange-950/30 border border-orange-200 dark:border-orange-800 space-y-1 text-xs text-orange-900 dark:text-orange-200">
            <div className="flex items-center gap-2 font-semibold">
              <AlertTriangle className="w-4 h-4 text-orange-600" />
              <span>Review Token Expired</span>
            </div>
            <p>
              The client review link has expired past its validity window. Generate a new review link to collect client consent.
            </p>
          </div>
        )}

        {/* Active Link Banner (if generated in this session or pending/viewed) */}
        {(generatedReviewUrl || (auth && (auth.status === "PENDING" || auth.status === "VIEWED"))) && (
          <div className="p-3.5 rounded-xl border border-blue-200 dark:border-blue-900 bg-blue-50/50 dark:bg-blue-950/20 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-blue-900 dark:text-blue-200 flex items-center gap-1.5">
                <Link2 className="w-3.5 h-3.5" />
                {auth?.status === "VIEWED" ? "Client Review Portal (Opened by Client)" : "Client Review Portal Link"}
              </span>
              {auth?.expires_at && (
                <span className="text-[11px] text-muted-foreground">
                  Expires: {new Date(auth.expires_at).toLocaleDateString("en-IN")}
                </span>
              )}
            </div>

            {generatedReviewUrl && (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={generatedReviewUrl}
                  className="w-full text-xs font-mono bg-background border border-border px-3 py-1.5 rounded-lg text-foreground focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => copyToClipboard(generatedReviewUrl)}
                  className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 flex items-center gap-1 shrink-0 transition-colors"
                >
                  {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? "Copied" : "Copy Link"}</span>
                </button>
                <a
                  href={generatedReviewUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="p-1.5 rounded-lg border border-border bg-background hover:bg-muted text-muted-foreground hover:text-foreground shrink-0 transition-colors"
                  title="Open Portal Preview"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            )}
          </div>
        )}

        {/* Action Panel */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <div className="flex items-center gap-2">
            {(!auth || auth.status === "EXPIRED" || auth.status === "REVOKED" || auth.status === "REJECTED") && isWriter && (
              <div className="flex items-center gap-2">
                <select
                  value={expiresInHours}
                  onChange={(e) => setExpiresInHours(Number(e.target.value))}
                  disabled={actionLoading}
                  className="text-xs bg-background border border-border rounded-lg px-2.5 py-1.5 text-foreground focus:outline-none"
                >
                  <option value={24}>Valid 24 Hours</option>
                  <option value={48}>Valid 48 Hours</option>
                  <option value={72}>Valid 3 Days</option>
                  <option value={168}>Valid 7 Days</option>
                </select>
                <button
                  type="button"
                  onClick={handleCreateRequest}
                  disabled={actionLoading}
                  className="px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 flex items-center gap-1.5 transition-colors disabled:opacity-50"
                >
                  {actionLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Link2 className="w-3.5 h-3.5" />}
                  <span>{auth ? "Renew Review Link" : "Request Client Review"}</span>
                </button>
              </div>
            )}

            {auth && (auth.status === "PENDING" || auth.status === "VIEWED" || auth.status === "AUTHORIZED") && isManager && (
              <button
                type="button"
                onClick={() => setShowRevokeModal(true)}
                disabled={actionLoading}
                className="px-3 py-1.5 rounded-lg border border-rose-300 dark:border-rose-900 text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/50 text-xs font-medium flex items-center gap-1.5 transition-colors"
              >
                <Ban className="w-3.5 h-3.5" />
                <span>Revoke Authorization</span>
              </button>
            )}
          </div>

          {auth?.id && (
            <button
              type="button"
              onClick={() => setShowHistory(!showHistory)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
            >
              <History className="w-3.5 h-3.5" />
              <span>{showHistory ? "Hide Audit History" : "View Audit History"}</span>
              {showHistory ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>

        {/* Audit History Timeline */}
        {showHistory && (
          <div className="mt-4 pt-4 border-t border-border space-y-2">
            <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider">
              Immutable Client Authorization Audit Trail
            </h4>
            {history.length === 0 ? (
              <p className="text-xs text-muted-foreground italic">No audit records recorded yet.</p>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                {history.map((entry) => (
                  <div
                    key={entry.id}
                    className="p-2.5 rounded-lg bg-muted/40 border border-border text-xs flex items-start justify-between gap-3"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-foreground">{entry.action}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-mono">
                          {entry.actor_type}
                        </span>
                      </div>
                      <p className="text-muted-foreground mt-0.5">{entry.notes}</p>
                      {entry.actor_name && (
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          Actor: {entry.actor_name}
                        </p>
                      )}
                    </div>
                    <span className="text-[11px] text-muted-foreground whitespace-nowrap">
                      {new Date(entry.created_at).toLocaleString("en-IN")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Revocation Modal */}
      {showRevokeModal && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border rounded-xl max-w-md w-full p-5 space-y-4 shadow-xl">
            <div className="flex items-center gap-2 text-rose-600 dark:text-rose-400 font-semibold text-base">
              <Ban className="w-5 h-5" />
              <h4>Revoke Client Authorization</h4>
            </div>
            <p className="text-xs text-muted-foreground">
              Revoking will immediately deactivate the public client review link and revoke any granted consent. A reason is required for audit logs.
            </p>
            <textarea
              value={revocationReason}
              onChange={(e) => setRevocationReason(e.target.value)}
              placeholder="e.g. Return figures revised due to client credit note amendments..."
              className="w-full text-xs bg-background border border-border rounded-lg p-3 min-h-[90px] focus:outline-none focus:ring-1 focus:ring-primary text-foreground"
            />
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowRevokeModal(false)}
                className="px-3.5 py-1.5 rounded-lg border border-border text-xs font-medium hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRevoke}
                disabled={!revocationReason.trim() || actionLoading}
                className="px-4 py-1.5 rounded-lg bg-rose-600 text-white text-xs font-semibold hover:bg-rose-700 transition-colors disabled:opacity-50"
              >
                {actionLoading ? "Revoking..." : "Confirm Revocation"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
