'use client';

import { useRef, useEffect, useState, useCallback } from 'react';

/**
 * Single source of truth for scroll-driven animation progress.
 * Returns a normalized 0–1 value representing how far the user
 * has scrolled through the landing page.
 *
 * All 3D animation, camera movement, and 2D content reveals
 * derive from this one value — no independent timers.
 */
export function useScrollProgress() {
  const [progress, setProgress] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);
  const rafId = useRef<number>(0);

  const updateProgress = useCallback(() => {
    const scrollY = window.scrollY;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    const p = docHeight > 0 ? Math.min(1, Math.max(0, scrollY / docHeight)) : 0;
    setProgress(p);
  }, []);

  useEffect(() => {
    // Check reduced-motion preference
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mq.matches);
    const handleMqChange = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener('change', handleMqChange);

    // Scroll listener with rAF throttle
    let ticking = false;
    const handleScroll = () => {
      if (!ticking) {
        ticking = true;
        rafId.current = requestAnimationFrame(() => {
          updateProgress();
          ticking = false;
        });
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    updateProgress(); // initial

    return () => {
      window.removeEventListener('scroll', handleScroll);
      mq.removeEventListener('change', handleMqChange);
      if (rafId.current) cancelAnimationFrame(rafId.current);
    };
  }, [updateProgress]);

  return { progress, reducedMotion };
}
