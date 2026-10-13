"use client";

import { useMemo } from "react";
import { formatINR, formatInrCompact } from "@/lib/format";
import { calculateNetClaimableItc, NetItcCalculation } from "@/lib/statutoryCompliance";
import {
  TrendingUp,
  AlertTriangle,
  ShieldCheck,
  AlertCircle,
  Lock,
} from "lucide-react";

interface CumulativeItcExposureCardProps {
  kpis: {
    eligible_itc: number;
    reversed_itc: number;
    reclaimed_itc: number;
    on_hold_itc?: number;
    at_risk_itc?: number;
    missed_itc?: number;
  };
  totalRunsCount?: number;
  finalizedRunsCount?: number;
  className?: string;
}

export function CumulativeItcExposureCard({
  kpis,
  totalRunsCount = 1,
  finalizedRunsCount = 0,
  className = "",
}: CumulativeItcExposureCardProps) {
  const calc: NetItcCalculation = useMemo(
    () => calculateNetClaimableItc(kpis),
    [kpis]
  );

  const totalBase = Math.max(
    1,
    calc.netClaimableRupees + calc.reversedRupees + calc.atRiskRupees + (calc.onHoldRupees || 0)
  );
  const claimablePct = Math.min(100, Math.round((calc.netClaimableRupees / totalBase) * 100));
  const reversedPct = Math.min(
    100 - claimablePct,
    Math.round((calc.reversedRupees / totalBase) * 100)
  );
  const atRiskPct = Math.max(
    0,
    Math.min(100 - claimablePct - reversedPct, Math.round((calc.atRiskRupees / totalBase) * 100))
  );

  const getHealthBadgeCls = (rating: NetItcCalculation["healthRating"]) => {
    switch (rating) {
      case "HIGH_RISK":
        return "bg-rose-100 text-rose-800 border-rose-300";
      case "MODERATE_RISK":
        return "bg-amber-100 text-amber-900 border-amber-300";
      default:
        return "bg-emerald-100 text-emerald-800 border-emerald-300";
    }
  };

  return (
    <div
      className={`rounded-2xl border border-gray-200 bg-white p-5 shadow-xs flex flex-col justify-between gap-4 ${className}`}
    >
      {/* 1. Header & Period Lock Status */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-gray-100">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-bold text-gray-900 uppercase tracking-wider">
              Statutory Net ITC Position
            </h3>
            <span
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold ${getHealthBadgeCls(
                calc.healthRating
              )}`}
            >
              {calc.healthRating === "HIGH_RISK" ? (
                <AlertTriangle className="h-3 w-3 shrink-0" />
              ) : calc.healthRating === "MODERATE_RISK" ? (
                <AlertCircle className="h-3 w-3 shrink-0" />
              ) : (
                <ShieldCheck className="h-3 w-3 shrink-0" />
              )}
              <span>{calc.healthLabel}</span>
            </span>
          </div>
          <p className="text-[11px] text-gray-500 mt-0.5">
            Formula: Eligible Table 4A(5) − Reversed 4B + Reclaimed 4D(1)
          </p>
        </div>

        {totalRunsCount > 0 && (
          <div className="flex items-center gap-1.5 text-[11px] font-medium bg-gray-50 border border-gray-200/80 px-2.5 py-1 rounded-lg text-gray-600 shrink-0">
            <Lock className="h-3 w-3 text-gray-400" />
            <span>
              <strong className="text-gray-900">{finalizedRunsCount}</strong> of{" "}
              <strong className="text-gray-900">{totalRunsCount}</strong> periods locked
            </span>
          </div>
        )}
      </div>

      {/* 2. Middle Body: Hero Metric, Table 4 Equation, Allocation Bar */}
      <div className="space-y-4 flex-1 flex flex-col justify-around">
        {/* Hero Card: Net Claimable Credit */}
        <div className="rounded-xl bg-gradient-to-br from-gray-50/90 to-white border border-gray-200/80 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500 block">
                Net Claimable Credit
              </span>
              <div
                className="mt-1 font-mono text-2xl sm:text-3xl font-extrabold text-gray-900 tracking-tight tabular-nums break-words"
                title={formatINR(calc.netClaimableRupees)}
              >
                {formatINR(calc.netClaimableRupees)}
              </div>
            </div>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-2 pt-2 border-t border-gray-100">
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200/80 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-800">
              <TrendingUp className="h-3 w-3 text-emerald-600 shrink-0" />
              <span>Authorized for GSTR-3B Table 4(C)</span>
            </span>
          </div>
        </div>

        {/* Statutory Table 4 Equation Breakdown */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] font-semibold text-gray-600 px-0.5">
            <span className="uppercase tracking-wider">Statutory Equation Breakdown</span>
            <span className="text-[10px] text-gray-400 font-normal">Table 4 Rules</span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {/* 4A(5) Eligible */}
            <div
              className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-2.5 flex flex-col justify-between"
              title={`Table 4A(5) Gross Eligible ITC: ${formatINR(calc.eligibleRupees)}`}
            >
              <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-800 truncate">
                + 4A(5) Eligible
              </span>
              <span className="mt-1 font-mono text-[13px] font-bold text-gray-900 tabular-nums truncate">
                {formatInrCompact(calc.eligibleRupees)}
              </span>
              <span className="text-[10px] text-gray-500 truncate">Gross 2B Credit</span>
            </div>

            {/* 4B Reversals */}
            <div
              className="rounded-xl border border-orange-100 bg-orange-50/40 p-2.5 flex flex-col justify-between"
              title={`Table 4B Reversals: ${formatINR(calc.reversedRupees)}`}
            >
              <span className="text-[10px] font-bold uppercase tracking-wider text-orange-900 truncate">
                − 4(B) Reversed
              </span>
              <span className="mt-1 font-mono text-[13px] font-bold text-gray-900 tabular-nums truncate">
                {formatInrCompact(calc.reversedRupees)}
              </span>
              <span className="text-[10px] text-gray-500 truncate">Sec 17(5) / R37</span>
            </div>

            {/* 4D(1) Reclaimed */}
            <div
              className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-2.5 flex flex-col justify-between"
              title={`Table 4D(1) Reclaimed Credit: ${formatINR(calc.reclaimedRupees)}`}
            >
              <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-900 truncate">
                + 4D(1) Reclaim
              </span>
              <span className="mt-1 font-mono text-[13px] font-bold text-gray-900 tabular-nums truncate">
                {formatInrCompact(calc.reclaimedRupees)}
              </span>
              <span className="text-[10px] text-gray-500 truncate">Cleared Reversals</span>
            </div>
          </div>
        </div>

        {/* Credit Allocation Proportional Bar & Detailed Legend */}
        <div className="space-y-2 rounded-xl border border-gray-100 bg-[#FCFCFD] p-3.5">
          <div className="flex items-center justify-between text-[11px] text-gray-600">
            <span className="font-semibold">Credit Portfolio Allocation</span>
            <span className="font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              {claimablePct}% Net Claimable
            </span>
          </div>
          <div className="h-2.5 w-full rounded-full bg-gray-100 flex overflow-hidden shadow-inner">
            <div
              style={{ width: `${claimablePct}%` }}
              className="h-full bg-emerald-500 transition-all duration-500"
              title={`Net Claimable: ${claimablePct}% (${formatINR(calc.netClaimableRupees)})`}
            />
            <div
              style={{ width: `${reversedPct}%` }}
              className="h-full bg-orange-400 transition-all duration-500"
              title={`Reversals (4B): ${reversedPct}% (${formatINR(calc.reversedRupees)})`}
            />
            <div
              style={{ width: `${atRiskPct}%` }}
              className="h-full bg-rose-500 transition-all duration-500"
              title={`At Risk: ${atRiskPct}% (${formatINR(calc.atRiskRupees)})`}
            />
          </div>

          {/* Legend */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 pt-1 text-[11px] text-gray-600 font-medium">
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
              <span>
                Net Eligible:{" "}
                <strong className="text-gray-900 font-mono">
                  {formatInrCompact(calc.netClaimableRupees)}
                </strong>
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-orange-400 shrink-0" />
              <span>
                Reversals:{" "}
                <strong className="text-gray-900 font-mono">
                  {formatInrCompact(calc.reversedRupees)}
                </strong>
              </span>
            </div>
            {calc.atRiskRupees > 0 && (
              <div className="flex items-center gap-1.5 text-rose-700">
                <span className="h-2 w-2 rounded-full bg-rose-500 shrink-0" />
                <span>
                  At Risk:{" "}
                  <strong className="text-rose-900 font-mono">
                    {formatInrCompact(calc.atRiskRupees)}
                  </strong>
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 3. Statutory Risk Advisory Callout */}
      <div
        className={`rounded-xl border p-3 text-[11.5px] flex items-start gap-2.5 ${
          calc.healthRating === "HIGH_RISK"
            ? "border-rose-200 bg-rose-50/60 text-rose-950"
            : calc.healthRating === "MODERATE_RISK"
            ? "border-amber-200 bg-amber-50/60 text-amber-950"
            : "border-gray-200/80 bg-gray-50/80 text-gray-700"
        }`}
      >
        {calc.healthRating === "HIGH_RISK" ? (
          <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
        ) : calc.healthRating === "MODERATE_RISK" ? (
          <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
        ) : (
          <ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
        )}
        <div className="leading-relaxed space-y-0.5">
          <p className="font-semibold text-gray-900">
            {calc.healthRating === "HIGH_RISK"
              ? "Statutory Compliance Risk Detected"
              : calc.healthRating === "MODERATE_RISK"
              ? "Reconciliation Advisory"
              : "Statutory Position Clean"}
          </p>
          <p className="text-[11px] text-gray-600">{calc.healthDescription}</p>
        </div>
      </div>
    </div>
  );
}
