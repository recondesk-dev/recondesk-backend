"use client";

import Link from "next/link";
import { PRICING_PLANS, type PricingPlan } from "@/lib/pricing-data";

type PricingGridProps = {
  onSelectPlan?: (planId: "monthly" | "starter" | "growth") => void;
  loadingPlan?: string | null;
  isDashboard?: boolean;
};

export function PricingGrid({ onSelectPlan, loadingPlan, isDashboard = false }: PricingGridProps) {
  return (
    <div className="space-y-8">
      {/* 4 Pricing Cards */}
      <div className="mx-auto mt-8 grid max-w-7xl gap-6 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
        {PRICING_PLANS.map((plan) => (
          <PricingCard
            key={plan.id}
            plan={plan}
            onSelectPlan={onSelectPlan}
            loadingPlan={loadingPlan}
            isDashboard={isDashboard}
          />
        ))}
      </div>

      {/* Shared "Included in ALL Plans" Bar */}
      <div className="mx-auto max-w-7xl rounded-2xl border border-slate-200/80 bg-white/70 p-5 shadow-sm backdrop-blur-md">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-200/60 pb-3 mb-4">
          <div className="flex items-center gap-2">
            <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-500 ring-4 ring-emerald-100" />
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--ink)]">
              Included in 100% of Plans — Zero Feature Gating
            </span>
          </div>
          <span className="text-xs text-gray-500 font-medium">
            Every tier gets the complete ReconDesk matching engine & compliance suite
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs text-gray-700">
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Smart 2B Reconciliation</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Decision Layer AI</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">GSTR-3B & 1A Tie-outs</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">E-Invoice & IRN Lookup</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">IMS Direct Writeback</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Live Tally Bridge Sync</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Multi-Period Audit (9C)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Rule 37 & 17(5) Reversals</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function PricingCard({
  plan,
  onSelectPlan,
  loadingPlan,
  isDashboard,
}: {
  plan: PricingPlan;
  onSelectPlan?: (planId: "monthly" | "starter" | "growth") => void;
  loadingPlan?: string | null;
  isDashboard?: boolean;
}) {
  const isGrowth = plan.id === "growth";
  const isCustom = plan.id === "custom";

  return (
    <article
      className={`liquid-glass-card ${
        isGrowth ? "liquid-glass-card--featured ring-2 ring-[var(--ink)] shadow-xl scale-[1.02]" : ""
      } ${
        isCustom ? "border-slate-300/80 bg-gradient-to-b from-slate-50/90 to-white/70" : ""
      } flex h-full flex-col p-6 transition-all duration-300`}
    >
      <span className="liquid-glass-card__blob liquid-glass-card__blob--a" aria-hidden />
      <span className="liquid-glass-card__blob liquid-glass-card__blob--b" aria-hidden />

      <div className="liquid-glass-card__content flex h-full flex-col">
        {/* Header & Badge */}
        <div className="flex items-center justify-between gap-2 min-h-[28px]">
          <h2 className="text-xl font-bold tracking-tight text-[var(--ink)]">{plan.name}</h2>
          {plan.badge && (
            <span
              className={`shrink-0 rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-wider shadow-sm flex items-center gap-1 ${
                isGrowth
                  ? "bg-[var(--ink)] text-white"
                  : isCustom
                  ? "bg-slate-200/90 text-slate-800"
                  : plan.id === "starter"
                  ? "bg-amber-100 text-amber-900 border border-amber-200"
                  : "bg-slate-100 text-slate-700"
              }`}
            >
              {isGrowth && (
                <svg className="w-3 h-3 fill-amber-400" viewBox="0 0 20 20">
                  <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                </svg>
              )}
              {plan.badge}
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-gray-500 min-h-[36px] leading-relaxed">{plan.blurb}</p>

        {/* Pricing & GSTIN Capacity framing */}
        <div className="mt-5 border-b border-gray-200/60 pb-5">
          <div className="flex items-baseline gap-1">
            <span className="text-4xl font-extrabold tracking-tight text-[var(--ink)] tabular-nums">
              {plan.priceDisplay}
            </span>
            {plan.periodLabel && (
              <span className="text-sm font-medium text-gray-500">{plan.periodLabel}</span>
            )}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-[var(--ink)] ring-1 ring-slate-200">
              <svg
                className="w-3.5 h-3.5 text-gray-500"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5m0 0h4m-4 0V11m0 0T9.5 9.5M12 11t2.5-1.5"
                />
              </svg>
              {plan.gstinCapacity}
            </span>
            {plan.valueTag && (
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                  isGrowth
                    ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                    : plan.id === "starter"
                    ? "bg-indigo-50 text-indigo-700 border border-indigo-100"
                    : "bg-slate-100 text-slate-600"
                }`}
              >
                {plan.valueTag}
              </span>
            )}
          </div>

          <p className="mt-2 text-xs text-gray-500">
            {isCustom
              ? "Tailored agreement · Custom billing cycles"
              : "Excl. 18% GST · Unlimited runs in period"}
          </p>

          {/* Primary Call to Action Button */}
          <div className="mt-4">
            {isCustom ? (
              <a
                href={plan.ctaHref || "mailto:contact@recondesk.in?subject=Custom%20Enterprise%20Plan%20Enquiry"}
                className="inline-flex w-full min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 py-2.5 text-sm font-semibold text-white shadow-md transition-opacity hover:opacity-90"
              >
                {plan.cta} →
              </a>
            ) : isDashboard && onSelectPlan ? (
              <button
                type="button"
                disabled={loadingPlan !== null}
                onClick={() => onSelectPlan(plan.id as "monthly" | "starter" | "growth")}
                className="inline-flex w-full min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 py-2.5 text-sm font-semibold text-white shadow-md transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loadingPlan === plan.id ? "Opening checkout…" : `${plan.cta} →`}
              </button>
            ) : (
              <Link
                href={`/auth/signup?plan=${plan.id}`}
                className="inline-flex w-full min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 py-2.5 text-sm font-semibold text-white shadow-md transition-all hover:opacity-90"
              >
                {plan.cta} →
              </Link>
            )}
          </div>
        </div>

        {/* Highlights Section */}
        <div className="mt-5 flex-1">
          <p className="mb-3 text-xs font-bold uppercase tracking-wider text-[var(--ink)] flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--ink)]" />
            Plan Highlights
          </p>

          <ul className="space-y-3 text-xs leading-relaxed text-gray-700">
            {plan.highlights.map((feat) => (
              <li key={feat.header} className="flex items-start gap-2.5">
                <span className="mt-0.5 shrink-0 rounded-full bg-emerald-100 p-0.5 text-emerald-700">
                  <svg
                    className="h-3 w-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </span>
                <div>
                  <span className="font-semibold text-[var(--ink)] block">{feat.header}</span>
                  <span className="text-gray-500 leading-normal block mt-0.5">{feat.benefit}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </article>
  );
}
