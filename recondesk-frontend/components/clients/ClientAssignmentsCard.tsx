"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  UserCheck,
  UserPlus,
  Trash2,
  Loader2,
  AlertCircle,
  Users,
  Shield,
  FileSpreadsheet,
  CheckCircle2,
} from "lucide-react";

import { Modal } from "@/components/ui/Modal";
import { Avatar } from "@/components/ui/Avatar";
import { useToast } from "@/components/providers/ToastProvider";
import {
  clientsApi,
  isApiError,
  type ClientAssignmentItem,
  type TeamMemberListItem,
} from "@/lib/api";
import { isRoleManagerOrAbove } from "@/lib/auth-profile";

import {
  ROLE_CONFIGS,
  getRoleConfig,
  initialsFromLabel,
  canManageClientAssignments,
  type AssignmentRole,
  type RoleConfig,
} from "./clientAssignmentsLogic";

export {
  ROLE_CONFIGS,
  getRoleConfig,
  initialsFromLabel,
  canManageClientAssignments,
  type AssignmentRole,
  type RoleConfig,
};

const ICON_COMPONENTS = {
  Shield,
  ShieldCheck,
  UserCheck,
  FileSpreadsheet,
  Users,
};

interface ClientAssignmentsCardProps {
  clientId: string;
  authToken: string | null;
  currentUserRole?: string | null;
  teamMembers?: TeamMemberListItem[];
  onAssignmentChanged?: () => void;
}

export function ClientAssignmentsCard({
  clientId,
  authToken,
  currentUserRole,
  teamMembers = [],
  onAssignmentChanged,
}: ClientAssignmentsCardProps) {
  const toast = useToast();
  const canManage = isRoleManagerOrAbove(currentUserRole);

  const swrKey =
    authToken && clientId ? (["client-assignments", authToken, clientId] as const) : null;

  const {
    data: assignmentsData,
    error: assignmentsError,
    isLoading,
    mutate: mutateAssignments,
  } = useSWR(
    swrKey,
    ([, token, cid]) => clientsApi.listAssignments(token, cid),
    { revalidateOnFocus: false }
  );

  const assignments: ClientAssignmentItem[] = useMemo(() => {
    return assignmentsData?.assignments || [];
  }, [assignmentsData]);

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [selectedRole, setSelectedRole] = useState<AssignmentRole>("preparer");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Deleting state tracking
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Filter eligible active team members for assignment
  const eligibleMembers = useMemo(() => {
    return (teamMembers || []).filter(
      (m): m is TeamMemberListItem & { member_user_id: string } =>
        m.status === "active" && typeof m.member_user_id === "string" && m.member_user_id.length > 0
    );
  }, [teamMembers]);

  const openAddModal = () => {
    setActionError(null);
    if (eligibleMembers.length > 0 && !selectedUserId) {
      setSelectedUserId(eligibleMembers[0].member_user_id || "");
    }
    setModalOpen(true);
  };

  const closeAddModal = () => {
    if (isSubmitting) return;
    setModalOpen(false);
    setActionError(null);
  };

  const handleAddAssignment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authToken || !clientId) return;
    if (!selectedUserId.trim()) {
      setActionError("Please select a team member.");
      return;
    }

    setIsSubmitting(true);
    setActionError(null);

    try {
      await clientsApi.addAssignment(authToken, clientId, selectedUserId.trim(), selectedRole);
      toast("Role assigned successfully", "success");
      setModalOpen(false);
      await mutateAssignments();
      onAssignmentChanged?.();
    } catch (err: unknown) {
      const msg = isApiError(err) ? err.detail : "Failed to assign role. Please verify permissions.";
      setActionError(msg);
      toast(msg, "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemoveAssignment = async (assignment: ClientAssignmentItem) => {
    if (!authToken || !clientId || !assignment.id) return;

    setDeletingId(assignment.id);
    setConfirmDeleteId(null);

    try {
      await clientsApi.removeAssignment(authToken, clientId, assignment.id);
      toast("Assignment removed successfully", "success");
      await mutateAssignments();
      onAssignmentChanged?.();
    } catch (err: unknown) {
      const msg = isApiError(err) ? err.detail : "Could not remove assignment.";
      toast(msg, "error");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <section className="dashboard-card p-6" data-testid="client-assignments-card">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#F0F0F0] pb-5">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
              Client Team & Role Assignments
            </h2>
            <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-600/10">
              Granular RBAC
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Assign designated Preparers, Reviewers, Managers, and Partners for GSTR compliance workflows.
          </p>
        </div>

        {canManage && (
          <button
            type="button"
            onClick={openAddModal}
            className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
          >
            <UserPlus className="h-3.5 w-3.5" />
            <span>Add Assignment</span>
          </button>
        )}
      </div>

      {/* Error state */}
      {assignmentsError && (
        <div className="mt-4 flex items-center justify-between rounded-[1.25rem] bg-red-50 p-4 text-sm text-red-800">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
            <span>Failed to load team assignments.</span>
          </div>
          <button
            type="button"
            onClick={() => void mutateAssignments()}
            className="font-semibold text-red-900 underline hover:opacity-80"
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {isLoading ? (
        <div className="mt-5 space-y-3">
          {[1, 2, 3].map((idx) => (
            <div
              key={idx}
              className="flex items-center justify-between rounded-2xl bg-gray-50 p-4 animate-pulse"
            >
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-gray-200" />
                <div className="space-y-1.5">
                  <div className="h-4 w-32 rounded bg-gray-200" />
                  <div className="h-3 w-48 rounded bg-gray-200" />
                </div>
              </div>
              <div className="h-6 w-24 rounded-full bg-gray-200" />
            </div>
          ))}
        </div>
      ) : assignments.length === 0 ? (
        /* Empty State */
        <div className="mt-6 flex flex-col items-center justify-center rounded-2xl bg-[#F7F7F8] px-6 py-10 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-gray-200">
            <Users className="h-6 w-6 text-gray-400" />
          </div>
          <h3 className="mt-3 text-sm font-semibold text-[var(--ink)]">
            No specialized role assignments
          </h3>
          <p className="mt-1 max-w-sm text-xs text-gray-500">
            Assign team members as Preparers, Reviewers, Managers, or Partners to govern reconciliation access.
          </p>
          {canManage ? (
            <button
              type="button"
              onClick={openAddModal}
              className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm hover:opacity-90 transition-opacity"
            >
              <UserPlus className="h-3.5 w-3.5" />
              <span>Assign First Role</span>
            </button>
          ) : (
            <span className="mt-4 inline-flex items-center gap-1 text-xs text-gray-400">
              Contact your firm Manager or Partner to configure client roles.
            </span>
          )}
        </div>
      ) : (
        /* Assignments List */
        <div className="mt-5 divide-y divide-[#F0F0F0] overflow-hidden rounded-2xl ring-1 ring-[#F0F0F0]">
          {assignments.map((item) => {
            const roleCfg = getRoleConfig(item.assignment_role);
            const RoleIcon = ICON_COMPONENTS[roleCfg.iconName] || Users;
            const displayName =
              item.user_name ||
              item.user_profiles?.full_name ||
              item.email ||
              item.user_profiles?.email ||
              "Team Member";
            const displayEmail = item.email || item.user_profiles?.email || "";
            const isDeleting = deletingId === item.id;
            const isConfirming = confirmDeleteId === item.id;
            const dateStr = item.assigned_at
              ? new Date(item.assigned_at).toLocaleDateString("en-IN", {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                })
              : null;

            return (
              <div
                key={item.id}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-white p-4 transition-colors hover:bg-[#FAFAFA]"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Avatar initials={initialsFromLabel(displayName)} size="sm" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-semibold text-[var(--ink)]">
                        {displayName}
                      </p>
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${roleCfg.badgeBg} ${roleCfg.badgeText} ${roleCfg.ringColor}`}
                      >
                        <RoleIcon className="h-3 w-3 shrink-0" />
                        <span>{roleCfg.label}</span>
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                      {displayEmail && <span className="truncate">{displayEmail}</span>}
                      {displayEmail && dateStr && <span>•</span>}
                      {dateStr && <span>Assigned {dateStr}</span>}
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-between sm:justify-end gap-3 self-stretch sm:self-center">
                  <span className="hidden lg:inline text-xs text-gray-400 text-right max-w-xs truncate">
                    {roleCfg.description}
                  </span>

                  {canManage && (
                    <div className="shrink-0">
                      {isConfirming ? (
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => void handleRemoveAssignment(item)}
                            disabled={isDeleting}
                            className="inline-flex items-center gap-1 rounded-full bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                          >
                            {isDeleting ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <span>Confirm</span>
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(null)}
                            disabled={isDeleting}
                            className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(item.id)}
                          disabled={isDeleting}
                          title={`Remove ${displayName} as ${roleCfg.label}`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-full text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add Assignment Modal */}
      {canManage && (
        <Modal
          open={modalOpen}
          onClose={closeAddModal}
          title="Add Client Role Assignment"
        >
          <form onSubmit={handleAddAssignment} className="space-y-4">
            {actionError && (
              <div className="rounded-xl bg-red-50 p-3 text-xs text-red-800 flex items-center gap-2">
                <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
                <span>{actionError}</span>
              </div>
            )}

            {/* Team member selection */}
            <div>
              <label className="mb-1.5 block text-xs font-semibold text-gray-700">
                Select Team Member
              </label>
              {eligibleMembers.length > 0 ? (
                <select
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value)}
                  disabled={isSubmitting}
                  className="w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-[var(--ink)] outline-none focus:border-black focus:ring-1 focus:ring-black"
                >
                  {eligibleMembers.map((m) => {
                    const label = m.full_name?.trim() || m.email || m.member_user_id;
                    const roleLabel = m.role ? ` (${m.role})` : "";
                    return (
                      <option key={m.member_user_id} value={m.member_user_id}>
                        {label}{roleLabel}
                      </option>
                    );
                  })}
                </select>
              ) : (
                <div>
                  <input
                    type="text"
                    value={selectedUserId}
                    onChange={(e) => setSelectedUserId(e.target.value)}
                    placeholder="Enter user UUID"
                    disabled={isSubmitting}
                    className="w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-[var(--ink)] outline-none focus:border-black focus:ring-1 focus:ring-black"
                  />
                  <p className="mt-1 text-[11px] text-gray-500">
                    No active team members found in roster. You can specify a member UUID directly.
                  </p>
                </div>
              )}
            </div>

            {/* Role selector */}
            <div>
              <label className="mb-1.5 block text-xs font-semibold text-gray-700">
                Assign Role
              </label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {(Object.keys(ROLE_CONFIGS) as AssignmentRole[]).map((roleKey) => {
                  const cfg = ROLE_CONFIGS[roleKey];
                  const Icon = ICON_COMPONENTS[cfg.iconName] || Users;
                  const isSelected = selectedRole === roleKey;
                  return (
                    <button
                      type="button"
                      key={roleKey}
                      onClick={() => setSelectedRole(roleKey)}
                      disabled={isSubmitting}
                      className={`flex flex-col items-start gap-1 rounded-xl p-3 text-left transition-all border ${
                        isSelected
                          ? "border-black bg-black text-white shadow-sm"
                          : "border-gray-200 bg-white text-gray-800 hover:border-gray-300 hover:bg-gray-50"
                      }`}
                    >
                      <div className="flex w-full items-center justify-between">
                        <div className="flex items-center gap-1.5 font-semibold text-xs">
                          <Icon className={`h-3.5 w-3.5 ${isSelected ? "text-white" : cfg.badgeText}`} />
                          <span>{cfg.label}</span>
                        </div>
                        {isSelected && <CheckCircle2 className="h-3.5 w-3.5 text-white" />}
                      </div>
                      <span
                        className={`text-[11px] leading-snug ${
                          isSelected ? "text-white/80" : "text-gray-500"
                        }`}
                      >
                        {cfg.description}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="mt-5 flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
              <button
                type="button"
                onClick={closeAddModal}
                disabled={isSubmitting}
                className="rounded-full bg-gray-100 px-4 py-2 text-xs font-medium text-gray-700 hover:bg-gray-200 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting || !selectedUserId}
                className="inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-5 py-2 text-xs font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-50"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Assigning…</span>
                  </>
                ) : (
                  <span>Save Assignment</span>
                )}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
