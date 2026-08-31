/**
 * lib/gsap.ts
 * Central GSAP initializer — registers ScrollTrigger once, client-side only.
 * Import this (not "gsap" directly) in any scrollstory component.
 */

// This module is intentionally client-only.
// Next.js will tree-shake it from SSR bundles when used inside 'use client' components.

import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger);
}

export { gsap, ScrollTrigger };
export default gsap;
