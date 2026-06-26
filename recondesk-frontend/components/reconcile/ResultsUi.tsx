"use client";

import type { CSSProperties, ReactNode } from "react";

import { formatINRNumber } from "@/lib/format";

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
  "box-border w-full max-w-full space-y-4 overflow-x-hidden px-8 pt-2";

export const statCardsGridClass =
  "mt-4 grid w-full min-w-0 grid-cols-2 gap-3 border-t border-[#F0F0F0] pt-4 md:[grid-template-columns:repeat(4,minmax(0,1fr))]";

export const statCardValueClass = "text-xl font-semibold tabular-nums";

export const tableWrapClass = "w-full min-w-0 overflow-x-hidden";

export const tableClass = "w-full table-auto border-collapse text-left";

export const decisionTableWrapClass = tableWrapClass;

export const decisionTableClass =
  "w-full table-fixed border-collapse text-left";

export const tableHeadClass =
  "bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400";

export const tableHeadCellClass =
  "px-4 py-3 text-left overflow-hidden text-ellipsis whitespace-nowrap";

export const tableRowClass =
  "border-b border-[#F5F5F5] bg-white hover:bg-[#FAFAFA] transition-all duration-150";

export const tableCellClass = "px-4 py-3 align-middle";

export const tableTruncateCellClass =
  `${tableCellClass} overflow-hidden text-ellipsis whitespace-nowrap`;

export const tableStickyCheckboxHeadClass =
  "sticky left-0 z-10 w-8 bg-[#FAFAFA] px-3 py-3";

export const tableStickyCheckboxCellClass =
  "sticky left-0 z-10 w-8 bg-white px-3 py-3 transition-all duration-150 group-hover:bg-[#FAFAFA]";

export const topSuppliersTableClass = decisionTableClass;

export const topSuppliersThGstin = `${tableHeadCellClass} w-[18%]`;
export const topSuppliersTdGstin = `${tableCellClass} max-w-0 overflow-visible font-mono text-[12px] text-gray-500`;
export const topSuppliersThTradeName = `${tableHeadCellClass} w-[32%]`;
export const topSuppliersTdTradeName = `${tableCellClass} max-w-0 overflow-visible`;
export const topSuppliersThInvoiceCount = `${tableHeadCellClass} w-[14%] text-center`;
export const topSuppliersTdInvoiceCount = `${tableCellClass} text-center text-[13px] text-gray-600 tabular-nums`;
export const topSuppliersThTotal = `${tableHeadCellClass} w-[22%] text-right`;
export const topSuppliersTdTotal = `${tableCellClass} text-right font-semibold`;
export const topSuppliersThImpact = `${tableHeadCellClass} w-[14%] text-right`;
export const topSuppliersTdImpact = `${tableCellClass} text-right`;

export const matchedTableClass = decisionTableClass;

export const matchedThGstin = `${tableHeadCellClass} w-[16%]`;
export const matchedTdGstin = `${tableCellClass} max-w-0 overflow-visible font-mono text-[12px] text-gray-500`;
export const matchedThInvoice = `${tableHeadCellClass} w-[12%]`;
export const matchedTdInvoice = `${tableCellClass} max-w-0 overflow-visible`;
export const matchedThDate = `${tableHeadCellClass} w-[10%]`;
export const matchedTdDate = `${tableCellClass} text-[13px] text-gray-500`;
export const matchedThAmount = `${tableHeadCellClass} w-[10%] text-right`;
export const matchedTdAmount = `${tableCellClass} text-right`;
export const matchedThMatchLevel = `${tableHeadCellClass} w-[10%] text-center`;
export const matchedTdMatchLevel = `${tableCellClass} text-center`;
export const matchedThConfidence = `${tableHeadCellClass} w-[10%] text-center`;
export const matchedTdConfidence = `${tableCellClass} text-center text-[13px] text-gray-600`;
export const matchedThDiscrepancy = `${tableHeadCellClass} w-[22%]`;
export const matchedTdDiscrepancy = `${tableCellClass} max-w-0 overflow-visible text-[13px] text-gray-600`;
export const matchedThNotes = `${tableHeadCellClass} w-[10%]`;
export const matchedTdNotes = `${tableCellClass}`;

export function DecisionTableColGroup({
  includeNotice = false,
}: {
  includeNotice?: boolean;
}) {
  return (
    <colgroup>
      <col style={{ width: 40 }} />
      <col style={{ width: 36 }} />
      <col style={{ width: "11%" }} />
      <col style={{ width: "9%" }} />
      <col style={{ width: "8%" }} />
      <col style={{ width: "8%" }} />
      <col style={{ width: "6%" }} />
      <col style={{ width: includeNotice ? "13%" : "15%" }} />
      <col style={{ width: includeNotice ? "12%" : "14%" }} />
      <col style={{ width: includeNotice ? "11%" : "13%" }} />
      <col style={{ width: includeNotice ? "7%" : "8%" }} />
      {includeNotice ? <col style={{ width: "10%" }} /> : null}
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
  col?: "amount" | "gstin" | "status" | string,
  opts?: { align?: "right" }
): string {
  if (col === "amount") {
    return `${tableCellClass} w-[110px] min-w-[110px] overflow-visible whitespace-nowrap text-right font-semibold`;
  }
  if (col === "gstin") {
    return `${tableCellClass} max-w-0 overflow-visible`;
  }
  if (col === "status" || col === "notice") {
    return `${tableCellClass} overflow-visible whitespace-nowrap`;
  }
  if (
    col === "invoice" ||
    col === "what" ||
    col === "why" ||
    col === "next" ||
    col === "num" ||
    col === "date"
  ) {
    return `${tableTruncateCellClass} max-w-0 overflow-visible${
      opts?.align === "right" ? " text-right" : ""
    }`;
  }
  return `${tableTruncateCellClass} max-w-0${opts?.align === "right" ? " text-right" : ""}`;
}

// ─── Primitives ──────────────────────────────────────────────────────────────

export function InrAmount({
  amount,
  sizeClass = "text-[13px] font-semibold",
  numberColorClass = "text-gray-900",
  numberStyle,
}: {
  amount: number;
  sizeClass?: string;
  numberColorClass?: string;
  numberStyle?: CSSProperties;
}) {
  return (
    <span className={`inline-flex tabular-nums ${sizeClass}`}>
      <span className={`text-gray-400 ${sizeClass}`}>₹</span>
      <span className={numberColorClass} style={numberStyle}>
        {formatINRNumber(amount)}
      </span>
    </span>
  );
}

export function AmountDisplay({ amount }: { amount: number }) {
  return <InrAmount amount={amount} />;
}

type StatAccent =
  | "neutral"
  | "matched"
  | "missed"
  | "risk"
  | "saved"
  | "reversed"
  | "pending"
  | "review_required"
  | "linked";

const statAccentValue: Record<
  StatAccent,
  { value: string; dot: string; card?: string }
> = {
  neutral: { value: "text-gray-800", dot: "bg-gray-300" },
  matched: { value: "text-gray-800", dot: "bg-brand" },
  missed: { value: "text-gray-900", dot: "bg-red-500" },
  risk: { value: "text-gray-900", dot: "bg-amber-500" },
  saved: {
    value: "text-green-700",
    dot: "bg-green-500",
    card: "bg-green-50 border-green-100",
  },
  reversed: {
    value: "text-red-600",
    dot: "bg-red-500",
    card: "bg-red-50 border-red-100",
  },
  pending: {
    value: "text-amber-700",
    dot: "bg-amber-500",
    card: "bg-amber-50 border-amber-100",
  },
  review_required: {
    value: "text-[#B45309]",
    dot: "bg-[#F59E0B]",
    card: "bg-white border-[#F0F0F0] border-l-4 border-l-[#F59E0B]",
  },
  linked: {
    value: "text-[#5B41C7]",
    dot: "bg-[#7B5CFA]",
    card: "bg-white border-[#F0F0F0] border-l-4 border-l-[#7B5CFA]",
  },
};

export function StatCard({
  label,
  value,
  accent = "neutral",
  subtext,
}: {
  label: string;
  value: ReactNode;
  accent?: StatAccent;
  subtext?: string;
}) {
  const colors = statAccentValue[accent];
  const isCurrency =
    accent === "missed" ||
    accent === "risk" ||
    accent === "saved" ||
    accent === "reversed" ||
    accent === "pending" ||
    accent === "neutral";
  return (
    <div
      className={`box-border flex min-w-0 w-full flex-col gap-2 overflow-hidden rounded-2xl border py-3.5 ${
        colors.card ?? "border-[#F0F0F0] bg-white"
      } ${isCurrency ? "px-4" : "pl-5 pr-4"}`}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${colors.dot}`}
          aria-hidden
        />
        <p className="min-w-0 truncate text-[11px] font-medium uppercase tracking-widest text-gray-900">
          {label}
        </p>
      </div>
      <div
        className={`min-w-0 truncate ${
          isCurrency ? "" : `${statCardValueClass} ${colors.value}`
        }`}
      >
        {value}
      </div>
      {subtext && (
        <p className="truncate text-[11px] text-gray-400">{subtext}</p>
      )}
    </div>
  );
}

type SectionAmountBadgeVariant = "claim" | "risk" | "rule37" | "neutral";

const sectionAmountBadgeStyles: Record<
  SectionAmountBadgeVariant,
  { card: string; label: string; amount: string }
> = {
  claim: {
    card: "bg-green-50 border-green-100",
    label: "text-green-500",
    amount: "text-green-700",
  },
  risk: {
    card: "bg-red-50 border-red-100",
    label: "text-red-400",
    amount: "text-red-600",
  },
  rule37: {
    card: "bg-amber-50 border-amber-100",
    label: "text-amber-500",
    amount: "text-amber-700",
  },
  neutral: {
    card: "bg-gray-50 border-gray-200",
    label: "text-gray-500",
    amount: "text-gray-800",
  },
};

export function SectionAmountBadge({
  label,
  amount,
  variant,
  sublabel,
}: {
  label: string;
  amount: number;
  variant: SectionAmountBadgeVariant;
  sublabel?: string;
}) {
  const styles = sectionAmountBadgeStyles[variant];
  return (
    <div
      className={`inline-flex min-w-[120px] flex-col items-center justify-center rounded-2xl border px-5 py-3 ${styles.card}`}
    >
      <span
        className={`text-center text-[10px] font-semibold uppercase tracking-widest ${styles.label}`}
      >
        {label}
      </span>
      <InrAmount
        amount={amount}
        sizeClass="whitespace-nowrap text-xl font-bold"
        numberColorClass={styles.amount}
      />
      {sublabel ? (
        <span className="mt-1 text-center text-[10px] text-gray-500">
          {sublabel}
        </span>
      ) : null}
    </div>
  );
}

export type SectionHeaderBadge = {
  label: string;
  amount: number;
  variant: SectionAmountBadgeVariant;
  sublabel?: string;
};

export function SectionHeader({
  title,
  dotColor,
  amount,
  amountLabel,
  badgeVariant = "claim",
  badges,
  actions,
}: {
  title: string;
  dotColor: string;
  amount?: number;
  amountLabel?: string;
  badgeVariant?: SectionAmountBadgeVariant;
  badges?: SectionHeaderBadge[];
  actions?: ReactNode;
}) {
  const resolvedBadges: SectionHeaderBadge[] =
    badges ??
    (amount != null && amountLabel != null
      ? [{ label: amountLabel, amount, variant: badgeVariant }]
      : []);
  const showRight = resolvedBadges.length > 0 || actions != null;

  return (
    <div className="mb-5 flex w-full items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: dotColor }}
          aria-hidden
        />
        <h2 className="min-w-0 truncate text-lg font-semibold text-gray-900">
          {title}
        </h2>
      </div>
      {showRight && (
        <div className="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
          {resolvedBadges.length > 0 ? (
            <div className="flex flex-wrap items-stretch justify-end gap-3">
              {resolvedBadges.map((badge) => (
                <SectionAmountBadge
                  key={badge.label}
                  label={badge.label}
                  amount={badge.amount}
                  variant={badge.variant}
                  sublabel={badge.sublabel}
                />
              ))}
            </div>
          ) : null}
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

export type ResultsBucketTabId =
  | "matched"
  | "risk"
  | "itc"
  | "rule37"
  | "gstr3b"
  | "followup";

const RESULTS_BUCKET_TABS: { id: ResultsBucketTabId; label: string }[] = [
  { id: "matched", label: "Matched" },
  { id: "risk", label: "ITC at Risk" },
  { id: "itc", label: "Missed ITC" },
  { id: "rule37", label: "Rule 37" },
  { id: "gstr3b", label: "GSTR-3B Check" },
  { id: "followup", label: "Follow-up Log" },
];

export function ResultsBucketTabs({
  active,
  onChange,
  rightContent,
}: {
  active: ResultsBucketTabId;
  onChange: (tab: ResultsBucketTabId) => void;
  rightContent?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col sm:flex-row sm:items-end justify-between border-b border-[#F0F0F0] gap-4">
      <nav
        className="flex flex-wrap gap-1"
        role="tablist"
        aria-label="Reconciliation results"
      >
      {RESULTS_BUCKET_TABS.map(({ id, label }) => {
        const isActive = active === id;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={
              isActive
                ? "-mb-px border-b-2 border-brand px-4 py-2.5 text-[13px] font-medium text-gray-900"
                : "px-4 py-2.5 text-[13px] font-medium text-gray-500 transition-colors hover:text-gray-800"
            }
            onClick={() => onChange(id)}
          >
            {label}
          </button>
        );
      })}
      </nav>
      {rightContent && <div className="mb-1">{rightContent}</div>}
    </div>
  );
}
