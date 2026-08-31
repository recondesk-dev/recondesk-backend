"use client";

import { motion } from "framer-motion";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";

interface Props {
  scrollProgress: number;
}

const TESTIMONIALS = [
  {
    name: "CA Rajesh Mehta",
    firm: "Mehta & Associates, Mumbai",
    quote:
      "What used to take us 3–4 hours per client now takes under 15 minutes. ReconDesk caught mismatches we'd been missing for months.",
    before: { metric: "4 hrs", label: "per client" },
    after: { metric: "12 min", label: "per client" },
  },
  {
    name: "CA Priya Sharma",
    firm: "Sharma Tax Consultants, Pune",
    quote:
      "I was skeptical about any tool claiming to automate reconciliation. The accuracy is genuinely impressive — I trust it more than my own VLOOKUPs now.",
    before: { metric: "₹3.2L", label: "ITC unclaimed" },
    after: { metric: "₹0", label: "unclaimed" },
  },
  {
    name: "CA Vikram Gupta",
    firm: "VG & Co., Delhi",
    quote:
      "Onboarded 8 new clients last quarter. Previously that would have broken us. With ReconDesk, we scaled without hiring anyone.",
    before: { metric: "22 clients", label: "max capacity" },
    after: { metric: "47 clients", label: "managed today" },
  },
];

/**
 * Chapter 07 — Proof
 * Three testimonial cards + before/after stat pairs, stagger-revealed on scroll.
 */
export function Chapter07_Proof({ scrollProgress }: Props) {
  const visibleCards = Math.min(
    TESTIMONIALS.length,
    Math.floor(((scrollProgress - 0.1) / 0.7) * TESTIMONIALS.length + 0.5)
  );

  return (
    <StickyScene background="#ffffff">
      <div className="relative h-full w-full flex flex-col justify-center px-6 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl py-10">
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-[#aaa]">
            Chapter 07 — Proof
          </p>
          <h2 className="mt-3 text-2xl font-semibold text-[#0a0a0a] sm:text-3xl">
            CAs who switched. Results they saw.
          </h2>

          <div className="mt-8 grid gap-6 sm:grid-cols-3">
            {TESTIMONIALS.map((t, i) => (
              <motion.div
                key={i}
                animate={{
                  opacity: i < visibleCards ? 1 : 0,
                  y: i < visibleCards ? 0 : 32,
                }}
                transition={{ duration: 0.8, ease: "easeOut", delay: i * 0.15 }}
                className="flex flex-col rounded-2xl border border-[#e5e5e5] bg-white p-6 shadow-sm"
              >
                {/* Quote */}
                <p className="flex-1 text-sm leading-relaxed text-[#444]">
                  &ldquo;{t.quote}&rdquo;
                </p>

                {/* Attribution */}
                <div className="mt-4 border-t border-[#f0f0f0] pt-4">
                  <p className="font-semibold text-[#0a0a0a] text-sm">{t.name}</p>
                  <p className="text-xs text-[#aaa]">{t.firm}</p>
                </div>

                {/* Before / after */}
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-red-50 px-3 py-2 text-center">
                    <p className="font-mono text-xs text-red-400 uppercase tracking-wider">Before</p>
                    <p className="mt-1 font-mono text-xl font-bold text-red-600">
                      {t.before.metric}
                    </p>
                    <p className="font-mono text-[10px] text-red-400">{t.before.label}</p>
                  </div>
                  <div className="rounded-lg bg-green-50 px-3 py-2 text-center">
                    <p className="font-mono text-xs text-green-500 uppercase tracking-wider">After</p>
                    <p className="mt-1 font-mono text-xl font-bold text-green-700">
                      {t.after.metric}
                    </p>
                    <p className="font-mono text-[10px] text-green-600">{t.after.label}</p>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Aggregate stat */}
          <motion.div
            className="mt-10 grid grid-cols-3 gap-4 rounded-2xl border border-[#e5e5e5] bg-[#fafafa] p-6"
            animate={{ opacity: visibleCards >= 3 ? 1 : 0, y: visibleCards >= 3 ? 0 : 20 }}
            transition={{ duration: 0.8 }}
          >
            {[
              { stat: "94%", label: "reduction in reconciliation time" },
              { stat: "₹2.1Cr", label: "ITC recovered across clients" },
              { stat: "0", label: "penalty notices after switching" },
            ].map((s, i) => (
              <div key={i} className="text-center">
                <p className="font-mono text-3xl font-bold text-green-700">{s.stat}</p>
                <p className="mt-1 text-xs text-[#888]">{s.label}</p>
              </div>
            ))}
          </motion.div>
        </div>
      </div>
    </StickyScene>
  );
}
