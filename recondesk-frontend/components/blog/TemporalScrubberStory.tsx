"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Calendar,
  Clock,
  AlertTriangle,
  Lock,
  ArrowRight,
  RotateCcw,
  Sparkles,
  ShieldCheck,
  TrendingDown,
  Building2,
  DollarSign,
} from "lucide-react";

interface Milestone {
  day: number;
  time: string;
  label: string;
  badge: string;
  supplierStatus: "pending" | "missed" | "locked" | "recovered";
  portalStatus: "open" | "closing" | "frozen" | "cleared";
  itcAvailable: number; // in Rupees
  cashTaxPayable: number; // in Rupees
  headline: string;
  narrative: string;
}

const MILESTONES: Milestone[] = [
  {
    day: 1,
    time: "Day 1 to 10",
    label: "Business Operations",
    badge: "CALM PERIOD",
    supplierStatus: "pending",
    portalStatus: "open",
    itcAvailable: 1000000,
    cashTaxPayable: 200000,
    headline: "Invoices Accumulating in Books",
    narrative:
      "Your client recorded ₹10 Lakhs eligible ITC in Tally, including ₹1.8 Lakhs on invoice #842 from a key supplier. Everything looks normal.",
  },
  {
    day: 11,
    time: "Day 11 • 23:59:59",
    label: "GSTR-1 Cut-off",
    badge: "SUPPLIER DEADLINE",
    supplierStatus: "missed",
    portalStatus: "closing",
    itcAvailable: 1000000,
    cashTaxPayable: 200000,
    headline: "Supplier Misses GSTR-1 Deadline",
    narrative:
      "Midnight strikes. The supplier forgot to file their monthly GSTR-1. In traditional practice, you have zero visibility of this delay.",
  },
  {
    day: 14,
    time: "Day 14 • 00:00:01",
    label: "GSTR-2B Lock",
    badge: "STATIC SNAPSHOT",
    supplierStatus: "locked",
    portalStatus: "frozen",
    itcAvailable: 820000,
    cashTaxPayable: 380000,
    headline: "GSTR-2B Freezes: ₹1.8L Locked Out",
    narrative:
      "GSTN generates the static 2B snapshot. Invoices not filed by 11th are shut out. Under Rule 36(4), this ₹1.8L ITC cannot be claimed this month.",
  },
  {
    day: 20,
    time: "Day 20 • 21:00:00",
    label: "GSTR-3B Filing Night",
    badge: "CASH DRAIN",
    supplierStatus: "locked",
    portalStatus: "frozen",
    itcAvailable: 820000,
    cashTaxPayable: 380000,
    headline: "The Cash Shock: ₹1.8L Hard Cash Outflow",
    narrative:
      "It's filing night. The client has to pay ₹1.8 Lakhs extra in hard cash out of their working capital because the missing ITC is legally blocked.",
  },
  {
    day: 21,
    time: "ReconDesk Fix",
    label: "Automated Early Resolution",
    badge: "RECONDESK PROTOCOL",
    supplierStatus: "recovered",
    portalStatus: "cleared",
    itcAvailable: 1000000,
    cashTaxPayable: 200000,
    headline: "Early Nudge & 100% ITC Restored",
    narrative:
      "ReconDesk flags the missing invoice on Day 12 and sends an automated WhatsApp/email nudge to the supplier. Supplier files before lock. ₹1.8L saved!",
  },
];

export function TemporalScrubberStory() {
  const [currentIndex, setCurrentIndex] = useState<number>(0);
  const current = MILESTONES[currentIndex];

  const formatRupees = (amt: number) =>
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amt);

  return (
    <div
      className="my-10 overflow-hidden rounded-2xl border border-[#E5E5E2] bg-[#0A0A0A] text-white shadow-xl"
      style={{ contain: "paint layout", transform: "translateZ(0)" }}
    >
      {/* Top Cockpit Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-white/10 px-5 py-4 bg-white/[0.02]">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#7B5CFA]/20 border border-[#7B5CFA]/40 text-[#7B5CFA]">
            <Clock className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold tracking-wider text-white uppercase">
                Temporal Scrubber
              </span>
              <span className="rounded-full bg-purple-500/20 px-2 py-0.2 text-[9px] font-mono font-semibold text-purple-300 border border-purple-500/30">
                120 FPS ENGINE
              </span>
            </div>
            <p className="text-[11px] text-white/50">
              The 20-Day Filing Clock &amp; Client Working Capital Simulation
            </p>
          </div>
        </div>

        {/* Milestone Indicator */}
        <div className="mt-2 sm:mt-0 flex items-center gap-1.5 font-mono text-[11px] text-white/60">
          <Calendar className="h-3.5 w-3.5 text-[#7B5CFA]" />
          <span>Timeline Point: {currentIndex + 1} / {MILESTONES.length}</span>
        </div>
      </div>

      {/* Main Interactive Stage */}
      <div className="p-5 sm:p-7 space-y-6">
        {/* Timeline Scrubber Bar */}
        <div className="space-y-2">
          <div className="flex justify-between text-[11px] font-mono text-white/50">
            <span>Day 1 (Invoices start)</span>
            <span className="text-amber-400">Day 11 (GSTR-1)</span>
            <span className="text-purple-400">Day 14 (GSTR-2B Lock)</span>
            <span className="text-red-400">Day 20 (3B Cash Due)</span>
            <span className="text-emerald-400">ReconDesk Protocol</span>
          </div>

          {/* Interactive Scrub Buttons */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {MILESTONES.map((m, idx) => (
              <button
                key={m.label}
                type="button"
                onClick={() => setCurrentIndex(idx)}
                className={`group relative flex flex-col rounded-lg p-2.5 text-left transition-all duration-150 ${
                  currentIndex === idx
                    ? "bg-[#7B5CFA] text-white shadow-lg shadow-[#7B5CFA]/25 scale-[1.02]"
                    : "bg-white/5 text-white/70 hover:bg-white/10 hover:text-white border border-white/5"
                }`}
                style={{ willChange: "transform" }}
              >
                <span className="text-[10px] font-mono uppercase tracking-wider opacity-80">
                  {m.time.split(" • ")[0]}
                </span>
                <span className="mt-0.5 truncate text-xs font-bold leading-snug">
                  {m.label}
                </span>
                {currentIndex === idx && (
                  <motion.div
                    layoutId="active-indicator"
                    className="absolute -bottom-1 left-1/2 h-1 w-6 -translate-x-1/2 rounded-full bg-white"
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Live Gauges Split-View */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Narrative & Story Card (Left 6 cols) */}
          <div className="lg:col-span-6 rounded-xl border border-white/10 bg-white/[0.03] p-5 flex flex-col justify-between">
            <AnimatePresence mode="wait">
              <motion.div
                key={current.label}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.15 }}
                className="space-y-3"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider border ${
                      current.supplierStatus === "recovered"
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                        : current.supplierStatus === "locked"
                        ? "bg-red-500/20 text-red-300 border-red-500/40"
                        : current.supplierStatus === "missed"
                        ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                        : "bg-blue-500/20 text-blue-300 border-blue-500/40"
                    }`}
                  >
                    {current.badge}
                  </span>
                  <span className="text-xs text-white/40 font-mono">{current.time}</span>
                </div>

                <h4 className="text-lg font-bold text-white tracking-tight">
                  {current.headline}
                </h4>

                <p className="text-xs sm:text-sm text-white/70 leading-relaxed">
                  {current.narrative}
                </p>

                {/* Sub-status Indicator */}
                <div className="mt-3 rounded-lg border border-white/10 bg-black/40 p-3 space-y-1 text-xs font-mono">
                  <div className="flex justify-between text-white/50">
                    <span>Supplier GSTR-1 Status:</span>
                    <span
                      className={`font-bold ${
                        current.supplierStatus === "recovered"
                          ? "text-emerald-400"
                          : current.supplierStatus === "locked"
                          ? "text-red-400"
                          : current.supplierStatus === "missed"
                          ? "text-amber-400"
                          : "text-white"
                      }`}
                    >
                      {current.supplierStatus.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex justify-between text-white/50">
                    <span>Portal GSTR-2B Gate:</span>
                    <span
                      className={`font-bold ${
                        current.portalStatus === "frozen"
                          ? "text-red-400 flex items-center gap-1"
                          : current.portalStatus === "cleared"
                          ? "text-emerald-400"
                          : "text-white"
                      }`}
                    >
                      {current.portalStatus === "frozen" && <Lock className="h-3 w-3" />}
                      {current.portalStatus.toUpperCase()}
                    </span>
                  </div>
                </div>
              </motion.div>
            </AnimatePresence>

            {/* Quick Next/Prev Stepper */}
            <div className="mt-4 pt-3 border-t border-white/10 flex justify-between items-center text-xs">
              <button
                type="button"
                disabled={currentIndex === 0}
                onClick={() => setCurrentIndex((p) => Math.max(0, p - 1))}
                className="text-white/60 hover:text-white disabled:opacity-30 disabled:pointer-events-none"
              >
                &larr; Earlier Day
              </button>
              <button
                type="button"
                disabled={currentIndex === MILESTONES.length - 1}
                onClick={() => setCurrentIndex((p) => Math.min(MILESTONES.length - 1, p + 1))}
                className="font-bold text-[#7B5CFA] hover:text-purple-300 flex items-center gap-1 disabled:opacity-30 disabled:pointer-events-none"
              >
                <span>Advance Clock</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Electronic Cash Ledger & Bank Drain Gauge (Right 6 cols) */}
          <div className="lg:col-span-6 rounded-xl border border-white/10 bg-black/60 p-5 flex flex-col justify-between space-y-4">
            <div>
              <div className="flex items-center justify-between text-xs text-white/60 font-mono pb-2 border-b border-white/10">
                <span className="flex items-center gap-1.5">
                  <Building2 className="h-3.5 w-3.5 text-[#7B5CFA]" />
                  <span>CLIENT CASH LEDGER SIMULATION</span>
                </span>
                <span className="text-[10px] text-white/40">GSTR-3B TABLE 6.1</span>
              </div>

              {/* Gauge 1: Available ITC */}
              <div className="mt-4 space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-white/60">GSTR-2B Claimable Credit:</span>
                  <motion.span
                    key={current.itcAvailable}
                    initial={{ scale: 0.95 }}
                    animate={{ scale: 1 }}
                    className={`font-mono font-bold ${
                      current.itcAvailable < 1000000
                        ? "text-red-400"
                        : "text-emerald-400"
                    }`}
                  >
                    {formatRupees(current.itcAvailable)}
                  </motion.span>
                </div>
                {/* Visual Bar */}
                <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                  <motion.div
                    className={`h-full ${
                      current.itcAvailable < 1000000
                        ? "bg-red-500"
                        : "bg-emerald-500"
                    }`}
                    animate={{ width: `${(current.itcAvailable / 1000000) * 100}%` }}
                    transition={{ type: "spring", stiffness: 120, damping: 20 }}
                  />
                </div>
              </div>

              {/* Gauge 2: Cash Tax to Pay (The Real Pain) */}
              <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-4 space-y-2">
                <div className="flex items-center justify-between text-xs text-white/60">
                  <span>Net Cash Tax to Pay (Hard Cash):</span>
                  {current.cashTaxPayable > 200000 && (
                    <span className="inline-flex items-center gap-1 rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-bold text-red-300">
                      <TrendingDown className="h-3 w-3" />
                      +₹1,80,000 EXTRA CASH
                    </span>
                  )}
                </div>

                {/* Rolling Numbers Display */}
                <motion.div
                  key={current.cashTaxPayable}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`text-2xl sm:text-3xl font-mono font-extrabold tracking-tight ${
                    current.cashTaxPayable > 200000
                      ? "text-red-400"
                      : "text-emerald-400"
                  }`}
                >
                  {formatRupees(current.cashTaxPayable)}
                </motion.div>

                <p className="text-[11px] text-white/50 leading-relaxed">
                  {current.cashTaxPayable > 200000
                    ? "⚠️ ₹1.8 Lakhs working capital drained directly from the client's bank account because the invoice missed the 14th snapshot."
                    : "✅ Zero working capital loss. 100% of eligible ITC utilized to offset output GST."}
                </p>
              </div>
            </div>

            {/* Bottom Insight Footer */}
            <div className="rounded-lg bg-[#7B5CFA]/10 border border-[#7B5CFA]/30 p-3 text-[11px] text-purple-200 flex items-start gap-2">
              <Sparkles className="h-4 w-4 text-[#7B5CFA] shrink-0 mt-0.5" />
              <span>
                <strong>Takeaway for CAs:</strong> Manual reconciliation on the 20th is too late. ReconDesk automates early detection on Day 12 so no client ever pays extra cash.
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
