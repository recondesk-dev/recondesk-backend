import Link from "next/link";

import { ExcelVsRecon } from "@/components/landing/ExcelVsRecon";
import { InvoiceJourney } from "@/components/landing/InvoiceJourney";
import { RiskCaseFile } from "@/components/landing/RiskCaseFile";
import { StatusTicker } from "@/components/landing/StatusTicker";
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
    <section id={id} className={`mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20 lg:px-8 ${className}`}>
      {children}
    </section>
  );
}

function SectionEyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[11px] tracking-[0.2em] text-[#6B7C8F]">{children}</p>
  );
}

export default function LandingPage() {
  return (
    <>
      {/* ── Section 1: Hero ── */}
      <Section className="pb-10 pt-12 sm:pb-12 sm:pt-16 lg:pt-20">
        <div className="max-w-3xl">
          <p className="font-mono text-[11px] tracking-[0.22em] text-[#0D4F3C]">RECONDESK</p>
          <h1 className="mt-5 font-display text-[2rem] font-semibold leading-[1.15] tracking-tight text-[#0B1D33] sm:text-5xl sm:leading-[1.12] lg:text-[3.25rem]">
            Every invoice needs a judgment call. Excel can&apos;t make it.
          </h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-[#3D4F63] sm:text-lg">
            Decision intelligence for GSTR-2B — claim, hold, or dispute — with the statute and next
            step attached.
          </p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[48px] items-center justify-center border border-[#0D4F3C] bg-[#0D4F3C] px-6 font-mono text-[13px] font-medium tracking-wide text-white transition hover:bg-[#0A3F30]"
            >
              Start Free — 2 Runs
            </Link>
            <a
              href="#invoice-journey"
              className="inline-flex min-h-[48px] items-center justify-center border border-[#0B1D33]/25 bg-transparent px-6 font-mono text-[13px] tracking-wide text-[#0B1D33] transition hover:border-[#0B1D33] hover:bg-white"
            >
              Follow one invoice →
            </a>
          </div>
          <p className="mt-5 font-mono text-[11px] text-[#6B7C8F]">
            From <span className="text-[#0B1D33]">₹499/mo</span> · No card to start · Tally, Busy &amp; Excel
          </p>
        </div>
      </Section>

      <StatusTicker />

      {/* ── Section 2: Invoice Journey ── */}
      <Section id="invoice-journey" className="scroll-mt-20 border-t border-[#D4D9E0]">
        <div className="mb-12 max-w-2xl sm:mb-16">
          <SectionEyebrow>THE INVOICE JOURNEY</SectionEyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold text-[#0B1D33] sm:text-3xl">
            One anonymized invoice. Raw row to stamped verdict.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-[#3D4F63] sm:text-base">
            Scroll the pipeline a CA actually runs — not a three-icon explainer.
          </p>
        </div>
        <InvoiceJourney />
      </Section>

      {/* ── Section 3: Excel vs ReconDesk ── */}
      <Section className="border-t border-[#D4D9E0] bg-white">
        <div className="mb-10 max-w-2xl sm:mb-12">
          <SectionEyebrow>SIDE BY SIDE</SectionEyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold text-[#0B1D33] sm:text-3xl">
            Same six rows. Different instrument.
          </h2>
        </div>
        <ExcelVsRecon />
      </Section>

      {/* ── Section 4: Risk case file ── */}
      <Section className="border-t border-[#D4D9E0]">
        <div className="mb-10 max-w-2xl sm:mb-12">
          <SectionEyebrow>RISK REGISTER</SectionEyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold text-[#0B1D33] sm:text-3xl">
            What the firm actually loses.
          </h2>
        </div>
        <RiskCaseFile />
      </Section>

      {/* FAQ — kept lean, restyled via landing-ledger scope */}
      <Section className="border-t border-[#D4D9E0] bg-white pt-12 pb-10 sm:pt-16 sm:pb-12">
        <h2 className="font-display text-2xl font-semibold text-[#0B1D33] sm:text-3xl">
          Questions before you file the next return
        </h2>
        <div className="ledger-faq mt-8">
          <FaqAccordion />
        </div>
      </Section>

      {/* Pricing strip */}
      <Section className="border-t border-[#D4D9E0] py-12 sm:py-16">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-md">
            <SectionEyebrow>PRICING</SectionEyebrow>
            <h2 className="mt-3 font-display text-2xl font-semibold text-[#0B1D33] sm:text-3xl">
              Firm-grade. Transparent.
            </h2>
            <p className="mt-2 text-sm text-[#3D4F63]">Start free. Upgrade when the practice needs it.</p>
          </div>
          <div className="grid w-full gap-4 sm:grid-cols-2 lg:max-w-xl">
            <div className="border border-[#0B1D33]/20 bg-white p-5">
              <p className="font-mono text-[11px] tracking-wider text-[#6B7C8F]">SOLO CA</p>
              <p className="mt-2 font-display text-3xl text-[#0B1D33]">
                <span className="font-sans text-2xl">₹</span>
                <span className="font-mono">499</span>
                <span className="font-mono text-sm font-normal text-[#6B7C8F]">/mo</span>
              </p>
              <p className="mt-2 font-mono text-[11px] text-[#6B7C8F]">1 GSTIN · 2 free runs</p>
              <Link
                href="/signup"
                className="mt-6 inline-flex min-h-[44px] w-full items-center justify-center border border-[#0B1D33]/25 font-mono text-[12px] tracking-wide text-[#0B1D33] transition hover:border-[#0B1D33] hover:bg-[#F2F3F5]"
              >
                Start Free
              </Link>
            </div>
            <div className="border border-[#0D4F3C] bg-[#0B1D33] p-5">
              <p className="font-mono text-[11px] tracking-wider text-[#1A6B52]">CA FIRM</p>
              <p className="mt-2 font-display text-3xl text-white">
                <span className="font-sans text-2xl">₹</span>
                <span className="font-mono">8,699</span>
                <span className="font-mono text-sm font-normal text-[#8A9AAB]">/mo</span>
              </p>
              <p className="mt-2 font-mono text-[11px] text-[#8A9AAB]">50 runs/mo · team access</p>
              <Link
                href="/pricing"
                className="mt-6 inline-flex min-h-[44px] w-full items-center justify-center bg-[#0D4F3C] font-mono text-[12px] tracking-wide text-white transition hover:bg-[#0A3F30]"
              >
                View All Plans
              </Link>
            </div>
          </div>
        </div>
      </Section>

      {/* Final CTA */}
      <section className="border-t border-[#0B1D33] bg-[#0B1D33]">
        <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-4 py-16 sm:px-6 sm:py-20 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="max-w-xl">
            <h2 className="font-display text-2xl font-semibold text-white sm:text-3xl">
              Stop guessing in cells. Start stamping decisions.
            </h2>
            <p className="mt-3 font-mono text-[12px] leading-relaxed text-[#8A9AAB]">
              First 2 reconciliations free. No credit card.
            </p>
          </div>
          <Link
            href="/auth/signup"
            className="inline-flex min-h-[48px] shrink-0 items-center justify-center border border-[#0D4F3C] bg-[#0D4F3C] px-8 font-mono text-[13px] font-medium tracking-wide text-white transition hover:bg-[#0A3F30]"
          >
            Get Started Free →
          </Link>
        </div>
      </section>
    </>
  );
}
