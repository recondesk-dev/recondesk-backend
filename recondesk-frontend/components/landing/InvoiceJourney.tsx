"use client";

import { motion, useReducedMotion } from "framer-motion";

const MATCH_LEVELS = [
  { level: "L1", label: "GSTIN + Inv# + Amount", hit: true },
  { level: "L2", label: "GSTIN + Inv# fuzzy", hit: false },
  { level: "L3", label: "GSTIN + Amount + Date", hit: false },
  { level: "L4", label: "Vendor + Amount window", hit: false },
  { level: "L5", label: "Fuzzy composite", hit: false },
] as const;

function JourneyStep({
  children,
  delay = 0,
}: {
  children: React.ReactNode;
  delay?: number;
}) {
  const reduce = useReducedMotion();

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 28 }}
      whileInView={reduce ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-12% 0px -8% 0px", amount: 0.35 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1], delay }}
    >
      {children}
    </motion.div>
  );
}

function StepLabel({ n, title }: { n: string; title: string }) {
  return (
    <div className="mb-4 flex items-baseline gap-3">
      <span className="font-mono text-[11px] tracking-[0.14em] text-[#6B7C8F]">{n}</span>
      <h3 className="font-display text-lg text-[#0B1D33] sm:text-xl">{title}</h3>
    </div>
  );
}

export function InvoiceJourney() {
  const reduce = useReducedMotion();

  return (
    <div className="relative mx-auto max-w-2xl">
      {/* Vertical rule */}
      <div
        className="absolute bottom-8 left-[11px] top-8 w-px bg-[#D4D9E0] sm:left-[15px]"
        aria-hidden
      />

      <div className="space-y-14 sm:space-y-20">
        {/* Step 1 — Raw GSTR-2B */}
        <JourneyStep>
          <div className="relative pl-8 sm:pl-10">
            <span
              className="absolute left-0 top-1.5 flex h-[23px] w-[23px] items-center justify-center border border-[#0B1D33] bg-[#F2F3F5] font-mono text-[10px] text-[#0B1D33] sm:h-8 sm:w-8 sm:text-[11px]"
              aria-hidden
            >
              01
            </span>
            <StepLabel n="STEP 01" title="Raw row from GSTR-2B" />
            <div className="overflow-x-auto border border-[#0B1D33]/20 bg-white">
              <table className="w-full min-w-[520px] border-collapse font-mono text-[11px] sm:text-xs">
                <thead>
                  <tr className="border-b border-[#D4D9E0] bg-[#0B1D33] text-left text-[10px] tracking-wider text-[#A8B5C4]">
                    <th className="px-3 py-2 font-medium">GSTIN</th>
                    <th className="px-3 py-2 font-medium">INV NO</th>
                    <th className="px-3 py-2 font-medium">DATE</th>
                    <th className="px-3 py-2 font-medium text-right">TAXABLE</th>
                    <th className="px-3 py-2 font-medium text-right">IGST</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="bg-[#FAFBFC]">
                    <td className="px-3 py-3 text-[#0B1D33]">27AB•••1Z5</td>
                    <td className="px-3 py-3 text-[#0B1D33]">INV/24-25/1847</td>
                    <td className="px-3 py-3 text-[#4A5C6E]">15-05-2026</td>
                    <td className="px-3 py-3 text-right tabular-nums text-[#0B1D33]">
                      <span className="font-sans">₹</span>2,48,000.00
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-[#0B1D33]">
                      <span className="font-sans">₹</span>44,640.00
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="mt-3 font-mono text-[11px] text-[#6B7C8F]">
              Source: GSTR-2B · May 2026 · 1 of 3,842 rows
            </p>
          </div>
        </JourneyStep>

        {/* Step 2 — Matching */}
        <JourneyStep delay={0.05}>
          <div className="relative pl-8 sm:pl-10">
            <span
              className="absolute left-0 top-1.5 flex h-[23px] w-[23px] items-center justify-center border border-[#0B1D33] bg-[#F2F3F5] font-mono text-[10px] text-[#0B1D33] sm:h-8 sm:w-8 sm:text-[11px]"
              aria-hidden
            >
              02
            </span>
            <StepLabel n="STEP 02" title="Matching attempt — L1 through L5" />
            <div className="border border-[#0B1D33]/20 bg-white p-4 sm:p-5">
              <ul className="space-y-2.5">
                {MATCH_LEVELS.map((m, i) => (
                  <motion.li
                    key={m.level}
                    initial={reduce ? false : { opacity: 0.35 }}
                    whileInView={reduce ? undefined : { opacity: 1 }}
                    viewport={{ once: true, amount: 0.8 }}
                    transition={{ delay: 0.08 * i, duration: 0.35 }}
                    className={`flex items-center justify-between gap-3 border-b border-[#EEF1F4] pb-2.5 last:border-0 last:pb-0 ${
                      m.hit ? "text-[#0B1D33]" : "text-[#9AA6B4]"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={`font-mono text-[11px] font-medium tracking-wide ${
                          m.hit ? "text-[#1A6B52]" : "text-[#9AA6B4]"
                        }`}
                      >
                        {m.level}
                      </span>
                      <span className="font-mono text-[11px] sm:text-xs">{m.label}</span>
                    </div>
                    <span className="font-mono text-[10px] tracking-wider">
                      {m.hit ? "HIT" : "—"}
                    </span>
                  </motion.li>
                ))}
              </ul>
              <p className="mt-4 border-t border-[#EEF1F4] pt-3 font-mono text-[11px] text-[#1A6B52]">
                Resolved at L1 · exact GSTIN + invoice number + amount
              </p>
            </div>
          </div>
        </JourneyStep>

        {/* Step 3 — Decision stamp */}
        <JourneyStep delay={0.08}>
          <div className="relative pl-8 sm:pl-10">
            <span
              className="absolute left-0 top-1.5 flex h-[23px] w-[23px] items-center justify-center border border-[#0B1D33] bg-[#F2F3F5] font-mono text-[10px] text-[#0B1D33] sm:h-8 sm:w-8 sm:text-[11px]"
              aria-hidden
            >
              03
            </span>
            <StepLabel n="STEP 03" title="Decision layer verdict" />

            {/* Stamp — money shot */}
            <div className="relative mb-8 flex justify-center py-6 sm:py-8">
              <motion.div
                initial={reduce ? false : { opacity: 0, scale: 0.92, rotate: -8 }}
                whileInView={reduce ? undefined : { opacity: 1, scale: 1, rotate: -2.5 }}
                viewport={{ once: true, amount: 0.6 }}
                transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1], delay: 0.1 }}
                className="ledger-stamp relative select-none px-6 py-5 sm:px-10 sm:py-6"
                aria-label="Verdict: Matched — Rule 37 clear"
              >
                <div className="ledger-stamp-inner border-[3px] border-double border-[#1A6B52] px-5 py-4 text-center sm:px-8 sm:py-5">
                  <p className="font-display text-xl font-semibold tracking-wide text-[#1A6B52] sm:text-2xl">
                    MATCHED
                  </p>
                  <p className="mt-1 font-mono text-[11px] tracking-[0.18em] text-[#1A6B52]/80 sm:text-xs">
                    RULE 37 CLEAR
                  </p>
                </div>
              </motion.div>
            </div>

            {/* WHAT / WHY / NEXT */}
            <div className="grid gap-0 border border-[#0B1D33]/20 bg-white sm:grid-cols-3">
              {[
                {
                  label: "WHAT",
                  body: "Books invoice INV/24-25/1847 aligns with GSTR-2B entry. ITC of ₹44,640 is eligible.",
                },
                {
                  label: "WHY",
                  body: "L1 exact match. Supplier filed on time. No Sec 17(5) block. Rule 37 payment condition satisfied.",
                },
                {
                  label: "NEXT",
                  body: "Claim in GSTR-3B Table 4(A)(5). No hold. No vendor follow-up required.",
                },
              ].map((col) => (
                <div
                  key={col.label}
                  className="border-b border-[#D4D9E0] p-4 last:border-b-0 sm:border-b-0 sm:border-r sm:border-[#D4D9E0] sm:last:border-r-0 sm:p-5"
                >
                  <p className="font-mono text-[10px] tracking-[0.2em] text-[#6B7C8F]">{col.label}</p>
                  <p className="mt-2 text-sm leading-relaxed text-[#0B1D33]">{col.body}</p>
                </div>
              ))}
            </div>

            {/* Alternate stamp example — review */}
            <p className="mt-8 font-mono text-[11px] tracking-wide text-[#6B7C8F]">
              Alternate outcome on the same pipeline:
            </p>
            <div className="mt-3 flex justify-start">
              <div className="ledger-stamp-review relative -rotate-1 select-none px-4 py-3 sm:px-6">
                <div className="border-[3px] border-double border-[#D97706] px-4 py-3 text-center sm:px-6">
                  <p className="font-display text-base font-semibold tracking-wide text-[#D97706] sm:text-lg">
                    REVIEW REQUIRED
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] tracking-[0.16em] text-[#D97706]/90">
                    SECTION 17(5) RISK
                  </p>
                </div>
              </div>
            </div>
          </div>
        </JourneyStep>
      </div>
    </div>
  );
}
