import Link from "next/link";

import { DecisionLayerSection } from "@/components/public/DecisionLayerSection";
import { FaqAccordion } from "@/components/public/FaqAccordion";
import { HowItWorksSteps } from "@/components/public/HowItWorksSteps";
import { LandingDashboardPreview } from "@/components/public/LandingDashboardPreview";
import { LandingHero } from "@/components/public/LandingHero";
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
      <LandingHero />

      <SecurityTrustStrip />

      <DecisionLayerSection />

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
          <div
            className="landing-card min-h-[220px] rounded-[1.5rem] bg-white p-5 sm:p-6"
            aria-hidden
          />
          <div
            className="landing-card min-h-[220px] rounded-[1.5rem] bg-white p-5 shadow-[var(--shadow-lift)] sm:p-6"
            aria-hidden
          />
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
