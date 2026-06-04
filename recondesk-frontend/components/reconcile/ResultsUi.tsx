"use client";

import type { ReactNode } from "react";

// ─── Shared class tokens ─────────────────────────────────────────────────────

export const filterInputClass =
  "border border-[#E5E7EB] rounded-xl text-[13px] px-3 py-2 bg-white focus:ring-2 focus:ring-brand/20 focus:border-brand outline-none transition-all duration-150";

export const filterRowClass = "flex flex-wrap gap-2 w-full";

export const filterAmountInputClass = `${filterInputClass} max-w-[100px] w-full min-w-0`;

export const filterDateInputClass = `${filterInputClass} max-w-[140px] w-full min-w-0`;

export const filterGstinInputClass = `${filterInputClass} min-w-[160px] flex-1`;

export const filterDropdownClass = `${filterInputClass} max-w-[160px] w-full min-w-0`;

export const csvDownloadBtnClass =
  "inline-flex shrink-0 items-center justify-center gap-2 border border-[#E5E7EB] bg-white text-gray-600 text-[13px] font-medium rounded-xl px-4 py-2 hover:bg-gray-50 transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50";

export const sectionContainerClass =
  "w-full box-border bg-white rounded-2xl border border-[#F0F0F0] p-6 mb-6 transition-all duration-150";

export const pageContentClass =
  "mx-auto box-border w-full max-w-full space-y-4 overflow-x-hidden pt-2 lg:max-w-7xl";

export const statCardsGridClass =
  "mt-4 grid w-full grid-cols-2 gap-3 border-t border-[#F0F0F0] pt-4 sm:grid-cols-4";

export const tableWrapClass = "w-full overflow-x-auto";

export const tableClass = "min-w-[800px] w-full table-fixed text-left";

export const tableHeadClass =
  "bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400";

export const tableHeadCellClass =
  "px-4 py-3 text-left overflow-hidden text-ellipsis whitespace-nowrap";

export const tableRowClass =
  "border-b border-[#F5F5F5] bg-white hover:bg-[#FAFAFA] transition-all duration-150";

export const tableCellClass = "px-4 py-4 align-middle";

export const tableTruncateCellClass =
  `${tableCellClass} overflow-hidden text-ellipsis whitespace-nowrap`;

export const tableStickyCheckboxHeadClass =
  "sticky left-0 z-10 bg-[#FAFAFA] px-4 py-3 w-10";

export const tableStickyCheckboxCellClass =
  "sticky left-0 z-10 w-10 bg-white px-4 py-4 transition-all duration-150 group-hover:bg-[#FAFAFA]";

/** Fixed column widths for ITC / risk decision tables */
export const decisionTableCol = {
  checkbox: "w-10",
  num: "w-8",
  gstin: "w-[160px]",
  invoice: "w-[110px]",
  date: "w-[100px]",
  amount: "w-[90px]",
  impact: "w-[70px]",
  what: "w-[160px]",
  why: "w-[140px]",
  next: "w-[140px]",
  status: "w-[80px]",
  notice: "w-[120px]",
} as const;

export function decisionTh(
  col: keyof typeof decisionTableCol,
  align?: "right"
): string {
  return `${tableHeadCellClass} ${decisionTableCol[col]}${align === "right" ? " text-right" : ""}`;
}

export function decisionTd(
  col: keyof typeof decisionTableCol,
  opts?: { truncate?: boolean; align?: "right" }
): string {
  const truncate =
    opts?.truncate ??
    (col === "what" ||
      col === "why" ||
      col === "next" ||
      col === "gstin" ||
      col === "invoice");
  const base = truncate ? tableTruncateCellClass : tableCellClass;
  return `${base} ${decisionTableCol[col]}${opts?.align === "right" ? " text-right" : ""}`;
}

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

type StatAccent = "neutral" | "matched" | "missed" | "risk";

const statAccentValue: Record<StatAccent, { value: string; dot: string }> = {
  neutral: { value: "text-gray-900", dot: "bg-gray-300" },
  matched: { value: "text-gray-900", dot: "bg-brand" },
  missed: { value: "text-[#DC2626]", dot: "bg-red-500" },
  risk: { value: "text-[#D97706]", dot: "bg-amber-500" },
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
    <div className="relative flex min-w-0 flex-col overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white px-5 py-4">
      <span
        className={`absolute top-3 left-3 h-2 w-2 rounded-full ${colors.dot}`}
        aria-hidden
      />
      <p className="truncate text-[11px] font-medium uppercase tracking-widest text-gray-400">
        {label}
      </p>
      <p
        className={`mt-1 truncate text-3xl font-bold tabular-nums ${colors.value}`}
      >
        {value}
      </p>
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
    <div className="mb-5 flex w-full flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: dotColor }}
          aria-hidden
        />
        <h2 className="min-w-0 truncate text-lg font-semibold text-gray-900">
          {title}
        </h2>
        {amount != null && (
          <span
            className="shrink-0 text-xl font-bold tabular-nums"
            style={{ color: dotColor }}
          >
            {amount}
          </span>
        )}
      </div>
      {actions != null && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
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
