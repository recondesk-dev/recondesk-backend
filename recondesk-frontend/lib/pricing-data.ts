export type BillingCycle = "monthly" | "yearly";

export type PricingTierId = "free" | "solo" | "firm" | "large_firm";

export type PricingPlan = {
  id: PricingTierId;
  name: string;
  badge?: string;
  badgeYearly?: string;
  /** Per-GSTIN chip shown on monthly toggle (derived, e.g. "₹36 / GSTIN / mo") */
  valueTagMonthly: string;
  /** Per-GSTIN chip shown on annual toggle (derived, e.g. "₹360/GSTIN/yr") */
  valueTagYearly: string;
  /** Ex-GST monthly price in rupees */
  priceMonthly: number;
  /** Ex-GST annual price in rupees */
  priceYearly: number;
  /** Annual price / 12, rounded – shown as "/mo" on the annual card */
  effectiveMonthlyPrice: number;
  /** Savings percent when choosing annual over monthly (0–100, integer) */
  savingsPercent: number;
  gstinCapacity: string;
  gstinLimit: number;
  blurb: string;
  cta: string;
  ctaHref?: string;
  featured?: boolean;
  isFree?: boolean;
  highlights: {
    header: string;
    benefit: string;
  }[];
};

// ─── Single source of truth for prices (ex-GST, rupees) ──────────────────────
const RAW: Record<
  PricingTierId,
  { monthly: number; yearly: number; gstinLimit: number } | null
> = {
  free: null, // free plan has no prices
  solo: { monthly: 899, yearly: 8999, gstinLimit: 25 },
  firm: { monthly: 1499, yearly: 14999, gstinLimit: 75 },
  large_firm: { monthly: 1899, yearly: 18999, gstinLimit: 150 },
};

// Helper: round a number to at most 0 decimal places
function roundInt(n: number): number {
  return Math.round(n);
}

// Helper: savings percent annual vs monthly annualised
function savingsPct(monthly: number, yearly: number): number {
  const annualisedMonthly = monthly * 12;
  return Math.round(((annualisedMonthly - yearly) / annualisedMonthly) * 100);
}

// Build derived per-GSTIN tags
function perGstinMonthly(monthly: number, gstinLimit: number): string {
  return `₹${roundInt(monthly / gstinLimit)} / GSTIN / mo`;
}
function perGstinYearly(yearly: number, gstinLimit: number): string {
  return `₹${roundInt(yearly / gstinLimit)}/GSTIN/yr`;
}

export const PRICING_PLANS: PricingPlan[] = [
  {
    id: "free",
    name: "Free Trial (60 Days)",
    priceMonthly: 0,
    priceYearly: 0,
    effectiveMonthlyPrice: 0,
    savingsPercent: 0,
    valueTagMonthly: "",
    valueTagYearly: "",
    gstinCapacity: "2 GSTINs",
    gstinLimit: 2,
    blurb: "Full-featured reconciliation suite to test 2 full monthly filing cycles. 100% free for 60 days.",
    cta: "Start 60-Day Free Trial",
    featured: false,
    isFree: true,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating — all 15+ matching & compliance tools included",
      },
      {
        header: "2 Client GSTINs",
        benefit: "Manage up to 2 active GSTINs with unlimited reconciliation runs",
      },
      {
        header: "60 Days Full Access",
        benefit: "2 full monthly filing cycles included — zero payment or card required",
      },
    ],
  },
  (() => {
    const r = RAW.solo!;
    const eff = roundInt(r.yearly / 12);
    const pct = savingsPct(r.monthly, r.yearly);
    return {
      id: "solo" as PricingTierId,
      name: "Solo",
      valueTagMonthly: perGstinMonthly(r.monthly, r.gstinLimit),
      valueTagYearly: perGstinYearly(r.yearly, r.gstinLimit),
      priceMonthly: r.monthly,
      priceYearly: r.yearly,
      effectiveMonthlyPrice: eff,
      savingsPercent: pct,
      gstinCapacity: "25 GSTINs",
      gstinLimit: r.gstinLimit,
      blurb: "Essential full-featured reconciliation suite for solo CAs & boutique practices.",
      cta: "Choose Solo",
      featured: false,
      highlights: [
        {
          header: "100% Full Desk Access",
          benefit: "Zero feature gating — all 15+ matching & compliance tools included",
        },
        {
          header: "Up to 25 Client GSTINs",
          benefit: "Manage up to 25 active GSTINs with unlimited reconciliation runs",
        },
        {
          header: "Billed Annually",
          benefit: `₹${r.monthly.toLocaleString("en-IN")}/mo or ₹${eff.toLocaleString("en-IN")}/mo billed annually (₹${r.yearly.toLocaleString("en-IN")}/yr)`,
        },
      ],
    };
  })(),
  (() => {
    const r = RAW.firm!;
    const eff = roundInt(r.yearly / 12);
    const pct = savingsPct(r.monthly, r.yearly);
    return {
      id: "firm" as PricingTierId,
      name: "Firm",
      badge: "Most Popular",
      badgeYearly: "Most Popular",
      valueTagMonthly: perGstinMonthly(r.monthly, r.gstinLimit),
      valueTagYearly: perGstinYearly(r.yearly, r.gstinLimit),
      priceMonthly: r.monthly,
      priceYearly: r.yearly,
      effectiveMonthlyPrice: eff,
      savingsPercent: pct,
      gstinCapacity: "75 GSTINs",
      gstinLimit: r.gstinLimit,
      blurb: "High-capacity suite for growing CA practices and multi-partner firms.",
      cta: "Choose Firm",
      featured: true,
      highlights: [
        {
          header: "100% Full Desk Access",
          benefit: "Zero feature gating — all 15+ matching & compliance tools included",
        },
        {
          header: "Up to 75 Client GSTINs",
          benefit: "Manage up to 75 active GSTINs with unlimited reconciliation runs",
        },
        {
          header: "Billed Annually",
          benefit: `₹${r.monthly.toLocaleString("en-IN")}/mo or ₹${eff.toLocaleString("en-IN")}/mo billed annually (₹${r.yearly.toLocaleString("en-IN")}/yr)`,
        },
        {
          header: "Multi-Staff Collaboration",
          benefit: "Team invites, client assignments, and complete audit trail",
        },
      ],
    };
  })(),
  (() => {
    const r = RAW.large_firm!;
    const eff = roundInt(r.yearly / 12);
    const pct = savingsPct(r.monthly, r.yearly);
    return {
      id: "large_firm" as PricingTierId,
      name: "Large Firm",
      valueTagMonthly: perGstinMonthly(r.monthly, r.gstinLimit),
      valueTagYearly: perGstinYearly(r.yearly, r.gstinLimit),
      priceMonthly: r.monthly,
      priceYearly: r.yearly,
      effectiveMonthlyPrice: eff,
      savingsPercent: pct,
      gstinCapacity: "150 GSTINs",
      gstinLimit: r.gstinLimit,
      blurb: "Comprehensive capacity for large CA firms and dedicated compliance teams.",
      cta: "Choose Large Firm",
      featured: false,
      highlights: [
        {
          header: "100% Full Desk Access",
          benefit: "Zero feature gating — all 15+ matching & compliance tools included",
        },
        {
          header: "Up to 150 Client GSTINs",
          benefit: "Best rate per GSTIN with unlimited reconciliation runs for all clients",
        },
        {
          header: "Billed Annually",
          benefit: `₹${r.monthly.toLocaleString("en-IN")}/mo or ₹${eff.toLocaleString("en-IN")}/mo billed annually (₹${r.yearly.toLocaleString("en-IN")}/yr)`,
        },
        {
          header: "Dedicated Support & ERP",
          benefit: "Priority support, onboarding training, and custom ERP integration",
        },
      ],
    };
  })(),
];

export function formatInr(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

/**
 * Returns { priceInr, gstinLimit, periodDays } for a canonical plan+cycle.
 * Used by create-order/route.ts to avoid a separate PLAN_CATALOG.
 */
export function getPlanCycleConfig(
  planId: string,
  cycle: "monthly" | "yearly"
): { priceInr: number; gstinLimit: number; periodDays: number } | null {
  const plan = PRICING_PLANS.find((p) => p.id === planId);
  if (!plan || plan.isFree) return null;
  return {
    priceInr: cycle === "monthly" ? plan.priceMonthly : plan.priceYearly,
    gstinLimit: plan.gstinLimit,
    periodDays: cycle === "monthly" ? 30 : 365,
  };
}
