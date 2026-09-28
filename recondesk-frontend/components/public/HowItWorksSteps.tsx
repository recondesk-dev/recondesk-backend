"use client";

import React from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  Cpu,
  Download,
  FileSpreadsheet,
  FileText,
  Layers,
  Mail,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  Zap,
} from "lucide-react";

export function HowItWorksSteps() {
  const steps = [
    {
      step: "01",
      tag: "Ingest",
      title: "Upload Portals & Ledgers",
      description:
        "Upload your GSTR-2B JSON and purchase registers from Tally, Busy, or Excel — or fetch 2B directly via 1-click GSTN OTP.",
      // Step 1 Micro-Visual
      renderVisual: () => (
        <div className="rounded-[12px] border border-[#E5E5E2] bg-[#F8FAFC] p-4 text-left font-mono text-xs">
          <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-2 text-[11px] font-bold text-[#0F172A]">
            <span className="flex items-center gap-1.5">
              <UploadCloud className="h-3.5 w-3.5 text-[#7B5CFA]" />
              File Ingestion
            </span>
            <span className="text-[10px] font-semibold text-emerald-600 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-100">
              Auto-Mapped
            </span>
          </div>

          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between rounded bg-white p-2 border border-[#E2E8F0]">
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#334155]">
                <FileText className="h-3.5 w-3.5 text-[#7B5CFA]" />
                GSTR-2B.json
              </span>
              <span className="text-[10px] font-bold text-[#16A34A]">1,438 Invs</span>
            </div>

            <div className="flex items-center justify-between rounded bg-white p-2 border border-[#E2E8F0]">
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#334155]">
                <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600" />
                Tally_Register.xlsx
              </span>
              <span className="text-[10px] font-bold text-[#16A34A]">Matched Columns</span>
            </div>
          </div>

          <div className="mt-2.5 flex items-center justify-between text-[10px] text-[#64748B] pt-1">
            <span>GSTIN, Inv#, Date, Tax</span>
            <span className="text-emerald-700 font-bold">● 0.8s Parser</span>
          </div>
        </div>
      ),
    },
    {
      step: "02",
      tag: "Engine",
      title: "20-Second Multi-Phase Match",
      description:
        "103+ statutory rules execute in parallel: normalizing invoice prefixes, isolating credit notes, and flagging Rule 37 reversals.",
      // Step 2 Micro-Visual
      renderVisual: () => (
        <div className="rounded-[12px] border border-[#E5E5E2] bg-[#F8FAFC] p-4 text-left font-mono text-xs">
          <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-2 text-[11px] font-bold text-[#0F172A]">
            <span className="flex items-center gap-1.5">
              <Cpu className="h-3.5 w-3.5 text-[#7B5CFA]" />
              5-Level Matching
            </span>
            <span className="text-[10px] font-semibold text-[#7B5CFA] bg-purple-50 px-1.5 py-0.2 rounded border border-purple-100">
              14.8s Speed
            </span>
          </div>

          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between rounded bg-white p-2 border border-[#E2E8F0]">
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#334155]">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                L1/L2 Normalization
              </span>
              <span className="text-[10px] font-bold text-[#16A34A]">97% Clean</span>
            </div>

            <div className="flex items-center justify-between rounded bg-white p-2 border border-[#E2E8F0]">
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#334155]">
                <Clock className="h-3.5 w-3.5 text-orange-600" />
                Rule 37 180-Day Scan
              </span>
              <span className="text-[10px] font-bold text-[#C2410C]">3 Flagged</span>
            </div>
          </div>

          <div className="mt-2.5 flex items-center justify-between text-[10px] text-[#64748B] pt-1">
            <span>₹0 Financial Drift</span>
            <span className="text-[#7B5CFA] font-bold">● 103+ Rules</span>
          </div>
        </div>
      ),
    },
    {
      step: "03",
      tag: "Export",
      title: "One-Click CA Decisions",
      description:
        "Auto-populate your GSTR-3B ITC claim, dispatch 1-click vendor demand letters, and export multi-sheet audit workpapers.",
      // Step 3 Micro-Visual
      renderVisual: () => (
        <div className="rounded-[12px] border border-[#E5E5E2] bg-[#F8FAFC] p-4 text-left font-mono text-xs">
          <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-2 text-[11px] font-bold text-[#0F172A]">
            <span className="flex items-center gap-1.5">
              <Download className="h-3.5 w-3.5 text-[#7B5CFA]" />
              Audit Workpapers
            </span>
            <span className="text-[10px] font-semibold text-emerald-600 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-100">
              3B Ready
            </span>
          </div>

          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between rounded bg-white p-2 border border-[#E2E8F0]">
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#334155]">
                <Check className="h-3.5 w-3.5 text-emerald-600" />
                GSTR-3B Table 4 Tie-out
              </span>
              <span className="text-[10px] font-bold text-[#16A34A]">₹48.24L</span>
            </div>

            <div className="flex items-center justify-between rounded bg-white p-2 border border-[#E2E8F0]">
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#334155]">
                <Mail className="h-3.5 w-3.5 text-[#7B5CFA]" />
                Vendor Demand Notice
              </span>
              <span className="text-[10px] font-bold text-[#7B5CFA]">1-Click PDF</span>
            </div>
          </div>

          <div className="mt-2.5 flex items-center justify-between text-[10px] text-[#64748B] pt-1">
            <span>Multi-Sheet .XLSX</span>
            <span className="text-emerald-700 font-bold">● 100% Audit Ready</span>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="mx-auto max-w-5xl">
      {/* ─── 3-Column Minimal Timeline ─── */}
      <div className="relative grid grid-cols-1 gap-6 md:grid-cols-3">
        
        {/* Connecting line on desktop */}
        <div
          className="pointer-events-none absolute left-[15%] right-[15%] top-6 hidden h-[2px] bg-gradient-to-r from-purple-200 via-purple-300 to-purple-200 md:block"
          aria-hidden="true"
        />

        {steps.map((item, index) => (
          <div
            key={item.step}
            className="relative flex flex-col justify-between rounded-[22px] border border-white/85 bg-white p-6 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)]"
          >
            <div>
              {/* Step Number Badge */}
              <div className="flex items-center justify-between">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#0A0A0A] font-mono text-xs font-bold text-white shadow-xs">
                  {item.step}
                </span>
                <span className="rounded-full bg-purple-50 px-2.5 py-0.5 font-mono text-[11px] font-bold text-[#7B5CFA] border border-purple-100">
                  {item.tag}
                </span>
              </div>

              {/* Title & Description */}
              <h3 className="mt-4 text-base font-bold text-[#0A0A0A] sm:text-lg">
                {item.title}
              </h3>
              <p className="mt-1.5 text-xs text-[#6B6B6B] leading-relaxed">
                {item.description}
              </p>
            </div>

            {/* Embedded Clean Micro-Visual */}
            <div className="mt-6 pt-2">
              {item.renderVisual()}
            </div>
          </div>
        ))}

      </div>
    </div>
  );
}
