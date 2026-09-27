"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { Lock, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";

export function Gstr2aVs2bCard() {
  const [activeTab, setActiveTab] = useState<"2b" | "2a">("2b");

  return (
    <div className="my-8 overflow-hidden rounded-2xl border border-[#E5E5E2] bg-white p-5 sm:p-7 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-5 border-b border-[#E5E5E2] gap-3">
        <div>
          <span className="text-xs font-bold uppercase tracking-wider text-[#7B5CFA]">
            Interactive Comparison
          </span>
          <h4 className="text-lg font-bold text-[#0A0A0A] sm:text-xl">
            GSTR-2A vs GSTR-2B: What Makes Them Fundamentally Different
          </h4>
        </div>

        {/* Tab Toggle */}
        <div className="flex rounded-lg bg-[#FAF9F5] p-1 border border-[#E5E5E2]">
          <button
            type="button"
            onClick={() => setActiveTab("2b")}
            className={`rounded-md px-3.5 py-1.5 text-xs font-bold transition-all ${
              activeTab === "2b"
                ? "bg-[#7B5CFA] text-white shadow-sm"
                : "text-[#6B6B6B] hover:text-[#0A0A0A]"
            }`}
          >
            GSTR-2B (The Vault)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("2a")}
            className={`rounded-md px-3.5 py-1.5 text-xs font-bold transition-all ${
              activeTab === "2a"
                ? "bg-[#0A0A0A] text-white shadow-sm"
                : "text-[#6B6B6B] hover:text-[#0A0A0A]"
            }`}
          >
            GSTR-2A (Dynamic Sand)
          </button>
        </div>
      </div>

      {/* Visual Canvas */}
      <div className="mt-6">
        {activeTab === "2b" ? (
          <motion.div
            key="2b"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-5 sm:p-6"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-600 text-white shadow-sm">
                  <Lock className="h-4 w-4" />
                </div>
                <div>
                  <h5 className="font-bold text-[#0A0A0A]">GSTR-2B: Static &amp; Legally Binding</h5>
                  <p className="text-xs text-[#6B6B6B]">The true foundation for GSTR-3B ITC claims</p>
                </div>
              </div>
              <span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-800 px-2.5 py-0.5 text-[11px] font-bold border border-emerald-200">
                <ShieldCheck className="h-3.5 w-3.5" />
                <span>Legally Compliant</span>
              </span>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3 text-xs">
              <div className="rounded-lg bg-white p-3 border border-emerald-200/80">
                <span className="text-[#8C8C8C] block text-[10px] uppercase font-bold">Nature</span>
                <span className="font-bold text-[#0A0A0A] text-sm">Static Snapshot</span>
                <p className="text-[11px] text-[#6B6B6B] mt-0.5">Does not change once generated on the 14th.</p>
              </div>
              <div className="rounded-lg bg-white p-3 border border-emerald-200/80">
                <span className="text-[#8C8C8C] block text-[10px] uppercase font-bold">Generated On</span>
                <span className="font-bold text-[#0A0A0A] text-sm">14th of Every Month</span>
                <p className="text-[11px] text-[#6B6B6B] mt-0.5">Captures all supplier filings up to 11th/13th cut-off.</p>
              </div>
              <div className="rounded-lg bg-white p-3 border border-emerald-200/80">
                <span className="text-[#8C8C8C] block text-[10px] uppercase font-bold">Legal Status</span>
                <span className="font-bold text-emerald-700 text-sm">Rule 36(4) Mandatory</span>
                <p className="text-[11px] text-[#6B6B6B] mt-0.5">The only statement recognized by GST audit officers.</p>
              </div>
            </div>

            <div className="mt-4 rounded-lg bg-white/80 p-3 text-xs text-emerald-900 border border-emerald-200/60 font-medium">
              💡 <strong>Bottom Line:</strong> Use GSTR-2B to file your return. If it is not in 2B, claiming it in 3B triggers an automated Section 73 notice.
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="2a"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className="rounded-xl border border-amber-200 bg-amber-50/40 p-5 sm:p-6"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-600 text-white shadow-sm">
                  <RefreshCw className="h-4 w-4" />
                </div>
                <div>
                  <h5 className="font-bold text-[#0A0A0A]">GSTR-2A: Dynamic &amp; Shifting</h5>
                  <p className="text-xs text-[#6B6B6B]">Good for tracking, dangerous for filing</p>
                </div>
              </div>
              <span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-800 px-2.5 py-0.5 text-[11px] font-bold border border-amber-200">
                <ShieldAlert className="h-3.5 w-3.5" />
                <span>Not for Claiming</span>
              </span>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3 text-xs">
              <div className="rounded-lg bg-white p-3 border border-amber-200/80">
                <span className="text-[#8C8C8C] block text-[10px] uppercase font-bold">Nature</span>
                <span className="font-bold text-[#0A0A0A] text-sm">Dynamic &amp; Real-time</span>
                <p className="text-[11px] text-[#6B6B6B] mt-0.5">Rows appear and disappear whenever vendors file or amend.</p>
              </div>
              <div className="rounded-lg bg-white p-3 border border-amber-200/80">
                <span className="text-[#8C8C8C] block text-[10px] uppercase font-bold">Updates</span>
                <span className="font-bold text-[#0A0A0A] text-sm">Continuous</span>
                <p className="text-[11px] text-[#6B6B6B] mt-0.5">Can change even months after the tax period has passed.</p>
              </div>
              <div className="rounded-lg bg-white p-3 border border-amber-200/80">
                <span className="text-[#8C8C8C] block text-[10px] uppercase font-bold">Legal Status</span>
                <span className="font-bold text-amber-700 text-sm">Unreliable for 3B</span>
                <p className="text-[11px] text-[#6B6B6B] mt-0.5">Departed law no longer allows claiming ITC on 2A.</p>
              </div>
            </div>

            <div className="mt-4 rounded-lg bg-white/80 p-3 text-xs text-amber-900 border border-amber-200/60 font-medium">
              ⚠️ <strong>Warning:</strong> Claiming ITC based on GSTR-2A numbers will cause massive variances in Table 4 of GSTR-3B. Always base claims on GSTR-2B.
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}
