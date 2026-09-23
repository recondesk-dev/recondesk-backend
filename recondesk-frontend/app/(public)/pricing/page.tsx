import { SubscriptionFeatures } from "@/components/billing/SubscriptionFeatures";
import { PricingGrid } from "@/components/billing/PricingGrid";

const pricingFaq = [
  {
    q: "Is there a free plan?",
    a: "Yes. Our Free plan gives you up to 2 GSTINs completely free forever with unlimited reconciliation runs and zero feature gating — no credit card needed.",
  },
  {
    q: "What am I paying for?",
    a: "You pay a subscription based on your firm's GSTIN capacity (Solo: up to 25 GSTINs, Firm: up to 75 GSTINs, Large Firm: up to 150 GSTINs). Every plan includes unlimited reconciliation runs during the subscription period.",
  },
  {
    q: "What is the difference between the plans?",
    a: "Every plan includes 100% of ReconDesk features — zero feature gating. All tiers include the full matching engine, IMS recommendations, Rule 37/17(5) engine, RCM reconciliation, audit observations, supplier scorecard, and Tally Bridge. Tiers differ ONLY by GSTIN capacity.",
  },
  {
    q: "Can I upgrade my plan anytime?",
    a: "Yes. You can upgrade from Solo to Firm or Large Firm whenever your firm expands client capacity. Purchasing an upgrade immediately extends your capacity and period.",
  },
  {
    q: "How does billing work?",
    a: "Payments are processed securely via Razorpay. Choose monthly billing or get a discounted effective monthly rate billed annually. Annual plans are manual one-time payments per annual cycle.",
  },
  {
    q: "Are prices inclusive of GST?",
    a: "Listed prices exclude 18% GST (+18% GST applies to all paid plans). Standard 18% GST is added at checkout with a formal tax invoice provided for input tax credit.",
  },
  {
    q: "What if my firm manages more than 150 GSTINs?",
    a: "Email contact@recondesk.in for tailored enterprise deployments and custom multi-partner firm setups.",
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
        Free to start · 2 GSTINs included forever · Unlimited runs · Manual Razorpay annual renewal · No auto-debit
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
