import Link from "next/link";

import { FaqAccordion } from "@/components/public/FaqAccordion";
import { FeatureStatsStrip } from "@/components/public/FeatureStatsStrip";
import { HowItWorksSteps } from "@/components/public/HowItWorksSteps";
import { LandingDashboardPreview } from "@/components/public/LandingDashboardPreview";
import { SecurityTrustStrip } from "@/components/public/SecurityTrustStrip";

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

export default function LandingPage() {
  return (
    <>
      {/* Hero */}
      <Section className="pb-12 pt-10 sm:pb-16 sm:pt-14">
        <div className="text-center">
          <h1 className="mx-auto max-w-4xl text-[1.75rem] font-semibold leading-tight tracking-tight text-[var(--ink)] sm:text-4xl sm:leading-tight lg:text-5xl">
            Find the ITC Your Clients Are Missing Every Month
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base leading-relaxed text-gray-600 sm:mt-5 sm:text-xl">
            GSTR-2B reconciliation for CA firms. Upload 2 files. Result in minutes.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-[var(--ink)] px-6 text-sm font-semibold text-white shadow-[var(--shadow-soft)] transition-opacity hover:opacity-90 sm:w-auto"
            >
              Start Free — First 2 Runs Free
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-white px-6 text-sm font-semibold text-[var(--ink)] shadow-[var(--shadow-soft)] transition hover:bg-[#F7F7F8] sm:w-auto"
            >
              See How It Works
            </a>
          </div>
          <p className="mt-6 px-1 text-sm leading-relaxed text-gray-500">
            No credit card to start
          </p>
          <div className="mx-auto mt-8 max-w-3xl rounded-[1.25rem] bg-white px-4 py-4 text-sm text-gray-600 shadow-[var(--shadow-soft)] sm:px-6">
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

      {/* Product showcase */}
      <Section className="py-12 sm:py-16">
        <LandingDashboardPreview />
      </Section>

      {/* Pain */}
      <Section className="py-10 sm:py-12">
        <h2 className="text-center text-2xl font-semibold text-[var(--ink)] sm:text-3xl">Sound familiar?</h2>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {[
            "3–8 hours per client, per month on manual VLOOKUP reconciliation",
            "ITC mismatches discovered after filing deadline — penalties already hit",
            "30–50 clients. One wrong cell. No audit trail.",
          ].map((text) => (
            <div
              key={text}
              className="landing-card rounded-[1.5rem] bg-white p-5 text-gray-600 sm:p-6"
            >
              <p className="text-sm leading-relaxed sm:text-base">{text}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* How it works */}
      <Section id="how-it-works" className="scroll-mt-20 py-12 sm:scroll-mt-24 sm:py-20">
        <HowItWorksSteps />
      </Section>

      {/* FAQ */}
      <Section className="pt-8 pb-12 sm:pt-10 sm:pb-14">
        <h2 className="px-2 text-center text-2xl font-semibold text-[var(--ink)] sm:px-0 sm:text-3xl">
          Questions CAs Ask Before Signing Up
        </h2>
        <FaqAccordion />
      </Section>

      {/* Pricing preview */}
      <Section className="py-12 sm:py-16">
        <div className="text-center">
          <h2 className="text-2xl font-semibold text-[var(--ink)] sm:text-3xl">Simple, transparent pricing</h2>
          <p className="mt-3 text-gray-500">Start free. Upgrade when you&apos;re ready.</p>
        </div>
        <div className="mx-auto mt-10 grid max-w-3xl gap-4 md:grid-cols-2">
          <div className="landing-card flex flex-col rounded-[1.5rem] bg-white p-5 sm:p-6">
            <h3 className="text-lg font-semibold text-[var(--ink)]">Solo CA</h3>
            <p className="mt-2 min-h-[2.25rem] text-3xl font-semibold text-[var(--ink)]" />
            <p className="mt-4 text-sm text-gray-500">1 client GSTIN · 2 free runs to start</p>
            <Link
              href="/auth/signup"
              className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-full bg-[#F5F5F6] text-sm font-semibold text-[var(--ink)] transition hover:bg-[#EBEBED]"
            >
              Start Free
            </Link>
          </div>
          <div className="landing-card relative flex flex-col rounded-[1.5rem] bg-white p-5 shadow-[var(--shadow-lift)] sm:p-6">
            <h3 className="text-lg font-semibold text-[var(--ink)]">CA Firm</h3>
            <p className="mt-2 min-h-[2.25rem] text-3xl font-semibold text-[var(--ink)]" />
            <p className="mt-4 text-sm text-gray-500">50 runs/month · Team access included</p>
            <Link
              href="/pricing"
              className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              View All Plans
            </Link>
          </div>
        </div>
      </Section>

      {/* Final CTA */}
      <Section className="py-16 sm:py-20">
        <div className="landing-card mx-auto max-w-2xl rounded-[1.75rem] bg-white px-5 py-10 text-center sm:px-10 sm:py-12">
          <h2 className="text-2xl font-semibold text-[var(--ink)] sm:text-3xl">Stop Losing ITC. Start Recovering It.</h2>
          <p className="mt-4 text-base leading-relaxed text-gray-600 sm:text-base">
            First 2 reconciliations free. No credit card required.
          </p>
          <Link
            href="/auth/signup"
            className="mt-8 inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-[var(--ink)] px-8 text-sm font-semibold text-white transition-opacity hover:opacity-90 sm:w-auto"
          >
            Get Started Free →
          </Link>
        </div>
      </Section>
    </>
  );
}
