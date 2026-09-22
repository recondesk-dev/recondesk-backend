export type BillingCycle = "monthly" | "yearly";

export type PricingTierId = "free" | "solo" | "firm" | "large_firm";

export type PricingPlan = {
  id: PricingTierId;
  name: string;
  badge?: string;
  badgeYearly?: string;
  valueTagMonthly?: string;
  valueTagYearly?: string;
  annualSavingsText?: string;
  priceMonthly: number;
  priceYearly: number;
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
    badgeYearly: "Save ₹3,589",
    valueTagMonthly: "₹32 / GSTIN / mo",
    valueTagYearly: "₹240/GSTIN/yr",
    annualSavingsText: "Save ₹3,589 — almost 5 months free",
    priceMonthly: 799,
    priceYearly: 5999,
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
        header: "Annual Savings",
        benefit: "Save ₹3,589 — almost 5 months free with annual billing",
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
    annualSavingsText: "Save ₹8,989 — almost 6 months free",
    priceMonthly: 1499,
    priceYearly: 8999,
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
        header: "Annual Savings",
        benefit: "Save ₹8,989 — almost 6 months free with annual billing",
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
    badgeYearly: "Save ₹14,989",
    valueTagMonthly: "₹17 / GSTIN / mo",
    valueTagYearly: "₹100/GSTIN/yr",
    annualSavingsText: "Save ₹14,989 — almost 5 months free",
    priceMonthly: 2499,
    priceYearly: 14999,
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
        header: "Annual Savings",
        benefit: "Save ₹14,989 — almost 5 months free with annual billing",
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
