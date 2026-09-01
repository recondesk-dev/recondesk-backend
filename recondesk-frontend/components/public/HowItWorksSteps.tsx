"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  Download,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  Layers,
  Lock,
  Mail,
  Play,
  Pause,
  Receipt,
  RotateCw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
  Zap,
} from "lucide-react";

type StageId = 0 | 1 | 2;

export function HowItWorksSteps() {
  const [activeStage, setActiveStage] = useState<StageId>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [matchProgress, setMatchProgress] = useState<number>(100);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Auto-advance stages every 5 seconds when playing
  useEffect(() => {
    if (!isPlaying) return;

    timerRef.current = setInterval(() => {
      setActiveStage((prev) => ((prev + 1) % 3) as StageId);
    }, 5200);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying]);

  // Reset match progress animation when switching to match stage
  useEffect(() => {
    if (activeStage === 1) {
      setMatchProgress(15);
      const t1 = setTimeout(() => setMatchProgress(45), 400);
      const t2 = setTimeout(() => setMatchProgress(82), 1000);
      const t3 = setTimeout(() => setMatchProgress(100), 1600);
      return () => {
        clearTimeout(t1);
        clearTimeout(t2);
        clearTimeout(t3);
      };
    }
  }, [activeStage]);

  const stages = [
    {
      id: 0 as StageId,
      stepNum: "01",
      title: "Upload & Auto-Detect",
      subtitle: "GSTR-2B JSON + Tally, Busy, or Excel registers",
      badge: "2 Files or OTP",
      icon: UploadCloud,
    },
    {
      id: 1 as StageId,
      stepNum: "02",
      title: "20-Second Match Engine",
      subtitle: "5-Level matching & Rule 37 / §17(5) automated scan",
      badge: "103+ Rules",
      icon: Cpu,
    },
    {
      id: 2 as StageId,
      stepNum: "03",
      title: "Decision-Ready Audit Files",
      subtitle: "1-Click 3B claims, vendor demand letters & Excel exports",
      badge: "Audit Ready",
      icon: FileCheck2,
    },
  ];

  return (
    <div className="mx-auto max-w-5xl">
      
      {/* ─── Top Stage Selector Navigation ─── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {stages.map((stage) => {
          const isActive = activeStage === stage.id;
          const Icon = stage.icon;

          return (
            <button
              key={stage.id}
              type="button"
              onClick={() => {
                setActiveStage(stage.id);
                setIsPlaying(false);
              }}
              className={`relative flex flex-col justify-between rounded-[14px] border p-4 sm:p-5 text-left transition-all duration-300 ${
                isActive
                  ? "border-[#7B5CFA] bg-white shadow-[0_12px_30px_rgba(123,92,250,0.08)] ring-1 ring-[#7B5CFA]/20"
                  : "border-[#E5E5E2] bg-white/70 hover:bg-white hover:border-[#CBD5E1]"
              }`}
            >
              {/* Active Progress Accent Top Bar */}
              {isActive && (
                <div className="absolute top-0 left-0 right-0 h-1 bg-[#7B5CFA] rounded-t-[14px]" />
              )}

              <div>
                <div className="flex items-center justify-between">
                  <span
                    className={`font-mono text-xs font-bold ${
                      isActive ? "text-[#7B5CFA]" : "text-[#94A3B8]"
                    }`}
                  >
                    STEP {stage.stepNum}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                      isActive
                        ? "bg-purple-50 text-[#7B5CFA] border border-purple-100"
                        : "bg-[#F1F5F9] text-[#64748B]"
                    }`}
                  >
                    {stage.badge}
                  </span>
                </div>

                <div className="mt-3 flex items-center gap-2">
                  <div
                    className={`flex h-8 w-8 items-center justify-center rounded-[8px] transition-colors ${
                      isActive
                        ? "bg-[#7B5CFA] text-white"
                        : "bg-[#F1F5F9] text-[#64748B]"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </div>
                  <h3 className="text-sm font-bold text-[#0A0A0A]">
                    {stage.title}
                  </h3>
                </div>

                <p className="mt-2 text-xs text-[#6B6B6B] leading-relaxed">
                  {stage.subtitle}
                </p>
              </div>

              {/* Progress timer indicator when playing */}
              {isActive && isPlaying && (
                <div className="mt-4 h-1 w-full overflow-hidden rounded-full bg-purple-100">
                  <div className="h-full bg-[#7B5CFA] animate-[heroFadeUp_5.2s_linear]" />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* ─── Main Animated Studio Canvas ─── */}
      <div className="relative mt-8 overflow-hidden rounded-[16px] border border-[#E2E8F0] bg-white shadow-[0_20px_50px_-12px_rgba(0,0,0,0.1)]">
        
        {/* Studio Window Chrome Bar */}
        <div className="flex items-center justify-between border-b border-[#E2E8F0] bg-[#FAFAFA] px-4 py-2.5">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-[#EF4444]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#F59E0B]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#10B981]" />
            <span className="ml-2 font-mono text-[11px] text-[#64748B] hidden sm:inline-block">
              app.recondesk.in/reconcile/
              {activeStage === 0
                ? "wizard/upload"
                : activeStage === 1
                ? "engine/processing"
                : "runs/5eb64c7c/results"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsPlaying(!isPlaying)}
              className="inline-flex items-center gap-1.5 rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#475569] hover:bg-[#F8FAFC]"
            >
              {isPlaying ? (
                <>
                  <Pause className="h-3 w-3 text-[#7B5CFA]" />
                  <span>Pause Demo</span>
                </>
              ) : (
                <>
                  <Play className="h-3 w-3 text-[#16A34A]" />
                  <span>Play Demo</span>
                </>
              )}
            </button>
            <span className="rounded bg-[#F1F5F9] px-2 py-1 font-mono text-[10px] text-[#64748B]">
              Stage {activeStage + 1} of 3
            </span>
          </div>
        </div>

        {/* ─── STAGE 1: INGESTION (Dropzone & Column Mapping) ─── */}
        {activeStage === 0 && (
          <div className="p-6 sm:p-8 animate-in fade-in duration-300">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#F1F5F9] pb-4">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-[#7B5CFA]">
                  Step 1 · Data Ingestion
                </span>
                <h4 className="mt-1 text-lg font-bold text-[#0A0A0A]">
                  Upload 2 Files or Connect GSTN via OTP
                </h4>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700 border border-emerald-100">
                <Check className="h-3.5 w-3.5" /> Auto Column Detection Active
              </span>
            </div>

            {/* Ingestion Cards */}
            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
              
              {/* File A: GSTR-2B */}
              <div className="rounded-[12px] border border-[#E2E8F0] bg-[#F8FAFC] p-4 font-mono text-xs">
                <div className="flex items-center justify-between text-[#0F172A] font-bold">
                  <span className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-[#7B5CFA]" />
                    <span>GSTR2B_July2026.json</span>
                  </span>
                  <span className="text-[10px] text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">
                    PARSED
                  </span>
                </div>
                <div className="mt-3 space-y-1 text-[11px] text-[#64748B]">
                  <div className="flex justify-between">
                    <span>Source:</span>
                    <span className="font-semibold text-[#0F172A]">GST Portal JSON</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Invoices Found:</span>
                    <span className="font-semibold text-[#0F172A]">1,438 Invoices</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Total ITC Value:</span>
                    <span className="font-bold text-[#16A34A]">₹48,24,650</span>
                  </div>
                </div>
              </div>

              {/* File B: Purchase Register */}
              <div className="rounded-[12px] border border-[#E2E8F0] bg-[#F8FAFC] p-4 font-mono text-xs">
                <div className="flex items-center justify-between text-[#0F172A] font-bold">
                  <span className="flex items-center gap-2">
                    <FileSpreadsheet className="h-4 w-4 text-emerald-600" />
                    <span>Tally_Purchase_Register.xlsx</span>
                  </span>
                  <span className="text-[10px] text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">
                    MAPPED
                  </span>
                </div>
                <div className="mt-3 space-y-1 text-[11px] text-[#64748B]">
                  <div className="flex justify-between">
                    <span>Accounting Stack:</span>
                    <span className="font-semibold text-[#0F172A]">Tally Prime / Busy / Excel</span>
                  </div>
                  <div className="flex justify-between">
                    <span>PR Rows Read:</span>
                    <span className="font-semibold text-[#0F172A]">1,438 Invoices</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Auto-Mapped Headers:</span>
                    <span className="font-bold text-emerald-700">GSTIN, Inv#, Date, Tax</span>
                  </div>
                </div>
              </div>

            </div>

            {/* Auto-Mapped Column Badges */}
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-emerald-100 bg-[#F0FDF4] p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-bold text-[#166534]">Detected Schema:</span>
                <span className="rounded bg-white px-2 py-0.5 font-mono text-[11px] text-[#166534] border border-emerald-200">
                  GSTIN ✓
                </span>
                <span className="rounded bg-white px-2 py-0.5 font-mono text-[11px] text-[#166534] border border-emerald-200">
                  Invoice No ✓
                </span>
                <span className="rounded bg-white px-2 py-0.5 font-mono text-[11px] text-[#166534] border border-emerald-200">
                  Taxable Value ✓
                </span>
                <span className="rounded bg-white px-2 py-0.5 font-mono text-[11px] text-[#166534] border border-emerald-200">
                  IGST/CGST/SGST ✓
                </span>
              </div>
              <span className="font-semibold text-[#166534] text-[11px]">
                Ready to Reconcile
              </span>
            </div>
          </div>
        )}

        {/* ─── STAGE 2: 20-SECOND MATCH ENGINE (Execution Radar) ─── */}
        {activeStage === 1 && (
          <div className="p-6 sm:p-8 animate-in fade-in duration-300">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#F1F5F9] pb-4">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-[#7B5CFA]">
                  Step 2 · Multi-Phase Execution
                </span>
                <h4 className="mt-1 text-lg font-bold text-[#0A0A0A]">
                  103+ Statutory Rules Matching 1,438 Invoices
                </h4>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-50 px-3 py-1 text-xs font-bold text-[#7B5CFA] border border-purple-100 font-mono">
                <RotateCw className="h-3.5 w-3.5 animate-spin text-[#7B5CFA]" />
                Worker Elapsed: 14.8s
              </span>
            </div>

            {/* Live Progress Bar */}
            <div className="mt-6 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-[#0F172A]">Processing Pipeline Status</span>
                <span className="font-mono font-bold text-[#7B5CFA]">{matchProgress}% Complete</span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-[#F1F5F9]">
                <div
                  className="h-full bg-[#7B5CFA] transition-all duration-500 rounded-full"
                  style={{ width: `${matchProgress}%` }}
                />
              </div>
            </div>

            {/* Live Engine Multi-Phase Log */}
            <div className="mt-5 space-y-2 font-mono text-xs">
              <div className="flex items-center justify-between rounded-[8px] border border-emerald-100 bg-[#F0FDF4] p-2.5 px-3">
                <span className="flex items-center gap-2 text-[#166534]">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                  <span>Phase 1: Quarantining Credit/Debit Notes (14 Notes Isolated)</span>
                </span>
                <span className="font-bold text-emerald-700">DONE</span>
              </div>

              <div className="flex items-center justify-between rounded-[8px] border border-purple-100 bg-[#FAF5FF] p-2.5 px-3">
                <span className="flex items-center gap-2 text-[#6B21A8]">
                  <CheckCircle2 className="h-3.5 w-3.5 text-[#7B5CFA] shrink-0" />
                  <span>Phase 2: L1 Exact Match &amp; L2 Prefix Normalization (INV/2026/0941 ↔ 941)</span>
                </span>
                <span className="font-bold text-[#7B5CFA]">875 MATCHED (90%)</span>
              </div>

              <div className="flex items-center justify-between rounded-[8px] border border-orange-100 bg-[#FFF7ED] p-2.5 px-3">
                <span className="flex items-center gap-2 text-[#C2410C]">
                  <Clock className="h-3.5 w-3.5 text-[#EA580C] shrink-0" />
                  <span>Phase 3: Rule 37 180-Day Payment Deadline &amp; Interest Scan</span>
                </span>
                <span className="font-bold text-[#C2410C]">3 REVERSALS FLAGGED</span>
              </div>
            </div>
          </div>
        )}

        {/* ─── STAGE 3: DECIDE (1-Click Action Cards) ─── */}
        {activeStage === 2 && (
          <div className="p-6 sm:p-8 animate-in fade-in duration-300">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#F1F5F9] pb-4">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-[#7B5CFA]">
                  Step 3 · Decision-Ready Results
                </span>
                <h4 className="mt-1 text-lg font-bold text-[#0A0A0A]">
                  Every Mismatch Explained: What, Why &amp; Next Action
                </h4>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700 border border-emerald-100">
                <Check className="h-3.5 w-3.5" /> 100% Audit Ready
              </span>
            </div>

            {/* Decision Action Rows */}
            <div className="mt-5 space-y-2.5 text-xs">
              
              {/* Row 1: Auto-Claim in 3B */}
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-[#E2E8F0] bg-white p-3 px-4 shadow-2xs hover:bg-[#F8FAFC] transition">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-[#0F172A]">Tata Steel Ltd</span>
                    <span className="rounded bg-[#DCFCE7] px-1.5 py-0.2 text-[10px] font-bold text-[#166534]">
                      Exact L1
                    </span>
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-[#64748B]">
                    INV/2026/8841 · Taxable: ₹14,80,000 · Discrepancy: ₹0
                  </p>
                </div>

                <span className="inline-flex items-center gap-1 rounded bg-[#0F172A] px-3 py-1.5 text-xs font-semibold text-white shadow-xs">
                  <Check className="h-3 w-3 text-emerald-400" />
                  Claim in 3B
                </span>
              </div>

              {/* Row 2: Send Vendor Notice */}
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-red-200 bg-[#FFF7F7] p-3 px-4 shadow-2xs hover:bg-red-50/50 transition">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-[#0F172A]">Reliance Retail Ltd</span>
                    <span className="rounded bg-[#FEE2E2] px-1.5 py-0.2 text-[10px] font-bold text-[#991B1B]">
                      Missing in 2B
                    </span>
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-[#DC2626]">
                    RR/88329 · ₹2,95,000 Unclaimed · Action: Request Supplier GSTR-1A
                  </p>
                </div>

                <span className="inline-flex items-center gap-1 rounded bg-[#7B5CFA] px-3 py-1.5 text-xs font-semibold text-white shadow-xs">
                  <Mail className="h-3 w-3" />
                  Send Vendor Notice
                </span>
              </div>

              {/* Row 3: Rule 37 180-Day Alert */}
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-orange-200 bg-[#FFFBF7] p-3 px-4 shadow-2xs hover:bg-orange-50/50 transition">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-[#0F172A]">Kalyani Heavy Motors</span>
                    <span className="rounded bg-[#FFEDD5] px-1.5 py-0.2 text-[10px] font-bold text-[#C2410C]">
                      Rule 37 (178d)
                    </span>
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-[#C2410C]">
                    KM/7710 · ₹1,15,400 at Risk · Due in 2 Days to Avoid 18% Interest
                  </p>
                </div>

                <span className="inline-flex items-center gap-1 rounded border border-[#FED7AA] bg-[#FFF7ED] px-3 py-1.5 text-xs font-bold text-[#C2410C]">
                  <Clock className="h-3 w-3" />
                  Payment Due Alert
                </span>
              </div>

            </div>

            {/* Bottom Export Bar */}
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[#F1F5F9] pt-4 text-xs">
              <span className="font-semibold text-[#0F172A]">
                Ready for GSTR-3B Filing &amp; Audit Sign-Off
              </span>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded border border-[#E2E8F0] bg-white px-2.5 py-1 text-xs font-medium text-[#475569]">
                  <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600" />
                  Multi-Sheet .XLSX
                </span>
                <span className="inline-flex items-center gap-1 rounded border border-[#E2E8F0] bg-white px-2.5 py-1 text-xs font-medium text-[#475569]">
                  <FileText className="h-3.5 w-3.5 text-blue-600" />
                  PDF Audit Summary
                </span>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
