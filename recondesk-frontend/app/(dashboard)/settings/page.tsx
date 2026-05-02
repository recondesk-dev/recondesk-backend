"use client";

import Link from "next/link";
import useSWR from "swr";
import { Bell, ChevronRight, CreditCard, UserCircle, Users } from "lucide-react";

import { authApi, teamApi, type AuthMeProfile, type TeamMemberListItem } from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

/** Backend exposes `/api/v1/auth/me`; same payload as documented “auth/me”. */
function SettingsSkeleton() {
  return (
    <div className="space-y-8">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="animate-pulse rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5"
          >
            <div className="mb-4 h-10 w-10 rounded-lg bg-[var(--border)]" />
            <div className="mb-2 h-5 w-3/5 rounded bg-[var(--border)]" />
            <div className="mb-4 h-4 w-full rounded bg-[var(--border)]" />
            <div className="h-4 w-16 rounded bg-[var(--border)]" />
          </div>
        ))}
      </div>
      <div className="animate-pulse rounded-xl border border-[var(--border)] bg-[var(--surface)] px-5 py-4">
        <div className="h-5 w-2/3 rounded bg-[var(--border)]" />
      </div>
    </div>
  );
}

function planLabel(profile: AuthMeProfile | undefined): string {
  const p = (profile?.plan ?? "free").toLowerCase();
  if (!p || p === "free") return "Free";
  return p.charAt(0).toUpperCase() + p.slice(1);
}

export default function SettingsHubPage() {
  const token = useAccessToken();
  const authToken = typeof token === "string" && token.length > 0 ? token : null;

  const resolvingToken = token === null;

  const meKey = authToken ? (["settings-me", authToken] as const) : null;
  const teamKey = authToken ? (["settings-team-count", authToken] as const) : null;

  const { data: me, isLoading: meLoading } = useSWR(
    meKey,
    ([, t]) => authApi.me(t),
    { keepPreviousData: true }
  );

  const { data: teamMembers, isLoading: teamLoading } = useSWR(
    teamKey,
    ([, t]) => teamApi.list(t),
    { keepPreviousData: true }
  );

  const loadingShell =
    resolvingToken ||
    (!!authToken &&
      ((meKey !== null && meLoading) || (teamKey !== null && teamLoading)));

  const runsUsed = me?.runs_used ?? 0;
  const teamSize = Array.isArray(teamMembers)
    ? (teamMembers as TeamMemberListItem[]).length
    : 0;

  const cards = [
    {
      href: "/settings/team",
      title: "Team",
      description: "Invite admins and staff, manage access.",
      Icon: Users,
    },
    {
      href: "/settings/billing",
      title: "Billing",
      description: "Plans, invoices, and payment methods.",
      Icon: CreditCard,
    },
    {
      href: "/settings/profile",
      title: "Profile",
      description: "Your name, firm, and contact details.",
      Icon: UserCircle,
    },
    {
      href: "/settings/notifications",
      title: "Notifications",
      description: "Email alerts and reminders.",
      Icon: Bell,
    },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          Settings
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Manage your workspace and preferences.
        </p>
      </div>

      {loadingShell ? (
        <SettingsSkeleton />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map(({ href, title, description, Icon }) => (
              <Link
                key={href}
                href={href}
                className="group flex flex-col rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm transition hover:border-[var(--accent)] hover:shadow-md"
              >
                <div className="mb-4 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg bg-[var(--accent-dim)] text-[var(--accent)]">
                  <Icon className="h-6 w-6" aria-hidden />
                </div>
                <h2 className="text-base font-semibold text-[var(--text-primary)]">
                  {title}
                </h2>
                <p className="mt-1 flex-1 text-sm text-[var(--text-secondary)]">
                  {description}
                </p>
                <span className="mt-4 inline-flex min-h-[44px] items-center gap-1 text-sm font-semibold text-[var(--accent)]">
                  Open
                  <ChevronRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
                </span>
              </Link>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-x-8 gap-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-5 py-4 text-sm">
            <span>
              <span className="text-[var(--text-secondary)]">Plan:</span>{" "}
              <span className="font-semibold text-[var(--text-primary)]">
                {planLabel(me)}
              </span>
            </span>
            <span className="hidden sm:inline text-[var(--border)]">|</span>
            <span>
              <span className="text-[var(--text-secondary)]">
                Runs used this month:
              </span>{" "}
              <span className="font-semibold text-[var(--text-primary)]">
                {runsUsed}
              </span>
              {me?.runs_limit != null && (
                <span className="text-[var(--text-secondary)]">
                  {" "}
                  / {me.runs_limit}
                </span>
              )}
            </span>
            <span className="hidden sm:inline text-[var(--border)]">|</span>
            <span>
              <span className="text-[var(--text-secondary)]">Team size:</span>{" "}
              <span className="font-semibold text-[var(--text-primary)]">
                {teamSize} members
              </span>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
