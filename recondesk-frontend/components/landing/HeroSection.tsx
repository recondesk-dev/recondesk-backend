import React from "react";
import Link from "next/link";
import { Check, ChevronRight } from "lucide-react";
import { GlowArcVisual } from "./GlowArcVisual";
import { HeroProductPanel } from "./HeroProductPanel";

export function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-white pt-14 sm:pt-20 lg:pt-[84px] pb-16 sm:pb-24">
      {/* Centered Hero Content */}
      <div className="mx-auto max-w-5xl px-4 text-center sm:px-6 lg:px-8">
        
        {/* 1. Split Badge Pill (Orchestrated Step 1: 0ms delay) */}
        <div className="hero-animate-badge inline-flex items-center justify-center">
          <a
            href="#modules"
            className="group inline-flex items-center gap-2 rounded-full border border-[#E5E5E2] bg-white p-1 pl-1 pr-3 text-xs shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition hover:border-[#6B6B6B]/40"
          >
            {/* Left half: solid black rounded pill */}
            <span className="rounded-full bg-[#0A0A0A] px-2.5 py-0.5 font-semibold text-white">
              What&apos;s New
            </span>
            {/* Right half: plain text with chevron */}
            <span className="flex items-center gap-1 font-medium text-[#0A0A0A]">
              <span>GSTR-2B, 1, 3B &amp; IMS Support v2.4</span>
              <ChevronRight className="h-3.5 w-3.5 text-[#6B6B6B] transition-transform duration-150 group-hover:translate-x-0.5" />
            </span>
          </a>
        </div>

        {/* 2. Big Headline (Orchestrated Step 2: ~180ms delay) */}
        <h1 className="hero-animate-headline mt-7 text-4xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-6xl lg:text-[66px] lg:leading-[1.1]">
          Still Matching Invoices
          <br className="hidden sm:inline" />
          {" "}By <span className="text-[#7B5CFA]">Hand</span> in 2026?
        </h1>

        {/* 3. Short 2-line Subtext (Orchestrated Step 3: ~360ms delay) */}
        <p className="hero-animate-subtext mx-auto mt-5 max-w-[560px] text-base leading-relaxed text-[#6B6B6B] sm:text-lg">
          Upload your Tally, Busy, or Excel registers with GST portal files. Get audit-grade 5-level matching, Rule 37 reversal alerts, and decision-ready workpapers in under 60 seconds.
        </p>

        {/* 4. Two CTA Buttons Side by Side (Orchestrated Step 4: ~540ms delay) */}
        <div className="hero-animate-ctas mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
          {/* Solid brand purple button (#7B5CFA) */}
          <Link
            href="/auth/signup"
            className="inline-flex min-h-[46px] w-full items-center justify-center gap-1.5 rounded-[8px] bg-[#7B5CFA] px-6 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#6C4DE6] active:scale-[0.99] sm:w-auto"
          >
            <span>Start 60-Day Free Trial (2 GSTINs)</span>
            <span>→</span>
          </Link>

          {/* Purple-outline ghost button */}
          <a
            href="#modules"
            className="inline-flex min-h-[46px] w-full items-center justify-center gap-1.5 rounded-[8px] border border-[#7B5CFA] bg-white px-6 py-2.5 text-sm font-semibold text-[#7B5CFA] transition-colors hover:bg-[#7B5CFA]/5 active:scale-[0.99] sm:w-auto"
          >
            <span>Explore GSTR Modules</span>
            <span>↓</span>
          </a>
        </div>

        {/* Trust Points */}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs font-medium text-[#6B6B6B]">
          <span className="flex items-center gap-1.5">
            <Check className="h-3.5 w-3.5 text-emerald-600" /> No credit card required
          </span>
          <span className="hidden text-[#E5E5E2] sm:inline">•</span>
          <span className="flex items-center gap-1.5">
            <Check className="h-3.5 w-3.5 text-emerald-600" /> Works with Tally, Busy &amp; Excel
          </span>
          <span className="hidden text-[#E5E5E2] sm:inline">•</span>
          <span className="flex items-center gap-1.5">
            <Check className="h-3.5 w-3.5 text-emerald-600" /> 2 GSTINs free for 60 days (2 monthly cycles)
          </span>
        </div>
      </div>

      {/* Hero Visual Container: Glow Aura + Product Preview Panel */}
      <div className="relative mx-auto mt-12 sm:mt-16 lg:mt-20 max-w-7xl px-2 sm:px-6 lg:px-8">
        {/* Glow Aura Visual behind the panel */}
        <div className="hero-animate-glow">
          <GlowArcVisual />
        </div>

        {/* Product Preview Panel */}
        <div className="relative z-10 hero-animate-panel">
          <HeroProductPanel />
        </div>
      </div>
    </section>
  );
}
