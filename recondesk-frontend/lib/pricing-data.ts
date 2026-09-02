export type BillingCycle = "monthly" | "yearly";

export type PricingTierId = "starter" | "growth" | "pro" | "firm";

export type PricingPlan = {
  id: PricingTierId;
  name: string;
  badge?: string;
  badgeYearly?: string;
  valueTagMonthly?: string;
  valueTagYearly?: string;
  priceMonthly: number;
  priceYearly: number;
  overageMonthlyPerGstin?: number;
  overageYearlyPerGstin?: number;
  gstinCapacity: string;
  gstinLimit: number;
  blurb: string;
  cta: string;
  ctaHref?: string;
  featured?: boolean;
  isFirm?: boolean;
  highlights: {
    header: string;
    benefit: string;
  }[];
};

export const PRICING_PLANS: PricingPlan[] = [
  {
    id: "starter",
    name: "Starter",
    badgeYearly: "Save ~30%",
    valueTagMonthly: "₹48 / GSTIN / mo",
    valueTagYearly: "₹400 / GSTIN / yr",
    priceMonthly: 1199,
    priceYearly: 9999,
    gstinCapacity: "Up to 25 GSTINs",
    gstinLimit: 25,
    blurb: "Essential full-featured reconciliation suite for solo CAs & boutique practices.",
    cta: "Start Starter",
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
        header: "Save ~30% on Annual",
        benefit: "Save ₹4,389/year with yearly billing compared to monthly",
      },
    ],
  },
  {
    id: "growth",
    name: "Growth",
    badge: "Most Popular",
    badgeYearly: "Save ~31%",
    valueTagMonthly: "₹36 / GSTIN / mo",
    valueTagYearly: "₹300 / GSTIN / yr",
    priceMonthly: 1799,
    priceYearly: 14999,
    gstinCapacity: "Up to 50 GSTINs",
    gstinLimit: 50,
    blurb: "High-capacity suite for growing CA practices with active tax teams.",
    cta: "Go Growth",
    featured: true,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating — all 15+ matching & compliance tools included",
      },
      {
        header: "Up to 50 Client GSTINs",
        benefit: "Double your client capacity with unlimited monthly/annual runs",
      },
      {
        header: "Save ~31% on Annual",
        benefit: "Save ₹6,589/year with yearly billing compared to monthly",
      },
    ],
  },
  {
    id: "pro",
    name: "Pro",
    badgeYearly: "Save ~30%",
    valueTagMonthly: "₹24 / GSTIN / mo",
    valueTagYearly: "₹200 / GSTIN / yr",
    priceMonthly: 2399,
    priceYearly: 19999,
    gstinCapacity: "Up to 100 GSTINs",
    gstinLimit: 100,
    blurb: "Comprehensive capacity for large CA firms and dedicated compliance teams.",
    cta: "Choose Pro",
    featured: false,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating — all 15+ matching & compliance tools included",
      },
      {
        header: "Up to 100 Client GSTINs",
        benefit: "Best rate per GSTIN with unlimited reconciliation runs for all clients",
      },
      {
        header: "Multi-Staff Collaboration",
        benefit: "Team invites, client assignments, and complete audit trail",
      },
    ],
  },
  {
    id: "firm",
    name: "Firm",
    badge: "Scale",
    valueTagMonthly: "+₹25/GSTIN > 100",
    valueTagYearly: "+₹200/GSTIN > 100",
    priceMonthly: 2399,
    priceYearly: 19999,
    overageMonthlyPerGstin: 25,
    overageYearlyPerGstin: 200,
    gstinCapacity: "100+ GSTINs",
    gstinLimit: 100,
    blurb: "Dynamic usage-scaled pricing for multi-partner firms managing over 100 GSTINs.",
    cta: "Start Firm",
    featured: false,
    isFirm: true,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating with unlimited GSTIN capacity scaling",
      },
      {
        header: "Usage-Scaled Beyond 100",
        benefit: "₹25/mo or ₹200/yr per additional GSTIN beyond 100 clients",
      },
      {
        header: "Dedicated Account Support",
        benefit: "Priority support, onboarding training, and custom ERP integration assistance",
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

export function calculateFirmPrice(
  cycle: BillingCycle,
  totalGstinCount: number
): {
  basePrice: number;
  extraGstins: number;
  overageRate: number;
  overageAmount: number;
  totalBeforeGst: number;
  gstAmount: number;
  totalWithGst: number;
} {
  const isYearly = cycle === "yearly";
  const basePrice = isYearly ? 19999 : 2399;
  const overageRate = isYearly ? 200 : 25;
  const extraGstins = Math.max(0, totalGstinCount - 100);
  const overageAmount = extraGstins * overageRate;
  const totalBeforeGst = basePrice + overageAmount;
  const gstAmount = Math.round(totalBeforeGst * 0.18);
  const totalWithGst = totalBeforeGst + gstAmount;

  return {
    basePrice,
    extraGstins,
    overageRate,
    overageAmount,
    totalBeforeGst,
    gstAmount,
    totalWithGst,
  };
}
