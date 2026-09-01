"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock,
  Copy,
  Cpu,
  Database,
  Download,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  Filter,
  HelpCircle,
  KeyRound,
  Layers,
  Lock,
  Mail,
  Receipt,
  RotateCw,
  Search,
  Server,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
  Users,
  Zap,
} from "lucide-react";

type MatchLevelKey = "L1" | "L2" | "L3" | "L4" | "L6";
type RuleCategory = "all" | "sec16" | "rule37" | "sec17" | "rule88d" | "rcm" | "g1m" | "g9c";
type ExcelSheetKey = "sheet1" | "sheet2" | "sheet3" | "sheet4";

interface RuleItem {
  id: string;
  code: string;
  category: "sec16" | "rule37" | "sec17" | "rule88d" | "rcm" | "g1m" | "g9c";
  categoryLabel: string;
  title: string;
  sectionRef: string;
  condition: string;
  action: string;
  auditOutput: string;
}

const STATUTORY_RULES: RuleItem[] = [
  // ─── Section 16 & Ingestion ───
  {
    id: "r1",
    code: "MAT_001",
    category: "sec16",
    categoryLabel: "Section 16 Eligibility",
    title: "GSTR-2B Portal Reflection Verification",
    sectionRef: "CGST Act Section 16(2)(aa) r/w Rule 36(4)",
    condition: "Invoice details must be communicated to recipient in Form GSTR-2B generated under Rule 60(7).",
    action: "Verifies invoice presence in supplier-filed GSTR-2B. Invoices not in 2B are quarantined to prevent wrongful GSTR-3B claims.",
    auditOutput: "Tagged as 'Eligible ITC' or 'Missing in 2B — Pending Supplier Filing'.",
  },
  {
    id: "r2",
    code: "MAT_002",
    category: "sec16",
    categoryLabel: "Section 16 Eligibility",
    title: "Annual Statutory ITC Claim Cut-Off Tracker",
    sectionRef: "CGST Act Section 16(4)",
    condition: "ITC in respect of any invoice or debit note cannot be claimed after 30th November following the end of financial year or annual return filing.",
    action: "Monitors invoice dates against the November 30 statutory deadline. Flags prior-year unbooked credits approaching expiration.",
    auditOutput: "Section 16(4) Expiration Risk Alert with remaining calendar days countdown.",
  },
  {
    id: "r3",
    code: "MAT_003",
    category: "sec16",
    categoryLabel: "Section 16 Eligibility",
    title: "Possession of Tax Invoice & QR IRN Verification",
    sectionRef: "CGST Act Section 16(2)(a) r/w Rule 48(4)",
    condition: "Taxpayer must be in possession of valid tax invoice/debit note with mandatory 64-character IRN for applicable B2B suppliers.",
    action: "Validates supplier E-Invoice IRN schema and matches invoice date with tax invoice issuance date.",
    auditOutput: "IRN Status: Verified / Non-Applicable.",
  },
  {
    id: "r4",
    code: "MAT_004",
    category: "sec16",
    categoryLabel: "Section 16 Eligibility",
    title: "Tax Actually Paid to Government Verification",
    sectionRef: "CGST Act Section 16(2)(c)",
    condition: "Tax charged in respect of supply must be actually paid to the Government by the supplier in cash or eligible ITC.",
    action: "Cross-checks supplier GSTR-3B filing status indicators in portal metadata to identify non-compliant vendors.",
    auditOutput: "Supplier GSTR-3B Filing Compliance Flag: Active / Defaulter.",
  },

  // ─── Rule 37 & 37A (180 Days & Supplier Defaults) ───
  {
    id: "r5",
    code: "R37_001",
    category: "rule37",
    categoryLabel: "Rule 37 Tracking",
    title: "180-Day Supplier Payment & Section 50(1) Interest Calculation",
    sectionRef: "CGST Rules Rule 37 r/w Section 50(1)",
    condition: "Recipient fails to pay supplier value of supply plus tax within 180 days from invoice date.",
    action: "Calculates exact 18% per annum interest liability from invoice date; computes proportionate partial payment reversals.",
    auditOutput: "Rule 37 Reversal Schedule exported in GSTR-9C Workpaper Sheet 4.",
  },
  {
    id: "r6",
    code: "R37_002",
    category: "rule37",
    categoryLabel: "Rule 37 Tracking",
    title: "Rule 37 Reclaim on Subsequent Supplier Settlement",
    sectionRef: "CGST Rules Rule 37(4) Proviso to Section 16(2)",
    condition: "Recipient makes payment of value of supply plus tax to supplier after earlier reversal.",
    action: "Automatically allows reclaim of previously reversed ITC in GSTR-3B Table 4(A)(5) upon detecting payment date.",
    auditOutput: "Rule 37 Reclaim Ledger entry with voucher linkage.",
  },
  {
    id: "r7",
    code: "R37_003",
    category: "rule37",
    categoryLabel: "Rule 37 Tracking",
    title: "Supplier GSTR-3B Non-Filing Reversal Tracker",
    sectionRef: "CGST Rules Rule 37A",
    condition: "Supplier filed GSTR-1 but failed to furnish Form GSTR-3B by 30th September following the end of financial year.",
    action: "Flags defaulting supplier GSTINs for mandatory Rule 37A reversal by 30th November, and tracks re-credit upon filing.",
    auditOutput: "Rule 37A Defaulting Supplier Notice & Reclaim Audit Log.",
  },

  // ─── Section 17(5) Blocked Credits ───
  {
    id: "r8",
    code: "SEC17_001",
    category: "sec17",
    categoryLabel: "Section 17(5) Blocked",
    title: "Motor Vehicles & Passenger Transport Credit Scanner",
    sectionRef: "CGST Act Section 17(5)(a) & (aa)",
    condition: "Motor vehicles for transportation of persons having approved seating capacity of ≤ 13 persons, unless used for specified taxable purposes.",
    action: "Scans purchase ledgers for HSN Chapter 8703 / vehicle lease expenses and advises CA to block in GSTR-3B Table 4(B)(1).",
    auditOutput: "Blocked Credit Advisory citing Section 17(5)(a).",
  },
  {
    id: "r9",
    code: "SEC17_002",
    category: "sec17",
    categoryLabel: "Section 17(5) Blocked",
    title: "Food, Beverages, Outdoor Catering & Club Memberships",
    sectionRef: "CGST Act Section 17(5)(b)(i) & (ii)",
    condition: "Supply of food and beverages, outdoor catering, beauty treatment, health services, club memberships, and life/health insurance.",
    action: "Detects HSN 9963 / 9972 catering and corporate subscription bills; restricts claim before GSTR-3B preparation.",
    auditOutput: "Ineligible ITC flag with statutory exempt override notes.",
  },
  {
    id: "r10",
    code: "SEC17_003",
    category: "sec17",
    categoryLabel: "Section 17(5) Blocked",
    title: "Works Contract for Immovable Property Construction",
    sectionRef: "CGST Act Section 17(5)(c) & (d)",
    condition: "Works contract services supplied for construction of immovable property (other than plant and machinery) when capitalized.",
    action: "Scans HSN 9954 contractor invoices and cross-checks asset capitalization tags to flag blocked construction credit.",
    auditOutput: "Immovable Property Capitalization Warning in audit summary.",
  },
  {
    id: "r11",
    code: "SEC17_004",
    category: "sec17",
    categoryLabel: "Section 17(5) Blocked",
    title: "Goods Lost, Stolen, Destroyed, Written Off or Gifted",
    sectionRef: "CGST Act Section 17(5)(h)",
    condition: "Goods lost, stolen, destroyed, written off or disposed of by way of gift or free samples.",
    action: "Identifies inventory write-down vouchers and promotional sample distributions to compute mandatory credit reversal.",
    auditOutput: "Section 17(5)(h) Stock Write-Off Reversal Schedule.",
  },

  // ─── Rule 88D & 88C Notice Defense ───
  {
    id: "r12",
    code: "R88D_001",
    category: "rule88d",
    categoryLabel: "Rule 88D Defense",
    title: "GSTR-3B vs 2B Dual-Threshold Notice Trigger Pre-Check",
    sectionRef: "CGST Rules Rule 88D r/w Form GST DRC-01C",
    condition: "ITC availed in GSTR-3B exceeds ITC available in GSTR-2B by more than 10% / 20% and ₹25,00,000.",
    action: "Pre-calculates net variance across IGST, CGST, SGST before 3B submission; triggers alert if thresholds are breached.",
    auditOutput: "One-Click DRC-01C Explanatory Reply Draft with statutory citations.",
  },
  {
    id: "r13",
    code: "R88C_001",
    category: "rule88d",
    categoryLabel: "Rule 88D Defense",
    title: "GSTR-1 Outward Tax vs GSTR-3B Table 3.1 Liability Check",
    sectionRef: "CGST Rules Rule 88C r/w Form GST DRC-01B",
    condition: "Tax payable declared in Form GSTR-1 exceeds the liability declared in Form GSTR-3B Table 3.1(a).",
    action: "Compares outward registers against 3B tax payments; auto-drafts DRC-01B Part B reply citing earlier period excess tax.",
    auditOutput: "Form GST DRC-01B Part B Response Narrative.",
  },

  // ─── Reverse Charge Mechanism (RCM) ───
  {
    id: "r14",
    code: "RCM_001",
    category: "rcm",
    categoryLabel: "RCM Section 9(3)",
    title: "Inward Reverse Charge GTA & Legal Services Segregation",
    sectionRef: "CGST Act Section 9(3) & Section 9(4) r/w Table 3.1(d)",
    condition: "Supplies received from Goods Transport Agencies (GTA), legal advocates, or security agencies subject to reverse charge.",
    action: "Segregates RCM inward supplies to ensure liability is paid in cash in Table 3.1(d) and concurrently claimed in Table 4(A)(3).",
    auditOutput: "RCM Tax Head Cash Payment & ITC Claim Reconciliation.",
  },
  {
    id: "r15",
    code: "RCM_002",
    category: "rcm",
    categoryLabel: "RCM Section 9(3)",
    title: "RCM Self-Invoice & Voucher Number Validation",
    sectionRef: "CGST Act Section 31(3)(f) & (g)",
    condition: "Recipient liable to pay tax under Section 9(3)/9(4) must issue payment voucher and self-invoice on date of receipt.",
    action: "Checks for corresponding payment voucher entries in accounting ledgers for all inward RCM claims.",
    auditOutput: "RCM Self-Invoice Compliance Schedule.",
  },

  // ─── GSTR-1 Outward Diagnostics ───
  {
    id: "r16",
    code: "G1M_001",
    category: "g1m",
    categoryLabel: "GSTR-1 Outward Diagnostics",
    title: "B2B Outward Invoice Omission Diagnostic",
    sectionRef: "CGST Act Section 37 r/w Rule 59",
    condition: "B2B sales invoice entered in books but omitted in Form GSTR-1 Table 4A/4B.",
    action: "Flags missing sales records to prevent recipient ITC loss and downstream commercial disputes.",
    auditOutput: "G1M1 Missing B2B Outward Schedule.",
  },
  {
    id: "r17",
    code: "G1M_002",
    category: "g1m",
    categoryLabel: "GSTR-1 Outward Diagnostics",
    title: "Tax Rate Discrepancy & HSN Rate Drift",
    sectionRef: "CGST Rules Rule 59(2) Table 12",
    condition: "Tax rate billed in accounting software (e.g. 18%) differs from GSTR-1 declaration (e.g. 12%).",
    action: "Detects tax rate differences per line item and computes differential tax liability before filing lock.",
    auditOutput: "G1M3 Differential Tax Rate Audit Log.",
  },
  {
    id: "r18",
    code: "G1M_003",
    category: "g1m",
    categoryLabel: "GSTR-1 Outward Diagnostics",
    title: "B2B vs B2CL / B2CS Cross-Classification Check",
    sectionRef: "CGST Rules Rule 59 Table 5 & Table 7",
    condition: "Registered B2B invoice incorrectly declared in Table 5 (B2CL) or Table 7 (B2CS retail).",
    action: "Isolates invoices with recipient GSTIN filed under unorganized retail buckets, generating reclassification schedules.",
    auditOutput: "G1M5 Reclassification Table for GSTR-1A amendment.",
  },
  {
    id: "r19",
    code: "G1M_004",
    category: "g1m",
    categoryLabel: "GSTR-1 Outward Diagnostics",
    title: "Table 13 Document Serial Sequence & Cancellation Audit",
    sectionRef: "CGST Rules Rule 59(2) Table 13",
    condition: "Gaps or overlaps in serial numbering of tax invoices, credit notes, and cancelled documents issued during the month.",
    action: "Validates sequential numbering from start to end number and tallies total issued vs cancelled counts.",
    auditOutput: "Table 13 Document Sequence Audit Certificate.",
  },

  // ─── GSTR-9C Annual Audit Workpapers ───
  {
    id: "r20",
    code: "G9C_001",
    category: "g9c",
    categoryLabel: "GSTR-9C Annual Audit",
    title: "Table 8A vs Table 8B/8C 12-Month Period Rollup",
    sectionRef: "CGST Act Section 44 r/w Rule 80(3)",
    condition: "Annual reconciliation of ITC reflected in GSTR-2B (Table 8A) against ITC availed in GSTR-3B (Table 8B & 8C).",
    action: "Compiles all 12 monthly GSTR-2B returns against purchase ledgers, isolating timing differences causing Table 8D gaps.",
    auditOutput: "Table 8D Reconciliation Statement with zero unverified variance.",
  },
  {
    id: "r21",
    code: "G9C_002",
    category: "g9c",
    categoryLabel: "GSTR-9C Annual Audit",
    title: "Supplier-Wise PAN Rollup & Cross-State Branch Aggregation",
    sectionRef: "CGST Act Section 44 Table 8 Workpapers",
    condition: "Multi-state suppliers billing across different branch GSTINs under the same Corporate PAN.",
    action: "Rolls up all transactions by 10-digit PAN, matching total financial year turnover and eligible tax credits.",
    auditOutput: "Supplier PAN Workpaper Sheet 2 in GSTR-9C Audit Pack.",
  },
];

export default function ReconDepthPage() {
  // Interactive State
  const [selectedMatchLevel, setSelectedMatchLevel] = useState<MatchLevelKey>("L2");
  const [selectedRuleCategory, setSelectedRuleCategory] = useState<RuleCategory>("all");
  const [ruleSearchQuery, setRuleSearchQuery] = useState("");
  const [excessClaimAmount, setExcessClaimAmount] = useState(2800000); // 28 Lakhs
  const [availableItc] = useState(12000000); // 1.2 Crore
  const [activeSheet, setActiveSheet] = useState<ExcelSheetKey>("sheet1");
  const [copiedReply, setCopiedReply] = useState(false);

  // Filtered Rules
  const filteredRules = STATUTORY_RULES.filter((rule) => {
    const matchesCategory =
      selectedRuleCategory === "all" || rule.category === selectedRuleCategory;
    const matchesSearch =
      rule.title.toLowerCase().includes(ruleSearchQuery.toLowerCase()) ||
      rule.code.toLowerCase().includes(ruleSearchQuery.toLowerCase()) ||
      rule.sectionRef.toLowerCase().includes(ruleSearchQuery.toLowerCase()) ||
      rule.condition.toLowerCase().includes(ruleSearchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  // Calculate Rule 88D Thresholds
  const excessPct = ((excessClaimAmount / availableItc) * 100).toFixed(1);
  const isRule88DTrigger =
    excessClaimAmount > 2500000 && Number(excessPct) > 10.0;

  const handleCopyReply = () => {
    setCopiedReply(true);
    setTimeout(() => setCopiedReply(false), 2000);
  };

  return (
    <div className="min-h-screen bg-white text-[#0A0A0A] font-sans selection:bg-[#7B5CFA]/20 selection:text-[#7B5CFA]">
      
      {/* ─── Hero Section & Glowing Punchline ─── */}
      <section className="relative overflow-hidden pt-20 pb-16 sm:pt-28 sm:pb-24 border-b border-[#E5E5E2]">
        {/* Soft Violet Aura Background */}
        <div
          className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-96 w-[700px] rounded-full bg-[#7B5CFA]/10 blur-[120px]"
          aria-hidden="true"
        />

        <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 text-center">
          
          {/* Eyebrow */}
          <div className="inline-flex items-center gap-2 rounded-full border border-purple-200 bg-purple-50 px-4 py-1.5 text-xs font-extrabold uppercase tracking-widest text-[#7B5CFA]">
            <Zap className="h-3.5 w-3.5" />
            <span>Technical Architecture &amp; Statutory Engine Specifications</span>
          </div>

          {/* Glowing Bold Punchline */}
          <h1 className="mt-8 text-4xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-6xl lg:text-7xl">
            Inside{" "}
            <span className="relative inline-block text-[#7B5CFA] drop-shadow-[0_0_40px_rgba(123,92,250,0.55)]">
              ReconDesk
            </span>
          </h1>

          {/* Subtitle in readable black text */}
          <p className="mx-auto mt-6 max-w-3xl text-lg font-medium text-[#1E293B] sm:text-2xl leading-relaxed">
            Every layer of matching, every compliance rule, every decision — explained.
          </p>

          {/* Live Engine Diagnostic Spec Bar */}
          <div className="mt-10 mx-auto max-w-4xl rounded-[14px] border border-[#E2E8F0] bg-[#FAFAFA] p-3.5 px-5 shadow-xs flex flex-wrap items-center justify-center gap-4 sm:gap-8 text-xs sm:text-sm font-semibold text-[#475569]">
            <span className="flex items-center gap-1.5 text-[#0F172A]">
              <Cpu className="h-4 w-4 text-[#7B5CFA]" />
              <span>103 Hardcoded Statutory Rules</span>
            </span>
            <span className="flex items-center gap-1.5 text-emerald-700">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              <span>₹0 Financial Drift Guarantee</span>
            </span>
            <span className="flex items-center gap-1.5 text-blue-700">
              <ShieldCheck className="h-4 w-4 text-blue-600" />
              <span>Paise-Level Audit Rigor</span>
            </span>
            <span className="flex items-center gap-1.5 text-purple-700">
              <Lock className="h-4 w-4 text-[#7B5CFA]" />
              <span>Zero AI Model Ingestion</span>
            </span>
          </div>

        </div>
      </section>

      {/* ─── Sticky Precision Sub-Nav Rail ─── */}
      <nav className="sticky top-16 z-40 w-full border-b border-[#E5E5E2] bg-white/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-start sm:justify-center overflow-x-auto px-4 py-3 scrollbar-none gap-2">
          {[
            { label: "01 Ingestion", href: "#ingestion" },
            { label: "02 5-Level Engine", href: "#engine" },
            { label: "03 103+ Rule Codex", href: "#rules" },
            { label: "04 Outward GSTR-1", href: "#outward" },
            { label: "05 Notice Shield", href: "#shield" },
            { label: "06 9C Audit Workpapers", href: "#audit" },
            { label: "07 CA Governance", href: "#governance" },
          ].map((item) => (
            <a
              key={item.label}
              href={item.href}
              className="shrink-0 rounded-full px-3.5 py-1 text-xs sm:text-sm font-bold text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#0A0A0A] transition-colors"
            >
              {item.label}
            </a>
          ))}
        </div>
      </nav>

      {/* ─── Chapter 1: Universal Ingestion & Auto-Detection ─── */}
      <section id="ingestion" className="py-16 sm:py-24 border-b border-[#E5E5E2]">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          
          <div className="max-w-3xl">
            <span className="font-mono text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
              Chapter 01 · Data Ingestion Architecture
            </span>
            <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
              Zero Column Remapping. Universal Accounting Ingestion.
            </h2>
            <p className="mt-3 text-base sm:text-lg text-[#555555] leading-relaxed">
              ReconDesk eliminates the tedious spreadsheet preparation step. Upload raw client files directly from any software; our header detection engine auto-detects fields in under a second.
            </p>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
            
            {/* Capability 1 */}
            <div className="rounded-[16px] border border-[#E5E5E2] bg-[#FAFAFA] p-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-white border border-[#E2E8F0] text-[#7B5CFA] shadow-xs">
                <FileSpreadsheet className="h-5 w-5" />
              </div>
              <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
                Any Accounting Software
              </h3>
              <p className="mt-2 text-sm sm:text-base text-[#64748B] leading-relaxed">
                Native support for <strong>Tally Prime, Tally ERP 9, Busy Accounting, Zoho Books, SAP, Oracle Financials</strong>, and custom firm Excel/CSV exports without altering headers.
              </p>
            </div>

            {/* Capability 2 */}
            <div className="rounded-[16px] border border-[#E5E5E2] bg-[#FAFAFA] p-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-white border border-[#E2E8F0] text-emerald-600 shadow-xs">
                <Zap className="h-5 w-5" />
              </div>
              <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
                1-Second Portal Parser
              </h3>
              <p className="mt-2 text-sm sm:text-base text-[#64748B] leading-relaxed">
                High-speed parsing of massive GSTR-2B JSON and Excel dumps (10,000+ invoices in &lt;1.2 seconds) with auto-normalization of IGST, CGST, SGST, and Cess components.
              </p>
            </div>

            {/* Capability 3 */}
            <div className="rounded-[16px] border border-[#E5E5E2] bg-[#FAFAFA] p-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-white border border-[#E2E8F0] text-blue-600 shadow-xs">
                <KeyRound className="h-5 w-5" />
              </div>
              <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
                1-Click GSTN Direct OTP Fetch
              </h3>
              <p className="mt-2 text-sm sm:text-base text-[#64748B] leading-relaxed">
                Direct government portal integration. Enter client GSTIN, verify with OTP, and pull official GSTR-2B data automatically without manual portal downloads.
              </p>
            </div>

          </div>

        </div>
      </section>

      {/* ─── Chapter 2: The 5-Level Matching Architecture ─── */}
      <section id="engine" className="py-16 sm:py-24 border-b border-[#E5E5E2] bg-[#FAFAFA]">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          
          <div className="max-w-3xl">
            <span className="font-mono text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
              Chapter 02 · Deterministic Multi-Phase Matcher
            </span>
            <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
              The 5-Level Matching Architecture
            </h2>
            <p className="mt-3 text-base sm:text-lg text-[#555555] leading-relaxed">
              Standard Excel VLOOKUP fails because invoice formatting is inherently messy. ReconDesk resolves invoice discrepancies through 5 progressive deterministic tiers with ₹0 financial delta.
            </p>
          </div>

          {/* Interactive Match Dissector Widget */}
          <div className="mt-12 rounded-[20px] border border-[#E2E8F0] bg-white p-6 sm:p-8 shadow-sm">
            
            {/* Level Selector Tabs */}
            <div className="flex flex-wrap items-center gap-2 border-b border-[#E2E8F0] pb-4">
              {[
                { key: "L1" as MatchLevelKey, label: "L1 · Exact Match", pill: "≤ ₹1 Paise" },
                { key: "L2" as MatchLevelKey, label: "L2 · Format Normalized", pill: "Prefix/Zero Diff" },
                { key: "L3" as MatchLevelKey, label: "L3 · Tolerance Drift", pill: "Value/Date Shift" },
                { key: "L4" as MatchLevelKey, label: "L4 · Multi-State PAN", pill: "Branch Cross-Match" },
                { key: "L6" as MatchLevelKey, label: "L6 · Unilateral / Orphan", pill: "Missing in 2B/Books" },
              ].map((lvl) => (
                <button
                  key={lvl.key}
                  type="button"
                  onClick={() => setSelectedMatchLevel(lvl.key)}
                  className={`flex items-center gap-2 rounded-full px-4 py-2 text-xs sm:text-sm font-bold transition-all ${
                    selectedMatchLevel === lvl.key
                      ? "bg-[#0A0A0A] text-white shadow-xs"
                      : "bg-[#F8FAFC] text-[#64748B] border border-[#E2E8F0] hover:text-[#0A0A0A]"
                  }`}
                >
                  <span>{lvl.label}</span>
                  <span
                    className={`rounded-full px-1.5 py-0.2 text-[9px] sm:text-[10px] ${
                      selectedMatchLevel === lvl.key
                        ? "bg-white/20 text-white"
                        : "bg-[#E2E8F0] text-[#475569]"
                    }`}
                  >
                    {lvl.pill}
                  </span>
                </button>
              ))}
            </div>

            {/* Level Dissection Visual */}
            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2 items-center">
              
              {/* Left: Code / Invoice Morph Visual */}
              <div className="rounded-[14px] border border-[#E2E8F0] bg-[#F8FAFC] p-5 font-mono text-xs sm:text-sm text-[#334155]">
                <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-2 text-[11px] sm:text-xs font-bold text-[#0F172A]">
                  <span>INVOICE_PAIR_DISSECTION</span>
                  <span className="text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100">
                    Active Level: {selectedMatchLevel}
                  </span>
                </div>

                {selectedMatchLevel === "L1" && (
                  <div className="mt-4 space-y-3">
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">GSTR-2B (Portal JSON):</p>
                      <p className="font-bold text-[#0F172A]">27AAACT0012P1ZR · INV-8841 · ₹1,42,800.00</p>
                    </div>
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">Purchase Register (Tally):</p>
                      <p className="font-bold text-[#0F172A]">27AAACT0012P1ZR · INV-8841 · ₹1,42,800.00</p>
                    </div>
                    <div className="rounded bg-emerald-50 p-2.5 text-xs sm:text-sm font-bold text-emerald-800 border border-emerald-200">
                      ✓ Exact Match: 100% Identity on GSTIN, Invoice #, and Tax Value (Diff: ₹0.00)
                    </div>
                  </div>
                )}

                {selectedMatchLevel === "L2" && (
                  <div className="mt-4 space-y-3">
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">GSTR-2B (Portal JSON):</p>
                      <p className="font-bold text-[#0F172A]">27AAACT0012P1ZR · <span className="bg-purple-100 text-purple-800 px-1 rounded">INV/2026/0941</span> · ₹57,354.20</p>
                    </div>
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">Purchase Register (Tally):</p>
                      <p className="font-bold text-[#0F172A]">27AAACT0012P1ZR · <span className="bg-purple-100 text-purple-800 px-1 rounded">941</span> · ₹57,354.20</p>
                    </div>
                    <div className="rounded bg-purple-50 p-2.5 text-xs sm:text-sm font-bold text-[#7B5CFA] border border-purple-200">
                      ✨ L2 Normalized: Stripped &apos;/2026/&apos; prefix and leading zeros. Financial Delta: ₹0.00.
                    </div>
                  </div>
                )}

                {selectedMatchLevel === "L3" && (
                  <div className="mt-4 space-y-3">
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">GSTR-2B (Portal JSON):</p>
                      <p className="font-bold text-[#0F172A]">29IAVQW2226S5Z3 · BILL-110 · ₹9,088.33 (30 Jun 2026)</p>
                    </div>
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">Purchase Register (Tally):</p>
                      <p className="font-bold text-[#0F172A]">29IAVQW2226S5Z3 · BILL-110 · ₹9,090.00 (02 Jul 2026)</p>
                    </div>
                    <div className="rounded bg-amber-50 p-2.5 text-xs sm:text-sm font-bold text-amber-900 border border-amber-200">
                      ⚠️ L3 Tolerance Match: ₹1.67 rounding delta &amp; cross-period date shift.
                    </div>
                  </div>
                )}

                {selectedMatchLevel === "L4" && (
                  <div className="mt-4 space-y-3">
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">GSTR-2B (Maharashtra Branch):</p>
                      <p className="font-bold text-[#0F172A]"><span className="bg-blue-100 text-blue-800 px-1 rounded">27</span>AAACB1234F1ZR · INV-502 · ₹3,20,000</p>
                    </div>
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">Purchase Register (Karnataka Branch):</p>
                      <p className="font-bold text-[#0F172A]"><span className="bg-blue-100 text-blue-800 px-1 rounded">29</span>AAACB1234F1ZK · INV-502 · ₹3,20,000</p>
                    </div>
                    <div className="rounded bg-blue-50 p-2.5 text-xs sm:text-sm font-bold text-blue-900 border border-blue-200">
                      🌐 L4 Multi-State PAN Match: Same 10-digit entity PAN (AAACB1234F). Prevents wrongful rejection.
                    </div>
                  </div>
                )}

                {selectedMatchLevel === "L6" && (
                  <div className="mt-4 space-y-3">
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">Missed ITC (2B Only):</p>
                      <p className="font-bold text-red-600">3 Invoices in 2B · ₹4,12,000 Unclaimed in Books</p>
                    </div>
                    <div className="rounded bg-white p-3 border border-[#E2E8F0]">
                      <p className="text-[10px] sm:text-xs text-[#64748B]">Ineligible / Pending (Books Only):</p>
                      <p className="font-bold text-amber-700">5 Invoices in Books · ₹2,95,000 Missing from Supplier 2B</p>
                    </div>
                    <div className="rounded bg-gray-100 p-2.5 text-xs sm:text-sm font-bold text-[#0F172A] border border-gray-300">
                      🔍 L6 Unilateral Classification: Segregates missed tax credits from defaulting supplier liabilities.
                    </div>
                  </div>
                )}

              </div>

              {/* Right: Technical Explanation */}
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-[#7B5CFA]">
                  Statutory Rigor
                </span>
                <h3 className="mt-1 text-2xl font-bold text-[#0A0A0A]">
                  How {selectedMatchLevel} Operates
                </h3>
                <p className="mt-3 text-sm sm:text-base text-[#555555] leading-relaxed">
                  {selectedMatchLevel === "L1" &&
                    "L1 executes a bitwise comparison across Supplier GSTIN, alphanumeric invoice serials, and tax buckets (IGST, CGST, SGST, Cess). Over 60% of clean vendor invoices resolve here in milliseconds with absolute certainty."}
                  {selectedMatchLevel === "L2" &&
                    "Suppliers frequently file with prefixes like 'INV/26/', '2026-', or strip leading zeroes ('00941' vs '941'). ReconDesk extracts the core numerical and alphanumeric token, bridging the format gap without human intervention."}
                  {selectedMatchLevel === "L3" &&
                    "Accounts teams often encounter fractional paise round-off differences or invoices dated on the 31st but booked on the 1st of the next month. L3 flags these as soft matches with exact delta logs for CA approval."}
                  {selectedMatchLevel === "L4" &&
                    "Large enterprises (e.g. Tata, Reliance, L&T) bill from multiple state GSTINs under the same Corporate PAN. L4 automatically identifies cross-state branch supplies, preventing accidental double payment or false mismatch alarms."}
                  {selectedMatchLevel === "L6" &&
                    "Unmatched invoices are automatically quarantined into actionable buckets: 'Missed ITC' (available to claim before Section 16(4) cut-off) and 'ITC at Risk' (ready for 1-click supplier follow-up demand notices)."}
                </p>

                <div className="mt-6 flex flex-wrap items-center gap-4 text-xs sm:text-sm font-semibold text-[#0F172A]">
                  <span className="flex items-center gap-1.5">
                    <Check className="h-4 w-4 text-emerald-600" />
                    Zero Loss of Audit Trail
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Check className="h-4 w-4 text-emerald-600" />
                    Reviewer Timestamp Attached
                  </span>
                </div>
              </div>

            </div>

          </div>

        </div>
      </section>

      {/* ─── Chapter 3: The 103+ Statutory Rule Codex ─── */}
      <section id="rules" className="py-16 sm:py-24 border-b border-[#E5E5E2]">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          
          <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
            <div className="max-w-2xl">
              <span className="font-mono text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
                Chapter 03 · Statutory Intelligence
              </span>
              <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
                The 103+ Statutory Rules Codex
              </h2>
              <p className="mt-3 text-base sm:text-lg text-[#555555] leading-relaxed">
                Every tax check in ReconDesk is directly mapped to the Central Goods and Services Tax Act, 2017 and CGST Rules. Search and inspect the comprehensive statutory rules catalogue below.
              </p>
            </div>

            {/* Search Input */}
            <div className="relative w-full md:w-72">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-[#94A3B8]" />
              <input
                type="text"
                placeholder="Search rule (e.g. 17(5), 37, 88D)..."
                value={ruleSearchQuery}
                onChange={(e) => setRuleSearchQuery(e.target.value)}
                className="w-full rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] py-2.5 pl-9 pr-3 text-xs sm:text-sm text-[#0F172A] placeholder-[#94A3B8] focus:border-[#7B5CFA] focus:bg-white focus:outline-none focus:ring-1 focus:ring-[#7B5CFA]"
              />
            </div>
          </div>

          {/* Category Filter Chips */}
          <div className="mt-8 flex flex-wrap items-center gap-2">
            {[
              { key: "all" as RuleCategory, label: `All Rules (${filteredRules.length})` },
              { key: "sec16" as RuleCategory, label: "Section 16 Eligibility" },
              { key: "rule37" as RuleCategory, label: "Rule 37 (180 Days)" },
              { key: "sec17" as RuleCategory, label: "Section 17(5) Blocked" },
              { key: "rule88d" as RuleCategory, label: "Rule 88D / DRC-01C" },
              { key: "rcm" as RuleCategory, label: "RCM Section 9(3)" },
              { key: "g1m" as RuleCategory, label: "GSTR-1 Outward Diagnostics" },
              { key: "g9c" as RuleCategory, label: "GSTR-9C Annual Audit" },
            ].map((cat) => (
              <button
                key={cat.key}
                type="button"
                onClick={() => setSelectedRuleCategory(cat.key)}
                className={`rounded-full px-4 py-2 text-xs sm:text-sm font-semibold transition-all ${
                  selectedRuleCategory === cat.key
                    ? "bg-[#7B5CFA] text-white shadow-xs"
                    : "bg-white text-[#64748B] border border-[#E2E8F0] hover:bg-[#F8FAFC] hover:text-[#0A0A0A]"
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>

          {/* Rule Status Summary Bar */}
          <div className="mt-4 flex items-center justify-between text-xs sm:text-sm text-[#64748B]">
            <span>Showing <strong>{filteredRules.length}</strong> core statutory verification handlers</span>
            <span className="text-emerald-700 font-semibold">● 100% Audit-Grade Traceability</span>
          </div>

          {/* Rule Cards Grid */}
          <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-2">
            {filteredRules.map((rule) => (
              <div
                key={rule.id}
                className="rounded-[16px] border border-[#E5E5E2] bg-white p-6 shadow-xs transition-all hover:border-[#7B5CFA]/40 hover:shadow-sm flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-[#7B5CFA] bg-purple-50 px-2.5 py-1 rounded border border-purple-100">
                      {rule.code}
                    </span>
                    <span className="text-xs font-semibold text-[#64748B]">
                      {rule.sectionRef}
                    </span>
                  </div>

                  <h3 className="mt-3.5 text-base sm:text-lg font-bold text-[#0A0A0A]">
                    {rule.title}
                  </h3>

                  <div className="mt-3.5 space-y-2.5 text-xs sm:text-sm">
                    <div className="rounded-[10px] bg-[#F8FAFC] p-3 border border-[#E2E8F0]">
                      <span className="font-bold text-[#334155]">Trigger Condition: </span>
                      <span className="text-[#64748B] leading-relaxed">{rule.condition}</span>
                    </div>

                    <div className="rounded-[10px] bg-[#FAF5FF] p-3 border border-purple-100 text-[#6B21A8]">
                      <span className="font-bold">ReconDesk Action: </span>
                      <span className="leading-relaxed">{rule.action}</span>
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex items-center justify-between border-t border-[#F1F5F9] pt-3 text-xs text-[#64748B]">
                  <span className="font-semibold text-[#0F172A]">{rule.auditOutput}</span>
                  <span className="text-emerald-600 font-bold">● Active in Pipeline</span>
                </div>
              </div>
            ))}
          </div>

        </div>
      </section>

      {/* ─── Chapter 4: Outward Revenue & GSTR-1 Diagnostics ─── */}
      <section id="outward" className="py-16 sm:py-24 border-b border-[#E5E5E2] bg-[#FAFAFA]">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          
          <div className="max-w-3xl">
            <span className="font-mono text-xs font-bold uppercase tracking-widest text-emerald-600">
              Chapter 04 · Outward Supply &amp; Revenue Reconciliation
            </span>
            <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
              GSTR-1 Outward Diagnostics (G1M1–G1M10)
            </h2>
            <p className="mt-3 text-base sm:text-lg text-[#555555] leading-relaxed">
              Ensure outward tax liabilities match accounting ledgers before monthly filing locks. ReconDesk executes 10 diagnostic tests across B2B, B2CL, export LUT, and document sequences.
            </p>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2">
            
            <div className="rounded-[16px] border border-[#E5E5E2] bg-white p-6 shadow-xs">
              <div className="flex items-center justify-between">
                <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-800 border border-emerald-100">
                  G1M1 → G1M10 Diagnostic Matrix
                </span>
                <span className="text-xs font-mono font-bold text-[#64748B]">Table 4 to 13</span>
              </div>

              <ul className="mt-5 space-y-3 text-xs sm:text-sm text-[#334155]">
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold text-[#0F172A]">G1M1 / G1M2: </span>
                    <span>Inward B2B sales in books missing in GSTR-1 or vice-versa.</span>
                  </div>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold text-[#0F172A]">G1M3 / G1M4: </span>
                    <span>Tax rate drift (e.g. 18% billed in books vs 12% declared on portal).</span>
                  </div>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold text-[#0F172A]">G1M5 / G1M6: </span>
                    <span>B2B invoice wrongly classified under B2CL or B2CS unorganized retail.</span>
                  </div>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold text-[#0F172A]">G1M7 / G1M8: </span>
                    <span>Export invoice with/without payment of tax vs shipping bill LUT mismatch.</span>
                  </div>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold text-[#0F172A]">G1M9 / G1M10: </span>
                    <span>Credit note (CDNR) without original invoice linkage &amp; Table 13 count gap.</span>
                  </div>
                </li>
              </ul>
            </div>

            <div className="rounded-[16px] border border-[#E5E5E2] bg-white p-6 shadow-xs flex flex-col justify-between">
              <div>
                <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-800 border border-blue-100">
                  GSTR-1A Mid-Month Window
                </span>
                <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
                  Pre-Filing Amendment Recommendations
                </h3>
                <p className="mt-2 text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
                  Before the monthly portal window locks on the 14th, ReconDesk generates a formatted amendment schedule so you can rectify supplier disputes in GSTR-1A before GSTR-3B liability is generated.
                </p>

                <div className="mt-4 rounded-[10px] border border-blue-200 bg-[#EFF6FF] p-3 text-xs text-blue-950 font-mono">
                  <div className="font-bold border-b border-blue-200 pb-1 flex justify-between">
                    <span>GSTR-1A Amendment Action Schedule</span>
                    <span className="text-blue-700">FY 2026–27</span>
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-blue-900">
                    ⚡ 3 B2B Invoices recommended for upward value amendment · ₹42,000 differential tax pre-calculated.
                  </p>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-[#F1F5F9] text-xs sm:text-sm font-semibold text-[#0F172A]">
                Eliminates Rule 88C DRC-01B outward liability intimations
              </div>
            </div>

          </div>

        </div>
      </section>

      {/* ─── Chapter 5: GSTR-3B Notice Shield & DRC-01C Reply Drafter ─── */}
      <section id="shield" className="py-16 sm:py-24 border-b border-[#E5E5E2]">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          
          <div className="max-w-3xl">
            <span className="font-mono text-xs font-bold uppercase tracking-widest text-[#F59E0B]">
              Chapter 05 · Notice Defense System
            </span>
            <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
              Rule 88D Notice Shield &amp; DRC-01B/C Drafter
            </h2>
            <p className="mt-3 text-base sm:text-lg text-[#555555] leading-relaxed">
              Under Rule 88D, whenever ITC claimed in GSTR-3B exceeds GSTR-2B by &gt;10% and &gt;₹25 Lakhs, an automated DRC-01C intimation is generated by the GST portal. ReconDesk stress-tests your return before filing.
            </p>
          </div>

          {/* Interactive Simulator */}
          <div className="mt-12 rounded-[20px] border border-[#E5E5E2] bg-[#FAFAFA] p-6 sm:p-8">
            
            <div className="grid grid-cols-1 gap-8 lg:grid-cols-2 items-center">
              
              {/* Controls */}
              <div>
                <h3 className="text-lg font-bold text-[#0A0A0A]">
                  Rule 88D Dual-Threshold Stress-Tester
                </h3>
                <p className="mt-1 text-xs sm:text-sm text-[#64748B]">
                  Drag the slider to test how ReconDesk monitors excess ITC claims against statutory thresholds.
                </p>

                <div className="mt-6 space-y-4">
                  <div>
                    <div className="flex justify-between text-xs sm:text-sm font-semibold text-[#334155]">
                      <span>Excess ITC Claimed in 3B:</span>
                      <span className="font-mono text-sm sm:text-base font-bold text-[#7B5CFA]">
                        ₹{(excessClaimAmount / 100000).toFixed(2)} Lakhs
                      </span>
                    </div>
                    <input
                      type="range"
                      min={500000}
                      max={6000000}
                      step={100000}
                      value={excessClaimAmount}
                      onChange={(e) => setExcessClaimAmount(Number(e.target.value))}
                      className="mt-2 w-full accent-[#7B5CFA] cursor-pointer"
                    />
                    <div className="flex justify-between text-[10px] sm:text-xs text-[#94A3B8] font-mono mt-1">
                      <span>₹5 Lakhs</span>
                      <span>Threshold: ₹25 Lakhs</span>
                      <span>₹60 Lakhs</span>
                    </div>
                  </div>

                  <div className="rounded-[12px] border border-[#E2E8F0] bg-white p-4 space-y-2 text-xs sm:text-sm">
                    <div className="flex justify-between text-[#64748B]">
                      <span>Available ITC in 2B:</span>
                      <span className="font-bold text-[#0F172A]">₹1,20,00,000 (1.20 Cr)</span>
                    </div>
                    <div className="flex justify-between text-[#64748B]">
                      <span>Excess Percentage:</span>
                      <span className="font-bold text-[#0F172A]">{excessPct}%</span>
                    </div>
                    <div className="flex justify-between text-[#64748B] border-t border-[#F1F5F9] pt-2">
                      <span>Dual-Threshold Status:</span>
                      <span
                        className={`font-bold px-2 py-0.5 rounded text-xs ${
                          isRule88DTrigger
                            ? "bg-red-100 text-red-800"
                            : "bg-emerald-100 text-emerald-800"
                        }`}
                      >
                        {isRule88DTrigger ? "🔴 DRC-01C STATUTORY TRIGGER" : "🟢 SAFE (Below Threshold)"}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Live DRC-01B/C Reply Output */}
              <div className="rounded-[14px] border border-[#E2E8F0] bg-white p-5 font-mono text-xs sm:text-sm">
                <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-2 text-xs font-bold text-[#0F172A]">
                  <span>FORM_GST_DRC_01B_PART_B_REPLY</span>
                  <span className="text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-100">
                    Statutory Template
                  </span>
                </div>

                <div className="mt-3 rounded-[8px] bg-[#F8FAFC] p-3 text-xs sm:text-sm leading-relaxed text-[#475569] border border-[#E2E8F0]">
                  <p className="font-bold text-[#0F172A]">
                    Reason 1: Excess liability / timing difference under Section 16(4)
                  </p>
                  <p className="mt-1.5 text-[#64748B]">
                    &quot;The differential ITC of ₹{(excessClaimAmount / 100000).toFixed(2)} Lakhs pertains to inward supplies of previous tax periods in respect of which tax was deposited by suppliers but reflected in GSTR-2B of the current tax period. Workings are maintained and verified.&quot;
                  </p>
                </div>

                <div className="mt-4 flex items-center justify-between pt-2 border-t border-[#F1F5F9]">
                  <button
                    type="button"
                    onClick={handleCopyReply}
                    className="inline-flex items-center gap-1.5 text-xs sm:text-sm font-bold text-[#7B5CFA] hover:text-[#6C4DE6]"
                  >
                    {copiedReply ? (
                      <>
                        <Check className="h-4 w-4 text-emerald-600" />
                        <span className="text-emerald-600">Copied to Clipboard!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-4 w-4" />
                        <span>Copy Statutory Reply Draft</span>
                      </>
                    )}
                  </button>
                  <span className="text-xs text-[#94A3B8]">PDF &amp; Word Export Ready</span>
                </div>
              </div>

            </div>

          </div>

        </div>
      </section>

      {/* ─── Chapter 6: GSTR-9C Annual Audit Workbook Architecture ─── */}
      <section id="audit" className="py-16 sm:py-24 border-b border-[#E5E5E2] bg-[#FAFAFA]">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          
          <div className="max-w-3xl">
            <span className="font-mono text-xs font-bold uppercase tracking-widest text-blue-600">
              Chapter 06 · Annual Certification
            </span>
            <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
              GSTR-9C Multi-Sheet Audit Workbook Architecture
            </h2>
            <p className="mt-3 text-base sm:text-lg text-[#555555] leading-relaxed">
              At financial year-end, manual 12-month reconciliation is a nightmare. ReconDesk rolls up all 12 monthly GSTR-2B returns against your annual purchase register into a ready-to-certify multi-sheet `.xlsx` workbook.
            </p>
          </div>

          {/* Interactive Excel Dissector */}
          <div className="mt-12 rounded-[20px] border border-[#E2E8F0] bg-white overflow-hidden shadow-sm">
            
            {/* Sheet Tabs Header */}
            <div className="flex items-center bg-[#F1F5F9] border-b border-[#E2E8F0] px-4 pt-3 gap-1 overflow-x-auto scrollbar-none">
              {[
                { key: "sheet1" as ExcelSheetKey, label: "Sheet 1: Table 8A vs 8B/8C Tie-Out" },
                { key: "sheet2" as ExcelSheetKey, label: "Sheet 2: Supplier PAN Rollup" },
                { key: "sheet3" as ExcelSheetKey, label: "Sheet 3: Audit Observations Log" },
                { key: "sheet4" as ExcelSheetKey, label: "Sheet 4: Rule 37 & 17(5) Reversals" },
              ].map((sheet) => (
                <button
                  key={sheet.key}
                  type="button"
                  onClick={() => setActiveSheet(sheet.key)}
                  className={`rounded-t-[8px] px-4 py-2.5 text-xs sm:text-sm font-bold transition-all ${
                    activeSheet === sheet.key
                      ? "bg-white text-[#0A0A0A] border-t border-x border-[#E2E8F0] shadow-2xs"
                      : "text-[#64748B] hover:text-[#0A0A0A]"
                  }`}
                >
                  {sheet.label}
                </button>
              ))}
            </div>

            {/* Active Sheet Content */}
            <div className="p-6 font-mono text-xs sm:text-sm">
              {activeSheet === "sheet1" && (
                <div className="space-y-4">
                  <div className="flex justify-between items-center text-xs sm:text-sm font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2">
                    <span>ANNUAL GSTR-9 TABLE 8 RECONCILIATION SCHEDULE</span>
                    <span className="text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">FY 2025–26 ROLLUP</span>
                  </div>
                  <div className="space-y-2 text-xs sm:text-sm">
                    <div className="flex justify-between p-3 rounded bg-[#F8FAFC]">
                      <span>Table 8A (ITC available in GSTR-2B auto-drafted):</span>
                      <span className="font-bold text-[#0F172A]">₹5,78,94,200.00</span>
                    </div>
                    <div className="flex justify-between p-3 rounded bg-[#F8FAFC]">
                      <span>Table 8B (ITC as per GSTR-3B Table 4(A)(5) availed):</span>
                      <span className="font-bold text-[#0F172A]">₹5,78,94,200.00</span>
                    </div>
                    <div className="flex justify-between p-3 rounded bg-emerald-50 text-[#166534] font-bold">
                      <span>Table 8D Difference (8A − (8B + 8C)):</span>
                      <span>₹0.00 (Zero Drift Certified)</span>
                    </div>
                  </div>
                </div>
              )}

              {activeSheet === "sheet2" && (
                <div className="space-y-4">
                  <div className="flex justify-between items-center text-xs sm:text-sm font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2">
                    <span>SUPPLIER-WISE 10-DIGIT PAN CUMULATIVE ROLLUP</span>
                    <span className="text-blue-700 bg-blue-50 px-2 py-0.5 rounded">244 ENTITIES</span>
                  </div>
                  <div className="space-y-2 text-xs sm:text-sm">
                    <div className="flex justify-between p-3 rounded bg-[#F8FAFC]">
                      <span>Tata Steel Ltd (PAN: AAACB1234F · 4 State GSTINs):</span>
                      <span className="font-bold text-[#0F172A]">184 Invoices · ₹1,48,20,000 (100% Matched)</span>
                    </div>
                    <div className="flex justify-between p-3 rounded bg-[#F8FAFC]">
                      <span>Reliance Industries (PAN: AAACT0012P · 7 State GSTINs):</span>
                      <span className="font-bold text-[#0F172A]">92 Invoices · ₹88,40,000 (100% Matched)</span>
                    </div>
                  </div>
                </div>
              )}

              {activeSheet === "sheet3" && (
                <div className="space-y-4">
                  <div className="flex justify-between items-center text-xs sm:text-sm font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2">
                    <span>SEVERITY-RANKED AUDIT OBSERVATIONS LOG</span>
                    <span className="text-amber-700 bg-amber-50 px-2 py-0.5 rounded">0 HIGH RISK</span>
                  </div>
                  <div className="space-y-2 text-xs sm:text-sm">
                    <div className="flex justify-between p-3 rounded bg-[#FFFBEB] text-amber-950">
                      <span>Obs #01: 3 Invoices with rounding differences &gt; ₹5 (L3 review notes attached).</span>
                      <span className="font-bold">LOW RISK</span>
                    </div>
                    <div className="flex justify-between p-3 rounded bg-[#F0FDF4] text-emerald-900">
                      <span>Obs #02: All Section 16(2)(aa) 2B reflection proofs verified for FY.</span>
                      <span className="font-bold">VERIFIED</span>
                    </div>
                  </div>
                </div>
              )}

              {activeSheet === "sheet4" && (
                <div className="space-y-4">
                  <div className="flex justify-between items-center text-xs sm:text-sm font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2">
                    <span>RULE 37 &amp; SECTION 17(5) STATUTORY REVERSAL SCHEDULE</span>
                    <span className="text-purple-700 bg-purple-50 px-2 py-0.5 rounded">AUDIT READY</span>
                  </div>
                  <div className="space-y-2 text-xs sm:text-sm">
                    <div className="flex justify-between p-3 rounded bg-[#F8FAFC]">
                      <span>Rule 37 180-Day Reversals Required:</span>
                      <span className="font-bold text-orange-700">3 Invoices · ₹1,15,400 (Interest: ₹10,386)</span>
                    </div>
                    <div className="flex justify-between p-3 rounded bg-[#F8FAFC]">
                      <span>Section 17(5) Ineligible Credits Isolated:</span>
                      <span className="font-bold text-red-700">8 Invoices · ₹4,22,000 (HSN 8703 / 9963)</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="bg-[#F8FAFC] border-t border-[#E2E8F0] p-4 flex justify-between items-center text-xs sm:text-sm text-[#64748B]">
              <span className="font-semibold text-[#0F172A]">Format: Multi-Sheet .XLSX &amp; PDF Sign-Off Report</span>
              <span className="text-emerald-700 font-bold">● Formatted for Statutory Auditors</span>
            </div>

          </div>

        </div>
      </section>

      {/* ─── Chapter 7: CA Firm Governance & Collaboration ─── */}
      <section id="governance" className="py-16 sm:py-24 border-b border-[#E5E5E2]">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          
          <div className="max-w-3xl">
            <span className="font-mono text-xs font-bold uppercase tracking-widest text-[#7B5CFA]">
              Chapter 07 · Practice Management &amp; Audit Governance
            </span>
            <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
              Architected for CA Firm Workflows &amp; Peer Review
            </h2>
            <p className="mt-3 text-base sm:text-lg text-[#555555] leading-relaxed">
              Managing 50+ client GSTINs requires structured teamwork. ReconDesk provides multi-user firm accounts, audit locking, and automated communication tools.
            </p>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
            
            <div className="rounded-[16px] border border-[#E5E5E2] bg-[#FAFAFA] p-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-white border border-[#E2E8F0] text-[#7B5CFA] shadow-xs">
                <Users className="h-5 w-5" />
              </div>
              <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
                Unlimited Team Seats
              </h3>
              <p className="mt-2 text-sm sm:text-base text-[#64748B] leading-relaxed">
                Invite article assistants, senior audit managers, and partners. Role-based permissions ensure staff can upload and reconcile while partners approve and sign off.
              </p>
            </div>

            <div className="rounded-[16px] border border-[#E5E5E2] bg-[#FAFAFA] p-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-white border border-[#E2E8F0] text-emerald-600 shadow-xs">
                <Lock className="h-5 w-5" />
              </div>
              <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
                Finalize &amp; Lock Runs
              </h3>
              <p className="mt-2 text-sm sm:text-base text-[#64748B] leading-relaxed">
                Once a tax period is filed, partners can cryptographically lock the run. Prevents accidental edits or overwrites, maintaining immutable records for ICAI peer review.
              </p>
            </div>

            <div className="rounded-[16px] border border-[#E5E5E2] bg-[#FAFAFA] p-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-white border border-[#E2E8F0] text-purple-600 shadow-xs">
                <Mail className="h-5 w-5" />
              </div>
              <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
                1-Click Supplier Demand Letters
              </h3>
              <p className="mt-2 text-sm sm:text-base text-[#64748B] leading-relaxed">
                Automatically generate formal PDF letters and WhatsApp summaries for defaulting vendors with itemized missing invoice tables attached.
              </p>
            </div>

          </div>

        </div>
      </section>

      {/* ─── Bottom Flagship CTA Banner ─── */}
      <section className="py-20 sm:py-28 bg-[#FAFAFA]">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 text-center">
          <div className="relative overflow-hidden rounded-[20px] border border-[#E5E5E2] bg-white p-8 sm:p-14 shadow-md">
            
            {/* Ambient purple background blur */}
            <div
              className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 h-48 w-96 rounded-full bg-[#7B5CFA]/15 blur-3xl"
              aria-hidden="true"
            />

            <h2 className="relative text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
              Experience the Full Depth of ReconDesk Free
            </h2>
            <p className="relative mx-auto mt-4 max-w-xl text-base sm:text-lg text-[#64748B] leading-relaxed">
              One GSTIN is 100% free forever with all 103+ statutory rules, multi-phase matching, and full audit workpapers unlocked.
            </p>

            <div className="relative mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/auth/signup"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-full bg-[#7B5CFA] px-8 py-3.5 text-base font-bold text-white shadow-sm transition-all hover:bg-[#6C4DE6] hover:shadow-md"
              >
                <span>Start Free — One GSTIN, Forever</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-full border border-[#E2E8F0] bg-white px-7 py-3.5 text-base font-bold text-[#0A0A0A] hover:bg-[#F8FAFC] transition-colors"
              >
                <span>Back to Homepage</span>
              </Link>
            </div>

          </div>
        </div>
      </section>

    </div>
  );
}
