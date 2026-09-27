"use client";

import React, { useState, useRef, MouseEvent, TouchEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Crosshair,
  Eye,
  ShieldAlert,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Info,
  ArrowRight,
} from "lucide-react";
import Link from "next/link";

interface Transaction {
  id: string;
  vendor: string;
  gstin: string;
  booksInv: string;
  portalInv: string;
  taxAmount: string;
  // What the client sees
  clientStatus: string;
  // What GST Dept X-Ray sees
  deptVerdict: "MISMATCH" | "LOCKED_OUT" | "CLEAN";
  deptRisk: string;
  deptNotice: string;
  // What ReconDesk sees
  reconResolution: string;
  reconScore: string;
}

const TRANSACTIONS: Transaction[] = [
  {
    id: "tx-1",
    vendor: "Kalyani Steel & Infra",
    gstin: "27AAACK1234A1Z1",
    booksInv: "INV-842",
    portalInv: "INV/2024-25/0842",
    taxAmount: "₹1,80,000",
    clientStatus: "Recorded in Tally",
    deptVerdict: "MISMATCH",
    deptRisk: "VLOOKUP Fails (Prefix Drift)",
    deptNotice: "Section 73 Demand Notice + 24% Int",
    reconResolution: "L3 Normalized (842 == 842)",
    reconScore: "99.8% Match",
  },
  {
    id: "tx-2",
    vendor: "Apex Packaging LLP",
    gstin: "27ABCCA5678B1Z2",
    booksInv: "APX/902",
    portalInv: "APX/902",
    taxAmount: "₹45,000",
    clientStatus: "Recorded in Tally",
    deptVerdict: "LOCKED_OUT",
    deptRisk: "Supplier Filed GSTR-1 on 15th",
    deptNotice: "Rule 36(4) Ineligible for Current 3B",
    reconResolution: "Tagged for Next Month 2B Auto-Avail",
    reconScore: "100% Timing Tracked",
  },
  {
    id: "tx-3",
    vendor: "Zenith Logistics Hub",
    gstin: "27AABCZ9999C1Z3",
    booksInv: "ZEN-4100",
    portalInv: "ZEN-4100",
    taxAmount: "₹92,500",
    clientStatus: "Recorded in Tally",
    deptVerdict: "CLEAN",
    deptRisk: "Exact Match",
    deptNotice: "Safe to Claim in Table 4(A)(5)",
    reconResolution: "L1 Instant Exact Match",
    reconScore: "100% Validated",
  },
];

export function ForensicAuditLoupe() {
  const [lensMode, setLensMode] = useState<"client" | "dept" | "recondesk">("dept");
  const [hoveredRow, setHoveredRow] = useState<string>("tx-1");
  const [lensPos, setLensPos] = useState({ x: 180, y: 120 });
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setLensPos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };

  const handleTouchMove = (e: TouchEvent<HTMLDivElement>) => {
    if (!containerRef.current || !e.touches[0]) return;
    const rect = containerRef.current.getBoundingClientRect();
    setLensPos({
      x: e.touches[0].clientX - rect.left,
      y: e.touches[0].clientY - rect.top,
    });
  };

  const selectedTx = TRANSACTIONS.find((t) => t.id === hoveredRow) || TRANSACTIONS[0];

  return (
    <div className="my-10 overflow-hidden rounded-2xl border border-[#E5E5E2] bg-white shadow-sm">
      {/* Inspection Mode Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-[#E5E5E2] p-4 sm:p-5 gap-3 bg-[#FAF9F5]">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#7B5CFA] text-white shadow-sm">
            <Crosshair className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-[#0A0A0A]">
                The Forensic Audit Loupe
              </h4>
              <span className="rounded-full bg-purple-100 text-[#7B5CFA] px-2 py-0.2 text-[9px] font-bold border border-purple-200">
                INTERACTIVE X-RAY
              </span>
            </div>
            <p className="text-[11px] text-[#6B6B6B]">
              Hover or move your cursor across the ledger to reveal what the GST Department sees underneath.
            </p>
          </div>
        </div>

        {/* 3 Mode Switchers */}
        <div className="flex rounded-lg bg-white p-1 border border-[#E5E5E2] shadow-xs text-xs font-semibold">
          <button
            type="button"
            onClick={() => setLensMode("client")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-all ${
              lensMode === "client"
                ? "bg-[#0A0A0A] text-white shadow-sm"
                : "text-[#6B6B6B] hover:text-[#0A0A0A]"
            }`}
          >
            <Eye className="h-3 w-3" />
            <span>1. Client Books</span>
          </button>

          <button
            type="button"
            onClick={() => setLensMode("dept")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-all ${
              lensMode === "dept"
                ? "bg-red-600 text-white shadow-sm"
                : "text-[#6B6B6B] hover:text-red-600"
            }`}
          >
            <ShieldAlert className="h-3 w-3" />
            <span>2. Department X-Ray</span>
          </button>

          <button
            type="button"
            onClick={() => setLensMode("recondesk")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-all ${
              lensMode === "recondesk"
                ? "bg-[#7B5CFA] text-white shadow-sm"
                : "text-[#6B6B6B] hover:text-[#7B5CFA]"
            }`}
          >
            <Sparkles className="h-3 w-3" />
            <span>3. ReconDesk Lens</span>
          </button>
        </div>
      </div>

      {/* Forensic Interactive Canvas */}
      <div
        ref={containerRef}
        onMouseMove={handleMouseMove}
        onTouchMove={handleTouchMove}
        className="relative cursor-crosshair select-none p-5 sm:p-7 bg-gradient-to-b from-white to-[#FAF9F5]/40"
      >
        {/* Dynamic Telemetry HUD Banner */}
        <div
          className={`mb-5 flex flex-col sm:flex-row sm:items-center sm:justify-between rounded-xl p-3 text-xs border transition-colors ${
            lensMode === "dept"
              ? "bg-red-50/80 border-red-200 text-red-900"
              : lensMode === "recondesk"
              ? "bg-purple-50/80 border-purple-200 text-purple-900"
              : "bg-gray-50 border-gray-200 text-gray-800"
          }`}
        >
          <div className="flex items-center gap-2 font-mono">
            <span className="font-bold">CURRENT_LENS:</span>
            <span className="uppercase font-extrabold tracking-wide">
              {lensMode === "dept"
                ? "🚨 GSTN Scrutiny Radar (Rule 88D / Section 73)"
                : lensMode === "recondesk"
                ? "⚡ ReconDesk Algorithmic Resolver"
                : "📄 Standard Tally Purchase Register (Raw)"}
            </span>
          </div>
          <div className="mt-1 sm:mt-0 font-mono text-[11px] opacity-75">
            VARIANCE_DETECTED: ₹1,80,000 | ACTIVE_ROW: {selectedTx.booksInv}
          </div>
        </div>

        {/* Ledger Table */}
        <div className="overflow-x-auto rounded-xl border border-[#E5E5E2] bg-white shadow-xs">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#FAF9F5] border-b border-[#E5E5E2] text-[#6B6B6B] font-bold uppercase tracking-wider text-[10px]">
              <tr>
                <th className="px-4 py-3">Vendor / GSTIN</th>
                <th className="px-4 py-3">Books Inv #</th>
                <th className="px-4 py-3">Portal GSTR-2B Inv #</th>
                <th className="px-4 py-3">Tax Value</th>
                <th className="px-4 py-3">
                  {lensMode === "dept"
                    ? "Dept X-Ray Verdict"
                    : lensMode === "recondesk"
                    ? "ReconDesk Resolution"
                    : "Client Perception"}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E5E5E2]">
              {TRANSACTIONS.map((tx) => {
                const isHovered = hoveredRow === tx.id;
                return (
                  <tr
                    key={tx.id}
                    onMouseEnter={() => setHoveredRow(tx.id)}
                    className={`transition-colors cursor-pointer ${
                      isHovered
                        ? lensMode === "dept"
                          ? "bg-red-50/50"
                          : lensMode === "recondesk"
                          ? "bg-purple-50/50"
                          : "bg-[#FAF9F5]"
                        : "hover:bg-gray-50/60"
                    }`}
                  >
                    <td className="px-4 py-3.5">
                      <div className="font-bold text-[#0A0A0A]">{tx.vendor}</div>
                      <div className="font-mono text-[10px] text-[#8C8C8C]">{tx.gstin}</div>
                    </td>

                    <td className="px-4 py-3.5 font-mono font-semibold text-[#0A0A0A]">
                      {tx.booksInv}
                    </td>

                    <td className="px-4 py-3.5 font-mono">
                      {lensMode === "client" ? (
                        <span className="text-gray-400">??? (Manual check required)</span>
                      ) : (
                        <span
                          className={`font-semibold ${
                            tx.booksInv !== tx.portalInv ? "text-amber-600 font-bold" : "text-[#0A0A0A]"
                          }`}
                        >
                          {tx.portalInv}
                        </span>
                      )}
                    </td>

                    <td className="px-4 py-3.5 font-mono font-bold text-[#0A0A0A]">
                      {tx.taxAmount}
                    </td>

                    <td className="px-4 py-3.5">
                      {lensMode === "client" && (
                        <span className="inline-flex items-center gap-1 rounded bg-gray-100 text-gray-700 px-2 py-0.5 text-[11px] font-medium">
                          <CheckCircle2 className="h-3 w-3 text-gray-500" />
                          <span>Recorded in Tally</span>
                        </span>
                      )}

                      {lensMode === "dept" && (
                        <div>
                          {tx.deptVerdict === "MISMATCH" && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 text-red-700 px-2.5 py-0.5 text-[11px] font-bold border border-red-200">
                              <ShieldAlert className="h-3 w-3" />
                              <span>MISMATCH: 0 MATCH IN 2B</span>
                            </span>
                          )}
                          {tx.deptVerdict === "LOCKED_OUT" && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-800 px-2.5 py-0.5 text-[11px] font-bold border border-amber-200">
                              <AlertTriangle className="h-3 w-3" />
                              <span>LOCKED OUT (FILED ON 15TH)</span>
                            </span>
                          )}
                          {tx.deptVerdict === "CLEAN" && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-700 px-2.5 py-0.5 text-[11px] font-bold border border-emerald-200">
                              <CheckCircle2 className="h-3 w-3" />
                              <span>MATCHED IN GSTR-2B</span>
                            </span>
                          )}
                        </div>
                      )}

                      {lensMode === "recondesk" && (
                        <div>
                          {tx.deptVerdict === "MISMATCH" && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-purple-100 text-[#7B5CFA] px-2.5 py-0.5 text-[11px] font-bold border border-purple-200">
                              <Sparkles className="h-3 w-3" />
                              <span>L3 FUZZY MATCHED ({tx.reconScore})</span>
                            </span>
                          )}
                          {tx.deptVerdict === "LOCKED_OUT" && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-700 px-2.5 py-0.5 text-[11px] font-bold border border-blue-200">
                              <Info className="h-3 w-3" />
                              <span>AUTO-SCHEDULED FOR NEXT 3B</span>
                            </span>
                          )}
                          {tx.deptVerdict === "CLEAN" && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-700 px-2.5 py-0.5 text-[11px] font-bold border border-emerald-200">
                              <CheckCircle2 className="h-3 w-3" />
                              <span>L1 VERIFIED &amp; CLAIMABLE</span>
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Detailed Forensic Inspector Breakdown of the Selected Row */}
        <div className="mt-5 rounded-xl border border-[#E5E5E2] bg-white p-4 sm:p-5 shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-3 border-b border-[#E5E5E2] gap-2">
            <div className="text-xs font-bold text-[#0A0A0A] flex items-center gap-2">
              <span className="flex h-2 w-2 rounded-full bg-[#7B5CFA]" />
              <span>Inspection Target: {selectedTx.vendor} ({selectedTx.booksInv})</span>
            </div>
            <span className="font-mono text-xs font-bold text-[#7B5CFA]">
              At-Risk Value: {selectedTx.taxAmount}
            </span>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 text-xs">
            <div className="space-y-1 rounded-lg bg-[#FAF9F5] p-3 border border-[#E5E5E2]">
              <span className="text-[#8C8C8C] text-[10px] uppercase font-bold block">
                {lensMode === "dept" ? "Department Scrutiny Radar" : "ReconDesk Forensic Engine"}
              </span>
              <p className="font-semibold text-[#0A0A0A]">
                {lensMode === "dept" ? selectedTx.deptRisk : selectedTx.reconResolution}
              </p>
            </div>

            <div
              className={`space-y-1 rounded-lg p-3 border ${
                lensMode === "dept"
                  ? "bg-red-50/60 border-red-200 text-red-900"
                  : "bg-purple-50/60 border-purple-200 text-purple-900"
              }`}
            >
              <span className="text-[10px] uppercase font-bold block opacity-75">
                {lensMode === "dept" ? "Statutory Penalty / Consequence" : "Outcome for Client"}
              </span>
              <p className="font-bold">
                {lensMode === "dept"
                  ? selectedTx.deptNotice
                  : `100% Tax Credit Secured (${selectedTx.taxAmount})`}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Conversion Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-t border-[#E5E5E2] bg-[#FAF9F5] px-5 py-3.5 text-xs text-[#6B6B6B] gap-3">
        <span>
          Don&apos;t wait for GST notices to expose mismatches. Run ReconDesk&apos;s forensic match on your client files in 60 seconds.
        </span>
        <Link
          href="/auth/signup"
          className="inline-flex shrink-0 items-center gap-1.5 font-bold text-[#7B5CFA] hover:text-[#6C4DE6] transition-colors"
        >
          <span>Try 2 GSTINs Free</span>
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}
