"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FileCheck2,
  FileSpreadsheet,
  FileWarning,
  Sparkles,
  ArrowRight,
} from "lucide-react";

interface Step {
  id: number;
  title: string;
  badge: string;
  description: string;
  vendorDoc: {
    invNo: string;
    date: string;
    amount: string;
    gstin: string;
  };
  prDoc: {
    invNo: string;
    date: string;
    amount: string;
    gstin: string;
  };
  status: "error" | "warning" | "resolving" | "success";
  statusText: string;
  analysisText: string;
}

const STEPS: Step[] = [
  {
    id: 1,
    title: "1. The Discrepancy",
    badge: "Raw Upload",
    description:
      "A vendor enters 'INV/2024-25/0842' in their GSTR-1, but your client's accounts team typed '842' in Tally. Standard VLOOKUP fails immediately.",
    vendorDoc: {
      invNo: "INV/2024-25/0842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    prDoc: {
      invNo: "842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    status: "error",
    statusText: "VLOOKUP FAILED — 0 MATCH",
    analysisText: "Standard spreadsheet formulas treat these as two unrelated transactions.",
  },
  {
    id: 2,
    title: "2. The Section 16(4) Danger",
    badge: "Filing Deadline Risk",
    description:
      "Because the invoice is unmatched in GSTR-2B, the client excludes it from GSTR-3B Table 4. As November 30 passes, this ₹73,600 ITC permanently lapses.",
    vendorDoc: {
      invNo: "INV/2024-25/0842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    prDoc: {
      invNo: "842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    status: "warning",
    statusText: "CRITICAL: DEADLINE AT RISK",
    analysisText: "Without fuzzy normalization, ₹73,600 in tax credit is blocked.",
  },
  {
    id: 3,
    title: "3. ReconDesk Fuzzy Intelligence",
    badge: "L3 Normalized Match",
    description:
      "ReconDesk strips slashes, financial year prefixes, and leading zeroes. It identifies identical GSTIN, exact date, and identical tax amount.",
    vendorDoc: {
      invNo: "INV/2024-25/0842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    prDoc: {
      invNo: "842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    status: "resolving",
    statusText: "NORMALIZING & LINKING...",
    analysisText: "Core numeric pattern matches '842' with 100% tax and date parity.",
  },
  {
    id: 4,
    title: "4. ITC Recovered & Documented",
    badge: "Audit-Ready Workpaper",
    description:
      "Matched under Level 3 (L3 Fuzzy). Automatically tagged for GSTR-3B Table 4(A)(5) claiming, with audit remarks recorded for tax authorities.",
    vendorDoc: {
      invNo: "INV/2024-25/0842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    prDoc: {
      invNo: "842",
      date: "14-Jul-2024",
      amount: "₹4,82,400",
      gstin: "27AAACG0000A1Z5",
    },
    status: "success",
    statusText: "MATCHED: ₹73,600 ITC CLAIMABLE",
    analysisText: "Safe to claim in GSTR-3B. Comprehensive audit workpaper exported.",
  },
];

export function ScrollyInvoiceStory() {
  const [activeStep, setActiveStep] = useState<number>(0);
  const current = STEPS[activeStep];

  return (
    <div className="my-10 overflow-hidden rounded-2xl border border-[#E5E5E2] bg-white p-5 sm:p-8 shadow-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-6 border-b border-[#E5E5E2] gap-2">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-50 px-2.5 py-0.5 text-xs font-semibold text-[#7B5CFA] border border-purple-200">
            <Sparkles className="h-3 w-3" />
            Interactive Storyboard
          </span>
          <h4 className="mt-1 text-lg font-bold text-[#0A0A0A] sm:text-xl">
            Watch an Unmatched Invoice Get Rescued
          </h4>
        </div>
        <div className="flex items-center gap-1 text-xs text-[#6B6B6B]">
          <span>Step {activeStep + 1} of {STEPS.length}</span>
        </div>
      </div>

      {/* Step Tabs for quick navigation */}
      <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {STEPS.map((step, idx) => (
          <button
            key={step.id}
            type="button"
            onClick={() => setActiveStep(idx)}
            className={`rounded-lg p-2.5 text-left text-xs transition-all ${
              activeStep === idx
                ? "border-2 border-[#7B5CFA] bg-purple-50/50 font-bold text-[#0A0A0A] shadow-sm"
                : "border border-[#E5E5E2] bg-[#FAF9F5] text-[#6B6B6B] hover:bg-white hover:text-[#0A0A0A]"
            }`}
          >
            <div className="text-[10px] uppercase font-bold text-[#7B5CFA]">{step.badge}</div>
            <div className="truncate mt-0.5">{step.title.split(". ")[1]}</div>
          </button>
        ))}
      </div>

      {/* Interactive Stage */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-12 lg:items-center">
        {/* Narrative / Description (Left 5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <AnimatePresence mode="wait">
            <motion.div
              key={current.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
              className="space-y-3"
            >
              <h5 className="text-base font-bold text-[#0A0A0A] sm:text-lg">
                {current.title}
              </h5>
              <p className="text-xs sm:text-sm text-[#4A4A4A] leading-relaxed">
                {current.description}
              </p>
              <div className="rounded-lg bg-[#FAF9F5] p-3 border border-[#E5E5E2] text-xs text-[#6B6B6B]">
                <strong className="text-[#0A0A0A]">Engine Verdict:</strong> {current.analysisText}
              </div>
            </motion.div>
          </AnimatePresence>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              disabled={activeStep === 0}
              onClick={() => setActiveStep((prev) => Math.max(0, prev - 1))}
              className="rounded-md border border-[#E5E5E2] px-3 py-1.5 text-xs font-medium text-[#6B6B6B] disabled:opacity-40 hover:bg-[#FAF9F5]"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={activeStep === STEPS.length - 1}
              onClick={() => setActiveStep((prev) => Math.min(STEPS.length - 1, prev + 1))}
              className="flex items-center gap-1.5 rounded-md bg-[#7B5CFA] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm disabled:opacity-40 hover:bg-[#6C4DE6]"
            >
              <span>Next Step</span>
              <ArrowRight className="h-3 w-3" />
            </button>
          </div>
        </div>

        {/* Visual Engine Stage (Right 7 cols) */}
        <div className="lg:col-span-7">
          <div className="relative overflow-hidden rounded-xl border border-[#E5E5E2] bg-[#0A0A0A] p-4 sm:p-5 text-white shadow-lg">
            {/* Window Top Bar */}
            <div className="flex items-center justify-between border-b border-white/10 pb-3 text-[11px] text-white/60">
              <div className="flex items-center gap-1.5">
                <div className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
                <div className="h-2.5 w-2.5 rounded-full bg-amber-500/80" />
                <div className="h-2.5 w-2.5 rounded-full bg-emerald-500/80" />
                <span className="ml-2 font-mono text-[10px]">recondesk-match-stream</span>
              </div>
              <span className="font-mono text-[10px] text-white/40">INV_ID: #842</span>
            </div>

            {/* Document Comparison */}
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              {/* Document A: GSTR-2B */}
              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-purple-300">
                  <FileSpreadsheet className="h-3.5 w-3.5" />
                  <span>Portal (GSTR-2B)</span>
                </div>
                <div className="mt-2 space-y-1 font-mono text-[11px]">
                  <div className="text-white/50">Inv: <span className="text-white font-bold">{current.vendorDoc.invNo}</span></div>
                  <div className="text-white/50">Date: <span className="text-white">{current.vendorDoc.date}</span></div>
                  <div className="text-white/50">Amt: <span className="text-white font-semibold">{current.vendorDoc.amount}</span></div>
                </div>
              </div>

              {/* Document B: Purchase Register */}
              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-300">
                  <FileCheck2 className="h-3.5 w-3.5" />
                  <span>Client Books (Tally/PR)</span>
                </div>
                <div className="mt-2 space-y-1 font-mono text-[11px]">
                  <div className="text-white/50">Inv: <span className={`font-bold ${current.status === "error" ? "text-red-400" : current.status === "success" ? "text-emerald-400" : "text-white"}`}>{current.prDoc.invNo}</span></div>
                  <div className="text-white/50">Date: <span className="text-white">{current.prDoc.date}</span></div>
                  <div className="text-white/50">Amt: <span className="text-white font-semibold">{current.prDoc.amount}</span></div>
                </div>
              </div>
            </div>

            {/* Live Engine Resolution Banner */}
            <motion.div
              key={current.id + "-badge"}
              initial={{ scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.2 }}
              className={`mt-4 flex items-center justify-between rounded-lg p-3 text-xs font-semibold ${
                current.status === "error"
                  ? "bg-red-950/80 text-red-200 border border-red-800"
                  : current.status === "warning"
                  ? "bg-amber-950/80 text-amber-200 border border-amber-800"
                  : current.status === "resolving"
                  ? "bg-purple-950/80 text-purple-200 border border-purple-800"
                  : "bg-emerald-950/80 text-emerald-200 border border-emerald-800"
              }`}
            >
              <div className="flex items-center gap-2">
                {current.status === "error" && <FileWarning className="h-4 w-4 text-red-400" />}
                {current.status === "warning" && <AlertTriangle className="h-4 w-4 text-amber-400" />}
                {current.status === "resolving" && <Cpu className="h-4 w-4 text-purple-400 animate-spin" />}
                {current.status === "success" && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                <span>{current.statusText}</span>
              </div>
              <span className="font-mono text-[10px] opacity-75">STATUS_CODE: {current.status.toUpperCase()}</span>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}
