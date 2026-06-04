"use client";

import type { ReactNode } from "react";

// ─── Shared class tokens ─────────────────────────────────────────────────────

export const filterInputClass =
  "border border-[#E5E7EB] rounded-xl text-[13px] px-3 py-2 bg-white focus:ring-2 focus:ring-brand/20 focus:border-brand outline-none transition-all duration-150";

export const filterRowClass =
  "flex w-full flex-wrap items-center gap-2 md:flex-nowrap";

export const filterAmountInputClass = `${filterInputClass} w-[90px] shrink-0`;

export const filterDateInputClass = `${filterInputClass} w-[130px] shrink-0`;

export const filterGstinInputClass = `${filterInputClass} min-w-[120px] max-w-full flex-1`;

export const filterDropdownClass = `${filterInputClass} w-[140px] shrink-0`;

export const csvDownloadBtnClass =
  "inline-flex shrink-0 items-center justify-center gap-2 border border-[#E5E7EB] bg-white text-gray-600 text-[13px] font-medium rounded-xl px-4 py-2 hover:bg-gray-50 transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50";

export const sectionContainerClass =
  "mb-6 box-border w-full max-w-full rounded-2xl border border-[#F0F0F0] bg-white p-6 transition-all duration-150";

export const pageContentClass =
  "box-border w-full max-w-full space-y-4 overflow-x-hidden px-6 pt-2";

export const statCardsGridClass =
  "mt-4 grid w-full min-w-0 grid-cols-2 gap-3 border-t border-[#F0F0F0] pt-4 md:[grid-template-columns:repeat(4,minmax(0,1fr))]";

export const tableWrapClass = "w-full overflow-x-auto";

export const tableClass =
  "w-full min-w-[700px] table-fixed border-collapse text-left";

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
  "sticky left-0 z-10 w-8 bg-[#FAFAFA] px-2 py-3";

export const tableStickyCheckboxCellClass =
  "sticky left-0 z-10 w-8 bg-white px-2 py-4 transition-all duration-150 group-hover:bg-[#FAFAFA]";

export function DecisionTableColGroup({
  includeNotice = false,
}: {
  includeNotice?: boolean;
}) {
  return (
    <colgroup>
      <col style={{ width: 32 }} />
      <col style={{ width: 32 }} />
      <col style={{ width: "15%" }} />
      <col style={{ width: "11%" }} />
      <col style={{ width: "10%" }} />
      <col style={{ width: "9%" }} />
      <col style={{ width: "7%" }} />
      <col style={{ width: "16%" }} />
      <col style={{ width: "13%" }} />
      <col style={{ width: "14%" }} />
      {includeNotice ? (
        <>
          <col style={{ width: "8%" }} />
          <col />
        </>
      ) : (
        <col />
      )}
    </colgroup>
  );
}

export function decisionTh(
  _col?: string,
  align?: "right"
): string {
  return `${tableHeadCellClass}${align === "right" ? " text-right" : ""}`;
}

export function decisionTd(
  _col?: string,
  opts?: { align?: "right" }
): string {
  return `${tableTruncateCellClass}${opts?.align === "right" ? " text-right" : ""}`;
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
  neutral: { value: "text-gray-800", dot: "bg-gray-300" },
  matched: { value: "text-gray-800", dot: "bg-brand" },
  missed: { value: "text-[#E05252]", dot: "bg-red-500" },
  risk: { value: "text-[#E09A3A]", dot: "bg-amber-500" },
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
    <div className="relative box-border flex min-w-0 w-full flex-col overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white px-5 py-4">
      <span
        className={`absolute left-3 top-3 h-1.5 w-1.5 rounded-full ${colors.dot}`}
        aria-hidden
      />
      <p className="truncate text-[11px] font-medium uppercase tracking-widest text-gray-300">
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
    <div className="mb-5 flex w-full flex-nowrap items-center justify-between gap-3">
      <div className="flex min-w-0 shrink items-center gap-2">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: dotColor }}
          aria-hidden
        />
        <h2 className="min-w-0 truncate text-lg font-semibold text-gray-900">
          {title}
        </h2>
      </div>
      {amount != null && (
        <span
          className="shrink-0 text-xl font-bold tabular-nums"
          style={{ color: dotColor }}
        >
          {amount}
        </span>
      )}
      {actions != null && (
        <div className="flex shrink-0 items-center gap-2 whitespace-nowrap">
          {actions}
        </div>
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
