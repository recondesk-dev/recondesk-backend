"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Sparkles,
  UploadCloud,
  Scale,
  Layers,
  FileSpreadsheet,
  AlertTriangle,
  Copy,
  Check,
  ExternalLink,
} from "lucide-react";

interface CommandCenterQuickActionsProps {
  clientId: string;
  clientGstin: string;
  runId?: string | null;
  className?: string;
}

export function CommandCenterQuickActions({
  clientId,
  clientGstin,
  runId,
  className = "",
}: CommandCenterQuickActionsProps) {
  const [copied, setCopied] = useState(false);

  const handleCopyGstin = async () => {
    try {
      await navigator.clipboard.writeText(clientGstin);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  return (
    <div className={`rounded-2xl border border-gray-200 bg-white p-4 shadow-xs ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3 pb-3 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-gray-900 uppercase tracking-wider">
            CA Quick Actions
          </span>
          <span className="text-[11px] text-gray-500">
            · Common statutory and operational workflows for this client
          </span>
        </div>

        {/* GSTIN Quick Copy Pill */}
        <button
          type="button"
          onClick={handleCopyGstin}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-mono font-medium text-gray-700 hover:bg-gray-100 transition-colors"
          title="Click to copy GSTIN"
        >
          <span>{clientGstin}</span>
          {copied ? (
            <span className="inline-flex items-center gap-0.5 text-emerald-600 font-sans font-semibold">
              <Check className="h-3.5 w-3.5" /> Copied
            </span>
          ) : (
            <Copy className="h-3 w-3 text-gray-400" />
          )}
        </button>
      </div>

      {/* Grid of Action Buttons */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {/* 1. New Reconciliation Wizard */}
        <Link
          href={`/reconcile/${clientId}/new`}
          className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-black hover:bg-black hover:text-white transition-all shadow-xs"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100 text-emerald-800 group-hover:bg-white/20 group-hover:text-white transition-colors mb-1.5">
            <Sparkles className="h-4 w-4" />
          </div>
          <span className="text-xs font-bold leading-tight">New Recon Run</span>
          <span className="text-[10px] text-gray-500 group-hover:text-gray-300 mt-0.5">
            Smart 2B ↔ PR
          </span>
        </Link>

        {/* 2. Request Documents / Upload Link */}
        <Link
          href={`/clients/${clientId}/communication`}
          className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-gray-400 hover:bg-gray-50 transition-all shadow-xs"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 text-blue-800 group-hover:bg-blue-200 transition-colors mb-1.5">
            <UploadCloud className="h-4 w-4" />
          </div>
          <span className="text-xs font-semibold text-gray-900 leading-tight">Request Files</span>
          <span className="text-[10px] text-gray-500 mt-0.5">
            Branded upload link
          </span>
        </Link>

        {/* 3. Reversal & Reclaim Ledger (Rule 37) */}
        <Link
          href={`/clients/${clientId}/reversal-ledger`}
          className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-gray-400 hover:bg-gray-50 transition-all shadow-xs"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-100 text-orange-800 group-hover:bg-orange-200 transition-colors mb-1.5">
            <Scale className="h-4 w-4" />
          </div>
          <span className="text-xs font-semibold text-gray-900 leading-tight">Reversal Ledger</span>
          <span className="text-[10px] text-gray-500 mt-0.5">
            Rule 37 / 37A dues
          </span>
        </Link>

        {/* 4. Multi-Period Batch Analysis */}
        <Link
          href={`/clients/${clientId}/multi-period`}
          className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-gray-400 hover:bg-gray-50 transition-all shadow-xs"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100 text-indigo-800 group-hover:bg-indigo-200 transition-colors mb-1.5">
            <Layers className="h-4 w-4" />
          </div>
          <span className="text-xs font-semibold text-gray-900 leading-tight">Multi-Period</span>
          <span className="text-[10px] text-gray-500 mt-0.5">
            Quarterly / FY batch
          </span>
        </Link>

        {/* 5. Table 4 Statutory Workpaper */}
        {runId ? (
          <Link
            href={`/reconcile/runs/${runId}/gstr3b`}
            className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-gray-400 hover:bg-gray-50 transition-all shadow-xs"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100 text-emerald-800 group-hover:bg-emerald-200 transition-colors mb-1.5">
              <FileSpreadsheet className="h-4 w-4" />
            </div>
            <span className="text-xs font-semibold text-gray-900 leading-tight">Table 4 Paper</span>
            <span className="text-[10px] text-gray-500 mt-0.5">
              GSTR-3B workpaper
            </span>
          </Link>
        ) : (
          <Link
            href="/filing/gstr-3b"
            className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-gray-400 hover:bg-gray-50 transition-all shadow-xs"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-100 text-gray-700 group-hover:bg-gray-200 transition-colors mb-1.5">
              <FileSpreadsheet className="h-4 w-4" />
            </div>
            <span className="text-xs font-semibold text-gray-900 leading-tight">Filing Desk</span>
            <span className="text-[10px] text-gray-500 mt-0.5">
              GSTR-3B filings
            </span>
          </Link>
        )}

        {/* 6. Top Suppliers at Risk */}
        {runId ? (
          <Link
            href={`/reconcile/runs/${runId}/vendors`}
            className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-gray-400 hover:bg-gray-50 transition-all shadow-xs"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-100 text-rose-800 group-hover:bg-rose-200 transition-colors mb-1.5">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <span className="text-xs font-semibold text-gray-900 leading-tight">Risk Suppliers</span>
            <span className="text-[10px] text-gray-500 mt-0.5">
              Missing 2B vendors
            </span>
          </Link>
        ) : (
          <Link
            href="/vendors"
            className="group flex flex-col items-center justify-center text-center p-3 rounded-xl border border-gray-200 bg-[#FCFCFD] hover:border-gray-400 hover:bg-gray-50 transition-all shadow-xs"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-100 text-gray-700 group-hover:bg-gray-200 transition-colors mb-1.5">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <span className="text-xs font-semibold text-gray-900 leading-tight">Vendor Scorecard</span>
            <span className="text-[10px] text-gray-500 mt-0.5">
              Compliance roster
            </span>
          </Link>
        )}
      </div>
    </div>
  );
}
