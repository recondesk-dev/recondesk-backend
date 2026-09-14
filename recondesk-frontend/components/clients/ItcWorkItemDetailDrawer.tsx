"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { formatINR } from "@/lib/format";
import {
  workItemsApi,
  ItcWorkItem,
  ItcWorkItemEvent,
} from "@/lib/api";

interface TeamMember {
  id: string;
  member_user_id: string;
  full_name: string;
  email: string;
  role: string;
}

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
  const [activeTab, setActiveTab] = useState<"overview" | "timeline">("overview");
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

  // Fetch live item with events timeline
  const { data: itemData, mutate: mutateItem } = useSWR<ItcWorkItem & { events: ItcWorkItemEvent[] }>(
    workItem?.id && authToken ? [`work-item`, workItem.id] : null,
    () => workItemsApi.get(authToken, workItem!.id!),
    { refreshInterval: 0 }
  );

  // Fetch team members for assignment
  const { data: teamMembers } = useSWR<TeamMember[]>(
    authToken ? [`team-members-assign`] : null,
    async () => {
      const res = await fetch("/api/team/members?include_owner=true", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!res.ok) return [];
      return res.json();
    }
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

  const handleRevalidate = async () => {
    if (!item.id) return;
    setIsRevalidating(true);
    setActionError(null);
    try {
      await workItemsApi.revalidate(authToken, item.id);
      mutateItem();
      onUpdated();
      setActionMessage("Revalidation registered. Authoritative engine will recheck in next reconciliation.");
    } catch (err: any) {
      setActionError(err.detail || err.message || "Failed to request revalidation.");
    } finally {
      setIsRevalidating(false);
    }
  };

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
              <span className="text-gray-400 block text-[11px]">Revalidation Hook</span>
              <span className="font-medium text-gray-700">
                {item.revalidation_status || "NONE"}
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
                {/* WHAT / WHY / NEXT */}
                <div className="space-y-3">
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
                        {teamMembers?.map((m) => (
                          <option key={m.member_user_id || m.id} value={m.member_user_id}>
                            {m.full_name || m.email} ({m.role})
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

                    {item.status === "RESOLVED" && item.revalidation_status !== "PENDING" && (
                      <button
                        disabled={isRevalidating}
                        onClick={handleRevalidate}
                        className="rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-[12px] font-semibold text-blue-800 hover:bg-blue-100"
                      >
                        {isRevalidating ? "Requesting…" : "Request Revalidation (Phase 5.5)"}
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
                          <div className="absolute -left-6 top-1 h-3.5 w-3.5 rounded-full border-2 border-white bg-black shadow-sm" />
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
    </div>
  );
}
