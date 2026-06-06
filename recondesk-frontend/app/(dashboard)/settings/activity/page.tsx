"use client";

import Link from "next/link";
import useSWR from "swr";

import { ActivityLogPanel } from "@/components/settings/ActivityLogPanel";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  normalizeAuthRole,
} from "@/lib/auth-profile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

export default function ActivityLogSettingsPage() {
  const token = useAccessToken();
  const authToken =
    typeof token === "string" && token.length > 0 ? token : null;

  const meKey = authToken ? (["activity-me", authToken] as const) : null;
  const { data: me, isLoading: meLoading } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const roleNorm = normalizeAuthRole(me?.role);
  const isAdmin = roleNorm === "admin";
  const resolving = token === null || (!!authToken && meKey !== null && meLoading);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/settings"
          className="text-sm font-medium text-brand hover:underline"
        >
          ← Settings
        </Link>
        <h1 className="mt-2 text-xl font-semibold text-[var(--text-primary)]">
          Activity Log
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Review workspace actions by admin and staff users.
        </p>
      </div>

      {resolving ? (
        <div className="animate-pulse rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8">
          <div className="h-5 w-1/3 rounded bg-[var(--border)]" />
        </div>
      ) : !isAdmin ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
          Only workspace admins can view the activity log.
        </div>
      ) : authToken ? (
        <ActivityLogPanel authToken={authToken} />
      ) : null}
    </div>
  );
}
