"use client";

import Link from "next/link";
import { FileText, Layers, FileCheck, RefreshCcw, Calculator, ArrowRight } from "lucide-react";

const FILING_MODULES = [
  {
    title: "Form GSTR-4 & CMP-08 (Composition)",
    href: "/filing/gstr-4",
    badge: "Composition Taxpayer",
    badgeColor: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
    desc: "Annual Return & quarterly CMP-08 for Section 10 Composition Scheme & Notification 2/2019. Rate-wise calculation, CMP-08 reconciliation, CA audit cell overrides, and GSTN portal JSON export.",
    icon: Calculator,
    actionText: "Open GSTR-4 Workbench",
  },
  {
    title: "Form GSTR-1 (Outward Supplies)",
    href: "/filing/gstr-1",
    badge: "Monthly / Quarterly",
    badgeColor: "bg-blue-500/10 text-blue-600 border-blue-500/20",
    desc: "Sales Register to GSTR-1 preparation, B2B, B2C, Amendments, HSN summary, and automated tie-out with GSTR-3B.",
    icon: FileText,
    actionText: "File GSTR-1",
  },
  {
    title: "Form GSTR-3B (Summary Return)",
    href: "/filing/gstr-3b",
    badge: "Monthly / Quarterly",
    badgeColor: "bg-purple-500/10 text-purple-600 border-purple-500/20",
    desc: "Tax liability offset, ITC eligibility verification, RCM calculations, and secure filing workflow.",
    icon: FileCheck,
    actionText: "File GSTR-3B",
  },
  {
    title: "Bulk Multi-Period Filing Batches",
    href: "/filing/batches",
    badge: "Batch Processing",
    badgeColor: "bg-amber-500/10 text-amber-600 border-amber-500/20",
    desc: "Multi-client & multi-period automated batch filing and verification runner.",
    icon: Layers,
    actionText: "View Filing Batches",
  },
];

export default function FilingIndexPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-8 px-6 py-10">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-[var(--ink)]">
          GST Filing & Compliance Center
        </h1>
        <p className="mt-2 text-sm text-gray-500 max-w-2xl">
          Select a return type below to prepare, reconcile, edit CA audit overrides, and generate official GSTN portal JSON payloads.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {FILING_MODULES.map((mod) => {
          const Icon = mod.icon;
          return (
            <div
              key={mod.href}
              className="flex flex-col justify-between rounded-2xl bg-white border border-gray-200/80 p-6 shadow-sm hover:shadow-md transition"
            >
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="p-3 bg-gray-100 rounded-xl text-gray-800">
                    <Icon size={22} />
                  </div>
                  <span className={`px-3 py-1 text-xs font-semibold rounded-full border ${mod.badgeColor}`}>
                    {mod.badge}
                  </span>
                </div>
                <div>
                  <h2 className="text-lg font-bold text-gray-900">{mod.title}</h2>
                  <p className="mt-1.5 text-xs text-gray-500 leading-relaxed">{mod.desc}</p>
                </div>
              </div>

              <div className="pt-6 mt-4 border-t border-gray-100">
                <Link
                  href={mod.href}
                  className="inline-flex items-center gap-2 text-xs font-bold text-brand hover:underline"
                >
                  {mod.actionText}
                  <ArrowRight size={14} />
                </Link>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
