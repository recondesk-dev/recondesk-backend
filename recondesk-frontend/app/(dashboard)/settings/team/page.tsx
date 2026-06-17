"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import { Modal } from "@/components/ui/Modal";
import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import { useToast } from "@/components/providers/ToastProvider";
import {
  isApiError,
  teamApi,
  type AuthMeProfile,
  type TeamMemberListItem,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  normalizeAuthRole,
} from "@/lib/auth-profile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function formatJoined(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

function isSelfRow(row: TeamMemberListItem, profile: AuthMeProfile | undefined) {
  if (!profile?.email || !row.email) return false;
  return profile.email.toLowerCase().trim() === row.email.toLowerCase().trim();
}

function TeamTableSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-[var(--border)] px-4 py-4 last:border-b-0"
          >
            <div className="h-4 flex-1 rounded bg-[var(--border)]" />
            <div className="h-4 flex-1 rounded bg-[var(--border)]" />
            <div className="h-4 w-20 rounded bg-[var(--border)]" />
            <div className="h-4 w-24 rounded bg-[var(--border)]" />
            <div className="h-4 w-16 rounded bg-[var(--border)]" />
            <div className="h-8 w-24 rounded bg-[var(--border)]" />
          </div>
        ))}
      </div>
    </div>
  );
}

function TeamSettingsPageContent() {
  const toast = useToast();
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.trim().length > 0
      ? tokenState.trim()
      : null;

  const meKey = authToken ? (["/api/v1/auth/me", authToken] as const) : null;
  const membersKey = authToken
    ? (["/api/team/members", authToken] as const)
    : null;

  const { data: me } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );
  const {
    data: members,
    error: membersError,
    isLoading: membersLoading,
    mutate: mutateMembers,
  } = useSWR(membersKey, ([, t]) => teamApi.list(t));

  const roleNorm = normalizeAuthRole(me?.role);
  const isAdmin = roleNorm === "admin";

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "staff">("staff");
  const [inviteSubmitting, setInviteSubmitting] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  // Auto-open invite modal when navigated with ?invite=1 (e.g. from header dropdown)
  const searchParams = useSearchParams();
  useEffect(() => {
    if (searchParams.get("invite") === "1" && isAdmin) {
      setInviteError(null);
      setInviteOpen(true);
    }
  }, [searchParams, isAdmin]);

  const [actionBusyId, setActionBusyId] = useState<string | null>(null);

  const sortedMembers = useMemo(() => {
    const list = [...(members ?? [])];
    list.sort((a, b) => {
      const ast = a.status === "pending" ? 1 : 0;
      const bst = b.status === "pending" ? 1 : 0;
      if (ast !== bst) return ast - bst;
      return (a.full_name || a.email).localeCompare(b.full_name || b.email);
    });
    return list;
  }, [members]);

  const showTeamEmpty =
    !membersLoading &&
    Array.isArray(members) &&
    !sortedMembers.some(
      (r) =>
        r.status === "pending" ||
        (r.status === "active" && !isSelfRow(r, me))
    );

  const submitInvite = async () => {
    if (!authToken) return;
    const email = inviteEmail.trim();
    if (!email) {
      setInviteError("Email is required.");
      return;
    }
    setInviteSubmitting(true);
    setInviteError(null);
    try {
      await teamApi.invite(authToken, email, inviteRole);
      toast("Invitation sent", "success");
      setInviteOpen(false);
      setInviteEmail("");
      setInviteRole("staff");
      await mutateMembers();
    } catch (e: unknown) {
      const msg = isApiError(e) ? e.detail : "Could not send invitation.";
      setInviteError(msg);
      toast(msg, "error");
    } finally {
      setInviteSubmitting(false);
    }
  };

  const removeMember = async (row: TeamMemberListItem) => {
    if (!authToken) return;
    setActionBusyId(row.id);
    try {
      await teamApi.remove(authToken, row.id);
      toast("Team member removed", "success");
      await mutateMembers();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Could not remove member.", "error");
    } finally {
      setActionBusyId(null);
    }
  };

  const resendInvite = async (row: TeamMemberListItem) => {
    if (!authToken) return;
    const role = row.role.toLowerCase() === "admin" ? "admin" : "staff";
    setActionBusyId(row.id);
    try {
      await teamApi.invite(authToken, row.email, role);
      toast("Invitation sent", "success");
      await mutateMembers();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Could not resend invitation.", "error");
    } finally {
      setActionBusyId(null);
    }
  };

  if (tokenState === null) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 animate-pulse rounded bg-[var(--border)]" />
        <TeamTableSkeleton />
      </div>
    );
  }

  if (!authToken) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-5 py-8 text-center text-sm text-[var(--text-secondary)]">
        Sign in required to manage team members.
      </div>
    );
  }

  if (!me) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 animate-pulse rounded bg-[var(--border)]" />
        <TeamTableSkeleton />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-6 text-sm text-amber-950">
        Only admins can manage team members.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          Team Members
        </h1>
        <button
          type="button"
          className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-brand px-5 text-sm font-semibold text-white hover:bg-brand-hover"
          onClick={() => {
            setInviteError(null);
            setInviteOpen(true);
          }}
        >
          Invite Staff
        </button>
      </div>

      <div className="rounded-xl bg-gray-100 px-5 py-4 text-sm text-[var(--text-primary)]">
        <p className="font-semibold text-[var(--text-primary)]">Role descriptions</p>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--text-secondary)]">
          <li>
            <strong className="text-[var(--text-primary)]">Admin:</strong> Upload
            files, run reconciliation, view all clients, finalize runs, manage billing.
          </li>
          <li>
            <strong className="text-[var(--text-primary)]">Staff:</strong> Upload
            files, run reconciliation, view assigned clients, add notes — cannot
            finalize.
          </li>
        </ul>
      </div>

      {membersError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load team members.
        </div>
      )}

      {membersLoading && !members ? (
        <TeamTableSkeleton />
      ) : showTeamEmpty ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] px-6 py-16 text-center">
          <div className="mx-auto w-full max-w-[400px]">
            <EmptyStateIllustration className="mx-auto text-gray-400" />
            <h2 className="mt-4 text-lg font-semibold text-gray-900">
              No team members yet
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Invite your staff to upload files and run reconciliations. You retain admin
              control — only you can finalize.
            </p>
            <button
              type="button"
              className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-full bg-brand px-5 text-sm font-semibold text-white hover:bg-brand-hover"
              onClick={() => {
                setInviteError(null);
                setInviteOpen(true);
              }}
            >
              Invite First Team Member
            </button>
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <div className="overflow-x-auto">
            <table className="min-w-[920px] w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[#FAFAFB] text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Role</th>
                  <th className="px-4 py-3">Joined</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {sortedMembers.map((row) => {
                  const adminBadge =
                    row.role.toLowerCase() === "admin";
                  const pending = row.status === "pending";
                  const selfRow = !pending && isSelfRow(row, me);
                  return (
                    <tr key={row.id} className="border-b border-[var(--border)]">
                      <td className="px-4 py-3 font-medium text-[var(--text-primary)]">
                        {pending ? "—" : row.full_name || "—"}
                      </td>
                      <td className="px-4 py-3 text-[var(--text-secondary)]">
                        {row.email}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex min-h-[28px] items-center rounded-full px-3 py-1 text-xs font-semibold ${
                            adminBadge
                              ? "bg-brand-dim text-brand"
                              : "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {adminBadge ? "Admin" : "Staff"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[var(--text-secondary)]">
                        {formatJoined(row.joined_at)}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex min-h-[28px] items-center rounded-full px-3 py-1 text-xs font-semibold ${
                            pending
                              ? "bg-amber-100 text-amber-900"
                              : "bg-emerald-50 text-emerald-800"
                          }`}
                        >
                          {pending ? "Pending" : "Active"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {pending ? (
                          <button
                            type="button"
                            disabled={actionBusyId === row.id}
                            className="inline-flex min-h-[44px] items-center justify-center rounded-full border border-[var(--border)] px-4 text-sm font-medium text-[var(--text-primary)] hover:bg-brand-dim disabled:opacity-50"
                            onClick={() => void resendInvite(row)}
                          >
                            {actionBusyId === row.id ? "Sending…" : "Resend Invite"}
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled={selfRow || actionBusyId === row.id}
                            className="inline-flex min-h-[44px] items-center justify-center rounded-full px-4 text-sm font-semibold text-[var(--danger)] hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-35"
                            title={selfRow ? "You cannot remove yourself" : undefined}
                            onClick={() => void removeMember(row)}
                          >
                            {actionBusyId === row.id ? "Removing…" : "Remove"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        open={inviteOpen}
        onClose={() => !inviteSubmitting && setInviteOpen(false)}
        title="Invite team member"
        footer={
          <>
            <button
              type="button"
              disabled={inviteSubmitting}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full border border-[var(--border)] px-4 text-sm font-medium"
              onClick={() => setInviteOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={inviteSubmitting}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-brand px-5 text-sm font-semibold text-white disabled:opacity-50 hover:bg-brand-hover disabled:hover:bg-brand"
              onClick={() => void submitInvite()}
            >
              {inviteSubmitting ? "Sending…" : "Send Invite"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {inviteError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {inviteError}
            </div>
          )}
          <div>
            <label
              htmlFor="invite-email"
              className="mb-1 block text-sm font-medium text-[var(--text-primary)]"
            >
              Email <span className="text-[var(--danger)]">*</span>
            </label>
            <input
              id="invite-email"
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
              placeholder="colleague@firm.in"
              autoComplete="email"
            />
          </div>
          <div>
            <span className="mb-2 block text-sm font-medium text-[var(--text-primary)]">
              Role
            </span>
            <div className="space-y-3">
              <label className="flex cursor-pointer gap-3 rounded-lg border border-[var(--border)] p-3 hover:bg-brand-dim/40">
                <input
                  type="radio"
                  name="invite-role"
                  checked={inviteRole === "admin"}
                  onChange={() => setInviteRole("admin")}
                  className="mt-1"
                />
                <span>
                  <span className="font-semibold text-[var(--text-primary)]">
                    Admin
                  </span>
                  <span className="mt-1 block text-xs text-[var(--text-secondary)]">
                    Full access including finalize runs and billing.
                  </span>
                </span>
              </label>
              <label className="flex cursor-pointer gap-3 rounded-lg border border-[var(--border)] p-3 hover:bg-brand-dim/40">
                <input
                  type="radio"
                  name="invite-role"
                  checked={inviteRole === "staff"}
                  onChange={() => setInviteRole("staff")}
                  className="mt-1"
                />
                <span>
                  <span className="font-semibold text-[var(--text-primary)]">
                    Staff
                  </span>
                  <span className="mt-1 block text-xs text-[var(--text-secondary)]">
                    Assigned clients only; cannot finalize reconciliations.
                  </span>
                </span>
              </label>
            </div>
          </div>
        </div>
      </Modal>
    </div>
  );
}

export default function TeamSettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6">
          <div className="h-8 w-48 animate-pulse rounded bg-[var(--border)]" />
          <TeamTableSkeleton />
        </div>
      }
    >
      <TeamSettingsPageContent />
    </Suspense>
  );
}
