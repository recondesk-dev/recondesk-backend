"use client";

import React from "react";
import {
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  Clock,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  Layers,
  Receipt,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

export function GstrModulesGrid() {
  return (
    <section id="modules" className="scroll-mt-20 py-20 sm:py-28 border-t border-[#E5E5E2] bg-[#FAFAFA]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto">
          <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
            Complete GSTR Coverage
          </p>
          <h2 className="mt-2.5 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
            Built for Every GST Reconciliation Workflow
          </h2>
          <p className="mt-3.5 text-base text-[#6B6B6B] leading-relaxed">
            ReconDesk replaces messy spreadsheets with automated modules for purchase ITC, sales reconciliation, liability checks, and annual audit certification.
          </p>
        </div>

        {/* 4 Upgraded Feature Cards with Mini UI Previews & Micro-Widgets */}
        <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2">
          
          {/* ─── Card 1: GSTR-2B ↔ Purchase Register (ITC Engine) ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[16px] border border-[#E5E5E2] bg-white p-6 sm:p-7 shadow-xs transition-all duration-300 hover:-translate-y-1 hover:border-[#7B5CFA]/40 hover:shadow-[0_16px_40px_rgba(123,92,250,0.08)]">
            {/* Top Accent Line */}
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#7B5CFA]" />

            <div>
              {/* Header Badge & Icon */}
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-50 px-3 py-1 text-xs font-bold text-[#7B5CFA] border border-purple-100">
                  <Layers className="h-3.5 w-3.5" />
                  Purchase / ITC Engine
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  L1 to L4 &amp; L6
                </span>
              </div>

              {/* Title & Description */}
              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-2B ↔ Purchase Register
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Full-spectrum ITC reconciliation pairing portal data with Tally, Busy, or Excel in seconds.
              </p>

              {/* 💡 Micro-Widget / Mini UI Preview: Live Invoice Pair Matching */}
              <div className="mt-5 overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 text-xs font-mono">
                <div className="flex items-center justify-between text-[11px] text-[#64748B] border-b border-[#E2E8F0] pb-2">
                  <span className="font-semibold text-[#0F172A]">Matching Engine Simulation</span>
                  <span className="font-bold text-[#16A34A] flex items-center gap-1">
                    <Check className="h-3 w-3" /> Auto-Claimed
                  </span>
                </div>

                <div className="mt-2.5 space-y-1.5 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">GSTR-2B:</span>
                    <span className="font-bold text-[#0F172A]">INV-0941 · ₹1,42,000</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">PR Books:</span>
                    <span className="font-bold text-[#0F172A]">INV-941 · ₹1,42,000</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between rounded bg-white p-1.5 px-2 border border-[#E2E8F0]">
                    <span className="text-[10px] font-bold text-[#7B5CFA]">
                      ✨ L2 Normalized Match (Prefix Delta)
                    </span>
                    <span className="text-[10px] font-bold text-[#16A34A]">₹0 Diff</span>
                  </div>
                </div>

                {/* Status Chips */}
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[10px] font-sans">
                  <span className="rounded bg-[#DCFCE7] px-2 py-0.5 font-bold text-[#166534]">
                    IMS: Accepted
                  </span>
                  <span className="rounded bg-[#FEF9C3] px-2 py-0.5 font-bold text-[#713F12]">
                    Rule 37: 0 Days Due
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    §17(5): Clean
                  </span>
                </div>
              </div>

              {/* Feature Points */}
              <ul className="mt-5 space-y-2 text-xs text-[#334155]">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-[#7B5CFA] shrink-0" />
                  <span>5-Level Multi-Phase Matcher (L1 exact to L4 PAN)</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-[#7B5CFA] shrink-0" />
                  <span>Rule 37 180-day unpaid reversal alerts + interest estimates</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-[#7B5CFA] shrink-0" />
                  <span>Section 17(5) restricted credit advisor across 7 HSN chapters</span>
                </li>
              </ul>
            </div>

            <div className="mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <a
                href="#how-it-works"
                className="inline-flex items-center gap-1.5 text-xs font-bold text-[#7B5CFA] group-hover:translate-x-0.5 transition-transform"
              >
                <span>Explore ITC matching logic</span>
                <ArrowRight className="h-3 w-3" />
              </a>
            </div>
          </div>

          {/* ─── Card 2: GSTR-1 ↔ Sales Register (Revenue Tie-Out) ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[16px] border border-[#E5E5E2] bg-white p-6 sm:p-7 shadow-xs transition-all duration-300 hover:-translate-y-1 hover:border-[#10B981]/40 hover:shadow-[0_16px_40px_rgba(16,185,129,0.08)]">
            {/* Top Accent Line */}
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#10B981]" />

            <div>
              {/* Header Badge & Icon */}
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 border border-emerald-100">
                  <BarChart3 className="h-3.5 w-3.5" />
                  Sales / Revenue
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  G1M1–G1M10
                </span>
              </div>

              {/* Title & Description */}
              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-1 ↔ Sales Register
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Ensure outward supplies and tax liability match your books before monthly or quarterly filing.
              </p>

              {/* 💡 Micro-Widget / Mini UI Preview: Sales Tie-Out & G1M Rules */}
              <div className="mt-5 overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 text-xs font-mono">
                <div className="flex items-center justify-between text-[11px] text-[#64748B] border-b border-[#E2E8F0] pb-2">
                  <span className="font-semibold text-[#0F172A]">Outward Supply Tie-Out</span>
                  <span className="font-bold text-emerald-600 flex items-center gap-1">
                    <Check className="h-3 w-3" /> Zero Tax Drift
                  </span>
                </div>

                <div className="mt-2.5 space-y-1.5 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">Sales Register:</span>
                    <span className="font-bold text-[#0F172A]">₹84,50,000 (124 Invoices)</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">GSTR-1 Portal:</span>
                    <span className="font-bold text-[#0F172A]">₹84,50,000 (124 Invoices)</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between rounded bg-white p-1.5 px-2 border border-[#E2E8F0]">
                    <span className="text-[10px] font-bold text-emerald-700">
                      ⚡ GSTR-1A Amendment Window
                    </span>
                    <span className="rounded bg-emerald-100 px-1.5 py-0.2 text-[9px] font-bold text-emerald-800">
                      Open
                    </span>
                  </div>
                </div>

                {/* Status Chips */}
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[10px] font-sans">
                  <span className="rounded bg-[#DCFCE7] px-2 py-0.5 font-bold text-[#166534]">
                    B2B: 88 Inv
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    B2CL / Export: 36
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    Table 13: Verified
                  </span>
                </div>
              </div>

              {/* Feature Points */}
              <ul className="mt-5 space-y-2 text-xs text-[#334155]">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                  <span>G1M1–G1M10 mismatch diagnostic codes</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                  <span>B2B, B2CL, B2CS, CDNR &amp; Export auto-categorization</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                  <span>HSN Rate &amp; Table 13 Documents issued audit checks</span>
                </li>
              </ul>
            </div>

            <div className="mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <a
                href="#how-it-works"
                className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-700 group-hover:translate-x-0.5 transition-transform"
              >
                <span>View GSTR-1 discrepancy codes</span>
                <ArrowRight className="h-3 w-3" />
              </a>
            </div>
          </div>

          {/* ─── Card 3: GSTR-3B vs Books & 2B (Notice Shield) ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[16px] border border-[#E5E5E2] bg-white p-6 sm:p-7 shadow-xs transition-all duration-300 hover:-translate-y-1 hover:border-[#F59E0B]/40 hover:shadow-[0_16px_40px_rgba(245,158,11,0.08)]">
            {/* Top Accent Line */}
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#F59E0B]" />

            <div>
              {/* Header Badge & Icon */}
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-800 border border-amber-100">
                  <FileCheck2 className="h-3.5 w-3.5" />
                  Compliance &amp; Notice Shield
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  Rule 88D &amp; DRC-01C
                </span>
              </div>

              {/* Title & Description */}
              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-3B vs Books &amp; 2B
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Reconcile tax payable and ITC claimed against portal figures to pre-empt scrutiny notices.
              </p>

              {/* 💡 Micro-Widget / Mini UI Preview: Rule 88D & DRC-01B Generator */}
              <div className="mt-5 overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 text-xs font-mono">
                <div className="flex items-center justify-between text-[11px] text-[#64748B] border-b border-[#E2E8F0] pb-2">
                  <span className="font-semibold text-[#0F172A]">Rule 88D Compliance Check</span>
                  <span className="font-bold text-amber-700 flex items-center gap-1">
                    <Check className="h-3 w-3" /> Within Threshold
                  </span>
                </div>

                <div className="mt-2.5 space-y-1.5 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">ITC in GSTR-2B:</span>
                    <span className="font-bold text-[#0F172A]">₹48,24,650</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">ITC in GSTR-3B:</span>
                    <span className="font-bold text-[#0F172A]">₹48,24,650</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between rounded bg-white p-1.5 px-2 border border-[#E2E8F0]">
                    <span className="text-[10px] font-bold text-amber-800">
                      📄 DRC-01B Reply Narrative
                    </span>
                    <span className="rounded bg-amber-100 px-1.5 py-0.2 text-[9px] font-bold text-amber-900">
                      Ready
                    </span>
                  </div>
                </div>

                {/* Status Chips */}
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[10px] font-sans">
                  <span className="rounded bg-[#DCFCE7] px-2 py-0.5 font-bold text-[#166534]">
                    Variance: 0.0%
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    DRC-01C: Safe
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    Auto Audit Logged
                  </span>
                </div>
              </div>

              {/* Feature Points */}
              <ul className="mt-5 space-y-2 text-xs text-[#334155]">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-amber-600 shrink-0" />
                  <span>Rule 88D / DRC-01C threshold variance monitoring</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-amber-600 shrink-0" />
                  <span>Instant DRC-01B draft reply narrative generator</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-amber-600 shrink-0" />
                  <span>Period-by-period tax liability &amp; eligible ITC tie-out</span>
                </li>
              </ul>
            </div>

            <div className="mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <a
                href="#how-it-works"
                className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-800 group-hover:translate-x-0.5 transition-transform"
              >
                <span>See notice prevention checks</span>
                <ArrowRight className="h-3 w-3" />
              </a>
            </div>
          </div>

          {/* ─── Card 4: GSTR-9C Annual Audit Workpapers ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[16px] border border-[#E5E5E2] bg-white p-6 sm:p-7 shadow-xs transition-all duration-300 hover:-translate-y-1 hover:border-[#3B82F6]/40 hover:shadow-[0_16px_40px_rgba(59,130,246,0.08)]">
            {/* Top Accent Line */}
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#3B82F6]" />

            <div>
              {/* Header Badge & Icon */}
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700 border border-blue-100">
                  <FileSpreadsheet className="h-3.5 w-3.5" />
                  Annual Audit Workpapers
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  12-Month Rollup
                </span>
              </div>

              {/* Title & Description */}
              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-9C Annual Audit Rollup
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Streamline annual GST audit certifications with automated full-year ITC rollups and audit reports.
              </p>

              {/* 💡 Micro-Widget / Mini UI Preview: Annual FY Table 8A vs 8B Rollup */}
              <div className="mt-5 overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 text-xs font-mono">
                <div className="flex items-center justify-between text-[11px] text-[#64748B] border-b border-[#E2E8F0] pb-2">
                  <span className="font-semibold text-[#0F172A]">Table 8A vs 8B FY Summary</span>
                  <span className="font-bold text-blue-600 flex items-center gap-1">
                    <Check className="h-3 w-3" /> 12 Periods Synced
                  </span>
                </div>

                <div className="mt-2.5 space-y-1.5 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">Table 8A (GSTR-2B):</span>
                    <span className="font-bold text-[#0F172A]">₹5,78,94,200</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">Table 8B (Books):</span>
                    <span className="font-bold text-[#0F172A]">₹5,78,94,200</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between rounded bg-white p-1.5 px-2 border border-[#E2E8F0]">
                    <span className="text-[10px] font-bold text-blue-700">
                      📊 Multi-Sheet Audit Workbook
                    </span>
                    <span className="rounded bg-blue-100 px-1.5 py-0.2 text-[9px] font-bold text-blue-800">
                      .XLSX Ready
                    </span>
                  </div>
                </div>

                {/* Status Chips */}
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[10px] font-sans">
                  <span className="rounded bg-[#DCFCE7] px-2 py-0.5 font-bold text-[#166534]">
                    Variance: ₹0
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    Observations: 0 High Risk
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    Carry-Forward OK
                  </span>
                </div>
              </div>

              {/* Feature Points */}
              <ul className="mt-5 space-y-2 text-xs text-[#334155]">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0" />
                  <span>Full Financial Year (FY) cumulative ITC rollup in 10s</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0" />
                  <span>Multi-sheet audit workpaper Excel &amp; PDF exports</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0" />
                  <span>Severity-ranked audit observation summaries for CA sign-off</span>
                </li>
              </ul>
            </div>

            <div className="mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <a
                href="#how-it-works"
                className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-700 group-hover:translate-x-0.5 transition-transform"
              >
                <span>View 9C audit export format</span>
                <ArrowRight className="h-3 w-3" />
              </a>
            </div>
          </div>

        </div>
      </div>
    </section>
  );
}
