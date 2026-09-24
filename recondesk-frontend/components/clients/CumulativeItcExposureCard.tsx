"use client";

import { useMemo } from "react";
import { formatINR, formatInrCompact } from "@/lib/format";
import { calculateNetClaimableItc, NetItcCalculation } from "@/lib/statutoryCompliance";
import { TrendingUp, AlertTriangle, ShieldCheck, HelpCircle } from "lucide-react";

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

  const totalBase = Math.max(1, calc.eligibleRupees + calc.onHoldRupees + calc.atRiskRupees);
  const claimablePct = Math.min(100, Math.round((calc.netClaimableRupees / totalBase) * 100));
  const reversedPct = Math.min(100, Math.round((calc.reversedRupees / totalBase) * 100));
  const atRiskPct = Math.min(100, Math.round((calc.atRiskRupees / totalBase) * 100));

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
    <div className={`rounded-2xl border border-gray-200 bg-white p-5 shadow-xs space-y-4 ${className}`}>
      {/* Header */}
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
          <div className="text-[11px] text-gray-500 font-medium">
            <span className="font-semibold text-gray-900">{finalizedRunsCount}</span> of{" "}
            <span className="font-semibold text-gray-900">{totalRunsCount}</span> periods locked
          </div>
        )}
      </div>

      {/* Primary Value Display & Visual Stacked Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 items-center">
        <div className="sm:col-span-5 space-y-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
            Net Claimable Credit
          </span>
          <div className="font-mono text-2xl font-bold text-gray-900 tabular-nums">
            {formatINR(calc.netClaimableRupees)}
          </div>
          <p className="text-[11px] text-emerald-700 font-medium flex items-center gap-1">
            <TrendingUp className="h-3.5 w-3.5" />
            <span>Authorized for GSTR-3B Table 4C</span>
          </p>
        </div>

        <div className="sm:col-span-7 space-y-2">
          {/* Stacked Proportional Bar */}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[11px] text-gray-500">
              <span>Credit Allocation</span>
              <span>{claimablePct}% Net Claimable</span>
            </div>
            <div className="h-2.5 w-full rounded-full bg-gray-100 flex overflow-hidden">
              <div
                style={{ width: `${claimablePct}%` }}
                className="h-full bg-emerald-500 transition-all duration-500"
                title={`Net Claimable: ${claimablePct}%`}
              />
              <div
                style={{ width: `${reversedPct}%` }}
                className="h-full bg-orange-400 transition-all duration-500"
                title={`Reversals (4B): ${reversedPct}%`}
              />
              <div
                style={{ width: `${atRiskPct}%` }}
                className="h-full bg-rose-500 transition-all duration-500"
                title={`At Risk: ${atRiskPct}%`}
              />
            </div>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap items-center gap-3 text-[10.5px] text-gray-500 font-medium">
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span>Net Eligible</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-orange-400" />
              <span>Reversals ({formatInrCompact(calc.reversedRupees)})</span>
            </span>
            {calc.atRiskRupees > 0 && (
              <span className="inline-flex items-center gap-1 text-rose-700">
                <span className="h-2 w-2 rounded-full bg-rose-500" />
                <span>At Risk ({formatInrCompact(calc.atRiskRupees)})</span>
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Advisory Callout */}
      <div className="rounded-xl border border-gray-100 bg-[#FCFCFD] p-3 text-[11.5px] text-gray-600 flex items-start gap-2">
        <HelpCircle className="h-3.5 w-3.5 text-gray-400 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          {calc.healthDescription}
        </p>
      </div>
    </div>
  );
}
