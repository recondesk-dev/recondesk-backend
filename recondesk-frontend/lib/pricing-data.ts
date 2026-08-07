export type PricingPlan = {
  id: "starter" | "growth" | "custom";
  name: string;
  priceDisplay: string;
  periodLabel: string;
  gstinCapacity: string;
  blurb: string;
  cta: string;
  ctaHref?: string;
  featured?: boolean;
  isCustom?: boolean;
  featureSectionHeader?: string;
  features: {
    header: string;
    benefit: string;
  }[];
};

export const PRICING_PLANS: PricingPlan[] = [
  {
    id: "starter",
    name: "Starter",
    priceDisplay: "₹5,999",
    periodLabel: "/year",
    gstinCapacity: "Up to 50 GSTINs",
    blurb: "Essential GSTR-2B reconciliation & ITC risk protection for growing CA practices.",
    cta: "Start with Starter",
    featured: false,
    features: [
      {
        header: "GSTR-2B vs Books reconciliation",
        benefit: "Tiered smart matching from exact invoice match to fuzzy search",
      },
      {
        header: "Decision Layer",
        benefit: "See WHY every mismatch happened and WHAT to do next, not just raw errors",
      },
      {
        header: "Missed ITC & ITC-at-Risk detection",
        benefit: "Instantly surface unclaimed tax credits & high-risk vendor invoices",
      },
      {
        header: "Rule 37 tracking",
        benefit: "Never miss a 180-day reversal deadline again on unpaid invoices",
      },
      {
        header: "Section 17(5) blocked credit detection",
        benefit: "Auto-detect ineligible non-claimable supplier GST before filing",
      },
      {
        header: "Duplicate invoice detection",
        benefit: "Prevent accidental double-claiming on duplicate entries",
      },
      {
        header: "Flexible ERP import",
        benefit: "Import seamlessly from any ERP, Tally, Busy, or custom Excel format",
      },
      {
        header: "Advanced filtered export",
        benefit: "Comprehensive Excel audit workbooks & client-ready PDF reports",
      },
    ],
  },
  {
    id: "growth",
    name: "Growth",
    priceDisplay: "₹9,999",
    periodLabel: "/year",
    gstinCapacity: "Up to 100 GSTINs",
    blurb: "Complete compliance suite with end-to-end automation, e-invoicing & multi-period audit.",
    cta: "Go Growth",
    featured: true,
    featureSectionHeader: "Everything in Starter, plus:",
    features: [
      {
        header: "GSTR-3B tie-out",
        benefit: "2B vs 3B ITC comparison with automatic DRC-01C risk trigger",
      },
      {
        header: "GSTR-1 vs 3B outward liability tie-out",
        benefit: "Outward supply comparison with automatic DRC-01B risk trigger",
      },
      {
        header: "GSTR-1A amendment window tracking",
        benefit: "Monitor post-filing outward sales adjustments seamlessly",
      },
      {
        header: "Sales-side (GSTR-1) reconciliation",
        benefit: "Complete outward supply audit & sales register matching",
      },
      {
        header: "E-Invoice Check",
        benefit: "Verify books against IRP with live IRN lookup",
      },
      {
        header: "Multi-Period Wizard",
        benefit: "Auto-fetch & reconcile a full financial year in 1 run (GSTR-9C ready)",
      },
      {
        header: "IMS Actions",
        benefit: "Accept/reject/hold recommendations with direct GSTN writeback",
      },
      {
        header: "Vendor Compliance Scorecards",
        benefit: "Vendor-wise ITC risk ranking & filing reliability history",
      },
      {
        header: "Follow-up Log",
        benefit: "Complete audit trail of supplier communications & chase letters",
      },
      {
        header: "Live Tally Bridge sync",
        benefit: "Real-time Purchase Register sync with zero manual upload",
      },
      {
        header: "Priority support",
        benefit: "Fast-lane support response during peak tax filing deadlines",
      },
    ],
  },
  {
    id: "custom",
    name: "Custom",
    priceDisplay: "Let's Talk",
    periodLabel: "",
    gstinCapacity: "100+ GSTINs",
    blurb: "Bespoke capacity, dedicated support & custom onboarding for enterprise & multi-partner firms.",
    cta: "Talk to us",
    ctaHref: "mailto:contact@recondesk.in?subject=Custom%20Enterprise%20Plan%20Enquiry",
    featured: false,
    isCustom: true,
    features: [
      {
        header: "More than 100 GSTIN capacity",
        benefit: "Flexible volume sizing tailored to large client portfolios",
      },
      {
        header: "Custom onboarding & training",
        benefit: "Dedicated workflow setup & staff training for multi-partner firms",
      },
      {
        header: "Dedicated account manager",
        benefit: "Direct escalation channel & guaranteed SLA response times",
      },
      {
        header: "Tailored data integrations",
        benefit: "Enterprise API access & bespoke ERP data pipelines",
      },
      {
        header: "Firm-wide administration",
        benefit: "Centralized multi-office workspace & consolidated billing controls",
      },
    ],
  },
];
