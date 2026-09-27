"use client";

import React, { useState } from "react";
import { Calculator, ArrowRight, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";

export function ItcLossCalculator() {
  const [monthlyTurnoverLakhs, setMonthlyTurnoverLakhs] = useState<number>(50);
  const [averageItcRate, setAverageItcRate] = useState<number>(18);
  const [unmatchedPercent, setUnmatchedPercent] = useState<number>(7.5);

  // Calculations:
  // Estimated monthly purchase ~ 60% of turnover
  const estimatedMonthlyPurchases = monthlyTurnoverLakhs * 0.6;
  const monthlyItc = estimatedMonthlyPurchases * (averageItcRate / 100);
  const monthlyItcAtRisk = monthlyItc * (unmatchedPercent / 100);
  const annualItcAtRisk = monthlyItcAtRisk * 12;

  const formatLakhsOrThousands = (lakhs: number) => {
    const rawRupees = lakhs * 100000;
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(rawRupees);
  };

  return (
    <div className="my-8 overflow-hidden rounded-2xl border border-[#E5E5E2] bg-gradient-to-b from-[#FAF9F5] to-white p-6 shadow-sm sm:p-8">
      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[#7B5CFA]">
        <Calculator className="h-4 w-4" />
        <span>Interactive Estimator</span>
      </div>

      <h3 className="mt-2 text-xl font-bold text-[#0A0A0A] sm:text-2xl">
        Estimate Your Client&apos;s Annual ITC at Risk
      </h3>
      <p className="mt-1 text-xs text-[#6B6B6B] sm:text-sm">
        Adjust the sliders below to see how minor vendor filing delays can compound into massive ITC disallowances under Section 16(4).
      </p>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Sliders */}
        <div className="space-y-5">
          <div>
            <div className="flex justify-between text-xs font-medium text-[#0A0A0A]">
              <span>Monthly B2B Turnover</span>
              <span className="font-bold text-[#7B5CFA]">₹{monthlyTurnoverLakhs} Lakhs</span>
            </div>
            <input
              type="range"
              min={5}
              max={500}
              step={5}
              value={monthlyTurnoverLakhs}
              onChange={(e) => setMonthlyTurnoverLakhs(Number(e.target.value))}
              className="mt-2 h-2 w-full cursor-pointer appearance-none rounded-lg bg-[#E5E5E2] accent-[#7B5CFA]"
            />
            <div className="flex justify-between text-[10px] text-[#8C8C8C]">
              <span>₹5 L</span>
              <span>₹250 L</span>
              <span>₹500 L</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between text-xs font-medium text-[#0A0A0A]">
              <span>Estimated Unreconciled / Delayed Invoices</span>
              <span className="font-bold text-amber-600">{unmatchedPercent}%</span>
            </div>
            <input
              type="range"
              min={1}
              max={25}
              step={0.5}
              value={unmatchedPercent}
              onChange={(e) => setUnmatchedPercent(Number(e.target.value))}
              className="mt-2 h-2 w-full cursor-pointer appearance-none rounded-lg bg-[#E5E5E2] accent-amber-500"
            />
            <div className="flex justify-between text-[10px] text-[#8C8C8C]">
              <span>1% (Minimal)</span>
              <span>7.5% (Average)</span>
              <span>25% (High risk)</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between text-xs font-medium text-[#0A0A0A]">
              <span>Blended GST Rate</span>
              <span className="font-bold text-[#0A0A0A]">{averageItcRate}%</span>
            </div>
            <div className="mt-2 flex gap-2">
              {[5, 12, 18, 28].map((rate) => (
                <button
                  key={rate}
                  type="button"
                  onClick={() => setAverageItcRate(rate)}
                  className={`flex-1 rounded-md py-1.5 text-xs font-semibold transition-all ${
                    averageItcRate === rate
                      ? "bg-[#7B5CFA] text-white shadow-sm"
                      : "border border-[#E5E5E2] bg-white text-[#6B6B6B] hover:border-[#7B5CFA]/50"
                  }`}
                >
                  {rate}%
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Results Card */}
        <div className="flex flex-col justify-between rounded-xl border border-purple-100 bg-purple-50/40 p-5 sm:p-6">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold text-purple-700">
              <ShieldAlert className="h-4 w-4" />
              <span>Compounded Annual Leakage</span>
            </div>

            <div className="mt-3">
              <div className="text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
                {formatLakhsOrThousands(annualItcAtRisk)}
              </div>
              <p className="mt-1 text-xs text-[#6B6B6B]">
                Potential lost or notice-prone credit per year ({formatLakhsOrThousands(monthlyItcAtRisk)} / month)
              </p>
            </div>

            <div className="mt-4 space-y-2 rounded-lg border border-purple-200/60 bg-white/80 p-3 text-xs">
              <div className="flex justify-between text-[#6B6B6B]">
                <span>Est. Monthly Purchases:</span>
                <span className="font-semibold text-[#0A0A0A]">₹{estimatedMonthlyPurchases.toFixed(1)} L</span>
              </div>
              <div className="flex justify-between text-[#6B6B6B]">
                <span>Total Monthly ITC pool:</span>
                <span className="font-semibold text-[#0A0A0A]">₹{monthlyItc.toFixed(2)} L</span>
              </div>
            </div>
          </div>

          <div className="mt-5 border-t border-purple-200/60 pt-4">
            <Link
              href="/auth/signup"
              className="group flex w-full items-center justify-center gap-2 rounded-lg bg-[#7B5CFA] px-4 py-2.5 text-xs font-bold text-white transition hover:bg-[#6C4DE6] shadow-sm"
            >
              <Sparkles className="h-4 w-4" />
              <span>Recover Missed ITC With ReconDesk Free</span>
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
