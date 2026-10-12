"use client";

import Link from "next/link";
import { FileText, Layers, FileCheck, RefreshCcw, Calculator, ArrowRight, Receipt, ShoppingCart, Building2, Plane, Globe } from "lucide-react";

const FILING_MODULES = [
  {
    title: "Form GSTR-6 (ISD under Section 20)",
    href: "/filing/gstr-6",
    badge: "Input Service Distributor",
    badgeColor: "bg-indigo-500/10 text-indigo-600 border-indigo-500/20",
    desc: "Input Service Distributor credit pooling & distribution under Rule 39. Proportionate turnover allocation, cross-state CGST/SGST to IGST conversion, and downstream flow to recipient GSTR-2B Table 4(A)(4).",
    icon: Building2,
    actionText: "Open GSTR-6 Workbench",
  },
  {
    title: "Form GSTR-5 (Non-Resident Taxable Persons)",
    href: "/filing/gstr-5",
    badge: "NRTP under Section 27",
    badgeColor: "bg-blue-500/10 text-blue-600 border-blue-500/20",
    desc: "Periodic return for non-resident taxable persons. Bill of Entry import ITC-only restriction under Section 17(5), advance tax deposit sufficiency, 90-day registration validity tracking, and amended 13th due date.",
    icon: Plane,
    actionText: "Open GSTR-5 Workbench",
  },
  {
    title: "Form GSTR-5A (OIDAR Overseas Supplies)",
    href: "/filing/gstr-5a",
    badge: "OIDAR under Section 14 IGST",
    badgeColor: "bg-violet-500/10 text-violet-600 border-violet-500/20",
    desc: "Cross-border digital services supplied to non-taxable online recipients in India. State-wise B2C outward turnover at uniform 18% IGST, zero domestic ITC invariant, and GSTN offline JSON generation.",
    icon: Globe,
    actionText: "Open GSTR-5A Workbench",
  },
  {
    title: "Form GSTR-7 (TDS under Section 51)",
    href: "/filing/gstr-7",
    badge: "Government / PSU Deductor",
    badgeColor: "bg-indigo-500/10 text-indigo-600 border-indigo-500/20",
    desc: "Tax Deducted at Source for notified government entities and PSUs. Contract-level threshold validation (> ₹2.5L), Section 51(1) Proviso checks, Table 3/4 reconciliation, and GSTN offline JSON.",
    icon: Receipt,
    actionText: "Open GSTR-7 Workbench",
  },
  {
    title: "Form GSTR-8 (TCS under Section 52)",
    href: "/filing/gstr-8",
    badge: "E-Commerce Operator",
    badgeColor: "bg-purple-500/10 text-purple-600 border-purple-500/20",
    desc: "Tax Collected at Source for e-commerce platforms. Supplier-wise gross and returned supply reconciliation, net taxable turnover calculation, reduced 0.5% rate verification, and GSTN offline JSON.",
    icon: ShoppingCart,
    actionText: "Open GSTR-8 Workbench",
  },
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
