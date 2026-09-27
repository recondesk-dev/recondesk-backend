"use client";

import React, { useState } from "react";
import { AlertOctagon, ArrowRight, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";

export function CaCatchRadar() {
  const [booksItc, setBooksItc] = useState<number>(1240000);
  const [portal2bItc, setPortal2bItc] = useState<number>(1060000);

  const variance = Math.max(0, booksItc - portal2bItc);
  const annualInterest = variance * 0.24; // 24% per annum under Section 50(3)
  const penalty100 = variance; // up to 100% penalty under Section 74

  const formatRupees = (amt: number) =>
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amt);

  return (
    <div className="my-8 overflow-hidden rounded-2xl border border-red-200 bg-gradient-to-b from-red-50/40 via-white to-white p-5 sm:p-7 shadow-sm">
      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-red-600">
        <AlertOctagon className="h-4 w-4" />
        <span>CA Catch 🎯 • Department Scrutiny Simulator</span>
      </div>

      <h3 className="mt-2 text-lg sm:text-xl font-bold text-[#0A0A0A]">
        What the GST Officer Sees When You Claim Based on Books
      </h3>
      <p className="mt-1 text-xs text-[#6B6B6B]">
        Most CAs claim ITC based on their Tally purchase register rather than GSTR-2B. Watch how the department portal flags the mismatch automatically.
      </p>

      {/* Simulator Inputs & Result */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="rounded-xl border border-[#E5E5E2] bg-white p-4">
            <div className="flex justify-between text-xs font-semibold text-[#0A0A0A]">
              <span>ITC in Client Purchase Register (Books)</span>
              <span className="font-mono text-[#7B5CFA]">{formatRupees(booksItc)}</span>
            </div>
            <input
              type="range"
              min={500000}
              max={2500000}
              step={20000}
              value={booksItc}
              onChange={(e) => setBooksItc(Number(e.target.value))}
              className="mt-2 h-2 w-full cursor-pointer appearance-none rounded-lg bg-[#E5E5E2] accent-[#7B5CFA]"
            />
          </div>

          <div className="rounded-xl border border-[#E5E5E2] bg-white p-4">
            <div className="flex justify-between text-xs font-semibold text-[#0A0A0A]">
              <span>ITC Reflected in GSTR-2B (Portal Snapshot)</span>
              <span className="font-mono text-emerald-700">{formatRupees(portal2bItc)}</span>
            </div>
            <input
              type="range"
              min={500000}
              max={2500000}
              step={20000}
              value={portal2bItc}
              onChange={(e) => setPortal2bItc(Number(e.target.value))}
              className="mt-2 h-2 w-full cursor-pointer appearance-none rounded-lg bg-[#E5E5E2] accent-emerald-600"
            />
          </div>
        </div>

        {/* Notice Demand Result Card */}
        <div className="rounded-xl border border-red-200 bg-red-950 p-5 text-white flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs text-red-300 font-mono pb-2 border-b border-red-800">
              <span className="flex items-center gap-1.5">
                <ShieldAlert className="h-4 w-4 text-red-400" />
                <span>FORM GST DRC-01B NOTICE PREVIEW</span>
              </span>
              <span>RULE 88D</span>
            </div>

            <div className="mt-4 space-y-2">
              <div className="flex justify-between text-xs text-red-200/80">
                <span>Excess ITC Availed:</span>
                <span className="font-mono font-bold text-red-300 text-sm">
                  {formatRupees(variance)}
                </span>
              </div>
              <div className="flex justify-between text-xs text-red-200/80">
                <span>Mandatory Interest @ 24% p.a. (Sec 50):</span>
                <span className="font-mono text-white text-xs">{formatRupees(annualInterest)}</span>
              </div>
              <div className="flex justify-between text-xs text-red-200/80">
                <span>Potential Penalty (Sec 73/74):</span>
                <span className="font-mono text-white text-xs">Up to {formatRupees(penalty100)}</span>
              </div>
            </div>

            <div className="mt-4 rounded-lg bg-red-900/60 p-2.5 text-[11px] text-red-200 border border-red-800">
              ⚠️ <strong>Statutory Risk:</strong> If variance exceeds ₹25 Lakhs or 20%, GSTN automatically disables Part A of GSTR-1 for the subsequent tax period until paid or explained.
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-red-800">
            <Link
              href="/auth/signup"
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-2 text-xs font-bold text-red-950 shadow-sm hover:bg-red-50 transition"
            >
              <Sparkles className="h-3.5 w-3.5 text-[#7B5CFA]" />
              <span>Prevent DRC-01B Notices With ReconDesk</span>
              <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
