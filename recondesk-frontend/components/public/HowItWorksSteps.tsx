"use client";

import { useEffect, useRef, useState } from "react";
import { ClipboardList, GitMerge, Upload } from "lucide-react";

const STEPS = [
  {
    key: "upload",
    title: "1. Upload",
    description: "GSTR-2B JSON + Purchase Register (Tally, Busy, or any Excel — auto-detected)",
    Icon: Upload,
  },
  {
    key: "match",
    title: "2. Match",
    description: "ReconDesk matches 5,000+ invoices using 5-level matching.",
    Icon: GitMerge,
  },
  {
    key: "decide",
    title: "3. Decide",
    description: "Every mismatch explained: What is wrong, Why it happened, What to do next",
    Icon: ClipboardList,
  },
] as const;

const RESULT_STATS = [
  {
    label: "Matched",
    value: "4,457",
    sub: "Clean matched",
    valueClass: "text-[var(--ink)]",
    dotClass: "bg-[var(--ink)]",
  },
  {
    label: "Review Required",
    value: "396",
    sub: "Needs verification",
    valueClass: "text-[var(--ink)]",
    dotClass: "bg-amber-500",
  },
  {
    label: "Missed ITC",
    value: "₹43.73L",
    sub: "Still recoverable",
    valueClass: "text-red-700",
    dotClass: "bg-red-500",
  },
  {
    label: "ITC at Risk",
    value: "₹14.93L",
    sub: "Compliance risk",
    valueClass: "text-amber-800",
    dotClass: "bg-amber-500",
  },
] as const;

const RESULT_TABS = [
  { label: "Matched", count: "4,457", active: true },
  { label: "Review Required", count: "396", active: false },
  { label: "Missed ITC", count: "147", active: false },
  { label: "ITC at Risk", count: "124", active: false },
] as const;

function ResultsPagePreview({ clear }: { clear: boolean }) {
  return (
    <div
      className={`how-works-results mx-auto mt-10 max-w-4xl transition-all duration-700 ease-out sm:mt-14 ${
        clear
          ? "translate-y-0 scale-100 opacity-100 blur-0"
          : "translate-y-2 scale-[0.985] opacity-[0.28] blur-[1.5px]"
      }`}
      aria-hidden
    >
      <div className="overflow-hidden rounded-[1.75rem] bg-white shadow-[var(--shadow-lift)] ring-1 ring-[#F0F0F0]">
        {/* Fake chrome */}
        <div className="flex items-center gap-2 border-b border-[#F0F0F0] px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#E5E5E5]" />
          <span className="ml-3 truncate rounded-full bg-[#F5F5F6] px-3 py-1 text-[11px] font-medium text-gray-400">
            app.recondesk.in / reconcile / results
          </span>
        </div>

        <div className="bg-[var(--bg)] p-4 sm:p-5">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="text-lg font-semibold tracking-tight text-[var(--ink)]">2026-03</p>
              <p className="mt-0.5 text-[11px] text-gray-500">Assigned to: Your team</p>
            </div>
            <span className="rounded-full bg-[#F5F5F6] px-3 py-1.5 text-[11px] font-semibold text-gray-600">
              Sample result
            </span>
          </div>

          {/* Result summary cards — mirrors real results page */}
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {RESULT_STATS.map((stat, i) => (
              <div
                key={stat.label}
                className={`rounded-[1.15rem] bg-white p-3.5 shadow-[var(--shadow-soft)] ${
                  clear ? "how-works-metric" : ""
                }`}
                style={clear ? { animationDelay: `${i * 0.08}s` } : undefined}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                    {stat.label}
                  </p>
                  <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${stat.dotClass}`} />
                </div>
                <p
                  className={`mt-2 font-sans text-xl font-semibold tracking-tight sm:text-2xl ${stat.valueClass}`}
                >
                  {stat.value}
                </p>
                <p className="mt-1 text-[11px] text-gray-500">{stat.sub}</p>
              </div>
            ))}
          </div>

          {/* Bucket tabs */}
          <div className="mt-4 flex gap-1.5 overflow-hidden">
            {RESULT_TABS.map((tab) => (
              <span
                key={tab.label}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold ${
                  tab.active
                    ? "bg-[var(--ink)] text-white"
                    : "bg-white text-gray-500 shadow-[var(--shadow-soft)]"
                }`}
              >
                {tab.label}
                <span className={tab.active ? "text-white/70" : "text-gray-400"}>{tab.count}</span>
              </span>
            ))}
          </div>

          {/* Mini table hint */}
          <div className="mt-3 overflow-hidden rounded-[1.15rem] bg-white shadow-[var(--shadow-soft)]">
            <div className="grid grid-cols-4 gap-2 border-b border-[#F0F0F0] px-3 py-2 text-[9px] font-semibold uppercase tracking-widest text-gray-400">
              <span>Supplier</span>
              <span>Invoice#</span>
              <span>Amount</span>
              <span>Status</span>
            </div>
            {[
              ["27AABCU…", "INV-2041", "₹23,644", "Matched"],
              ["33BWYCM…", "BILL-912", "₹8,290", "Matched"],
              ["19EYICC…", "PO-1743", "₹1.4L", "Matched"],
            ].map((row) => (
              <div
                key={row[1]}
                className="grid grid-cols-4 gap-2 border-b border-[#F7F7F8] px-3 py-2.5 text-[11px] last:border-0"
              >
                <span className="truncate font-mono text-gray-500">{row[0]}</span>
                <span className="truncate font-medium text-[var(--ink)]">{row[1]}</span>
                <span className="tabular-nums text-gray-700">{row[2]}</span>
                <span className="text-emerald-700">{row[3]}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <p
        className={`mt-3 text-center text-xs transition-opacity duration-500 ${
          clear ? "text-gray-500 opacity-100" : "text-gray-400 opacity-60"
        }`}
      >
        {clear
          ? "Decide with a clear results view — matched, review, missed ITC, and risk."
          : "Results stay soft until matching finishes…"}
      </p>
    </div>
  );
}

export function HowItWorksSteps() {
  const rootRef = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  const [activeStep, setActiveStep] = useState(0);
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduceMotion(mq.matches);
    const onChange = () => setReduceMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setInView(true);
      },
      { threshold: 0.35 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!inView || reduceMotion) return;
    const id = window.setInterval(() => {
      setActiveStep((prev) => (prev + 1) % STEPS.length);
    }, 2400);
    return () => window.clearInterval(id);
  }, [inView, reduceMotion]);

  const progress = reduceMotion || !inView ? 1 : activeStep / (STEPS.length - 1);
  const resultsClear = reduceMotion || !inView || activeStep === STEPS.length - 1;

  return (
    <div ref={rootRef} className={inView ? "how-works-inview" : ""}>
      <h2 className="how-works-title text-center text-2xl font-semibold text-[var(--ink)] sm:text-3xl">
        How ReconDesk Works
      </h2>

      <div className="relative mt-12">
        <div
          className="pointer-events-none absolute left-[16.666%] right-[16.666%] top-[28px] hidden h-[2px] bg-[#E8E8EA] md:block"
          aria-hidden
        >
          <div
            className="how-works-progress h-full origin-left rounded-full bg-[var(--ink)] transition-transform duration-700 ease-out"
            style={{ transform: `scaleX(${Math.max(progress, 0.02)})` }}
          />
        </div>

        <ol className="grid gap-8 md:grid-cols-3">
          {STEPS.map((step, index) => {
            const Icon = step.Icon;
            const active = reduceMotion || activeStep === index;
            const done = reduceMotion || activeStep > index;
            return (
              <li
                key={step.key}
                className={`how-works-step relative flex flex-col items-center text-center transition-all duration-500 ${
                  inView ? "how-works-step-visible" : "opacity-0 translate-y-3"
                }`}
                style={{ transitionDelay: inView ? `${index * 120}ms` : "0ms" }}
              >
                <button
                  type="button"
                  onClick={() => setActiveStep(index)}
                  className={`relative z-[1] flex h-14 w-14 items-center justify-center rounded-2xl transition-all duration-500 ${
                    active
                      ? "scale-110 bg-[var(--ink)] text-white shadow-[var(--shadow-lift)]"
                      : done
                        ? "bg-white text-[var(--ink)] shadow-[var(--shadow-soft)] ring-2 ring-[var(--ink)]/10"
                        : "bg-white text-gray-400 shadow-[var(--shadow-soft)]"
                  }`}
                  aria-current={active ? "step" : undefined}
                  aria-label={step.title}
                >
                  <Icon
                    className={`h-7 w-7 transition-transform duration-500 ${
                      active && !reduceMotion ? "how-works-icon-bounce" : ""
                    }`}
                    aria-hidden
                  />
                  {active && !reduceMotion ? (
                    <span className="how-works-ring absolute inset-0 rounded-2xl" aria-hidden />
                  ) : null}
                </button>
                <h3
                  className={`mt-4 text-base font-semibold transition-colors duration-300 ${
                    active ? "text-[var(--ink)]" : "text-gray-500"
                  }`}
                >
                  {step.title}
                </h3>
                <p
                  className={`mt-2 max-w-xs text-sm leading-relaxed transition-colors duration-300 ${
                    active ? "text-gray-600" : "text-gray-400"
                  }`}
                >
                  {step.description}
                </p>
              </li>
            );
          })}
        </ol>
      </div>

      <ResultsPagePreview clear={resultsClear} />
    </div>
  );
}
