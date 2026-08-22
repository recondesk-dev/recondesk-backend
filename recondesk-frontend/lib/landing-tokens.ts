/**
 * Design tokens for the 3D marketing landing page.
 * 
 * Palette logic: near-void background, paper-white foreground, one reserved
 * accent that never appears during the "pain" section — only from the
 * solution "turn" onward.
 */

export const LANDING = {
  colors: {
    void: '#0A0A0B',
    voidLifted: '#111114',
    paper: '#F5F5F3',
    gray: '#6B6B70',
    grayDim: '#3A3A3E',
    surface: '#2A2A2E',
    surfaceBorder: '#3A3A40',
    accent: '#34D399',
    accentGlow: 'rgba(52, 211, 153, 0.25)',
    accentDim: 'rgba(52, 211, 153, 0.08)',
    danger: '#EF4444',
    dangerDim: 'rgba(239, 68, 68, 0.3)',
  },

  fonts: {
    display: 'var(--font-general-sans), var(--font-plus-jakarta), system-ui, sans-serif',
    body: 'var(--font-plus-jakarta), system-ui, sans-serif',
    mono: 'var(--font-space-mono), ui-monospace, monospace',
  },

  motion: {
    painShakeIntensity: 0.002,
    turnDuration: 1.2,
  },

  /** Instance counts tiered by viewport width, not device sniffing. */
  performance: {
    mobile: { invoicePlanes: 12, particles: 80 },
    tablet: { invoicePlanes: 20, particles: 200 },
    desktop: { invoicePlanes: 30, particles: 400 },
  },

  /** Scroll progress breakpoints (0–1) for narrative sections. */
  scroll: {
    heroEnd: 0.12,
    painStart: 0.12,
    painEnd: 0.52,
    turnStart: 0.52,
    turnMid: 0.62,
    turnEnd: 0.72,
    solutionStart: 0.72,
    solutionEnd: 0.88,
    pricingStart: 0.88,
    pricingEnd: 0.95,
    closeStart: 0.95,
  },
} as const;

/** Helper: get performance tier from viewport width. */
export function getPerformanceTier(width: number) {
  if (width < 768) return LANDING.performance.mobile;
  if (width < 1280) return LANDING.performance.tablet;
  return LANDING.performance.desktop;
}

/** Helper: lerp between two values by a 0–1 factor. */
export function lerp(a: number, b: number, t: number) {
  return a + (b - a) * Math.max(0, Math.min(1, t));
}

/** Helper: remap a value from one range to a 0–1 factor. */
export function remap(value: number, inMin: number, inMax: number) {
  return Math.max(0, Math.min(1, (value - inMin) / (inMax - inMin)));
}
