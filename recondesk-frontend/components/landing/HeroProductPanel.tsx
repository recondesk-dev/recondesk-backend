"use client";

import { useState } from "react";
import { Logo } from "@/components/ui/Logo";
import {
  AlertTriangle,
  ArrowDownToLine,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  Filter,
  Layers,
  Search,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";

export function HeroProductPanel() {
  const [activeTab, setActiveTab] = useState<
    "matched" | "review_required" | "itc" | "risk" | "rule37" | "ims"
  >("matched");

  const tabs = [
    { id: "matched" as const, label: "Matched", count: 1280, color: "text-[#16A34A]" },
    { id: "review_required" as const, label: "Review Required", count: 38, color: "text-[#D97706]" },
    { id: "itc" as const, label: "Missed ITC", count: 14, color: "text-[#DC2626]" },
    { id: "risk" as const, label: "ITC at Risk", count: 6, color: "text-[#DC2626]" },
    { id: "rule37" as const, label: "Rule 37", count: 3, color: "text-[#EA580C]" },
    { id: "ims" as const, label: "IMS Actions", count: 8, color: "text-[#7B5CFA]" },
  ];

  return (
    <div className="relative z-10 mx-auto w-full max-w-6xl px-1 sm:px-4">
      {/* Outer Panel Chrome Frame with soft drop shadow lifting off white page */}
      <div className="overflow-hidden rounded-[14px] border border-[#E2E8F0] bg-white shadow-[0_25px_60px_-15px_rgba(0,0,0,0.12)] transition-all duration-300">
        
        {/* App Chrome Top Navigation / Context Bar */}
        <div className="flex flex-wrap items-center justify-between border-b border-[#E2E8F0] bg-[#FAFAFA] px-4 py-3 sm:px-6">
          {/* Breadcrumb & Client Info */}
          <div className="flex min-w-0 items-center gap-2 text-xs">
            <Logo height={20} />
            <span className="text-[#CBD5E1]">/</span>
            <span className="font-semibold text-[#0F172A] truncate max-w-[150px] sm:max-w-none">
              Aarav Textiles Ltd
            </span>
            <span className="text-[#CBD5E1]">/</span>
            <span className="font-medium text-[#64748B]">Q2 FY 2026–27</span>
            <span className="hidden rounded border border-[#E2E8F0] bg-white px-2 py-0.5 font-mono text-[11px] text-[#64748B] sm:inline-block">
              27AABCT3921P1ZK
            </span>
          </div>

          {/* Action Toolbar */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1 text-xs font-semibold text-[#334155] hover:bg-[#F8FAFC]"
            >
              <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600" />
              <span>Export XLSX</span>
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1 text-xs font-semibold text-[#334155] hover:bg-[#F8FAFC]"
            >
              <FileText className="h-3.5 w-3.5 text-blue-600" />
              <span>PDF Report</span>
            </button>
            <span className="inline-flex items-center gap-1 rounded-md bg-[#DC2626] px-3 py-1 text-xs font-semibold text-white">
              Finalize Run
            </span>
          </div>
        </div>

        {/* Dashboard Body Area */}
        <div className="p-4 sm:p-6 space-y-4 bg-[#F8FAFC]">
          
          {/* 1. Real KPI Grid (Run Summary + Action Required Split) */}
          <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
            
            {/* Left Card: Run Total & Progress */}
            <div className="flex items-center gap-4 sm:gap-6 rounded-[10px] border border-[#E2E8F0] bg-white p-4 sm:p-5 shadow-xs">
              <div className="min-w-[76px] text-center">
                <div className="text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">
                  Run Total
                </div>
                <div className="mt-1 text-3xl font-black text-[#0F172A] tabular-nums">
                  1,438
                </div>
                <div className="text-[11px] text-[#94A3B8]">invoices</div>
              </div>

              <div className="h-12 w-[1px] bg-[#F1F5F9]" />

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between text-xs text-[#64748B] mb-1.5">
                  <span className="font-bold uppercase tracking-wider text-[#94A3B8]">
                    Clean Matched
                  </span>
                  <span className="font-bold text-[#16A34A] tabular-nums">
                    1,280 · 89.0%
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#F1F5F9]">
                  <div
                    className="h-full rounded-full bg-[#16A34A] transition-all"
                    style={{ width: "89%" }}
                  />
                </div>
                <div className="mt-1.5 text-[11px] font-medium text-[#64748B]">
                  158 invoices require CA decision
                </div>
              </div>

              <div className="hidden sm:block h-12 w-[1px] bg-[#F1F5F9]" />

              <div className="hidden sm:block min-w-[70px] text-center">
                <div className="text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">
                  Assigned
                </div>
                <div className="mt-1 text-xs font-bold text-[#0F172A]">
                  CA Team
                </div>
                <div className="text-[10px] text-emerald-600 font-medium">● Verified</div>
              </div>
            </div>

            {/* Right Card: Action Required Drilldown */}
            <div className="overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-white shadow-xs">
              <div className="flex items-center justify-between border-b border-[#FEE2E2] bg-[#FFF7F7] px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#DC2626]" />
                  <span className="text-xs font-bold uppercase tracking-wider text-[#991B1B]">
                    158 Invoices Need Action
                  </span>
                </div>
                <span className="text-[11px] font-bold text-[#DC2626]">
                  ₹4,58,200 at stake
                </span>
              </div>

              <div className="divide-y divide-[#F8FAFC] text-xs">
                <div className="flex items-center justify-between px-4 py-2 hover:bg-[#FAF9F7] transition-colors">
                  <span className="font-medium text-[#334155]">Review Required (Tolerances &amp; Formats)</span>
                  <div className="flex items-center gap-2">
                    <span className="rounded border border-[#FCD34D] bg-[#FFFBEB] px-2 py-0.5 font-bold text-[#92400E]">
                      38
                    </span>
                    <span className="text-[#CBD5E1]">›</span>
                  </div>
                </div>

                <div className="flex items-center justify-between px-4 py-2 hover:bg-[#FAF9F7] transition-colors">
                  <span className="font-medium text-[#334155]">Missed ITC (In Books, Missing in 2B)</span>
                  <div className="flex items-center gap-2">
                    <span className="rounded border border-[#FECACA] bg-[#FEF2F2] px-2 py-0.5 font-bold text-[#991B1B]">
                      14
                    </span>
                    <span className="font-bold text-[#DC2626] tabular-nums">₹3,42,800</span>
                    <span className="text-[#CBD5E1]">›</span>
                  </div>
                </div>

                <div className="flex items-center justify-between px-4 py-2 hover:bg-[#FAF9F7] transition-colors">
                  <span className="font-medium text-[#334155]">Rule 37 (180-Day Payment Risk)</span>
                  <div className="flex items-center gap-2">
                    <span className="rounded border border-[#FED7AA] bg-[#FFF7ED] px-2 py-0.5 font-bold text-[#C2410C]">
                      3
                    </span>
                    <span className="font-bold text-[#EA580C] tabular-nums">₹1,15,400</span>
                    <span className="text-[#CBD5E1]">›</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 2. Results Bucket Tabs & Table Container */}
          <div className="overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-white shadow-xs">
            
            {/* Real Results Bucket Tabs Strip */}
            <div className="flex overflow-x-auto border-b border-[#E2E8F0] bg-[#FAFAFA] px-2">
              {tabs.map((tab) => {
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-3 text-xs font-semibold transition-all ${
                      isActive
                        ? "border-[#0F172A] bg-white text-[#0F172A]"
                        : "border-transparent text-[#64748B] hover:text-[#0F172A]"
                    }`}
                  >
                    <span>{tab.label}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                        isActive
                          ? "bg-[#0F172A] text-white"
                          : "bg-[#E2E8F0] text-[#475569]"
                      }`}
                    >
                      {tab.count}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Filter Toolbar (Matches Real Results Page) */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#F1F5F9] bg-white px-4 py-2.5 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1.5 rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[#64748B]">
                  <Search className="h-3 w-3" />
                  <span className="text-[11px]">Filter by GSTIN or Invoice #</span>
                </div>
                <div className="rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[11px] font-medium text-[#475569]">
                  Match: Exact (L1) &amp; Soft (L2)
                </div>
              </div>

              <div className="flex items-center gap-2 text-[11px] text-[#64748B]">
                <span>Showing 1–4 of 1,280</span>
                <span className="rounded bg-[#F1F5F9] px-2 py-1 font-semibold text-[#0F172A]">
                  Page 1 of 32
                </span>
              </div>
            </div>

            {/* Decision & Matched Rows Table (Real ReconDesk Columns) */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-[#F1F5F9] bg-[#FAFAFA] text-[11px] font-bold uppercase tracking-[0.5px] text-[#64748B]">
                    <th className="px-4 py-2.5">Supplier GSTIN &amp; Name</th>
                    <th className="px-4 py-2.5">Invoice # &amp; Date</th>
                    <th className="px-4 py-2.5 text-right">Taxable Value</th>
                    <th className="px-4 py-2.5 text-center">Match Level</th>
                    <th className="px-4 py-2.5 text-right">Discrepancy</th>
                    <th className="px-4 py-2.5 text-center">IMS Status</th>
                    <th className="px-4 py-2.5 text-right">Decision / Next Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC] text-[13px]">
                  
                  {/* Row 1: Clean L1 Match */}
                  <tr className="hover:bg-[#F8FAFC] transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0F172A]">Tata Steel Ltd</div>
                      <div className="font-mono text-[11px] text-[#64748B]">27AAACT0012P1ZR</div>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <div className="font-bold text-[#1D4ED8]">INV/2026/8841</div>
                      <div className="text-[11px] text-[#64748B]">14 Mar 2026</div>
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-[#0F172A] tabular-nums">
                      ₹14,80,000
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold bg-[#DCFCE7] text-[#166534]">
                        Exact L1
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-emerald-600 font-semibold text-xs tabular-nums">
                      ₹0.00
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-[#DCFCE7] text-[#166534]">
                        Accepted
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="inline-flex items-center gap-1 rounded bg-[#0F172A] px-2.5 py-1 text-[11px] font-semibold text-white shadow-xs">
                        <Check className="h-3 w-3 text-emerald-400" />
                        Claim in 3B
                      </span>
                    </td>
                  </tr>

                  {/* Row 2: Normalized L2 Match */}
                  <tr className="hover:bg-[#F8FAFC] transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0F172A]">Infosys Technologies</div>
                      <div className="font-mono text-[11px] text-[#64748B]">29AAACI4916D1ZY</div>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <div className="font-bold text-[#1D4ED8]">INF-0941 <span className="text-[#94A3B8]">↔ INF-941</span></div>
                      <div className="text-[11px] text-[#64748B]">12 Mar 2026</div>
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-[#0F172A] tabular-nums">
                      ₹4,20,500
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold bg-[#F0F9FF] text-[#0369A1]">
                        Soft L2
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-emerald-600 font-semibold text-xs tabular-nums">
                      ₹0.00 (Prefix)
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-[#FFFBEB] text-[#92400E]">
                        Pending
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="inline-flex items-center rounded border border-[#CBD5E1] bg-white px-2.5 py-1 text-[11px] font-medium text-[#334155] hover:bg-[#F8FAFC]">
                        Approve Match
                      </span>
                    </td>
                  </tr>

                  {/* Row 3: Missed ITC */}
                  <tr className="hover:bg-[#F8FAFC] transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0F172A]">Reliance Retail Ltd</div>
                      <div className="font-mono text-[11px] text-[#64748B]">27AABCR0412R1ZU</div>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <div className="font-bold text-[#DC2626]">RR/88329</div>
                      <div className="text-[11px] text-[#64748B]">08 Mar 2026</div>
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-[#DC2626] tabular-nums">
                      ₹2,95,000
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold bg-[#FEF2F2] text-[#991B1B]">
                        Missed in 2B
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-[#DC2626] font-bold text-xs tabular-nums">
                      -₹2,95,000
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-[#FEF2F2] text-[#991B1B]">
                        Action Needed
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="inline-flex items-center gap-1 rounded bg-[#7B5CFA] px-2.5 py-1 text-[11px] font-semibold text-white shadow-xs">
                        Send Vendor Notice
                      </span>
                    </td>
                  </tr>

                  {/* Row 4: Rule 37 180-Day Warning */}
                  <tr className="hover:bg-[#F8FAFC] transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0F172A]">Kalyani Heavy Motors</div>
                      <div className="font-mono text-[11px] text-[#64748B]">27AABCK1928L1ZM</div>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <div className="font-bold text-[#EA580C]">KM/7710</div>
                      <div className="text-[11px] text-[#64748B]">18 Sep 2025</div>
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-[#0F172A] tabular-nums">
                      ₹1,15,400
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold bg-[#FFF7ED] text-[#C2410C]">
                        Rule 37 (178d)
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-[#EA580C] font-semibold text-xs tabular-nums">
                      Reversal Risk
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-[#DCFCE7] text-[#166534]">
                        Accepted
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="inline-flex items-center gap-1 rounded border border-[#FED7AA] bg-[#FFF7ED] px-2.5 py-1 text-[11px] font-bold text-[#C2410C]">
                        <Clock className="h-3 w-3" />
                        Due in 2 Days
                      </span>
                    </td>
                  </tr>

                </tbody>
              </table>
            </div>

          </div>
        </div>

      </div>
    </div>
  );
}
