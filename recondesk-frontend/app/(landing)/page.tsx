import Link from "next/link";
import { ClipboardList, GitMerge, Upload } from "lucide-react";

import { FaqAccordion } from "@/components/public/FaqAccordion";
import { FeatureStatsStrip } from "@/components/public/FeatureStatsStrip";
import { SecurityTrustStrip } from "@/components/public/SecurityTrustStrip";
import { formatInrFull } from "@/lib/format";

function Section({
  id,
  className = "",
  children,
}: {
  id?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={`mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-16 lg:px-8 ${className}`}>
      {children}
    </section>
  );
}

function InrAmount({
  amount,
  className = "",
  amountClassName = "font-mono",
}: {
  amount: string;
  className?: string;
  amountClassName?: string;
}) {
  return (
    <span className={className}>
      <span className="font-sans">{"\u20B9"}</span>
      <span className={amountClassName}>{amount}</span>
    </span>
  );
}

function InrFromFormat({
  value,
  className = "",
  amountClassName = "font-mono",
}: {
  value: number;
  className?: string;
  amountClassName?: string;
}) {
  const formatted = formatInrFull(value);
  return (
    <span className={className}>
      <span className="font-sans">{formatted.charAt(0)}</span>
      <span className={amountClassName}>{formatted.slice(1)}</span>
    </span>
  );
}

export default function LandingPage() {
  return (
    <>
      {/* Hero */}
      <Section className="pb-12 pt-10 sm:pb-16 sm:pt-14">
        <div className="text-center">
          <h1 className="mx-auto max-w-4xl text-[1.75rem] font-semibold leading-tight tracking-tight text-[#0A0A0A] sm:text-4xl sm:leading-tight lg:text-5xl">
            Find the ITC Your Clients Are Missing Every Month
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base leading-relaxed text-[#3A3A3A] sm:mt-5 sm:text-xl">
            GSTR-2B reconciliation for CA firms. Upload 2 files. Result in minutes.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-[var(--accent)] px-6 text-sm font-semibold text-white shadow-lg shadow-[var(--accent)]/25 transition hover:opacity-95 sm:w-auto"
            >
              Start Free — First 2 Runs Free
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-full border border-[#E5E5E5] bg-white px-6 text-sm font-semibold text-[#0A0A0A] transition hover:bg-[#F5F5F5] sm:w-auto"
            >
              See How It Works
            </a>
          </div>
          <p className="mt-6 px-1 text-sm leading-relaxed text-[#6B6B6B]">
            Plans from <InrAmount amount="399/month" amountClassName="" /> · No credit card to start
          </p>
          <div className="mx-auto mt-8 max-w-3xl rounded-xl border border-[#E5E5E5] bg-[#F5F5F5] px-4 py-4 text-sm text-[#3A3A3A] sm:px-6">
            <p className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-center sm:gap-x-6 sm:gap-y-2">
              <span>✓ No credit card required</span>
              <span className="hidden text-[#E5E5E5] sm:inline" aria-hidden>
                ·
              </span>
              <span>✓ Works with Tally, Busy &amp; Excel</span>
              <span className="hidden text-[#E5E5E5] sm:inline" aria-hidden>
                ·
              </span>
              <span>✓ First 2 runs completely free</span>
            </p>
          </div>
          <FeatureStatsStrip />
        </div>
      </Section>

      <SecurityTrustStrip />

      {/* Pain */}
      <Section className="border-t border-[#E5E5E5] bg-white py-10 sm:py-12">
        <h2 className="text-center text-2xl font-semibold text-[#0A0A0A] sm:text-3xl">Sound familiar?</h2>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {[
            "3–8 hours per client, per month on manual VLOOKUP reconciliation",
            "ITC mismatches discovered after filing deadline — penalties already hit",
            "30–50 clients. One wrong cell. No audit trail.",
          ].map((text) => (
            <div
              key={text}
              className="landing-card rounded-2xl border border-[#E5E5E5] bg-[#F5F5F5] p-5 text-[#3A3A3A] sm:p-6"
            >
              <p className="text-sm leading-relaxed sm:text-base">{text}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* How it works */}
      <Section id="how-it-works" className="scroll-mt-20 bg-white py-12 sm:scroll-mt-24 sm:py-20">
        <h2 className="text-center text-2xl font-semibold text-[#0A0A0A] sm:text-3xl">How ReconDesk Works</h2>
        <ul className="mt-12 grid gap-8 md:grid-cols-3">
          <li className="flex flex-col items-center text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--accent)]/15 text-[var(--accent)]">
              <Upload className="h-7 w-7" aria-hidden />
            </div>
            <h3 className="mt-4 text-base font-semibold text-[#0A0A0A]">1. Upload</h3>
            <p className="mt-2 text-sm leading-relaxed text-[#3A3A3A]">
              GSTR-2B JSON + Purchase Register (Tally, Busy, or any Excel — auto-detected)
            </p>
          </li>
          <li className="flex flex-col items-center text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--accent)]/15 text-[var(--accent)]">
              <GitMerge className="h-7 w-7" aria-hidden />
            </div>
            <h3 className="mt-4 text-base font-semibold text-[#0A0A0A]">2. Match</h3>
            <p className="mt-2 text-sm leading-relaxed text-[#3A3A3A]">
              ReconDesk matches 5,000+ invoices using 5-level matching.
            </p>
          </li>
          <li className="flex flex-col items-center text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--accent)]/15 text-[var(--accent)]">
              <ClipboardList className="h-7 w-7" aria-hidden />
            </div>
            <h3 className="mt-4 text-base font-semibold text-[#0A0A0A]">3. Decide</h3>
            <p className="mt-2 text-sm leading-relaxed text-[#3A3A3A]">
              Every mismatch explained: What is wrong, Why it happened, What to do next
            </p>
          </li>
        </ul>

        {/* Mock result card */}
        <div className="landing-card mx-auto mt-10 max-w-lg rounded-2xl border border-[#E5E5E5] bg-[#F5F5F5] p-5 text-center sm:mt-14 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-[#6B6B6B]">Sample run summary</p>
          <div className="mt-4 grid grid-cols-3 gap-3 sm:flex sm:flex-wrap sm:items-start sm:justify-center sm:gap-12">
            <div>
              <p className="text-xs text-[#6B6B6B]">ITC at Risk</p>
              <p className="mt-1 text-lg font-semibold text-amber-500">
                <InrFromFormat value={124500} />
              </p>
            </div>
            <div>
              <p className="text-xs text-[#6B6B6B]">Matched</p>
              <p className="mt-1 font-mono text-lg font-semibold text-emerald-600">847</p>
              <p className="text-[10px] text-[#6B6B6B]">invoices</p>
            </div>
            <div>
              <p className="text-xs text-[#6B6B6B]">Mismatches</p>
              <p className="mt-1 font-mono text-lg font-semibold text-[#0A0A0A]">23</p>
            </div>
          </div>
        </div>
      </Section>

      {/* FAQ */}
      <Section className="border-t border-[#E5E5E5] bg-white pt-8 pb-12 sm:pt-10 sm:pb-14">
        <h2 className="px-2 text-center text-2xl font-semibold text-[#0A0A0A] sm:px-0 sm:text-3xl">
          Questions CAs Ask Before Signing Up
        </h2>
        <FaqAccordion />
      </Section>

      {/* Pricing preview */}
      <Section className="border-t border-[#E5E5E5] bg-white py-12 sm:py-16">
        <div className="text-center">
          <h2 className="text-2xl font-semibold text-[#0A0A0A] sm:text-3xl">Simple, transparent pricing</h2>
          <p className="mt-3 text-[#6B6B6B]">Start free. Upgrade when you&apos;re ready.</p>
        </div>
        <div className="mx-auto mt-10 grid max-w-3xl gap-6 md:grid-cols-2">
          <div className="landing-card flex flex-col rounded-2xl border border-[#E5E5E5] bg-[#F5F5F5] p-5 sm:p-6">
            <h3 className="text-lg font-semibold text-[#0A0A0A]">Solo CA</h3>
            <p className="mt-2 text-3xl font-semibold text-[#0A0A0A]">
              <InrAmount amount="399" amountClassName="font-mono" />
              <span className="text-base font-normal text-[#6B6B6B]">/month</span>
            </p>
            <p className="mt-4 text-sm text-[#6B6B6B]">1 client GSTIN · 2 free runs to start</p>
            <Link
              href="/signup"
              className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-full border border-[#E5E5E5] bg-white text-sm font-semibold text-[#0A0A0A] transition hover:bg-[#EBEBEB]"
            >
              Start Free
            </Link>
          </div>
          <div className="landing-card relative flex flex-col rounded-2xl border-2 border-[var(--accent)] bg-[#F5F5F5] p-5 pt-7 sm:p-6 sm:pt-6">
            <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[var(--accent)] px-3 py-0.5 text-xs font-semibold text-white">
              Most Popular
            </span>
            <h3 className="text-lg font-semibold text-[#0A0A0A]">CA Firm</h3>
            <p className="mt-2 text-3xl font-semibold text-[#0A0A0A]">
              <InrAmount amount="9,999" amountClassName="font-mono" />
              <span className="text-base font-normal text-[#6B6B6B]">/month</span>
            </p>
            <p className="mt-4 text-sm text-[#6B6B6B]">35 runs/month · Team access included</p>
            <Link
              href="/pricing"
              className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--accent)] text-sm font-semibold text-white transition hover:opacity-95"
            >
              View All Plans
            </Link>
          </div>
        </div>
      </Section>

      {/* Final CTA */}
      <Section className="border-t border-[#E5E5E5] bg-white py-16 sm:py-20">
        <div className="landing-card mx-auto max-w-2xl rounded-3xl border border-[#E5E5E5] bg-[#F5F5F5] px-5 py-10 text-center sm:px-10 sm:py-12">
          <h2 className="text-2xl font-semibold text-[#0A0A0A] sm:text-3xl">Stop Losing ITC. Start Recovering It.</h2>
          <p className="mt-4 text-base leading-relaxed text-[#3A3A3A] sm:text-base">
            First 2 reconciliations free. No credit card required.
          </p>
          <Link
            href="/auth/signup"
            className="mt-8 inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-[var(--accent)] px-8 text-sm font-semibold text-white transition hover:opacity-95 sm:w-auto"
          >
            Get Started Free →
          </Link>
        </div>
      </Section>
    </>
  );
}
