"use client";

import type { CSSProperties, ReactNode } from "react";

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

export const tableWrapClass = "w-full overflow-x-auto";

export const tableClass = "w-full table-auto border-collapse text-left";

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

export const topSuppliersTableClass = tableClass;

export const topSuppliersThGstin = `${tableHeadCellClass} min-w-[170px] w-[170px]`;
export const topSuppliersTdGstin = `${tableCellClass} min-w-[170px] w-[170px] overflow-visible font-mono text-[12px] text-gray-500`;
export const topSuppliersThTradeName = `${tableHeadCellClass} min-w-[180px]`;
export const topSuppliersTdTradeName = `${tableCellClass} min-w-[180px] font-medium text-gray-800 overflow-hidden text-ellipsis whitespace-nowrap`;
export const topSuppliersThInvoiceCount = `${tableHeadCellClass} min-w-[120px] w-[120px] text-center`;
export const topSuppliersTdInvoiceCount = `${tableCellClass} min-w-[120px] w-[120px] text-center text-[13px] text-gray-600 tabular-nums`;
export const topSuppliersThTotal = `${tableHeadCellClass} min-w-[140px] w-[140px] text-right`;
export const topSuppliersTdTotal = `${tableCellClass} min-w-[140px] w-[140px] text-right font-semibold`;
export const topSuppliersThImpact = `${tableHeadCellClass} min-w-[90px] w-[90px] text-right`;
export const topSuppliersTdImpact = `${tableCellClass} min-w-[90px] w-[90px] text-right`;

export const matchedTableClass = tableClass;

export const matchedThGstin = `${tableHeadCellClass} min-w-[160px] w-[160px]`;
export const matchedTdGstin = `${tableCellClass} min-w-[160px] w-[160px] overflow-visible font-mono text-[12px] text-gray-500`;
export const matchedThInvoice = `${tableHeadCellClass} min-w-[110px] w-[110px]`;
export const matchedTdInvoice = `${tableCellClass} min-w-[110px] w-[110px] font-medium text-gray-800`;
export const matchedThDate = `${tableHeadCellClass} min-w-[100px] w-[100px]`;
export const matchedTdDate = `${tableCellClass} min-w-[100px] w-[100px] text-[13px] text-gray-500`;
export const matchedThAmount = `${tableHeadCellClass} min-w-[90px] w-[90px] text-right`;
export const matchedTdAmount = `${tableCellClass} min-w-[90px] w-[90px] text-right`;
export const matchedThMatchLevel = `${tableHeadCellClass} min-w-[100px] w-[100px] text-center`;
export const matchedTdMatchLevel = `${tableCellClass} min-w-[100px] w-[100px] text-center`;
export const matchedThConfidence = `${tableHeadCellClass} min-w-[100px] w-[100px] text-center`;
export const matchedTdConfidence = `${tableCellClass} min-w-[100px] w-[100px] text-center text-[13px] text-gray-600`;
export const matchedThDiscrepancy = `${tableHeadCellClass} min-w-[150px]`;
export const matchedTdDiscrepancy = `${tableCellClass} min-w-[150px] overflow-hidden text-ellipsis whitespace-nowrap text-[13px] text-gray-600`;
export const matchedThNotes = `${tableHeadCellClass} min-w-[80px] w-[80px]`;
export const matchedTdNotes = `${tableCellClass} min-w-[80px] w-[80px]`;

export function DecisionTableColGroup({
  includeNotice = false,
}: {
  includeNotice?: boolean;
}) {
  return (
    <colgroup>
      <col style={{ width: 32 }} />
      <col style={{ width: 32 }} />
      <col style={{ width: 130 }} />
      <col style={{ width: "11%" }} />
      <col style={{ width: "10%" }} />
      <col style={{ width: 110 }} />
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
  col?: "amount" | "gstin" | "status" | string,
  opts?: { align?: "right" }
): string {
  if (col === "amount") {
    return `${tableCellClass} w-[110px] min-w-[110px] overflow-visible whitespace-nowrap text-right font-semibold`;
  }
  if (col === "gstin") {
    return `${tableCellClass} max-w-[130px] overflow-visible`;
  }
  if (col === "status") {
    return `${tableCellClass} overflow-visible whitespace-nowrap`;
  }
  return `${tableTruncateCellClass}${opts?.align === "right" ? " text-right" : ""}`;
}

// ─── Primitives ──────────────────────────────────────────────────────────────

export function formatINRPlain(amount: number): string {
  return amount.toLocaleString("en-IN", {
    maximumFractionDigits: 0,
  });
}

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
        {formatINRPlain(amount)}
      </span>
    </span>
  );
}

export function AmountDisplay({ amount }: { amount: number }) {
  return <InrAmount amount={amount} />;
}

type StatAccent = "neutral" | "matched" | "missed" | "risk";

const statAccentValue: Record<StatAccent, { value: string; dot: string }> = {
  neutral: { value: "text-gray-800", dot: "bg-gray-300" },
  matched: { value: "text-gray-800", dot: "bg-brand" },
  missed: { value: "text-gray-900", dot: "bg-red-500" },
  risk: { value: "text-gray-900", dot: "bg-amber-500" },
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
  const isCurrency = accent === "missed" || accent === "risk";
  return (
    <div
      className={`box-border flex min-w-0 w-full flex-col gap-2 overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white py-3.5 ${
        isCurrency ? "px-4" : "pl-5 pr-4"
      }`}
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
    </div>
  );
}

type SectionAmountBadgeVariant = "claim" | "risk" | "rule37";

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
};

export function SectionAmountBadge({
  label,
  amount,
  variant,
}: {
  label: string;
  amount: number;
  variant: SectionAmountBadgeVariant;
}) {
  const styles = sectionAmountBadgeStyles[variant];
  return (
    <div
      className={`inline-flex min-w-[120px] flex-col items-center justify-center rounded-2xl border px-5 py-3 ${styles.card}`}
    >
      <span
        className={`text-[10px] font-semibold uppercase tracking-widest ${styles.label}`}
      >
        {label}
      </span>
      <InrAmount
        amount={amount}
        sizeClass="whitespace-nowrap text-xl font-bold"
        numberColorClass={styles.amount}
      />
    </div>
  );
}

export function SectionHeader({
  title,
  dotColor,
  amount,
  amountLabel,
  badgeVariant = "claim",
  actions,
}: {
  title: string;
  dotColor: string;
  amount?: number;
  amountLabel?: string;
  badgeVariant?: SectionAmountBadgeVariant;
  actions?: ReactNode;
}) {
  const showRight =
    (amount != null && amountLabel != null) || actions != null;

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
        <div className="flex shrink-0 items-center gap-3">
          {amount != null && amountLabel != null && (
            <SectionAmountBadge
              label={amountLabel}
              amount={amount}
              variant={badgeVariant}
            />
          )}
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
