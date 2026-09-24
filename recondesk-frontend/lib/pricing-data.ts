export type BillingCycle = "monthly" | "yearly";

export type PricingTierId = "free" | "solo" | "firm" | "large_firm";

export type PricingPlan = {
  id: PricingTierId;
  name: string;
  badge?: string;
  badgeYearly?: string;
  valueTagMonthly?: string;
  valueTagYearly?: string;
  priceMonthly: number;
  priceYearly: number;
  effectiveMonthlyPrice: number;
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

export const PRICING_PLANS: PricingPlan[] = [
  {
    id: "free",
    name: "Free",
    priceMonthly: 0,
    priceYearly: 0,
    effectiveMonthlyPrice: 0,
    gstinCapacity: "2 GSTINs",
    gstinLimit: 2,
    blurb: "Essential reconciliation suite to get started. 100% free with full features.",
    cta: "Start Free — 2 GSTINs Forever",
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
        header: "Free Forever",
        benefit: "Zero payment required — no credit card needed to get started",
      },
    ],
  },
  {
    id: "solo",
    name: "Solo",
    valueTagMonthly: "₹32 / GSTIN / mo",
    valueTagYearly: "₹240/GSTIN/yr",
    priceMonthly: 799,
    priceYearly: 5999,
    effectiveMonthlyPrice: 500,
    gstinCapacity: "25 GSTINs",
    gstinLimit: 25,
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
        benefit: "₹799/mo → ₹500/mo billed annually (₹5,999/yr)",
      },
    ],
  },
  {
    id: "firm",
    name: "Firm",
    badge: "Most Popular",
    badgeYearly: "Most Popular",
    valueTagMonthly: "₹20 / GSTIN / mo",
    valueTagYearly: "₹120/GSTIN/yr",
    priceMonthly: 1499,
    priceYearly: 8999,
    effectiveMonthlyPrice: 750,
    gstinCapacity: "75 GSTINs",
    gstinLimit: 75,
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
        benefit: "₹1,499/mo → ₹750/mo billed annually (₹8,999/yr)",
      },
      {
        header: "Multi-Staff Collaboration",
        benefit: "Team invites, client assignments, and complete audit trail",
      },
    ],
  },
  {
    id: "large_firm",
    name: "Large Firm",
    valueTagMonthly: "₹17 / GSTIN / mo",
    valueTagYearly: "₹80/GSTIN/yr",
    priceMonthly: 2499,
    priceYearly: 11999,
    effectiveMonthlyPrice: 1000,
    gstinCapacity: "150 GSTINs",
    gstinLimit: 150,
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
        benefit: "₹2,499/mo → ₹1,000/mo billed annually (₹11,999/yr)",
      },
      {
        header: "Dedicated Support & ERP",
        benefit: "Priority support, onboarding training, and custom ERP integration",
      },
    ],
  },
];

export function formatInr(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}
