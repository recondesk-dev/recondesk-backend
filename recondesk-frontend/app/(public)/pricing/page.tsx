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
];

export default function PricingPage() {
  return (
    <div className="px-4 pb-16 pt-10 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl text-center">
        <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">Simple Monthly Plans</h1>
        <p className="mt-4 text-lg text-slate-400">
          First 2 reconciliations free. No credit card required.
        </p>
      </div>

      <div className="mx-auto mt-14 grid max-w-6xl gap-6 lg:grid-cols-3">
        {/* Starter */}
        <div className="flex flex-col rounded-2xl border border-white/10 bg-[#13161f] p-6">
          <h2 className="text-lg font-semibold text-white">Starter</h2>
          <p className="mt-2 font-mono text-3xl font-semibold text-white">
            ₹399<span className="text-base font-normal text-slate-400">/month</span>
          </p>
          <ul className="mt-6 flex-1 space-y-3 text-sm text-slate-300">
            <li>1 run/month</li>
            <li>₹399/run</li>
            <li>Unused runs carry over up to 2 months</li>
          </ul>
          <Link
            href="/auth/signup"
            className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-lg border border-white/15 bg-white/5 text-sm font-semibold text-white transition hover:bg-white/10"
          >
            Start Free
          </Link>
        </div>

        {/* Growth */}
        <div className="relative flex flex-col rounded-2xl border-2 border-[var(--accent)] bg-[#13161f] p-6 shadow-lg shadow-[var(--accent)]/10">
          <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[var(--accent)] px-3 py-0.5 text-xs font-semibold text-white">
            Most Popular
          </span>
          <h2 className="text-lg font-semibold text-white">Growth</h2>
          <p className="mt-2 font-mono text-3xl font-semibold text-white">
            ₹1,700<span className="text-base font-normal text-slate-400">/month</span>
          </p>
          <ul className="mt-6 flex-1 space-y-3 text-sm text-slate-300">
            <li>5 runs/month</li>
            <li>₹340/run — save 15%</li>
            <li>Unused runs carry over up to 2 months</li>
          </ul>
          <Link
            href="/auth/signup"
            className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-lg bg-[var(--accent)] text-sm font-semibold text-white transition hover:opacity-95"
          >
            Start Free
          </Link>
        </div>

        {/* Pro */}
        <div className="flex flex-col rounded-2xl border border-white/10 bg-[#13161f] p-6">
          <h2 className="text-lg font-semibold text-white">Pro</h2>
          <p className="mt-2 font-mono text-3xl font-semibold text-white">
            ₹3,499<span className="text-base font-normal text-slate-400">/month</span>
          </p>
          <ul className="mt-6 flex-1 space-y-3 text-sm text-slate-300">
            <li>12 runs/month</li>
            <li>₹291/run — save 27%</li>
            <li>Unused runs carry over up to 2 months</li>
          </ul>
          <Link
            href="/auth/signup"
            className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-lg border border-white/15 bg-white/5 text-sm font-semibold text-white transition hover:bg-white/10"
          >
            Start Free
          </Link>
        </div>
      </div>

      <div className="mx-auto mt-16 max-w-3xl rounded-2xl border border-white/10 bg-[#0a0c10]/80 p-6 sm:p-8">
        <h2 className="text-center text-lg font-semibold text-white">Included in every plan</h2>
        <ul className="mt-6 grid gap-3 sm:grid-cols-2">
          {features.map((f) => (
            <li key={f} className="flex items-start gap-2 text-sm text-slate-300">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" aria-hidden />
              {f}
            </li>
          ))}
        </ul>
      </div>

      <div className="mx-auto mt-16 max-w-3xl">
        <h2 className="text-center text-xl font-semibold text-white">Pricing FAQ</h2>
        <dl className="mt-8 space-y-4">
          {pricingFaq.map(({ q, a }) => (
            <div key={q} className="rounded-xl border border-white/10 bg-[#13161f] px-5 py-4">
              <dt className="font-semibold text-white">{q}</dt>
              <dd className="mt-2 text-sm text-slate-400">{a}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
