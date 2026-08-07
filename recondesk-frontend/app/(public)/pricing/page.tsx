import { SubscriptionFeatures } from "@/components/billing/SubscriptionFeatures";
import { PricingGrid } from "@/components/billing/PricingGrid";

const pricingFaq = [
  {
    q: "Is there a free trial?",
    a: "Yes. Your first 2 reconciliations are free — no credit card needed. Free accounts can manage up to 1 GSTIN.",
  },
  {
    q: "What am I paying for?",
    a: "You pay an annual subscription based on your firm's GSTIN capacity (Starter: up to 50 GSTINs, Growth: up to 100 GSTINs, Custom: 100+ GSTINs). Every plan includes unlimited reconciliation runs during the subscription period.",
  },
  {
    q: "What is the difference between Starter and Growth?",
    a: "Starter delivers complete GSTR-2B vs Books reconciliation, Decision Layer, Missed ITC, Rule 37 tracking, Section 17(5) blocked credit, and exports for up to 50 GSTINs. Growth expands capacity to 100 GSTINs and unlocks advanced features including GSTR-3B tie-outs, GSTR-1 sales-side recon, E-Invoice verification, Multi-Period FY Wizard, IMS direct writeback, Vendor Scorecards, Live Tally Bridge sync, and priority support.",
  },
  {
    q: "Can I upgrade my plan anytime?",
    a: "Yes. You can upgrade from Starter to Growth or to a Custom plan whenever your firm expands client capacity. Purchasing an upgrade extends your subscription period.",
  },
  {
    q: "How does billing work?",
    a: "Manual annual payment via Razorpay. No automatic debit mandates or surprise credit card charges.",
  },
  {
    q: "Are prices inclusive of GST?",
    a: "Listed prices exclude 18% GST. Standard 18% GST is added at checkout with tax invoice provided for input credit.",
  },
  {
    q: "What if my firm manages more than 100 GSTINs?",
    a: "Select our Custom tier or email contact@recondesk.in. We provide tailored volume pricing, multi-partner onboarding, dedicated account management, and custom SLAs.",
  },
] as const;

export default function PricingPage() {
  return (
    <div className="relative px-4 pb-20 pt-10 sm:px-6 lg:px-8">
      <div
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[520px] overflow-hidden"
        aria-hidden
      >
        <div className="absolute left-1/2 top-8 h-72 w-[42rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(17,17,17,0.06),transparent_70%)] blur-2xl" />
        <div className="absolute right-[8%] top-40 h-56 w-56 rounded-full bg-[radial-gradient(circle,rgba(17,17,17,0.06),transparent_70%)] blur-2xl" />
      </div>

      <div className="mx-auto max-w-6xl text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
          Pricing
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-[var(--ink)] sm:text-4xl lg:text-5xl">
          Simple plans. Sized by GSTIN capacity.
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-base text-gray-600 sm:text-lg">
          Choose the right tier for your firm&apos;s portfolio. Annual subscriptions with unlimited reconciliation runs.
        </p>
      </div>

      <PricingGrid />

      <p className="mx-auto mt-8 max-w-6xl text-center text-xs text-gray-500">
        Free to start · 2 reconciliations included · Manual Razorpay annual renewal · No auto-debit
      </p>

      <SubscriptionFeatures />

      <div className="mx-auto mt-20 max-w-3xl">
        <h2 className="text-center text-xl font-semibold text-[var(--ink)] sm:text-2xl">
          Frequently Asked Questions
        </h2>
        <dl className="mt-8 space-y-3">
          {pricingFaq.map(({ q, a }) => (
            <div
              key={q}
              className="rounded-[1.25rem] bg-white/80 px-5 py-4 shadow-[var(--shadow-soft)] backdrop-blur-sm"
            >
              <dt className="font-semibold text-[var(--ink)]">{q}</dt>
              <dd className="mt-2 text-sm text-gray-600 leading-relaxed">{a}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
