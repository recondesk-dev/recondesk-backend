"use client";

import { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";

const features = [
  "5-level invoice matching",
  "ITC recovery amount in ₹",
  "Rule 37 tracking",
  "Section 17(5) flags",
  "Excel + PDF export",
  "Decision layer (what's wrong, why, what to do)",
  "Team collaboration",
];

const pricingFaq = [
  {
    q: "Is there a free trial?",
    a: "Yes. First 2 reconciliations are completely free. No credit card needed.",
  },
  {
    q: "Can I switch plans?",
    a: "Yes. Upgrade or downgrade anytime.",
  },
  {
    q: "What happens to unused runs?",
    a: "They carry over for up to 2 months then expire.",
  },
  {
    q: "How does billing work?",
    a: "Manual monthly payment via Razorpay. No auto-debit mandate required.",
  },
  {
    q: "What is the difference between Solo and Firm plans?",
    a: "Solo plans are designed for individual CAs handling a smaller client base. Firm plans are for CA firms with larger client volumes needing more runs per month at better per-run rates.",
  },
  {
    q: "Do unused runs carry over?",
    a: "For Solo plans, runs expire at the end of each month. For Firm plans, unused runs carry over for up to 2 months.",
  },
  {
    q: "What happens if I need more than 100 runs?",
    a: "Contact us at contact@recondesk.in for a custom Enterprise plan tailored to your firm's volume.",
  },
];

type PlanCardProps = {
  name: string;
  /** Main price string, e.g. "₹499" */
  price: string;
  bullets: string[];
  highlight?: boolean;
  badge?: string;
  cta: string;
  href: string;
};

function PlanCard({ name, price, bullets, highlight = false, badge, cta, href }: PlanCardProps) {
  return (
    <div
      className={`relative z-10 flex flex-col rounded-[1.5rem] bg-white p-6 transition duration-300 ${
        highlight ? "shadow-[var(--shadow-lift)]" : "shadow-[var(--shadow-soft)]"
      }`}
    >
      {badge ? (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-[var(--ink)] px-3 py-0.5 text-xs font-semibold text-white">
          {badge}
        </span>
      ) : null}

      <h2 className="text-lg font-semibold text-[var(--ink)]">{name}</h2>

      <p className="mt-2 font-mono text-3xl font-bold tracking-tight text-[var(--ink)]">
        {price}
        <span className="ml-1.5 text-base font-normal text-gray-400">+ GST</span>
      </p>

      <ul className="mt-4 flex-1 space-y-2 text-sm text-gray-600">
        {bullets.map((line) => (
          <li key={line}>• {line}</li>
        ))}
      </ul>

      <Link
        href={href}
        className={`mt-6 inline-flex w-full min-h-[44px] items-center justify-center rounded-full px-4 py-2.5 text-sm font-semibold transition ${
          highlight
            ? "bg-[var(--ink)] text-white hover:opacity-90"
            : "bg-[#F5F5F6] text-[var(--ink)] hover:bg-[#EBEBED]"
        }`}
      >
        {cta}
      </Link>
    </div>
  );
}

function EnterpriseCard() {
  const bullets = [
    "100+ runs/month",
    "Dedicated support",
    "Custom onboarding",
    "SLA guarantee",
  ];

  return (
    <div className="lg:col-span-2 flex flex-col gap-6 rounded-[1.5rem] bg-white p-6 shadow-[var(--shadow-soft)] sm:flex-row sm:items-stretch sm:justify-between sm:gap-8">
      <div className="flex min-w-0 flex-1 flex-col">
        <h2 className="text-lg font-semibold text-[var(--ink)]">Enterprise</h2>
        <p className="mt-2 font-mono text-3xl font-bold tracking-tight text-[var(--ink)]">Custom pricing</p>
        <ul className="mt-4 space-y-2 text-sm text-gray-600">
          {bullets.map((line) => (
            <li key={line}>• {line}</li>
          ))}
        </ul>
      </div>
      <div className="flex shrink-0 flex-col justify-end sm:w-48">
        <a
          href="mailto:contact@recondesk.in"
          className="inline-flex min-h-[44px] w-full items-center justify-center rounded-full bg-[var(--ink)] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
        >
          Contact Sales
        </a>
      </div>
    </div>
  );
}

export default function PricingPage() {
  const [tier, setTier] = useState<"solo" | "firm">("solo");

  const tabBase =
    "relative z-10 min-h-[44px] flex-1 rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-300 ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ink)] sm:flex-none sm:px-8";
  const tabActive = "text-white";
  const tabInactive = "text-gray-600 hover:text-[var(--ink)]";

  return (
    <div className="px-4 pb-16 pt-10 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl text-center">
        <h1 className="text-3xl font-semibold tracking-tight text-[var(--ink)] sm:text-4xl">Simple Monthly Plans</h1>
        <p className="mt-4 text-lg text-gray-600">
          First 2 reconciliations free. No credit card required.
        </p>

        <div className="mx-auto mt-10 flex w-full max-w-md justify-center sm:max-w-none">
          <div
            className="relative inline-flex w-full rounded-full bg-white p-1 shadow-[var(--shadow-soft)] sm:w-auto"
            role="tablist"
            aria-label="Plan type"
          >
            <span
              className="pointer-events-none absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-full bg-[var(--ink)] shadow-sm transition-transform duration-300 ease-out"
              style={{
                transform: tier === "solo" ? "translateX(0)" : "translateX(100%)",
              }}
              aria-hidden
            />
            <button
              id="tab-solo"
              type="button"
              role="tab"
              aria-selected={tier === "solo"}
              aria-controls="pricing-plans-panel"
              className={`${tabBase} ${tier === "solo" ? tabActive : tabInactive}`}
              onClick={() => setTier("solo")}
            >
              Individual
            </button>
            <button
              id="tab-firm"
              type="button"
              role="tab"
              aria-selected={tier === "firm"}
              aria-controls="pricing-plans-panel"
              className={`${tabBase} ${tier === "firm" ? tabActive : tabInactive}`}
              onClick={() => setTier("firm")}
            >
              Enterprise
            </button>
          </div>
        </div>
      </div>

      <div
        id="pricing-plans-panel"
        role="tabpanel"
        aria-labelledby={tier === "solo" ? "tab-solo" : "tab-firm"}
        className="mx-auto mt-14 max-w-6xl"
      >
        {tier === "solo" ? (
          <div key="solo" className="pricing-tier-enter grid gap-6 lg:grid-cols-4">
            <PlanCard
              name="Starter"
              price="₹499"
              bullets={["1 run/month", "₹499/run", "Runs expire monthly — no carry over"]}
              href="/auth/signup"
              cta="Start Free"
            />
            <PlanCard
              name="Growth"
              price="₹1,699"
              bullets={["5 runs/month", "₹340/run", "Runs expire monthly — no carry over"]}
              highlight
              badge="Most Popular"
              href="/auth/signup"
              cta="Start Free"
            />
            <PlanCard
              name="Pro"
              price="₹3,699"
              bullets={["12 runs/month", "₹308/run", "Runs expire monthly — no carry over"]}
              badge="Best Value"
              href="/auth/signup"
              cta="Start Free"
            />
            <PlanCard
              name="Scale"
              price="₹5,699"
              bullets={["30 runs/month", "₹190/run", "Runs expire monthly — no carry over"]}
              badge="Founder's Offer"
              href="/auth/signup"
              cta="Start Free"
            />
          </div>
        ) : (
          <div key="firm" className="pricing-tier-enter grid gap-6 lg:grid-cols-2">
            <PlanCard
              name="Growth Firm"
              price="₹8,699"
              bullets={[
                "50 runs/month",
                "₹174/run",
                "Unused runs carry over for up to 2 months",
              ]}
              highlight
              badge="Most Popular"
              href="/auth/signup"
              cta="Start Free"
            />
            <PlanCard
              name="Scale Firm"
              price="₹14,699"
              bullets={[
                "100 runs/month",
                "₹147/run",
                "Unused runs carry over for up to 2 months",
              ]}
              badge="Best Value"
              href="/auth/signup"
              cta="Start Free"
            />
            <EnterpriseCard />
          </div>
        )}
      </div>

      <p className="mx-auto mt-6 max-w-6xl text-xs text-gray-500">
        All prices exclude GST. 18% GST applicable.
      </p>

      <div className="mx-auto mt-16 max-w-3xl rounded-[1.5rem] bg-white p-6 shadow-[var(--shadow-soft)] sm:p-8">
        <h2 className="text-center text-lg font-semibold text-[var(--ink)]">Included in every plan</h2>
        <ul className="mt-6 grid gap-3 sm:grid-cols-2">
          {features.map((f) => (
            <li key={f} className="flex items-start gap-2 text-sm text-gray-600">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
              {f}
            </li>
          ))}
        </ul>
      </div>

      <div className="mx-auto mt-16 max-w-3xl">
        <h2 className="text-center text-xl font-semibold text-[var(--ink)]">Pricing FAQ</h2>
        <dl className="mt-8 space-y-3">
          {pricingFaq.map(({ q, a }) => (
            <div key={q} className="rounded-[1.25rem] bg-white px-5 py-4 shadow-[var(--shadow-soft)]">
              <dt className="font-semibold text-[var(--ink)]">{q}</dt>
              <dd className="mt-2 text-sm text-gray-500">{a}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
