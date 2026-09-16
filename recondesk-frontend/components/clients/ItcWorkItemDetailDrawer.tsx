"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { formatINR } from "@/lib/format";
import {
  workItemsApi,
  teamApi,
  TeamMemberListItem,
  ItcWorkItem,
  ItcWorkItemEvent,
  ResolutionIntelligenceResponse,
} from "@/lib/api";
import {
  fetchWorkItemVendorProfile,
  fetchWorkItemFollowupHistory,
  scheduleWorkItemFollowup,
  WorkItemVendorProfile,
  FollowupLog,
} from "@/lib/vendorFollowupApi";
import VendorCommunicationModal from "@/components/clients/VendorCommunicationModal";
import RecordVendorResponseModal from "@/components/clients/RecordVendorResponseModal";
import {
  deriveEffectiveRevalStatus,
  REVALIDATION_STATUS_LABELS,
  getRevalidationBadgeStyle,
  sanitizeTechnicalReason,
  getNotRevalidatedExplanation,
  canRequestRevalidation,
  canRetryRevalidation,
  canExecuteRevalidation,
  shouldPollRevalidation,
  deriveRevalidationActionFeedback,
  isMakerCheckerRequired,
  resolveTaxDiffAfterPaise,
  formatTaxDiffAfter,
  RevalUxStatus,
} from "@/components/clients/revalidationUxLogic";

interface ItcWorkItemDetailDrawerProps {
  workItem: ItcWorkItem | null;
  authToken: string;
  clientId: string;
  currentUserRole?: string;
  currentUserId?: string;
  onClose: () => void;
  onUpdated: () => void;
}

export function ItcWorkItemDetailDrawer({
  workItem,
  authToken,
  clientId,
  currentUserRole = "admin",
  currentUserId,
  onClose,
  onUpdated,
}: ItcWorkItemDetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<"overview" | "vendor" | "timeline">("overview");
  const [newNote, setNewNote] = useState("");
  const [isSubmittingNote, setIsSubmittingNote] = useState(false);

  // Status transition state
  const [targetStatus, setTargetStatus] = useState<string>("");
  const [statusNote, setStatusNote] = useState<string>("");
  const [isTransitioning, setIsTransitioning] = useState(false);

  // Priority override state
  const [isPriorityModalOpen, setIsPriorityModalOpen] = useState(false);
  const [overridePriority, setOverridePriority] = useState<string>("HIGH");
  const [priorityReason, setPriorityReason] = useState("");
  const [isOverridingPriority, setIsOverridingPriority] = useState(false);

  // Due date state
  const [dueDateInput, setDueDateInput] = useState<string>("");
  const [isUpdatingDueDate, setIsUpdatingDueDate] = useState(false);

  // Assignee state
  const [isAssigning, setIsAssigning] = useState(false);

  // Resolution modal state
  const [isResolutionOpen, setIsResolutionOpen] = useState(false);
  const [resolutionCode, setResolutionCode] = useState<string>("VENDOR_CORRECTION_RECEIVED");
  const [resolutionNote, setResolutionNote] = useState("");
  const [isResolving, setIsResolving] = useState(false);

  // Dismiss / Reopen modal state
  const [isDismissOpen, setIsDismissOpen] = useState(false);
  const [dismissReason, setDismissReason] = useState("");
  const [isDismissing, setIsDismissing] = useState(false);

  const [isReopenOpen, setIsReopenOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [isReopening, setIsReopening] = useState(false);

  const [isRevalidating, setIsRevalidating] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Phase 5.3: Vendor Resolution modals and state
  const [isContactModalOpen, setIsContactModalOpen] = useState(false);
  const [isResponseModalOpen, setIsResponseModalOpen] = useState(false);
  const [isScheduleFollowupOpen, setIsScheduleFollowupOpen] = useState(false);
  const [followupDateInput, setFollowupDateInput] = useState("");
  const [followupNoteInput, setFollowupNoteInput] = useState("");
  const [isSchedulingFollowup, setIsSchedulingFollowup] = useState(false);

  // Fetch live item with events timeline (polls safely at 4000ms only during PENDING/REVALIDATING)
  const { data: itemData, mutate: mutateItem } = useSWR<ItcWorkItem & { events: ItcWorkItemEvent[] }>(
    workItem?.id && authToken ? [`work-item`, workItem.id] : null,
    () => workItemsApi.get(authToken, workItem!.id!),
    {
      refreshInterval: (latestData) => {
        const cur = latestData?.revalidation_status || workItem?.revalidation_status;
        return shouldPollRevalidation(cur) ? 4000 : 0;
      },
    }
  );

  // Fetch team members for assignment
  const { data: teamMembers } = useSWR<TeamMemberListItem[]>(
    authToken ? ["team-members-assign", authToken] : null,
    () => teamApi.list(authToken, { includeOwner: true }),
    { refreshInterval: 0 }
  );

  // Phase 5.3: Fetch Vendor Compliance Profile
  const { data: vendorProfile, mutate: mutateVendorProfile } = useSWR<WorkItemVendorProfile>(
    workItem?.id && authToken ? ["work-item-vendor-profile", workItem.id] : null,
    () => fetchWorkItemVendorProfile(workItem!.id!, authToken),
    { refreshInterval: 0 }
  );

  // Phase 5.3: Fetch Work Item Communication History
  const { data: followupHistoryData, mutate: mutateFollowups } = useSWR<{
    work_item_id: string;
    client_gstin_id: string;
    total_logs: number;
    logs: FollowupLog[];
  }>(
    workItem?.id && authToken ? ["work-item-followup-history", workItem.id] : null,
    () => fetchWorkItemFollowupHistory(workItem!.id!, authToken),
    { refreshInterval: 0 }
  );

  // Phase 5.4: Fetch Deterministic Resolution Intelligence
  const {
    data: intelligenceData,
    mutate: mutateIntelligence,
    isLoading: isIntelligenceLoading,
  } = useSWR<ResolutionIntelligenceResponse>(
    workItem?.id && authToken ? ["work-item-intelligence", workItem.id] : null,
    () => workItemsApi.getIntelligence(authToken, workItem!.id!),
    { refreshInterval: 0 }
  );

  const item = itemData || workItem;

  useEffect(() => {
    if (item?.due_at) {
      setDueDateInput(item.due_at.slice(0, 10));
    } else {
      setDueDateInput("");
    }
    setActionMessage(null);
    setActionError(null);
  }, [item?.id, item?.due_at]);

  if (!item) return null;

  const isCA = currentUserRole === "admin" || currentUserRole === "owner";
  const events = itemData?.events || [];
  const followups = followupHistoryData?.logs || [];

  // Phase 5.5B: Revalidation status and event metadata derivation
  const revalEvents = [...events]
    .filter((e) =>
      [
        "REVALIDATION_COMPLETED",
        "REVALIDATION_STARTED",
        "REVALIDATION_REQUESTED",
        "REVALIDATION_STALE_TARGET_SKIPPED",
      ].includes(e.event_type)
    )
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  const latestRevalEvent = revalEvents[0];
  const effectiveRevalStatus = deriveEffectiveRevalStatus(item, latestRevalEvent);
  const revalBadgeStyle = getRevalidationBadgeStyle(effectiveRevalStatus);
  const revalStatusLabel = REVALIDATION_STATUS_LABELS[effectiveRevalStatus];
  const revalActionPermission = canRequestRevalidation(effectiveRevalStatus, item.exception_type);

  const revalTargetRunId =
    latestRevalEvent?.metadata?.target_run_id ||
    latestRevalEvent?.metadata?.evaluated_target_run_id ||
    item.target_run_id;

  const prevException =
    latestRevalEvent?.metadata?.previous_exception_type ||
    item.previous_exception_type ||
    item.exception_type;

  const newException =
    latestRevalEvent?.metadata?.new_exception_type ||
    item.new_exception_type;

  const taxDiffBeforePaise =
    latestRevalEvent?.metadata?.tax_diff_before ??
    (item.tax_diff_before != null
      ? item.tax_diff_before
      : (item.itc_impact_paise ?? Math.round((item.itc_impact || 0) * 100)));

  const taxDiffAfterPaise = resolveTaxDiffAfterPaise(item, latestRevalEvent);

  const authoritativeRef =
    latestRevalEvent?.metadata?.authoritative_record_ref ||
    item.authoritative_record_ref;

  const comparisonReason =
    latestRevalEvent?.metadata?.comparison_reason ||
    latestRevalEvent?.note ||
    item.comparison_reason;

  const handleScheduleFollowup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!item.id || !followupDateInput) return;
    setIsSchedulingFollowup(true);
    setActionError(null);
    try {
      await scheduleWorkItemFollowup(
        item.id,
        {
          due_at: followupDateInput,
          note: followupNoteInput.trim() || undefined,
        },
        authToken
      );
      setIsScheduleFollowupOpen(false);
      setFollowupDateInput("");
      setFollowupNoteInput("");
      mutateItem();
      onUpdated();
      setActionMessage("Next follow-up scheduled and logged to timeline.");
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to schedule follow-up.");
    } finally {
      setIsSchedulingFollowup(false);
    }
  };

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newNote.trim() || !item.id) return;
    setIsSubmittingNote(true);
    setActionError(null);
    try {
      await workItemsApi.addNote(authToken, item.id, newNote.trim());
      setNewNote("");
      mutateItem();
      onUpdated();
      setActionMessage("Note recorded to activity timeline.");
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to add note.");
    } finally {
      setIsSubmittingNote(false);
    }
  };

  const handleStatusTransition = async (newStatus: string) => {
    if (!item.id) return;
    setIsTransitioning(true);
    setActionError(null);
    try {
      await workItemsApi.updateStatus(authToken, item.id, newStatus, statusNote || undefined);
      setStatusNote("");
      mutateItem();
      onUpdated();
      setActionMessage(`Status moved to ${newStatus}.`);
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to transition status.");
    } finally {
      setIsTransitioning(false);
    }
  };

  const handleAssign = async (assignedToId: string | null) => {
    if (!item.id) return;
    setIsAssigning(true);
    setActionError(null);
    try {
      await workItemsApi.assign(authToken, item.id, assignedToId || null);
      mutateItem();
      onUpdated();
      setActionMessage("Assignment updated.");
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to assign work item.");
    } finally {
      setIsAssigning(false);
    }
  };

  const handlePriorityOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!item.id || !priorityReason.trim()) return;
    setIsOverridingPriority(true);
    setActionError(null);
    try {
      await workItemsApi.overridePriority(authToken, item.id, overridePriority, priorityReason.trim());
      setIsPriorityModalOpen(false);
      setPriorityReason("");
      mutateItem();
      onUpdated();
      setActionMessage(`Priority overridden to ${overridePriority}.`);
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to override priority.");
    } finally {
      setIsOverridingPriority(false);
    }
  };

  const handleDueDateChange = async (val: string) => {
    if (!item.id) return;
    setIsUpdatingDueDate(true);
    setActionError(null);
    try {
      const isoVal = val ? new Date(val).toISOString() : null;
      await workItemsApi.setDueDate(authToken, item.id, isoVal);
      setDueDateInput(val);
      mutateItem();
      onUpdated();
      setActionMessage("Due date updated.");
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to update due date.");
    } finally {
      setIsUpdatingDueDate(false);
    }
  };

  const handleResolve = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!item.id || !resolutionNote.trim()) return;
    setIsResolving(true);
    setActionError(null);
    try {
      await workItemsApi.resolve(authToken, item.id, resolutionCode, resolutionNote.trim());
      setIsResolutionOpen(false);
      setResolutionNote("");
      mutateItem();
      onUpdated();
      setActionMessage(
        isCA
          ? "Work item marked RESOLVED."
          : "Work item submitted to CA for final review (READY_FOR_REVIEW)."
      );
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to resolve work item.");
    } finally {
      setIsResolving(false);
    }
  };

  const handleDismiss = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!item.id || !dismissReason.trim()) return;
    setIsDismissing(true);
    setActionError(null);
    try {
      await workItemsApi.dismiss(authToken, item.id, dismissReason.trim());
      setIsDismissOpen(false);
      setDismissReason("");
      mutateItem();
      onUpdated();
      setActionMessage("Work item DISMISSED.");
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to dismiss work item.");
    } finally {
      setIsDismissing(false);
    }
  };

  const handleReopen = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!item.id || !reopenReason.trim()) return;
    setIsReopening(true);
    setActionError(null);
    try {
      await workItemsApi.reopen(authToken, item.id, reopenReason.trim());
      setIsReopenOpen(false);
      setReopenReason("");
      mutateItem();
      onUpdated();
      setActionMessage("Work item REOPENED.");
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to reopen work item.");
    } finally {
      setIsReopening(false);
    }
  };

  const runRevalidationFlow = async (isExplicitExecute: boolean = false) => {
    if (!item.id || isRevalidating) return;
    setIsRevalidating(true);
    setActionError(null);
    try {
      const updated = isExplicitExecute
        ? await workItemsApi.executeRevalidation(authToken, item.id)
        : await workItemsApi.revalidate(authToken, item.id, { execute_now: true });
      mutateItem();
      onUpdated();
      const feedback = deriveRevalidationActionFeedback(updated || item, isCA);
      if (feedback.error) {
        setActionError(feedback.error);
      } else if (feedback.message) {
        setActionMessage(feedback.message);
      }
    } catch (err: any) {
      setActionError(
        err.detail ||
          err.message ||
          (isExplicitExecute ? "Failed to execute revalidation." : "Failed to request revalidation.")
      );
    } finally {
      setIsRevalidating(false);
    }
  };

  const handleRevalidate = () => runRevalidationFlow(false);
  const handleExecuteRevalidation = () => runRevalidationFlow(true);

  const getPriorityBadgeColor = (prio: string) => {
    switch (prio) {
      case "CRITICAL":
        return "bg-rose-50 text-rose-700 border-rose-200";
      case "HIGH":
        return "bg-orange-50 text-orange-700 border-orange-200";
      case "MEDIUM":
        return "bg-amber-50 text-amber-700 border-amber-200";
      default:
        return "bg-gray-50 text-gray-700 border-gray-200";
    }
  };

  const getStatusBadgeColor = (st: string) => {
    switch (st) {
      case "RESOLVED":
        return "bg-emerald-50 text-emerald-700 border-emerald-200";
      case "READY_FOR_REVIEW":
        return "bg-purple-50 text-purple-700 border-purple-200";
      case "WAITING_VENDOR":
        return "bg-amber-50 text-amber-700 border-amber-200";
      case "IN_PROGRESS":
        return "bg-blue-50 text-blue-700 border-blue-200";
      case "ASSIGNED":
        return "bg-indigo-50 text-indigo-700 border-indigo-200";
      case "DISMISSED":
        return "bg-gray-100 text-gray-600 border-gray-300";
      default:
        return "bg-gray-50 text-gray-700 border-gray-200";
    }
  };

  const getSlaBadgeColor = (sla?: string) => {
    switch (sla) {
      case "OVERDUE":
        return "bg-rose-100 text-rose-800 border-rose-200";
      case "DUE_SOON":
        return "bg-amber-100 text-amber-800 border-amber-200";
      case "ON_TRACK":
        return "bg-emerald-100 text-emerald-800 border-emerald-200";
      default:
        return "bg-gray-100 text-gray-500 border-gray-200";
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/40 backdrop-blur-sm transition-opacity">
      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-2xl bg-white shadow-2xl flex flex-col">
          {/* Header */}
          <div className="border-b border-gray-200 px-6 py-4 bg-gray-50 flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="rounded bg-black px-2 py-0.5 text-[11px] font-bold text-white uppercase tracking-wider">
                  {item.exception_type}
                </span>
                {item.is_blocking && (
                  <span className="rounded bg-rose-600 px-2 py-0.5 text-[11px] font-bold text-white uppercase tracking-wider">
                    Blocker Gate
                  </span>
                )}
                <span
                  className={`rounded border px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ${getPriorityBadgeColor(
                    item.priority
                  )}`}
                >
                  {item.priority}
                  {item.manual_priority && " (Overridden)"}
                </span>
                <span
                  className={`rounded border px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ${getStatusBadgeColor(
                    item.status
                  )}`}
                >
                  {item.status.replace(/_/g, " ")}
                </span>
                {item.sla_status && item.sla_status !== "NO_DUE_DATE" && (
                  <span
                    className={`rounded border px-2 py-0.5 text-[11px] font-medium ${getSlaBadgeColor(
                      item.sla_status
                    )}`}
                  >
                    {item.sla_status.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <h2 className="mt-2 text-[17px] font-semibold text-gray-900">
                Invoice {item.invoice_number || item.record_id}
              </h2>
              <p className="text-[12px] text-gray-500">
                {item.supplier_name} • GSTIN: {item.supplier_gstin}
              </p>
            </div>

            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-200 hover:text-gray-700 transition-colors"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Feedback Banners */}
          {actionMessage && (
            <div className="bg-emerald-50 border-b border-emerald-200 px-6 py-2.5 text-[12px] text-emerald-800 flex items-center justify-between">
              <span>{actionMessage}</span>
              <button onClick={() => setActionMessage(null)} className="text-emerald-600 hover:text-emerald-900 font-bold">
                ✕
              </button>
            </div>
          )}
          {actionError && (
            <div className="bg-rose-50 border-b border-rose-200 px-6 py-2.5 text-[12px] text-rose-800 flex items-center justify-between">
              <span>{actionError}</span>
              <button onClick={() => setActionError(null)} className="text-rose-600 hover:text-rose-900 font-bold">
                ✕
              </button>
            </div>
          )}

          {/* Key Metrics Banner */}
          <div className="grid grid-cols-3 gap-2 px-6 py-3 bg-white border-b border-gray-100 text-[12px]">
            <div>
              <span className="text-gray-400 block text-[11px]">ITC at Stake</span>
              <span className="font-semibold text-gray-900 text-[14px]">
                {formatINR(item.itc_impact)}
              </span>
            </div>
            <div>
              <span className="text-gray-400 block text-[11px]">Invoice Date</span>
              <span className="font-medium text-gray-700">
                {item.invoice_date || "—"} ({item.age_days}d ago)
              </span>
            </div>
            <div>
              <span className="text-gray-400 block text-[11px]">Authoritative Revalidation</span>
              <span
                className={`inline-flex items-center gap-1.5 px-2 py-0.5 mt-0.5 rounded text-[11px] font-semibold border ${revalBadgeStyle.badgeBg} ${revalBadgeStyle.badgeText} ${revalBadgeStyle.badgeBorder}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${revalBadgeStyle.dotColor}`} />
                {revalStatusLabel}
              </span>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200 px-6 bg-gray-50/50">
            <button
              onClick={() => setActiveTab("overview")}
              className={`py-2.5 px-3 text-[12.5px] font-medium border-b-2 transition-colors ${
                activeTab === "overview"
                  ? "border-black text-black font-semibold"
                  : "border-transparent text-gray-500 hover:text-gray-800"
              }`}
            >
              Overview & Guidance
            </button>
            <button
              onClick={() => setActiveTab("vendor")}
              className={`py-2.5 px-3 text-[12.5px] font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                activeTab === "vendor"
                  ? "border-black text-black font-semibold"
                  : "border-transparent text-gray-500 hover:text-gray-800"
              }`}
            >
              <span>Vendor Resolution</span>
              {vendorProfile && (
                <span
                  className={`rounded-full px-1.5 py-0.2 text-[10px] font-semibold border ${
                    vendorProfile.risk_tier === "CRITICAL_RISK"
                      ? "bg-rose-100 text-rose-800 border-rose-200"
                      : vendorProfile.risk_tier === "HIGH_RISK"
                      ? "bg-orange-100 text-orange-800 border-orange-200"
                      : "bg-emerald-100 text-emerald-800 border-emerald-200"
                  }`}
                >
                  {vendorProfile.risk_score}/100
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("timeline")}
              className={`py-2.5 px-3 text-[12.5px] font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                activeTab === "timeline"
                  ? "border-black text-black font-semibold"
                  : "border-transparent text-gray-500 hover:text-gray-800"
              }`}
            >
              <span>Activity Timeline</span>
              {events.length > 0 && (
                <span className="rounded-full bg-gray-200 px-1.5 py-0.2 text-[10.5px] text-gray-700 font-semibold">
                  {events.length}
                </span>
              )}
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
            {activeTab === "overview" ? (
              <>
                {/* Phase 5.4: Deterministic Resolution Intelligence Section */}
                <div className="rounded-xl border border-indigo-200 bg-gradient-to-b from-indigo-50/70 to-white p-5 space-y-5 shadow-sm">
                  {/* Header */}
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-600 text-white tracking-wider uppercase">
                          Phase 5.4
                        </span>
                        <span className="text-[14px] font-bold text-gray-900">
                          Resolution Intelligence & Insights
                        </span>
                        <span className="rounded bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold text-indigo-800 border border-indigo-200">
                          Deterministic Read-Only
                        </span>
                      </div>
                      <p className="mt-1 text-[12px] text-gray-600">
                        Live synthesis of root cause, cross-source evidence, operational friction, and next action.
                      </p>
                    </div>
                    {isIntelligenceLoading && (
                      <span className="text-[11px] text-indigo-600 font-medium animate-pulse">
                        Analyzing…
                      </span>
                    )}
                  </div>

                  {isIntelligenceLoading && !intelligenceData && (
                    <div className="space-y-3 py-4 animate-pulse">
                      <div className="h-4 bg-indigo-100 rounded w-3/4"></div>
                      <div className="h-4 bg-indigo-50 rounded w-1/2"></div>
                      <div className="h-16 bg-gray-100 rounded w-full"></div>
                    </div>
                  )}

                  {intelligenceData && (
                    <>
                      {/* 1. Root Cause Explanation */}
                      <div className="rounded-lg bg-white border border-gray-200 p-4 space-y-2.5">
                        <div className="flex items-center justify-between">
                          <h4 className="text-[12.5px] font-bold text-gray-900 flex items-center gap-2">
                            <span className="h-2 w-2 rounded-full bg-indigo-600"></span>
                            Root Cause Explanation
                          </h4>
                          <span
                            className={`px-2 py-0.5 rounded text-[10.5px] font-semibold border ${
                              intelligenceData.root_cause_explanation.confidence_level === "HIGH"
                                ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                                : intelligenceData.root_cause_explanation.confidence_level === "MEDIUM"
                                ? "bg-amber-50 text-amber-800 border-amber-200"
                                : "bg-gray-50 text-gray-700 border-gray-200"
                            }`}
                          >
                            Confidence: {intelligenceData.root_cause_explanation.confidence_level}
                          </span>
                        </div>
                        <div className="text-[12px] space-y-1.5 text-gray-700 leading-relaxed">
                          <p>
                            <strong className="text-gray-900">What Happened:</strong>{" "}
                            {intelligenceData.root_cause_explanation.what_happened}
                          </p>
                          <p>
                            <strong className="text-gray-900">Likely Cause:</strong>{" "}
                            {intelligenceData.root_cause_explanation.likely_root_cause}
                          </p>
                          <p>
                            <strong className="text-gray-900">Statutory Context:</strong>{" "}
                            <span className="text-gray-600 italic">
                              {intelligenceData.root_cause_explanation.statutory_context}
                            </span>
                          </p>
                          {intelligenceData.root_cause_explanation.confidence_rationale && (
                            <p className="text-[11px] text-gray-500 pt-1 border-t border-gray-100">
                              <span className="font-semibold text-gray-600">Confidence Rationale:</span>{" "}
                              {intelligenceData.root_cause_explanation.confidence_rationale}
                            </p>
                          )}
                        </div>
                      </div>

                      {/* 2. Concrete Evidence Points */}
                      {intelligenceData.evidence && intelligenceData.evidence.length > 0 && (
                        <div className="rounded-lg bg-white border border-gray-200 p-4 space-y-3">
                          <h4 className="text-[12.5px] font-bold text-gray-900 flex items-center gap-2">
                            <span className="h-2 w-2 rounded-full bg-blue-600"></span>
                            Supporting Evidence ({intelligenceData.evidence.length})
                          </h4>
                          <div className="space-y-2">
                            {intelligenceData.evidence.map((ev, idx) => (
                              <div
                                key={idx}
                                className="flex items-start justify-between gap-3 p-2.5 rounded-lg bg-gray-50/70 border border-gray-100 text-[11.5px]"
                              >
                                <div className="space-y-0.5 flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className="font-semibold text-gray-900">{ev.factor}</span>
                                    <span className="font-mono text-[9.5px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                                      {ev.source}
                                    </span>
                                  </div>
                                  <p className="text-gray-700 leading-snug">{ev.finding}</p>
                                </div>
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold border uppercase shrink-0 ${
                                    ev.severity === "CRITICAL"
                                      ? "bg-rose-50 text-rose-700 border-rose-200"
                                      : ev.severity === "HIGH"
                                      ? "bg-orange-50 text-orange-700 border-orange-200"
                                      : ev.severity === "MEDIUM"
                                      ? "bg-amber-50 text-amber-700 border-amber-200"
                                      : ev.severity === "LOW"
                                      ? "bg-blue-50 text-blue-700 border-blue-200"
                                      : "bg-gray-50 text-gray-600 border-gray-200"
                                  }`}
                                >
                                  {ev.severity}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 3. Operational Resolution Difficulty & Disclaimer */}
                      <div className="rounded-lg bg-white border border-gray-200 p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <div>
                            <h4 className="text-[12.5px] font-bold text-gray-900 flex items-center gap-2">
                              <span className="h-2 w-2 rounded-full bg-purple-600"></span>
                              Operational Resolution Difficulty
                            </h4>
                            <span className="text-[11px] text-gray-500">
                              Deterministic friction assessment (0–100)
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span
                              className={`px-2 py-0.5 rounded text-[11px] font-bold uppercase border ${
                                intelligenceData.resolution_difficulty.tier === "VERY_HIGH"
                                  ? "bg-rose-50 text-rose-800 border-rose-200"
                                  : intelligenceData.resolution_difficulty.tier === "HIGH"
                                  ? "bg-orange-50 text-orange-800 border-orange-200"
                                  : intelligenceData.resolution_difficulty.tier === "MEDIUM"
                                  ? "bg-amber-50 text-amber-800 border-amber-200"
                                  : "bg-emerald-50 text-emerald-800 border-emerald-200"
                              }`}
                            >
                              {intelligenceData.resolution_difficulty.tier.replace(/_/g, " ")} • {intelligenceData.resolution_difficulty.score}/100
                            </span>
                          </div>
                        </div>

                        {/* Progress bar */}
                        <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              intelligenceData.resolution_difficulty.score >= 75
                                ? "bg-rose-500"
                                : intelligenceData.resolution_difficulty.score >= 50
                                ? "bg-orange-500"
                                : intelligenceData.resolution_difficulty.score >= 25
                                ? "bg-amber-500"
                                : "bg-emerald-500"
                            }`}
                            style={{ width: `${Math.min(100, Math.max(5, intelligenceData.resolution_difficulty.score))}%` }}
                          />
                        </div>

                        {/* Contributing factors */}
                        {intelligenceData.resolution_difficulty.factors && intelligenceData.resolution_difficulty.factors.length > 0 && (
                          <div className="space-y-1.5 pt-1">
                            <span className="text-[11px] font-semibold text-gray-700 block">
                              Friction Factors:
                            </span>
                            {intelligenceData.resolution_difficulty.factors.map((f, idx) => (
                              <div key={idx} className="flex items-center justify-between text-[11px] text-gray-600 bg-gray-50 px-2 py-1 rounded">
                                <span>
                                  <strong className="text-gray-800">{f.dimension}:</strong> {f.rationale}
                                </span>
                                <span className="font-semibold text-purple-700 shrink-0 ml-2">
                                  +{f.impact_points} pts
                                </span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Mandatory Disclaimer */}
                        <div className="rounded border border-amber-200 bg-amber-50/60 p-2 text-[10.5px] text-amber-900 leading-snug">
                          <strong>Notice:</strong> {intelligenceData.resolution_difficulty.disclaimer}
                        </div>
                      </div>

                      {/* 4. Next Best Action (with 1-click trigger) */}
                      <div className="rounded-lg bg-white border-2 border-indigo-300 p-4 space-y-3 shadow-sm">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="rounded bg-indigo-600 text-white px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider">
                              Next Best Action
                            </span>
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase border ${
                                intelligenceData.next_best_action.urgency === "IMMEDIATE"
                                  ? "bg-rose-100 text-rose-800 border-rose-200"
                                  : intelligenceData.next_best_action.urgency === "HIGH"
                                  ? "bg-orange-100 text-orange-800 border-orange-200"
                                  : "bg-blue-100 text-blue-800 border-blue-200"
                              }`}
                            >
                              {intelligenceData.next_best_action.urgency}
                            </span>
                          </div>
                          {intelligenceData.next_best_action.requires_role && (
                            <span className="text-[10px] text-gray-500">
                              Role: {intelligenceData.next_best_action.requires_role}
                            </span>
                          )}
                        </div>

                        <div>
                          <h5 className="text-[13px] font-bold text-gray-900">
                            {intelligenceData.next_best_action.title}
                          </h5>
                          <p className="mt-1 text-[12px] text-gray-700 leading-relaxed">
                            {intelligenceData.next_best_action.description}
                          </p>
                        </div>

                        {intelligenceData.next_best_action.prerequisites && intelligenceData.next_best_action.prerequisites.length > 0 && (
                          <div className="text-[11px] text-gray-500 bg-gray-50 p-2 rounded">
                            <span className="font-semibold text-gray-700">Pre-conditions: </span>
                            {intelligenceData.next_best_action.prerequisites.join(" • ")}
                          </div>
                        )}

                        {/* 1-Click Action Buttons */}
                        <div className="pt-2 flex items-center gap-2">
                          {intelligenceData.next_best_action.action_type === "DISPATCH_VENDOR_FOLLOWUP" && (
                            <button
                              onClick={() => setIsContactModalOpen(true)}
                              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-indigo-700 shadow-sm transition-colors flex items-center gap-1.5"
                            >
                              <span>Dispatch Vendor Communication</span>
                              <span>→</span>
                            </button>
                          )}

                          {intelligenceData.next_best_action.action_type === "RECORD_VENDOR_RESPONSE" && (
                            <button
                              onClick={() => setIsResponseModalOpen(true)}
                              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-indigo-700 shadow-sm transition-colors flex items-center gap-1.5"
                            >
                              <span>Record Vendor Response</span>
                              <span>→</span>
                            </button>
                          )}

                          {intelligenceData.next_best_action.action_type === "DISPOSITION_OR_RESOLVE" && (
                            <button
                              onClick={() => setIsResolutionOpen(true)}
                              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-emerald-700 shadow-sm transition-colors flex items-center gap-1.5"
                            >
                              <span>Apply CA Resolution</span>
                              <span>→</span>
                            </button>
                          )}

                          {intelligenceData.next_best_action.action_type === "REVALIDATE_INVOICE" && (
                            <button
                              disabled={isRevalidating}
                              onClick={handleRevalidate}
                              className="rounded-lg bg-blue-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-blue-700 shadow-sm transition-colors flex items-center gap-1.5"
                            >
                              <span>{isRevalidating ? "Requesting…" : "Request Revalidation"}</span>
                              <span>→</span>
                            </button>
                          )}

                          {intelligenceData.next_best_action.action_type === "SWITCH_VENDOR_TAB" && (
                            <button
                              onClick={() => setActiveTab("vendor")}
                              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-indigo-700 shadow-sm transition-colors flex items-center gap-1.5"
                            >
                              <span>View Vendor Resolution Tab</span>
                              <span>→</span>
                            </button>
                          )}

                          {intelligenceData.next_best_action.action_type === "SCHEDULE_FOLLOWUP" && (
                            <button
                              onClick={() => setIsScheduleFollowupOpen(true)}
                              className="rounded-lg bg-purple-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-purple-700 shadow-sm transition-colors flex items-center gap-1.5"
                            >
                              <span>Schedule Next Follow-up</span>
                              <span>→</span>
                            </button>
                          )}
                        </div>
                      </div>

                      {/* 5. Revalidation Guidance */}
                      <div className="rounded-lg bg-white border border-gray-200 p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <h4 className="text-[12.5px] font-bold text-gray-900 flex items-center gap-2">
                            <span className="h-2 w-2 rounded-full bg-teal-600"></span>
                            Revalidation Readiness
                          </h4>
                          <span
                            className={`px-2 py-0.5 rounded text-[10.5px] font-bold uppercase border ${
                              intelligenceData.revalidation_guidance.status === "READY"
                                ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                                : intelligenceData.revalidation_guidance.status === "NOT_READY"
                                ? "bg-amber-50 text-amber-800 border-amber-200"
                                : "bg-gray-50 text-gray-700 border-gray-200"
                            }`}
                          >
                            {intelligenceData.revalidation_guidance.status.replace(/_/g, " ")}
                          </span>
                        </div>

                        <p className="text-[12px] text-gray-700 leading-snug">
                          {intelligenceData.revalidation_guidance.summary}
                        </p>

                        {intelligenceData.revalidation_guidance.prerequisites && intelligenceData.revalidation_guidance.prerequisites.length > 0 && (
                          <div className="space-y-1.5 pt-1">
                            <span className="text-[11px] font-semibold text-gray-600 block">
                              Prerequisites Checklist:
                            </span>
                            {intelligenceData.revalidation_guidance.prerequisites.map((p, idx) => (
                              <div key={idx} className="flex items-center gap-2 text-[11.5px]">
                                {p.satisfied ? (
                                  <span className="text-emerald-600 font-bold">✓</span>
                                ) : (
                                  <span className="text-amber-500 font-bold">○</span>
                                )}
                                <span className={p.satisfied ? "text-gray-800" : "text-gray-500"}>
                                  {p.item}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>

                {/* Phase 5.5: Dedicated Authoritative Revalidation Section */}
                <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4 shadow-sm">
                  {/* Header */}
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-teal-700 text-white tracking-wider uppercase">
                          Phase 5.5
                        </span>
                        <h3 className="text-[14px] font-bold text-gray-900">
                          Authoritative Revalidation
                        </h3>
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-semibold border ${revalBadgeStyle.badgeBg} ${revalBadgeStyle.badgeText} ${revalBadgeStyle.badgeBorder}`}
                        >
                          <span className={`h-1.5 w-1.5 rounded-full ${revalBadgeStyle.dotColor}`} />
                          {revalStatusLabel}
                        </span>
                      </div>
                      <p className="mt-1 text-[12px] text-gray-600">
                        Reconciliation verification of exception status against authoritative GST data.
                      </p>
                    </div>

                    {/* Action button in header */}
                    {revalActionPermission.allowed && (
                      <button
                        disabled={isRevalidating}
                        onClick={handleRevalidate}
                        className="rounded-lg bg-black px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-gray-800 disabled:opacity-50 transition-colors shadow-sm"
                      >
                        {isRevalidating
                          ? "Revalidating…"
                          : effectiveRevalStatus === "ERROR" || effectiveRevalStatus === "NOT_REVALIDATED"
                          ? "Retry Revalidation"
                          : effectiveRevalStatus === "PERSISTS"
                          ? "Re-request Revalidation"
                          : "Request Revalidation"}
                      </button>
                    )}
                    {canExecuteRevalidation(effectiveRevalStatus, item.exception_type) && (
                      <button
                        disabled={isRevalidating}
                        onClick={handleExecuteRevalidation}
                        className="rounded-lg bg-indigo-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors shadow-sm"
                      >
                        {isRevalidating ? "Executing…" : "Execute Revalidation"}
                      </button>
                    )}
                    {effectiveRevalStatus === "REVALIDATING" && (
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-[12px] font-medium text-gray-500">
                        <span className="h-2 w-2 rounded-full bg-blue-600 animate-ping" />
                        Evaluating…
                      </span>
                    )}
                  </div>

                  {/* NONE */}
                  {effectiveRevalStatus === "NONE" && (
                    <div className="rounded-lg bg-gray-50 border border-gray-200 p-4 space-y-2">
                      <p className="text-[12.5px] text-gray-700">
                        This exception has not yet undergone authoritative revalidation against a subsequent reconciliation run.
                      </p>
                      <p className="text-[11.5px] text-gray-500">
                        When a new GSTR-2B or Purchase Register reconciliation run completes, requesting revalidation will compare this invoice against fresh authoritative reconciliation outcomes.
                      </p>
                      {revalActionPermission.reason && (
                        <p className="text-[11.5px] text-amber-700 font-medium">
                          {revalActionPermission.reason}
                        </p>
                      )}
                    </div>
                  )}

                  {/* PENDING */}
                  {effectiveRevalStatus === "PENDING" && (
                    <div className="rounded-lg bg-indigo-50/70 border border-indigo-200 p-4 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-indigo-900 text-[12.5px] flex items-center gap-1.5">
                          <span className="h-2 w-2 rounded-full bg-indigo-600" />
                          Revalidation queued for authoritative reconciliation
                        </span>
                        {item.revalidation_requested_at && (
                          <span className="text-[11px] text-indigo-700 font-medium">
                            Requested:{" "}
                            {new Date(item.revalidation_requested_at).toLocaleString("en-IN", {
                              day: "numeric",
                              month: "short",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                        )}
                      </div>
                      <p className="text-[12px] text-indigo-950 leading-relaxed">
                        Evaluation uses authoritative reconciliation data. ReconDesk will evaluate this invoice against the latest eligible completed reconciliation run.
                      </p>
                      <div className="flex items-center justify-between gap-3 pt-1">
                        <div className="text-[11px] text-indigo-800 bg-white/80 rounded border border-indigo-100 p-2 flex-1">
                          <strong>Status:</strong> Waiting for reconciliation evaluation. No clearance or outcome is assumed until the authoritative comparison executes.
                        </div>
                        {canExecuteRevalidation(effectiveRevalStatus, item.exception_type) && (
                          <button
                            disabled={isRevalidating}
                            onClick={handleExecuteRevalidation}
                            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors shadow-sm shrink-0"
                          >
                            {isRevalidating ? "Executing…" : "Execute Revalidation"}
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                  {/* REVALIDATING */}
                  {effectiveRevalStatus === "REVALIDATING" && (
                    <div className="rounded-lg bg-blue-50/70 border border-blue-200 p-4 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-blue-900 text-[12.5px] flex items-center gap-1.5">
                          <span className="h-2 w-2 rounded-full bg-blue-600 animate-pulse" />
                          Revalidation in progress
                        </span>
                        <span className="text-[11px] text-blue-700 font-mono animate-pulse">
                          Evaluating outcomes…
                        </span>
                      </div>
                      <p className="text-[12px] text-blue-950 leading-relaxed">
                        Authoritative reconciliation outcome comparison is currently executing. Evaluating invoice business identity against fresh authoritative OutcomeRows.
                      </p>
                      <div className="text-[11px] text-blue-800 bg-white/80 rounded border border-blue-100 p-2">
                        Live evaluation active. Results will refresh automatically upon completion.
                      </div>
                    </div>
                  )}

                  {/* CLEARED */}
                  {effectiveRevalStatus === "CLEARED" && (
                    <div className="rounded-lg bg-emerald-50/80 border border-emerald-200 p-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-emerald-600" />
                        <h4 className="font-bold text-emerald-950 text-[13px]">
                          Authoritative reconciliation indicates that this exception no longer applies.
                        </h4>
                      </div>

                      <div className="grid grid-cols-2 gap-3 text-[12px] bg-white rounded-lg p-3 border border-emerald-100">
                        <div>
                          <span className="text-gray-400 block text-[11px]">Previous Exception</span>
                          <span className="font-semibold text-gray-800 font-mono text-[11.5px]">
                            {prevException}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-400 block text-[11px]">Resulting Classification</span>
                          <span className="font-semibold text-emerald-700">
                            Cleared (Eligible Credit)
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-400 block text-[11px]">Tax Discrepancy Before</span>
                          <span className="text-gray-700 font-medium">
                            {taxDiffBeforePaise != null ? formatINR(taxDiffBeforePaise / 100) : "—"}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-400 block text-[11px]">Tax Discrepancy After</span>
                          <span className="text-emerald-700 font-bold">
                            {formatTaxDiffAfter(taxDiffAfterPaise)}
                          </span>
                        </div>
                        {authoritativeRef && (
                          <div className="col-span-2 border-t border-gray-100 pt-1.5">
                            <span className="text-gray-400 block text-[10.5px]">Authoritative Record Reference</span>
                            <span className="font-mono text-gray-600 text-[11px]">{authoritativeRef}</span>
                          </div>
                        )}
                      </div>

                      {/* Maker-checker enforcement */}
                      {isMakerCheckerRequired(item) ? (
                        <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-[12px] text-amber-900 space-y-1">
                          <div className="flex items-center gap-1.5 font-bold">
                            <span className="text-amber-700">⚠️</span>
                            CA review required before final resolution.
                          </div>
                          <p className="text-[11.5px] text-amber-800 leading-snug">
                            This item is a blocking exception subject to maker-checker governance. Authoritative clearance is recorded, but final operational closure requires CA sign-off.
                          </p>
                        </div>
                      ) : (
                        <div className="rounded-lg bg-emerald-100/60 border border-emerald-200 p-2.5 text-[11.5px] text-emerald-900">
                          Operational resolution: <strong>RESOLVED</strong> (Vendor correction verified via authoritative reconciliation).
                        </div>
                      )}
                    </div>
                  )}

                  {/* PERSISTS */}
                  {effectiveRevalStatus === "PERSISTS" && (
                    <div className="rounded-lg bg-rose-50/80 border border-rose-200 p-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-rose-600" />
                        <h4 className="font-bold text-rose-950 text-[13px]">
                          The authoritative reconciliation still shows this exception.
                        </h4>
                      </div>

                      <div className="bg-white rounded-lg p-3 border border-rose-100 space-y-2 text-[12px]">
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <span className="text-gray-400 block text-[11px]">Exception Category</span>
                            <span className="font-semibold text-rose-800 font-mono text-[11.5px]">
                              {item.exception_type}
                            </span>
                          </div>
                          <div>
                            <span className="text-gray-400 block text-[11px]">Tax at Stake</span>
                            <span className="font-semibold text-gray-800">
                              {formatINR(item.itc_impact)}
                            </span>
                          </div>
                        </div>
                        {comparisonReason && (
                          <div className="border-t border-gray-100 pt-1.5">
                            <span className="text-gray-400 block text-[10.5px]">Authoritative Difference / Evidence</span>
                            <p className="text-gray-800 text-[11.5px] mt-0.5 leading-snug">
                              {comparisonReason}
                            </p>
                          </div>
                        )}
                        <div className="border-t border-gray-100 pt-1.5">
                          <span className="text-gray-400 block text-[10.5px]">Recommended Next Action</span>
                          <p className="text-gray-700 text-[11.5px] mt-0.5 font-medium">
                            {item.next_action || "Follow up with supplier for GSTR-1 amendment or invoice correction."}
                          </p>
                        </div>
                      </div>

                      <p className="text-[11px] text-gray-500 italic">
                        Note: Objective reconciliation outcome. Does not automatically imply vendor non-compliance or error.
                      </p>
                    </div>
                  )}

                  {/* CHANGED */}
                  {effectiveRevalStatus === "CHANGED" && (
                    <div className="rounded-lg bg-amber-50/80 border border-amber-200 p-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-amber-600" />
                        <h4 className="font-bold text-amber-950 text-[13px]">
                          The invoice was found again, but its authoritative exception state changed.
                        </h4>
                      </div>

                      <div className="bg-white rounded-lg p-3 border border-amber-100 space-y-2 text-[12px]">
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <span className="text-gray-400 block text-[11px]">Previous Exception</span>
                            <span className="font-mono text-gray-800 text-[11.5px]">{prevException}</span>
                          </div>
                          <div>
                            <span className="text-gray-400 block text-[11px]">New Exception</span>
                            <span className="font-mono text-amber-800 font-bold text-[11.5px]">
                              {newException || "MODIFIED"}
                            </span>
                          </div>
                          <div>
                            <span className="text-gray-400 block text-[11px]">Difference Before</span>
                            <span className="text-gray-700">
                              {taxDiffBeforePaise != null ? formatINR(taxDiffBeforePaise / 100) : "—"}
                            </span>
                          </div>
                          <div>
                            <span className="text-gray-400 block text-[11px]">Difference After</span>
                            <span className="text-gray-900 font-semibold">
                              {formatTaxDiffAfter(taxDiffAfterPaise)}
                            </span>
                          </div>
                        </div>
                        {comparisonReason && (
                          <div className="border-t border-gray-100 pt-1.5">
                            <span className="text-gray-400 block text-[10.5px]">Authoritative Comparison Evidence</span>
                            <p className="text-gray-800 text-[11.5px] mt-0.5">{comparisonReason}</p>
                          </div>
                        )}
                      </div>

                      <p className="text-[11.5px] text-amber-900 font-medium">
                        The exception is not cleared; the invoice discrepancy has altered classification in the latest reconciliation run.
                      </p>
                    </div>
                  )}

                  {/* ERROR */}
                  {effectiveRevalStatus === "ERROR" && (
                    <div className="rounded-lg bg-red-50/80 border border-red-200 p-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-red-600" />
                        <h4 className="font-bold text-red-950 text-[13px]">
                          Revalidation could not be completed.
                        </h4>
                      </div>
                      <p className="text-[12px] text-red-900 bg-white rounded p-3 border border-red-100 leading-relaxed">
                        {sanitizeTechnicalReason(
                          latestRevalEvent?.metadata?.error_message || latestRevalEvent?.note || actionError
                        )}
                      </p>
                      <div className="flex items-center justify-between pt-1">
                        <span className="text-[11px] text-gray-500">
                          The previous work item state was preserved.
                        </span>
                        <button
                          disabled={isRevalidating}
                          onClick={handleRevalidate}
                          className="rounded-lg bg-red-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-red-700 disabled:opacity-50 shadow-sm"
                        >
                          {isRevalidating ? "Retrying…" : "Retry Revalidation"}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* NOT_REVALIDATED */}
                  {effectiveRevalStatus === "NOT_REVALIDATED" && (
                    <div className="rounded-lg bg-gray-50 border border-gray-200 p-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-gray-500" />
                        <h4 className="font-bold text-gray-900 text-[13px]">
                          ReconDesk could not establish a valid authoritative comparison.
                        </h4>
                      </div>
                      <p className="text-[12px] text-gray-800 bg-white rounded p-3 border border-gray-200 leading-relaxed">
                        {getNotRevalidatedExplanation(latestRevalEvent?.metadata?.reason, comparisonReason)}
                      </p>
                      <div className="flex items-center justify-between pt-1">
                        <span className="text-[11px] text-gray-500">
                          Status is not marked as PERSISTS. Authoritative comparison requires an eligible completed run.
                        </span>
                        {canRetryRevalidation(effectiveRevalStatus) && (
                          <button
                            disabled={isRevalidating}
                            onClick={handleRevalidate}
                            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-[12px] font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                          >
                            {isRevalidating ? "Retrying…" : "Retry Revalidation"}
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Authoritative Comparison Run Card (when target run ID exists) */}
                  {revalTargetRunId && (
                    <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3.5 space-y-2 text-[12px]">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-slate-600 flex items-center gap-1.5">
                          <span className="h-1.5 w-1.5 rounded-full bg-slate-700" />
                          Authoritative Comparison
                        </span>
                        <span className="text-[10px] font-mono text-slate-600 bg-white border border-slate-200 px-1.5 py-0.5 rounded">
                          Authoritative GST Source
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-[11.5px] pt-1">
                        <div>
                          <span className="text-gray-400 block text-[10.5px]">Target Reconciliation Run</span>
                          <Link
                            href={`/reconcile/runs/${revalTargetRunId}/results?search=${encodeURIComponent(
                              item.invoice_number || ""
                            )}`}
                            target="_blank"
                            className="font-mono text-indigo-600 underline font-medium hover:text-indigo-800"
                          >
                            {revalTargetRunId} →
                          </Link>
                        </div>
                        <div>
                          <span className="text-gray-400 block text-[10.5px]">Comparison Result</span>
                          <span className="font-semibold text-gray-900">{revalStatusLabel}</span>
                        </div>
                        {latestRevalEvent?.created_at && (
                          <div className="col-span-2">
                            <span className="text-gray-400 block text-[10.5px]">Evaluated Timestamp</span>
                            <span className="text-gray-700">
                              {new Date(latestRevalEvent.created_at).toLocaleString("en-IN", {
                                day: "numeric",
                                month: "short",
                                year: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Historical Baseline Guidance (Import Snapshot) */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between px-1">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
                      Historical Baseline Guidance (Import Snapshot)
                    </span>
                    <span className="text-[10px] text-gray-400">
                      Immutable Run Outputs
                    </span>
                  </div>
                  <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-4">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-blue-600 text-white px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">
                        WHAT
                      </span>
                      <h4 className="text-[12.5px] font-semibold text-blue-900">
                        Discrepancy Identified
                      </h4>
                    </div>
                    <p className="mt-1.5 text-[12.5px] text-blue-950 leading-relaxed">
                      {item.what || "Discrepancy identified in reconciliation."}
                    </p>
                  </div>

                  <div className="rounded-xl border border-amber-100 bg-amber-50/50 p-4">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-amber-600 text-white px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">
                        WHY
                      </span>
                      <h4 className="text-[12.5px] font-semibold text-amber-900">
                        Statutory / Financial Impact
                      </h4>
                    </div>
                    <p className="mt-1.5 text-[12.5px] text-amber-950 leading-relaxed">
                      {item.why || "Discrepancy impacts statutory ITC eligibility under GST laws."}
                    </p>
                  </div>

                  <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-4">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-emerald-600 text-white px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">
                        NEXT
                      </span>
                      <h4 className="text-[12.5px] font-semibold text-emerald-900">
                        Recommended Resolution Action
                      </h4>
                    </div>
                    <p className="mt-1.5 text-[12.5px] text-emerald-950 leading-relaxed">
                      {item.next_action || "Contact supplier or apply statutory audit disposition."}
                    </p>
                  </div>
                </div>

                {/* Assignment & Due Date Controls */}
                <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-4">
                  <h3 className="text-[13px] font-semibold text-gray-900">
                    Ownership & Operational Target
                  </h3>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-[11.5px] text-gray-500 mb-1">
                        Assigned Staff
                      </label>
                      <select
                        value={item.assigned_to || ""}
                        disabled={isAssigning}
                        onChange={(e) => handleAssign(e.target.value || null)}
                        className="w-full rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-[12px] text-gray-800 focus:border-black focus:outline-none cursor-pointer"
                      >
                        <option value="">Unassigned</option>
                        {teamMembers
                          ?.filter((m) => m.status === "active" && m.member_user_id)
                          .map((m) => (
                            <option key={m.member_user_id!} value={m.member_user_id!}>
                              {m.full_name?.trim() || m.email} ({m.role})
                            </option>
                          ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-[11.5px] text-gray-500 mb-1">
                        Due Date
                      </label>
                      <input
                        type="date"
                        value={dueDateInput}
                        disabled={isUpdatingDueDate}
                        onChange={(e) => handleDueDateChange(e.target.value)}
                        className="w-full rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-[12px] text-gray-800 focus:border-black focus:outline-none cursor-pointer"
                      />
                    </div>
                  </div>

                  {/* Priority Override (CA only) */}
                  <div className="pt-2 border-t border-gray-100 flex items-center justify-between text-[12px]">
                    <div>
                      <span className="text-gray-400">Current Priority:</span>{" "}
                      <span className="font-semibold text-gray-800">{item.priority}</span>
                      {item.manual_priority && (
                        <span className="text-[11px] text-amber-600 ml-1.5">
                          (Reason: {item.priority_override_reason})
                        </span>
                      )}
                    </div>
                    {isCA && (
                      <button
                        onClick={() => setIsPriorityModalOpen(true)}
                        className="rounded border border-gray-200 px-2 py-1 text-[11.5px] font-medium text-gray-700 hover:bg-gray-50"
                      >
                        Override Priority
                      </button>
                    )}
                  </div>
                </div>

                {/* Operational Quick Actions */}
                <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
                  <h3 className="text-[13px] font-semibold text-gray-900">
                    Operational State Transitions
                  </h3>

                  <div className="flex flex-wrap gap-2">
                    {item.status !== "IN_PROGRESS" && item.status !== "RESOLVED" && item.status !== "DISMISSED" && (
                      <button
                        disabled={isTransitioning}
                        onClick={() => handleStatusTransition("IN_PROGRESS")}
                        className="rounded-lg bg-blue-50 border border-blue-200 px-3 py-1.5 text-[12px] font-medium text-blue-700 hover:bg-blue-100"
                      >
                        Mark In Progress
                      </button>
                    )}

                    {item.status !== "WAITING_VENDOR" && item.status !== "RESOLVED" && item.status !== "DISMISSED" && (
                      <button
                        disabled={isTransitioning}
                        onClick={() => handleStatusTransition("WAITING_VENDOR")}
                        className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5 text-[12px] font-medium text-amber-700 hover:bg-amber-100"
                      >
                        Wait for Vendor
                      </button>
                    )}

                    {item.status !== "READY_FOR_REVIEW" && item.status !== "RESOLVED" && item.status !== "DISMISSED" && (
                      <button
                        disabled={isTransitioning}
                        onClick={() => handleStatusTransition("READY_FOR_REVIEW")}
                        className="rounded-lg bg-purple-50 border border-purple-200 px-3 py-1.5 text-[12px] font-medium text-purple-700 hover:bg-purple-100"
                      >
                        Submit for CA Review
                      </button>
                    )}

                    {item.status !== "RESOLVED" && item.status !== "DISMISSED" && (
                      <button
                        onClick={() => setIsResolutionOpen(true)}
                        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-emerald-700 shadow-sm"
                      >
                        Resolve Exception
                      </button>
                    )}

                    {item.status !== "DISMISSED" && (
                      <button
                        onClick={() => setIsDismissOpen(true)}
                        className="rounded-lg border border-gray-200 px-3 py-1.5 text-[12px] font-medium text-gray-600 hover:bg-gray-100"
                      >
                        Dismiss
                      </button>
                    )}

                    {(item.status === "RESOLVED" || item.status === "DISMISSED") && isCA && (
                      <button
                        onClick={() => setIsReopenOpen(true)}
                        className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-[12px] font-semibold text-amber-800 hover:bg-amber-100"
                      >
                        Reopen Item
                      </button>
                    )}

                    {revalActionPermission.allowed && (
                      <button
                        disabled={isRevalidating}
                        onClick={handleRevalidate}
                        className="rounded-lg border border-teal-300 bg-teal-50 px-3 py-1.5 text-[12px] font-semibold text-teal-800 hover:bg-teal-100 disabled:opacity-50"
                      >
                        {isRevalidating
                          ? "Revalidating…"
                          : effectiveRevalStatus === "ERROR" || effectiveRevalStatus === "NOT_REVALIDATED"
                          ? "Retry Revalidation"
                          : effectiveRevalStatus === "PERSISTS"
                          ? "Re-request Revalidation"
                          : "Request Revalidation"}
                      </button>
                    )}
                    {canExecuteRevalidation(effectiveRevalStatus, item.exception_type) && (
                      <button
                        disabled={isRevalidating}
                        onClick={handleExecuteRevalidation}
                        className="rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-[12px] font-semibold text-indigo-800 hover:bg-indigo-100 disabled:opacity-50"
                      >
                        {isRevalidating ? "Executing…" : "Execute Revalidation"}
                      </button>
                    )}
                    {effectiveRevalStatus === "REVALIDATING" && (
                      <button
                        disabled
                        className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-[12px] font-medium text-gray-400 cursor-not-allowed"
                      >
                        Revalidation in progress…
                      </button>
                    )}
                  </div>
                </div>

                {/* Deep Links & Provenance */}
                <div className="rounded-xl border border-gray-100 bg-gray-50 p-4 text-[12px] space-y-2">
                  <span className="text-gray-400 block text-[11px] font-medium uppercase tracking-wider">
                    Authoritative Provenance
                  </span>
                  <div className="flex items-center justify-between text-gray-600">
                    <span>Reconciliation Run ID:</span>
                    <span className="font-mono text-gray-800">{item.run_id}</span>
                  </div>
                  <div className="flex items-center justify-between text-gray-600">
                    <span>Record ID:</span>
                    <span className="font-mono text-gray-800">{item.record_id}</span>
                  </div>
                  <div className="pt-2 flex gap-3">
                    <Link
                      href={`/reconcile/runs/${item.run_id}/results?search=${encodeURIComponent(
                        item.invoice_number || ""
                      )}`}
                      className="text-black font-semibold underline text-[12px]"
                      target="_blank"
                    >
                      View in Reconciliation Outcomes →
                    </Link>
                    <Link
                      href={`/reconcile/runs/${item.run_id}/gstr3b`}
                      className="text-black font-semibold underline text-[12px]"
                      target="_blank"
                    >
                      View Table 4 Workpaper →
                    </Link>
                  </div>
                </div>
              </>
            ) : activeTab === "vendor" ? (
              /* Vendor Resolution Tab */
              <div className="space-y-6">
                {/* Vendor Profile Card */}
                <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm space-y-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <h4 className="text-[14px] font-semibold text-gray-900">
                        {vendorProfile?.vendor_name || item.supplier_name || item.vendor_name || item.supplier_gstin || "Unknown Vendor"}
                      </h4>
                      <p className="text-[12px] font-mono text-gray-500 mt-0.5">
                        GSTIN: {item.supplier_gstin || item.vendor_gstin || "—"}
                      </p>
                    </div>

                    {vendorProfile && (
                      <div className="text-right">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                            vendorProfile.risk_tier === "CRITICAL_RISK"
                              ? "bg-rose-50 text-rose-700 border-rose-200"
                              : vendorProfile.risk_tier === "HIGH_RISK"
                              ? "bg-orange-50 text-orange-700 border-orange-200"
                              : vendorProfile.risk_tier === "MEDIUM_RISK"
                              ? "bg-amber-50 text-amber-700 border-amber-200"
                              : "bg-emerald-50 text-emerald-700 border-emerald-200"
                          }`}
                        >
                          {vendorProfile.risk_tier.replace(/_/g, " ")} • {vendorProfile.risk_score}/100
                        </span>
                        <span className="block text-[10.5px] text-gray-400 mt-0.5">Compliance Risk</span>
                      </div>
                    )}
                  </div>

                  {/* Vendor Scorecard Metrics Grid */}
                  <div className="grid grid-cols-3 gap-2.5 pt-2 border-t border-gray-100 text-[11.5px]">
                    <div className="p-2 bg-gray-50 rounded-lg">
                      <span className="text-gray-400 block text-[10.5px]">Total Invoices</span>
                      <span className="font-semibold text-gray-900">
                        {vendorProfile?.total_invoices ?? "—"}
                      </span>
                    </div>

                    <div className="p-2 bg-gray-50 rounded-lg">
                      <span className="text-gray-400 block text-[10.5px]">Mismatches</span>
                      <span className="font-semibold text-gray-900">
                        {vendorProfile?.mismatch_count ?? 0} (
                        {vendorProfile?.mismatch_rate ? (vendorProfile.mismatch_rate * 100).toFixed(0) : 0}%)
                      </span>
                    </div>

                    <div className="p-2 bg-gray-50 rounded-lg">
                      <span className="text-gray-400 block text-[10.5px]">Rule 37 Overdue</span>
                      <span className="font-semibold text-gray-900">
                        {vendorProfile?.rule37_open_count ?? 0} ({formatINR(vendorProfile?.rule37_at_risk ?? 0)})
                      </span>
                    </div>

                    <div className="p-2 bg-gray-50 rounded-lg">
                      <span className="text-gray-400 block text-[10.5px]">Late Filings</span>
                      <span className="font-semibold text-gray-900">
                        {vendorProfile?.late_filing_count ?? 0}
                      </span>
                    </div>

                    <div className="p-2 bg-gray-50 rounded-lg">
                      <span className="text-gray-400 block text-[10.5px]">Open Work Items</span>
                      <span className="font-semibold text-indigo-700">
                        {vendorProfile?.open_work_item_count ?? 1} items
                      </span>
                    </div>

                    <div className="p-2 bg-gray-50 rounded-lg">
                      <span className="text-gray-400 block text-[10.5px]">Total ITC at Stake</span>
                      <span className="font-semibold text-rose-700">
                        {formatINR(vendorProfile?.itc_at_stake ?? item.itc_impact)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Resolution Action Toolbar */}
                <div className="space-y-2">
                  <h4 className="text-[12px] font-semibold text-gray-700 uppercase tracking-wider">
                    Vendor Resolution Actions
                  </h4>
                  <div className="grid grid-cols-2 gap-2.5">
                    <button
                      type="button"
                      onClick={() => setIsContactModalOpen(true)}
                      className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-indigo-200 bg-indigo-50/50 text-indigo-800 text-[12px] font-semibold hover:bg-indigo-100/70 transition-colors shadow-sm"
                    >
                      <span>💬</span> Contact Vendor (1-Click)
                    </button>

                    <button
                      type="button"
                      onClick={() => setIsResponseModalOpen(true)}
                      className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-emerald-200 bg-emerald-50/50 text-emerald-800 text-[12px] font-semibold hover:bg-emerald-100/70 transition-colors shadow-sm"
                    >
                      <span>📝</span> Record Vendor Response
                    </button>

                    <button
                      type="button"
                      onClick={() => setIsScheduleFollowupOpen(true)}
                      className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 bg-white text-gray-800 text-[12px] font-medium hover:bg-gray-50 transition-colors"
                    >
                      <span>📅</span> Schedule Follow-up SLA
                    </button>

                    <button
                      type="button"
                      onClick={handleRevalidate}
                      disabled={isRevalidating}
                      className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 bg-white text-gray-800 text-[12px] font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
                    >
                      <span>🔄</span> {isRevalidating ? "Registering…" : "Request Revalidation"}
                    </button>
                  </div>
                </div>

                {/* Communication & Follow-up History */}
                <div className="border-t border-gray-200 pt-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-[12px] font-semibold text-gray-700 uppercase tracking-wider">
                      Work Item Communication History
                    </h4>
                    <span className="text-[11px] text-gray-400">
                      {followups.length} dispatch{followups.length === 1 ? "" : "es"}
                    </span>
                  </div>

                  {followups.length === 0 ? (
                    <div className="p-4 border border-dashed border-gray-200 rounded-lg text-center">
                      <p className="text-[12px] text-gray-400">
                        No communications dispatched yet for this work item.
                      </p>
                      <button
                        type="button"
                        onClick={() => setIsContactModalOpen(true)}
                        className="mt-2 inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-indigo-600 hover:text-indigo-800"
                      >
                        Contact Vendor via WhatsApp or Email →
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      {followups.map((log) => (
                        <div
                          key={log.id}
                          className="border border-gray-200 rounded-lg p-3 bg-gray-50/50 space-y-1.5 text-[12px]"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span
                                className={`px-2 py-0.5 rounded text-[10.5px] font-bold ${
                                  log.channel === "WHATSAPP"
                                    ? "bg-emerald-100 text-emerald-800"
                                    : "bg-indigo-100 text-indigo-800"
                                }`}
                              >
                                {log.channel}
                              </span>
                              <span className="font-medium text-gray-800">
                                {log.template_type.replace(/_/g, " ")}
                              </span>
                            </div>
                            <span className="text-[11px] text-gray-400">
                              {new Date(log.dispatched_at).toLocaleString("en-IN", {
                                day: "numeric",
                                month: "short",
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </span>
                          </div>

                          <div className="text-[11.5px] text-gray-500 flex items-center justify-between">
                            <span>
                              To: {log.vendor_email || log.vendor_phone || log.supplier_name || log.supplier_gstin}
                            </span>
                            <span className="font-semibold text-gray-700">
                              {formatINR(log.at_risk_itc_rupees)}
                            </span>
                          </div>

                          {log.message_body && (
                            <p className="text-[11px] text-gray-600 bg-white border border-gray-100 rounded p-2 line-clamp-3 whitespace-pre-wrap font-mono">
                              {log.message_body}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              /* Timeline Tab */
              <div className="space-y-6">
                {/* Add Note Form */}
                <form onSubmit={handleAddNote} className="space-y-2">
                  <label className="block text-[12px] font-semibold text-gray-700">
                    Add Operational Note
                  </label>
                  <textarea
                    rows={2}
                    value={newNote}
                    onChange={(e) => setNewNote(e.target.value)}
                    placeholder="E.g., Spoke to supplier accountant; they confirmed invoice will be in Aug GSTR-1."
                    className="w-full rounded-lg border border-gray-200 p-2.5 text-[12px] text-gray-900 focus:border-black focus:outline-none"
                  />
                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={isSubmittingNote || !newNote.trim()}
                      className="rounded-lg bg-black px-3.5 py-1.5 text-[12px] font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
                    >
                      {isSubmittingNote ? "Saving…" : "Post Note"}
                    </button>
                  </div>
                </form>

                {/* Timeline Stream */}
                <div className="border-t border-gray-200 pt-4 space-y-4">
                  <h4 className="text-[12px] font-semibold text-gray-500 uppercase tracking-wider">
                    Chronological Audit Trail
                  </h4>

                  {events.length === 0 ? (
                    <p className="text-[12px] text-gray-400 py-4 text-center">
                      No operational events recorded yet.
                    </p>
                  ) : (
                    <div className="relative pl-6 space-y-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-gray-200">
                      {events.map((ev) => (
                        <div key={ev.id} className="relative text-[12px]">
                          <div
                            className={`absolute -left-6 top-1 h-3.5 w-3.5 rounded-full border-2 border-white shadow-sm ${
                              ev.event_type === "COMMUNICATION_DISPATCHED"
                                ? "bg-indigo-600"
                                : ev.event_type === "VENDOR_RESPONSE_RECORDED"
                                ? "bg-emerald-600"
                                : ev.event_type === "FOLLOWUP_SCHEDULED"
                                ? "bg-amber-600"
                                : ev.event_type === "REVALIDATION_REQUESTED"
                                ? "bg-indigo-500"
                                : ev.event_type === "REVALIDATION_STARTED"
                                ? "bg-blue-600 animate-pulse"
                                : ev.event_type === "REVALIDATION_COMPLETED"
                                ? ev.metadata?.revalidation_result === "CLEARED"
                                  ? "bg-emerald-600"
                                  : ev.metadata?.revalidation_result === "ERROR"
                                  ? "bg-red-600"
                                  : "bg-amber-600"
                                : ev.event_type === "REVALIDATION_STALE_TARGET_SKIPPED"
                                ? "bg-amber-500"
                                : "bg-black"
                            }`}
                          />
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-gray-900">
                              {ev.event_type.replace(/_/g, " ")}
                            </span>
                            <span className="text-[11px] text-gray-400">
                              {new Date(ev.created_at).toLocaleString("en-IN", {
                                day: "numeric",
                                month: "short",
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </span>
                          </div>
                          <p className="text-gray-600 mt-0.5">
                            By <span className="font-medium text-gray-800">{ev.actor_name || "System"}</span> (
                            {ev.actor_role || "system"})
                          </p>

                          {/* Event Metadata Pills */}
                          {ev.metadata && Object.keys(ev.metadata).length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1 text-[10.5px]">
                              {ev.metadata.revalidation_result && (
                                <span
                                  className={`rounded border px-1.5 py-0.5 font-bold ${
                                    ev.metadata.revalidation_result === "CLEARED"
                                      ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                                      : ev.metadata.revalidation_result === "ERROR"
                                      ? "bg-red-50 text-red-800 border-red-200"
                                      : "bg-amber-50 text-amber-800 border-amber-200"
                                  }`}
                                >
                                  Result: {ev.metadata.revalidation_result}
                                </span>
                              )}
                              {ev.metadata.target_run_id && (
                                <span className="rounded bg-slate-100 border border-slate-200 px-1.5 py-0.5 text-slate-800 font-mono">
                                  Run: {String(ev.metadata.target_run_id).slice(0, 8)}…
                                </span>
                              )}
                              {ev.metadata.new_exception_type && (
                                <span className="rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-amber-800 font-mono">
                                  New: {ev.metadata.new_exception_type}
                                </span>
                              )}
                              {ev.metadata.tax_diff_before != null && (
                                <span className="rounded bg-gray-100 border border-gray-200 px-1.5 py-0.5 text-gray-700">
                                  Before: {formatINR(ev.metadata.tax_diff_before / 100)}
                                </span>
                              )}
                              {ev.metadata.tax_diff_after != null && (
                                <span className="rounded bg-gray-100 border border-gray-200 px-1.5 py-0.5 text-gray-700">
                                  After: {formatTaxDiffAfter(Number(ev.metadata.tax_diff_after))}
                                </span>
                              )}
                              {ev.metadata.channel && (
                                <span className="rounded bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 text-indigo-700 font-medium">
                                  {ev.metadata.channel}
                                </span>
                              )}
                              {ev.metadata.template_type && (
                                <span className="rounded bg-gray-100 border border-gray-200 px-1.5 py-0.5 text-gray-700 font-mono">
                                  {ev.metadata.template_type}
                                </span>
                              )}
                              {ev.metadata.response_category && (
                                <span className="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-emerald-800 font-medium">
                                  Category: {ev.metadata.response_category}
                                </span>
                              )}
                              {ev.metadata.promised_date && (
                                <span className="rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-amber-800">
                                  Promised: {ev.metadata.promised_date}
                                </span>
                              )}
                              {ev.metadata.reason && (
                                <span className="rounded bg-gray-50 border border-gray-200 px-1.5 py-0.5 text-gray-600 font-mono">
                                  Reason: {ev.metadata.reason}
                                </span>
                              )}
                            </div>
                          )}

                          {ev.note && (
                            <p className="mt-1.5 text-gray-800 bg-gray-50 border border-gray-100 rounded-lg p-2 leading-relaxed">
                              {ev.note}
                            </p>
                          )}
                          {ev.from_status && ev.to_status && (
                            <p className="mt-1 text-[11px] text-gray-500">
                              Transition: <span className="font-medium">{ev.from_status}</span> →{" "}
                              <span className="font-medium text-black">{ev.to_status}</span>
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-gray-200 px-6 py-3 bg-gray-50 flex items-center justify-between">
            <span className="text-[11.5px] text-gray-500">
              Operational Exception Item • Phase 5.2 Lifecycle
            </span>
            <button
              onClick={onClose}
              className="rounded-lg bg-white border border-gray-200 px-4 py-1.5 text-[12px] font-medium text-gray-700 hover:bg-gray-100"
            >
              Close
            </button>
          </div>
        </div>
      </div>

      {/* Priority Override Modal */}
      {isPriorityModalOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl space-y-4">
            <h3 className="text-[15px] font-semibold text-gray-900">
              Override Operational Priority
            </h3>
            <p className="text-[12px] text-gray-500">
              System recommended: <strong>{item.system_priority || item.priority}</strong>. You can manually adjust this priority for operational dispatch.
            </p>
            <form onSubmit={handlePriorityOverride} className="space-y-3">
              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">New Priority</label>
                <select
                  value={overridePriority}
                  onChange={(e) => setOverridePriority(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 p-2 text-[12px] focus:outline-none"
                >
                  <option value="CRITICAL">CRITICAL</option>
                  <option value="HIGH">HIGH</option>
                  <option value="MEDIUM">MEDIUM</option>
                  <option value="LOW">LOW</option>
                </select>
              </div>
              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">
                  Reason for Override (Required for Audit)
                </label>
                <textarea
                  rows={2}
                  required
                  value={priorityReason}
                  onChange={(e) => setPriorityReason(e.target.value)}
                  placeholder="E.g., Client confirmed critical delivery depends on clearing this vendor."
                  className="w-full rounded-lg border border-gray-200 p-2 text-[12px] focus:outline-none"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsPriorityModalOpen(false)}
                  className="rounded-lg px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isOverridingPriority || !priorityReason.trim()}
                  className="rounded-lg bg-black px-4 py-1.5 text-[12px] font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
                >
                  {isOverridingPriority ? "Saving…" : "Confirm Override"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Resolution Modal */}
      {isResolutionOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl space-y-4">
            <h3 className="text-[15px] font-semibold text-gray-900">
              Record Operational Resolution
            </h3>
            <p className="text-[12px] text-gray-500">
              Select the structured reason how this exception was resolved.
              {!isCA && item.is_blocking && (
                <span className="block mt-1 text-amber-700 font-medium">
                  Note: As staff, recording resolution on a blocking exception will submit this item for CA approval (READY_FOR_REVIEW).
                </span>
              )}
            </p>

            <form onSubmit={handleResolve} className="space-y-3">
              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">
                  Resolution Code
                </label>
                <select
                  value={resolutionCode}
                  onChange={(e) => setResolutionCode(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 p-2 text-[12px] focus:outline-none"
                >
                  <option value="VENDOR_CORRECTION_RECEIVED">Vendor Correction Received</option>
                  <option value="VENDOR_CORRECTION_EXPECTED">Vendor Correction Expected</option>
                  <option value="VENDOR_CONTACTED">Vendor Contacted</option>
                  <option value="PAYMENT_VERIFIED">Payment Verified (&lt;180 Days)</option>
                  <option value="DOCUMENT_VERIFIED">Document & E-Way Bill Verified</option>
                  <option value="CLIENT_CONFIRMATION">Client Written Confirmation</option>
                  <option value="DUPLICATE_CONFIRMED">Duplicate Confirmed / Book Reversal</option>
                  <option value="STATUTORY_DISPOSITION_APPLIED">Statutory Disposition Applied</option>
                  <option value="NOT_ACTIONABLE">Not Actionable / Immaterial</option>
                </select>
              </div>

              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">
                  Resolution Explanatory Note (Required)
                </label>
                <textarea
                  rows={3}
                  required
                  value={resolutionNote}
                  onChange={(e) => setResolutionNote(e.target.value)}
                  placeholder="Explain the factual basis of resolution for the audit trail…"
                  className="w-full rounded-lg border border-gray-200 p-2.5 text-[12px] focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsResolutionOpen(false)}
                  className="rounded-lg px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isResolving || !resolutionNote.trim()}
                  className="rounded-lg bg-emerald-600 px-4 py-1.5 text-[12px] font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  {isResolving ? "Submitting…" : isCA ? "Approve & Resolve" : "Submit for CA Review"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Dismiss Modal */}
      {isDismissOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl space-y-4">
            <h3 className="text-[15px] font-semibold text-gray-900">
              Dismiss Exception Work Item
            </h3>
            <p className="text-[12px] text-gray-500">
              Dismissing closes the operational task without applying statutory resolution. Justification is required.
            </p>
            <form onSubmit={handleDismiss} className="space-y-3">
              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">
                  Dismissal Justification
                </label>
                <textarea
                  rows={3}
                  required
                  value={dismissReason}
                  onChange={(e) => setDismissReason(e.target.value)}
                  placeholder="Why should this exception not be acted upon?"
                  className="w-full rounded-lg border border-gray-200 p-2.5 text-[12px] focus:outline-none"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsDismissOpen(false)}
                  className="rounded-lg px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isDismissing || !dismissReason.trim()}
                  className="rounded-lg bg-gray-800 px-4 py-1.5 text-[12px] font-semibold text-white hover:bg-black disabled:opacity-50"
                >
                  {isDismissing ? "Dismissing…" : "Confirm Dismissal"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Reopen Modal */}
      {isReopenOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl space-y-4">
            <h3 className="text-[15px] font-semibold text-gray-900">
              Reopen Work Item
            </h3>
            <p className="text-[12px] text-gray-500">
              Reopening moves the exception back to active status for further investigation. Justification is required.
            </p>
            <form onSubmit={handleReopen} className="space-y-3">
              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">
                  Reason for Reopening
                </label>
                <textarea
                  rows={3}
                  required
                  value={reopenReason}
                  onChange={(e) => setReopenReason(e.target.value)}
                  placeholder="Explain why this previously closed item needs further action…"
                  className="w-full rounded-lg border border-gray-200 p-2.5 text-[12px] focus:outline-none"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsReopenOpen(false)}
                  className="rounded-lg px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isReopening || !reopenReason.trim()}
                  className="rounded-lg bg-amber-600 px-4 py-1.5 text-[12px] font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  {isReopening ? "Reopening…" : "Confirm Reopen"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Schedule Followup Modal */}
      {isScheduleFollowupOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl space-y-4">
            <h3 className="text-[15px] font-semibold text-gray-900">
              Schedule Next Follow-up
            </h3>
            <p className="text-[12px] text-gray-500">
              Set the next operational follow-up date and audit note for vendor engagement.
            </p>
            <form onSubmit={handleScheduleFollowup} className="space-y-3">
              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">
                  Target Due / Follow-up Date (Required)
                </label>
                <input
                  type="date"
                  required
                  value={followupDateInput}
                  onChange={(e) => setFollowupDateInput(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 p-2 text-[12px] focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-[11.5px] text-gray-500 mb-1">
                  Follow-up Plan Note
                </label>
                <textarea
                  rows={2}
                  value={followupNoteInput}
                  onChange={(e) => setFollowupNoteInput(e.target.value)}
                  placeholder="E.g., Call vendor accounts desk if GSTR-1 not filed by 11th."
                  className="w-full rounded-lg border border-gray-200 p-2.5 text-[12px] focus:outline-none"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsScheduleFollowupOpen(false)}
                  className="rounded-lg px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSchedulingFollowup || !followupDateInput}
                  className="rounded-lg bg-indigo-600 px-4 py-1.5 text-[12px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {isSchedulingFollowup ? "Scheduling…" : "Save Follow-up"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Contact Vendor Modal (WhatsApp / Email) */}
      <VendorCommunicationModal
        isOpen={isContactModalOpen}
        onClose={() => setIsContactModalOpen(false)}
        onDispatched={() => {
          mutateItem();
          mutateIntelligence();
          mutateFollowups();
          onUpdated();
        }}
        clientId={clientId}
        workItemId={item.id!}
        vendorGstin={item.supplier_gstin || item.vendor_gstin || ""}
        vendorName={item.supplier_name || item.vendor_name || ""}
        atRiskItcRupees={item.itc_impact ?? item.itc_amount_at_stake ?? 0}
        token={authToken}
      />

      {/* Record Vendor Response Modal */}
      <RecordVendorResponseModal
        isOpen={isResponseModalOpen}
        onClose={() => setIsResponseModalOpen(false)}
        onRecorded={() => {
          mutateItem();
          mutateIntelligence();
          mutateVendorProfile();
          onUpdated();
        }}
        workItemId={item.id!}
        vendorGstin={item.supplier_gstin || item.vendor_gstin || ""}
        vendorName={item.supplier_name || item.vendor_name || ""}
        isBlocking={item.is_blocking || false}
        currentStatus={item.status || "OPEN"}
        token={authToken}
      />
    </div>
  );
}
