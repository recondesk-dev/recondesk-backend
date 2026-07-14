"use client";

import { useEffect, useRef, useState } from "react";
import { ClipboardList, GitMerge, Upload } from "lucide-react";

import { formatInrFull } from "@/lib/format";

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

function InrFromFormat({ value }: { value: number }) {
  const formatted = formatInrFull(value);
  return (
    <span>
      <span className="font-sans">{formatted.charAt(0)}</span>
      <span className="font-mono">{formatted.slice(1)}</span>
    </span>
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
    }, 2200);
    return () => window.clearInterval(id);
  }, [inView, reduceMotion]);

  const progress = reduceMotion || !inView ? 1 : activeStep / (STEPS.length - 1);
  const showSummary = reduceMotion || !inView || activeStep === STEPS.length - 1;

  return (
    <div ref={rootRef} className={inView ? "how-works-inview" : ""}>
      <h2 className="how-works-title text-center text-2xl font-semibold text-[var(--ink)] sm:text-3xl">
        How ReconDesk Works
      </h2>

      <div className="relative mt-12">
        {/* Connector line (desktop) */}
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

      {/* Sample run summary */}
      <div
        className={`landing-card mx-auto mt-10 max-w-lg rounded-[1.5rem] bg-white p-5 text-center transition-all duration-500 sm:mt-14 sm:p-6 ${
          showSummary
            ? "translate-y-0 opacity-100"
            : "pointer-events-none translate-y-3 opacity-40"
        }`}
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Sample run summary</p>
        <div className="mt-4 grid grid-cols-3 gap-3 sm:flex sm:flex-wrap sm:items-start sm:justify-center sm:gap-12">
          <div className={showSummary && !reduceMotion ? "how-works-metric" : ""}>
            <p className="text-xs text-gray-500">ITC at Risk</p>
            <p className="mt-1 text-lg font-semibold text-amber-600">
              <InrFromFormat value={124500} />
            </p>
          </div>
          <div
            className={showSummary && !reduceMotion ? "how-works-metric" : ""}
            style={{ animationDelay: "0.1s" }}
          >
            <p className="text-xs text-gray-500">Matched</p>
            <p className="mt-1 font-mono text-lg font-semibold text-emerald-600">847</p>
            <p className="text-[10px] text-gray-400">invoices</p>
          </div>
          <div
            className={showSummary && !reduceMotion ? "how-works-metric" : ""}
            style={{ animationDelay: "0.2s" }}
          >
            <p className="text-xs text-gray-500">Mismatches</p>
            <p className="mt-1 font-mono text-lg font-semibold text-[var(--ink)]">23</p>
          </div>
        </div>
      </div>
    </div>
  );
}
