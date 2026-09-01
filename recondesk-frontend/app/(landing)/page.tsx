import Link from "next/link";
import { HeroSection } from "@/components/landing/HeroSection";
import { FeatureStatsStrip } from "@/components/public/FeatureStatsStrip";
import { SecurityTrustStrip } from "@/components/public/SecurityTrustStrip";
import { HowItWorksSteps } from "@/components/public/HowItWorksSteps";
import { LandingDashboardPreview } from "@/components/public/LandingDashboardPreview";
import { PricingGrid } from "@/components/billing/PricingGrid";
import { FaqAccordion } from "@/components/public/FaqAccordion";

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
    <section id={id} className={`mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8 ${className}`}>
      {children}
    </section>
  );
}

export default function LandingPage() {
  return (
    <div className="bg-white text-[#0A0A0A]">
      {/* 1. Hero Section with Staggered Load Entrance, Glow Arc, and Browser Chrome Panel */}
      <HeroSection />

      {/* 2. Feature Stats: What's Under The Hood */}
      <FeatureStatsStrip />

      {/* 3. Security & Trust Strip */}
      <SecurityTrustStrip />

      {/* 4. Pain Points: Sound familiar? */}
      <Section className="py-12 sm:py-16">
        <div className="text-center">
          <p className="text-xs font-bold uppercase tracking-widest text-[#F97316]">
            The CA Dilemma
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-[#0A0A0A] sm:text-3xl">
            Sound familiar?
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-[#6B6B6B]">
            Manual reconciliation drains hundreds of billable hours every month and exposes your clients to notices.
          </p>
        </div>

        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {[
            {
              title: "3–8 hours per client",
              desc: "Spent on manual VLOOKUP spreadsheets trying to reconcile mismatched invoice numbers and formats.",
            },
            {
              title: "ITC mismatches discovered late",
              desc: "Found after the filing deadline — interest and Section 50 penalties have already started accumulating.",
            },
            {
              title: "30–50 clients. One wrong cell.",
              desc: "No audit trail, no rule documentation, and no automated follow-up with defaulting suppliers.",
            },
          ].map((item) => (
            <div
              key={item.title}
              className="rounded-[10px] border border-[#E5E5E2] bg-white p-6 transition-all hover:border-[#6B6B6B]/40"
            >
              <div className="h-1 w-8 rounded-full bg-[#F97316] mb-4" />
              <h3 className="text-base font-bold text-[#0A0A0A]">{item.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-[#6B6B6B]">{item.desc}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* 5. How It Works */}
      <Section id="how-it-works" className="scroll-mt-20 py-12 sm:scroll-mt-24 sm:py-20">
        <div className="text-center mb-10">
          <p className="text-xs font-bold uppercase tracking-widest text-[#F97316]">
            Streamlined Workflow
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-[#0A0A0A] sm:text-3xl">
            How ReconDesk Works
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-[#6B6B6B]">
            From raw spreadsheet uploads to decision-ready audit files in 3 simple steps.
          </p>
        </div>
        <HowItWorksSteps />
      </Section>

      {/* 6. Product Showcase / Interactive Deep Dive */}
      <Section id="features" className="py-12 sm:py-16">
        <div className="text-center mb-10">
          <p className="text-xs font-bold uppercase tracking-widest text-[#F97316]">
            Interactive Showcase
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-[#0A0A0A] sm:text-3xl">
            Decision-Ready Intelligence
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-[#6B6B6B]">
            Explore each layer of the reconciliation engine built specifically for Indian GST workflows.
          </p>
        </div>
        <LandingDashboardPreview />
      </Section>

      {/* 7. Simple, Transparent Pricing */}
      <Section id="pricing" className="py-12 sm:py-20 border-t border-[#E5E5E2]">
        <div className="text-center mb-12">
          <p className="text-xs font-bold uppercase tracking-widest text-[#F97316]">
            Transparent Plans
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-[#0A0A0A] sm:text-3xl">
            Simple, Transparent Pricing
          </h2>
          <p className="mt-3 text-sm text-[#6B6B6B]">
            Start free. Upgrade when you&apos;re ready for your firm. Zero feature gating.
          </p>
        </div>
        <PricingGrid />
      </Section>

      {/* 8. FAQ Accordion */}
      <Section id="faq" className="pt-8 pb-16 sm:pt-10 sm:pb-20 border-t border-[#E5E5E2]">
        <div className="text-center mb-10">
          <p className="text-xs font-bold uppercase tracking-widest text-[#F97316]">
            Got Questions?
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-[#0A0A0A] sm:text-3xl">
            Questions CAs Ask Before Signing Up
          </h2>
        </div>
        <FaqAccordion />
      </Section>

      {/* 9. Final High-Converting CTA Banner */}
      <Section className="py-16 sm:py-24">
        <div className="relative mx-auto max-w-4xl overflow-hidden rounded-[14px] border border-[#E5E5E2] bg-white p-8 text-center sm:p-14 shadow-sm">
          {/* Subtle warm accent glow in background */}
          <div
            className="absolute -top-24 left-1/2 -translate-x-1/2 h-48 w-96 rounded-full bg-[#F97316]/10 blur-3xl pointer-events-none"
            aria-hidden="true"
          />

          <h2 className="relative text-2xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
            Stop Losing ITC. Start Recovering It.
          </h2>
          <p className="relative mx-auto mt-4 max-w-xl text-sm leading-relaxed text-[#6B6B6B] sm:text-base">
            First 2 reconciliations free. Upload your GSTR-2B and purchase register now to see results in 60 seconds.
          </p>
          
          <div className="relative mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-[8px] bg-[#0A0A0A] px-8 text-sm font-semibold text-white transition-opacity hover:opacity-90 active:scale-[0.99] sm:w-auto"
            >
              <span>Get Started Free</span>
              <span>→</span>
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-[8px] border border-[#E5E5E2] bg-white px-6 text-sm font-semibold text-[#0A0A0A] transition hover:bg-[#F5F5F3] sm:w-auto"
            >
              See How It Works
            </a>
          </div>

          <p className="relative mt-5 text-xs text-[#6B6B6B]">
            No credit card required • Works with Tally, Busy &amp; Excel
          </p>
        </div>
      </Section>
    </div>
  );
}
