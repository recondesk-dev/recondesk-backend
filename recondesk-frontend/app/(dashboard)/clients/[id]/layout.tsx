"use client";

import Link from "next/link";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Check, SlidersHorizontal } from "lucide-react";

interface NavItem {
  label: string;
  href: string;
  description: string;
  isActive: (pathname: string, searchParams: URLSearchParams | null) => boolean;
}

interface NavGroup {
  id: string;
  label: string;
  icon?: typeof SlidersHorizontal;
  items: NavItem[];
}

function ClientWorkspaceNav({ id }: { id: string }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const navRef = useRef<HTMLDivElement>(null);
  const [openMenu, setOpenMenu] = useState<string | null>(null);

  // Close menus on outside click or escape
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpenMenu(null);
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  // Close menu on route change
  useEffect(() => {
    setOpenMenu(null);
  }, [pathname, searchParams]);

  const groups: NavGroup[] = useMemo(
    () => [
      {
        id: "reconciliation",
        label: "Reconciliation",
        items: [
          {
            label: "GSTR-2B Reconciliation",
            href: `/reconcile/${id}/new`,
            description:
              "Purchase Register vs GSTR-2B — ITC matching and eligibility",
            isActive: (p) =>
              p.startsWith(`/reconcile/${id}`) || p.startsWith("/reconcile/runs"),
          },
          {
            label: "GSTR-1 Reconciliation",
            href: `/reconcile/gstr1/new?client_gstin_id=${encodeURIComponent(id)}`,
            description:
              "Sales Register ↔ GSTR-1 matching & outward tax tie-out",
            isActive: (p) => p.startsWith("/reconcile/gstr1"),
          },
          {
            label: "2A vs 2B Timing Analysis",
            href: `/clients/${id}/gstr2a-delta`,
            description:
              "Supplier filing cutoff analysis & deferred ITC tracking",
            isActive: (p) =>
              p === `/clients/${id}/gstr2a-delta` ||
              p.startsWith(`/clients/${id}/gstr2a-delta/`),
          },
          {
            label: "Annual Purchase Reconciliation",
            href: `/clients/${id}/multi-period`,
            description:
              "12-month batch — Books vs GSTR-2B reconciliation",
            isActive: (p) =>
              p === `/clients/${id}/multi-period` ||
              p.startsWith(`/clients/${id}/multi-period/`),
          },
        ],
      },
      {
        id: "compliance",
        label: "Compliance",
        items: [
          {
            label: "GSTR-3B",
            href: "/filing/gstr-3b",
            description:
              "Table 4 ITC compilation & return summary (Filing gated)",
            isActive: (p) => p.startsWith("/filing/gstr-3b"),
          },
          {
            label: "Reversal & Reclaim Ledger",
            href: `/clients/${id}/reversal-ledger`,
            description:
              "Table 4(B)(2) longitudinal tracking, condition evidence & authorized reclaims",
            isActive: (p) =>
              p === `/clients/${id}/reversal-ledger` ||
              p.startsWith(`/clients/${id}/reversal-ledger/`),
          },
          {
            label: "GSTR-9",
            href: `/clients/${id}/gstr9`,
            description:
              "Annual Return workspace (Tables 4, 5, 6, 7, 8, 9)",
            isActive: (p, sp) =>
              (p === `/clients/${id}/gstr9` ||
                p.startsWith(`/clients/${id}/gstr9/`)) &&
              sp?.get("tab") !== "gstr9c",
          },
          {
            label: "Annual ITC Reconciliation",
            href: `/clients/${id}/gstr9c`,
            description:
              "Annual 2B vs 3B ITC variance with GSTR-9/9C support",
            isActive: (p) =>
              p === `/clients/${id}/gstr9c` ||
              p.startsWith(`/clients/${id}/gstr9c/`),
          },
          {
            label: "GSTR-9C Audit Statement",
            href: `/clients/${id}/gstr9?tab=gstr9c`,
            description:
              "Statutory reconciliation statement under Section 44(2)",
            isActive: (p, sp) =>
              (p === `/clients/${id}/gstr9` ||
                p.startsWith(`/clients/${id}/gstr9/`)) &&
              sp?.get("tab") === "gstr9c",
          },
          {
            label: "Notice Defense & Workpapers",
            href: `/clients/${id}/notices`,
            description:
              "Form GST DRC-01C, ASMT-10 & DRC-01 audit defense & mathematical reconciliation annexures",
            isActive: (p) =>
              p === `/clients/${id}/notices` ||
              p.startsWith(`/clients/${id}/notices/`),
          },
        ],
      },
      {
        id: "vendors",
        label: "Vendors & Resolution",
        items: [
          {
            label: "Vendor Risk",
            href: `/clients/${id}/followup?tab=risk_list`,
            description:
              "Supplier compliance rating & unfiled return exposure",
            isActive: (p, sp) =>
              p === `/clients/${id}/followup` && sp?.get("tab") === "risk_list",
          },
          {
            label: "Vendor Follow-up Hub",
            href: `/clients/${id}/followup`,
            description:
              "Automated notices, Rule 37A reminders, WhatsApp/Email dispatch",
            isActive: (p, sp) =>
              p === `/clients/${id}/followup` && sp?.get("tab") !== "risk_list",
          },
          {
            label: "Communication",
            href: `/clients/${id}/communication`,
            description:
              "Communication Center & message history",
            isActive: (p) =>
              p === `/clients/${id}/communication` ||
              p.startsWith(`/clients/${id}/communication/`),
          },
          {
            label: "Follow-up History",
            href: `/clients/${id}/follow-up`,
            description:
              "Dispatch audit trail & formal notice record",
            isActive: (p) =>
              p === `/clients/${id}/follow-up` ||
              p.startsWith(`/clients/${id}/follow-up/`),
          },
        ],
      },
    ],
    [id]
  );

  const settingsGroup: NavGroup = useMemo(
    () => ({
      id: "settings",
      label: "Settings & Data",
      icon: SlidersHorizontal,
      items: [
        {
          label: "Excel / Tally Field Mapping",
          href: `/clients/${id}/import-mapping`,
          description:
            "Configure column mappings for purchase & sales registers",
          isActive: (p) =>
            p === `/clients/${id}/import-mapping` ||
            p.startsWith(`/clients/${id}/import-mapping/`),
        },
        {
          label: "Manage Data",
          href: "/manage-data",
          description:
            "Historical returns & client registers",
          isActive: (p) => p.startsWith("/manage-data"),
        },
        {
          label: "Tally / ERP Bridge",
          href: "/settings/tally-bridge",
          description:
            "Desktop connector setup & sync",
          isActive: (p) => p.startsWith("/settings/tally-bridge"),
        },
      ],
    }),
    [id]
  );

  const isOverviewActive = pathname === `/clients/${id}`;
  const isCommandCenterActive = pathname === `/clients/${id}/command-center` || pathname.startsWith(`/clients/${id}/command-center/`);

  const isGroupActive = (group: NavGroup) =>
    group.items.some((item) => item.isActive(pathname, searchParams));

  const activeGroup = useMemo(() => {
    const all = [...groups, settingsGroup];
    return all.find((g) => isGroupActive(g)) || null;
  }, [groups, settingsGroup, pathname, searchParams]);

  return (
    <div ref={navRef} className="space-y-3">
      {/* Primary Top Navigation Row */}
      <nav className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* Overview Tab */}
          <Link
            href={`/clients/${id}`}
            className={
              isOverviewActive
                ? "rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white shadow-sm"
                : "rounded-full bg-white px-4 py-2 text-sm font-medium text-gray-500 shadow-[var(--shadow-soft)] transition-colors hover:text-[var(--ink)]"
            }
          >
            Overview
          </Link>

          {/* ITC Command Center Tab */}
          <Link
            href={`/clients/${id}/command-center`}
            className={
              isCommandCenterActive
                ? "rounded-full bg-black px-4 py-2 text-sm font-semibold text-white shadow-sm flex items-center gap-1.5"
                : "rounded-full bg-white px-4 py-2 text-sm font-medium text-gray-600 shadow-[var(--shadow-soft)] transition-colors hover:text-[var(--ink)] flex items-center gap-1.5"
            }
          >
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <span>ITC Command Center</span>
          </Link>


          {/* Grouped Workflow Tabs */}
          {groups.map((group) => {
            const active = isGroupActive(group);
            const isOpen = openMenu === group.id;

            return (
              <div key={group.id} className="relative">
                <button
                  type="button"
                  onClick={() => setOpenMenu(isOpen ? null : group.id)}
                  aria-expanded={isOpen}
                  className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm transition-colors ${
                    active
                      ? "bg-[var(--ink)] font-semibold text-white shadow-sm"
                      : "bg-white font-medium text-gray-500 shadow-[var(--shadow-soft)] hover:text-[var(--ink)]"
                  }`}
                >
                  <span>{group.label}</span>
                  <ChevronDown
                    size={14}
                    className={`transition-transform ${
                      isOpen ? "rotate-180" : ""
                    } ${active ? "text-white/80" : "text-gray-400"}`}
                  />
                </button>

                {isOpen && (
                  <div className="absolute left-0 mt-2 w-72 sm:w-80 rounded-2xl bg-white p-2 shadow-xl ring-1 ring-[#F0F0F0] z-50">
                    <div className="px-3 py-1.5 border-b border-gray-100 mb-1">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                        {group.label} Workflows
                      </p>
                    </div>
                    {group.items.map((item) => {
                      const itemActive = item.isActive(pathname, searchParams);
                      return (
                        <Link
                          key={item.href}
                          href={item.href}
                          onClick={() => setOpenMenu(null)}
                          className={`group flex flex-col gap-0.5 rounded-xl px-3.5 py-2.5 transition-colors ${
                            itemActive
                              ? "bg-[#F7F7F8] text-[var(--ink)]"
                              : "hover:bg-[#F7F7F8] text-gray-700"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span
                              className={`text-sm ${
                                itemActive
                                  ? "font-semibold text-[var(--ink)]"
                                  : "font-medium group-hover:text-[var(--ink)]"
                              }`}
                            >
                              {item.label}
                            </span>
                            {itemActive && (
                              <Check size={14} className="text-[var(--ink)]" />
                            )}
                          </div>
                          <span className="text-[11px] leading-tight text-gray-400 group-hover:text-gray-500">
                            {item.description}
                          </span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Right Utility: Settings & Data */}
        <div className="relative">
          <button
            type="button"
            onClick={() =>
              setOpenMenu(openMenu === settingsGroup.id ? null : settingsGroup.id)
            }
            aria-expanded={openMenu === settingsGroup.id}
            className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-sm transition-colors ${
              isGroupActive(settingsGroup)
                ? "bg-[var(--ink)] font-semibold text-white shadow-sm"
                : "bg-white font-medium text-gray-500 shadow-[var(--shadow-soft)] hover:text-[var(--ink)]"
            }`}
          >
            <SlidersHorizontal size={14} className="opacity-70" />
            <span className="hidden sm:inline">{settingsGroup.label}</span>
            <ChevronDown
              size={14}
              className={`transition-transform ${
                openMenu === settingsGroup.id ? "rotate-180" : ""
              }`}
            />
          </button>

          {openMenu === settingsGroup.id && (
            <div className="absolute right-0 mt-2 w-72 sm:w-80 rounded-2xl bg-white p-2 shadow-xl ring-1 ring-[#F0F0F0] z-50">
              <div className="px-3 py-1.5 border-b border-gray-100 mb-1">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  Client Data & Configuration
                </p>
              </div>
              {settingsGroup.items.map((item) => {
                const itemActive = item.isActive(pathname, searchParams);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpenMenu(null)}
                    className={`group flex flex-col gap-0.5 rounded-xl px-3.5 py-2.5 transition-colors ${
                      itemActive
                        ? "bg-[#F7F7F8] text-[var(--ink)]"
                        : "hover:bg-[#F7F7F8] text-gray-700"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span
                        className={`text-sm ${
                          itemActive
                            ? "font-semibold text-[var(--ink)]"
                            : "font-medium group-hover:text-[var(--ink)]"
                        }`}
                      >
                        {item.label}
                      </span>
                      {itemActive && (
                        <Check size={14} className="text-[var(--ink)]" />
                      )}
                    </div>
                    <span className="text-[11px] leading-tight text-gray-400 group-hover:text-gray-500">
                      {item.description}
                    </span>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </nav>

      {/* Contextual Sub-Navigation Strip (when inside a group workflow) */}
      {activeGroup && !isOverviewActive && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-2xl bg-[#F7F7F8] px-3 py-1.5 ring-1 ring-black/[0.04]">
          <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            {activeGroup.label}:
          </span>
          {activeGroup.items.map((item) => {
            const itemActive = item.isActive(pathname, searchParams);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-full px-3 py-1 text-xs transition-colors ${
                  itemActive
                    ? "bg-[var(--ink)] font-semibold text-white shadow-xs"
                    : "font-medium text-gray-600 hover:bg-white/80 hover:text-[var(--ink)]"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ClientWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const id = (params?.id as string) || "";

  return (
    <div className="space-y-6">
      <Suspense
        fallback={
          <div className="flex h-10 animate-pulse items-center rounded-full bg-gray-100" />
        }
      >
        <ClientWorkspaceNav id={id} />
      </Suspense>
      <div>{children}</div>
    </div>
  );
}
