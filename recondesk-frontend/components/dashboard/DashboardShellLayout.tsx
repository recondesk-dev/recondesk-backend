"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { Avatar } from "@/components/ui/Avatar";
import { useToast } from "@/components/providers/ToastProvider";
import { authApi, isApiError, reconcileRunsApi } from "@/lib/api";
import { DW, formatPeriodLabel } from "@/lib/dashboard-portfolio";
import { subscribeAccessToken } from "@/lib/supabase/client";

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

function pageTitle(pathname: string): string {
  if (pathname === "/") return "Dashboard";
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
  const toast = useToast();
  const title = pageTitle(pathname);
  const [panelOpen, setPanelOpen] = useState(false);
  const [accessToken, setAccessToken] = useState<string | false | null>(null);
  const [currentUser, setCurrentUser] = useState({
    name: "…",
    role: "…",
    initials: "··",
  });

  useEffect(() => subscribeAccessToken(setAccessToken), []);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      if (accessToken === null) return;

      if (accessToken === false) {
        setCurrentUser({ name: "Guest", role: "—", initials: "?" });
        return;
      }

      try {
        const me = await authApi.me(accessToken);
        if (cancelled) return;
        const name = me.full_name?.trim() || me.email?.trim() || "User";
        const role = (me.role ?? "staff").toUpperCase();
        setCurrentUser({
          name,
          role,
          initials: initialsFromDisplayName(name),
        });
      } catch {
        if (cancelled) return;
        setCurrentUser({
          name: "User",
          role: "STAFF",
          initials: "?",
        });
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

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

  const nav = [
    { href: "/", label: "Dashboard", Icon: NavIconDashboard },
    { href: "/clients", label: "Clients", Icon: NavIconUsers },
    { href: "/runs", label: "Runs", Icon: NavIconRefresh },
    { href: "/billing", label: "Billing", Icon: NavIconCredit },
    { href: "/settings", label: "Settings", Icon: NavIconGear },
  ];

  return (
    <div className="flex min-h-screen min-w-[1280px] bg-[var(--bg)] text-[var(--text-primary)]">
      <aside className="fixed inset-y-0 left-0 flex w-[240px] flex-col bg-[var(--sidebar)] text-white">
        <div className="flex items-center gap-2 px-5 py-6">
          <span className="text-lg font-semibold tracking-tight" style={{ fontWeight: 600 }}>
            ReconDesk
          </span>
          <span className="h-2 w-2 rounded-full bg-[var(--accent)]" aria-hidden />
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {nav.map(({ href, label, Icon }) => {
            const isActive =
              href === "/"
                ? pathname === "/"
                : pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-3 border-l-4 px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-[var(--accent)] bg-[rgba(108,99,255,0.1)] text-white"
                    : "border-transparent text-[#6B7280] hover:text-white"
                }`}
              >
                <Icon className="shrink-0 opacity-90" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-white/10 p-4">
          <div className="flex items-center gap-3">
            <Avatar initials={currentUser.initials} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-white">{currentUser.name}</p>
              <span className="mt-0.5 inline-block rounded bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#9CA3AF]">
                {currentUser.role}
              </span>
            </div>
          </div>
        </div>
      </aside>

      <div className="ml-[240px] flex min-h-screen flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-8">
          <h1 className="text-lg font-semibold text-[var(--text-primary)]" style={{ fontSize: 18, fontWeight: 600 }}>
            {title}
          </h1>
          <div className="flex items-center gap-4">
            <button
              type="button"
              className="relative rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--bg)]"
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

        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>

      {panelOpen && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-[80] bg-black/30"
            aria-label="Close notifications"
            onClick={() => setPanelOpen(false)}
          />
          <div className="fixed inset-y-0 right-0 z-[90] flex w-full max-w-md flex-col border-l border-[var(--border)] bg-[var(--surface)] shadow-2xl">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
              <h2 className="text-base font-semibold">Failed reconciliations</h2>
              <button
                type="button"
                className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg)]"
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
                <p className="text-sm text-[var(--text-secondary)]">Loading failed runs…</p>
              )}
              {failuresError && (
                <p className="text-sm text-[var(--danger)]">
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
                  <p className="text-sm text-[var(--text-secondary)]">No failed runs.</p>
                )}
              <ul className="space-y-3">
                {failures?.items.map((item) => (
                  <li
                    key={item.runId}
                    className="rounded-lg border border-[var(--border)] p-3"
                  >
                    <p className="font-medium text-[var(--text-primary)]">{item.tradeName}</p>
                    <p className="text-xs text-[var(--text-secondary)]">{item.period}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-[var(--danger)]">{item.errorSnippet}</p>
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
