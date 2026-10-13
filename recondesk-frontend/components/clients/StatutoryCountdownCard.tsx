"use client";

import { useEffect, useState } from "react";
import { Clock, Calendar, AlertTriangle, ShieldCheck, CheckCircle2, AlertCircle } from "lucide-react";
import {
  calculateStatutoryDeadlines,
  evaluatePeriodCompliance,
  StatutoryDeadlineItem,
  ComplianceCycleStatus,
  PeriodComplianceStatus,
} from "@/lib/statutoryCompliance";

interface StatutoryCountdownCardProps {
  selectedPeriod?: string | null;
  isLocked?: boolean;
  finalizedAt?: string | null;
  className?: string;
}

export function StatutoryCountdownCard({
  selectedPeriod,
  isLocked = false,
  finalizedAt,
  className = "",
}: StatutoryCountdownCardProps) {
  const [cycleData, setCycleData] = useState<ComplianceCycleStatus>(() =>
    calculateStatutoryDeadlines()
  );

  // Live timer tick every 60 seconds
  useEffect(() => {
    const timer = setInterval(() => {
      setCycleData(calculateStatutoryDeadlines());
    }, 60000);
    return () => clearInterval(timer);
  }, []);

  const periodCompliance: PeriodComplianceStatus | null = selectedPeriod
    ? evaluatePeriodCompliance(selectedPeriod, isLocked, finalizedAt)
    : null;

  const getUrgencyBadgeCls = (urgency: StatutoryDeadlineItem["urgency"]) => {
    switch (urgency) {
      case "critical":
        return "bg-rose-100 text-rose-800 border-rose-200 animate-pulse";
      case "warning":
        return "bg-amber-100 text-amber-900 border-amber-200";
      case "approaching":
        return "bg-blue-100 text-blue-800 border-blue-200";
      default:
        return "bg-emerald-100 text-emerald-800 border-emerald-200";
    }
  };

  const getPhaseAccentCls = (accent: ComplianceCycleStatus["accentColor"]) => {
    switch (accent) {
      case "rose":
        return "border-rose-200 bg-rose-50/50 text-rose-950";
      case "amber":
        return "border-amber-200 bg-amber-50/50 text-amber-950";
      case "indigo":
        return "border-indigo-200 bg-indigo-50/40 text-indigo-950";
      default:
        return "border-emerald-200 bg-emerald-50/50 text-emerald-950";
    }
  };

  return (
    <div className={`rounded-2xl border border-gray-200 bg-white p-5 shadow-xs flex flex-col justify-between gap-4 ${className}`}>
      {/* Top Banner: Cycle Phase & Selected Period Status */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gray-100 text-gray-800">
            <Clock className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-gray-900 uppercase tracking-wider">
                Statutory GST Timelines
              </span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-semibold text-gray-600">
                IST (UTC+05:30)
              </span>
            </div>
            <p className="text-[11px] text-gray-500">
              Active cycle: {cycleData.currentISTTimeFormatted}
            </p>
          </div>
        </div>

        {/* Selected Period Status Pill */}
        {periodCompliance && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-gray-500">Period {periodCompliance.period}:</span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${periodCompliance.statusBadgeCls}`}
            >
              {periodCompliance.isLocked ? (
                <CheckCircle2 className="h-3 w-3 shrink-0" />
              ) : periodCompliance.status === "OVERDUE" ? (
                <AlertCircle className="h-3 w-3 shrink-0" />
              ) : (
                <Clock className="h-3 w-3 shrink-0" />
              )}
              <span>{periodCompliance.statusLabel}</span>
            </span>
          </div>
        )}
      </div>

      {/* Cycle Phase Highlight Callout */}
      <div className={`rounded-xl border p-3.5 text-xs ${getPhaseAccentCls(cycleData.accentColor)}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="font-bold tracking-tight text-[13px]">{cycleData.phaseTitle}</span>
          <span className="text-[10.5px] uppercase font-bold tracking-wider opacity-75">
            Day {cycleData.currentDayOfMonth} of Month
          </span>
        </div>
        <p className="mt-1 text-gray-700 leading-relaxed text-[11.5px]">{cycleData.phaseSubtitle}</p>
        <p className="mt-1.5 font-medium text-[11.5px] opacity-90">
          💡 <strong>Action:</strong> {cycleData.recommendedAction}
        </p>
      </div>

      {/* 3 Deadline Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {cycleData.deadlines.map((item) => (
          <div
            key={item.kind}
            className="rounded-xl border border-gray-200 bg-[#FCFCFD] p-3.5 flex flex-col justify-between hover:border-gray-300 transition-colors"
          >
            <div>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h4 className="font-semibold text-gray-900 text-xs">{item.title}</h4>
                  <p className="text-[11px] text-gray-500 flex items-center gap-1 mt-0.5">
                    <Calendar className="h-3 w-3 text-gray-400" />
                    <span>Due: <strong>{item.targetDateFormatted}</strong></span>
                  </p>
                </div>
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold ${getUrgencyBadgeCls(
                    item.urgency
                  )}`}
                >
                  {item.urgencyLabel}
                </span>
              </div>

              <p className="mt-2 text-[11px] text-gray-600 line-clamp-2">{item.description}</p>
            </div>

            <div className="mt-3 pt-2.5 border-t border-gray-100 flex items-center justify-between text-[10px] text-gray-400">
              <span className="truncate">{item.statutoryRule}</span>
              <span className="font-mono font-medium text-gray-600 shrink-0">
                {item.daysRemaining}d {item.hoursRemaining}h
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Statutory Safeguards Accordion / Alert Footnote */}
      <div className="rounded-xl bg-gray-50 border border-gray-200/80 p-3 text-[11.5px] text-gray-600 flex items-start gap-2.5">
        <ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <p className="font-medium text-gray-900">
            Automated Statutory Risk Safeguards Active:
          </p>
          <p className="text-gray-500 leading-relaxed text-[11px]">
            <strong>Rule 88D (DRC-01C):</strong> Flags any excess claim &gt;20% over GSTR-2B. ·{" "}
            <strong>Rule 37 180-Day Rule:</strong> Triggers mandatory Table 4B(2) reversals + 18% p.a. interest tracking under Sec 50. ·{" "}
            <strong>Sec 17(5):</strong> Auto-advises on blocked motor vehicles, catering & club memberships.
          </p>
        </div>
      </div>
    </div>
  );
}
