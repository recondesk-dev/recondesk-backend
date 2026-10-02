"use client";

import { useEffect, useState, useRef } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Download,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  Layers,
  Mail,
  Receipt,
  RotateCw,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const RULE_COUNT_FALLBACK = "103+";

export function FeatureStatsStrip() {
  const [ruleCount, setRuleCount] = useState(RULE_COUNT_FALLBACK);
  const [copiedLetter, setCopiedLetter] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/rules/summary`)
      .then((res) => {
        if (!res.ok) throw new Error("Rules summary request failed");
        return res.json() as Promise<{ total?: number }>;
      })
      .then((data) => {
        if (cancelled) return;
        const total = typeof data.total === "number" ? data.total : null;
        if (total !== null && total > 0) {
          setRuleCount(`${total}+`);
        }
      })
      .catch(() => {
        // Keep fallback on error
      });
    return () => {
      cancelled = true;
      if (copyTimer.current) clearTimeout(copyTimer.current);
    };
  }, []);

  const handleCopyNotice = async () => {
    setCopyError(false);
    try {
      await navigator.clipboard.writeText("Dear Supplier, 3 invoices are missing in GSTR-2B. Please file before the statutory cut-off...");
      setCopiedLetter(true);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopiedLetter(false), 2000);
    } catch {
      setCopiedLetter(false);
      setCopyError(true);
    }
  };

  return (
    <section
      id="engine"
      className="mx-auto mt-20 mb-12 max-w-6xl px-4 sm:px-6 lg:px-8"
      aria-label="Product capabilities"
    >
      {/* Section Header */}
      <div className="text-center max-w-3xl mx-auto">
        <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
          Engine Specifications
        </p>
        <h2 className="mt-2.5 text-2xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-3xl">
          What&apos;s Under the Hood
        </h2>
        <p className="mt-2 text-sm text-[#6B6B6B] leading-relaxed">
          Here is what happens in the 20 seconds after you upload your GSTR files and purchase registers.
        </p>
      </div>

      {/* ─── Creative Engine Specs Bento Grid ─── */}
      <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-3">
        
        {/* ── Card 1: 103+ Rules Engine (Spans 2 columns on desktop) ── */}
        <div className="md:col-span-2 relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-50 px-3 py-1 text-xs font-bold text-[#7B5CFA] border border-purple-100">
                <Zap className="h-3.5 w-3.5" />
                Rule Execution Core
              </span>
              <span className="font-mono text-[11px] font-semibold text-[#64748B] bg-[#F8FAFC] px-2 py-0.5 rounded border border-[#E2E8F0]">
                MAT_001 → MAT_{ruleCount}
              </span>
            </div>

            <h3 className="mt-4 text-xl font-bold text-[#0A0A0A] sm:text-2xl">
              {ruleCount} Statutory Rules Running in Parallel
            </h3>
            <p className="mt-1 text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
              Every invoice is verified against hardcoded Indian GST statutory logic — from Section 16(2) filing proofs to paise-level round-offs.
            </p>

            {/* Live Interactive Rule Checklist Simulation */}
            <div className="mt-5 space-y-2 font-mono text-xs">
              <div className="flex items-center justify-between rounded-[8px] border border-emerald-100 bg-[#F0FDF4] p-2.5 px-3">
                <span className="flex items-center gap-2 text-[#166534] font-medium text-[11px]">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                  <span>Invoice Number Normalization (INV/2026/0941 ↔ 941)</span>
                </span>
                <span className="rounded bg-emerald-200/60 px-1.5 py-0.2 text-[9px] font-bold text-[#166534]">
                  PASSED
                </span>
              </div>

              <div className="flex items-center justify-between rounded-[8px] border border-purple-100 bg-[#FAF5FF] p-2.5 px-3">
                <span className="flex items-center gap-2 text-[#6B21A8] font-medium text-[11px]">
                  <CheckCircle2 className="h-3.5 w-3.5 text-[#7B5CFA] shrink-0" />
                  <span>Section 16(2)(aa) Supplier Filing Verification</span>
                </span>
                <span className="rounded bg-purple-200/60 px-1.5 py-0.2 text-[9px] font-bold text-[#6B21A8]">
                  VERIFIED IN 2B
                </span>
              </div>

              <div className="flex items-center justify-between rounded-[8px] border border-amber-100 bg-[#FFFBEB] p-2.5 px-3">
                <span className="flex items-center gap-2 text-[#92400E] font-medium text-[11px]">
                  <CheckCircle2 className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                  <span>Credit/Debit Note Quarantine (14 Notes Isolated)</span>
                </span>
                <span className="rounded bg-amber-200/60 px-1.5 py-0.2 text-[9px] font-bold text-[#92400E]">
                  QUARANTINED
                </span>
              </div>

              <div className="flex items-center justify-between rounded-[8px] border border-blue-100 bg-[#EFF6FF] p-2.5 px-3">
                <span className="flex items-center gap-2 text-[#1E40AF] font-medium text-[11px]">
                  <CheckCircle2 className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                  <span>Rule 88D Statutory Notice Threshold Monitoring</span>
                </span>
                <span className="rounded bg-blue-200/60 px-1.5 py-0.2 text-[9px] font-bold text-[#1E40AF]">
                  SAFE (&lt;20%)
                </span>
              </div>
            </div>
          </div>

          <div className="mt-5 pt-4 border-t border-[#F1F5F9] flex flex-wrap items-center justify-between gap-3 text-xs text-[#64748B]">
            <span className="font-semibold text-[#0F172A]">0% Manual VLOOKUP Errors</span>
            <span className="text-[11px]">Processed in worker tasks under 20s</span>
          </div>
        </div>

        {/* ── Card 2: 5-Level Match Hierarchy Bar (1 column on desktop) ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700 border border-blue-100">
                <Layers className="h-3.5 w-3.5" />
                Multi-Phase Matcher
              </span>
              <span className="text-[11px] font-bold text-emerald-600">
                97% Auto-Resolved
              </span>
            </div>

            <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
              5-Level Multi-Tier Resolution
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              Categorizes invoices by confidence so your team only reviews true edge cases.
            </p>

            {/* Segmented Match Distribution Progress Bar */}
            <div className="mt-4 space-y-2">
              <div className="h-3 w-full overflow-hidden rounded-full bg-[#F1F5F9] flex gap-0.5 p-0.5">
                <div className="h-full bg-emerald-500 rounded-l-full" style={{ width: "62%" }} title="L1 Exact: 62%" />
                <div className="h-full bg-blue-500" style={{ width: "18%" }} title="L2 Format: 18%" />
                <div className="h-full bg-amber-500" style={{ width: "11%" }} title="L3 Drift: 11%" />
                <div className="h-full bg-purple-500" style={{ width: "6%" }} title="L4 PAN: 6%" />
                <div className="h-full bg-gray-400 rounded-r-full" style={{ width: "3%" }} title="L6 Orphan: 3%" />
              </div>

              {/* Breakdown Rows */}
              <div className="space-y-1.5 text-[11px] pt-1">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 font-medium text-[#334155]">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    L1 Exact Match (≤₹1 paise)
                  </span>
                  <span className="font-bold text-[#0F172A] tabular-nums">62%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 font-medium text-[#334155]">
                    <span className="h-2 w-2 rounded-full bg-blue-500" />
                    L2 Format Normalized
                  </span>
                  <span className="font-bold text-[#0F172A] tabular-nums">18%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 font-medium text-[#334155]">
                    <span className="h-2 w-2 rounded-full bg-amber-500" />
                    L3 Value / Date Drift
                  </span>
                  <span className="font-bold text-[#0F172A] tabular-nums">11%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 font-medium text-[#334155]">
                    <span className="h-2 w-2 rounded-full bg-purple-500" />
                    L4 Multi-State PAN Match
                  </span>
                  <span className="font-bold text-[#0F172A] tabular-nums">6%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 font-medium text-[#334155]">
                    <span className="h-2 w-2 rounded-full bg-gray-400" />
                    L6 Orphan (2B / Books Only)
                  </span>
                  <span className="font-bold text-[#0F172A] tabular-nums">3%</span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#F1F5F9] text-[11px] text-[#64748B]">
            Eliminates spreadsheet crashing on 10k+ rows
          </div>
        </div>

        {/* ── Card 3: Rule 37 180-Day Countdown (1 column) ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-orange-50 px-3 py-1 text-xs font-bold text-orange-700 border border-orange-100">
                <Clock className="h-3.5 w-3.5" />
                Rule 37 Tracker
              </span>
              <span className="rounded bg-orange-100 text-orange-800 text-[10px] font-bold px-1.5 py-0.5">
                Sec 50(1)
              </span>
            </div>

            <h3 className="mt-4 text-base font-bold text-[#0A0A0A]">
              180-Day Payment Reversal Alert
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              Tracks unpaid supplier invoices past 180 days with automatic interest calculations.
            </p>

            <div className="mt-4 rounded-[10px] border border-orange-200 bg-[#FFF7ED] p-3 text-xs">
              <div className="flex items-center justify-between font-bold text-orange-950">
                <span>Overdue Invoices:</span>
                <span className="tabular-nums">3 Invoices</span>
              </div>
              <div className="flex items-center justify-between text-orange-800 mt-1">
                <span>ITC Reversal Risk:</span>
                <span className="font-bold tabular-nums">₹1,15,400</span>
              </div>
              <div className="mt-2 pt-2 border-t border-orange-200/70 text-[10px] text-orange-900 font-medium">
                ⚡ Auto-calculates 18% p.a. interest penalty + proportional partial payments.
              </div>
            </div>
          </div>

          <div className="mt-4 text-[11px] text-[#64748B]">
            Never miss a mandatory reversal before audit
          </div>
        </div>

        {/* ── Card 4: Section 17(5) 7-Chapter Scanner (1 column) ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1 text-xs font-bold text-red-700 border border-red-100">
                <ShieldAlert className="h-3.5 w-3.5" />
                Blocked Credit Shield
              </span>
              <span className="rounded bg-red-100 text-red-800 text-[10px] font-bold px-1.5 py-0.5">
                Sec 17(5)
              </span>
            </div>

            <h3 className="mt-4 text-base font-bold text-[#0A0A0A]">
              Section 17(5) Blocked Credit Scanner
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              Detects restricted expenses in books before wrongful credit is claimed in GSTR-3B.
            </p>

            {/* HSN Badges Cloud */}
            <div className="mt-3.5 flex flex-wrap gap-1.5 text-[10px]">
              <span className="rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-1 font-semibold text-[#334155]">
                8703 Motor Vehicles
              </span>
              <span className="rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-1 font-semibold text-[#334155]">
                9963 Food &amp; Catering
              </span>
              <span className="rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-1 font-semibold text-[#334155]">
                9972 Club Member
              </span>
              <span className="rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-1 font-semibold text-[#334155]">
                9954 Works Contract
              </span>
              <span className="rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-1 font-semibold text-[#334155]">
                9993 Health / Personal
              </span>
              <span className="rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-1 font-semibold text-[#334155]">
                2106 Tobacco
              </span>
            </div>
          </div>

          <div className="mt-4 text-[11px] text-[#64748B]">
            Advisory warnings with statutory exempt notes
          </div>
        </div>

        {/* ── Card 5: 1-Click Defaulting Vendor Demand Letters (1 column) ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 border border-emerald-100">
                <Mail className="h-3.5 w-3.5" />
                Vendor Recovery
              </span>
              <span className="rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold px-1.5 py-0.5">
                1-Click
              </span>
            </div>

            <h3 className="mt-4 text-base font-bold text-[#0A0A0A]">
              Automated Vendor Notice Letters
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              Stop chasing defaulting suppliers on WhatsApp. Generate itemized demand letters in seconds.
            </p>

            {/* Inset Letter Preview */}
            <div className="mt-3.5 rounded-[8px] border border-[#E2E8F0] bg-[#F8FAFC] p-2.5 font-mono text-[10px] text-[#475569]">
              <div className="font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-1 flex justify-between">
                <span>Notice: Missing GSTR-1 Invoices</span>
                <span className="text-[#16A34A]">₹2.95L</span>
              </div>
              <p className="mt-1.5 text-[9.5px] leading-tight text-[#64748B]">
                &quot;Dear Supplier, 3 invoices are missing in GSTR-2B. Please file before the statutory cut-off...&quot;
              </p>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between pt-2 border-t border-[#F1F5F9]">
            <button
              type="button"
              onClick={handleCopyNotice}
              aria-live="polite"
              className="inline-flex items-center gap-1 text-[11px] font-bold text-[#7B5CFA] hover:text-[#6C4DE6]"
            >
              {copiedLetter ? (
                <>
                  <Check className="h-3 w-3 text-emerald-600" />
                  <span className="text-emerald-600">Copied to clipboard!</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  <span>Copy Sample Notice</span>
                </>
              )}
            </button>
            <span className="text-[10px] text-[#94A3B8]">PDF &amp; Excel Export</span>
            {copyError && <span role="status" className="text-[10px] text-red-700">Copy unavailable. Please select the sample notice above.</span>}
          </div>
        </div>

      </div>
    </section>
  );
}
