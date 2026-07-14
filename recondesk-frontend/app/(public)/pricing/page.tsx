"use client";

import { useState } from "react";
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

function PlanCard({ highlight = false }: { highlight?: boolean }) {
  return (
    <div
      className={`relative z-10 min-h-[280px] rounded-[1.5rem] bg-white p-6 transition duration-300 ${
        highlight ? "shadow-[var(--shadow-lift)]" : "shadow-[var(--shadow-soft)]"
      }`}
      aria-hidden
    />
  );
}

function EnterpriseCard() {
  return (
    <div
      className="lg:col-span-2 min-h-[200px] rounded-[1.5rem] bg-white p-6 shadow-[var(--shadow-soft)]"
      aria-hidden
    />
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
            <PlanCard />
            <PlanCard highlight />
            <PlanCard />
            <PlanCard />
          </div>
        ) : (
          <div key="firm" className="pricing-tier-enter grid gap-6 lg:grid-cols-2">
            <PlanCard highlight />
            <PlanCard />
            <EnterpriseCard />
          </div>
        )}
      </div>


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
