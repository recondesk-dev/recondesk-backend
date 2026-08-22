'use client';

import { LANDING } from '@/lib/landing-tokens';

/**
 * Static fallback for prefers-reduced-motion: reduce.
 *
 * Instead of the animated 3D canvas, renders a clean static
 * visual — a stylized grid pattern suggesting the resolved
 * reconciliation state, using pure CSS.
 */
export default function ReducedMotionFallback() {
  return (
    <div
      className="fixed inset-0 z-0 overflow-hidden"
      style={{ pointerEvents: 'none' }}
      aria-hidden="true"
    >
      {/* Subtle grid pattern suggesting resolved invoices */}
      <div className="absolute inset-0 flex items-center justify-center opacity-[0.06]">
        <div className="grid grid-cols-8 gap-2">
          {Array.from({ length: 32 }).map((_, i) => (
            <div
              key={i}
              className="rounded-sm"
              style={{
                width: '60px',
                height: '38px',
                backgroundColor:
                  i % 5 === 0
                    ? LANDING.colors.surface
                    : LANDING.colors.accent,
              }}
            />
          ))}
        </div>
      </div>

      {/* Soft radial gradient for depth */}
      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(ellipse at 50% 40%, ${LANDING.colors.void}00 0%, ${LANDING.colors.void} 70%)`,
        }}
      />
    </div>
  );
}
