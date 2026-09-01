"use client";

import { useState } from "react";
import { Logo } from "@/components/ui/Logo";
import {
  Bell,
  Building2,
  Check,
  CreditCard,
  FileSpreadsheet,
  FileText,
  HardDrive,
  HelpCircle,
  LayoutDashboard,
  Lock,
  Receipt,
  RefreshCw,
  Search,
  Settings,
  Trash2,
  UploadCloud,
  Users,
} from "lucide-react";

export function HeroProductPanel() {
  const [activeTab, setActiveTab] = useState<
    "matched" | "review_required" | "risk" | "itc"
  >("matched");

  const sidebarLinks = [
    { label: "Dashboard", icon: LayoutDashboard, active: false },
    { label: "Clients", icon: Users, active: false },
    { label: "Vendors", icon: Building2, active: false },
    { label: "Reconciliations", icon: RefreshCw, active: true },
    { label: "E-Invoicing", icon: Receipt, active: false },
    { label: "Manage Data", icon: HardDrive, active: false },
    { label: "Billing", icon: CreditCard, active: false },
    { label: "Settings", icon: Settings, active: false },
  ];

  return (
    <div className="relative z-10 mx-auto w-full max-w-6xl px-1 sm:px-2">
      {/* Outer Window Chrome Frame with soft drop shadow */}
      <div className="overflow-hidden rounded-[16px] border border-[#E2E8F0] bg-[#F1F5F9] shadow-[0_25px_60px_-15px_rgba(0,0,0,0.14)]">
        
        {/* Browser Top Window Bar */}
        <div className="flex h-10 items-center justify-between border-b border-[#E2E8F0] bg-white px-4">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-[#EF4444]/80" />
            <div className="h-3 w-3 rounded-full bg-[#F59E0B]/80" />
            <div className="h-3 w-3 rounded-full bg-[#10B981]/80" />
          </div>

          <div className="flex items-center gap-2 rounded-full bg-[#F1F5F9] px-4 py-1 font-mono text-[11px] text-[#64748B]">
            <Lock className="h-3 w-3 text-[#94A3B8]" />
            <span>app.recondesk.in/reconcile/runs/5eb64c7c/results</span>
          </div>

          <div className="flex items-center gap-2 text-xs font-semibold text-[#64748B]">
            <span className="rounded bg-[#F1F5F9] px-2 py-0.5 text-[10px]">EN</span>
            <span className="text-[#CBD5E1]">|</span>
            <span className="text-[10px] text-[#94A3B8]">हि</span>
          </div>
        </div>

        {/* Main 2-Column App Layout (Sidebar + Content Workspace) */}
        <div className="flex min-h-[580px] bg-[#F8FAFC]">
          
          {/* Left Sidebar (Desktop view) */}
          <aside className="hidden w-52 shrink-0 flex-col justify-between border-r border-[#E2E8F0] bg-white p-4 lg:flex">
            <div>
              <div className="px-2 py-1 mb-6">
                <Logo height={24} />
              </div>

              <nav className="space-y-1">
                {sidebarLinks.map((item) => {
                  const Icon = item.icon;
                  return (
                    <div
                      key={item.label}
                      className={`flex items-center gap-3 rounded-[8px] px-3 py-2 text-xs font-semibold transition-colors ${
                        item.active
                          ? "bg-[#F1F5F9] text-[#0F172A]"
                          : "text-[#64748B] hover:bg-[#F8FAFC] hover:text-[#0F172A]"
                      }`}
                    >
                      <Icon className={`h-4 w-4 ${item.active ? "text-[#7B5CFA]" : "text-[#94A3B8]"}`} />
                      <span>{item.label}</span>
                    </div>
                  );
                })}
              </nav>
            </div>

            {/* User Profile Pill at Bottom */}
            <div className="flex items-center gap-2.5 rounded-[8px] border border-[#E2E8F0] bg-[#FAFAFA] p-2 opacity-80">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#E2E8F0] text-[11px] font-bold text-[#64748B]">
                CA
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-semibold text-[#475569]">CA Partner</p>
                <p className="truncate text-[10px] text-[#94A3B8]">audit@ca-firm.in</p>
              </div>
            </div>
          </aside>

          {/* Right Workspace Main Content */}
          <main className="flex-1 p-3 sm:p-5 space-y-3.5 min-w-0">
            
            {/* 1. Top Context / Action Bar Card */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-[#E2E8F0] bg-white p-3 px-4 shadow-xs">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-[#94A3B8]">Clients</span>
                <span className="text-[#CBD5E1]">/</span>
                <span className="font-bold text-[#0F172A]">Apex Technologies Ltd</span>
                <span className="text-[#CBD5E1]">/</span>
                <span className="text-[#64748B]">July 2026</span>
                <span className="rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-0.5 font-mono text-[11px] text-[#94A3B8]">
                  27AAACT0012P1ZR
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1 text-xs font-semibold text-[#475569] hover:bg-[#F8FAFC]"
                >
                  <UploadCloud className="h-3.5 w-3.5 text-[#64748B]" />
                  <span>Export</span>
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1 text-xs font-semibold text-[#475569] hover:bg-[#F8FAFC]"
                >
                  <FileText className="h-3.5 w-3.5 text-[#64748B]" />
                  <span>PDF Report</span>
                </button>
                <button
                  type="button"
                  className="rounded-[6px] border border-red-200 bg-white p-1.5 text-red-500 hover:bg-red-50"
                  title="Delete"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
                <span className="rounded-[6px] bg-[#DCFCE7] px-2.5 py-1 text-xs font-bold text-[#166534]">
                  Finalized
                </span>
              </div>
            </div>

            {/* 2. Surreal KPI Grid (Run Summary + Action Required Split) */}
            <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
              
              {/* Left Card: Run Total & Progress */}
              <div className="flex items-center gap-4 sm:gap-6 rounded-[10px] border border-[#E2E8F0] bg-white p-4 shadow-xs">
                <div className="min-w-[72px] text-center">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">
                    Run Total
                  </div>
                  <div className="mt-1 text-3xl font-black text-[#0F172A] tabular-nums">
                    972
                  </div>
                  <div className="text-[10px] text-[#94A3B8]">invoices</div>
                </div>

                <div className="h-12 w-[1px] bg-[#F1F5F9]" />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between text-xs text-[#64748B] mb-1">
                    <span className="font-bold uppercase tracking-wider text-[#94A3B8]">
                      Matched
                    </span>
                    <span className="font-bold text-[#16A34A] tabular-nums">
                      875 · 90%
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-[#F1F5F9]">
                    <div
                      className="h-full rounded-full bg-[#16A34A] transition-all"
                      style={{ width: "90%" }}
                    />
                  </div>
                  <div className="mt-1.5 text-[11px] font-medium text-[#64748B]">
                    97 invoices need attention
                  </div>
                </div>

                <div className="hidden sm:block h-12 w-[1px] bg-[#F1F5F9]" />

                <div className="hidden sm:block min-w-[76px] text-center">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">
                    Assigned
                  </div>
                  <div className="mt-1 text-xs font-bold text-[#475569]">
                    CA Team
                  </div>
                  <div className="text-[10px] text-[#94A3B8]">July 2026</div>
                </div>
              </div>

              {/* Right Card: 111 Invoices Need Action */}
              <div className="rounded-[10px] border border-[#E2E8F0] bg-white p-4 shadow-xs">
                <div className="flex items-center gap-2 mb-2.5">
                  <span className="h-2 w-2 rounded-full bg-[#DC2626]" />
                  <span className="text-xs font-bold uppercase tracking-wider text-[#991B1B]">
                    111 Invoices Need Action
                  </span>
                </div>

                <div className="space-y-1.5 text-xs">
                  <div className="flex items-center justify-between py-1">
                    <span className="font-medium text-[#334155]">Review Required</span>
                    <div className="flex items-center gap-1.5">
                      <span className="rounded bg-[#FEF9C3] px-1.5 py-0.5 text-[10px] font-bold text-[#713F12]">
                        61
                      </span>
                      <span className="text-[#CBD5E1]">›</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between py-1">
                    <span className="font-medium text-[#334155]">Missed ITC</span>
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-[#FEE2E2] px-1.5 py-0.5 text-[10px] font-bold text-[#991B1B]">
                        11
                      </span>
                      <span className="font-bold text-[#DC2626] tabular-nums">₹2.12L</span>
                      <span className="text-[#CBD5E1]">›</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between py-1">
                    <span className="font-medium text-[#334155]">ITC at Risk — Not in GSTR-2B</span>
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-[#FEE2E2] px-1.5 py-0.5 text-[10px] font-bold text-[#991B1B]">
                        39
                      </span>
                      <span className="font-bold text-[#DC2626] tabular-nums">₹8.62L</span>
                      <span className="text-[#CBD5E1]">›</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* 3. Main Results Table Card */}
            <div className="overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-white shadow-xs">
              
              {/* Primary Tabs */}
              <div className="flex items-center justify-between border-b border-[#E2E8F0] bg-white px-4 pt-2 overflow-x-auto">
                <div className="flex items-center gap-6 text-xs font-bold">
                  <button
                    type="button"
                    onClick={() => setActiveTab("matched")}
                    className={`flex items-center gap-1.5 border-b-2 pb-2.5 transition-all ${
                      activeTab === "matched"
                        ? "border-[#7B5CFA] text-[#0F172A]"
                        : "border-transparent text-[#64748B]"
                    }`}
                  >
                    <span>MATCHED</span>
                    <span className="rounded-full bg-[#DCFCE7] px-1.5 py-0.2 text-[10px] text-[#166534]">
                      875
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("review_required")}
                    className={`flex items-center gap-1.5 border-b-2 pb-2.5 transition-all ${
                      activeTab === "review_required"
                        ? "border-[#7B5CFA] text-[#0F172A]"
                        : "border-transparent text-[#64748B]"
                    }`}
                  >
                    <span>Review Required</span>
                    <span className="rounded-full bg-[#FEF9C3] px-1.5 py-0.2 text-[10px] text-[#713F12]">
                      61
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("risk")}
                    className={`flex items-center gap-1.5 border-b-2 pb-2.5 transition-all ${
                      activeTab === "risk"
                        ? "border-[#7B5CFA] text-[#0F172A]"
                        : "border-transparent text-[#64748B]"
                    }`}
                  >
                    <span>ITC at Risk</span>
                    <span className="rounded-full bg-[#FEE2E2] px-1.5 py-0.2 text-[10px] text-[#991B1B]">
                      39
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("itc")}
                    className={`flex items-center gap-1.5 border-b-2 pb-2.5 transition-all ${
                      activeTab === "itc"
                        ? "border-[#7B5CFA] text-[#0F172A]"
                        : "border-transparent text-[#64748B]"
                    }`}
                  >
                    <span>Missed ITC</span>
                    <span className="rounded-full bg-[#FEE2E2] px-1.5 py-0.2 text-[10px] text-[#991B1B]">
                      11
                    </span>
                  </button>
                </div>

                <div className="hidden sm:flex items-center gap-1 text-[11px] text-[#64748B] pb-2">
                  <span>Duplicate Entries</span>
                  <span className="rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] font-bold text-[#475569]">
                    10
                  </span>
                </div>
              </div>

              {/* Secondary Modules Row */}
              <div className="flex flex-wrap items-center gap-1.5 border-b border-[#F1F5F9] bg-[#FAFAFA] px-4 py-2 text-[11px]">
                <span className="font-bold text-[#94A3B8] mr-1">MODULES →</span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  Rule 37 <span className="text-[#94A3B8]">Unpaid 180d</span>
                </span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  Section 17(5)
                </span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  RCM
                </span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  GSTR-3B Tie-out
                </span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  E-Invoice Check
                </span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  IMS Actions
                </span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  Follow-up Log
                </span>
                <span className="rounded-[4px] border border-[#E2E8F0] bg-white px-2 py-0.5 font-medium text-[#475569]">
                  Notes (0)
                </span>
              </div>

              {/* Filter Toolbar */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#F1F5F9] bg-white px-4 py-2.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1.5 rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1 text-[#94A3B8]">
                    <Search className="h-3 w-3" />
                    <span className="text-[11px] text-[#94A3B8]">Search supplier GSTIN or invoice nu</span>
                  </div>
                  <span className="rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] text-[#475569]">
                    All types ⌄
                  </span>
                  <span className="rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] text-[#475569]">
                    All levels ⌄
                  </span>
                  <span className="rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] text-[#475569]">
                    All IMS ⌄
                  </span>
                  <span className="rounded-[6px] border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] text-[#475569]">
                    Date: Newest first ⌄
                  </span>
                </div>

                <div className="flex items-center gap-3 text-[11px]">
                  <span className="flex items-center gap-1 text-[#16A34A] font-bold">
                    <span className="h-2 w-2 rounded-full bg-[#16A34A]" /> 875 Matched
                  </span>
                  <span className="flex items-center gap-1 text-[#D97706] font-bold">
                    <span className="h-2 w-2 rounded-full bg-[#D97706]" /> 875 Non-exact
                  </span>
                </div>
              </div>

              {/* Real Table Rows */}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] bg-[#FAFAFA] text-[11px] font-bold uppercase tracking-[0.5px] text-[#64748B]">
                      <th className="px-4 py-2.5">Supplier GSTIN</th>
                      <th className="px-4 py-2.5">Invoice #</th>
                      <th className="px-4 py-2.5">Date</th>
                      <th className="px-4 py-2.5 text-right">Amount</th>
                      <th className="px-4 py-2.5 text-center">Match</th>
                      <th className="px-4 py-2.5 text-center">Confidence</th>
                      <th className="px-4 py-2.5 text-center">IMS</th>
                      <th className="px-4 py-2.5 text-right">Discrepancy</th>
                      <th className="px-4 py-2.5 text-center">Notes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC] text-[12px]">
                    
                    {/* Row 1 */}
                    <tr className="hover:bg-[#F8FAFC] transition-colors">
                      <td className="px-4 py-2.5 font-mono font-bold text-[#0F172A]">
                        27EHYCI2900Z2ZY
                      </td>
                      <td className="px-4 py-2.5 font-mono font-bold text-[#1D4ED8]">
                        INV20269730686
                      </td>
                      <td className="px-4 py-2.5 text-[#64748B] whitespace-nowrap">
                        30 Jun 2026
                      </td>
                      <td className="px-4 py-2.5 text-right font-bold text-[#0F172A] tabular-nums">
                        ₹57,354.20
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <span className="rounded bg-[#FEF9C3] px-1.5 py-0.5 text-[10px] font-bold text-[#713F12]">
                          Fuzzy L3
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <div className="inline-flex items-center gap-1 text-[11px] text-[#16A34A] font-bold">
                          <span className="h-1.5 w-6 rounded-full bg-[#16A34A]" />
                          <span>80%</span>
                          <span className="rounded border border-[#BFDBFE] bg-[#EFF6FF] px-1 py-0.2 text-[9px] text-[#1D4ED8]">
                            why?
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <span className="rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] text-[#64748B]">
                          No action
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right text-[#64748B] tabular-nums">
                        ₹0
                      </td>
                      <td className="px-4 py-2.5 text-center text-[#CBD5E1]">
                        —
                      </td>
                    </tr>

                    {/* Row 2 */}
                    <tr className="hover:bg-[#F8FAFC] transition-colors">
                      <td className="px-4 py-2.5 font-mono font-bold text-[#0F172A]">
                        29IAVQW2226S5Z3
                      </td>
                      <td className="px-4 py-2.5 font-mono font-bold text-[#1D4ED8]">
                        INV20264790657
                      </td>
                      <td className="px-4 py-2.5 text-[#64748B] whitespace-nowrap">
                        30 Jun 2026
                      </td>
                      <td className="px-4 py-2.5 text-right font-bold text-[#0F172A] tabular-nums">
                        ₹9,088.33
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <span className="rounded bg-[#FEF9C3] px-1.5 py-0.5 text-[10px] font-bold text-[#713F12]">
                          Fuzzy L3
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <div className="inline-flex items-center gap-1 text-[11px] text-[#16A34A] font-bold">
                          <span className="h-1.5 w-6 rounded-full bg-[#16A34A]" />
                          <span>80%</span>
                          <span className="rounded border border-[#BFDBFE] bg-[#EFF6FF] px-1 py-0.2 text-[9px] text-[#1D4ED8]">
                            why?
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <span className="rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] text-[#64748B]">
                          No action
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right text-[#64748B] tabular-nums">
                        ₹0
                      </td>
                      <td className="px-4 py-2.5 text-center text-[#CBD5E1]">
                        —
                      </td>
                    </tr>

                    {/* Row 3 */}
                    <tr className="hover:bg-[#F8FAFC] transition-colors">
                      <td className="px-4 py-2.5 font-mono font-bold text-[#0F172A]">
                        24QPIBC6400K3ZG
                      </td>
                      <td className="px-4 py-2.5 font-mono font-bold text-[#1D4ED8]">
                        INV20266640023
                      </td>
                      <td className="px-4 py-2.5 text-[#64748B] whitespace-nowrap">
                        30 Jun 2026
                      </td>
                      <td className="px-4 py-2.5 text-right font-bold text-[#0F172A] tabular-nums">
                        ₹22,283.51
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <span className="rounded bg-[#FEF9C3] px-1.5 py-0.5 text-[10px] font-bold text-[#713F12]">
                          Fuzzy L3
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <div className="inline-flex items-center gap-1 text-[11px] text-[#16A34A] font-bold">
                          <span className="h-1.5 w-6 rounded-full bg-[#16A34A]" />
                          <span>80%</span>
                          <span className="rounded border border-[#BFDBFE] bg-[#EFF6FF] px-1 py-0.2 text-[9px] text-[#1D4ED8]">
                            why?
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <span className="rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] text-[#64748B]">
                          No action
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right text-[#64748B] tabular-nums">
                        ₹0
                      </td>
                      <td className="px-4 py-2.5 text-center text-[#CBD5E1]">
                        —
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Bottom Status / Finalized Bar */}
              <div className="flex flex-wrap items-center justify-between border-t border-[#E2E8F0] bg-[#FAFAFA] px-4 py-2.5 text-[11px] text-[#64748B]">
                <div className="flex flex-wrap items-center gap-4">
                  <span className="flex items-center gap-1 text-[#16A34A] font-bold">
                    <Check className="h-3.5 w-3.5" /> Matched reviewed
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> Review Required — 61 pending
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-red-500" /> Missed ITC — 11 pending
                  </span>
                </div>

                <div className="flex items-center gap-2 font-medium text-[#94A3B8]">
                  <span>Finalized by CA Reviewer</span>
                  <span className="rounded bg-[#DCFCE7] px-2 py-0.5 font-bold text-[#166534]">
                    Locked
                  </span>
                </div>
              </div>

            </div>
          </main>
        </div>

      </div>
    </div>
  );
}
