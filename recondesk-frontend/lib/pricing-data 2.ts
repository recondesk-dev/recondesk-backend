export type PricingPlan = {
  id: "monthly" | "starter" | "growth" | "custom";
  name: string;
  badge?: string;
  valueTag?: string;
  priceDisplay: string;
  periodLabel: string;
  gstinCapacity: string;
  blurb: string;
  cta: string;
  ctaHref?: string;
  featured?: boolean;
  isCustom?: boolean;
  highlights: {
    header: string;
    benefit: string;
  }[];
};

export const PRICING_PLANS: PricingPlan[] = [
  {
    id: "monthly",
    name: "Monthly",
    badge: "Flexible",
    valueTag: "Pay-as-you-go",
    priceDisplay: "₹999",
    periodLabel: "/month",
    gstinCapacity: "Up to 25 GSTINs",
    blurb: "Flexible month-to-month access with zero long-term commitment.",
    cta: "Start Monthly",
    featured: false,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating — all 15+ audit & matching tools included",
      },
      {
        header: "Pay Month-to-Month",
        benefit: "Ideal for short-term projects or trying out ReconDesk",
      },
      {
        header: "Up to 25 Client GSTINs",
        benefit: "Manage up to 25 active GSTINs with unlimited period runs",
      },
    ],
  },
  {
    id: "starter",
    name: "Starter",
    badge: "Save 50%",
    valueTag: "₹120 / GSTIN / yr",
    priceDisplay: "₹5,999",
    periodLabel: "/year",
    gstinCapacity: "Up to 50 GSTINs",
    blurb: "Essential annual capacity for growing individual CA practices.",
    cta: "Start with Starter",
    featured: false,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating — all 15+ audit & matching tools included",
      },
      {
        header: "Save 50% vs Monthly",
        benefit: "Save ₹5,989/yr compared to paying monthly",
      },
      {
        header: "Up to 50 Client GSTINs",
        benefit: "Manage up to 50 active GSTINs with unlimited annual runs",
      },
    ],
  },
  {
    id: "growth",
    name: "Growth",
    badge: "Most Popular",
    valueTag: "Best Value (~₹100/GSTIN)",
    priceDisplay: "₹9,999",
    periodLabel: "/year",
    gstinCapacity: "Up to 100 GSTINs",
    blurb: "High-capacity annual suite for mid-size firms & active tax teams.",
    cta: "Go Growth",
    featured: true,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating — all 15+ audit & matching tools included",
      },
      {
        header: "2x Capacity for +₹4,000",
        benefit: "Double your GSTIN capacity from 50 to 100 at our lowest rate per GSTIN",
      },
      {
        header: "Up to 100 Client GSTINs",
        benefit: "Built for expanding CA practices with growing client portfolios",
      },
    ],
  },
  {
    id: "custom",
    name: "Custom",
    badge: "Enterprise",
    valueTag: "Custom SLA & Volume",
    priceDisplay: "Let's Talk",
    periodLabel: "",
    gstinCapacity: "100+ GSTINs",
    blurb: "Bespoke volume, SLAs & dedicated support for multi-partner firms.",
    cta: "Talk to us",
    ctaHref: "mailto:contact@recondesk.in?subject=Custom%20Enterprise%20Plan%20Enquiry",
    featured: false,
    isCustom: true,
    highlights: [
      {
        header: "100% Full Desk Access",
        benefit: "Zero feature gating + bespoke volume sizing (100+ GSTINs)",
      },
      {
        header: "Dedicated Account Manager",
        benefit: "Direct escalation channel & guaranteed SLA response times",
      },
      {
        header: "Custom Onboarding & Integrations",
        benefit: "Multi-partner team training & tailored ERP data pipelines",
      },
    ],
  },
];

