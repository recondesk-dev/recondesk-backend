"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import useSWR, { mutate } from "swr";
import { Avatar } from "@/components/ui/Avatar";
import { useToast } from "@/components/providers/ToastProvider";
import { authApi, isApiError, reconcileRunsApi, type AuthMeProfile } from "@/lib/api";
import { displayPlanName } from "@/lib/plan-display";
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

function subscriptionFromMe(me: AuthMeProfile) {
  const runsLimit = me.runs_limit ?? 2;
  const runsUsed = Math.max(0, me.runs_used ?? 0);
  return {
    plan: me.plan ?? null,
    runsUsed,
    runsLimit: Math.max(runsLimit, 1),
  };
}

function pageTitle(pathname: string): string {
  if (pathname === "/dashboard") return "Dashboard";
  if (pathname === "/clients") return "Clients";
  if (pathname === "/runs") return "Runs";
  if (pathname === "/billing") return "Billing";
  if (pathname.startsWith("/settings/team")) return "Team";
  if (pathname.startsWith("/settings")) return "Settings";
  if (/^\/clients\/[^/]+$/.test(pathname)) return "Client Detail";
  return "ReconDesk";
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
  const title = pageTitle(pathname);
  const [panelOpen, setPanelOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const [accessToken, setAccessToken] = useState<string | false | null>(null);
  const [currentUser, setCurrentUser] = useState({
    name: "…",
    role: "…",
    initials: "··",
  });
  const [subscription, setSubscription] = useState<{
    plan: string | null;
    runsUsed: number;
    runsLimit: number;
  } | null>(null);

  useEffect(() => subscribeAccessToken(setAccessToken), []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function applyMeProfile(me: AuthMeProfile) {
    const name = me.full_name?.trim() || me.email?.trim() || "User";
    const role = (me.role ?? "staff").toUpperCase();
    setCurrentUser({
      name,
      role,
      initials: initialsFromDisplayName(name),
    });
    setSubscription(subscriptionFromMe(me));
  }

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      if (accessToken === null) return;

      if (accessToken === false) {
        setCurrentUser({ name: "Guest", role: "—", initials: "?" });
        setSubscription(null);
        return;
      }

      try {
        const me = await authApi.me(accessToken);
        if (cancelled) return;
        applyMeProfile(me);
      } catch {
        if (cancelled) return;
        setCurrentUser({
          name: "User",
          role: "STAFF",
          initials: "?",
        });
        setSubscription(null);
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const runsUsed = subscription?.runsUsed ?? 0;
  const runsLimit = subscription?.runsLimit ?? 2;
  const runsLeft = Math.max(0, runsLimit - runsUsed);
  const runsUsedPct = Math.min(100, Math.round((runsUsed / runsLimit) * 100));

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
    <div className="flex min-h-screen min-w-[1280px] bg-[var(--bg)] text-[var(--text-primary)]">
      <aside className="fixed inset-y-0 left-0 z-50 flex w-[240px] flex-col bg-white border-r border-gray-100">
        <div className="flex items-center gap-2 px-5 py-6">
          <span
            className="font-brand text-lg font-semibold tracking-tight text-gray-900"
            style={{ fontWeight: 600 }}
          >
            ReconDesk
          </span>
          <span className="h-2 w-2 rounded-full bg-[var(--accent)]" aria-hidden />
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
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                  isActive
                    ? "bg-gray-100 font-semibold text-gray-900"
                    : "font-medium text-gray-400 hover:bg-gray-50 hover:text-gray-700"
                }`}
              >
                <Icon className={`shrink-0 ${isActive ? "text-gray-900" : "text-gray-400"}`} />
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

                <div className="space-y-2.5 border-b border-gray-100 px-4 py-3">
                  <span className="inline-flex rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700">
                    {subscription ? displayPlanName(subscription.plan) : "…"}
                  </span>
                  <div>
                    <div className="flex items-baseline justify-between gap-2 text-xs text-gray-500">
                      <span>
                        {subscription ? (
                          <>
                            {runsUsed} of {runsLimit} runs used
                          </>
                        ) : (
                          "Loading usage…"
                        )}
                      </span>
                      {subscription && (
                        <span className="shrink-0 font-medium text-gray-700">
                          {runsLeft} left
                        </span>
                      )}
                    </div>
                    <div
                      className="mt-1.5 h-1 overflow-hidden rounded-full bg-gray-100"
                      role="progressbar"
                      aria-valuenow={runsUsed}
                      aria-valuemin={0}
                      aria-valuemax={runsLimit}
                      aria-label={`${runsUsed} of ${runsLimit} runs used`}
                    >
                      <div
                        className="h-full rounded-full bg-emerald-500 transition-[width] duration-300"
                        style={{ width: subscription ? `${runsUsedPct}%` : "0%" }}
                      />
                    </div>
                  </div>
                </div>

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

      <div className="ml-[240px] flex min-h-screen flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-gray-100 bg-white px-8">
          <h1 className="text-lg font-semibold text-gray-900" style={{ fontSize: 18, fontWeight: 600 }}>
            {title}
          </h1>
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
            <Avatar initials={currentUser.initials} />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto bg-gray-50/50 p-8">{children}</main>
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
                      className="mt-2 text-sm font-semibold text-[var(--accent)] hover:underline"
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
