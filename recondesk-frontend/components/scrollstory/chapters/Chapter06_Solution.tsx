"use client";

import { motion } from "framer-motion";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";

interface Props {
  scrollProgress: number;
}

const WORKFLOW_STEPS = [
  {
    id: "upload",
    icon: "⬆",
    label: "Upload",
    desc: "Drop your GSTR-2B JSON and Purchase Register CSV.",
    color: "#16a34a",
  },
  {
    id: "match",
    icon: "⟷",
    label: "Match",
    desc: "ReconDesk matches by GSTIN, invoice number, amount and date.",
    color: "#16a34a",
  },
  {
    id: "flag",
    icon: "⚑",
    label: "Flag",
    desc: "Genuine mismatches are flagged with full context — no false positives.",
    color: "#16a34a",
  },
  {
    id: "resolve",
    icon: "✎",
    label: "Resolve",
    desc: "One-click actions: accept, defer to next month, or request from supplier.",
    color: "#16a34a",
  },
  {
    id: "done",
    icon: "✓",
    label: "Done",
    desc: "Download audit-ready reconciliation report. File 3B with confidence.",
    color: "#16a34a",
  },
];

// Fake UI mock rows
const MOCK_ROWS = [
  { inv: "INV-0211", supplier: "Acme Supplies", igst: "₹14,400", status: "match" },
  { inv: "INV-0892", supplier: "Beta Materials", igst: "₹12,500", status: "match" },
  { inv: "INV-1043", supplier: "Gamma Traders", igst: "₹52,000", status: "match" },
  { inv: "INV-0444", supplier: "Delta Corp", igst: "₹8,750", status: "flag" },
  { inv: "INV-0567", supplier: "Epsilon Ltd", igst: "₹23,400", status: "match" },
];

/**
 * Chapter 06 — Solution
 * White background. ReconDesk product UI wireframe. Workflow steps animate in.
 */
export function Chapter06_Solution({ scrollProgress }: Props) {
  const showWorkflow = scrollProgress > 0.1;
  const visibleSteps = Math.min(
    WORKFLOW_STEPS.length,
    Math.floor(((scrollProgress - 0.15) / 0.65) * WORKFLOW_STEPS.length)
  );
  const showMock = scrollProgress > 0.55;

  return (
    <StickyScene background="#ffffff">
      <div className="relative h-full w-full flex flex-col justify-center px-6 overflow-y-auto">
        <div className="mx-auto w-full max-w-4xl py-10">
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-[#aaa]">
            Chapter 06 — Solution
          </p>
          <h2 className="mt-3 text-2xl font-semibold text-[#0a0a0a] sm:text-3xl">
            Introducing ReconDesk.
          </h2>
          <p className="mt-2 text-base text-[#666]">
            GSTR-2B reconciliation in minutes, not hours.
          </p>

          {/* Workflow steps */}
          <motion.div
            className="mt-8 flex flex-wrap gap-3"
            animate={{ opacity: showWorkflow ? 1 : 0 }}
            transition={{ duration: 0.6 }}
          >
            {WORKFLOW_STEPS.map((step, i) => (
              <motion.div
                key={step.id}
                animate={{
                  opacity: i < visibleSteps ? 1 : 0.15,
                  scale: i < visibleSteps ? 1 : 0.96,
                }}
                transition={{ duration: 0.6, ease: "easeOut" }}
                className="flex flex-col items-center gap-1.5 rounded-2xl border border-[#e5e5e5] bg-white px-5 py-4 shadow-sm"
              >
                <span className="text-2xl">{step.icon}</span>
                <span className="font-semibold text-[#0a0a0a]">{step.label}</span>
                <p className="max-w-[140px] text-center text-xs leading-relaxed text-[#888]">
                  {step.desc}
                </p>
                {i < visibleSteps && (
                  <motion.span
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    className="mt-1 text-green-600 text-lg font-bold"
                  >
                    ✓
                  </motion.span>
                )}
              </motion.div>
            ))}
          </motion.div>

          {/* Mock UI */}
          <motion.div
            className="mt-8"
            animate={{ opacity: showMock ? 1 : 0, y: showMock ? 0 : 20 }}
            transition={{ duration: 0.8 }}
          >
            <div className="rounded-2xl border border-[#e5e5e5] bg-[#fafafa] overflow-hidden shadow-sm">
              {/* Mock title bar */}
              <div className="flex items-center gap-2 border-b border-[#e5e5e5] bg-white px-4 py-3">
                <div className="h-3 w-3 rounded-full bg-[#eee]" />
                <div className="h-3 w-3 rounded-full bg-[#eee]" />
                <div className="h-3 w-3 rounded-full bg-[#eee]" />
                <span className="ml-4 font-mono text-xs text-[#aaa]">
                  ReconDesk — Aug 2024 Reconciliation
                </span>
                <span className="ml-auto rounded-full bg-green-100 px-2 py-0.5 font-mono text-xs font-semibold text-green-700">
                  98.2% matched
                </span>
              </div>
              {/* Mock rows */}
              <div className="divide-y divide-[#f0f0f0]">
                {MOCK_ROWS.map((row, i) => (
                  <div
                    key={i}
                    className="grid grid-cols-4 gap-4 px-4 py-2.5 font-mono text-xs"
                  >
                    <span className="text-[#888]">{row.inv}</span>
                    <span className="text-[#333]">{row.supplier}</span>
                    <span className="text-[#333]">{row.igst}</span>
                    <span
                      className={
                        row.status === "flag"
                          ? "font-semibold text-amber-600"
                          : "font-semibold text-green-600"
                      }
                    >
                      {row.status === "flag" ? "⚑ Review" : "✓ Matched"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </StickyScene>
  );
}
