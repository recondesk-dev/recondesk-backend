"use client";

import Link from "next/link";
import useSWR from "swr";
import {
  Bell,
  ChevronRight,
  ClipboardList,
  CreditCard,
  SlidersHorizontal,
  UserCircle,
  Users,
} from "lucide-react";

import { teamApi, billingApi, filingApi, type TeamMemberListItem } from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  normalizeAuthRole,
} from "@/lib/auth-profile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function SettingsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="dashboard-card animate-pulse p-5"
          >
            <div className="mb-4 h-11 w-11 rounded-full bg-gray-100" />
            <div className="mb-2 h-5 w-3/5 rounded bg-gray-100" />
            <div className="mb-4 h-4 w-full rounded bg-gray-100" />
            <div className="h-4 w-16 rounded bg-gray-100" />
          </div>
        ))}
      </div>
      <div className="dashboard-card animate-pulse px-5 py-4">
        <div className="h-5 w-2/3 rounded bg-gray-100" />
      </div>
    </div>
  );
}


export default function SettingsHubPage() {
  const token = useAccessToken();
  const authToken = typeof token === "string" && token.length > 0 ? token : null;

  const resolvingToken = token === null;

  const meKey = authToken ? (["settings-me", authToken] as const) : null;
  const teamKey = authToken ? (["settings-team-count", authToken] as const) : null;
  const billingKey = authToken ? (["settings-billing", authToken] as const) : null;

  const { data: me, isLoading: meLoading } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const { data: teamMembers, isLoading: teamLoading } = useSWR(
    teamKey,
    ([, t]) => teamApi.list(t),
    { keepPreviousData: true }
  );

  const { data: billingStatus, isLoading: billingLoading } = useSWR(
    billingKey,
    ([, t]) => billingApi.status(t)
  );

  const { data: filingFeatures } = useSWR("filing-features", () =>
    filingApi.features()
  );
  // Fail closed: only show when the API explicitly enables GSTR-3B.
  const gstr3bFilingEnabled = filingFeatures?.gstr3b_filing_enabled === true;

  const loadingShell =
    resolvingToken ||
    (!!authToken &&
      ((meKey !== null && meLoading) || (teamKey !== null && teamLoading) || (billingKey !== null && billingLoading)));

  const rawPlan =
    (billingStatus?.subscription_active && billingStatus.plan?.trim()) ||
    billingStatus?.credit_batches?.find(
      (b) => (b.runs_remaining ?? 0) > 0 && (b.status || "").toLowerCase() !== "expired"
    )?.plan?.trim() ||
    me?.plan ||
    "free";
  const planLabelStr = rawPlan.charAt(0).toUpperCase() + rawPlan.slice(1).toLowerCase();

  const gstinCapacity = billingStatus
    ? `${billingStatus.gstins_used ?? 0} / ${billingStatus.gstin_limit ?? 2}`
    : "—";

  const teamSize = Array.isArray(teamMembers)
    ? (teamMembers as TeamMemberListItem[]).length
    : 0;

  const roleNorm = normalizeAuthRole(me?.role);
  const isAdmin = !!me && roleNorm === "admin";

  const cards = [
    {
      href: "/settings/team",
      title: "Team",
      description: "Invite admins and staff, manage access.",
      Icon: Users,
    },
    ...(isAdmin
      ? [
          {
            href: "/settings/activity",
            title: "Activity Log",
            description: "View workspace activity and audit events.",
            Icon: ClipboardList,
          },
        ]
      : []),
    {
      href: "/settings/reconciliation",
      title: "Reconciliation",
      description: "Auto-approve confidence threshold and match triage.",
      Icon: SlidersHorizontal,
    },
    {
      href: "/filing/gstr-1",
      title: "GSTR-1 Filing",
      description: "Readiness, Save to GSTN, EVC OTP, and File.",
      Icon: ClipboardList,
    },
    ...(gstr3bFilingEnabled
      ? [
          {
            href: "/filing/gstr-3b",
            title: "GSTR-3B Filing",
            description: "Confirm figures, Save, Offset liability, EVC, File.",
            Icon: ClipboardList,
          },
        ]
      : []),
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
    <div className="space-y-7">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
          Settings
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage your workspace and preferences.
        </p>
      </div>

      {loadingShell ? (
        <SettingsSkeleton />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map(({ href, title, description, Icon }) => (
              <Link
                key={href}
                href={href}
                className="group flex flex-col rounded-[1.5rem] bg-white p-5 shadow-[var(--shadow-soft)] transition-transform duration-200 hover:-translate-y-0.5"
              >
                <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
                  <Icon className="h-5 w-5" aria-hidden />
                </div>
                <h2 className="text-base font-semibold text-[var(--ink)]">
                  {title}
                </h2>
                <p className="mt-1 flex-1 text-sm text-gray-500">
                  {description}
                </p>
                <span className="mt-4 inline-flex min-h-[40px] items-center gap-1 text-sm font-semibold text-[var(--ink)]">
                  Open
                  <ChevronRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
                </span>
              </Link>
            ))}
          </div>

          <div className="dashboard-card flex flex-wrap items-center gap-x-8 gap-y-3 px-5 py-4 text-sm">
            <span>
              <span className="text-gray-500">Plan:</span>{" "}
              <span className="font-semibold text-[var(--ink)]">
                {planLabelStr}
              </span>
            </span>
            <span className="hidden text-[#E5E5E5] sm:inline">|</span>
            <span>
              <span className="text-gray-500">GSTINs:</span>{" "}
              <span className="font-semibold text-[var(--ink)]">{gstinCapacity}</span>
            </span>
            <span className="hidden text-[#E5E5E5] sm:inline">|</span>
            <span>
              <span className="text-gray-500">Team size:</span>{" "}
              <span className="font-semibold text-[var(--ink)]">
                {teamSize} members
              </span>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
