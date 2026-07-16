import Link from "next/link";
import { SubscriptionFeatures } from "@/components/billing/SubscriptionFeatures";

const plans = [
  {
    id: "starter",
    name: "Starter",
    price: 999,
    periodLabel: "/month",
    gstins: 25,
    blurb: "For solo CAs building a steady client desk.",
    cta: "Start with Starter",
    featured: false,
  },
  {
    id: "growth",
    name: "Growth",
    price: 7999,
    periodLabel: "/year",
    gstins: 50,
    blurb: "Best value for growing firms — a full year of capacity.",
    cta: "Go Growth",
    featured: true,
  },
  {
    id: "pro",
    name: "Pro",
    price: 11999,
    periodLabel: "/year",
    gstins: 75,
    blurb: "Room for a larger portfolio without changing how you work.",
    cta: "Choose Pro",
    featured: false,
  },
] as const;

const pricingFaq = [
  {
    q: "Is there a free trial?",
    a: "Yes. Your first 2 reconciliations are free — no credit card needed. Free accounts can manage up to 2 GSTINs.",
  },
  {
    q: "What am I paying for?",
    a: "You pay for GSTIN capacity and the subscription period. Every plan includes the full ReconDesk product — matching, compliance, exports, team tools. Higher plans simply let you add more client GSTINs.",
  },
  {
    q: "Can I switch plans?",
    a: "Yes. Upgrade anytime. Purchasing a plan extends your subscription from your current end date (or today if expired).",
  },
  {
    q: "How does billing work?",
    a: "Manual payment via Razorpay — monthly for Starter, yearly for Growth and Pro. No auto-debit mandate.",
  },
  {
    q: "Are prices inclusive of GST?",
    a: "Listed prices exclude GST. 18% GST is added at checkout.",
  },
  {
    q: "What if I need more than 75 GSTINs?",
    a: "Write to contact@recondesk.in for a custom Enterprise plan sized to your firm.",
  },
] as const;

function formatInr(n: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(n);
}

function PlanCard({
  plan,
}: {
  plan: (typeof plans)[number];
}) {
  return (
    <article
      className={`liquid-glass-card ${plan.featured ? "liquid-glass-card--featured" : ""} flex h-full flex-col p-7 sm:p-8`}
    >
      <span className="liquid-glass-card__blob liquid-glass-card__blob--a" aria-hidden />
      <span className="liquid-glass-card__blob liquid-glass-card__blob--b" aria-hidden />
      <div className="liquid-glass-card__content flex h-full flex-col">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">{plan.name}</h2>
            <p className="mt-1 text-sm text-gray-500">{plan.blurb}</p>
          </div>
          {plan.featured && (
            <span className="shrink-0 rounded-full bg-[var(--ink)] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-white">
              Best value
            </span>
          )}
        </div>

        <div className="mt-8">
          <p className="flex items-baseline gap-1">
            <span className="text-4xl font-semibold tracking-tight text-[var(--ink)] tabular-nums">
              {formatInr(plan.price)}
            </span>
            <span className="text-sm text-gray-500">{plan.periodLabel}</span>
          </p>
          <p className="mt-2 text-sm font-medium text-[var(--ink)]">
            Up to {plan.gstins} GSTINs
          </p>
          <p className="mt-1 text-xs text-gray-500">Excl. 18% GST · unlimited runs in period</p>
        </div>

        <ul className="mt-8 space-y-2.5 text-sm text-gray-600">
          <li className="flex gap-2">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--ink)]" aria-hidden />
            Full product on every plan
          </li>
          <li className="flex gap-2">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--ink)]" aria-hidden />
            GSTR-2B + GSTR-1 reconciliation
          </li>
          <li className="flex gap-2">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--ink)]" aria-hidden />
            Team, exports, and follow-ups included
          </li>
        </ul>

        <div className="mt-auto pt-8">
          <Link
            href={`/signup?plan=${plan.id}`}
            className={`inline-flex w-full min-h-[44px] items-center justify-center rounded-full px-6 py-2.5 text-sm font-semibold transition-opacity hover:opacity-90 ${
              plan.featured
                ? "bg-[var(--ink)] text-white shadow-sm"
                : "bg-white/80 text-[var(--ink)] ring-1 ring-black/10"
            }`}
          >
            {plan.cta}
          </Link>
        </div>
      </div>
    </article>
  );
}

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
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-[var(--ink)] sm:text-4xl">
          Simple plans. Priced by GSTIN.
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-gray-600">
          One product. Three capacities. Pay monthly or yearly — every subscription unlocks the
          full desk.
        </p>
      </div>

      <div className="mx-auto mt-14 grid max-w-6xl gap-6 lg:grid-cols-3">
        {plans.map((plan) => (
          <PlanCard key={plan.id} plan={plan} />
        ))}
      </div>

      <p className="mx-auto mt-6 max-w-6xl text-center text-xs text-gray-500">
        Free to start · 2 reconciliations included · Manual Razorpay renewal · No auto-debit
      </p>

      <SubscriptionFeatures />

      <div className="mx-auto mt-20 max-w-3xl">
        <h2 className="text-center text-xl font-semibold text-[var(--ink)]">Pricing FAQ</h2>
        <dl className="mt-8 space-y-3">
          {pricingFaq.map(({ q, a }) => (
            <div
              key={q}
              className="rounded-[1.25rem] bg-white/80 px-5 py-4 shadow-[var(--shadow-soft)] backdrop-blur-sm"
            >
              <dt className="font-semibold text-[var(--ink)]">{q}</dt>
              <dd className="mt-2 text-sm text-gray-500">{a}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
