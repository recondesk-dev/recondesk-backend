"use client";

import type { ReactNode } from "react";

// ─── Shared class tokens ─────────────────────────────────────────────────────

export const filterInputClass =
  "border border-[#E5E7EB] rounded-xl text-[13px] px-3 py-2 bg-white focus:ring-2 focus:ring-brand/20 focus:border-brand outline-none transition-all duration-150";

export const csvDownloadBtnClass =
  "inline-flex items-center justify-center gap-2 border border-[#E5E7EB] bg-white text-gray-600 text-[13px] font-medium rounded-xl px-4 py-2 hover:bg-gray-50 transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50";

export const sectionContainerClass =
  "bg-white rounded-2xl border border-[#F0F0F0] p-6 mb-6 transition-all duration-150";

export const tableWrapClass = "overflow-x-auto";

export const tableClass = "min-w-full text-left";

export const tableHeadClass =
  "bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400";

export const tableHeadCellClass = "px-4 py-3 text-left";

export const tableRowClass =
  "border-b border-[#F5F5F5] bg-white hover:bg-[#FAFAFA] transition-all duration-150";

export const tableCellClass = "px-4 py-4 align-middle";

export const tableStickyCheckboxHeadClass =
  "sticky left-0 z-10 bg-[#FAFAFA] px-4 py-3";

export const tableStickyCheckboxCellClass =
  "sticky left-0 z-10 bg-white px-4 py-4 transition-all duration-150 group-hover:bg-[#FAFAFA]";

// ─── Primitives ──────────────────────────────────────────────────────────────

export function formatINRPlain(amount: number): string {
  return amount.toLocaleString("en-IN", {
    maximumFractionDigits: 0,
  });
}

export function AmountDisplay({ amount }: { amount: number }) {
  return (
    <span className="font-semibold text-gray-900 tabular-nums">
      <span className="font-normal text-gray-400">₹</span>
      {formatINRPlain(amount)}
    </span>
  );
}

type StatAccent = "neutral" | "missed" | "risk";

const statAccentValue: Record<StatAccent, { value: string; bar: string }> = {
  neutral: { value: "text-gray-900", bar: "bg-gray-900" },
  missed: { value: "text-[#DC2626]", bar: "bg-[#DC2626]" },
  risk: { value: "text-[#D97706]", bar: "bg-[#D97706]" },
};

export function StatCard({
  label,
  value,
  accent = "neutral",
}: {
  label: string;
  value: ReactNode;
  accent?: StatAccent;
}) {
  const colors = statAccentValue[accent];
  return (
    <div className="relative flex min-w-[140px] flex-1 flex-col rounded-2xl border border-[#F0F0F0] bg-white px-5 py-4">
      <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
        {label}
      </p>
      <p className={`mt-1 text-3xl font-bold tabular-nums ${colors.value}`}>
        {value}
      </p>
      <span
        className={`absolute bottom-4 left-5 h-[3px] w-[3px] rounded-full ${colors.bar}`}
        aria-hidden
      />
    </div>
  );
}

export function SectionHeader({
  title,
  dotColor,
  amount,
  actions,
}: {
  title: string;
  dotColor: string;
  amount?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: dotColor }}
          aria-hidden
        />
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {amount != null && (
          <span className="text-xl font-bold tabular-nums" style={{ color: dotColor }}>
            {amount}
          </span>
        )}
        {actions}
      </div>
    </div>
  );
}

export function ImpactBadge({ level }: { level: "high" | "medium" | "low" }) {
  const cls = {
    high: "bg-red-50 text-red-600",
    medium: "bg-amber-50 text-amber-600",
    low: "bg-gray-100 text-gray-500",
  }[level];
  const label = level === "medium" ? "Medium" : level === "high" ? "High" : "Low";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

export type DecisionStatus = "pending" | "acted" | "ignored";

export function DecisionStatusPill({ status }: { status: DecisionStatus }) {
  if (status === "acted")
    return (
      <span className="inline-flex rounded-full bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-600">
        Done
      </span>
    );
  if (status === "ignored")
    return (
      <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-400 line-through">
        Ignored
      </span>
    );
  return (
    <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
      Pending
    </span>
  );
}

export function Rule37SeverityLabel({
  urgency,
}: {
  urgency: "CRITICAL" | "HIGH" | "MEDIUM";
}) {
  const cfg = {
    CRITICAL: { color: "text-red-600", label: "CRITICAL" },
    HIGH: { color: "text-amber-600", label: "HIGH" },
    MEDIUM: { color: "text-gray-500", label: "MEDIUM" },
  }[urgency];
  return (
    <span className={`text-[11px] font-medium ${cfg.color}`}>
      <span aria-hidden>● </span>
      {cfg.label}
    </span>
  );
}

export function rule37BorderClass(
  urgency: "CRITICAL" | "HIGH" | "MEDIUM",
  acted: boolean
): string {
  if (acted) return "border-l-[#E5E7EB]";
  if (urgency === "CRITICAL") return "border-l-[#DC2626]";
  if (urgency === "HIGH") return "border-l-[#D97706]";
  return "border-l-[#6B7280]";
}
