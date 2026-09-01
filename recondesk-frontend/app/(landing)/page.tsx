import Link from "next/link";
import { HeroSection } from "@/components/landing/HeroSection";
import { GstrModulesGrid } from "@/components/landing/GstrModulesGrid";
import { FeatureStatsStrip } from "@/components/public/FeatureStatsStrip";
import { SecurityTrustStrip } from "@/components/public/SecurityTrustStrip";
import { HowItWorksSteps } from "@/components/public/HowItWorksSteps";
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
      {/* 1. Hero Section with Glow Arc and Browser Chrome Panel */}
      <HeroSection />

      {/* 2. Supported GSTR Modules Grid (2B, 1, 3B, 9C) */}
      <GstrModulesGrid />

      {/* 3. Feature Stats: What's Under The Hood */}
      <FeatureStatsStrip />

      {/* 4. Security & Trust Strip */}
      <SecurityTrustStrip />

      {/* 5. How It Works (Upload -> Match -> Decide) */}
      <Section id="how-it-works" className="scroll-mt-20 py-12 sm:scroll-mt-24 sm:py-20 border-t border-[#E5E5E2]">
        <div className="text-center mb-10">
          <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
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

      {/* 6. Simple, Transparent Pricing */}
      <Section id="pricing" className="py-12 sm:py-20 border-t border-[#E5E5E2]">
        <div className="text-center mb-12">
          <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
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

      {/* 7. FAQ Accordion */}
      <Section id="faq" className="pt-8 pb-16 sm:pt-10 sm:pb-20 border-t border-[#E5E5E2]">
        <div className="text-center mb-10">
          <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
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
          {/* Subtle brand purple accent glow in background */}
          <div
            className="absolute -top-24 left-1/2 -translate-x-1/2 h-48 w-96 rounded-full bg-[#7B5CFA]/10 blur-3xl pointer-events-none"
            aria-hidden="true"
          />

          <h2 className="relative text-2xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
            Stop Losing ITC. Start Recovering It.
          </h2>
          <p className="relative mx-auto mt-4 max-w-xl text-sm leading-relaxed text-[#6B6B6B] sm:text-base">
            One GSTIN 100% free forever. Upload your GSTR portal files and purchase register now to see results in 60 seconds.
          </p>
          
          <div className="relative mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-[8px] bg-[#7B5CFA] px-8 text-sm font-semibold text-white transition-colors hover:bg-[#6C4DE6] active:scale-[0.99] sm:w-auto"
            >
              <span>Start Free — One GSTIN, Forever</span>
              <span>→</span>
            </Link>
            <a
              href="#modules"
              className="inline-flex min-h-[48px] w-full items-center justify-center gap-1.5 rounded-[8px] border border-[#7B5CFA] bg-white px-6 text-sm font-semibold text-[#7B5CFA] transition-colors hover:bg-[#7B5CFA]/5 active:scale-[0.99] sm:w-auto"
            >
              <span>Explore GSTR Modules</span>
              <span>↓</span>
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
