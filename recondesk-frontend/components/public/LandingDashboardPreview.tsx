"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileSearch,
  GitMerge,
  Shield,
  Users,
} from "lucide-react";

type ScreenId = "dashboard" | "results" | "decisions";

const SCREENS: {
  id: ScreenId;
  path: string;
  title: string;
  description: string;
  featureIndex: number;
}[] = [
  {
    id: "dashboard",
    path: "dashboard",
    title: "See your portfolio at a glance",
    description: "Stats, risk, and next actions for every client — in one soft workspace.",
    featureIndex: 2,
  },
  {
    id: "results",
    path: "reconcile / results",
    title: "Know the ITC at risk instantly",
    description: "Matched vs mismatch totals with rupee impact, ready for review.",
    featureIndex: 1,
  },
  {
    id: "decisions",
    path: "reconcile / decide",
    title: "Decide what to do next",
    description: "Each mismatch explained — what’s wrong, why, and the next step.",
    featureIndex: 3,
  },
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

const ATTENTION_ROWS = [
  { initials: "AK", name: "Aarav Textiles", status: "Pending", tone: "amber" as const },
  { initials: "PS", name: "Priya Softwares", status: "In progress", tone: "ink" as const },
  { initials: "NM", name: "Nova Metals", status: "Ready", tone: "emerald" as const },
  { initials: "RL", name: "Ravi Logistics", status: "Failed", tone: "rose" as const },
];

const DECISIONS = [
  {
    invoice: "INV-2041",
    what: "Taxable value mismatch",
    why: "GSTR-2B and books differ by ₹2,480",
    next: "Ask supplier to amend GSTR-1",
  },
  {
    invoice: "INV-1188",
    what: "Missing in GSTR-2B",
    why: "Invoice present in books only",
    next: "Hold ITC until reflected",
  },
  {
    invoice: "INV-3310",
    what: "Section 17(5) likely",
    why: "Expense category may block credit",
    next: "Flag as blocked credit",
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

function Shell({
  path,
  activeNav,
  children,
}: {
  path: string;
  activeNav: number;
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-[1.75rem] bg-white shadow-[var(--shadow-lift)]">
      <div className="flex items-center gap-2 border-b border-[#F0F0F0] px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
        <span className="ml-3 truncate rounded-full bg-[#F5F5F6] px-3 py-1 text-[11px] font-medium text-gray-400">
          app.recondesk.in / {path}
        </span>
      </div>
      <div className="flex">
        <aside className="hidden w-[72px] shrink-0 border-r border-[#F0F0F0] bg-[#FAFAFB] p-3 sm:block">
          <div className="mb-4 h-8 w-8 rounded-full bg-[var(--ink)]" />
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className={`h-8 rounded-full transition-colors duration-500 ${
                  i === activeNav ? "bg-[var(--ink)]" : "bg-[#EFEFEF]"
                }`}
              />
            ))}
          </div>
        </aside>
        <div className="min-w-0 flex-1 bg-[var(--bg)] p-4 sm:p-5">{children}</div>
      </div>
    </div>
  );
}

function DashboardScreen({ activeRow }: { activeRow: number }) {
  return (
    <>
      <div>
        <p className="text-sm font-semibold tracking-tight text-[var(--ink)]">Quick Stats</p>
        <p className="mt-0.5 text-[11px] text-gray-500">Portfolio snapshot for this return period</p>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-[var(--ink)] p-3 text-white shadow-[var(--shadow-soft)]">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-white/15">
            <AlertTriangle className="h-3.5 w-3.5" />
          </span>
          <div>
            <p className="landing-dash-pulse font-sans text-xl font-semibold tracking-tight">4</p>
            <p className="mt-0.5 text-[10px] font-medium text-white/65">Needs Attention</p>
          </div>
        </div>
        <div className="flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-white p-3 shadow-[var(--shadow-soft)]">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
            <Shield className="h-3.5 w-3.5" />
          </span>
          <div>
            <p className="font-sans text-xl font-semibold tracking-tight text-[var(--ink)]">₹1.2L</p>
            <p className="mt-0.5 text-[10px] font-medium text-gray-500">ITC at Risk</p>
          </div>
        </div>
        <div className="flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-white p-3 shadow-[var(--shadow-soft)]">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
            <FileSearch className="h-3.5 w-3.5" />
          </span>
          <div>
            <p className="font-sans text-xl font-semibold tracking-tight text-[var(--ink)]">2</p>
            <p className="mt-0.5 text-[10px] font-medium text-gray-500">Ready for Review</p>
          </div>
        </div>
        <div className="flex min-h-[96px] flex-col justify-between rounded-[1.15rem] bg-white p-3 shadow-[var(--shadow-soft)]">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
            <Users className="h-3.5 w-3.5" />
          </span>
          <div>
            <p className="font-sans text-xl font-semibold tracking-tight text-[var(--ink)]">28</p>
            <p className="mt-0.5 text-[10px] font-medium text-gray-500">Total Clients</p>
          </div>
        </div>
      </div>
      <div className="mt-3 rounded-[1.25rem] bg-white p-3.5 shadow-[var(--shadow-soft)]">
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
          {ATTENTION_ROWS.map((row, index) => (
            <li
              key={row.name}
              className={`flex items-center gap-2.5 rounded-2xl px-2.5 py-2 transition-colors duration-500 ${
                index === activeRow ? "bg-[#F0F0F0]" : "bg-[#F7F7F8]"
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
          ))}
        </ul>
      </div>
    </>
  );
}

function ResultsScreen() {
  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold tracking-tight text-[var(--ink)]">Run summary</p>
          <p className="mt-0.5 text-[11px] text-gray-500">Aarav Textiles · Apr 2026</p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-emerald-700">
          <GitMerge className="h-3 w-3" />
          5-level match
        </span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {[
          { label: "Matched", value: "847", sub: "invoices", tone: "text-emerald-600" },
          { label: "Mismatches", value: "23", sub: "to review", tone: "text-[var(--ink)]" },
          { label: "ITC at Risk", value: "₹1.2L", sub: "this run", tone: "text-amber-600" },
        ].map((card) => (
          <div
            key={card.label}
            className="rounded-[1.15rem] bg-white p-3 text-center shadow-[var(--shadow-soft)]"
          >
            <p className="text-[10px] font-medium text-gray-500">{card.label}</p>
            <p className={`mt-1 font-sans text-lg font-semibold tracking-tight ${card.tone}`}>
              {card.value}
            </p>
            <p className="mt-0.5 text-[10px] text-gray-400">{card.sub}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 rounded-[1.25rem] bg-white p-3.5 shadow-[var(--shadow-soft)]">
        <p className="text-xs font-semibold text-[var(--ink)]">Match breakdown</p>
        <div className="mt-3 space-y-2.5">
          {[
            { label: "L1 Exact", pct: 72 },
            { label: "L2–L3 Probable", pct: 18 },
            { label: "Unmatched", pct: 10 },
          ].map((row) => (
            <div key={row.label}>
              <div className="mb-1 flex justify-between text-[11px]">
                <span className="text-gray-600">{row.label}</span>
                <span className="font-medium text-[var(--ink)]">{row.pct}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[#F0F0F0]">
                <div
                  className="landing-dash-bar h-full rounded-full bg-[var(--ink)]"
                  style={{ width: `${row.pct}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="mt-3 rounded-[1.15rem] bg-[var(--ink)] px-4 py-3 text-white shadow-[var(--shadow-soft)]">
        <p className="text-[11px] font-medium text-white/65">Recoverable this month</p>
        <p className="landing-dash-pulse mt-0.5 font-sans text-xl font-semibold tracking-tight">
          ₹1,24,500
        </p>
      </div>
    </>
  );
}

function DecisionsScreen({ activeDecision }: { activeDecision: number }) {
  return (
    <>
      <div>
        <p className="text-sm font-semibold tracking-tight text-[var(--ink)]">Decide</p>
        <p className="mt-0.5 text-[11px] text-gray-500">What is wrong · Why · What to do next</p>
      </div>
      <div className="mt-3 space-y-2">
        {DECISIONS.map((item, index) => {
          const active = index === activeDecision;
          return (
            <div
              key={item.invoice}
              className={`rounded-[1.15rem] bg-white p-3 shadow-[var(--shadow-soft)] transition-all duration-500 ${
                active ? "ring-2 ring-[var(--ink)]/15 shadow-[var(--shadow-lift)]" : "opacity-70"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold tracking-tight text-[var(--ink)]">
                  {item.invoice}
                </p>
                <span className="rounded-full bg-[#F5F5F6] px-2 py-0.5 text-[10px] font-semibold text-gray-600">
                  Mismatch
                </span>
              </div>
              {active ? (
                <div className="mt-2 grid gap-1.5 sm:grid-cols-3">
                  <div className="rounded-lg bg-[#F7F7F8] px-2.5 py-1.5">
                    <p className="text-[9px] font-semibold uppercase tracking-widest text-gray-400">What</p>
                    <p className="mt-0.5 text-[11px] font-medium leading-snug text-gray-700">{item.what}</p>
                  </div>
                  <div className="rounded-lg bg-[#F7F7F8] px-2.5 py-1.5">
                    <p className="text-[9px] font-semibold uppercase tracking-widest text-gray-400">Why</p>
                    <p className="mt-0.5 text-[11px] leading-snug text-gray-500">{item.why}</p>
                  </div>
                  <div className="rounded-lg bg-[#F7F7F8] px-2.5 py-1.5">
                    <p className="text-[9px] font-semibold uppercase tracking-widest text-gray-400">Next</p>
                    <p className="mt-0.5 text-[11px] font-medium leading-snug text-[var(--ink)]">{item.next}</p>
                  </div>
                </div>
              ) : (
                <p className="mt-1.5 truncate text-[11px] text-gray-500">{item.what}</p>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

export function LandingDashboardPreview() {
  const [screenIndex, setScreenIndex] = useState(0);
  const [activeRow, setActiveRow] = useState(0);
  const [activeDecision, setActiveDecision] = useState(0);
  const [reduceMotion, setReduceMotion] = useState(false);

  const screen = SCREENS[screenIndex];

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduceMotion(mq.matches);
    const onChange = () => setReduceMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (reduceMotion) return;
    const id = window.setInterval(() => {
      setScreenIndex((prev) => (prev + 1) % SCREENS.length);
    }, 4200);
    return () => window.clearInterval(id);
  }, [reduceMotion]);

  useEffect(() => {
    if (reduceMotion || screen.id !== "dashboard") return;
    const id = window.setInterval(() => {
      setActiveRow((prev) => (prev + 1) % ATTENTION_ROWS.length);
    }, 1400);
    return () => window.clearInterval(id);
  }, [reduceMotion, screen.id]);

  useEffect(() => {
    if (reduceMotion || screen.id !== "decisions") return;
    const id = window.setInterval(() => {
      setActiveDecision((prev) => (prev + 1) % DECISIONS.length);
    }, 1400);
    return () => window.clearInterval(id);
  }, [reduceMotion, screen.id]);

  return (
    <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-12">
      <div className="landing-dash-enter relative mx-auto w-full max-w-lg lg:max-w-none" aria-hidden>
        <div key={screen.id} className="landing-dash-screen">
          <Shell
            path={screen.path}
            activeNav={screen.id === "dashboard" ? 0 : screen.id === "results" ? 1 : 2}
          >
            {screen.id === "dashboard" ? (
              <DashboardScreen activeRow={activeRow} />
            ) : screen.id === "results" ? (
              <ResultsScreen />
            ) : (
              <DecisionsScreen activeDecision={activeDecision} />
            )}
          </Shell>
        </div>

        <div className="mt-4 flex items-center justify-center gap-2">
          {SCREENS.map((s, i) => (
            <button
              key={s.id}
              type="button"
              aria-label={`Show ${s.title}`}
              onClick={() => setScreenIndex(i)}
              className={`h-2 rounded-full transition-all duration-300 ${
                i === screenIndex ? "w-6 bg-[var(--ink)]" : "w-2 bg-[#D4D4D4] hover:bg-[#BDBDBD]"
              }`}
            />
          ))}
        </div>
      </div>

      <div>
        <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">Product tour</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--ink)] sm:text-3xl">
          {screen.title}
        </h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-gray-600 sm:text-base">
          {screen.description}
        </p>
        <ul className="mt-8 space-y-3">
          {FEATURES.map((feature, index) => {
            const active = index === screen.featureIndex;
            return (
              <li key={feature.title}>
                <button
                  type="button"
                  onClick={() => {
                    const target = SCREENS.findIndex((s) => s.featureIndex === index);
                    if (target >= 0) setScreenIndex(target);
                    else if (index === 0) setScreenIndex(1);
                  }}
                  className={`flex w-full gap-3 rounded-[1.15rem] px-3 py-3 text-left transition-all duration-300 ${
                    active
                      ? "bg-white shadow-[var(--shadow-soft)]"
                      : "hover:bg-white/60"
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors ${
                      active
                        ? "bg-[var(--ink)] text-white"
                        : "bg-white text-[var(--ink)] shadow-[var(--shadow-soft)]"
                    }`}
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-[var(--ink)]">{feature.title}</p>
                    <p className="mt-0.5 text-sm leading-relaxed text-gray-500">{feature.description}</p>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
