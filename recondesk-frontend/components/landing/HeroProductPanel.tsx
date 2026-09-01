"use client";

import { useState } from "react";
import { Logo } from "@/components/ui/Logo";
import {
  AlertTriangle,
  BarChart3,
  Bell,
  CheckCircle2,
  Clock,
  FileCheck2,
  Filter,
  Layers,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";

export function HeroProductPanel() {
  const [activeTab, setActiveTab] = useState("GSTR-2B Recon");

  const navTabs = [
    { label: "GSTR-2B Recon", icon: Layers },
    { label: "GSTR-1 Sales", icon: BarChart3 },
    { label: "GSTR-3B vs Books", icon: FileCheck2 },
    { label: "Rule 37 Tracker", icon: Clock },
    { label: "Clients", icon: Users },
  ];

  return (
    <div className="relative z-10 mx-auto w-full max-w-6xl px-2 sm:px-4">
      {/* Outer Panel Chrome Frame with soft drop shadow lifting off white page */}
      <div className="overflow-hidden rounded-[12px] sm:rounded-[14px] border border-[#E5E5E2] bg-white shadow-[0_20px_50px_-12px_rgba(0,0,0,0.09)] transition-all duration-300">
        
        {/* Internal Top Bar / App Chrome */}
        <div className="flex h-14 items-center justify-between border-b border-[#E5E5E2] bg-white px-3 sm:px-5">
          {/* Left: Official Brand Logo with purple dot */}
          <div className="flex items-center gap-2.5">
            <Logo height={22} />
            <span className="hidden rounded-full bg-[#F5F5F3] px-2 py-0.5 text-[10px] font-semibold text-[#6B6B6B] sm:inline-block">
              Workspace
            </span>
          </div>

          {/* Center: Top bar nav icons/labels (collapses on mobile) */}
          <nav className="hidden items-center gap-1 md:flex">
            {navTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.label;
              return (
                <button
                  key={tab.label}
                  type="button"
                  onClick={() => setActiveTab(tab.label)}
                  className={`flex items-center gap-1.5 rounded-[8px] px-3 py-1.5 text-xs font-medium transition-colors ${
                    isActive
                      ? "bg-[#0A0A0A] text-white font-semibold"
                      : "text-[#6B6B6B] hover:bg-[#FAF9F7] hover:text-[#0A0A0A]"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Right: Search, Notification Bell, User Avatar */}
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="hidden items-center gap-1.5 rounded-[6px] border border-[#E5E5E2] bg-[#FAFAFA] px-2 py-1 text-[11px] text-[#6B6B6B] sm:flex">
              <Search className="h-3 w-3" />
              <span>Search invoices</span>
              <kbd className="rounded bg-white px-1 font-mono text-[9px] text-[#6B6B6B] shadow-xs">
                ⌘K
              </kbd>
            </div>

            <button
              type="button"
              className="relative flex h-8 w-8 items-center justify-center rounded-full text-[#6B6B6B] transition hover:bg-[#F5F5F3] hover:text-[#0A0A0A]"
              aria-label="Notifications"
            >
              <Bell className="h-4 w-4" />
              <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-[#F97316]" />
            </button>

            <div className="relative flex h-8 w-8 items-center justify-center rounded-full bg-[#0A0A0A] text-xs font-semibold text-white">
              <span>CA</span>
              <span className="absolute bottom-0 right-0 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#16A34A]" />
            </div>
          </div>
        </div>

        {/* Dashboard Content Area */}
        <div className="p-4 sm:p-6 md:p-8 bg-white space-y-6">
          
          {/* Subheader: Run Controls & Period Context */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-[#E5E5E2] pb-5">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base sm:text-lg font-bold text-[#0A0A0A]">
                  Active Reconciliation Run
                </h3>
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 border border-emerald-200">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
                  Ready to Finalize
                </span>
              </div>
              <p className="mt-0.5 text-xs text-[#6B6B6B]">
                Period: Q2 FY 2026–27 • 1,438 Invoices Evaluated across 42 Suppliers
              </p>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-auto">
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-[8px] border border-[#E5E5E2] bg-white px-3 py-1.5 text-xs font-medium text-[#0A0A0A] hover:bg-[#F5F5F3] transition"
              >
                <Filter className="h-3.5 w-3.5 text-[#6B6B6B]" />
                <span>Filter Mismatches</span>
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-[8px] bg-[#0A0A0A] px-3.5 py-1.5 text-xs font-medium text-white hover:bg-[#262626] transition"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>Rerun Matcher</span>
              </button>
            </div>
          </div>

          {/* Metric Stats Cards Row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* Card 1: Matched ITC */}
            <div className="rounded-[10px] border border-[#E5E5E2] bg-white p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[#6B6B6B]">
                  ITC Claimable &amp; Matched
                </span>
                <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                  98.4% Matched
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl sm:text-3xl font-extrabold tracking-tight text-[#0A0A0A]">
                  ₹48,24,650
                </span>
              </div>
              <p className="mt-1 text-xs text-[#6B6B6B] flex items-center gap-1">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 inline" />
                <span>1,280 clean exact + normalized pairs</span>
              </p>
            </div>

            {/* Card 2: Missed ITC */}
            <div className="rounded-[10px] border border-[#E5E5E2] bg-white p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[#6B6B6B]">
                  Missed / Unclaimed ITC
                </span>
                <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                  14 Invoices
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl sm:text-3xl font-extrabold tracking-tight text-[#0A0A0A]">
                  ₹3,42,800
                </span>
              </div>
              <p className="mt-1 text-xs text-[#6B6B6B] flex items-center gap-1">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-600 inline" />
                <span>Missing in supplier GSTR-1 filings</span>
              </p>
            </div>

            {/* Card 3: Rule 37 180-Day Risk */}
            <div className="rounded-[10px] border border-[#E5E5E2] bg-white p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[#6B6B6B]">
                  Rule 37 Reversal Alert
                </span>
                <span className="rounded-full bg-orange-50 px-1.5 py-0.5 text-[10px] font-semibold text-[#F97316]">
                  Action Needed
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl sm:text-3xl font-extrabold tracking-tight text-[#0A0A0A]">
                  ₹1,15,400
                </span>
              </div>
              <p className="mt-1 text-xs text-[#6B6B6B] flex items-center gap-1">
                <Clock className="h-3.5 w-3.5 text-[#F97316] inline" />
                <span>3 invoices crossing 180 days unpaid</span>
              </p>
            </div>
          </div>

          {/* 5-Level Match Hierarchy Distribution Bar */}
          <div className="rounded-[10px] border border-[#E5E5E2] bg-[#FAF9F7] p-4">
            <div className="flex items-center justify-between text-xs font-semibold text-[#0A0A0A] mb-2.5">
              <span className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-[#F97316]" />
                Multi-Level Match Hierarchy Distribution
              </span>
              <span className="text-[#6B6B6B] font-normal text-[11px]">
                Processed in 3.8 seconds
              </span>
            </div>

            {/* Segmented Distribution Bar */}
            <div className="h-3 w-full overflow-hidden rounded-full bg-[#E5E5E2] flex">
              <div style={{ width: "88%" }} className="bg-[#0A0A0A]" title="L1 Exact: 88%" />
              <div style={{ width: "6%" }} className="bg-[#F97316]" title="L2 Normalized: 6%" />
              <div style={{ width: "3%" }} className="bg-amber-400" title="L3 Toleranced: 3%" />
              <div style={{ width: "2%" }} className="bg-blue-500" title="L4 PAN Match: 2%" />
              <div style={{ width: "1%" }} className="bg-rose-500" title="L6 Review: 1%" />
            </div>

            {/* Legend */}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-[#6B6B6B]">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-[#0A0A0A]" />
                <strong className="text-[#0A0A0A]">L1 Exact:</strong> 88%
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-[#F97316]" />
                <strong className="text-[#0A0A0A]">L2 Normalized:</strong> 6%
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-amber-400" />
                <strong className="text-[#0A0A0A]">L3 Toleranced:</strong> 3%
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-blue-500" />
                <strong className="text-[#0A0A0A]">L4 PAN Match:</strong> 2%
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-rose-500" />
                <strong className="text-[#0A0A0A]">L6 Unmatched:</strong> 1%
              </span>
            </div>
          </div>

          {/* Decision-Ready Invoices Table */}
          <div className="overflow-hidden rounded-[10px] border border-[#E5E5E2]">
            <div className="border-b border-[#E5E5E2] bg-[#FAF9F7] px-4 py-2.5 text-xs font-semibold text-[#0A0A0A]">
              Actionable Invoice Decisions (WHAT / WHY / NEXT)
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#E5E5E2] bg-white text-[#6B6B6B]">
                    <th className="px-4 py-2.5 font-medium">Supplier &amp; GSTIN</th>
                    <th className="px-4 py-2.5 font-medium">Invoice #</th>
                    <th className="px-4 py-2.5 font-medium text-right">Taxable Value</th>
                    <th className="px-4 py-2.5 font-medium">Diagnosis</th>
                    <th className="px-4 py-2.5 font-medium text-right">Next Step</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E5E5E2]">
                  {/* Row 1 */}
                  <tr className="hover:bg-[#FAF9F7]/60 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0A0A0A]">Tata Steel Ltd</div>
                      <div className="text-[11px] text-[#6B6B6B]">27AAACT0012P1ZR</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-[#0A0A0A]">
                      INV/2026/8841
                    </td>
                    <td className="px-4 py-3 font-semibold text-[#0A0A0A] text-right">
                      ₹14,80,000
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                        <CheckCircle2 className="h-3 w-3" /> L1 Clean Match
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="rounded-[6px] bg-[#0A0A0A] px-2.5 py-1 text-[11px] font-semibold text-white">
                        Auto Claimed
                      </span>
                    </td>
                  </tr>

                  {/* Row 2 */}
                  <tr className="hover:bg-[#FAF9F7]/60 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0A0A0A]">Infosys Technologies</div>
                      <div className="text-[11px] text-[#6B6B6B]">29AAACI4916D1ZY</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-[#0A0A0A]">
                      INF-0941 <span className="text-[#6B6B6B]">↔ INF-941</span>
                    </td>
                    <td className="px-4 py-3 font-semibold text-[#0A0A0A] text-right">
                      ₹4,20,500
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                        L2 Number Prefix
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="rounded-[6px] border border-[#E5E5E2] bg-white px-2.5 py-1 text-[11px] font-medium text-[#0A0A0A]">
                        Approve Match
                      </span>
                    </td>
                  </tr>

                  {/* Row 3 */}
                  <tr className="hover:bg-[#FAF9F7]/60 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0A0A0A]">Reliance Retail Ltd</div>
                      <div className="text-[11px] text-[#6B6B6B]">27AABCR0412R1ZU</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-[#0A0A0A]">
                      RR/88329
                    </td>
                    <td className="px-4 py-3 font-semibold text-[#0A0A0A] text-right">
                      ₹2,95,000
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-semibold text-rose-700">
                        Missing in 2B
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="rounded-[6px] bg-[#F97316] px-2.5 py-1 text-[11px] font-semibold text-white">
                        Send Notice
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
