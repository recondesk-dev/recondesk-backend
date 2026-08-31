"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";

interface Props {
  scrollProgress: number;
}

const BEFORE_ITEMS = [
  "VLOOKUP on 400+ rows",
  "Manual column cleanup",
  "GST portal timeouts",
  "3–4 hrs per client",
  "Missed ITC claims",
  "Penalty risk",
];

const AFTER_ITEMS = [
  "Automatic matching",
  "Structured import",
  "Direct API fetch",
  "12 min per client",
  "Full ITC recovery",
  "Audit-ready report",
];

/**
 * Chapter 08 — Transformation
 * Split screen before/after. CTA button and secondary link.
 */
export function Chapter08_Transformation({ scrollProgress }: Props) {
  const showSplit = scrollProgress > 0.05;
  const visibleItems = Math.min(
    BEFORE_ITEMS.length,
    Math.floor(((scrollProgress - 0.1) / 0.5) * BEFORE_ITEMS.length)
  );
  const showCTA = scrollProgress > 0.65;

  return (
    <StickyScene background="#ffffff">
      <div className="relative h-full w-full flex flex-col justify-center overflow-hidden">

        <motion.div
          className="grid h-full grid-cols-2"
          animate={{ opacity: showSplit ? 1 : 0 }}
          transition={{ duration: 0.8 }}
        >
          {/* LEFT — Before (dark chaos) */}
          <div className="flex flex-col justify-center bg-[#0a0a0a] px-8 py-12 lg:px-12">
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-[#555]">
              Before ReconDesk
            </p>
            <h3 className="mt-3 text-xl font-semibold text-[#f0f0f0] sm:text-2xl">
              Manual. Slow. Risky.
            </h3>
            <ul className="mt-6 space-y-3">
              {BEFORE_ITEMS.map((item, i) => (
                <motion.li
                  key={i}
                  animate={{ opacity: i < visibleItems ? 1 : 0.1, x: i < visibleItems ? 0 : -10 }}
                  transition={{ duration: 0.4 }}
                  className="flex items-center gap-3 font-mono text-sm text-[#888]"
                >
                  <span className="flex-shrink-0 text-red-500">✗</span>
                  {item}
                </motion.li>
              ))}
            </ul>
          </div>

          {/* RIGHT — After (clean white) */}
          <div className="flex flex-col justify-center bg-[#f9fafb] px-8 py-12 lg:px-12">
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-[#aaa]">
              After ReconDesk
            </p>
            <h3 className="mt-3 text-xl font-semibold text-[#0a0a0a] sm:text-2xl">
              Automated. Fast. Certain.
            </h3>
            <ul className="mt-6 space-y-3">
              {AFTER_ITEMS.map((item, i) => (
                <motion.li
                  key={i}
                  animate={{ opacity: i < visibleItems ? 1 : 0.1, x: i < visibleItems ? 0 : 10 }}
                  transition={{ duration: 0.4, delay: i * 0.08 }}
                  className="flex items-center gap-3 font-mono text-sm text-[#333]"
                >
                  <span className="flex-shrink-0 text-green-600">✓</span>
                  {item}
                </motion.li>
              ))}
            </ul>
          </div>
        </motion.div>

        {/* CTA overlay */}
        <motion.div
          className="absolute bottom-0 left-0 right-0 flex flex-col items-center gap-4 bg-gradient-to-t from-white via-white/95 to-transparent px-6 pb-12 pt-16"
          animate={{ opacity: showCTA ? 1 : 0, y: showCTA ? 0 : 20 }}
          transition={{ duration: 0.8 }}
        >
          <h2 className="text-center text-2xl font-semibold text-[#0a0a0a] sm:text-3xl">
            Ready to reclaim your time?
          </h2>
          <p className="text-center text-sm text-[#888]">
            First 2 reconciliations free. No credit card required.
          </p>
          <div className="flex flex-col items-center gap-3 sm:flex-row">
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[52px] items-center justify-center rounded-full bg-[#16a34a] px-8 text-sm font-semibold text-white shadow-lg transition-all hover:bg-[#15803d] hover:shadow-xl"
            >
              See it with your data →
            </Link>
            <a
              href="#chapter-06"
              className="inline-flex min-h-[52px] items-center justify-center rounded-full border border-[#e5e5e5] bg-white px-8 text-sm font-semibold text-[#0a0a0a] transition-all hover:bg-[#f5f5f5]"
            >
              How it works
            </a>
          </div>
        </motion.div>
      </div>
    </StickyScene>
  );
}
