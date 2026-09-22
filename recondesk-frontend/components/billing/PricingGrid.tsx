"use client";

import Link from "next/link";
import { Fragment, useState, type ReactNode } from "react";
import {
  PRICING_PLANS,
  formatInr,
  type BillingCycle,
  type PricingPlan,
  type PricingTierId,
} from "@/lib/pricing-data";

function formatRupeeText(text: string | undefined): ReactNode {
  if (!text) return text;
  if (!text.includes("₹")) return text;
  const parts = text.split("₹");
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span style={{ fontFamily: "Arial, system-ui, -apple-system, sans-serif", fontWeight: "inherit" }}>
              ₹
            </span>
          )}
          {part}
        </Fragment>
      ))}
    </>
  );
}

type PricingGridProps = {
  onSelectPlan?: (planId: PricingTierId, cycle: BillingCycle) => void;
  loadingPlan?: string | null;
  isDashboard?: boolean;
  connectedGstins?: number;
};

export function PricingGrid({
  onSelectPlan,
  loadingPlan,
  isDashboard = false,
}: PricingGridProps) {
  // Annual is the default/hero toggle
  const [cycle, setCycle] = useState<BillingCycle>("yearly");

  return (
    <div className="space-y-8">
      {/* Monthly / Annual Billing Toggle Switch */}
      <div className="flex flex-col items-center justify-center gap-3 pt-2">
        <div className="inline-flex items-center rounded-full bg-slate-100 p-1.5 shadow-inner ring-1 ring-slate-200">
          <button
            type="button"
            onClick={() => setCycle("monthly")}
            className={`relative rounded-full px-5 py-2 text-sm font-semibold transition-all duration-200 ${
              cycle === "monthly"
                ? "bg-white text-[var(--ink)] shadow-md"
                : "text-gray-600 hover:text-[var(--ink)]"
            }`}
          >
            Monthly
          </button>
          <button
            type="button"
            onClick={() => setCycle("yearly")}
            className={`relative flex items-center gap-2 rounded-full px-5 py-2 text-sm font-semibold transition-all duration-200 ${
              cycle === "yearly"
                ? "bg-[var(--ink)] text-white shadow-md"
                : "text-gray-600 hover:text-[var(--ink)]"
            }`}
          >
            <span>Annual</span>
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ${
                cycle === "yearly"
                  ? "bg-emerald-500 text-white"
                  : "bg-emerald-100 text-emerald-800"
              }`}
            >
              Up to 6 mos free
            </span>
          </button>
        </div>
        <p className="text-xs text-gray-500">
          {cycle === "yearly"
            ? "Annual subscription — lowest effective rate per client GSTIN"
            : "Flexible month-to-month access with zero lock-in"}
        </p>
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
            <span className="font-semibold text-slate-800">IMS Recommendations</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Rule 37 & 17(5) Engine</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">RCM Reconciliation</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Audit Observations</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Supplier Scorecard</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">GSTR-1 & 3B Filing</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded-full bg-emerald-100 p-1 text-emerald-700">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-semibold text-slate-800">Live Tally Bridge</span>
          </div>
        </div>
      </div>

      {/* 4 Pricing Cards: Free, Solo, Firm (Most Popular), Large Firm */}
      <div className="mx-auto grid max-w-7xl gap-6 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
        {PRICING_PLANS.map((plan) => (
          <PricingCard
            key={plan.id}
            plan={plan}
            cycle={cycle}
            onSelectPlan={onSelectPlan}
            loadingPlan={loadingPlan}
            isDashboard={isDashboard}
          />
        ))}
      </div>
    </div>
  );
}

function PricingCard({
  plan,
  cycle,
  onSelectPlan,
  loadingPlan,
  isDashboard,
}: {
  plan: PricingPlan;
  cycle: BillingCycle;
  onSelectPlan?: (planId: PricingTierId, cycle: BillingCycle) => void;
  loadingPlan?: string | null;
  isDashboard?: boolean;
}) {
  const isFirm = plan.id === "firm";
  const isYearly = cycle === "yearly";

  const rawPrice = isYearly ? plan.priceYearly : plan.priceMonthly;
  const periodLabel = plan.isFree ? "" : isYearly ? "/year" : "/month";

  // Badge logic
  const displayedBadge = isYearly ? (plan.badgeYearly || plan.badge) : plan.badge;
  const displayedValueTag = isYearly ? plan.valueTagYearly : plan.valueTagMonthly;
  const displayPriceText = formatInr(rawPrice);

  return (
    <article
      className={`liquid-glass-card ${
        isFirm ? "liquid-glass-card--featured ring-2 ring-[var(--ink)] shadow-xl scale-[1.02]" : ""
      } flex h-full flex-col p-6 transition-all duration-300`}
    >
      <span className="liquid-glass-card__blob liquid-glass-card__blob--a" aria-hidden />
      <span className="liquid-glass-card__blob liquid-glass-card__blob--b" aria-hidden />

      <div className="liquid-glass-card__content flex h-full flex-col">
        {/* Header & Badge */}
        <div className="flex items-center justify-between gap-2 min-h-[28px]">
          <h2 className="text-xl font-bold tracking-tight text-[var(--ink)]">{plan.name}</h2>
          {displayedBadge && (
            <span
              className={`shrink-0 rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-wider shadow-sm flex items-center gap-1 ${
                isFirm
                  ? "bg-[var(--ink)] text-white"
                  : "bg-slate-100 text-slate-700"
              }`}
            >
              {isFirm && (
                <svg className="w-3 h-3 fill-amber-400" viewBox="0 0 20 20">
                  <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                </svg>
              )}
              {displayedBadge}
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-gray-500 min-h-[36px] leading-relaxed">{plan.blurb}</p>

        {/* Pricing & GSTIN Capacity framing */}
        <div className="mt-5 border-b border-gray-200/60 pb-5">
          <div className="flex items-baseline gap-1">
            <span className="text-4xl font-extrabold tracking-tight text-[var(--ink)] tabular-nums">
              {formatRupeeText(displayPriceText)}
            </span>
            {periodLabel && (
              <span className="text-sm font-medium text-gray-500">{periodLabel}</span>
            )}
          </div>

          {/* Annual Savings Messaging */}
          {isYearly && plan.annualSavingsText && (
            <div className="mt-2.5 rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-200/70 flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 shrink-0 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              <span>{formatRupeeText(plan.annualSavingsText)}</span>
            </div>
          )}

          {/* GSTIN Capacity & Per-GSTIN Rate display */}
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
            {displayedValueTag && (
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                  isFirm
                    ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                    : plan.id === "solo"
                    ? "bg-indigo-50 text-indigo-700 border border-indigo-100"
                    : "bg-slate-100 text-slate-600"
                }`}
              >
                {formatRupeeText(displayedValueTag)}
              </span>
            )}
          </div>

          {/* Tax notice & Unlimited runs */}
          <p className="mt-2 text-xs font-semibold text-slate-600">
            {plan.isFree ? "100% Free · Unlimited runs" : "+18% GST · Unlimited runs in period"}
          </p>

          {/* Primary Call to Action Button */}
          <div className="mt-4">
            {isDashboard && onSelectPlan ? (
              plan.isFree ? (
                <button
                  type="button"
                  disabled
                  className="inline-flex w-full min-h-[44px] items-center justify-center rounded-full bg-slate-200 px-6 py-2.5 text-sm font-semibold text-slate-600 cursor-default"
                >
                  Free Tier (2 GSTINs)
                </button>
              ) : (
                <button
                  type="button"
                  disabled={loadingPlan !== null}
                  onClick={() => onSelectPlan(plan.id, cycle)}
                  className="inline-flex w-full min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 py-2.5 text-sm font-semibold text-white shadow-md transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loadingPlan === plan.id ? "Opening checkout…" : `${plan.cta} →`}
                </button>
              )
            ) : (
              <Link
                href={`/auth/signup?plan=${plan.id}${plan.isFree ? "" : `&cycle=${cycle}`}`}
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
                  <span className="font-semibold text-[var(--ink)] block">{formatRupeeText(feat.header)}</span>
                  <span className="text-gray-500 leading-normal block mt-0.5">{formatRupeeText(feat.benefit)}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </article>
  );
}
