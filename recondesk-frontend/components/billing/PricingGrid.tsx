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
        isGrowth ? "liquid-glass-card--featured ring-2 ring-[var(--ink)] shadow-lg scale-[1.02]" : ""
      } ${
        isCustom ? "border-slate-300/80 bg-gradient-to-b from-slate-50/90 to-white/70" : ""
      } flex h-full flex-col p-6 transition-all duration-300`}
    >
      <span className="liquid-glass-card__blob liquid-glass-card__blob--a" aria-hidden />
      <span className="liquid-glass-card__blob liquid-glass-card__blob--b" aria-hidden />

      <div className="liquid-glass-card__content flex h-full flex-col">
        {/* Header & Badge */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold tracking-tight text-[var(--ink)]">{plan.name}</h2>
            <p className="mt-1 text-xs text-gray-500 min-h-[36px] leading-relaxed">{plan.blurb}</p>
          </div>
          {isGrowth && (
            <span className="shrink-0 rounded-full bg-[var(--ink)] px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-white shadow-sm flex items-center gap-1">
              <svg className="w-3 h-3 fill-amber-400" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
              Most Popular
            </span>
          )}
          {isCustom && (
            <span className="shrink-0 rounded-full bg-slate-200/80 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
              Enterprise
            </span>
          )}
        </div>

        {/* Pricing & GSTIN Capacity framing */}
        <div className="mt-6 border-b border-gray-200/60 pb-6">
          <div className="flex items-baseline gap-1">
            <span className="text-4xl font-extrabold tracking-tight text-[var(--ink)] tabular-nums">
              {plan.priceDisplay}
            </span>
            {plan.periodLabel && (
              <span className="text-sm font-medium text-gray-500">{plan.periodLabel}</span>
            )}
          </div>

          <div className="mt-3 inline-flex">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold ${
                isGrowth
                  ? "bg-[var(--ink)] text-white ring-1 ring-black/20"
                  : isCustom
                  ? "bg-slate-900/10 text-slate-800 ring-1 ring-slate-900/20"
                  : "bg-slate-100 text-[var(--ink)] ring-1 ring-slate-200"
              }`}
            >
              <svg
                className="w-3.5 h-3.5"
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
          </div>

          <p className="mt-2 text-xs text-gray-500">
            {isCustom
              ? "Tailored agreement · Custom billing cycles"
              : "Excl. 18% GST · Unlimited runs in period"}
          </p>
        </div>

        {/* Features List */}
        <div className="mt-6 flex-1">
          {plan.featureSectionHeader && (
            <p className="mb-3 text-xs font-bold uppercase tracking-wider text-[var(--ink)] flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--ink)]" />
              {plan.featureSectionHeader}
            </p>
          )}

          <ul className="space-y-3 text-xs leading-relaxed text-gray-700">
            {plan.features.map((feat) => (
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

        {/* CTA Button */}
        <div className="mt-8 pt-4">
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
              {loadingPlan === plan.id ? "Opening checkout…" : plan.cta}
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
    </article>
  );
}
