"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, FileSearch, Shield, Users } from "lucide-react";

const ATTENTION_ROWS = [
  { initials: "AK", name: "Aarav Textiles", status: "Pending", tone: "amber" as const },
  { initials: "PS", name: "Priya Softwares", status: "In progress", tone: "ink" as const },
  { initials: "NM", name: "Nova Metals", status: "Ready", tone: "emerald" as const },
  { initials: "RL", name: "Ravi Logistics", status: "Failed", tone: "rose" as const },
];

const FEATURES = [
  {
    title: "5-level invoice matching",
    description: "Exact to probable matches across thousands of invoices in minutes.",
  },
  {
    title: "ITC at risk in ₹",
    description: "See missed credit in rupees — not buried in spreadsheet columns.",
  },
  {
    title: "Priority clients first",
    description: "Needs-attention list so your team knows who to act on next.",
  },
  {
    title: "Decision-ready mismatches",
    description: "What’s wrong, why it happened, and what to do — per invoice.",
  },
];

function statusClass(tone: "amber" | "ink" | "emerald" | "rose") {
  switch (tone) {
    case "amber":
      return "bg-amber-50 text-amber-700";
    case "emerald":
      return "bg-emerald-50 text-emerald-700";
    case "rose":
      return "bg-rose-50 text-rose-700";
    default:
      return "bg-[#F0F0F0] text-gray-700";
  }
}

export function LandingDashboardPreview() {
  const [activeRow, setActiveRow] = useState(0);

  useEffect(() => {
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;

    const id = window.setInterval(() => {
      setActiveRow((prev) => (prev + 1) % ATTENTION_ROWS.length);
    }, 2800);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-12">
      {/* Dashboard mock */}
      <div
        className="landing-dash-enter relative mx-auto w-full max-w-lg lg:max-w-none"
        aria-hidden
      >
        <div className="overflow-hidden rounded-[1.75rem] bg-white shadow-[var(--shadow-lift)]">
          {/* Fake chrome */}
          <div className="flex items-center gap-2 border-b border-[#F0F0F0] px-4 py-3">
            <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
            <span className="ml-3 truncate rounded-full bg-[#F5F5F6] px-3 py-1 text-[11px] font-medium text-gray-400">
              app.recondesk.in / dashboard
            </span>
          </div>

          <div className="flex">
            {/* Mini sidebar */}
            <aside className="hidden w-[72px] shrink-0 border-r border-[#F0F0F0] bg-[#FAFAFB] p-3 sm:block">
              <div className="mb-4 h-8 w-8 rounded-full bg-[var(--ink)]" />
              <div className="space-y-2">
                <div className="h-8 rounded-full bg-[var(--ink)]" />
                <div className="h-8 rounded-full bg-[#EFEFEF]" />
                <div className="h-8 rounded-full bg-[#EFEFEF]" />
                <div className="h-8 rounded-full bg-[#EFEFEF]" />
              </div>
            </aside>

            {/* Main panel */}
            <div className="min-w-0 flex-1 bg-[var(--bg)] p-4 sm:p-5">
              <div className="landing-dash-stagger-1">
                <p className="text-sm font-semibold tracking-tight text-[var(--ink)]">Quick Stats</p>
                <p className="mt-0.5 text-[11px] text-gray-500">Portfolio snapshot for this return period</p>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <div className="landing-dash-stagger-2 flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-[var(--ink)] p-3 text-white shadow-[var(--shadow-soft)]">
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-white/15">
                    <AlertTriangle className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <p className="landing-dash-pulse font-sans text-xl font-semibold tracking-tight">4</p>
                    <p className="mt-0.5 text-[10px] font-medium text-white/65">Needs Attention</p>
                  </div>
                </div>
                <div className="landing-dash-stagger-3 flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-white p-3 shadow-[var(--shadow-soft)]">
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
                    <Shield className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <p className="font-sans text-xl font-semibold tracking-tight text-[var(--ink)]">₹1.2L</p>
                    <p className="mt-0.5 text-[10px] font-medium text-gray-500">ITC at Risk</p>
                  </div>
                </div>
                <div className="landing-dash-stagger-4 flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-white p-3 shadow-[var(--shadow-soft)]">
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
                    <FileSearch className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <p className="font-sans text-xl font-semibold tracking-tight text-[var(--ink)]">2</p>
                    <p className="mt-0.5 text-[10px] font-medium text-gray-500">Ready for Review</p>
                  </div>
                </div>
                <div className="landing-dash-stagger-5 flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-white p-3 shadow-[var(--shadow-soft)]">
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
                    <Users className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <p className="font-sans text-xl font-semibold tracking-tight text-[var(--ink)]">28</p>
                    <p className="mt-0.5 text-[10px] font-medium text-gray-500">Total Clients</p>
                  </div>
                </div>
              </div>

              <div className="landing-dash-stagger-6 mt-3 rounded-[1.25rem] bg-white p-3.5 shadow-[var(--shadow-soft)]">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-[var(--ink)]">Needs attention</p>
                    <p className="text-[11px] text-gray-500">Priority clients to act on next</p>
                  </div>
                  <span className="rounded-full bg-[#F5F5F6] px-2.5 py-1 text-[10px] font-semibold text-gray-500">
                    View all
                  </span>
                </div>
                <ul className="space-y-1.5">
                  {ATTENTION_ROWS.map((row, index) => {
                    const active = index === activeRow;
                    return (
                      <li
                        key={row.name}
                        className={`flex items-center gap-2.5 rounded-2xl px-2.5 py-2 transition-colors duration-500 ${
                          active ? "bg-[#F0F0F0]" : "bg-[#F7F7F8]"
                        }`}
                      >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-[10px] font-semibold text-[var(--ink)] shadow-sm">
                          {row.initials}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--ink)]">
                          {row.name}
                        </span>
                        <span
                          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusClass(row.tone)}`}
                        >
                          {row.status}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Feature callouts */}
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">Product tour</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--ink)] sm:text-3xl">
          See your portfolio at a glance
        </h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-gray-600 sm:text-base">
          A soft, focused workspace for CA firms — stats, risk, and next actions in one place.
        </p>
        <ul className="mt-8 space-y-4">
          {FEATURES.map((feature) => (
            <li key={feature.title} className="flex gap-3">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-[var(--ink)] shadow-[var(--shadow-soft)]">
                <CheckCircle2 className="h-4 w-4" aria-hidden />
              </span>
              <div>
                <p className="text-sm font-semibold text-[var(--ink)]">{feature.title}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-gray-500">{feature.description}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
