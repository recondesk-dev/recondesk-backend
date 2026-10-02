"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  Info,
  Layers,
  Receipt,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

type ModalType = "itc" | "gstr1" | "gstr3b" | "gstr9c" | null;

export function GstrModulesGrid() {
  const [activeModal, setActiveModal] = useState<ModalType>(null);

  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!activeModal) return;
    const trigger = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]'
    ) ?? []).filter((element) => element.getClientRects().length > 0);
    focusable()[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setActiveModal(null); }
      if (event.key !== "Tab") return;
      const items = focusable();
      const first = items[0];
      const last = items[items.length - 1];
      if (!first) { event.preventDefault(); dialogRef.current?.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      trigger?.focus({ preventScroll: true });
    };
  }, [activeModal]);

  return (
    <section id="modules" className="scroll-mt-20 py-20 sm:py-28 border-t border-[#CBD5E1]/60">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto">
          <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
            Complete GSTR Coverage
          </p>
          <h2 className="mt-2.5 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
            Built for Every GST Reconciliation Workflow
          </h2>
          <p className="mt-3.5 text-base text-[#5B6577] leading-relaxed">
            ReconDesk replaces messy spreadsheets with automated modules for purchase ITC, sales reconciliation, liability checks, and annual audit certification.
          </p>
        </div>

        {/* 4 Upgraded Feature Cards with Mini UI Previews & Micro-Widgets */}
        <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2">
          
          {/* ─── Card 1: GSTR-2B ↔ Purchase Register (ITC Engine) ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)]">
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#7B5CFA]" />

            <div>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-50 px-3 py-1 text-xs font-bold text-[#7B5CFA] border border-purple-100">
                  <Layers className="h-3.5 w-3.5" />
                  Purchase / ITC Engine
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  L1 to L4 &amp; L6
                </span>
              </div>

              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-2B ↔ Purchase Register
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Full-spectrum ITC reconciliation pairing portal data with Tally, Busy, or Excel in seconds.
              </p>

              {/* Micro-Widget Simulation */}
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

                <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[10px] font-sans">
                  <span className="rounded bg-[#DCFCE7] px-2 py-0.5 font-bold text-[#166534]">
                    IMS: Accepted
                  </span>
                  <span className="rounded bg-[#FEF9C3] px-2 py-0.5 font-bold text-[#713F12]">
                    Rule 37: 0 Days Due
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 font-semibold text-[#475569] border border-[#E2E8F0]">
                    Sec 17(5): Clean
                  </span>
                </div>
              </div>

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

            {/* Interactive Link that triggers Modal */}
            <div className="relative z-10 mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <button
                type="button"
                onClick={() => setActiveModal("itc")}
                className="inline-flex items-center gap-1.5 text-xs font-bold text-[#7B5CFA] hover:text-[#6C4DE6] group-hover:translate-x-0.5 transition-all"
              >
                <span>Explore ITC matching logic</span>
                <ArrowRight className="h-3 w-3" />
              </button>
            </div>

            {/* Faint white cloud fade overlay at bottom to dissolve sharp bottom edge */}
            <div
              className="pointer-events-none absolute -bottom-1 -left-1 -right-1 h-14 bg-gradient-to-t from-white via-white/85 to-transparent"
              aria-hidden="true"
            />
          </div>

          {/* ─── Card 2: GSTR-1 ↔ Sales Register (Revenue Tie-Out) ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)]">
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#10B981]" />

            <div>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 border border-emerald-100">
                  <BarChart3 className="h-3.5 w-3.5" />
                  Sales / Revenue
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  G1M1–G1M10
                </span>
              </div>

              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-1 ↔ Sales Register
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Ensure outward supplies and tax liability match your books before monthly or quarterly filing.
              </p>

              {/* Micro-Widget Simulation */}
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

            {/* Interactive Link that triggers Modal */}
            <div className="relative z-10 mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <button
                type="button"
                onClick={() => setActiveModal("gstr1")}
                className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-700 hover:text-emerald-800 group-hover:translate-x-0.5 transition-all"
              >
                <span>View GSTR-1 discrepancy codes</span>
                <ArrowRight className="h-3 w-3" />
              </button>
            </div>

            {/* Faint white cloud fade overlay at bottom to dissolve sharp bottom edge */}
            <div
              className="pointer-events-none absolute -bottom-1 -left-1 -right-1 h-14 bg-gradient-to-t from-white via-white/85 to-transparent"
              aria-hidden="true"
            />
          </div>

          {/* ─── Card 3: GSTR-3B vs Books & 2B (Notice Shield) ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)]">
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#F59E0B]" />

            <div>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-800 border border-amber-100">
                  <FileCheck2 className="h-3.5 w-3.5" />
                  Compliance &amp; Notice Shield
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  Rule 88D &amp; DRC-01C
                </span>
              </div>

              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-3B vs Books &amp; 2B
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Reconcile tax payable and ITC claimed against portal figures to pre-empt scrutiny notices.
              </p>

              {/* Micro-Widget Simulation */}
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
                      📄 DRC-01C Reply Narrative
                    </span>
                    <span className="rounded bg-amber-100 px-1.5 py-0.2 text-[9px] font-bold text-amber-900">
                      Ready
                    </span>
                  </div>
                </div>

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

              <ul className="mt-5 space-y-2 text-xs text-[#334155]">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-amber-600 shrink-0" />
                  <span>Rule 88D / DRC-01C threshold variance monitoring</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-amber-600 shrink-0" />
                  <span>Instant DRC-01C draft reply narrative generator</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-amber-600 shrink-0" />
                  <span>Period-by-period tax liability &amp; eligible ITC tie-out</span>
                </li>
              </ul>
            </div>

            {/* Interactive Link that triggers Modal */}
            <div className="relative z-10 mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <button
                type="button"
                onClick={() => setActiveModal("gstr3b")}
                className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-800 hover:text-amber-900 group-hover:translate-x-0.5 transition-all"
              >
                <span>See notice prevention checks</span>
                <ArrowRight className="h-3 w-3" />
              </button>
            </div>

            {/* Faint white cloud fade overlay at bottom to dissolve sharp bottom edge */}
            <div
              className="pointer-events-none absolute -bottom-1 -left-1 -right-1 h-14 bg-gradient-to-t from-white via-white/85 to-transparent"
              aria-hidden="true"
            />
          </div>

          {/* ─── Card 4: GSTR-9C Annual Audit Workpapers ─── */}
          <div className="group relative flex flex-col justify-between overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)]">
            <div className="absolute top-0 left-0 right-0 h-1 bg-[#3B82F6]" />

            <div>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700 border border-blue-100">
                  <FileSpreadsheet className="h-3.5 w-3.5" />
                  Annual Audit Workpapers
                </span>
                <span className="rounded-md bg-[#F8FAFC] px-2 py-1 text-[11px] font-bold text-[#64748B]">
                  12-Month Rollup
                </span>
              </div>

              <h3 className="mt-4 text-xl font-bold text-[#0A0A0A]">
                GSTR-9C Annual Audit Rollup
              </h3>
              <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
                Streamline annual GST audit certifications with automated full-year ITC rollups and audit reports.
              </p>

              {/* Micro-Widget Simulation */}
              <div className="mt-5 overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 text-xs font-mono">
                <div className="flex items-center justify-between text-[11px] text-[#64748B] border-b border-[#E2E8F0] pb-2">
                  <span className="font-semibold text-[#0F172A]">Table 8A vs 8B FY Summary</span>
                  <span className="font-bold text-blue-600 flex items-center gap-1">
                    <Check className="h-3 w-3" /> 12 Periods Synced
                  </span>
                </div>

                <div className="mt-2.5 space-y-1.5 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-[#64748B]">Table 8A (GSTR-2A):</span>
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

            {/* Interactive Link that triggers Modal */}
            <div className="relative z-10 mt-6 pt-4 border-t border-[#E5E5E2] flex items-center justify-between">
              <button
                type="button"
                onClick={() => setActiveModal("gstr9c")}
                className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-700 hover:text-blue-800 group-hover:translate-x-0.5 transition-all"
              >
                <span>View 9C audit export format</span>
                <ArrowRight className="h-3 w-3" />
              </button>
            </div>

            {/* Faint white cloud fade overlay at bottom to dissolve sharp bottom edge */}
            <div
              className="pointer-events-none absolute -bottom-1 -left-1 -right-1 h-14 bg-gradient-to-t from-white via-white/85 to-transparent"
              aria-hidden="true"
            />
          </div>

        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          CREATIVE INTERACTIVE MODALS FOR CHARTERED ACCOUNTANTS
      ───────────────────────────────────────────────────────────── */}
      {activeModal && (
        <div
          role="dialog"
          ref={dialogRef}
          tabIndex={-1}
          aria-label={activeModal === "itc" ? "ITC matching logic" : activeModal === "gstr1" ? "GSTR-1 discrepancy codes" : activeModal === "gstr3b" ? "Notice prevention checks" : "GSTR-9C audit export format"}
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 overflow-y-auto bg-black/60 backdrop-blur-xs animate-in fade-in duration-200"
          onClick={() => setActiveModal(null)}
        >
          <div
            className="relative my-auto w-full max-w-3xl overflow-hidden rounded-[16px] border border-[#E2E8F0] bg-white shadow-2xl transition-all animate-in zoom-in-95 duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            
            {/* ── MODAL 1: ITC Matching Architecture ── */}
            {activeModal === "itc" && (
              <div>
                {/* Modal Header */}
                <div className="border-b border-[#E2E8F0] bg-purple-50/50 p-5 sm:p-6">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-100 px-3 py-1 text-xs font-bold text-[#7B5CFA]">
                      <Layers className="h-3.5 w-3.5" />
                      5-Level Reconciliation Architecture
                    </span>
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      aria-label="Close module details"
                      className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <h3 className="mt-3 text-xl font-bold text-[#0A0A0A] sm:text-2xl">
                    How ReconDesk Matches Invoices Down to the Paise
                  </h3>
                  <p className="mt-1.5 text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
                    Designed specifically for CA firms to maximize legal ITC recovery without triggering Rule 37 or 17(5) scrutiny notices.
                  </p>
                </div>

                {/* Modal Body: Matching Tiers Table */}
                <div className="max-h-[60vh] overflow-y-auto p-5 sm:p-6 space-y-4 text-xs">
                  <div tabIndex={0} role="region" aria-label="Matching tiers comparison — scroll horizontally for more columns" className="rounded-[10px] border border-[#E2E8F0] overflow-hidden">
                    <table className="w-full text-left border-collapse">
                      <thead className="bg-[#FAFAFA] border-b border-[#E2E8F0] text-[11px] font-bold text-[#64748B] uppercase">
                        <tr>
                          <th className="p-3">Level</th>
                          <th className="p-3">Matching Logic &amp; Normalization</th>
                          <th className="p-3">Financial Delta</th>
                          <th className="p-3 text-right">CA Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F1F5F9] text-[12px]">
                        <tr>
                          <td className="p-3 font-bold text-[#166534]">
                            <span className="rounded bg-[#DCFCE7] px-2 py-0.5">Exact L1</span>
                          </td>
                          <td className="p-3 font-medium text-[#0F172A]">
                            Raw identical GSTIN + Invoice Number + Date + Tax
                          </td>
                          <td className="p-3 font-mono text-[#16A34A] font-bold">≤ ₹1.00</td>
                          <td className="p-3 text-right font-semibold text-[#166534]">Auto-Claimed in 3B</td>
                        </tr>
                        <tr>
                          <td className="p-3 font-bold text-[#0369A1]">
                            <span className="rounded bg-[#F0F9FF] px-2 py-0.5">Soft L2</span>
                          </td>
                          <td className="p-3 font-medium text-[#0F172A]">
                            Strips leading zeros, FY prefixes (<code>INV/2026/0941</code> ↔ <code>941</code>)
                          </td>
                          <td className="p-3 font-mono text-[#16A34A] font-bold">₹0.00</td>
                          <td className="p-3 text-right font-semibold text-[#0369A1]">Instant Auto-Merge</td>
                        </tr>
                        <tr>
                          <td className="p-3 font-bold text-[#713F12]">
                            <span className="rounded bg-[#FEF9C3] px-2 py-0.5">Fuzzy L3</span>
                          </td>
                          <td className="p-3 font-medium text-[#0F172A]">
                            Exact invoice with minor tax/date drift (1% / 30-day tolerance)
                          </td>
                          <td className="p-3 font-mono text-[#D97706] font-bold">Small Diff</td>
                          <td className="p-3 text-right font-semibold text-[#713F12]">1-Click Approval</td>
                        </tr>
                        <tr>
                          <td className="p-3 font-bold text-[#991B1B]">
                            <span className="rounded bg-[#FEF2F2] px-2 py-0.5">PAN L4</span>
                          </td>
                          <td className="p-3 font-medium text-[#0F172A]">
                            Same 10-digit vendor PAN, but billed under different state GSTIN
                          </td>
                          <td className="p-3 font-mono text-[#DC2626] font-bold">State Shift</td>
                          <td className="p-3 text-right font-semibold text-[#991B1B]">Notice Shield Flag</td>
                        </tr>
                        <tr>
                          <td className="p-3 font-bold text-[#475569]">
                            <span className="rounded bg-[#F1F5F9] px-2 py-0.5">Orphan L6</span>
                          </td>
                          <td className="p-3 font-medium text-[#0F172A]">
                            Invoices present in GSTR-2B only or recorded in Books only
                          </td>
                          <td className="p-3 font-mono text-[#64748B] font-bold">—</td>
                          <td className="p-3 text-right font-semibold text-[#7B5CFA]">Vendor Notice Log</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  {/* Statutory Checks Sub-card */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                    <div className="rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5">
                      <div className="font-bold text-[#0F172A] flex items-center gap-1.5">
                        <Clock className="h-4 w-4 text-[#EA580C]" /> Rule 37 180-Day Tracker
                      </div>
                      <p className="mt-1 text-[11px] text-[#64748B] leading-relaxed">
                        Tracks unbooked/unpaid invoices past 180 days with Section 50(1) interest calculation (18% p.a.) and proportionate partial reversal.
                      </p>
                    </div>
                    <div className="rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5">
                      <div className="font-bold text-[#0F172A] flex items-center gap-1.5">
                        <ShieldAlert className="h-4 w-4 text-[#DC2626]" /> Section 17(5) Blocked Credit
                      </div>
                      <p className="mt-1 text-[11px] text-[#64748B] leading-relaxed">
                        Evaluates 7 statutory HSN chapters (vehicles, food, clubs, works contract) to keep blocked credit out of your 3B claims.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Modal Footer Actions */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E2E8F0] bg-[#FAFAFA] p-4 sm:px-6">
                  <span className="text-xs text-[#64748B]">Zero setup required. Works with Tally, Busy &amp; Excel.</span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      className="rounded-[8px] border border-[#E2E8F0] bg-white px-4 py-2 text-xs font-semibold text-[#334155] hover:bg-[#F8FAFC]"
                    >
                      Close
                    </button>
                    <Link
                      href="/auth/signup"
                      className="inline-flex items-center gap-1.5 rounded-[8px] bg-[#7B5CFA] px-5 py-2 text-xs font-semibold text-white hover:bg-[#6C4DE6] shadow-xs"
                    >
                      <span>Start Free Reconcile</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              </div>
            )}

            {/* ── MODAL 2: GSTR-1 Discrepancy Codes ── */}
            {activeModal === "gstr1" && (
              <div>
                <div className="border-b border-[#E2E8F0] bg-emerald-50/50 p-5 sm:p-6">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-800">
                      <BarChart3 className="h-3.5 w-3.5" />
                      G1M1–G1M10 Rule Catalogue
                    </span>
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      aria-label="Close module details"
                      className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <h3 className="mt-3 text-xl font-bold text-[#0A0A0A] sm:text-2xl">
                    10 Automated Sales Mismatch Diagnostic Codes
                  </h3>
                  <p className="mt-1.5 text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
                    ReconDesk automatically tests outward sales registers against GSTR-1 returns to stop tax drift before filing.
                  </p>
                </div>

                <div className="max-h-[60vh] overflow-y-auto p-5 sm:p-6 space-y-2 text-xs">
                  {[
                    { code: "G1M1", title: "Missing in GSTR-1", desc: "Outward invoice present in sales books but missing in filed/draft GSTR-1 return." },
                    { code: "G1M2", title: "Missing in Books", desc: "Invoice reported on GSTN portal but omitted from client's accounting software." },
                    { code: "G1M3", title: "Tax Rate Drift", desc: "Taxable value matches but CGST/SGST/IGST rate classification differs (e.g. 18% vs 12%)." },
                    { code: "G1M4", title: "Customer GSTIN Error", desc: "Valid B2B invoice incorrectly categorized as B2CS unregistered cash sale." },
                    { code: "G1M5", title: "Duplicate Serial Number", desc: "Clashing document numbering series within the same financial year." },
                    { code: "G1M6", title: "CDNR Linkage Missing", desc: "Credit/Debit note filed without parent tax invoice reference." },
                    { code: "G1M7", title: "Table 13 Serial Verification", desc: "Discrepancy in total count of documents issued vs sales entries." },
                    { code: "G1M8", title: "Export LUT Check", desc: "Zero-rated export supply missing Letter of Undertaking (LUT) confirmation." },
                    { code: "G1M9", title: "POS State Code Drift", desc: "Place of supply state code differs between sales ledger and customer GSTIN." },
                    { code: "G1M10", title: "GSTR-1A Amendment Window", desc: "Tracks open GSTR-1A window to push invoice amendments before 3B auto-populates." },
                  ].map((rule) => (
                    <div key={rule.code} className="flex items-start gap-3 rounded-[8px] border border-[#E2E8F0] bg-white p-3 hover:bg-[#F8FAFC]">
                      <span className="shrink-0 rounded bg-emerald-100 font-mono text-[11px] font-bold text-emerald-800 px-2 py-0.5">
                        {rule.code}
                      </span>
                      <div>
                        <div className="font-bold text-[#0F172A]">{rule.title}</div>
                        <div className="text-[#64748B] text-[11px] mt-0.5">{rule.desc}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E2E8F0] bg-[#FAFAFA] p-4 sm:px-6">
                  <span className="text-xs text-[#64748B]">Verify sales liability in under 60 seconds.</span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      className="rounded-[8px] border border-[#E2E8F0] bg-white px-4 py-2 text-xs font-semibold text-[#334155] hover:bg-[#F8FAFC]"
                    >
                      Close
                    </button>
                    <Link
                      href="/auth/signup"
                      className="inline-flex items-center gap-1.5 rounded-[8px] bg-[#10B981] px-5 py-2 text-xs font-semibold text-white hover:bg-emerald-600 shadow-xs"
                    >
                      <span>Run Sales Check Free</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              </div>
            )}

            {/* ── MODAL 3: GSTR-3B Notice Shield ── */}
            {activeModal === "gstr3b" && (
              <div>
                <div className="border-b border-[#E2E8F0] bg-amber-50/50 p-5 sm:p-6">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-900">
                      <FileCheck2 className="h-3.5 w-3.5" />
                      Rule 88D &amp; DRC-01C Shield
                    </span>
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      aria-label="Close module details"
                      className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <h3 className="mt-3 text-xl font-bold text-[#0A0A0A] sm:text-2xl">
                    Pre-empt Department Scrutiny Notices
                  </h3>
                  <p className="mt-1.5 text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
                    Automatically checks GSTR-3B tax liability and ITC claims against statutory notice thresholds.
                  </p>
                </div>

                <div className="max-h-[60vh] overflow-y-auto p-5 sm:p-6 space-y-4 text-xs">
                  {/* Statutory Trigger Explanation */}
                  <div className="rounded-[10px] border border-amber-200 bg-[#FFFBEB] p-4">
                    <div className="flex items-center gap-2 font-bold text-amber-950 text-sm">
                      <ShieldAlert className="h-4 w-4 text-amber-600" />
                      Statutory DRC-01C Notice Trigger Rule
                    </div>
                    <p className="mt-2 text-xs text-amber-900 leading-relaxed">
                      Under Rule 88D, the GST portal generates an automated <strong>Form GST DRC-01C</strong> notice whenever the ITC claimed in <strong>Table 4(A) of GSTR-3B</strong> exceeds the ITC available in <strong>GSTR-2B</strong> by:
                    </p>
                    <div className="mt-2 flex items-center gap-3 font-mono font-bold text-xs text-amber-950 bg-white/80 rounded p-2 border border-amber-200">
                      <span>Threshold: Variance &gt; 20%</span>
                      <span>AND</span>
                      <span>Variance &gt; ₹25,00,000</span>
                    </div>
                  </div>

                  {/* Auto-Drafted Statement Preview */}
                  <div className="rounded-[10px] border border-[#E2E8F0] bg-white p-4">
                    <div className="font-bold text-[#0F172A] mb-1.5 flex items-center justify-between">
                      <span>One-Click DRC-01C Draft Reply Statement</span>
                      <span className="rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold px-2 py-0.5">CA Format</span>
                    </div>
                    <p className="text-[#64748B] text-[11px] mb-3">
                      ReconDesk generates audit-grade explanatory notes citing Section 16(4) carry-forward, credit notes, or vendor timing differences so CAs can file replies instantly.
                    </p>
                    <div className="rounded border border-[#E2E8F0] bg-[#F8FAFC] p-3 font-mono text-[11px] text-[#334155] leading-relaxed">
                      &quot;The differential ITC of ₹4,20,500 claimed in Table 4(A)(5) pertains to FY 2025–26 invoices availed in terms of Section 16(4) proviso and reconciled in ReconDesk audit log ID #RD-8842...&quot;
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E2E8F0] bg-[#FAFAFA] p-4 sm:px-6">
                  <span className="text-xs text-[#64748B]">Shield your clients from automated tax penalties.</span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      className="rounded-[8px] border border-[#E2E8F0] bg-white px-4 py-2 text-xs font-semibold text-[#334155] hover:bg-[#F8FAFC]"
                    >
                      Close
                    </button>
                    <Link
                      href="/auth/signup"
                      className="inline-flex items-center gap-1.5 rounded-[8px] bg-[#D97706] px-5 py-2 text-xs font-semibold text-white hover:bg-amber-700 shadow-xs"
                    >
                      <span>Try Notice Shield Free</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              </div>
            )}

            {/* ── MODAL 4: GSTR-9C Annual Audit Workbook ── */}
            {activeModal === "gstr9c" && (
              <div>
                <div className="border-b border-[#E2E8F0] bg-blue-50/50 p-5 sm:p-6">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 px-3 py-1 text-xs font-bold text-blue-800">
                      <FileSpreadsheet className="h-3.5 w-3.5" />
                      Annual Audit Certification Format
                    </span>
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      aria-label="Close module details"
                      className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <h3 className="mt-3 text-xl font-bold text-[#0A0A0A] sm:text-2xl">
                    12-Month Multi-Sheet FY Audit Workbook
                  </h3>
                  <p className="mt-1.5 text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
                    Export complete annual audit workpapers with Table 8A/8B tie-outs, vendor PAN rollups, and observation logs.
                  </p>
                </div>

                <div className="max-h-[60vh] overflow-y-auto p-5 sm:p-6 space-y-3 text-xs">
                  <div className="rounded-[10px] border border-[#E2E8F0] divide-y divide-[#F1F5F9] bg-white">
                    <div className="p-3.5 flex items-start gap-3">
                      <span className="rounded bg-blue-100 text-blue-800 font-bold px-2 py-0.5 text-[11px] shrink-0 font-mono">Sheet 1</span>
                      <div>
                        <div className="font-bold text-[#0F172A]">Table 8A vs Table 8B/8C FY Cumulative Tie-Out</div>
                        <div className="text-[#64748B] text-[11px] mt-0.5">Consolidates 12 monthly GSTR-2B returns against purchase register claims with multi-period variance breakdown.</div>
                      </div>
                    </div>
                    <div className="p-3.5 flex items-start gap-3">
                      <span className="rounded bg-blue-100 text-blue-800 font-bold px-2 py-0.5 text-[11px] shrink-0 font-mono">Sheet 2</span>
                      <div>
                        <div className="font-bold text-[#0F172A]">Supplier-Wise Annual ITC Breakdown (10-Digit PAN Grouped)</div>
                        <div className="text-[#64748B] text-[11px] mt-0.5">Ranks top vendors by transaction volume, un-reconciled balances, and late filing frequency across all branches.</div>
                      </div>
                    </div>
                    <div className="p-3.5 flex items-start gap-3">
                      <span className="rounded bg-blue-100 text-blue-800 font-bold px-2 py-0.5 text-[11px] shrink-0 font-mono">Sheet 3</span>
                      <div>
                        <div className="font-bold text-[#0F172A]">Severity-Ranked Audit Observations Log</div>
                        <div className="text-[#64748B] text-[11px] mt-0.5">High/Medium/Low risk findings with statutory section references ready for direct inclusion in CA audit reports.</div>
                      </div>
                    </div>
                    <div className="p-3.5 flex items-start gap-3">
                      <span className="rounded bg-blue-100 text-blue-800 font-bold px-2 py-0.5 text-[11px] shrink-0 font-mono">Sheet 4</span>
                      <div>
                        <div className="font-bold text-[#0F172A]">Rule 37 Reversal &amp; Section 17(5) Schedule</div>
                        <div className="text-[#64748B] text-[11px] mt-0.5">Itemized list of invoices exceeding 180 days with partial settlement history and blocked credit categories.</div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E2E8F0] bg-[#FAFAFA] p-4 sm:px-6">
                  <span className="text-xs text-[#64748B]">Complete FY audit rollups generated in under 10 seconds.</span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setActiveModal(null)}
                      className="rounded-[8px] border border-[#E2E8F0] bg-white px-4 py-2 text-xs font-semibold text-[#334155] hover:bg-[#F8FAFC]"
                    >
                      Close
                    </button>
                    <Link
                      href="/auth/signup"
                      className="inline-flex items-center gap-1.5 rounded-[8px] bg-[#2563EB] px-5 py-2 text-xs font-semibold text-white hover:bg-blue-700 shadow-xs"
                    >
                      <span>Generate 9C Workpapers Free</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              </div>
            )}

          </div>
        </div>
      )}
    </section>
  );
}
