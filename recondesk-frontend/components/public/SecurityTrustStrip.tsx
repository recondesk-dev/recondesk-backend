"use client";

import { useState } from "react";
import {
  Ban,
  Check,
  CheckCircle2,
  Download,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  Fingerprint,
  HardDrive,
  KeyRound,
  Layers,
  Lock,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserCheck,
  Users,
} from "lucide-react";

export function SecurityTrustStrip() {
  const [purgedDemo, setPurgedDemo] = useState(false);

  const handleDemoPurge = () => {
    setPurgedDemo(true);
    setTimeout(() => setPurgedDemo(false), 2500);
  };

  return (
    <section
      id="security"
      className="scroll-mt-20 mx-auto my-16 max-w-6xl px-4 sm:px-6 lg:px-8 border-t border-[#CBD5E1]/60 pt-16"
      aria-label="Security and data protection"
    >
      {/* Section Header */}
      <div className="text-center max-w-3xl mx-auto">
        <p className="text-xs font-bold uppercase tracking-widest text-emerald-600">
          Confidentiality &amp; Data Governance
        </p>
        <h2 className="mt-2.5 text-2xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-3xl">
          Your Clients&apos; Financial Ledgers Never Leave Your Private Vault
        </h2>
        <p className="mt-2 text-sm text-[#6B6B6B] leading-relaxed">
          Architected specifically for the strict confidentiality, client isolation, and audit-grade requirements of Indian Chartered Accountancy practices.
        </p>
      </div>

      {/* Top Verified Security Strip */}
      <div className="mt-8 flex flex-wrap items-center justify-center gap-2 sm:gap-4 text-xs font-semibold text-[#334155]">
        <div className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50/70 px-3.5 py-1.5 text-emerald-800">
          <Lock className="h-3.5 w-3.5 text-emerald-600" />
          <span>AES-256 At-Rest Encryption</span>
        </div>
        <div className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50/70 px-3.5 py-1.5 text-emerald-800">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
          <span>TLS 1.3 Strict Transit</span>
        </div>
        <div className="flex items-center gap-1.5 rounded-full border border-purple-200 bg-purple-50/70 px-3.5 py-1.5 text-[#7B5CFA]">
          <Ban className="h-3.5 w-3.5 text-[#7B5CFA]" />
          <span>Zero Public AI Model Training</span>
        </div>
        <div className="flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50/70 px-3.5 py-1.5 text-blue-800">
          <Server className="h-3.5 w-3.5 text-blue-600" />
          <span>AWS Mumbai (Asia Pacific) Region</span>
        </div>
      </div>

      {/* ─── Creative 4-Pillar Data Vault Grid ─── */}
      <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-2">
        
        {/* ── Pillar 1: Firm-Level Tenant Isolation ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 border border-emerald-100">
                <Users className="h-3.5 w-3.5" />
                Firm Tenant Isolation
              </span>
              <span className="rounded bg-[#F8FAFC] text-[10px] font-mono text-[#64748B] px-2 py-0.5 border border-[#E2E8F0]">
                Per-CA Partition
              </span>
            </div>

            <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
              100% Isolated Client Schemas
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              Every CA firm operates in a cryptographically isolated tenant. No competitor or unauthorized staff can ever access your client ledgers.
            </p>

            {/* Inset Micro-Widget: Isolation Architecture */}
            <div className="mt-4 rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 font-mono text-xs text-[#334155]">
              <div className="flex items-center justify-between text-[11px] font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2">
                <span>Tenant Isolation Gateway</span>
                <span className="text-emerald-600 flex items-center gap-1">
                  <Lock className="h-3 w-3" /> Strict Guard Active
                </span>
              </div>

              <div className="mt-2.5 space-y-1.5 text-[11px]">
                <div className="flex items-center justify-between rounded bg-white p-1.5 px-2 border border-[#E2E8F0]">
                  <span className="text-[#64748B]">Client A (Tally ERP 9)</span>
                  <span className="font-bold text-[#16A34A]">Encrypted Vault ✓</span>
                </div>
                <div className="flex items-center justify-between rounded bg-white p-1.5 px-2 border border-[#E2E8F0]">
                  <span className="text-[#64748B]">Client B (Busy Accounting)</span>
                  <span className="font-bold text-[#16A34A]">Encrypted Vault ✓</span>
                </div>
              </div>

              <div className="mt-2.5 flex items-center justify-between text-[10px] text-[#94A3B8] pt-1">
                <span>Cross-Firm Access: BLOCKED</span>
                <span className="text-emerald-700 font-bold">● Zero Data Leakage</span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#F1F5F9] text-[11px] text-[#64748B]">
            Complies with ICAI code of professional confidentiality
          </div>
        </div>

        {/* ── Pillar 2: Zero AI Training Guarantee ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-50 px-3 py-1 text-xs font-bold text-[#7B5CFA] border border-purple-100">
                <Ban className="h-3.5 w-3.5" />
                Zero Model Training
              </span>
              <span className="rounded bg-purple-100 text-[#7B5CFA] text-[10px] font-bold px-2 py-0.5">
                Strict Policy
              </span>
            </div>

            <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
              Your Client Data is Never Fed to AI
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              We never use client turnovers, supplier names, invoice line-items, or purchase registers to train public or private machine learning models.
            </p>

            {/* Inset Micro-Widget: Zero Ingestion Flow */}
            <div className="mt-4 rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 font-mono text-xs text-[#334155]">
              <div className="flex items-center justify-between text-[11px] font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2">
                <span>Deterministic Processing Pipeline</span>
                <span className="text-[#7B5CFA] font-bold">100% Private</span>
              </div>

              <div className="mt-2.5 space-y-1.5 text-[11px]">
                <div className="flex items-center justify-between">
                  <span className="text-[#64748B]">Statutory Match Engine:</span>
                  <span className="font-bold text-[#0F172A]">Deterministic Math</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[#64748B]">Third-Party LLM Ingestion:</span>
                  <span className="font-bold text-red-600">PROHIBITED (0 Bytes)</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[#64748B]">Commercial Reselling:</span>
                  <span className="font-bold text-red-600">NEVER SOLD</span>
                </div>
              </div>

              <div className="mt-2.5 flex items-center justify-between text-[10px] text-purple-700 font-bold pt-1">
                <span>● Confidentiality Guarantee</span>
                <span>Protected by SLA</span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#F1F5F9] text-[11px] text-[#64748B]">
            Your client lists and trade secrets remain exclusively yours
          </div>
        </div>

        {/* ── Pillar 3: Cryptographic Audit Trails ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700 border border-blue-100">
                <Fingerprint className="h-3.5 w-3.5" />
                Audit Trail Integrity
              </span>
              <span className="rounded bg-[#F8FAFC] text-[10px] font-mono text-[#64748B] px-2 py-0.5 border border-[#E2E8F0]">
                Immutable Logs
              </span>
            </div>

            <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
              Timestamped Proof for Every CA Decision
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              Every match approval, manual tolerance override, and Rule 37 resolution is recorded in an untamperable audit log for quality reviews.
            </p>

            {/* Inset Micro-Widget: Audit Log Certificate */}
            <div className="mt-4 rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 font-mono text-xs text-[#334155]">
              <div className="flex items-center justify-between text-[11px] font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2">
                <span>AUDIT_LOG_ENTRY #RD-9914</span>
                <span className="text-blue-600 font-bold">VERIFIED</span>
              </div>

              <div className="mt-2.5 space-y-1 text-[10.5px]">
                <div className="text-[#64748B]">
                  <span className="font-semibold text-[#0F172A]">Action:</span> Soft L2 Match Confirmed (INV-0941)
                </div>
                <div className="text-[#64748B]">
                  <span className="font-semibold text-[#0F172A]">Reviewer:</span> CA Senior Associate (Team A)
                </div>
                <div className="text-[#64748B]">
                  <span className="font-semibold text-[#0F172A]">Signature:</span> sha256:7f83b1657ff1fc53b...
                </div>
              </div>

              <div className="mt-2.5 flex items-center justify-between text-[10px] text-blue-700 font-bold pt-1">
                <span>● Ready for Peer Review</span>
                <span>Exportable in 1-Click</span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#F1F5F9] text-[11px] text-[#64748B]">
            Complete accountability across all article assistants and staff
          </div>
        </div>

        {/* ── Pillar 4: 1-Click Engagement Data Purge ── */}
        <div className="relative overflow-hidden rounded-[22px] border border-white/85 bg-white p-6 sm:p-7 shadow-[var(--shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1 text-xs font-bold text-red-700 border border-red-100">
                <Trash2 className="h-3.5 w-3.5" />
                Right to Erasure
              </span>
              <span className="rounded bg-red-100 text-red-800 text-[10px] font-bold px-2 py-0.5">
                Full Control
              </span>
            </div>

            <h3 className="mt-4 text-lg font-bold text-[#0A0A0A]">
              1-Click Permanent Engagement Purge
            </h3>
            <p className="mt-1 text-xs text-[#6B6B6B] leading-relaxed">
              When an audit concludes, export full encrypted workpaper archives and permanently wipe all client invoices from our servers with one click.
            </p>

            {/* Inset Micro-Widget: Instant Purge Action Simulation */}
            <div className="mt-4 rounded-[10px] border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 text-xs text-[#334155]">
              <div className="flex items-center justify-between text-[11px] font-bold text-[#0F172A] border-b border-[#E2E8F0] pb-2 font-mono">
                <span>Client: Aarav Textiles Ltd</span>
                <span className="text-[#64748B]">FY 2025–26</span>
              </div>

              <div className="mt-3 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={handleDemoPurge}
                  className={`inline-flex items-center gap-1.5 rounded-[8px] px-3 py-1.5 text-xs font-bold transition-all ${
                    purgedDemo
                      ? "bg-emerald-600 text-white"
                      : "bg-red-600 text-white hover:bg-red-700"
                  }`}
                >
                  {purgedDemo ? (
                    <>
                      <Check className="h-3.5 w-3.5" />
                      <span>Engagement Purged (0 Bytes Left)</span>
                    </>
                  ) : (
                    <>
                      <Trash2 className="h-3.5 w-3.5" />
                      <span>Purge Client Data Permanently</span>
                    </>
                  )}
                </button>
                <span className="text-[10px] text-[#94A3B8] font-mono">0 Residual Records</span>
              </div>

              <div className="mt-2.5 flex items-center justify-between text-[10px] text-red-700 font-semibold pt-1">
                <span>● Complete Data Erasure Guarantee</span>
                <span>No Lock-In</span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#F1F5F9] text-[11px] text-[#64748B]">
            You maintain 100% legal ownership over all client files
          </div>
        </div>

      </div>
    </section>
  );
}
