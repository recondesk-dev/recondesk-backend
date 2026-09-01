import React from "react";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Clock,
  FileCheck2,
  FileSpreadsheet,
  Layers,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

export function GstrModulesGrid() {
  const modules = [
    {
      badge: "Purchase / ITC Engine",
      title: "GSTR-2B ↔ Purchase Register",
      description:
        "Full-spectrum ITC reconciliation pairing portal data with Tally, Busy, or Excel registers in seconds.",
      features: [
        "5-Level Multi-Phase Matcher (L1 to L4 & L6)",
        "Rule 37 180-day unpaid reversal alerts",
        "Section 17(5) restricted credit advisory",
        "IMS Action Center (Accept / Reject / Hold)",
      ],
      icon: Layers,
      highlight: true,
    },
    {
      badge: "Sales / Revenue",
      title: "GSTR-1 ↔ Sales Register",
      description:
        "Ensure outward supplies and tax liability match your books before monthly or quarterly filing.",
      features: [
        "G1M1–G1M10 discrepancy diagnostic codes",
        "B2B, B2CL, B2CS, CDNR & Export categorization",
        "HSN Rate & Table 13 Documents verification",
        "GSTR-1A amendment window tracking",
      ],
      icon: BarChart3,
      highlight: false,
    },
    {
      badge: "Compliance & Liability",
      title: "GSTR-3B vs Books & 2B",
      description:
        "Reconcile tax payable and ITC claimed against portal figures to pre-empt scrutiny notices.",
      features: [
        "Rule 88D / DRC-01C threshold checking",
        "ITC available vs 3B claimed variance",
        "DRC-01B draft reply narrative generator",
        "Period-by-period liability tie-out",
      ],
      icon: FileCheck2,
      highlight: false,
    },
    {
      badge: "Annual Audit Workpapers",
      title: "GSTR-9C Annual Rollup",
      description:
        "Streamline annual GST audit certifications with automated full-year ITC rollups and audit reports.",
      features: [
        "Full Financial Year (FY) cumulative ITC rollup",
        "Multi-sheet audit workpaper Excel exports",
        "Severity-ranked audit observations",
        "Carry-forward & late filing adjustments",
      ],
      icon: FileSpreadsheet,
      highlight: false,
    },
  ];

  return (
    <section id="modules" className="scroll-mt-20 py-16 sm:py-24 border-t border-[#E5E5E2] bg-white">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto">
          <p className="text-xs font-bold uppercase tracking-widest text-[#F97316]">
            Complete GSTR Coverage
          </p>
          <h2 className="mt-2.5 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
            Built for Every GST Reconciliation Workflow
          </h2>
          <p className="mt-3.5 text-base text-[#6B6B6B] leading-relaxed">
            ReconDesk replaces fragmented spreadsheets with specialized modules for purchase, sales, liability checks, and annual audit certification.
          </p>
        </div>

        {/* 4-Card Module Grid */}
        <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2">
          {modules.map((m) => {
            const Icon = m.icon;
            return (
              <div
                key={m.title}
                className={`relative flex flex-col justify-between rounded-[12px] border p-6 sm:p-8 transition-all duration-200 hover:border-[#6B6B6B]/50 ${
                  m.highlight
                    ? "border-[#E5E5E2] bg-gradient-to-b from-orange-50/20 to-white shadow-xs"
                    : "border-[#E5E5E2] bg-white"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="rounded-full bg-[#F5F5F3] px-3 py-1 text-[11px] font-semibold text-[#0A0A0A]">
                      {m.badge}
                    </span>
                    <div className="flex h-9 w-9 items-center justify-center rounded-[8px] bg-[#0A0A0A] text-white">
                      <Icon className="h-4 w-4" />
                    </div>
                  </div>

                  <h3 className="mt-5 text-xl font-bold text-[#0A0A0A]">
                    {m.title}
                  </h3>
                  <p className="mt-2 text-sm text-[#6B6B6B] leading-relaxed">
                    {m.description}
                  </p>

                  {/* Bullet features */}
                  <ul className="mt-6 space-y-2.5 border-t border-[#E5E5E2] pt-6">
                    {m.features.map((feat) => (
                      <li key={feat} className="flex items-start gap-2.5 text-xs text-[#0A0A0A]">
                        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
                        <span className="font-medium">{feat}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="mt-8 pt-4 border-t border-[#E5E5E2]">
                  <a
                    href="#how-it-works"
                    className="inline-flex items-center gap-1.5 text-xs font-bold text-[#0A0A0A] hover:text-[#F97316] transition-colors"
                  >
                    <span>See reconciliation workflow</span>
                    <ArrowRight className="h-3 w-3" />
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
