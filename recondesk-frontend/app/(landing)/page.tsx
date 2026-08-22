'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';

import LandingNav from '@/components/landing3d/LandingNav';
import HeroSection from '@/components/landing3d/sections/HeroSection';
import PainSection from '@/components/landing3d/sections/PainSection';
import TurnSection from '@/components/landing3d/sections/TurnSection';
import SolutionSection from '@/components/landing3d/sections/SolutionSection';
import ProofSection from '@/components/landing3d/sections/ProofSection';
import PricingSection from '@/components/landing3d/sections/PricingSection';
import CloseSection from '@/components/landing3d/sections/CloseSection';
import ReducedMotionFallback from '@/components/landing3d/ReducedMotionFallback';

// Dynamic import: 3D scene is client-only, no SSR
const LandingScene = dynamic(
  () => import('@/components/landing3d/LandingScene'),
  { ssr: false },
);

/**
 * ReconDesk 3D Marketing Landing Page
 *
 * A scroll-driven, emotionally-arc'd single page:
 *   Hero → Pain (chaos builds) → Turn (chaos → order) →
 *   Solution (calm, concrete) → Proof → Pricing → Close
 *
 * The 3D canvas is persistent and full-bleed behind the content.
 * All animation is driven by a single scroll progress value.
 */
export default function LandingPage() {
  const [isReducedMotion, setIsReducedMotion] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setIsReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsReducedMotion(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return (
    <>
      {/* Fixed navigation */}
      <LandingNav />

      {/* 3D canvas — fixed, full-bleed, z-0 */}
      {isReducedMotion ? <ReducedMotionFallback /> : <LandingScene />}

      {/* 2D content — relative, z-10, scrolls over/through 3D */}
      <div className="relative z-10">
        {/* Hero — the thesis */}
        <HeroSection />

        {/* The pain, scene by scene */}
        <PainSection />

        {/* The turn — chaos → order */}
        <TurnSection />

        {/* Solution — the decision layer, made concrete */}
        <div id="how-it-works">
          <SolutionSection />
        </div>

        {/* Proof / scale */}
        <ProofSection />

        {/* Pricing — 3D disappears, calm 2D */}
        <PricingSection />

        {/* Close — visual bookend + CTA */}
        <CloseSection />
      </div>
    </>
  );
}
