"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/components/ui/Logo";
import useSWR, { mutate } from "swr";
import { Avatar } from "@/components/ui/Avatar";
import { useToast } from "@/components/providers/ToastProvider";
import {
  billingApi,
  isApiError,
  reconcileRunsApi,
  type BillingStatus,
  type CreditBatchRow,
} from "@/lib/api";
import {
  fetchFreshAuthProfile,
  normalizeAuthRole,
  resolveDisplayName,
} from "@/lib/auth-profile";
import { DW, formatPeriodLabel } from "@/lib/dashboard-portfolio";
import { createClient, subscribeAccessToken } from "@/lib/supabase/client";

function initialsFromDisplayName(name: string): string {
  const t = name.trim();
  if (!t) return "?";
  const parts = t.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    const a = parts[0][0];
    const b = parts[parts.length - 1][0];
    return `${a}${b}`.toUpperCase();
  }
  if (parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
  return parts[0][0]?.toUpperCase() ?? "?";
}

function capitalizePlanName(plan: string): string {
  const t = plan.trim();
  if (!t) return "Free";
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

function planFromCreditBatches(batches: CreditBatchRow[]): string | null {
  const active = batches.find(
    (b) =>
      (b.runs_remaining ?? 0) > 0 && (b.status || "").toLowerCase() !== "expired"
  );
  const plan = active?.plan?.trim();
  return plan ? capitalizePlanName(plan) : null;
}

function runsAvailableFromBilling(status: BillingStatus): number {
  return (status.free_runs_remaining ?? 0) + (status.runs_balance ?? 0);
}

function runsRemainingLabel(count: number): string {
  return count === 1 ? "1 run remaining" : `${count} runs remaining`;
}

function ProfileBillingSkeleton() {
  return (
    <div className="space-y-2 border-b border-gray-100 px-4 py-3" aria-hidden>
      <div className="h-5 w-14 animate-pulse rounded-full bg-gray-100" />
      <div className="h-3.5 w-28 animate-pulse rounded bg-gray-100" />
    </div>
  );
}

function NavIconDashboard({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 10.5L12 4l8 6.5V20a1 1 0 01-1 1h-5v-6H10v6H5a1 1 0 01-1-1v-9.5z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function NavIconUsers({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M17 20v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 20v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function NavIconRefresh({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M21 2v6h-6M3 12a9 9 0 0115.5-6.36M3 22v-6h6M21 12a9 9 0 01-15.5 6.36"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function NavIconCredit({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="2" y="5" width="20" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M2 10h20" stroke="currentColor" strokeWidth="1.5" />
      <path d="M6 14h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function NavIconGear({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 15.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM19.4 15a7.96 7.96 0 00.1-1 7.96 7.96 0 00-.1-1l2.1-1.65a.5.5 0 00.12-.64l-2-3.46a.5.5 0 00-.6-.22l-2.48 1a7.7 7.7 0 00-1.73-1l-.38-2.65A.5.5 0 0014.5 2h-5a.5.5 0 00-.49.42L8.63 5.07a7.7 7.7 0 00-1.73 1l-2.48-1a.5.5 0 00-.6.22l-2 3.46a.5.5 0 00.12.64L4.59 13a7.96 7.96 0 000 2l-2.1 1.65a.5.5 0 00-.12.64l2 3.46a.5.5 0 00.6.22l2.48-1c.53.43 1.12.78 1.73 1l.38 2.65a.5.5 0 00.49.42h5a.5.5 0 00.49-.42l.38-2.65c.61-.22 1.2-.57 1.73-1l2.48 1a.5.5 0 00.6-.22l2-3.46a.5.5 0 00-.12-.64L19.4 15z"
        stroke="currentColor"
        strokeWidth="1.2"
      />
    </svg>
  );
}

function BellIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M18 8a6 6 0 10-12 0c0 7-3 7-3 7h18s-3 0-3-7M13.73 21a2 2 0 01-3.46 0"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function DashboardShellLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createClient();
  const toast = useToast();
  const [panelOpen, setPanelOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const [headerProfileOpen, setHeaderProfileOpen] = useState(false);
  const headerProfileRef = useRef<HTMLDivElement>(null);
  const [accessToken, setAccessToken] = useState<string | false | null>(null);
  const [currentUser, setCurrentUser] = useState({
    name: "…",
    email: "",
    role: "…",
    initials: "··",
  });
  const [profileBilling, setProfileBilling] = useState<
    | { status: "idle" }
    | { status: "loading" }
    | { status: "ready"; planLabel: string; runsAvailable: number }
    | { status: "error" }
  >({ status: "idle" });

  useEffect(() => subscribeAccessToken(setAccessToken), []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
      if (headerProfileRef.current && !headerProfileRef.current.contains(e.target as Node)) {
        setHeaderProfileOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (!headerProfileOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setHeaderProfileOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [headerProfileOpen]);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      if (accessToken === null) return;

      if (accessToken === false) {
        setCurrentUser({ name: "Guest", email: "", role: "—", initials: "?" });
        return;
      }

      setCurrentUser({ name: "…", email: "", role: "…", initials: "··" });

      try {
        const me = await fetchFreshAuthProfile(accessToken);
        if (cancelled) return;
        const name = resolveDisplayName({
          profileFullName: me.full_name,
          email: me.email,
        });
        const role = normalizeAuthRole(me.role).toUpperCase();
        setCurrentUser({
          name,
          email: me.email ?? "",
          role,
          initials: initialsFromDisplayName(name),
        });
      } catch (err) {
        if (cancelled) return;
        console.warn("[DashboardShellLayout] fetchFreshAuthProfile failed, using fallback:", err);
        
        let authUserEmail = "";
        let metadataName = "";
        try {
          const {
            data: { user: authUser },
          } = await supabase.auth.getUser();
          authUserEmail = authUser?.email ?? "";
          metadataName = (authUser?.user_metadata as { full_name?: string } | undefined)?.full_name ?? "";
        } catch (authErr) {
          console.warn("[DashboardShellLayout] fallback supabase.auth.getUser failed:", authErr);
        }

        const name = resolveDisplayName({
          metadataFullName: metadataName,
          email: authUserEmail,
        }) || "Admin";

        setCurrentUser({
          name,
          email: authUserEmail || "admin@recondesk.in",
          role: "ADMIN",
          initials: initialsFromDisplayName(name),
        });
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  useEffect(() => {
    if (!profileOpen) {
      setProfileBilling({ status: "idle" });
      return;
    }

    if (typeof accessToken !== "string" || accessToken.length === 0) {
      setProfileBilling({ status: "error" });
      return;
    }

    let cancelled = false;
    setProfileBilling({ status: "loading" });

    void billingApi
      .status(accessToken)
      .then((status) => {
        if (cancelled) return;
        setProfileBilling({
          status: "ready",
          planLabel: planFromCreditBatches(status.credit_batches) ?? "Free",
          runsAvailable: runsAvailableFromBilling(status),
        });
      })
      .catch(() => {
        if (cancelled) return;
        setProfileBilling({ status: "error" });
      });

    return () => {
      cancelled = true;
    };
  }, [profileOpen, accessToken]);

  const failuresKey =
    typeof accessToken === "string" && accessToken.length > 0
      ? ([DW, "failures", accessToken] as const)
      : null;

  const {
    data: failures,
    error: failuresError,
    isLoading: failuresLoading,
    mutate: mutateFailures,
  } = useSWR(
    failuresKey,
    async ([, , token]) => {
      const rows = await reconcileRunsApi.list(token, {
        status: "failed",
        limit: 500,
      });
      const items = rows.slice(0, 5).map((r) => ({
        runId: r.id,
        tradeName: (r.trade_name || r.client_gstin || "Unknown").trim(),
        period: formatPeriodLabel(r.period),
        errorSnippet: (r.status_message || "Reconciliation failed.").slice(0, 80),
      }));
      return { count: rows.length, items };
    },
    { revalidateOnFocus: false }
  );

  const failedCount = failures?.count ?? 0;

  async function invalidateDw(): Promise<void> {
    await mutate((key: unknown) => Array.isArray(key) && key[0] === DW);
  }

  async function handleSignOut(): Promise<void> {
    await supabase.auth.signOut();
    router.push("/login");
  }

  const nav = [
    { href: "/dashboard", label: "Dashboard", Icon: NavIconDashboard },
    { href: "/clients", label: "Clients", Icon: NavIconUsers },
    { href: "/runs", label: "Runs", Icon: NavIconRefresh },
    { href: "/billing", label: "Billing", Icon: NavIconCredit },
    { href: "/settings", label: "Settings", Icon: NavIconGear },
  ];

  return (
    <div className="flex min-h-screen w-full min-w-0 bg-[var(--bg)] text-[var(--text-primary)]">
      <aside className="fixed inset-y-0 left-0 z-50 flex w-[240px] flex-col border-r border-[#F0F0F0] bg-white">
        <div className="px-5 py-6">
          <Link
            href="/dashboard"
            className="flex items-center"
          >
            <Logo width={210} height={40} />
          </Link>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {nav.map(({ href, label, Icon }) => {
            const isActive =
              href === "/dashboard"
                ? pathname === "/dashboard"
                : pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-3 rounded-xl py-2.5 pl-3 pr-3 text-sm transition-all duration-150 ${
                  isActive
                    ? "border-l-[3px] border-brand font-semibold text-brand"
                    : "border-l-[3px] border-transparent font-medium text-gray-500 hover:text-gray-800"
                }`}
              >
                <Icon className={`shrink-0 ${isActive ? "text-brand" : "text-gray-400"}`} />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-gray-100 p-4">
          <div className="relative" ref={profileRef}>
            {profileOpen && (
              <div
                className="absolute bottom-full left-0 right-0 mb-2 overflow-hidden rounded-xl border border-gray-100 bg-white shadow-sm"
                role="menu"
              >
                <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-3">
                  <Avatar initials={currentUser.initials} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-gray-900">
                      {currentUser.name}
                    </p>
                    <span className="mt-0.5 inline-block rounded bg-gray-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                      {currentUser.role}
                    </span>
                  </div>
                </div>

                {profileBilling.status === "loading" && <ProfileBillingSkeleton />}
                {profileBilling.status === "ready" && (
                  <div className="space-y-1.5 border-b border-gray-100 px-4 py-3">
                    <span className="inline-flex rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700">
                      {profileBilling.planLabel}
                    </span>
                    <p className="text-xs text-gray-500">
                      {runsRemainingLabel(profileBilling.runsAvailable)}
                    </p>
                  </div>
                )}

                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full px-4 py-2.5 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50"
                  onClick={() => {
                    setProfileOpen(false);
                    router.push("/settings");
                  }}
                >
                  Settings
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full px-4 py-2.5 text-left text-sm text-red-500 transition-colors hover:bg-red-50"
                  onClick={() => void handleSignOut()}
                >
                  Sign Out
                </button>
              </div>
            )}
            <button
              type="button"
              className="flex w-full items-center gap-3 rounded-xl p-2 text-left transition-colors hover:bg-gray-50"
              onClick={() => setProfileOpen((open) => !open)}
              aria-expanded={profileOpen}
              aria-haspopup="menu"
            >
              <Avatar initials={currentUser.initials} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">{currentUser.name}</p>
                <span className="mt-0.5 inline-block rounded bg-gray-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                  {currentUser.role}
                </span>
              </div>
            </button>
          </div>
        </div>
      </aside>

      <div className="ml-[240px] flex min-h-screen min-w-0 w-[calc(100%-240px)] max-w-[calc(100%-240px)] flex-1 flex-col overflow-x-hidden">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-gray-100 bg-white px-8">
          <div />
          <div className="flex items-center gap-4">
            <button
              type="button"
              className="relative rounded-xl p-2 text-gray-400 hover:bg-gray-50 transition-colors"
              aria-label="Notifications"
              onClick={() => setPanelOpen(true)}
            >
              <BellIcon />
              {failedCount > 0 && (
                <span className="absolute right-1 top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[var(--danger)] px-1 text-[10px] font-bold text-white">
                  {failedCount}
                </span>
              )}
            </button>
            <div className="relative" ref={headerProfileRef}>
              <button
                type="button"
                className="flex items-center rounded-full transition-all hover:ring-2 hover:ring-brand/30"
                onClick={() => setHeaderProfileOpen((o) => !o)}
                aria-expanded={headerProfileOpen}
                aria-haspopup="menu"
                aria-label="Open profile menu"
              >
                <Avatar initials={currentUser.initials} />
              </button>
              {headerProfileOpen && (
                <div
                  className="absolute right-0 top-full mt-2 w-64 overflow-hidden rounded-xl border border-gray-100 bg-white shadow-lg"
                  role="menu"
                >
                  {/* ── User info header ── */}
                  <div className="border-b border-gray-100 px-4 py-3">
                    <p className="truncate text-sm font-medium text-gray-900">
                      {currentUser.name}
                    </p>
                    {currentUser.email && (
                      <p className="truncate text-xs text-gray-500">
                        {currentUser.email}
                      </p>
                    )}
                    <span className="mt-1.5 inline-block rounded bg-gray-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                      {currentUser.role}
                    </span>
                  </div>

                  {/* ── Admin-only: Invite team member ── */}
                  {currentUser.role === "ADMIN" && (
                    <button
                      type="button"
                      role="menuitem"
                      className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50"
                      onClick={() => {
                        setHeaderProfileOpen(false);
                        router.push("/settings/team?invite=1");
                      }}
                    >
                      <svg className="h-4 w-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4-4v2" />
                        <circle cx="9" cy="7" r="4" />
                        <line x1="19" y1="8" x2="19" y2="14" />
                        <line x1="22" y1="11" x2="16" y2="11" />
                      </svg>
                      Invite team member
                    </button>
                  )}

                  {/* ── Help & Support ── */}
                  <a
                    href="mailto:contact@recondesk.in"
                    role="menuitem"
                    className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50"
                    onClick={() => setHeaderProfileOpen(false)}
                  >
                    <svg className="h-4 w-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10" />
                      <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
                      <line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    Help &amp; Support
                  </a>

                  {/* ── Settings ── */}
                  <button
                    type="button"
                    role="menuitem"
                    className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50"
                    onClick={() => {
                      setHeaderProfileOpen(false);
                      router.push("/settings");
                    }}
                  >
                    <svg className="h-4 w-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="3" />
                      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
                    </svg>
                    Settings
                  </button>

                  {/* ── Separator + Sign Out ── */}
                  <div className="border-t border-gray-100">
                    <button
                      type="button"
                      role="menuitem"
                      className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-red-500 transition-colors hover:bg-red-50"
                      onClick={() => void handleSignOut()}
                    >
                      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
                        <polyline points="16 17 21 12 16 7" />
                        <line x1="21" y1="12" x2="9" y2="12" />
                      </svg>
                      Sign out
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto bg-white p-8">
          {children}
        </main>
      </div>

      {panelOpen && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-[80] bg-black/30"
            aria-label="Close notifications"
            onClick={() => setPanelOpen(false)}
          />
          <div className="fixed inset-y-0 right-0 z-[90] flex w-full max-w-md flex-col border-l border-gray-100 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
              <h2 className="text-base font-semibold text-gray-900">Failed reconciliations</h2>
              <button
                type="button"
                className="rounded-xl p-1.5 text-gray-400 hover:bg-gray-50 transition-colors"
                onClick={() => setPanelOpen(false)}
                aria-label="Close"
              >
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {failuresLoading && (
                <p className="text-sm text-gray-400">Loading failed runs…</p>
              )}
              {failuresError && (
                <p className="text-sm text-red-500">
                  Could not load failures.{" "}
                  <button
                    type="button"
                    className="font-semibold underline"
                    onClick={() => void mutateFailures()}
                  >
                    Retry
                  </button>
                </p>
              )}
              {!failuresLoading &&
                !failuresError &&
                failures &&
                failures.items.length === 0 && (
                  <p className="text-sm text-gray-400">No failed runs.</p>
                )}
              <ul className="space-y-3">
                {failures?.items.map((item) => (
                  <li
                    key={item.runId}
                    className="rounded-xl border border-gray-100 bg-white p-4 shadow-sm"
                  >
                    <p className="font-medium text-gray-900">{item.tradeName}</p>
                    <p className="text-xs text-gray-400">{item.period}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-red-500">{item.errorSnippet}</p>
                    <button
                      type="button"
                      className="mt-2 text-sm font-semibold text-brand hover:underline"
                      onClick={() => {
                        if (typeof accessToken !== "string") return;
                        void (async () => {
                          try {
                            await reconcileRunsApi.retryFailed(accessToken, item.runId);
                            toast("Retry queued", "success");
                            await mutateFailures();
                            await invalidateDw();
                            setPanelOpen(false);
                          } catch (e: unknown) {
                            toast(isApiError(e) ? e.detail : "Retry failed", "error");
                          }
                        })();
                      }}
                    >
                      Retry
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
