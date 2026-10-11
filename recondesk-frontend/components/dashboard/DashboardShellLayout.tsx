"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Logo } from "@/components/ui/Logo";
import useSWR, { mutate } from "swr";
import { Avatar } from "@/components/ui/Avatar";
import { LanguageToggle } from "@/components/ui/LanguageToggle";
import { useToast } from "@/components/providers/ToastProvider";
import { useTranslations } from "next-intl";
import { Menu, X, PanelLeftClose, PanelLeftOpen, Truck } from "lucide-react";
import {
  billingApi,
  isApiError,
  reconcileRunsApi,
  type BillingStatus,
} from "@/lib/api";
import {
  fetchFreshAuthProfile,
  normalizeAuthRole,
  resolveDisplayName,
  isRoleAdminOrPartner,
} from "@/lib/auth-profile";
import { DW, formatPeriodLabel } from "@/lib/dashboard-portfolio";
import { clearOnboardingDoneCookie } from "@/lib/onboarding-cookie";
import { subscribeAccessToken } from "@/lib/supabase/client";
import { Analytics } from "@/lib/analytics";

import { AccessibleTooltip } from "@/components/ui/AccessibleTooltip";
import { safeStorageGet, safeStorageSet } from "@/lib/safeStorage";

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

function planLabelFromBilling(status: BillingStatus): string {
  // Only show paid plan names for active GSTIN subscriptions.
  // Legacy run packs must not surface as "Pro" / "Starter" in the shell.
  if (status.subscription_active && status.plan) {
    return capitalizePlanName(status.plan);
  }
  return "Free";
}

function billingCapacityLabel(status: BillingStatus): string {
  if (status.subscription_active) {
    return `${status.gstins_used ?? 0}/${status.gstin_limit ?? 0} GSTINs`;
  }
  const runs =
    (status.free_runs_remaining ?? 0) + (status.runs_balance ?? 0);
  if (runs > 0) {
    return runs === 1 ? "1 run remaining" : `${runs} runs remaining`;
  }
  return `${status.gstins_used ?? 0}/${status.gstin_limit ?? 1} GSTINs`;
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

function NavIconVendors({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3 9l1.5-6h15L21 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M3 9v11a1 1 0 001 1h16a1 1 0 001-1V9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M9 21V12h6v9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
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

function NavIconDatabase({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <ellipse cx="12" cy="5" rx="9" ry="3" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

function NavIconGear({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12.22 2h-.44a2 2 0 00-2 2v.18a2 2 0 01-1 1.73l-.43.25a2 2 0 01-2 0l-.15-.08a2 2 0 00-2.73.73l-.22.38a2 2 0 00.73 2.73l.15.1a2 2 0 011 1.72v.51a2 2 0 01-1 1.74l-.15.09a2 2 0 00-.73 2.73l.22.38a2 2 0 002.73.73l.15-.08a2 2 0 012 0l.43.25a2 2 0 011 1.73V20a2 2 0 002 2h.44a2 2 0 002-2v-.18a2 2 0 011-1.73l.43-.25a2 2 0 012 0l.15.08a2 2 0 002.73-.73l.22-.39a2 2 0 00-.73-2.73l-.15-.08a2 2 0 01-1-1.74v-.5a2 2 0 011-1.74l.15-.09a2 2 0 00.73-2.73l-.22-.38a2 2 0 00-2.73-.73l-.15.08a2 2 0 01-2 0l-.43-.25a2 2 0 01-1-1.73V4a2 2 0 00-2-2z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function NavIconFileText({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M14 2v6h6M16 13H8M16 17H8M10 9H8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function NavIconTruck({ className }: { className?: string }) {
  return <Truck className={className} size={18} />;
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
  const toast = useToast();
  const [panelOpen, setPanelOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!mobileMenuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const sidebar = sidebarRef.current;
    sidebar?.querySelector<HTMLButtonElement>('button[aria-label="Close menu"]')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setMobileMenuOpen(false); }
      if (event.key === "Tab" && sidebar) {
        const elements = Array.from(sidebar.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex="0"]')).filter(el => el.getClientRects().length > 0);
        const first = elements[0], last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    const desktop = window.matchMedia("(min-width: 1024px)");
    const onResize = () => { if (desktop.matches) setMobileMenuOpen(false); };
    document.addEventListener("keydown", onKey);
    desktop.addEventListener("change", onResize);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
      desktop.removeEventListener("change", onResize);
      if (!desktop.matches) menuTriggerRef.current?.focus();
    };
  }, [mobileMenuOpen]);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const [headerProfileOpen, setHeaderProfileOpen] = useState(false);
  const headerProfileRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [pathname]);
  const [accessToken, setAccessToken] = useState<string | false | null>(null);
  const [currentUser, setCurrentUser] = useState({
    name: "…",
    email: "",
    role: "…",
    initials: "··",
  });
  // User-scoped storage key
  const userStorageKey = useMemo(() => {
    const raw = currentUser.email || "";
    const clean = raw.trim().toLowerCase().replace(/[^a-z0-9]/g, "_");
    return clean ? `recondesk_sidebar_collapsed_${clean}` : "recondesk_sidebar_collapsed";
  }, [currentUser.email]);

  // Load layout preference scoped to user
  useEffect(() => {
    const stored = safeStorageGet<boolean | null>(userStorageKey, null);
    if (stored !== null) {
      setSidebarCollapsed(stored);
    } else {
      const legacy = safeStorageGet<boolean | null>("recondesk_sidebar_collapsed", null);
      if (legacy !== null) {
        setSidebarCollapsed(legacy);
      }
    }
  }, [userStorageKey]);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      safeStorageSet(userStorageKey, next);
      return next;
    });
  }, [userStorageKey]);

  // Optional ⌘B / Ctrl+B shortcut: disabled while typing in editable fields
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        const target = document.activeElement;
        const isInputField =
          target instanceof HTMLInputElement ||
          target instanceof HTMLTextAreaElement ||
          target instanceof HTMLSelectElement ||
          (target as HTMLElement)?.isContentEditable;
        if (!isInputField) {
          e.preventDefault();
          toggleSidebar();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggleSidebar]);
  const [profileBilling, setProfileBilling] = useState<
    | { status: "idle" }
    | { status: "loading" }
    | { status: "ready"; planLabel: string; capacityLabel: string }
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
        Analytics.identify({ id: me.id ?? "", email: me.email ?? "", name });
        Analytics.identify({ id: me.id ?? "", email: me.email ?? "", name });
      } catch (err) {
        if (cancelled) return;
        console.warn("[DashboardShellLayout] fetchFreshAuthProfile failed, using fallback:", err);
        
        const name = "User";
        setCurrentUser({
          name,
          email: "",
          role: "VIEWER",
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
          planLabel: planLabelFromBilling(status),
          capacityLabel: billingCapacityLabel(status),
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
        light: true,
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

  function handleSignOut(): void {
    clearOnboardingDoneCookie();
    window.location.href = "/api/auth/cognito-logout";
  }

  const tNav = useTranslations("nav");
  const tNotif = useTranslations("notifications");

  const nav = [
    { href: "/dashboard", label: tNav("dashboard"), Icon: NavIconDashboard },
    { href: "/clients", label: tNav("clients"), Icon: NavIconUsers },
    { href: "/vendors", label: tNav("vendors"), Icon: NavIconVendors },
    { href: "/reconciliations", label: tNav("reconciliations"), Icon: NavIconRefresh },
    { href: "/einvoicing", label: tNav("einvoicing"), Icon: NavIconFileText },
    { href: "/einvoicing/ewaybill", label: tNav("ewaybill"), Icon: NavIconTruck },
    ...(isRoleAdminOrPartner(currentUser.role)
      ? [{ href: "/manage-data", label: tNav("manageData"), Icon: NavIconDatabase }]
      : []),
    { href: "/billing", label: tNav("billing"), Icon: NavIconCredit },
    { href: "/settings", label: tNav("settings"), Icon: NavIconGear },
  ];

  return (
    <div
      data-sidebar-collapsed={sidebarCollapsed ? "true" : "false"}
      style={
        {
          "--workspace-sidebar-offset": sidebarCollapsed ? "96px" : "252px",
        } as React.CSSProperties
      }
      className="rd-workspace dashboard-soft-bg flex min-h-screen w-full min-w-0 text-[var(--text-primary)]"
    >
      {/* Mobile/Tablet Backdrop */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm transition-opacity lg:hidden"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Responsive Navigation Sidebar */}
      <aside
        ref={sidebarRef}
        id="workspace-navigation"
        data-open={mobileMenuOpen}
        data-collapsed={sidebarCollapsed}
        aria-label="Workspace navigation"
        className={`rd-workspace-sidebar fixed inset-y-3 left-3 z-50 flex flex-col rounded-[1.75rem] bg-white shadow-[var(--shadow-lift)] transition-all duration-200 motion-reduce:transition-none lg:translate-x-0 lg:shadow-[var(--shadow-soft)] ${
          sidebarCollapsed ? "w-[68px]" : "w-[230px] lg:w-[196px]"
        } ${
          mobileMenuOpen ? "translate-x-0" : "-translate-x-[120%] lg:translate-x-0"
        }`}
      >
        <div
          className={`rd-sidebar-brand flex items-center ${
            sidebarCollapsed
              ? "justify-center px-2 py-5 flex-col gap-2"
              : "justify-between px-4 pb-3 pt-5"
          }`}
        >
          <Link
            href="/dashboard"
            className="flex items-center"
            onClick={() => setMobileMenuOpen(false)}
            title="ReconDesk"
            aria-label="ReconDesk Home"
          >
            {sidebarCollapsed ? (
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 font-bold text-white text-base tracking-tighter shadow-xs">
                R<span className="h-1.5 w-1.5 rounded-full bg-[#7B5CFA] ml-0.5" />
              </span>
            ) : (
              <Logo height={40} />
            )}
          </Link>

          {/* Primary Sidebar Collapse Toggle (Desktop) */}
          <AccessibleTooltip
            content={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            shortcut="⌘B"
            side="right"
          >
            <button
              type="button"
              onClick={toggleSidebar}
              aria-expanded={!sidebarCollapsed}
              aria-controls="workspace-navigation"
              aria-label={sidebarCollapsed ? "Expand navigation sidebar (⌘B)" : "Collapse navigation sidebar (⌘B)"}
              className="hidden lg:flex items-center justify-center h-7 w-7 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen className="h-4 w-4" />
              ) : (
                <PanelLeftClose className="h-4 w-4" />
              )}
            </button>
          </AccessibleTooltip>

          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700 lg:hidden"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Close menu"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5 px-2 overflow-y-auto">
          {!sidebarCollapsed && <span className="rd-nav-caption">WORKSPACE</span>}
          {nav.map(({ href, label, Icon }) => {
            const isActive =
              href === "/dashboard"
                ? pathname === "/dashboard"
                : href === "/einvoicing"
                ? pathname === "/einvoicing" || (pathname.startsWith("/einvoicing/") && !pathname.startsWith("/einvoicing/ewaybill"))
                : pathname === href || pathname.startsWith(`${href}/`);
            const navLink = (
              <Link
                key={href}
                href={href}
                aria-current={isActive ? "page" : undefined}
                aria-label={label}
                onClick={() => setMobileMenuOpen(false)}
                className={`flex items-center gap-2.5 rounded-full px-3 py-2 text-[13px] transition-all duration-200 ${
                  sidebarCollapsed
                    ? "justify-center px-0 h-10 w-10 mx-auto"
                    : ""
                } ${
                  isActive
                    ? "bg-[var(--ink)] font-semibold text-white shadow-sm"
                    : "font-medium text-gray-500 hover:bg-gray-50 hover:text-gray-900"
                }`}
              >
                <Icon
                  className={`h-4 w-4 shrink-0 ${
                    isActive ? "text-white" : "text-gray-400"
                  }`}
                />
                {!sidebarCollapsed && <span>{label}</span>}
              </Link>
            );

            if (sidebarCollapsed) {
              return (
                <AccessibleTooltip key={href} content={label} side="right" className="w-full justify-center">
                  {navLink}
                </AccessibleTooltip>
              );
            }
            return navLink;
          })}
        </nav>

        <div className={`p-3 ${sidebarCollapsed ? "px-1.5" : ""}`}>
          <div className="relative" ref={profileRef}>
            {profileOpen && (
              <div
                className={`absolute bottom-full z-[60] mb-2 overflow-hidden rounded-2xl bg-white shadow-[var(--shadow-lift)] ring-1 ring-black/[0.04] ${
                  sidebarCollapsed ? "left-0 w-60" : "left-0 right-0"
                }`}
                role="menu"
              >
                <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-3">
                  <Avatar initials={currentUser.initials} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-gray-900">
                      {currentUser.name}
                    </p>
                    <span className="mt-0.5 inline-block rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                      {currentUser.role}
                    </span>
                  </div>
                </div>

                {profileBilling.status === "loading" && <ProfileBillingSkeleton />}
                {profileBilling.status === "ready" && (
                  <div className="space-y-1.5 border-b border-gray-100 px-4 py-3">
                    <span className="inline-flex rounded-full bg-gray-100 px-2.5 py-0.5 text-[11px] font-semibold text-gray-700">
                      {profileBilling.planLabel}
                    </span>
                    <p className="text-xs text-gray-500">
                      {profileBilling.capacityLabel}
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
                  {tNav("settings")}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full px-4 py-2.5 text-left text-sm text-red-500 transition-colors hover:bg-red-50"
                  onClick={() => void handleSignOut()}
                >
                  {tNav("signOut")}
                </button>
              </div>
            )}
            <button
              type="button"
              className={`flex w-full items-center gap-2.5 rounded-2xl p-1.5 text-left transition-colors hover:bg-gray-50 ${
                sidebarCollapsed ? "justify-center p-1" : ""
              }`}
              onClick={() => setProfileOpen((open) => !open)}
              aria-expanded={profileOpen}
              aria-haspopup="menu"
              aria-label={currentUser.name}
              title={sidebarCollapsed ? `${currentUser.name} (${currentUser.role})` : undefined}
            >
              <span className="relative shrink-0">
                <Avatar initials={currentUser.initials} />
              </span>
              {!sidebarCollapsed && (
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-semibold text-gray-900">{currentUser.name}</p>
                  <p className="truncate text-[11px] text-gray-400">
                    {currentUser.email || currentUser.role}
                  </p>
                </div>
              )}
            </button>
          </div>
        </div>
      </aside>

      <div
        className={`rd-workspace-main flex min-h-screen min-w-0 w-full flex-1 flex-col overflow-x-hidden transition-all duration-200 motion-reduce:transition-none ${
          sidebarCollapsed
            ? "lg:ml-[96px] lg:w-[calc(100%-96px)] lg:max-w-[calc(100%-96px)]"
            : "lg:ml-[216px] lg:w-[calc(100%-216px)] lg:max-w-[calc(100%-216px)]"
        }`}
      >
        <header className="rd-workspace-header relative z-[60] flex h-16 shrink-0 items-center justify-between px-4 sm:px-6 pt-2">
          <div className="flex items-center gap-3">
            {/* Header sidebar toggle */}
            <AccessibleTooltip
              content={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              shortcut="⌘B"
              side="bottom"
            >
              <button
                type="button"
                onClick={toggleSidebar}
                aria-expanded={!sidebarCollapsed}
                aria-controls="workspace-navigation"
                aria-label={sidebarCollapsed ? "Expand navigation sidebar (⌘B)" : "Collapse navigation sidebar (⌘B)"}
                className="hidden lg:flex items-center justify-center h-8 w-8 rounded-lg text-gray-500 hover:text-gray-900 hover:bg-white/80 border border-gray-200/70 shadow-xs transition-colors"
              >
                {sidebarCollapsed ? (
                  <PanelLeftOpen className="h-4 w-4" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </button>
            </AccessibleTooltip>

            <div className="rd-workspace-breadcrumb hidden lg:flex" aria-label="Current workspace">
              <span>ReconDesk</span><span aria-hidden="true">/</span>
              <strong>
                {nav.find(({ href }) => pathname === href)?.label ??
                  nav
                    .filter(({ href }) => pathname.startsWith(`${href}/`))
                    .sort((a, b) => b.href.length - a.href.length)[0]?.label ??
                  "Workspace"}
              </strong>
            </div>
            <button
              type="button"
              className="flex items-center justify-center rounded-full bg-white p-2 text-gray-600 shadow-[var(--shadow-soft)] hover:bg-gray-50 hover:text-gray-900 lg:hidden"
              onClick={() => setMobileMenuOpen(true)}
              ref={menuTriggerRef}
              aria-expanded={mobileMenuOpen}
              aria-controls="workspace-navigation"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="lg:hidden flex items-center">
              <Link href="/dashboard" className="flex items-center">
                <Logo width={120} height={22} />
              </Link>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <LanguageToggle />
            <button
              type="button"
              className="relative rounded-full bg-white p-2.5 text-gray-500 shadow-[var(--shadow-soft)] transition-colors hover:text-gray-900"
              aria-label={tNav("notifications")}
              onClick={() => setPanelOpen(true)}
            >
              <BellIcon />
              {failedCount > 0 && (
                <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-[var(--danger)] ring-2 ring-white" />
              )}
            </button>
            <div className="relative z-[70]" ref={headerProfileRef}>
              <button
                type="button"
                className="flex items-center rounded-full bg-white p-1 shadow-[var(--shadow-soft)] transition-all hover:ring-2 hover:ring-black/10"
                onClick={() => setHeaderProfileOpen((o) => !o)}
                aria-expanded={headerProfileOpen}
                aria-haspopup="menu"
                aria-label={tNav("openProfileMenu")}
              >
                <Avatar initials={currentUser.initials} />
              </button>
              {headerProfileOpen && (
                <div
                  className="absolute right-0 top-full z-[70] mt-2 w-64 overflow-hidden rounded-2xl bg-white shadow-[var(--shadow-lift)] ring-1 ring-black/[0.04]"
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

                  {/* ── Admin/Partner: Invite team member ── */}
                  {isRoleAdminOrPartner(currentUser.role) && (
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
                      {tNav("inviteTeamMember")}
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
                    {tNav("helpSupport")}
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
                    {tNav("settings")}
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
                      {tNav("signOut")}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="rd-workspace-content min-w-0 flex-1 overflow-x-hidden overflow-y-auto px-4 sm:px-6 pb-10 pt-2">
          {children}
        </main>
      </div>

      {panelOpen && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-[80] bg-black/20 backdrop-blur-[2px]"
            aria-label={tNotif("close")}
            onClick={() => setPanelOpen(false)}
          />
          <div className="fixed inset-y-3 right-3 z-[90] flex w-full max-w-md flex-col overflow-hidden rounded-[1.75rem] bg-white shadow-[var(--shadow-lift)] ring-1 ring-black/[0.04]">
            <div className="flex items-center justify-between px-5 pb-3 pt-5">
              <div>
                <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
                  {tNotif("failedReconciliations")}
                </h2>
                {failedCount > 0 && (
                  <p className="mt-0.5 text-sm text-gray-500">
                    {failedCount} {tNotif("reconciliationsNeedRetry")}
                  </p>
                )}
              </div>
              <button
                type="button"
                className="rounded-full bg-[#F5F5F6] p-2 text-gray-500 transition-colors hover:bg-gray-200/70 hover:text-[var(--ink)]"
                onClick={() => setPanelOpen(false)}
                aria-label={tNotif("close")}
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-4 pb-5">
              {failuresLoading && (
                <div className="space-y-2.5">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-24 animate-pulse rounded-2xl bg-[#F7F7F8]" />
                  ))}
                </div>
              )}
              {failuresError && (
                <div className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-800">
                  {tNotif("couldNotLoad")}{" "}
                  <button
                    type="button"
                    className="font-semibold text-[var(--ink)] underline"
                    onClick={() => void mutateFailures()}
                  >
                    {tNotif("retry")}
                  </button>
                </div>
              )}
              {!failuresLoading &&
                !failuresError &&
                failures &&
                failures.items.length === 0 && (
                  <div className="rounded-2xl bg-[#F7F7F8] px-4 py-10 text-center">
                    <p className="text-sm font-medium text-[var(--ink)]">{tNotif("noFailed")}</p>
                    <p className="mt-1 text-xs text-gray-400">{tNotif("allClear")}</p>
                  </div>
                )}
              <ul className="space-y-2.5">
                {failures?.items.map((item) => (
                  <li
                    key={item.runId}
                    className="rounded-2xl bg-[#F7F7F8] px-4 py-3.5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-[var(--ink)]">
                          {item.tradeName}
                        </p>
                        <p className="mt-0.5 text-xs text-gray-400">{item.period}</p>
                      </div>
                      <button
                        type="button"
                        className="shrink-0 rounded-full bg-[var(--ink)] px-3.5 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90"
                        onClick={() => {
                          if (typeof accessToken !== "string") return;
                          void (async () => {
                            try {
                              await reconcileRunsApi.retryFailed(accessToken, item.runId);
                              toast(tNotif("retryQueued"), "success");
                              await mutateFailures();
                              await invalidateDw();
                              setPanelOpen(false);
                            } catch (e: unknown) {
                              toast(isApiError(e) ? e.detail : tNotif("retryFailed"), "error");
                            }
                          })();
                        }}
                      >
                        {tNotif("retry")}
                      </button>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-red-600">
                      {item.errorSnippet}
                    </p>
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
